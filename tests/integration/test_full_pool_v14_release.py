from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from llm_abm_sim import concurrent_robustness_release as release_module
from llm_abm_sim.concurrent_robustness_release import (
    ConcurrentRobustnessProductionRelease,
    ConcurrentRobustnessReleaseError,
)
from llm_abm_sim.full_pool_two_stage_replay import FULL_POOL_TWO_STAGE_SOURCE_SCHEMA


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _minimal_dispatch_inputs(root: Path) -> dict[str, Path]:
    paths = {
        name: root / name
        for name in (
            "full-pool",
            "historical-formal",
            "historical-study",
            "historical-candidate",
            "v2-study",
            "candidate",
            "protected-v13",
        )
    }
    for path in paths.values():
        path.mkdir(parents=True)
        (path / "input.txt").write_text(path.name, encoding="utf-8")
    (paths["full-pool"] / "manifest.json").write_bytes(
        _json_bytes({"schema_version": FULL_POOL_TWO_STAGE_SOURCE_SCHEMA})
    )
    candidate_manifest = {
        "schema_version": release_module.ROBUSTNESS_V2_CANDIDATE_MANIFEST_SCHEMA,
        "candidate_type": release_module.ROBUSTNESS_V2_CANDIDATE_TYPE,
        "production_deploy_eligible": False,
    }
    (paths["candidate"] / "artifact_manifest.json").write_bytes(
        _json_bytes(candidate_manifest)
    )
    (paths["candidate"] / "report.html").write_bytes(b"candidate-report")
    protected_contract = root / "protected-v13-contract.json"
    protected_contract.write_bytes(_json_bytes({"schema_version": "fixture"}))
    paths["protected-contract"] = protected_contract
    return paths


def _promotion_kwargs(root: Path, paths: dict[str, Path]) -> dict[str, Any]:
    return {
        "repo_root": root,
        "formal_root": paths["historical-formal"],
        "study_root": paths["historical-study"],
        "historical_candidate_dir": paths["historical-candidate"],
        "v2_study_root": paths["v2-study"],
        "candidate_dir": paths["candidate"],
        "destination_dir": root / "release-v14",
        "release_contract_path": root / "release-v14-contract.json",
        "release_id": "prompt-model-v14",
        "full_pool_source_root": paths["full-pool"],
        "full_pool_manifest_sha256": "a" * 64,
        "full_pool_source_identity": "b" * 64,
        "protected_v13_release_root": paths["protected-v13"],
        "protected_v13_contract_path": paths["protected-contract"],
        "implementation_commit": "c" * 40,
    }


def test_v14_dispatch_requires_the_complete_exact_input_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _minimal_dispatch_inputs(tmp_path)
    kwargs = _promotion_kwargs(tmp_path, paths)
    called: dict[str, object] = {}

    def fake_promote(**values: object) -> ConcurrentRobustnessProductionRelease:
        called.update(values)
        return ConcurrentRobustnessProductionRelease(
            source_dir=tmp_path / "unused",
            contract_path=tmp_path / "unused.json",
            release_id="prompt-model-v14",
            report_sha256="d" * 64,
            manifest_sha256="e" * 64,
            release_identity_sha256="f" * 64,
        )

    monkeypatch.setattr(
        release_module,
        "_promote_prompt_model_v14_release",
        fake_promote,
    )
    result = release_module.promote_concurrent_robustness_release(**kwargs)
    assert result.release_id == "prompt-model-v14"
    assert called["v2_study_root"] == paths["v2-study"]
    assert called["historical_candidate_dir"] == paths["historical-candidate"]
    assert called["protected_v13_release_root"] == paths["protected-v13"]

    incomplete = dict(kwargs)
    incomplete["protected_v13_contract_path"] = None
    with pytest.raises(ConcurrentRobustnessReleaseError, match="exact v2 candidate"):
        release_module.promote_concurrent_robustness_release(**incomplete)
    assert not (tmp_path / "release-v14").exists()
    assert not (tmp_path / "release-v14-contract.json").exists()


def test_legacy_full_pool_dispatch_rejects_v14_only_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _minimal_dispatch_inputs(tmp_path)
    (paths["full-pool"] / "manifest.json").write_bytes(
        _json_bytes({"schema_version": "full-pool-segmented-source-v4"})
    )
    presentation_closure = tmp_path / "presentation-closure.json"
    fresh_manifest = tmp_path / "fresh-manifest.json"
    presentation_closure.write_bytes(_json_bytes({"schema_version": "fixture"}))
    fresh_manifest.write_bytes(_json_bytes({"schema_version": "fixture"}))
    legacy_called = False

    def fake_legacy_promote(**_values: object) -> ConcurrentRobustnessProductionRelease:
        nonlocal legacy_called
        legacy_called = True
        return ConcurrentRobustnessProductionRelease(
            source_dir=tmp_path / "unused",
            contract_path=tmp_path / "unused.json",
            release_id="legacy-release",
            report_sha256="d" * 64,
            manifest_sha256="e" * 64,
            release_identity_sha256="f" * 64,
        )

    monkeypatch.setattr(
        release_module,
        "_promote_full_pool_v12_release",
        fake_legacy_promote,
    )
    with pytest.raises(ConcurrentRobustnessReleaseError, match="v14-only"):
        release_module.promote_concurrent_robustness_release(
            repo_root=tmp_path,
            formal_root=paths["historical-formal"],
            study_root=paths["historical-study"],
            candidate_dir=paths["candidate"],
            historical_candidate_dir=paths["historical-candidate"],
            destination_dir=tmp_path / "legacy-release",
            release_contract_path=tmp_path / "legacy-contract.json",
            release_id="legacy-release",
            presentation_closure_path=presentation_closure,
            full_pool_source_root=paths["full-pool"],
            full_pool_manifest_sha256="a" * 64,
            implementation_commit="c" * 40,
            fresh_execution_manifest_path=fresh_manifest,
        )
    assert legacy_called is False


def test_v14_rejects_output_inside_derived_upstream_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _minimal_dispatch_inputs(tmp_path)
    upstream = tmp_path / "derived-upstream"
    upstream.mkdir()
    kwargs = _promotion_kwargs(tmp_path, paths)
    kwargs["destination_dir"] = upstream / "nested-release"
    monkeypatch.setattr(
        release_module,
        "_close_prompt_model_v14_inputs",
        lambda **_values: SimpleNamespace(
            full_pool_upstream=SimpleNamespace(root=upstream)
        ),
    )

    with pytest.raises(ConcurrentRobustnessReleaseError, match="upstream"):
        release_module.promote_concurrent_robustness_release(**kwargs)

    assert list(upstream.iterdir()) == []
    assert not Path(kwargs["release_contract_path"]).exists()


def test_v14_formal_shaped_fixture_cannot_survive_standalone_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _minimal_dispatch_inputs(tmp_path)
    kwargs = _promotion_kwargs(tmp_path, paths)
    before = {
        path: {
            item.relative_to(path).as_posix(): _sha256(item)
            for item in sorted(path.rglob("*"))
            if item.is_file()
        }
        for path in paths.values()
        if path.is_dir()
    }
    full_pool = SimpleNamespace(
        root=paths["full-pool"],
        source_identity="b" * 64,
        manifest_sha256="a" * 64,
    )
    formal_upstream = tmp_path / "formal-upstream"
    formal_upstream.mkdir()
    study_facts = SimpleNamespace(
        root_path=paths["v2-study"],
        root_identity_sha256="1" * 64,
        manifest_sha256="2" * 64,
    )
    closure = release_module._PromptModelV14Closure(
        full_pool_source=cast(Any, full_pool),
        full_pool_upstream=cast(Any, SimpleNamespace(root=formal_upstream)),
        v2_formal=cast(
            Any,
            SimpleNamespace(report_source=SimpleNamespace(facts=study_facts)),
        ),
        historical_formal=paths["historical-formal"],
        historical_study=paths["historical-study"],
        historical_candidate=paths["historical-candidate"],
        candidate=paths["candidate"],
        protected_v13_release=paths["protected-v13"],
        protected_v13_contract=paths["protected-contract"],
        production_html=b"<!doctype html><meta name='release' content='v14'>",
        full_pool_source_facts={
            "directory": "full-pool",
            "manifest_sha256": "a" * 64,
            "source_identity": "b" * 64,
        },
        historical_inputs={
            "formal_directory": "historical-formal",
            "study_directory": "historical-study",
            "candidate_directory": "historical-candidate",
        },
        v2_study={"directory": "v2-study", "counts": {"logical_judgments": 36_000}},
        presentation_candidate={
            "directory": "candidate",
            "candidate_identity_sha256": "3" * 64,
            "manifest_sha256": "4" * 64,
            "production_deploy_eligible": False,
        },
        protected_v13={
            "release_directory": "protected-v13",
            "contract_path": "protected-v13-contract.json",
            "contract_sha256": _sha256(paths["protected-contract"]),
        },
        workbook={"relative_path": "teacher_results.xlsx", "sha256": "5" * 64},
        prompt_contracts={"prompt_count": 4, "model_count": 5},
        provider_accounting={"prompt_model_v2": {"logical_judgments": 36_000}},
        realized_metrics={"formal_topology": {"cells": 20}},
        mechanism_inventory={},
        approved_downloads={},
        release_readiness={
            "schema_version": release_module.FULL_POOL_V14_READINESS_SCHEMA,
            "release_id": "prompt-model-v14",
        },
        snapshots={},
    )
    real_close = release_module._close_prompt_model_v14_inputs
    close_calls = 0

    def stage_fixture_then_close_real_inputs(**values: Any) -> Any:
        nonlocal close_calls
        close_calls += 1
        if close_calls == 1:
            return closure
        return real_close(**values)

    monkeypatch.setattr(
        release_module,
        "_close_prompt_model_v14_inputs",
        stage_fixture_then_close_real_inputs,
    )
    monkeypatch.setattr(
        release_module._REPORT_PRESENTATION,
        "validate_v2_realized_production",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(
        ConcurrentRobustnessReleaseError,
        match="upstream|Formal|closure",
    ):
        release_module.promote_concurrent_robustness_release(**kwargs)
    assert close_calls == 2

    assert not (tmp_path / "release-v14").exists()
    assert not (tmp_path / "release-v14-contract.json").exists()
    assert not list(tmp_path.glob(".release-v14.v14.*.staging"))
    assert (paths["candidate"] / "report.html").read_bytes() == b"candidate-report"
    for path, snapshot in before.items():
        assert {
            item.relative_to(path).as_posix(): _sha256(item)
            for item in sorted(path.rglob("*"))
            if item.is_file()
        } == snapshot
