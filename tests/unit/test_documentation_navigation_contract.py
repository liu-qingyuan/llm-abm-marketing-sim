from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = REPO_ROOT / "docs"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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
