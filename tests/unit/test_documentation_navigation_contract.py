from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = REPO_ROOT / "docs"
ROLE_DIRECTORIES = {"guides", "architecture", "adr", "references", "agents", "weekly"}
IMMUTABLE_DATASET_EVIDENCE = {
    DOCS_ROOT / "references" / "jinjiang-final-dataset-audit-20260624.md",
    DOCS_ROOT / "references" / "jinjiang-final-dataset-cleanup-20260624.md",
}
RETIRED_PATHS = (
    "01-项目概览",
    "02-架构设计",
    "03-使用指南",
    "04-开发验证",
    "05-周报",
    "99-参考资料",
    "prds",
    "decision-maps",
)
EXPECTED_REFERENCE_FILES = {
    "docs/references/README.md",
    "docs/references/jinjiang-final-dataset-audit-20260624.md",
    "docs/references/jinjiang-final-dataset-cleanup-20260624.md",
    "docs/references/jinjiang-final-dataset-latent-v1-validation-20260705.md",
    "docs/references/jinjiang-user-latent-attributes-reference-zh.md",
    "docs/references/jinjiang-concurrent-message-formal-release-20260727.md",
    "docs/references/jinjiang-concurrent-message-two-mode-formal-release-20260728.md",
    "docs/references/jinjiang-concurrent-message-editorial-formal-release-20260729.md",
    "docs/references/concurrent-message-legend-visual-semantics-audit-20260803.md",
    "docs/references/concurrent-message-sensitivity-curve-visual-reference-20260803.md",
    "docs/references/concurrent-message-sensitivity-curve-visual-reference-20260803.jpg",
    "docs/references/retention-cleanup-final-evidence-20260730.md",
    "docs/references/retention-cleanup-execution-20260730.json",
}
REMOVED_REFERENCE_FILES = {
    "docs/references/PostContent.md",
    "docs/references/retention-audit-baseline-20260730.md",
    "docs/references/retention-cleanup-execution-20260730.md",
    "docs/references/gitnexus-index-scope-20260730.md",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tracked_markdown_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.md"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [REPO_ROOT / relative_path for relative_path in result.stdout.split("\0") if relative_path]


def _local_markdown_links(source: Path) -> list[tuple[str, Path]]:
    links: list[tuple[str, Path]] = []
    link_pattern = re.compile(r"\[([^\]]+)\]\(([^)#]+)(?:#[^)]+)?\)")

    for match in link_pattern.finditer(_read(source)):
        raw_target = match.group(2).strip()
        if "://" in raw_target or raw_target.startswith("mailto:"):
            continue

        # Protected dataset evidence keeps its historical source annotation byte-identical.
        if source in IMMUTABLE_DATASET_EVIDENCE and raw_target == "../04-开发验证/README.md":
            continue

        target = (source.parent / raw_target).resolve()
        if target.is_dir():
            target = target / "README.md"
        links.append((match.group(1), target))

    return links


def _linked_from(source: Path, target: Path) -> bool:
    return target.resolve() in {target for _, target in _local_markdown_links(source)}


def test_documentation_root_has_one_entrypoint_and_six_role_directories() -> None:
    directories = {path.name for path in DOCS_ROOT.iterdir() if path.is_dir()}
    assert directories == ROLE_DIRECTORIES
    assert (DOCS_ROOT / "index.md").exists()

    docs_index = DOCS_ROOT / "index.md"
    for role in sorted(ROLE_DIRECTORIES):
        entrypoint = DOCS_ROOT / role / "README.md"
        assert entrypoint.exists(), entrypoint
        assert _linked_from(docs_index, entrypoint), f"{docs_index} should link to {entrypoint}"

    for retired in RETIRED_PATHS:
        assert not (DOCS_ROOT / retired).exists(), retired


def test_current_entrypoints_are_discoverable_from_the_single_index() -> None:
    docs_index = DOCS_ROOT / "index.md"
    expected_targets = [
        DOCS_ROOT / "references" / "README.md",
        DOCS_ROOT / "guides" / "getting-started-macos.md",
        DOCS_ROOT / "architecture" / "abm-runtime.md",
        DOCS_ROOT / "architecture" / "concurrent-message-competition-experiment.md",
        DOCS_ROOT / "architecture" / "jinjiang-user-profile-data-structure.md",
        DOCS_ROOT / "architecture" / "douyin-data-collection-architecture.md",
        DOCS_ROOT / "architecture" / "retention-audit.md",
        DOCS_ROOT / "references" / "jinjiang-final-dataset-audit-20260624.md",
        DOCS_ROOT / "references" / "retention-cleanup-final-evidence-20260730.md",
        DOCS_ROOT / "references" / "jinjiang-concurrent-message-editorial-formal-release-20260729.md",
        DOCS_ROOT / "weekly" / "README.md",
        DOCS_ROOT / "agents" / "README.md",
    ]
    for target in expected_targets:
        assert _linked_from(docs_index, target), f"{docs_index} should link to {target}"

    index_text = _read(docs_index)
    assert "https://abm.q1ngyuan.top/" in index_text
    assert "23 步" not in index_text
    assert "迁移索引" not in index_text
    assert "redirect tree" in index_text


def test_tracked_docs_markdown_links_resolve() -> None:
    for source in _tracked_markdown_files():
        for label, target in _local_markdown_links(source):
            assert target.exists(), f"{source} link {label!r} targets missing {target}"


def test_architecture_notes_keep_current_truth_without_ticket_gate_diagrams() -> None:
    runtime = _read(DOCS_ROOT / "architecture" / "abm-runtime.md")
    concurrent = _read(DOCS_ROOT / "architecture" / "concurrent-message-competition-experiment.md")
    user_profile = _read(DOCS_ROOT / "architecture" / "jinjiang-user-profile-data-structure.md")

    assert "LLM 不是仿真调度器" in runtime
    assert "EngageDecision" in runtime
    assert "Status: Implemented and published architecture note" in concurrent
    assert "explicit presentation destination 始终使用 Editorial default" in concurrent
    assert "in-place rebuild 仍按 persisted source report hash 选择历史兼容 bytes" in concurrent
    assert "普通 run 与 `contract-protected` Formal/release run" in concurrent
    assert "ConcurrentCampaignDiagnostics" in concurrent
    assert "authoritative_message_definitions()" in concurrent
    assert "message_snapshot.json" in concurrent
    assert "interest_tags" in user_profile
    assert "Prompt v2 mocked" not in user_profile
    assert "```mermaid" not in concurrent


def test_historical_narrative_and_creation_screenshots_are_removed() -> None:
    removed_architecture = (
        "final-research-offline-baseline.md",
        "final-research-runtime.md",
        "interactive-mechanism-report.md",
        "runtime-component-inventory.md",
        "source-tree-and-entrypoints.md",
        "testing-strategy.md",
        "concurrent-message-campaign-diagnostics.md",
        "concurrent-message-durable-execution.md",
    )
    for name in removed_architecture:
        assert not (DOCS_ROOT / "architecture" / name).exists(), name

    removed_references = (
        "jinjiang-concurrent-message-complete-offline-validation-20260726.md",
        "jinjiang-final-research-live-validation-20260713.md",
        "jinjiang-target-delivery-ranking-final-validation-20260715.md",
        "jinjiang-field-lineage-trace-validation-20260720.md",
        "jinjiang-runtime-field-trace-validation-20260720.md",
        "jinjiang-seed-first-complete-offline-report-validation-20260720.md",
        "jinjiang-seed-first-offline-validation-20260720.md",
        "jinjiang-prompt-v2-mock-validation-20260708.md",
        "jinjiang-interest-tags-contract-audit-20260723.md",
    )
    for name in removed_references:
        assert not (DOCS_ROOT / "references" / name).exists(), name

    source_assets = Path(__file__).resolve().parents[2] / "src" / "llm_abm_sim" / "report_assets"
    for name in (
        "media-mechanism-overview.png",
        "media-mechanism-sample.png",
        "media-mechanism-exposure-ranking.png",
        "media-mechanism-llm-decision.png",
        "media-mechanism-network-feedback.png",
    ):
        assert (source_assets / name).exists(), name
    assert not (DOCS_ROOT / "references" / "concurrent-message-editorial-ui-design").exists()
    assert not any(DOCS_ROOT.rglob("*desktop.png"))
    assert not any(DOCS_ROOT.rglob("*trace*.png"))


def test_required_evidence_and_weekly_navigation_remain() -> None:
    for relative_path in EXPECTED_REFERENCE_FILES:
        assert (REPO_ROOT / relative_path).exists(), relative_path
    for relative_path in REMOVED_REFERENCE_FILES:
        assert not (REPO_ROOT / relative_path).exists(), relative_path

    weekly_text = _read(DOCS_ROOT / "weekly" / "README.md")
    assert "不覆盖 current Architecture" in weekly_text
    assert len(list((DOCS_ROOT / "weekly").glob("*.md"))) == 7


def test_references_reading_order_and_root_navigation_contract() -> None:
    references = _read(DOCS_ROOT / "references" / "README.md")
    for marker in ("默认读取", "按需 research", "按需 presentation audit", "按需 rollback", "forensic-only"):
        assert marker in references
    assert "默认 AI 阅读顺序不超过" in references

    default_markers = ("current dataset", "current Editorial", "current Retention")
    default_positions = [references.index(marker) for marker in default_markers]
    assert default_positions == sorted(default_positions)

    docs_index = DOCS_ROOT / "index.md"
    root_reference_targets = {
        target.resolve()
        for _, target in _local_markdown_links(docs_index)
        if target.parent == (DOCS_ROOT / "references").resolve()
    }
    assert root_reference_targets == {
        (DOCS_ROOT / "references" / "README.md").resolve(),
        (DOCS_ROOT / "references" / "jinjiang-final-dataset-audit-20260624.md").resolve(),
        (DOCS_ROOT / "references" / "jinjiang-concurrent-message-editorial-formal-release-20260729.md").resolve(),
        (DOCS_ROOT / "references" / "retention-cleanup-final-evidence-20260730.md").resolve(),
    }


def test_tracked_references_are_exactly_the_current_evidence_set() -> None:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "docs/references"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked = {path for path in result.stdout.split("\0") if path}
    assert tracked == EXPECTED_REFERENCE_FILES


def test_retention_current_truth_uses_the_final_evidence_and_tracked_policy() -> None:
    retention_note = DOCS_ROOT / "architecture" / "retention-audit.md"
    architecture_readme = DOCS_ROOT / "architecture" / "README.md"
    references = DOCS_ROOT / "references" / "README.md"
    final_evidence = _read(DOCS_ROOT / "references" / "retention-cleanup-final-evidence-20260730.md")
    manifest = _read(REPO_ROOT / "configs" / "retention" / "manifest.json")

    assert _linked_from(architecture_readme, retention_note)
    assert "retention-manifest-v2" in _read(retention_note)
    assert "audit_valid=true" in _read(retention_note)
    assert "retention-cleanup-final-evidence-20260730.md" in _read(retention_note)
    assert ".gitnexusignore" in _read(retention_note)
    assert "Retention baseline" not in _read(references)
    assert "docs/references/gitnexus-index-scope-20260730.md" not in manifest
    assert '"path": ".gitnexusignore"' in manifest
    assert "source-tree-and-entrypoints.md" not in manifest
    for relative_path in REMOVED_REFERENCE_FILES:
        assert relative_path.removeprefix("docs/references/") not in final_evidence
