"""Crash and collision contracts for the private recovery campaign store."""
from __future__ import annotations

import multiprocessing
import os
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Any

import pytest

from llm_abm_sim import _concurrent_recovery_campaign as campaign


def _identity(tmp_path: Path, *, digest: str = "a" * 64, root_name: str = "control") -> dict[str, Any]:
    return {
        "campaign_identity_sha256": digest,
        "source_anchor_path": str(tmp_path / "source-campaign.json"),
        "control_root": str(tmp_path / root_name),
    }


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _rewrite_bytes(path: Path, payload: bytes) -> None:
    mode = path.stat().st_mode & 0o777
    path.chmod(0o600)
    try:
        path.write_bytes(payload)
    finally:
        path.chmod(mode)


def _try_scope_in_child(identity: dict[str, Any], sender: Any) -> None:
    try:
        with campaign.recovery_scope(identity):
            sender.send(("acquired", None))
    except campaign.RecoveryCampaignError as error:
        sender.send(("denied", type(error).__name__))
    finally:
        sender.close()


def _assert_child_finished(process: BaseProcess, receiver: Any) -> tuple[str, str | None]:
    try:
        assert receiver.poll(5), "child did not report its lock result"
        result = receiver.recv()
        process.join(5)
        assert not process.is_alive(), "child did not exit after reporting its lock result"
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
        process.join(5)
    assert process.exitcode == 0
    return result


def test_same_source_anchor_cannot_bind_a_different_control_root(tmp_path: Path) -> None:
    identity = _identity(tmp_path)
    with campaign.recovery_scope(identity):
        campaign.CampaignJournal.open(identity)

    foreign = _identity(tmp_path, digest="b" * 64, root_name="foreign-control")
    with campaign.recovery_scope(foreign):
        with pytest.raises(campaign.RecoveryCampaignError):
            campaign.CampaignJournal.open(foreign)
    assert not Path(foreign["control_root"]).exists()


def test_second_process_cannot_acquire_a_held_source_scope(tmp_path: Path) -> None:
    identity = _identity(tmp_path)
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_try_scope_in_child, args=(identity, sender))

    with campaign.recovery_scope(identity):
        process.start()
        sender.close()
        result = _assert_child_finished(process, receiver)

    assert result == ("denied", "RecoveryCampaignError")


def test_replaced_lock_inode_invalidates_the_held_scope(tmp_path: Path) -> None:
    identity = _identity(tmp_path)
    lock = Path(identity["source_anchor_path"]).with_name("source-campaign.json.lock")
    replacement = tmp_path / "replacement.lock"

    with campaign.recovery_scope(identity):
        journal = campaign.CampaignJournal.open(identity)
        replacement.write_bytes(b"")
        replacement.chmod(0o600)
        os.replace(replacement, lock)

        with pytest.raises(campaign.RecoveryCampaignError, match="identity changed"):
            journal.append("synthetic", {"attempt": 1})
        assert not (Path(identity["control_root"]) / "events/00000001.json").exists()


def test_durable_event_with_failed_head_publish_is_an_unrepairable_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _identity(tmp_path)
    with campaign.recovery_scope(identity):
        journal = campaign.CampaignJournal.open(identity)
        root = Path(identity["control_root"])

        def fail_head_publish(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
            raise OSError("simulated HEAD publication crash")

        monkeypatch.setattr(campaign.os, "replace", fail_head_publish)
        with pytest.raises(OSError, match="HEAD publication crash"):
            journal.append("synthetic", {"attempt": 1})

        event = root / "events/00000001.json"
        pending = root / ".HEAD-00000001.pending"
        assert event.is_file()
        assert pending.is_file()
        assert (root / "HEAD").read_bytes() == b'{"record_sha256":"' + (b"a" * 64) + b'","sequence":0}\n'
        before_read = _snapshot(root)
        with pytest.raises(campaign.RecoveryCampaignError):
            campaign.CampaignJournal.read(identity)
        assert _snapshot(root) == before_read


@pytest.mark.parametrize("corruption", ["missing", "truncated", "crossed-head"])
def test_independent_read_refuses_corrupt_chain_without_repair(
    tmp_path: Path, corruption: str,
) -> None:
    identity = _identity(tmp_path)
    with campaign.recovery_scope(identity):
        journal = campaign.CampaignJournal.open(identity)
        journal.append("synthetic", {"attempt": 1})

    root = Path(identity["control_root"])
    event = root / "events/00000001.json"
    if corruption == "missing":
        event.unlink()
    elif corruption == "truncated":
        _rewrite_bytes(event, b'{"schema_version":')
    else:
        _rewrite_bytes(root / "HEAD", b'{"record_sha256":"' + (b"b" * 64) + b'","sequence":1}\n')

    before_read = _snapshot(root)
    with pytest.raises(campaign.RecoveryCampaignError):
        campaign.CampaignJournal.read(identity)
    assert _snapshot(root) == before_read


def test_foreign_event_pending_collision_is_never_overwritten_or_removed(tmp_path: Path) -> None:
    identity = _identity(tmp_path)
    with campaign.recovery_scope(identity):
        journal = campaign.CampaignJournal.open(identity)
        pending = Path(identity["control_root"]) / "events/.00000001.json.pending"
        foreign = b"foreign event writer\n"
        pending.write_bytes(foreign)
        pending.chmod(0o444)

        with pytest.raises(FileExistsError):
            journal.append("synthetic", {"attempt": 1})
        assert pending.read_bytes() == foreign
        assert not (pending.parent / "00000001.json").exists()


def test_foreign_head_pending_collision_is_never_overwritten_or_removed(tmp_path: Path) -> None:
    identity = _identity(tmp_path)
    with campaign.recovery_scope(identity):
        journal = campaign.CampaignJournal.open(identity)
        root = Path(identity["control_root"])
        pending = root / ".HEAD-00000001.pending"
        foreign = b"foreign HEAD writer\n"
        pending.write_bytes(foreign)
        pending.chmod(0o444)
        head_before = (root / "HEAD").read_bytes()

        with pytest.raises(FileExistsError):
            journal.append("synthetic", {"attempt": 1})
        assert pending.read_bytes() == foreign
        assert (root / "HEAD").read_bytes() == head_before
        assert (root / "events/00000001.json").is_file()
