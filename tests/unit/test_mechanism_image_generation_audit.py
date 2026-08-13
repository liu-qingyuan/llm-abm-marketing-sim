from __future__ import annotations

import copy
import importlib.util
import json
import shutil
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ASSET_ROOT = _REPO_ROOT / "src" / "llm_abm_sim" / "report_assets"
_AUDIT_PATH = _ASSET_ROOT / "mechanism-image-generation-audit.json"
_VALIDATOR_PATH = _REPO_ROOT / "scripts" / "validate_mechanism_image_generation_audit.py"


def _load_validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mechanism_image_generation_audit_validator", _VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = _load_validator()


def _document() -> dict[str, object]:
    return json.loads(_AUDIT_PATH.read_text(encoding="utf-8"))


def _approved_document() -> dict[str, object]:
    document = _document()
    calls = document["calls"]
    assert isinstance(calls, list)
    accepted_hashes = {
        call["diagram_id"]: call["output_sha256"]
        for call in calls
        if isinstance(call, dict) and call["accepted"]
    }
    images = [
        {
            "filename": validator._PNG_BY_DIAGRAM[diagram_id],
            "sha256": accepted_hashes[diagram_id],
        }
        for diagram_id in validator._DIAGRAMS
    ]
    document["visual_approval"] = {
        "approver": "liu-qingyuan",
        "approved_at": "2026-08-13T07:10:00Z",
        "comment_url": (
            "https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/186"
            "#issuecomment-9999999999"
        ),
        "set_identity_sha256": validator._identity(
            "mechanism-visual-set-v1",
            "images",
            images,
        ),
        "images": images,
    }
    return document


def test_committed_audit_validates_only_at_the_pending_human_gate() -> None:
    summary = validator.validate_audit(
        _REPO_ROOT,
        require_visual_approval=False,
    )

    assert summary == {
        "schema_version": "mechanism-image-generation-audit-v1",
        "call_count": 6,
        "accepted_png_count": 5,
        "derivative_count": 5,
        "semantic_set_identity_sha256": (
            "c93dccf1a502e94484ad0db7a2abd9a8d5b2c16dd47c918825401da55ef170bf"
        ),
        "visual_set_identity_sha256": None,
        "visual_approval_status": "pending",
    }
    with pytest.raises(validator.AuditValidationError, match="visual approval is required"):
        validator.validate_audit(_REPO_ROOT)


def test_validator_accepts_one_complete_later_visual_approval_record() -> None:
    document = _approved_document()

    summary = validator._validate_document(
        document,
        _ASSET_ROOT,
        require_visual_approval=True,
    )

    assert summary["visual_approval_status"] == "approved"
    assert summary["visual_set_identity_sha256"] == (
        "6e3f6db6290e8f01c1f9763e9c297db426d1ed54a95014e1940fd43db7079c8b"
    )


def test_validator_rejects_schema_drift_crossed_hashes_and_partial_approval() -> None:
    extra_field = _document()
    extra_field["raw_prompt"] = "must never be published"
    with pytest.raises(validator.AuditValidationError, match="audit fields mismatch"):
        validator._validate_document(
            extra_field,
            _ASSET_ROOT,
            require_visual_approval=False,
        )

    crossed_hash = _document()
    calls = crossed_hash["calls"]
    assert isinstance(calls, list) and isinstance(calls[0], dict) and isinstance(calls[1], dict)
    calls[0]["output_sha256"], calls[1]["output_sha256"] = (
        calls[1]["output_sha256"],
        calls[0]["output_sha256"],
    )
    with pytest.raises(validator.AuditValidationError, match="generation ledger"):
        validator._validate_document(
            crossed_hash,
            _ASSET_ROOT,
            require_visual_approval=False,
        )

    partial_approval = _approved_document()
    visual_approval = partial_approval["visual_approval"]
    assert isinstance(visual_approval, dict) and isinstance(visual_approval["images"], list)
    visual_approval["images"] = visual_approval["images"][:-1]
    with pytest.raises(validator.AuditValidationError, match="complete accepted PNG set"):
        validator._validate_document(
            partial_approval,
            _ASSET_ROOT,
            require_visual_approval=True,
        )


def test_validator_rejects_semantic_time_and_attempt_contract_mutations() -> None:
    late_semantic_approval = _document()
    semantic_approval = late_semantic_approval["semantic_approval"]
    assert isinstance(semantic_approval, dict)
    semantic_approval["approved_at"] = "2026-08-13T08:00:00Z"
    with pytest.raises(validator.AuditValidationError, match="approved #185 whole set"):
        validator._validate_document(
            late_semantic_approval,
            _ASSET_ROOT,
            require_visual_approval=False,
        )

    duplicate_accepted = copy.deepcopy(_document())
    calls = duplicate_accepted["calls"]
    assert isinstance(calls, list) and isinstance(calls[2], dict)
    calls[2]["accepted"] = True
    calls[2]["rejection_reason"] = None
    with pytest.raises(validator.AuditValidationError, match="generation ledger"):
        validator._validate_document(
            duplicate_accepted,
            _ASSET_ROOT,
            require_visual_approval=False,
        )


@pytest.mark.skipif(shutil.which("cwebp") is None, reason="cwebp is unavailable")
def test_committed_webp_derivatives_rebuild_byte_identically() -> None:
    summary = validator.validate_audit(
        _REPO_ROOT,
        require_visual_approval=False,
        verify_derivatives=True,
    )

    assert summary["derivative_count"] == 5
