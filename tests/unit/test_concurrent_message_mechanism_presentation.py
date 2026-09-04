from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import llm_abm_sim
import llm_abm_sim.concurrent_message_mechanism_presentation as mechanism_module
from llm_abm_sim.concurrent_message_mechanism_presentation import _MECHANISM_PRESENTATION

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ASSET_ROOT = _REPO_ROOT / "src" / "llm_abm_sim" / "report_assets"
_REVIEW_PACKET = (
    _REPO_ROOT
    / "docs"
    / "references"
    / "concurrent-message-mechanism-semantic-masters-v4-review.md"
)


_EXPECTED_FILENAMES = (
    "mechanism-sample-first.mmd",
    "mechanism-pair-formation.mmd",
    "mechanism-independent-delivery.mmd",
    "mechanism-exposure-decisions.mmd",
    "mechanism-feedback-boundary.mmd",
    "real-batch-mechanism.mmd",
)
_FULL_POOL_FILENAME = "full-pool-mechanism.mmd"
_HISTORICAL_APPROVED_HASHES = {
    "mechanism-sample-first.mmd": "30786e0b98a576ab299b51e0aebceedb6b6d8fc03a7955ba56bc782bde594b81",
    "mechanism-pair-formation.mmd": "567859f204eed780ec8196aa1b23d6ed120e29a45161a442efa53fcf6431fb2e",
    "mechanism-independent-delivery.mmd": "a4c933e87ff25132434e8c890449d3c38326bf17b5da93309ab4f199513d3f87",
    "mechanism-exposure-decisions.mmd": "02ef23e190bb5fe5bbb313c3ac902201da8e44239f026189c529d75a0687bed8",
    "mechanism-feedback-boundary.mmd": "536a4de2b120e19a19b930c458ae481580541a8bc301a47cd7413a14b9e15675",
    "real-batch-mechanism.mmd": "73ea8c840faa315b0a5ee70b2958723fcf0fe140bfc000964a3d04c8f65bd907",
}


def test_interface_builds_one_deterministic_six_master_set() -> None:
    first = _MECHANISM_PRESENTATION.build()
    second = _MECHANISM_PRESENTATION.build()

    assert first == second
    assert first.schema_version == "concurrent-message-mechanism-presentation-v1"
    assert tuple(artifact.filename for artifact in first.mermaid_artifacts) == _EXPECTED_FILENAMES
    assert tuple(diagram.filename for diagram in first.diagrams) == _EXPECTED_FILENAMES
    assert re.fullmatch(r"[0-9a-f]{64}", first.semantic_set_identity_sha256)

    identity_document = {
        "schema_version": "mechanism-semantic-set-v1",
        "masters": [
            {"filename": artifact.filename, "sha256": artifact.sha256}
            for artifact in first.mermaid_artifacts
        ],
    }
    identity_bytes = (json.dumps(identity_document, sort_keys=True, separators=(",", ":")) + "\n").encode()
    assert hashlib.sha256(identity_bytes).hexdigest() == first.semantic_set_identity_sha256
    for artifact in first.mermaid_artifacts:
        assert artifact.payload.endswith(b"\n")
        assert hashlib.sha256(artifact.payload).hexdigest() == artifact.sha256


def test_semantic_records_have_three_lane_ownership_bilingual_parity_and_budgets() -> None:
    presentation = _MECHANISM_PRESENTATION.build()
    artifacts = {artifact.filename: artifact.payload.decode() for artifact in presentation.mermaid_artifacts}

    assert presentation.lane_order == (
        "historical_data",
        "platform_recommendation",
        "simulated_user_decision",
    )
    for index, diagram in enumerate(presentation.diagrams):
        assert diagram.lane_order == presentation.lane_order
        assert len(diagram.nodes) <= diagram.node_budget
        if index < 5:
            assert diagram.stage_count <= 5
        else:
            assert len(diagram.nodes) <= 8
        assert {projection.language for projection in diagram.projections} == {"zh-CN", "en-US"}

        zh = next(projection for projection in diagram.projections if projection.language == "zh-CN")
        en = next(projection for projection in diagram.projections if projection.language == "en-US")
        assert zh.keys == en.keys
        assert all(value.strip() for value in zh.values)
        assert all(value.strip() for value in en.values)
        assert zh.fallback_keys == en.fallback_keys
        assert len(zh.fallback_values) == len(en.fallback_values)

        node_ids = {node.semantic_id for node in diagram.nodes}
        assert len(node_ids) == len(diagram.nodes)
        assert all(re.fullmatch(r"[a-z][a-z0-9_]*", node_id) for node_id in node_ids)
        assert all(node.lane in presentation.lane_order for node in diagram.nodes)
        assert {node.stage for node in diagram.nodes} == set(range(1, diagram.stage_count + 1))
        assert len({edge.semantic_id for edge in diagram.edges}) == len(diagram.edges)
        assert all(re.fullmatch(r"[a-z][a-z0-9_]*", edge.semantic_id) for edge in diagram.edges)
        assert all(edge.source in node_ids and edge.target in node_ids for edge in diagram.edges)

        mermaid = artifacts[diagram.filename]
        assert f"dom-title-key: {diagram.title_key}" in mermaid
        assert f"dom-description-key: {diagram.description_key}" in mermaid
        for node in diagram.nodes:
            assert node.semantic_id in mermaid
            assert f"dom-node-key: {node.semantic_id}={node.label_key}" in mermaid
            assert f'{zh.value(node.label_key)}<br/>{en.value(node.label_key)}' in mermaid
        for fallback_key in zh.fallback_keys:
            assert f"fallback-key: {fallback_key}" in mermaid
        assert diagram.image_brief.visual_system in mermaid
        assert diagram.image_brief.purpose in mermaid
        assert diagram.image_brief.composition in mermaid
        for lane in presentation.lane_order:
            assert f"subgraph {lane}_lane" in mermaid


def test_master_set_locks_sample_capacity_same_exposure_and_feedback_invariants() -> None:
    diagrams = {
        diagram.diagram_id: diagram
        for diagram in _MECHANISM_PRESENTATION.build().diagrams
    }

    sample = diagrams["sample_first"]
    sample_nodes = {node.semantic_id: node for node in sample.nodes}
    assert sample_nodes["research_sample_1000"].stage == 5
    assert {node.semantic_id for node in sample.nodes} == {
        "eligible_user_pool",
        "influence_seed_union",
        "seed_direct_neighbors",
        "quota_regular_users",
        "research_sample_1000",
    }

    pairs = diagrams["pair_formation"]
    pair_nodes = {node.semantic_id for node in pairs.nodes}
    assert {
        "eligible_pairs_m1",
        "eligible_pairs_m2",
        "eligible_pairs_m3",
        "eligible_pairs_total_3000",
    } <= pair_nodes
    assert {edge.source for edge in pairs.edges if edge.target == "eligible_pairs_total_3000"} == {
        "eligible_pairs_m1",
        "eligible_pairs_m2",
        "eligible_pairs_m3",
    }
    pair_text = " ".join(next(p for p in pairs.projections if p.language == "en-US").values)
    assert "1,000 Users × 3 Messages = 3,000 Eligible Pairs" in pair_text
    assert not ({"queue", "exposure", "decision"} & pair_nodes)

    delivery = diagrams["independent_delivery"]
    delivery_nodes = {node.semantic_id for node in delivery.nodes}
    capacities = {
        "message_1_capacity_600",
        "message_2_capacity_600",
        "message_3_capacity_600",
    }
    assert capacities <= delivery_nodes
    assert {edge.target for edge in delivery.edges if edge.source == "shared_seed_launch"} == capacities
    delivery_text = " ".join(next(p for p in delivery.projections if p.language == "en-US").values)
    assert delivery_text.count("30 × Top20 = 600 Capacity") == 3
    assert "do not share one 20-slot quota" in delivery_text

    decisions = diagrams["exposure_decisions"]
    decision_nodes = {node.semantic_id: node for node in decisions.nodes}
    fork = [edge for edge in decisions.edges if edge.source == "exposed_pair"]
    assert {edge.target for edge in fork} == {
        "primary_campaign_decision",
        "report_only_shadow_decision",
    }
    assert {edge.label.key for edge in fork if edge.label is not None} == {
        "exposure_decisions.edge.same_exposure"
    }
    assert decision_nodes["primary_campaign_decision"].stage == 5
    assert decision_nodes["report_only_shadow_decision"].stage == 5

    feedback = diagrams["feedback_boundary"]
    stop_nodes = {
        "shadow_terminal_no_feedback",
        "ignore_terminal_no_feedback",
        "provider_failed_terminal_no_feedback",
    }
    assert not [edge for edge in feedback.edges if edge.source in stop_nodes]
    endpoints = {(edge.source, edge.target) for edge in feedback.edges}
    assert (
        "primary_succeeded_positive",
        "pending_positive_user_ids",
    ) in endpoints
    assert ("pending_positive_user_ids", "campaign_user_id_commit") in endpoints
    assert ("full_batch_barrier", "campaign_user_id_commit") in endpoints
    assert (
        "campaign_user_id_commit",
        "next_batch_ranking_contexts",
    ) in endpoints
    assert not [edge for edge in feedback.edges if edge.target == "full_batch_barrier"]


def test_committed_masters_and_low_fidelity_review_packet_match_the_interface() -> None:
    presentation = _MECHANISM_PRESENTATION.build()

    for artifact in presentation.mermaid_artifacts:
        assert (_ASSET_ROOT / artifact.filename).read_bytes() == artifact.payload

    review = _REVIEW_PACKET.read_text(encoding="utf-8")
    assert "Status: Awaiting whole-set human approval" in review
    assert "Provider/API/image-generation calls: `0`" in review
    assert presentation.semantic_set_identity_sha256 in review
    positions = [review.index(artifact.filename) for artifact in presentation.mermaid_artifacts]
    assert positions == sorted(positions)
    assert review.count("```mermaid") == 6
    for artifact in presentation.mermaid_artifacts:
        assert artifact.sha256 in review
        assert artifact.payload.decode().strip() in review
    for diagram in presentation.diagrams:
        assert diagram.image_brief.purpose in review


def test_full_pool_master_is_additive_bilingual_and_keeps_historical_bytes_exact() -> None:
    historical_before = {
        filename: (_ASSET_ROOT / filename).read_bytes()
        for filename in _HISTORICAL_APPROVED_HASHES
    }

    first = _MECHANISM_PRESENTATION.build_full_pool_master()
    second = _MECHANISM_PRESENTATION.build_full_pool_master()

    assert first == second
    assert tuple(diagram.filename for diagram in first.diagrams) == (_FULL_POOL_FILENAME,)
    assert tuple(artifact.filename for artifact in first.mermaid_artifacts) == (_FULL_POOL_FILENAME,)
    diagram = first.diagrams[0]
    artifact = first.mermaid_artifacts[0]
    node_ids = {node.semantic_id for node in diagram.nodes}
    edge_pairs = {(edge.source, edge.target) for edge in diagram.edges}
    assert len(diagram.nodes) <= 8
    assert diagram.image_brief.generate_raster is False
    assert {projection.language for projection in diagram.projections} == {"zh-CN", "en-US"}
    assert {
        "full_eligible_pool_36400",
        "eligible_pairs_109200",
        "independent_queues_30_batches",
        "exposure_gate",
        "primary_only_decision",
        "full_batch_barrier",
        "next_batch_ranking_context",
        "complete_three_message_coverage",
    } == node_ids
    assert ("primary_only_decision", "full_batch_barrier") in edge_pairs
    assert ("full_batch_barrier", "next_batch_ranking_context") in edge_pairs
    assert ("next_batch_ranking_context", "independent_queues_30_batches") in edge_pairs
    assert (_ASSET_ROOT / _FULL_POOL_FILENAME).read_bytes() == artifact.payload
    assert artifact.sha256 == hashlib.sha256(artifact.payload).hexdigest()
    assert b"36,400" in artifact.payload
    assert b"109,200" in artifact.payload
    assert b"1,214 / 1,194" in artifact.payload
    assert b"Primary-only" in artifact.payload

    historical_after = {
        filename: (_ASSET_ROOT / filename).read_bytes()
        for filename in _HISTORICAL_APPROVED_HASHES
    }
    assert historical_after == historical_before
    assert {
        filename: hashlib.sha256(payload).hexdigest()
        for filename, payload in historical_after.items()
    } == _HISTORICAL_APPROVED_HASHES


def test_two_stage_full_pool_master_has_one_bilingual_semantic_owner_and_new_bytes() -> None:
    historical_before = {
        filename: (_ASSET_ROOT / filename).read_bytes()
        for filename in _HISTORICAL_APPROVED_HASHES
    }
    legacy = _MECHANISM_PRESENTATION.build_full_pool_master()

    first = _MECHANISM_PRESENTATION.build_full_pool_two_stage_master()
    second = _MECHANISM_PRESENTATION.build_full_pool_two_stage_master()

    assert first == second
    assert first.schema_version == "full-pool-two-stage-mechanism-presentation-v1"
    assert tuple(diagram.filename for diagram in first.diagrams) == (_FULL_POOL_FILENAME,)
    assert tuple(artifact.filename for artifact in first.mermaid_artifacts) == (_FULL_POOL_FILENAME,)
    diagram = first.diagrams[0]
    artifact = first.mermaid_artifacts[0]
    node_ids = {node.semantic_id for node in diagram.nodes}
    edge_by_id = {edge.semantic_id: (edge.source, edge.target) for edge in diagram.edges}
    assert node_ids == {
        "full_eligible_pool_36400",
        "eligible_pairs_109200",
        "independent_queues_30_batches",
        "exposure_gate",
        "provider_judgment",
        "judgment_gate",
        "stable_probability_draw",
        "realized_outcome",
        "full_batch_barrier",
        "realized_feedback",
        "next_batch_ranking_context",
        "realized_projection",
    }
    assert edge_by_id == {
        "full_pool_to_pairs": ("full_eligible_pool_36400", "eligible_pairs_109200"),
        "pairs_to_queues": ("eligible_pairs_109200", "independent_queues_30_batches"),
        "queues_to_exposure": ("independent_queues_30_batches", "exposure_gate"),
        "exposure_to_provider_judgment": ("exposure_gate", "provider_judgment"),
        "judgment_to_gate": ("provider_judgment", "judgment_gate"),
        "provider_ignore_to_outcome": ("judgment_gate", "realized_outcome"),
        "positive_gate_to_draw": ("judgment_gate", "stable_probability_draw"),
        "draw_to_outcome": ("stable_probability_draw", "realized_outcome"),
        "outcome_to_barrier": ("realized_outcome", "full_batch_barrier"),
        "barrier_to_realized_feedback": ("full_batch_barrier", "realized_feedback"),
        "feedback_to_next_batch": ("realized_feedback", "next_batch_ranking_context"),
        "next_batch_feedback": ("next_batch_ranking_context", "independent_queues_30_batches"),
        "next_batch_to_projection": ("next_batch_ranking_context", "realized_projection"),
    }
    assert diagram.stage_count == 12
    assert diagram.node_budget == 12
    assert {projection.language for projection in diagram.projections} == {"zh-CN", "en-US"}
    assert artifact.payload != legacy.mermaid_artifacts[0].payload
    assert artifact.sha256 == hashlib.sha256(artifact.payload).hexdigest()
    assert b"Provider Judgment" in artifact.payload
    assert b"Stable Probability Draw" in artifact.payload
    assert b"Realized Feedback" in artifact.payload
    assert b"Realized Projection" in artifact.payload
    assert b"realized_reason" not in artifact.payload
    assert {
        filename: (_ASSET_ROOT / filename).read_bytes()
        for filename in _HISTORICAL_APPROVED_HASHES
    } == historical_before


def test_robustness_v2_master_owns_twenty_cell_two_stage_mermaid_svg_and_fallback() -> None:
    historical_before = {
        filename: (_ASSET_ROOT / filename).read_bytes()
        for filename in _HISTORICAL_APPROVED_HASHES
    }

    first = _MECHANISM_PRESENTATION.build_robustness_v2_master()
    second = _MECHANISM_PRESENTATION.build_robustness_v2_master()

    assert first == second
    assert first.schema_version == "concurrent-robustness-v2-mechanism-presentation-v1"
    assert tuple(artifact.filename for artifact in first.mermaid_artifacts) == (
        "prompt-model-realized-mechanism.mmd",
    )
    diagram = first.diagrams[0]
    artifact = first.mermaid_artifacts[0]
    node_ids = {node.semantic_id for node in diagram.nodes}
    edge_pairs = {(edge.source, edge.target) for edge in diagram.edges}
    assert node_ids == {
        "frozen_research_boundary",
        "canonical_prompt_matrix",
        "five_provider_conditions",
        "twenty_independent_cells",
        "provider_judgment",
        "judgment_gate",
        "shared_realization_draw",
        "realized_outcome",
        "full_batch_barrier",
        "realized_positive_feedback",
        "next_batch_ranking",
        "realized_main_projection",
    }
    assert ("provider_judgment", "judgment_gate") in edge_pairs
    assert ("judgment_gate", "shared_realization_draw") in edge_pairs
    assert ("shared_realization_draw", "realized_outcome") in edge_pairs
    assert ("realized_outcome", "full_batch_barrier") in edge_pairs
    assert ("full_batch_barrier", "realized_positive_feedback") in edge_pairs
    assert ("realized_positive_feedback", "next_batch_ranking") in edge_pairs
    assert ("next_batch_ranking", "twenty_independent_cells") in edge_pairs
    assert b"20 Independent Prompt-Model Cells" in artifact.payload
    assert b"Provider Judgment" in artifact.payload
    assert b"Shared Deterministic Draw" in artifact.payload
    assert b"Realized-Positive Feedback" in artifact.payload
    assert b"realized_reason" not in artifact.payload

    for language in ("zh-CN", "en-US"):
        svg = _MECHANISM_PRESENTATION.render_inline_svg(first, language=language)
        fallback = _MECHANISM_PRESENTATION.render_fallback(first, language=language)
        assert f'data-mechanism-language="{language}"' in svg
        assert f'data-mechanism-language="{language}"' in fallback
        for node in diagram.nodes:
            assert f'data-mechanism-node-id="{node.semantic_id}"' in svg
        for edge in diagram.edges:
            assert f'data-mechanism-edge-id="{edge.semantic_id}"' in svg
        projection = next(item for item in diagram.projections if item.language == language)
        for key in projection.fallback_keys:
            assert f'data-mechanism-fallback-key="{key}"' in fallback
    assert {
        filename: (_ASSET_ROOT / filename).read_bytes()
        for filename in _HISTORICAL_APPROVED_HASHES
    } == historical_before


def test_module_has_one_package_internal_interface_and_no_public_export() -> None:
    interface_types = [
        name
        for name, value in vars(mechanism_module).items()
        if isinstance(value, type) and name.endswith("Interface")
    ]
    assert interface_types == ["_MechanismPresentationInterface"]
    assert mechanism_module.__all__ == []
    assert not hasattr(llm_abm_sim, "MechanismPresentationInterface")
    assert not hasattr(llm_abm_sim, "MECHANISM_PRESENTATION")

    presentation = _MECHANISM_PRESENTATION.build()
    assert all(len(diagram.projections) == 2 for diagram in presentation.diagrams)
    assert sum(diagram.image_brief.generate_raster for diagram in presentation.diagrams) == 5


def test_three_layer_vocabulary_and_adr_0006_record_the_stable_decision() -> None:
    context = (_REPO_ROOT / "CONTEXT.md").read_text(encoding="utf-8")
    for heading, chinese_name, prohibited_reading in (
        ("Historical Data Layer", "历史数据层", "runtime live database"),
        ("Platform Recommendation Layer", "平台推荐层", "LLM"),
        ("Simulated User Decision Layer", "模拟用户决策层", "不创建 Research Sample"),
    ):
        section = context.split(f"### {heading}", 1)[1].split("\n### ", 1)[0]
        assert chinese_name in section
        assert prohibited_reading in section

    adr = (
        _REPO_ROOT
        / "docs"
        / "adr"
        / "0006-use-mermaid-first-single-owner-mechanism-presentation.md"
    ).read_text(encoding="utf-8")
    for decision in (
        "Mermaid-first",
        "Single owner",
        "完整双语投影",
        "两次整组审批",
        "Additive release",
    ):
        assert decision in adr
    assert "Status: Accepted (architecture decision; semantic master set approval pending)" in adr
    assert "当前 v1/v6 presentation" in adr
