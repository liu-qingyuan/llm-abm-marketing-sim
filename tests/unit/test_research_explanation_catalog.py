import pytest

from llm_abm_sim.final_research_report import _ranking_field_lineage
from llm_abm_sim.research_explanations import ResearchExplanationCatalog


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
