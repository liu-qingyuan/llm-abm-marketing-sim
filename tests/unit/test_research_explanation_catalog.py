import re

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
    catalog = ResearchExplanationCatalog.from_lineage(
        _ranking_field_lineage(),
        include_target_aggregate_reference=True,
    )

    for field_name in (
        "sample_comparison.base_source_scope_counts",
        "sample_comparison.final_source_scope_counts",
    ):
        assert catalog[field_name].value_range == "来源分组名称到非负人数的映射。"
        assert catalog[field_name].interpretation.startswith("不适用")
    assert catalog["ranking_rounds.selected_user_ids"].value_range == "0 个或多个 user_id（用户标识）组成的列表。"
    assert catalog["ranking_rounds.selected_user_ids"].interpretation.startswith("不适用")
    historical_diagnostic = catalog["ranking_diagnostics.historical_top20_diagnostic"]
    assert "top20_holdout_diagnostic.json" in historical_diagnostic.source
    assert "原始聚合互动参考" in historical_diagnostic.meaning
    assert "真实曝光分母" in historical_diagnostic.limitation
    assert "用户级归属" in historical_diagnostic.limitation
    assert "互斥" in historical_diagnostic.limitation

    historical_catalog = ResearchExplanationCatalog.from_lineage(_ranking_field_lineage())
    historical = historical_catalog["ranking_diagnostics.historical_top20_diagnostic"]
    assert "原始聚合互动参考" not in historical.meaning
    assert "top20_holdout_diagnostic.json" not in historical.source


def test_research_explanation_catalog_owns_concept_and_chart_templates() -> None:
    document = ResearchExplanationCatalog.from_lineage(_ranking_field_lineage()).as_document()

    assert set(document["concept_explanations"]) == {
        "sample",
        "lineage",
        "ranking",
        "network",
        "prompt",
        "aggregate",
        "users",
    }
    assert set(document["chart_explanations"]) == {
        "sample-composition-explanation",
        "batch-delivery-explanation",
        "action-status-explanation",
        "provider-failure-explanation",
        "network-activation-explanation",
        "ablation-overlap-explanation",
    }
    assert set(next(iter(document["concept_explanations"].values()))) == {"what", "why", "formation", "result"}
    assert set(next(iter(document["chart_explanations"].values()))) == {
        "measurement",
        "denominator",
        "purpose",
        "result",
    }


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
            without_paired_tokens = re.sub(
                r"[A-Za-z][A-Za-z0-9_./-]*(?: [A-Za-z0-9_./-]+)*（[^）]+）",
                "",
                value,
            )
            assert not re.search(r"[A-Za-z][A-Za-z0-9_./-]*", without_paired_tokens), (
                explanation.field_name,
                without_paired_tokens,
            )


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
