#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = "mechanism-image-generation-audit-v1"
_VISUAL_SET_SCHEMA_VERSION = "mechanism-visual-set-v1"
_ASSET_RELATIVE_ROOT = Path("src/llm_abm_sim/report_assets")
_AUDIT_FILENAME = "mechanism-image-generation-audit.json"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_VISUAL_APPROVAL_URL = re.compile(
    r"https://github\.com/liu-qingyuan/llm-abm-marketing-sim/issues/186#issuecomment-[0-9]+"
)

_TOP_FIELDS = {
    "schema_version",
    "semantic_approval",
    "calls",
    "visual_approval",
    "derivatives",
}
_SEMANTIC_APPROVAL_FIELDS = {
    "approver",
    "approved_at",
    "comment_url",
    "set_identity_sha256",
    "implementation_commit",
    "masters",
}
_CALL_FIELDS = {
    "diagram_id",
    "attempt",
    "model",
    "size",
    "quality",
    "called_at",
    "prompt_sha256",
    "output_sha256",
    "accepted",
    "rejection_reason",
}
_VISUAL_APPROVAL_FIELDS = {
    "approver",
    "approved_at",
    "comment_url",
    "set_identity_sha256",
    "images",
}
_DERIVATIVE_FIELDS = {
    "diagram_id",
    "source_filename",
    "source_sha256",
    "filename",
    "sha256",
    "encoder",
    "encoder_version",
    "arguments",
}
_FILE_HASH_FIELDS = {"filename", "sha256"}

_DIAGRAMS = (
    "sample_first",
    "pair_formation",
    "independent_delivery",
    "exposure_decisions",
    "feedback_boundary",
)
_PNG_BY_DIAGRAM = {
    "sample_first": "mechanism-sample-first-v4.png",
    "pair_formation": "mechanism-pair-formation-v4.png",
    "independent_delivery": "mechanism-independent-delivery-v4.png",
    "exposure_decisions": "mechanism-exposure-decisions-v4.png",
    "feedback_boundary": "mechanism-feedback-boundary-v4.png",
}
_WEBP_BY_DIAGRAM = {
    diagram_id: filename.removesuffix(".png") + ".webp"
    for diagram_id, filename in _PNG_BY_DIAGRAM.items()
}
_EXPECTED_WEBP_ARGUMENTS = [
    "-quiet",
    "-q",
    "84",
    "-m",
    "6",
    "-pass",
    "10",
    "-metadata",
    "none",
    "-sharp_yuv",
]

_EXPECTED_SEMANTIC_APPROVAL = {
    "approver": "liu-qingyuan",
    "approved_at": "2026-08-13T05:23:38Z",
    "comment_url": (
        "https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/185"
        "#issuecomment-5276313349"
    ),
    "set_identity_sha256": "c93dccf1a502e94484ad0db7a2abd9a8d5b2c16dd47c918825401da55ef170bf",
    "implementation_commit": "34ed1d3a7f85bc93acfbf5f7572fb03c0e3a3dbb",
    "masters": [
        {
            "filename": "mechanism-sample-first.mmd",
            "sha256": "30786e0b98a576ab299b51e0aebceedb6b6d8fc03a7955ba56bc782bde594b81",
        },
        {
            "filename": "mechanism-pair-formation.mmd",
            "sha256": "567859f204eed780ec8196aa1b23d6ed120e29a45161a442efa53fcf6431fb2e",
        },
        {
            "filename": "mechanism-independent-delivery.mmd",
            "sha256": "a4c933e87ff25132434e8c890449d3c38326bf17b5da93309ab4f199513d3f87",
        },
        {
            "filename": "mechanism-exposure-decisions.mmd",
            "sha256": "02ef23e190bb5fe5bbb313c3ac902201da8e44239f026189c529d75a0687bed8",
        },
        {
            "filename": "mechanism-feedback-boundary.mmd",
            "sha256": "536a4de2b120e19a19b930c458ae481580541a8bc301a47cd7413a14b9e15675",
        },
        {
            "filename": "real-batch-mechanism.mmd",
            "sha256": "73ea8c840faa315b0a5ee70b2958723fcf0fe140bfc000964a3d04c8f65bd907",
        },
    ],
}

# This immutable ledger contains hashes and timestamps only. Raw prompts and Provider
# payloads are intentionally absent from both this validator and the public audit.
_EXPECTED_CALL_LEDGER = (
    {
        "diagram_id": "sample_first",
        "attempt": 1,
        "called_at": "2026-08-13T06:53:30Z",
        "prompt_sha256": "eb10f123b77e552df802270f301c567ee5c3fc74baf5ae28c283e0ec419c1a08",
        "output_sha256": "a3f74f6b393ef6aa505ee968d3303c92aadc37a899de9c077556f2f402fdc61e",
        "accepted": True,
        "rejection_reason": None,
    },
    {
        "diagram_id": "pair_formation",
        "attempt": 1,
        "called_at": "2026-08-13T06:55:14Z",
        "prompt_sha256": "0e4908896e7d7ef87d0811f9baaeb12b46a97fb1f33d81ca0a4b30d59f6a06cd",
        "output_sha256": "fa251e8af0e7205e0072c1b545f77430db7e5834b6528959dfbaf393ad5a5d04",
        "accepted": True,
        "rejection_reason": None,
    },
    {
        "diagram_id": "independent_delivery",
        "attempt": 1,
        "called_at": "2026-08-13T06:56:53Z",
        "prompt_sha256": "df485d8fcf381c32effebeb1e26dc0abc761206fbefa207478574bf9a4c33c27",
        "output_sha256": "f59a388495dfe35bb335a502737d1c88670a36ddbcafdb9f46f9424033da44a9",
        "accepted": False,
        "rejection_reason": "Rendered human/group pictograms, violating the approved no-people constraint.",
    },
    {
        "diagram_id": "independent_delivery",
        "attempt": 2,
        "called_at": "2026-08-13T06:58:24Z",
        "prompt_sha256": "6d83fef760de5b7bbc77565e13baf001e41fbb2a3b6a08f74dabbbb4cb0d1ff3",
        "output_sha256": "a2d973a30855b54d03d23bfb6b6bb3e6ad174cb7d1e2fc733ca8441b48c55330",
        "accepted": True,
        "rejection_reason": None,
    },
    {
        "diagram_id": "exposure_decisions",
        "attempt": 1,
        "called_at": "2026-08-13T07:00:29Z",
        "prompt_sha256": "57400c6f4bf8b8ea919a680630d8dbee879ce64aea2500528fd132ec450c20f1",
        "output_sha256": "0d721fbeae68e939f1946d0349042112adc7e22b989a00d99e5b4e23ed45e620",
        "accepted": True,
        "rejection_reason": None,
    },
    {
        "diagram_id": "feedback_boundary",
        "attempt": 1,
        "called_at": "2026-08-13T07:02:10Z",
        "prompt_sha256": "2a4ff29bfebb7a93516a0cc2c30322f12e420250c5eed8c71f7c8670709f4875",
        "output_sha256": "299311aef8d5042e34d1ab0b0966348d215411cd967a2937c738848e03e8fccd",
        "accepted": True,
        "rejection_reason": None,
    },
)


class AuditValidationError(ValueError):
    pass


def _fail(message: str) -> None:
    raise AuditValidationError(message)


def _no_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        _fail(f"audit must be a regular file: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicate_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"cannot read audit JSON: {exc}")
    if not isinstance(document, dict):
        _fail("audit root must be an object")
    return document


def _expect_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{label} must be an object")
    return value


def _expect_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(f"{label} must be an array")
    return value


def _expect_exact_fields(value: dict[str, Any], fields: set[str], label: str) -> None:
    actual = set(value)
    if actual != fields:
        missing = sorted(fields - actual)
        extra = sorted(actual - fields)
        _fail(f"{label} fields mismatch; missing={missing}, extra={extra}")


def _expect_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(f"{label} must be a lowercase SHA-256")
    return value


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        _fail(f"{label} must be a UTC RFC 3339 timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        _fail(f"{label} is not a valid timestamp")
    return parsed


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _regular_asset(asset_root: Path, filename: str) -> Path:
    if Path(filename).name != filename:
        _fail(f"asset filename must be a basename: {filename}")
    path = asset_root / filename
    if path.is_symlink() or not path.is_file():
        _fail(f"asset must be a regular file: {filename}")
    if path.stat().st_size <= 0:
        _fail(f"asset must be non-empty: {filename}")
    return path


def _identity(schema_version: str, collection_name: str, records: list[dict[str, str]]) -> str:
    payload = {
        "schema_version": schema_version,
        collection_name: records,
    }
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return hashlib.sha256(encoded).hexdigest()


def _png_dimensions(path: Path) -> tuple[int, int]:
    payload = path.read_bytes()
    if len(payload) < 24 or payload[:8] != b"\x89PNG\r\n\x1a\n" or payload[12:16] != b"IHDR":
        _fail(f"invalid PNG: {path.name}")
    return struct.unpack(">II", payload[16:24])


def _webp_dimensions(path: Path) -> tuple[int, int]:
    payload = path.read_bytes()
    if len(payload) < 20 or payload[:4] != b"RIFF" or payload[8:12] != b"WEBP":
        _fail(f"invalid WebP: {path.name}")
    offset = 12
    while offset + 8 <= len(payload):
        fourcc = payload[offset : offset + 4]
        chunk_size = int.from_bytes(payload[offset + 4 : offset + 8], "little")
        chunk = payload[offset + 8 : offset + 8 + chunk_size]
        if len(chunk) != chunk_size:
            _fail(f"truncated WebP chunk: {path.name}")
        if fourcc == b"VP8X" and len(chunk) >= 10:
            width = 1 + int.from_bytes(chunk[4:7], "little")
            height = 1 + int.from_bytes(chunk[7:10], "little")
            return width, height
        if fourcc == b"VP8 " and len(chunk) >= 10 and chunk[3:6] == b"\x9d\x01\x2a":
            width = int.from_bytes(chunk[6:8], "little") & 0x3FFF
            height = int.from_bytes(chunk[8:10], "little") & 0x3FFF
            return width, height
        if fourcc == b"VP8L" and len(chunk) >= 5 and chunk[0] == 0x2F:
            bits = int.from_bytes(chunk[1:5], "little")
            width = (bits & 0x3FFF) + 1
            height = ((bits >> 14) & 0x3FFF) + 1
            return width, height
        offset += 8 + chunk_size + (chunk_size & 1)
    _fail(f"WebP has no supported image chunk: {path.name}")


def _validate_semantic_approval(document: dict[str, Any], asset_root: Path) -> datetime:
    approval = _expect_object(document["semantic_approval"], "semantic_approval")
    _expect_exact_fields(approval, _SEMANTIC_APPROVAL_FIELDS, "semantic_approval")
    if approval != _EXPECTED_SEMANTIC_APPROVAL:
        _fail("semantic_approval does not match the approved #185 whole set")

    masters = _expect_list(approval["masters"], "semantic_approval.masters")
    normalized: list[dict[str, str]] = []
    for index, raw_record in enumerate(masters):
        record = _expect_object(raw_record, f"semantic_approval.masters[{index}]")
        _expect_exact_fields(record, _FILE_HASH_FIELDS, f"semantic_approval.masters[{index}]")
        filename = record["filename"]
        if not isinstance(filename, str):
            _fail(f"semantic_approval.masters[{index}].filename must be a string")
        sha256 = _expect_sha256(record["sha256"], f"semantic_approval.masters[{index}].sha256")
        path = _regular_asset(asset_root, filename)
        if _sha256(path) != sha256:
            _fail(f"semantic master hash mismatch: {filename}")
        normalized.append({"filename": filename, "sha256": sha256})

    identity = _identity("mechanism-semantic-set-v1", "masters", normalized)
    if identity != approval["set_identity_sha256"]:
        _fail("semantic set identity mismatch")
    return _parse_time(approval["approved_at"], "semantic_approval.approved_at")


def _validate_calls(
    document: dict[str, Any], semantic_approved_at: datetime
) -> tuple[dict[str, str], datetime]:
    calls = _expect_list(document["calls"], "calls")
    if not 5 <= len(calls) <= 10:
        _fail("calls must contain 5..10 records")

    expected_common = {"model": "gpt-image-2", "size": "1536x1024", "quality": "high"}
    normalized: list[dict[str, Any]] = []
    times: list[datetime] = []
    attempts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, raw_call in enumerate(calls):
        call = _expect_object(raw_call, f"calls[{index}]")
        _expect_exact_fields(call, _CALL_FIELDS, f"calls[{index}]")
        if {key: call[key] for key in expected_common} != expected_common:
            _fail(f"calls[{index}] model/size/quality mismatch")
        if call["diagram_id"] not in _DIAGRAMS:
            _fail(f"calls[{index}].diagram_id is not expected")
        if isinstance(call["attempt"], bool) or not isinstance(call["attempt"], int):
            _fail(f"calls[{index}].attempt must be an integer")
        if type(call["accepted"]) is not bool:
            _fail(f"calls[{index}].accepted must be a boolean")
        _expect_sha256(call["prompt_sha256"], f"calls[{index}].prompt_sha256")
        _expect_sha256(call["output_sha256"], f"calls[{index}].output_sha256")
        if call["accepted"] and call["rejection_reason"] is not None:
            _fail(f"calls[{index}] accepted output cannot have a rejection reason")
        if not call["accepted"] and (
            not isinstance(call["rejection_reason"], str) or not call["rejection_reason"].strip()
        ):
            _fail(f"calls[{index}] rejected output needs a rejection reason")
        called_at = _parse_time(call["called_at"], f"calls[{index}].called_at")
        if called_at <= semantic_approved_at:
            _fail("semantic approval must precede every image-generation call")
        times.append(called_at)
        normalized.append(call)
        attempts[call["diagram_id"]].append(call)

    if normalized != [dict(record, **expected_common) for record in _EXPECTED_CALL_LEDGER]:
        _fail("calls do not match the immutable six-call generation ledger")
    if times != sorted(times) or len(set(times)) != len(times):
        _fail("calls must be strictly time ordered")
    if set(attempts) != set(_DIAGRAMS):
        _fail("every image diagram must have calls")

    accepted_hashes: dict[str, str] = {}
    for diagram_id in _DIAGRAMS:
        records = attempts[diagram_id]
        if not 1 <= len(records) <= 2:
            _fail(f"{diagram_id} must have 1..2 attempts")
        if [record["attempt"] for record in records] != list(range(1, len(records) + 1)):
            _fail(f"{diagram_id} attempts must be contiguous and ordered")
        accepted = [record for record in records if record["accepted"]]
        if len(accepted) != 1 or accepted[0] is not records[-1]:
            _fail(f"{diagram_id} must have exactly one accepted final attempt")
        accepted_hashes[diagram_id] = accepted[0]["output_sha256"]
    return accepted_hashes, times[-1]


def _validate_pngs(asset_root: Path, accepted_hashes: dict[str, str]) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    for diagram_id in _DIAGRAMS:
        filename = _PNG_BY_DIAGRAM[diagram_id]
        path = _regular_asset(asset_root, filename)
        sha256 = _sha256(path)
        if sha256 != accepted_hashes[diagram_id]:
            _fail(f"accepted PNG hash mismatch: {filename}")
        if _png_dimensions(path) != (1536, 1024):
            _fail(f"accepted PNG dimensions mismatch: {filename}")
        images.append({"filename": filename, "sha256": sha256})
    return images


def _validate_visual_approval(
    document: dict[str, Any],
    images: list[dict[str, str]],
    last_call_at: datetime,
    *,
    require_visual_approval: bool,
) -> str | None:
    raw_approval = document["visual_approval"]
    if raw_approval is None:
        if require_visual_approval:
            _fail("visual approval is required")
        return None

    approval = _expect_object(raw_approval, "visual_approval")
    _expect_exact_fields(approval, _VISUAL_APPROVAL_FIELDS, "visual_approval")
    if not isinstance(approval["approver"], str) or not approval["approver"].strip():
        _fail("visual_approval.approver must be non-empty")
    if not isinstance(approval["comment_url"], str) or _VISUAL_APPROVAL_URL.fullmatch(
        approval["comment_url"]
    ) is None:
        _fail("visual_approval.comment_url must reference one #186 issue comment")
    approved_at = _parse_time(approval["approved_at"], "visual_approval.approved_at")
    if approved_at <= last_call_at:
        _fail("visual approval must follow all accepted outputs")
    _expect_sha256(approval["set_identity_sha256"], "visual_approval.set_identity_sha256")

    raw_images = _expect_list(approval["images"], "visual_approval.images")
    approved_images: list[dict[str, str]] = []
    for index, raw_image in enumerate(raw_images):
        image = _expect_object(raw_image, f"visual_approval.images[{index}]")
        _expect_exact_fields(image, _FILE_HASH_FIELDS, f"visual_approval.images[{index}]")
        if not isinstance(image["filename"], str):
            _fail(f"visual_approval.images[{index}].filename must be a string")
        _expect_sha256(image["sha256"], f"visual_approval.images[{index}].sha256")
        approved_images.append(image)
    if approved_images != images:
        _fail("visual approval must bind the complete accepted PNG set in canonical order")

    identity = _identity(_VISUAL_SET_SCHEMA_VERSION, "images", images)
    if approval["set_identity_sha256"] != identity:
        _fail("visual set identity mismatch")
    return identity


def _validate_derivatives(
    document: dict[str, Any], asset_root: Path, accepted_hashes: dict[str, str]
) -> list[dict[str, Any]]:
    derivatives = _expect_list(document["derivatives"], "derivatives")
    if len(derivatives) != len(_DIAGRAMS):
        _fail("derivatives must contain exactly five records")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_derivative in enumerate(derivatives):
        derivative = _expect_object(raw_derivative, f"derivatives[{index}]")
        _expect_exact_fields(derivative, _DERIVATIVE_FIELDS, f"derivatives[{index}]")
        diagram_id = derivative["diagram_id"]
        if diagram_id not in _DIAGRAMS or diagram_id in seen:
            _fail(f"derivatives[{index}].diagram_id is unexpected or duplicated")
        seen.add(diagram_id)
        source_filename = _PNG_BY_DIAGRAM[diagram_id]
        filename = _WEBP_BY_DIAGRAM[diagram_id]
        if derivative["source_filename"] != source_filename or derivative["filename"] != filename:
            _fail(f"derivative filename mapping mismatch: {diagram_id}")
        source_sha256 = _expect_sha256(
            derivative["source_sha256"], f"derivatives[{index}].source_sha256"
        )
        if source_sha256 != accepted_hashes[diagram_id]:
            _fail(f"derivative source hash mismatch: {diagram_id}")
        if derivative["encoder"] != "cwebp" or derivative["encoder_version"] != "1.6.0":
            _fail(f"derivative encoder mismatch: {diagram_id}")
        if derivative["arguments"] != _EXPECTED_WEBP_ARGUMENTS:
            _fail(f"derivative arguments mismatch: {diagram_id}")
        sha256 = _expect_sha256(derivative["sha256"], f"derivatives[{index}].sha256")
        path = _regular_asset(asset_root, filename)
        if _sha256(path) != sha256:
            _fail(f"WebP hash mismatch: {filename}")
        if _webp_dimensions(path) != (1536, 1024):
            _fail(f"WebP dimensions mismatch: {filename}")
        normalized.append(derivative)

    if [record["diagram_id"] for record in normalized] != list(_DIAGRAMS):
        _fail("derivatives must use canonical diagram order")
    return normalized


def _verify_derivative_rebuilds(asset_root: Path, derivatives: list[dict[str, Any]]) -> None:
    executable = shutil.which("cwebp")
    if executable is None:
        _fail("cwebp is required for --verify-derivatives")
    version = subprocess.run(
        [executable, "-version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()[0]
    if any(record["encoder_version"] != version for record in derivatives):
        _fail(f"cwebp version mismatch: found {version}")

    with tempfile.TemporaryDirectory(prefix="mechanism-webp-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        for record in derivatives:
            source = asset_root / record["source_filename"]
            rebuilt = temporary_root / record["filename"]
            subprocess.run(
                [executable, *record["arguments"], str(source), "-o", str(rebuilt)],
                check=True,
                capture_output=True,
            )
            committed = asset_root / record["filename"]
            if rebuilt.read_bytes() != committed.read_bytes():
                _fail(f"deterministic WebP rebuild mismatch: {record['filename']}")


def _validate_document(
    document: dict[str, Any],
    asset_root: Path,
    *,
    require_visual_approval: bool,
    verify_derivatives: bool = False,
) -> dict[str, Any]:
    _expect_exact_fields(document, _TOP_FIELDS, "audit")
    if document["schema_version"] != _SCHEMA_VERSION:
        _fail(f"schema_version must be {_SCHEMA_VERSION}")

    semantic_approved_at = _validate_semantic_approval(document, asset_root)
    accepted_hashes, last_call_at = _validate_calls(document, semantic_approved_at)
    images = _validate_pngs(asset_root, accepted_hashes)
    visual_identity = _validate_visual_approval(
        document,
        images,
        last_call_at,
        require_visual_approval=require_visual_approval,
    )
    derivatives = _validate_derivatives(document, asset_root, accepted_hashes)
    if verify_derivatives:
        _verify_derivative_rebuilds(asset_root, derivatives)

    return {
        "schema_version": _SCHEMA_VERSION,
        "call_count": len(document["calls"]),
        "accepted_png_count": len(images),
        "derivative_count": len(derivatives),
        "semantic_set_identity_sha256": document["semantic_approval"]["set_identity_sha256"],
        "visual_set_identity_sha256": visual_identity,
        "visual_approval_status": "approved" if visual_identity is not None else "pending",
    }


def validate_audit(
    repo_root: Path,
    *,
    audit_path: Path | None = None,
    require_visual_approval: bool = True,
    verify_derivatives: bool = False,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    asset_root = repo_root / _ASSET_RELATIVE_ROOT
    path = audit_path or (asset_root / _AUDIT_FILENAME)
    return _validate_document(
        _load_json(path),
        asset_root,
        require_visual_approval=require_visual_approval,
        verify_derivatives=verify_derivatives,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the v4 mechanism image-generation audit")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--audit", type=Path)
    parser.add_argument(
        "--allow-pending-visual-approval",
        action="store_true",
        help="validate the pre-approval artifact set while requiring visual_approval to remain null",
    )
    parser.add_argument(
        "--verify-derivatives",
        action="store_true",
        help="rebuild all WebP derivatives with the recorded cwebp version and compare bytes",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        summary = validate_audit(
            args.repo_root,
            audit_path=args.audit,
            require_visual_approval=not args.allow_pending_visual_approval,
            verify_derivatives=args.verify_derivatives,
        )
    except (AuditValidationError, OSError, subprocess.CalledProcessError) as exc:
        print(f"INVALID {exc}")
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
