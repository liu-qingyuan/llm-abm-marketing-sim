from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = REPO_ROOT / "docs"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _local_markdown_links(source: Path) -> list[tuple[str, Path]]:
    links: list[tuple[str, Path]] = []
    for match in re.finditer(r"\[([^\]]+)\]\(([^)#]+)(?:#[^)]+)?\)", _read(source)):
        label = match.group(1)
        raw_target = match.group(2)
        if "://" in raw_target:
            continue
        target = (source.parent / raw_target).resolve()
        if target.is_dir():
            target = target / "README.md"
        links.append((label, target))
    return links


def _local_markdown_targets(source: Path) -> set[Path]:
    return {target for _, target in _local_markdown_links(source)}


def _linked_from(source: Path, target: Path) -> bool:
    return target.resolve() in _local_markdown_targets(source)


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

    index = DOCS_ROOT / "index.md"
    for entrypoint in expected_entrypoints[1:6]:
        assert _linked_from(index, entrypoint), f"{index} should link to {entrypoint}"


def test_legacy_development_validation_readme_is_a_migration_redirect():
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


def test_jinjiang_latent_attribute_entrypoints_are_discoverable():
    legacy_readme = DOCS_ROOT / "04-开发验证" / "README.md"
    docs_index = DOCS_ROOT / "index.md"
    discoverable_links = _local_markdown_links(legacy_readme) + _local_markdown_links(docs_index)

    def has_link(label_terms: tuple[str, ...], path_terms: tuple[str, ...]) -> bool:
        for label, target in discoverable_links:
            label_text = label.lower()
            path_text = target.relative_to(REPO_ROOT).as_posix().lower()
            if target.exists() and all(term in label_text or term in path_text for term in label_terms + path_terms):
                return True
        return False

    assert has_link(("latent", "reference"), ())
    assert has_link((), ("jinjiang", "data-structure")) or has_link(("数据结构",), ())
    assert has_link((), ("prds", "latent"))


def test_jinjiang_latent_attribute_prd_has_status_and_planning_headings():
    prd = DOCS_ROOT / "prds" / "docs-architecture-and-jinjiang-latent-attributes-migration.md"
    prd_text = _read(prd)

    assert "当前代码状态" in prd_text
    assert re.search(r"^##\s+超出范围$", prd_text, flags=re.MULTILINE)
    assert "后续 issue plan" in prd_text
    assert "验收标准" in prd_text or "测试决策" in prd_text
