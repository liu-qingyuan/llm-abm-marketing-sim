from pathlib import Path

import pytest

from llm_abm_sim.concurrent_robustness_revised import close_revised_evidence


def test_revised_closure_rejects_unbound_delivery(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Evidence"):
        close_revised_evidence(tmp_path, evidence_sha256="0" * 64)


def _evidence():
    from llm_abm_sim.concurrent_robustness_revised import MESSAGES, MODELS, PROMPTS, ClosedRevisedEvidence
    rows, commits = [], []
    for model in MODELS:
        for prompt in PROMPTS:
            cumulative = set()
            for batch in range(30):
                positives = set()
                for message in MESSAGES:
                    for i in range(20):
                        user = str(batch * 20 + i)
                        positive = prompt == "P1" or i % 2 == 0
                        rows.append(dict(requested_model=model, prompt_variant=prompt, cell_id=f"{prompt}::{model}",
                            user_id=user, message_id=message, time_step=batch, provider_engage=positive,
                            provider_probability=0.7, provider_confidence=0.8, observed_model=model,
                            provider_action="like" if positive else "ignore", realized_engage=positive,
                            realized_action="like" if positive else "ignore"))
                        if positive:
                            positives.add(user)
                commits.append(dict(cell_id=f"{prompt}::{model}", time_step=batch,
                    frozen_campaign_engaged_user_ids=sorted(cumulative), committed_realized_positive_user_ids=sorted(positives)))
                cumulative |= positives
    return ClosedRevisedEvidence(Path('/not-production'), {'identity_sha256':'0'*64,'identity_strata':[],'counts':{}},
        (), tuple(rows), tuple(commits), {str(i):'S1' for i in range(1000)}, tuple(str(i) for i in range(20)), (), {})


def test_analysis_keeps_seed_panel_separate_and_growth_deduplicated():
    from llm_abm_sim.concurrent_robustness_revised import analyze_revised_evidence
    e = _evidence()
    a = analyze_revised_evidence(e)
    assert a == analyze_revised_evidence(e)
    assert len(a['curves']) == 1440
    assert len(a['segment_message_slices']) == 144
    assert a['seed_pairs_per_cell'] == 60
    p1 = next(r for r in a['direct'] if r['prompt']=='P1' and r['message']=='all' and r['comparison']=='prompt_within_model')
    assert p1['pairs'] == 60 and p1['user_blocks'] == 20
    assert p1['engage_delta'] == 0.5
    assert p1['engage_disagreements'] == 30
    assert p1['direct_probability_label'] == 'small_observed_difference'
    assert a['growth'][0]['cumulative_positive_users'] == 10
    assert a['cells'][0]['exposures'] == 1800
    assert a['cells'][0]['campaign_positive_users'] == 300
    assert all(r['scope']=='descriptive_adaptive_path' for r in a['realized_contrasts'])


def test_analysis_rejects_missing_predeclared_seed_and_crossed_growth():
    from dataclasses import replace

    from llm_abm_sim.concurrent_robustness_revised import analyze_revised_evidence
    e = _evidence()
    with pytest.raises(ValueError,match='seed/message'):
        analyze_revised_evidence(replace(e, seed_users=(*e.seed_users,'absent')))
    changed = list(e.commits)
    changed[0] = {**changed[0], 'committed_realized_positive_user_ids': []}
    with pytest.raises(ValueError,match='barrier'):
        analyze_revised_evidence(replace(e, commits=tuple(changed)))


def test_report_preserves_history_and_downloads_share_analysis():
    import json
    from dataclasses import replace

    from llm_abm_sim.concurrent_robustness_revised import analyze_revised_evidence
    from llm_abm_sim.concurrent_robustness_revised_report import render_revised_research, revised_downloads
    e = _evidence()
    e = replace(e, document={**e.document, 'identity_strata': [dict(model='deepseek-v4-flash', prompt='P0', observed_model='deepseek-v4-flash', route='official', judgments=1800)]})
    a = analyze_revised_evidence(e)
    old = b'<meta name="abm-release-id" content="old"><meta name="abm-release-contract" content="abm-report-release-contract-v13"><main>PROTECTED MAIN</main><section class="robustness-section" data-testid="prompt-model-robustness-section" aria-labelledby="prompt-model-title">PROTECTED HISTORY</section>'
    candidate = render_revised_research(old, e, a)
    released = render_revised_research(old, e, a, release_id='release-v15')
    assert b'data-release-state="candidate"' in candidate
    assert b'data-release-state="production"' in released
    assert released.endswith(old[old.index(b'<section'):])
    assert b'<main>PROTECTED MAIN</main>' in released
    assert b'abm-report-release-contract-v15' in released
    assert b'28,800' in released and b'7167' in released and b'unknown/null' in released
    downloads = revised_downloads(e, a)
    assert len(downloads) == 13
    assert json.loads(downloads['revised-robustness/analysis.json']) == a
    assert len(a['planned_contrasts']) == 6
    assert len(a['prompt_model_interactions']) == 9
    assert all(r['rate_delta'] == 0 for r in a['prompt_model_interactions'])
    with pytest.raises(ValueError, match='anchor'):
        render_revised_research(released, e, a)


def test_release_rejects_fixture_and_invalid_identity(tmp_path):
    from llm_abm_sim.revised_robustness_release import (
        promote_revised_research_release,
        require_revised_deployment_profile,
        validate_revised_research_release,
    )
    with pytest.raises(ValueError, match='fields'):
        validate_revised_research_release(repo_root=tmp_path, contract_document={'production_deploy_eligible':True}, source_dir=tmp_path)
    with pytest.raises(ValueError, match='Formal'):
        require_revised_deployment_profile({'schema_version':'abm-report-release-contract-v15','production_deploy_eligible':True,'provider_calls':0})
    with pytest.raises(ValueError, match='invalid'):
        promote_revised_research_release(repo_root=tmp_path, verified_source=tmp_path/'input', evidence_sha256='0'*64, protected_v13_contract=tmp_path/'baseline', destination_dir=tmp_path/'release', release_id='../escape', implementation_commit='a'*40)
    with pytest.raises(ValueError, match='overlaps'):
        promote_revised_research_release(repo_root=tmp_path, verified_source=tmp_path/'input', evidence_sha256='0'*64, protected_v13_contract=tmp_path/'baseline', destination_dir=tmp_path/'input'/'release', release_id='release', implementation_commit='a'*40)
