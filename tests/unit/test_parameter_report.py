"""Report rendering remains evidence-derived, including process versus endpoint diagnostics."""
import xml.etree.ElementTree as ET

from llm_abm_sim._parameter_report import render


def _fixture():
    messages = ['message_1','message_2','message_3','message_1-message_2',
                'message_1-message_3','message_2-message_3']
    comparisons = []
    rates = []
    trajectories = []
    for w in range(7):
        for h in (1,3,6):
            config = f'w{w}-h{h}'
            for index, contrast in enumerate(messages[3:]):
                halfwidth = .005118 if index == 0 else .004
                comparisons.append({'configuration':config,'contrast':contrast,'direction':'positive',
                    'amplitude':'baseline' if config=='w0-h3' else 'equivalent_in_tested_range',
                    'difference_mean':.1,'difference_lower':.08,'difference_upper':.12,
                    'delta_mean':0.,'delta_lower':0.,'delta_upper':0.,
                    'difference_ordinary_lower':.1-halfwidth,'difference_ordinary_upper':.1+halfwidth,
                    'delta_ordinary_lower':0.,'delta_ordinary_upper':0.,'mc_precision_met':index!=0})
            for message in messages[:3]:
                rates.append({'configuration':config,'message':message,'mean':.5,'lower':.4,
                              'upper':.6,'historical_exposure_mean':600})
            for batch in range(1,31):
                for message in messages:
                    trajectories.append({'configuration':config,'batch':batch,'message':message,
                        'mean_cumulative_rate':.5,'seed_q025':.4,'seed_q975':.6,
                        'mean_cumulative_count':batch*10.,'seed_count_q025':batch*8.,
                        'seed_count_q975':batch*12.})
    evidence = {'comparisons':comparisons,'rates':rates,'simultaneous_t_critical':3.66,
        'collection':{'known_nominal_cost_usd':10.,'new_successes':1200,'physical_requests':1201,
            'qualification_requests':1,'retry_requests':0,'maximum_observed_in_flight':5,
            'authorized_maximum_concurrency':5,'nominal_cost_unknown_attempts':0,
            'known_response_usage':{'total_tokens':1234},'response_usage_missing_attempts':0},
        'new_collection_window':['start','end'],'bank_sha256':'bank','study_manifest_sha256':'study',
        'path_diagnostics_summary':{'paired_paths':2000,'same_final_exposure_set_as_baseline':2000,
            'changed_exposure_order_from_baseline':2000,'changed_batch_assignments_from_baseline':1900,
            'identical_endpoint_rates_to_baseline':2000,'historical_exposures':3780000,'topup_exposures':0,
            'unique_final_exposure_sets':1,'unique_order_counts_per_seed_min':20,
            'unique_order_counts_per_seed_max':21},
        'trajectory_baseline_maxima':[{'message':m,'configuration':'w6-h6','batch':5,
                                     'delta_mean_cumulative_rate':.0794} for m in messages]}
    return evidence, trajectories


def test_report_renders_count_curves_diagnostics_precision_and_weight_mapping(tmp_path):
    evidence, trajectories = _fixture()
    render(tmp_path,evidence,trajectories)
    assert len(list(tmp_path.glob('*.svg'))) == 27
    assert len(list(tmp_path.glob('*-count-h*.svg'))) == 9
    for svg in tmp_path.glob('*.svg'):
        ET.fromstring(svg.read_text())
    count = (tmp_path/'message_1-count-h3.svg').read_text()
    assert '累计互动人数' in count and '人</text>' in count and '%' not in count
    assert '%' in (tmp_path/'message_1-h3.svg').read_text()
    page = (tmp_path/'report.html').read_text()
    summary = (tmp_path/'summary.md').read_text()
    for output in (page,summary):
        assert '2000条最终曝光集合同一' in output
        assert '2000条曝光顺序变化' in output
        assert '1900条跨批曝光分配变化' in output
        assert '补采判断曝光数0' in output
        assert '终值严格一致' in output and '这不代表过程或普遍不敏感' in output
        assert 'MC精度不足21/63条' in output and '0.5118pp' in output
        assert '+7.9400pp' in output and '不是全时程显著性判据' in output
    for index in range(7):
        assert f'<td>w{index}</td>' in page
    assert '<td>0.65</td><td>0.15</td><td>0.20</td>' in page
    assert 'h=1/3/6交叉' in page


def test_nonidentical_exposure_sets_do_not_trigger_mechanical_identity_claim(tmp_path):
    evidence, trajectories = _fixture()
    evidence['path_diagnostics_summary']['same_final_exposure_set_as_baseline'] = 1999
    render(tmp_path,evidence,trajectories)
    assert '终值严格一致是这组曝光集合下的机械结果' not in (tmp_path/'summary.md').read_text()
