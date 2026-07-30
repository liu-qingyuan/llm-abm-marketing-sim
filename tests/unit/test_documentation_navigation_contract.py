from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = REPO_ROOT / "docs"


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

        target = (source.parent / raw_target).resolve()
        if target.is_dir():
            target = target / "README.md"
        links.append((match.group(1), target))

    return links


def _local_markdown_targets(source: Path) -> set[Path]:
    return {target for _, target in _local_markdown_links(source)}


def _linked_from(source: Path, target: Path) -> bool:
    return target.resolve() in _local_markdown_targets(source)


def _level_two_headings(path: Path) -> set[str]:
    return set(re.findall(r"^##\s+(.+?)\s*$", _read(path), flags=re.MULTILINE))


def test_documentation_role_directories_have_stable_entrypoints():
    expected_entrypoints = [
        DOCS_ROOT / "index.md",
        DOCS_ROOT / "prds" / "README.md",
        DOCS_ROOT / "references" / "README.md",
        DOCS_ROOT / "architecture" / "README.md",
        DOCS_ROOT / "adr" / "README.md",
        DOCS_ROOT / "agents" / "README.md",
        DOCS_ROOT / "04-开发验证" / "README.md",
    ]

    for entrypoint in expected_entrypoints:
        assert entrypoint.exists(), entrypoint

    docs_index = DOCS_ROOT / "index.md"
    for entrypoint in expected_entrypoints[1:6]:
        assert _linked_from(docs_index, entrypoint), f"{docs_index} should link to {entrypoint}"


def test_legacy_development_validation_readme_redirects_to_role_directories():
    legacy_readme = DOCS_ROOT / "04-开发验证" / "README.md"
    legacy_text = _read(legacy_readme)

    assert "迁移索引" in legacy_text or "legacy redirect" in legacy_text.lower()

    for target in [
        DOCS_ROOT / "prds" / "README.md",
        DOCS_ROOT / "references" / "README.md",
        DOCS_ROOT / "architecture" / "README.md",
        DOCS_ROOT / "adr" / "README.md",
    ]:
        assert _linked_from(legacy_readme, target), f"{legacy_readme} should redirect to {target}"


def test_jinjiang_latent_attribute_documents_are_discoverable_from_navigation_hubs():
    navigation_hubs = [
        DOCS_ROOT / "index.md",
        DOCS_ROOT / "04-开发验证" / "README.md",
    ]
    discoverable_targets = set().union(*[_local_markdown_targets(hub) for hub in navigation_hubs])

    expected_targets = [
        DOCS_ROOT / "references" / "jinjiang-user-latent-attributes-reference-zh.md",
        DOCS_ROOT / "architecture" / "jinjiang-user-profile-data-structure.md",
        DOCS_ROOT / "prds" / "jinjiang-user-latent-attributes-v1.md",
    ]

    for target in expected_targets:
        assert target.exists(), target
        assert target.resolve() in discoverable_targets, f"{target} should be linked from docs index or legacy entry"


def test_jinjiang_latent_attribute_prd_keeps_status_and_planning_sections():
    prd = DOCS_ROOT / "prds" / "jinjiang-user-latent-attributes-v1.md"
    prd_text = _read(prd)
    headings = _level_two_headings(prd)

    assert "Implementation status:" in prd_text
    assert "当前实现状态" in headings
    assert "非目标" in headings
    assert "审计与验收" in headings
    assert "后续 issue plan" in headings


def test_tracked_docs_markdown_links_resolve():
    for source in _tracked_markdown_files():
        for label, target in _local_markdown_links(source):
            assert target.exists(), f"{source} link {label!r} targets missing {target}"


def test_current_research_navigation_contract():
    docs_index = DOCS_ROOT / "index.md"
    index_text = _read(docs_index)
    expected_targets = [
        DOCS_ROOT / "architecture" / "concurrent-message-competition-experiment.md",
        DOCS_ROOT / "references" / "jinjiang-concurrent-message-editorial-formal-release-20260729.md",
        DOCS_ROOT / "references" / "jinjiang-final-dataset-audit-20260624.md",
        DOCS_ROOT / "references" / "jinjiang-final-dataset-latent-v1-validation-20260705.md",
    ]

    for target in expected_targets:
        assert _linked_from(docs_index, target), f"{docs_index} should link to {target}"
    assert "https://abm.q1ngyuan.top/" in index_text


def test_current_and_historical_document_status_contract():
    current_architecture = _read(DOCS_ROOT / "architecture" / "concurrent-message-competition-experiment.md")
    assert "Status: Implemented and published architecture note" in current_architecture
    assert "Ready for Spec" not in current_architecture
    assert "queues 未实现" not in current_architecture

    editorial_design = _read(DOCS_ROOT / "references" / "concurrent-message-editorial-ui-design" / "README.md")
    assert "renderer 已实现并已发布" in editorial_design
    assert "renderer 尚未实现" not in editorial_design

    historical_documents = {
        DOCS_ROOT / "architecture" / "interactive-mechanism-report.md": "Status: Superseded historical target",
        DOCS_ROOT
        / "prds"
        / "docs-architecture-and-jinjiang-latent-attributes-migration.md": "Status: Completed historical PRD; superseded",
        DOCS_ROOT
        / "decision-maps"
        / "refactor-test-hardening-2026-07.md": "Status: Completed historical decision map; superseded",
        DOCS_ROOT / "99-参考资料" / "README.md": "Status: Historical completed initial scan",
        DOCS_ROOT / "architecture" / "final-research-runtime.md": "Status: Historical single-message runtime baseline",
    }
    for path, marker in historical_documents.items():
        assert marker in _read(path), f"{path} should expose {marker!r}"


def test_concurrent_report_navigation_preserves_presentation_and_retention_semantics():
    durable_note = DOCS_ROOT / "architecture" / "concurrent-message-durable-execution.md"
    source_tree = DOCS_ROOT / "architecture" / "source-tree-and-entrypoints.md"
    durable_text = _read(durable_note)
    source_text = _read(source_tree)

    assert "explicit presentation destination 始终使用 Editorial default" in durable_text
    assert "in-place rebuild 仍按 persisted source report hash 选择历史兼容 bytes" in durable_text
    assert "普通 run 与 `contract-protected` Formal/release run" in durable_text
    assert "普通未受合同保护的 run 输出可以删除后重建" in source_text
    assert "contract-protected Formal/release roots 不能仅按目录类型推断删除" in source_text
    assert durable_text.count("```mermaid") == 8
    for heading in ("当前架构与调用关系", "目标架构与调用关系", "当前时序", "目标时序", "当前状态", "目标状态", "当前类关系", "目标类关系"):
        assert f"### {heading}" in durable_text



def test_retention_current_truth_navigation_contract():
    retention_note = DOCS_ROOT / "architecture" / "retention-audit.md"
    source_tree = DOCS_ROOT / "architecture" / "source-tree-and-entrypoints.md"
    references = DOCS_ROOT / "references" / "README.md"

    assert retention_note.exists()
    assert _linked_from(DOCS_ROOT / "architecture" / "README.md", retention_note)
    retention_text = _read(retention_note)
    source_text = _read(source_tree)
    references_text = _read(references)

    assert "Status: Implemented current architecture note" in retention_text
    assert "retention-manifest-v2" in retention_text
    assert "audit_valid=true" in retention_text
    assert "永不授权删除" in retention_text
    assert "contract-protected Formal/release roots" in source_text
    assert "不能仅按目录类型推断删除" in source_text
    assert "可随时删除重建" not in source_text
    assert "Historical repository retention audit baseline" in references_text
