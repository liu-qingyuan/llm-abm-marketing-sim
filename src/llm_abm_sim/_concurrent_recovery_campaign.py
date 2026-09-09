"""Study-owned durable campaign storage; not an authorization Interface.

Only the verified recovery execution path may supply a campaign identity. The
Operator holds a source-bound lock for the entire invocation; a lock or storage
handle never grants permission to call a Provider. No legacy evidence is written.
"""
from __future__ import annotations

import fcntl
import os
import stat
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, cast

from . import concurrent_robustness_formal_execution as _formal
from . import concurrent_robustness_recovery as _proposals
from . import concurrent_robustness_recovery_epoch as _epoch
from . import concurrent_robustness_v2 as _v2


class RecoveryCampaignError(ValueError):
    """The source claim, durable history, or invocation ownership is invalid."""


_held: ContextVar[tuple[Path, int, int, int] | None] = ContextVar("recovery_source_lock", default=None)


def _paths(identity: Mapping[str, Any]) -> tuple[Path, Path]:
    anchor = _proposals._safe_path(identity["source_anchor_path"])
    root = _proposals._safe_path(identity["control_root"])
    _v2._require_sha256(identity["campaign_identity_sha256"], "campaign identity")
    if anchor == root or anchor.is_relative_to(root) or root.is_relative_to(anchor):
        raise RecoveryCampaignError("Recovery control and source anchor overlap")
    if not anchor.parent.is_dir() or not root.parent.is_dir():
        raise RecoveryCampaignError("Recovery scope requires existing real parents")
    return anchor, root


def _lock_path(anchor: Path) -> Path:
    return anchor.with_name(f"{anchor.name}.lock")


def _require_scope(identity: Mapping[str, Any]) -> None:
    anchor, _ = _paths(identity)
    held = _held.get()
    if held is None or held[0] != anchor or held[2:] != (os.getpid(), threading.get_ident()):
        raise RecoveryCampaignError("Study requires the live source-bound Operator lock")
    try:
        current = _lock_path(anchor).lstat()
        descriptor = os.fstat(held[1])
    except OSError as error:
        raise RecoveryCampaignError("Recovery lock descriptor is no longer live") from error
    if (
        not stat.S_ISREG(current.st_mode) or not stat.S_ISREG(descriptor.st_mode)
        or current.st_dev != descriptor.st_dev or current.st_ino != descriptor.st_ino
        or current.st_nlink != 1 or descriptor.st_nlink != 1 or current.st_size != 0 or descriptor.st_size != 0
    ):
        raise RecoveryCampaignError("Recovery lock identity changed during invocation")


@contextmanager
def recovery_scope(identity: Mapping[str, Any]) -> Iterator[None]:
    """Hold the local source lock without reading credentials or granting slots."""
    anchor, _ = _paths(identity)
    if _held.get() is not None:
        raise RecoveryCampaignError("Recovery invocation scopes cannot be nested")
    lock = _proposals._safe_path(_lock_path(anchor))
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    token = None
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RecoveryCampaignError("Recovery source is already in use") from error
        token = _held.set((anchor, descriptor, os.getpid(), threading.get_ident()))
        _require_scope(identity)
        yield
    finally:
        if token is not None:
            _held.reset(token)
        os.close(descriptor)


def _read(path: Path) -> dict[str, Any]:
    fact = _proposals._file_fact(path)
    if cast(int, fact["mode"]) & 0o222:
        raise RecoveryCampaignError("Recovery durable records must be immutable")
    try:
        document, _ = _formal._load_canonical_object(path, "recovery record")
    except _formal.ConcurrentRobustnessFormalPreflightError as exc:
        raise RecoveryCampaignError("Recovery durable record is malformed") from exc
    return document


def _owner(identity: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "concurrent-recovery-source-owner-v1",
        "campaign_identity_sha256": identity["campaign_identity_sha256"],
        "control_root": identity["control_root"],
        "source_anchor_path": identity["source_anchor_path"],
    }


def _equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return _formal._canonical_json_bytes(left) == _formal._canonical_json_bytes(right)


class CampaignJournal:
    """One immutable event chain and checked monotonic head per claimed source.

    Admission, attempts and accounting are validated by the Study's recovery
    state machine before append. Every append requires the original live lock.
    Incomplete publication is rejected; it is never repaired or truncated.
    """

    def __init__(self, identity: Mapping[str, Any], records: tuple[dict[str, Any], ...]) -> None:
        self.identity = dict(identity)
        self._records = list(records)
        _, self.root = _paths(identity)
        self.head = records[-1]["record_sha256"] if records else identity["campaign_identity_sha256"]

    @property
    def records(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._records)

    @classmethod
    def open(cls, identity: Mapping[str, Any]) -> CampaignJournal:
        _require_scope(identity)
        anchor, root = _paths(identity)
        owner = _owner(identity)
        if not anchor.exists():
            if root.exists():
                raise RecoveryCampaignError("Unclaimed recovery control scope already exists")
            _epoch._publish_immutable(anchor, owner)
            root.mkdir()
            (root / "events").mkdir()
            (root / "invocations").mkdir()
            (root / "bundles").mkdir()
            _epoch._publish_immutable(root / "identity.json", dict(identity))
            _epoch._publish_immutable(root / "HEAD", {
                "sequence": 0, "record_sha256": identity["campaign_identity_sha256"],
            })
            _v2._fsync_directory(root.parent)
        elif not _equal(_read(anchor), owner):
            raise RecoveryCampaignError("Source is already bound to another recovery campaign")
        return cls.read(identity)

    @classmethod
    def read(cls, identity: Mapping[str, Any]) -> CampaignJournal:
        """Read a stable complete chain; no creation, lock, mutation or repair."""
        anchor, root = _paths(identity)
        if not _equal(_read(anchor), _owner(identity)):
            raise RecoveryCampaignError("Recovery source owner is crossed")
        if {p.name for p in root.iterdir()} != {"identity.json", "events", "HEAD", "invocations", "bundles"}:
            raise RecoveryCampaignError("Recovery control inventory is incomplete or crossed")
        if not _equal(_read(root / "identity.json"), dict(identity)):
            raise RecoveryCampaignError("Recovery control identity is crossed")
        for directory in ("invocations", "bundles"):
            if not _proposals._safe_path(root / directory).is_dir():
                raise RecoveryCampaignError("Recovery child scope is not a real directory")
        events = _proposals._safe_path(root / "events")
        if not events.is_dir():
            raise RecoveryCampaignError("Recovery events must be a dedicated directory")
        head_before = _read(root / "HEAD")
        sequence = head_before.get("sequence")
        if type(sequence) is not int or sequence < 0 or set(head_before) != {"sequence", "record_sha256"}:
            raise RecoveryCampaignError("Recovery head is malformed")
        if sorted(p.name for p in events.iterdir()) != [f"{n:08d}.json" for n in range(1, sequence + 1)]:
            raise RecoveryCampaignError("Recovery chain contains an orphan, gap or truncated tail")
        records: list[dict[str, Any]] = []
        previous = identity["campaign_identity_sha256"]
        for number in range(1, sequence + 1):
            row = _read(events / f"{number:08d}.json")
            if set(row) != {"schema_version", "campaign_identity_sha256", "sequence", "previous_sha256", "kind", "payload", "recorded_at_utc", "record_sha256"}:
                raise RecoveryCampaignError("Recovery event fields are not exact")
            body = {key: value for key, value in row.items() if key != "record_sha256"}
            if (
                row["schema_version"] != "concurrent-recovery-campaign-event-v1"
                or row["campaign_identity_sha256"] != identity["campaign_identity_sha256"]
                or type(row["sequence"]) is not int or row["sequence"] != number
                or row["previous_sha256"] != previous
                or not isinstance(row["kind"], str) or not isinstance(row["payload"], dict)
                or row["record_sha256"] != _v2._json_sha256(body)
            ):
                raise RecoveryCampaignError("Recovery event chain or checksum is crossed")
            instant = _formal._parse_utc(row["recorded_at_utc"], "recovery event time")
            if records and instant < _formal._parse_utc(records[-1]["recorded_at_utc"], "previous recovery event time"):
                raise RecoveryCampaignError("Recovery event clock moved backwards")
            previous = row["record_sha256"]
            records.append(row)
        if previous != head_before["record_sha256"] or not _equal(_read(root / "HEAD"), head_before):
            raise RecoveryCampaignError("Recovery head moved or differs from durable events")
        return cls(identity, tuple(records))

    def append(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        _require_scope(self.identity)
        if not _equal(_read(self.root / "HEAD"), {"sequence": len(self._records), "record_sha256": self.head}):
            raise RecoveryCampaignError("Recovery append uses a stale head")
        number = len(self._records) + 1
        timestamp = _formal._utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
        if self._records and timestamp < self._records[-1]["recorded_at_utc"]:
            raise RecoveryCampaignError("Recovery event clock moved backwards")
        body = {
            "schema_version": "concurrent-recovery-campaign-event-v1",
            "campaign_identity_sha256": self.identity["campaign_identity_sha256"],
            "sequence": number, "previous_sha256": self.head, "kind": kind, "payload": payload,
            "recorded_at_utc": timestamp,
        }
        row = {**body, "record_sha256": _v2._json_sha256(body)}
        _epoch._publish_immutable(self.root / "events" / f"{number:08d}.json", row)
        pending = self.root / f".HEAD-{number:08d}.pending"
        with pending.open("xb") as handle:
            handle.write(_formal._canonical_json_bytes({"sequence": number, "record_sha256": row["record_sha256"]}))
            handle.flush()
            os.fsync(handle.fileno())
        pending.chmod(0o444)
        os.replace(pending, self.root / "HEAD")
        _v2._fsync_directory(self.root)
        self._records.append(row)
        self.head = row["record_sha256"]
        return row
