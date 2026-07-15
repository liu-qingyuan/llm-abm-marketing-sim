import pytest

from llm_abm_sim.final_research_report import _ranking_field_lineage
from llm_abm_sim.research_explanations import ResearchExplanationCatalog, _pair_domain_tokens


def test_research_explanation_catalog_covers_every_lineage_field() -> None:
    lineage = _ranking_field_lineage()

    catalog = ResearchExplanationCatalog.from_lineage(lineage)

    assert set(catalog) == {entry.field_name for entry in lineage}
    assert all(
        (
            explanation.chinese_name,
            explanation.meaning,
            explanation.source,
            explanation.calculation,
            explanation.value_range,
            explanation.usage,
            explanation.interpretation,
            explanation.limitation,
        )
        for explanation in catalog.values()
    )


def test_research_explanation_catalog_describes_structured_field_shapes() -> None:
    catalog = ResearchExplanationCatalog.from_lineage(_ranking_field_lineage())

    for field_name in (
        "sample_comparison.base_source_scope_counts",
        "sample_comparison.final_source_scope_counts",
    ):
        assert catalog[field_name].value_range == "来源分组名称到非负人数的映射。"
        assert catalog[field_name].interpretation.startswith("不适用")
    assert catalog["ranking_rounds.selected_user_ids"].value_range == "0 个或多个 user_id（用户标识）组成的列表。"
    assert catalog["ranking_rounds.selected_user_ids"].interpretation.startswith("不适用")


def test_research_explanation_catalog_pairs_required_english_tokens_with_chinese() -> None:
    catalog = ResearchExplanationCatalog.from_lineage(_ranking_field_lineage())

    base_sample = catalog["sample_comparison.base_sample_count"]
    assert "network augmentation（网络补样）" in base_sample.meaning
    assert "source scope（来源分组）" in base_sample.meaning
    assert "network sample audit（网络样本审计）" in base_sample.source
    assert "Final Sample（最终样本）" in catalog["sample_comparison.final_sample_count"].meaning

    for explanation in catalog.values():
        for value in (
            explanation.meaning,
            explanation.source,
            explanation.calculation,
            explanation.value_range,
            explanation.usage,
            explanation.interpretation,
            explanation.limitation,
        ):
            assert _pair_domain_tokens(value) == value, explanation.field_name


@pytest.mark.parametrize("corruption", ["missing", "duplicate", "unknown"])
def test_research_explanation_catalog_rejects_lineage_contract_errors(corruption: str) -> None:
    lineage = _ranking_field_lineage()
    if corruption == "missing":
        lineage.pop()
    elif corruption == "duplicate":
        lineage[-1] = lineage[0]
    else:
        lineage[-1] = lineage[-1].model_copy(update={"field_name": "new_unexplained_field"})

    with pytest.raises(ValueError, match="duplicate|does not match"):
        ResearchExplanationCatalog.from_lineage(lineage)
