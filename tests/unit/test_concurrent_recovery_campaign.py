"""Study-owned campaign storage contracts; synthetic inputs, no Provider."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from llm_abm_sim import _concurrent_recovery_campaign as campaign


def _identity(tmp_path: Path) -> dict[str, Any]:
    return {
        "campaign_identity_sha256": "a" * 64,
        "source_anchor_path": str(tmp_path / "source-campaign.json"),
        "control_root": str(tmp_path / "control"),
    }


def test_campaign_scope_claim_is_exclusive_and_does_not_accept_another_root(tmp_path: Path) -> None:
    identity = _identity(tmp_path)
    with campaign.recovery_scope(identity):
        journal = campaign.CampaignJournal.open(identity)
        assert journal.head == "a" * 64
        assert journal.records == ()
        with pytest.raises(campaign.RecoveryCampaignError):
            with campaign.recovery_scope(identity):
                pass
    assert (tmp_path / "source-campaign.json").exists()
    other = copy.deepcopy(identity)
    other["campaign_identity_sha256"] = "b" * 64
    other["control_root"] = str(tmp_path / "other-control")
    with campaign.recovery_scope(other):
        with pytest.raises(campaign.RecoveryCampaignError):
            campaign.CampaignJournal.open(other)
    assert not (tmp_path / "other-control").exists()
    with pytest.raises(campaign.RecoveryCampaignError):
        campaign.CampaignJournal.open(identity)


def test_campaign_chain_survives_reopen_and_rejects_stale_writers_and_tail_loss(tmp_path: Path) -> None:
    identity = _identity(tmp_path)
    with campaign.recovery_scope(identity):
        journal = campaign.CampaignJournal.open(identity)
        stale = campaign.CampaignJournal.open(identity)
        row = journal.append("epoch_admitted", {"epoch": 1})
        assert row["sequence"] == 1
        assert row["previous_sha256"] == "a" * 64
        with pytest.raises(campaign.RecoveryCampaignError):
            stale.append("epoch_admitted", {"epoch": 1})
    reopened = campaign.CampaignJournal.read(identity)
    assert reopened.head == row["record_sha256"]
    assert reopened.records == (row,)
    (tmp_path / "control/events/00000001.json").unlink()
    with pytest.raises(campaign.RecoveryCampaignError):
        campaign.CampaignJournal.read(identity)
