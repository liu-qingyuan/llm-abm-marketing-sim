import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { expect, test, type Locator, type Page, type TestInfo } from '@playwright/test';

type RankingUser = {
  user_id: string;
  nickname: string;
  interest_tags: string[];
  reason: string;
  result_status: string;
  sample_source_scope: string;
  sample_role: string;
  is_seed: boolean;
  is_network_cohort: boolean;
};

type RankingCandidate = {
  ranking_position: number;
  user_id: string;
  is_seed: boolean;
  selected: boolean;
  base_network_relevance: number;
  engaged_neighbor_signal: number;
  historical_tag_affinity: number;
  recommendation_score: number;
};

type SensitivityVariant = {
  variant_id: string;
  weights: {
    base_network: number;
    engaged_neighbor: number;
    tag_affinity: number;
  };
  batches: Array<{
    overlap_with_main_user_ids: string[];
    added_vs_main_user_ids: string[];
  }>;
};

type RankingPayload = {
  users: RankingUser[];
  target_video: {
    video_url: string;
  };
  sample_comparison: {
    base_sample_count: number;
    final_sample_count: number;
    seed_count: number;
    network_cohort_count: number;
    replacement_count: number;
  };
  field_lineage: Array<{
    field_name: string;
  }>;
  run: {
    horizon: number;
    delivery_capacity: number;
  };
  ranking_rounds: Array<{
    time_step: number;
    candidates: RankingCandidate[];
  }>;
  ranking_diagnostics_summary: {
    batches_with_top_selection_change: number;
    main_weights: {
      base_network: number;
      engaged_neighbor: number;
      tag_affinity: number;
    };
  };
  ranking_diagnostics: {
    weight_sensitivity: {
      variants: SensitivityVariant[];
    };
  };
  downloads: Record<string, string>;
};

type CandidateWithBatch = RankingCandidate & { time_step: number };

function selectWorkedCandidate(payload: RankingPayload): CandidateWithBatch {
  const evidence = payload.ranking_rounds.flatMap((round) =>
    round.candidates.map((candidate) => ({ time_step: round.time_step, ...candidate })),
  );
  const candidate = evidence.find(
    (row) => !row.is_seed && row.selected && row.engaged_neighbor_signal > 0,
  ) ?? evidence.find((row) => !row.is_seed && row.selected) ?? evidence[0];
  if (!candidate) throw new Error('ranking report requires at least one persisted candidate');
  return candidate;
}

function sensitivityAverages(variant: SensitivityVariant): { overlap: number; changed: number } {
  const divisor = Math.max(1, variant.batches.length);
  return {
    overlap:
      variant.batches.reduce((total, batch) => total + batch.overlap_with_main_user_ids.length, 0) /
      divisor,
    changed:
      variant.batches.reduce((total, batch) => total + batch.added_vs_main_user_ids.length, 0) /
      divisor,
  };
}

function generateRankingReport(
  testInfo: TestInfo,
  fixtureKind: 'capacity' | 'effect' = 'capacity',
): { outputDir: string; payload: RankingPayload } {
  const fixtureDir = path.join(testInfo.outputDir, `processed-ranking-fixture-${fixtureKind}`);
  const outputDir = path.join(testInfo.outputDir, `ranking-report-${fixtureKind}`);
  const testModule = path.resolve('tests/integration/test_final_research_runner.py');
  execFileSync(path.resolve('.venv/bin/python'), ['-c', `
import importlib.util
import sys
from pathlib import Path

from llm_abm_sim import FinalResearchConfig, FinalResearchRunner
from llm_abm_sim.schemas import ProviderLLMConfig

test_module, fixture_path, output_path, fixture_kind = sys.argv[1:]
spec = importlib.util.spec_from_file_location("final_research_test_support", test_module)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if fixture_kind == "effect":
    fixture_dir = module._make_target_delivery_fixture(Path(fixture_path))
    sample_size = 70
    failed_user_id = "u79"
else:
    fixture_dir = module._make_processed_fixture(Path(fixture_path), user_count=1010)
    sample_size = 1000
    failed_user_id = "u1"
video_rows = module._read_csv(fixture_dir / "videos.csv")
for row in video_rows:
    if row["video_id"] == module.TARGET_VIDEO_ID:
        row["caption"] = "当高端酒店开始“限塑”，秸秆也能变废为宝#你我秸是阳光 #锦江酒店 #锦江ESG#乡村振兴#有光的地方"
        row["hashtags"] = '["乡村振兴", "你我秸是阳光", "有光的地方", "锦江ESG", "锦江酒店"]'
module._write_csv(fixture_dir / "videos.csv", list(video_rows[0]), video_rows)
provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
adapter = module._TargetDeliveryAdapter(failed_user_id=failed_user_id)
FinalResearchRunner(
    FinalResearchConfig(dataset_dir=fixture_dir, sample_size=sample_size, provider=provider_config),
    adapter,
).run_and_write(Path(output_path))
`, testModule, fixtureDir, outputDir, fixtureKind], { stdio: 'inherit' });
  const payload = JSON.parse(
    readFileSync(path.join(outputDir, 'final_research_report_payload.json'), 'utf8'),
  ) as RankingPayload;
  return { outputDir, payload };
}

async function expectChart(locator: Locator): Promise<void> {
  await expect(locator).toBeVisible();
  expect((await locator.boundingBox())?.height ?? 0).toBeGreaterThan(80);
}

async function expectNoLayoutFailures(page: Page): Promise<void> {
  const failures = await page.evaluate(() => {
    const visible = (element: HTMLElement) => element.offsetParent !== null;
    const textOverflow = [...document.querySelectorAll<HTMLElement>('button, a, th, td, label, h1, h2, h3')]
      .filter(visible)
      .filter((element) => element.scrollWidth > element.clientWidth + 2 && getComputedStyle(element).overflowX !== 'auto')
      .map((element) => `${element.tagName}:${element.textContent?.trim().slice(0, 40)}`);
    const overlappingGroups = [
      '.topbar > *',
      '.hero-funnel > article',
      '.object-flow > *',
      '.sample-metrics > article',
      '.chart-grid > article',
      '.filters > label',
      '.trace-groups > article',
    ];
    const overlaps: string[] = [];
    for (const selector of overlappingGroups) {
      const elements = [...document.querySelectorAll<HTMLElement>(selector)].filter(visible);
      for (let leftIndex = 0; leftIndex < elements.length; leftIndex += 1) {
        for (let rightIndex = leftIndex + 1; rightIndex < elements.length; rightIndex += 1) {
          const left = elements[leftIndex].getBoundingClientRect();
          const right = elements[rightIndex].getBoundingClientRect();
          const intersectionWidth = Math.min(left.right, right.right) - Math.max(left.left, right.left);
          const intersectionHeight = Math.min(left.bottom, right.bottom) - Math.max(left.top, right.top);
          if (intersectionWidth > 1 && intersectionHeight > 1) overlaps.push(`${selector}:${leftIndex}-${rightIndex}`);
        }
      }
    }
    return {
      horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
      textOverflow,
      overlaps,
    };
  });
  expect(failures).toEqual({ horizontalOverflow: false, textOverflow: [], overlaps: [] });
}

async function assertRankingReport(
  page: Page,
  outputDir: string,
  payload: RankingPayload,
  viewportHeight: number,
): Promise<void> {
  await page.goto(pathToFileURL(path.join(outputDir, 'report.html')).toString());
  await expect(page.getByTestId('final-research-ranking-report')).toBeVisible();

  const hero = page.getByTestId('ranking-hero');
  await expect(hero).toContainText('当高端酒店开始');
  await expect(hero).toContainText('1,000');
  await expect(hero).toContainText('Target exposures');
  await expect(hero).toContainText('Provider decisions');
  await expect(hero).toContainText('Actions');
  await expect(hero).toContainText('ignore');
  await expect(hero).toContainText('Below delivery capacity');
  await expect(page.getByTestId('target-video-link')).toHaveAttribute('href', payload.target_video.video_url);
  const nextSectionTop = await page.getByTestId('core-objects-section').evaluate(
    (element) => element.getBoundingClientRect().top,
  );
  expect(nextSectionTop).toBeLessThan(viewportHeight);

  await expect(page.getByTestId('core-objects-section')).toContainText('TargetVideo');
  await expect(page.getByTestId('core-objects-section')).toContainText('ResearchUser');
  await expect(page.getByTestId('core-objects-section')).toContainText('PlatformRecommendationModel');
  await page.getByRole('link', { name: '逐轮排序' }).click();
  await expect(page).toHaveURL(/#ranking-rounds$/);

  const sampleSection = page.getByTestId('sample-comparison-section');
  await expect(sampleSection).toContainText(`Seed Users（种子用户） ${payload.sample_comparison.seed_count}`);
  await expect(sampleSection).toContainText(`Network Cohort（网络传播识别组） ${payload.sample_comparison.network_cohort_count}`);
  await expect(sampleSection).toContainText(`普通用户替换 ${payload.sample_comparison.replacement_count}`);
  await expect(sampleSection).toContainText(`Base Sample（基础样本）是 network augmentation（网络补样）前按 source scope（来源分组）形成的初始 ${payload.sample_comparison.base_sample_count.toLocaleString()} 人样本`);
  await expect(sampleSection).toContainText(`Final Sample（最终样本）是真正进入正式 runtime（仿真运行）的 ${payload.sample_comparison.final_sample_count.toLocaleString()} 人样本`);
  await expect(sampleSection).toContainText('Historical Set（历史集合）评论网络中的直接邻居');
  await expect(sampleSection).toContainText('真实 processed user（处理后用户）');
  await expect(sampleSection).toContainText('不是合成用户或代表性随机样本');
  await expect(sampleSection).toContainText('固定种子用户');
  await expect(sampleSection).toContainText('等量替换普通用户');
  await expect(sampleSection).toContainText('最终样本总量不变');
  await expect(sampleSection).toContainText('采集来源分组，不是视频语义类别');
  await expect(page.getByTestId('sample-role-table').locator('tbody tr')).toHaveCount(3);
  await expect(page.getByTestId('sample-role-table')).toContainText('是否进入最终样本');
  await expect(page.getByTestId('sample-scope-table')).toContainText('变化');

  const lineageSection = page.getByTestId('field-lineage-section');
  await expect(lineageSection).toContainText('Field Dictionary（字段词典）');
  await expect(lineageSection).toContainText('Direct Observed Profile Field（直接观测画像字段）');
  await expect(lineageSection).toContainText('Runtime Simulation Result（仿真运行结果）');
  await expect(lineageSection).toContainText('Sampling（抽样）');
  await expect(lineageSection).toContainText('Report Only（仅报告）');
  await page.getByTestId('lineage-stage-filter').selectOption('LLM Prompt');
  await expect(page.getByTestId('lineage-table').locator('tbody tr')).not.toHaveCount(0);
  await expect(page.getByTestId('lineage-table')).toContainText('LLM Prompt（大模型提示）');
  await page.getByTestId('lineage-stage-filter').selectOption('');
  await page.getByTestId('lineage-search').fill('合成月收入标签');
  await expect(page.getByTestId('lineage-table').locator('tbody tr')).toHaveCount(1);
  await page.getByRole('button', { name: /latent_monthly_income/ }).click();
  const lineageDetail = page.getByTestId('lineage-detail');
  await expect(lineageDetail).toContainText('latent_monthly_income（合成月收入标签）');
  for (const label of ['含义', '来源', '计算 / 形成方式', '范围', '用途', '高低值解读', '限制']) {
    await expect(lineageDetail).toContainText(label);
  }
  await page.getByTestId('lineage-search').fill('推荐排序分数');
  const recommendationField = page.getByRole('button', { name: /^recommendation_score/ });
  await recommendationField.focus();
  await recommendationField.press('Enter');
  await expect(lineageDetail).toContainText('recommendation_score（推荐排序分数）');
  await expect(lineageDetail).toContainText('不是曝光概率、互动概率或真实平台参数');
  await page.getByTestId('lineage-search').fill('');
  await expect(page.getByTestId('lineage-table').locator('tbody tr')).toHaveCount(payload.field_lineage.length);

  const rankingSection = page.getByTestId('ranking-rounds-section');
  const weights = payload.ranking_diagnostics_summary.main_weights;
  const weightPercent = (value: number): string => `${(value * 100).toFixed(0)}%`;
  await expect(rankingSection).toContainText(weights.base_network.toFixed(2));
  await expect(rankingSection).toContainText(weights.engaged_neighbor.toFixed(2));
  await expect(rankingSection).toContainText(weights.tag_affinity.toFixed(2));
  await expect(rankingSection).toContainText(`Delivery Capacity ${payload.run.delivery_capacity}`);
  await expect(rankingSection).toContainText(`历史评论网络相关性 ${weightPercent(weights.base_network)}`);
  await expect(rankingSection).toContainText(`已互动直接邻居信号 ${weightPercent(weights.engaged_neighbor)}`);
  await expect(rankingSection).toContainText(`目标标签亲和度 ${weightPercent(weights.tag_affinity)}`);
  await expect(rankingSection).toContainText('0..1');
  await expect(rankingSection).toContainText('三位已互动直接邻居达到封顶');
  await expect(rankingSection).toContainText('只影响后续批次');
  await expect(rankingSection).toContainText(`每批最多投放 ${payload.run.delivery_capacity} 人`);
  await expect(rankingSection).toContainText('不是用户互动概率或 action 配额');
  await expect(rankingSection).toContainText('Batch 0');
  await expect(rankingSection).toContainText(`Batch 1–${payload.run.horizon - 1}`);
  const workedExample = page.getByTestId('ranking-worked-example');
  const candidate = selectWorkedCandidate(payload);
  const contributions = [
    candidate.base_network_relevance * weights.base_network,
    candidate.engaged_neighbor_signal * weights.engaged_neighbor,
    candidate.historical_tag_affinity * weights.tag_affinity,
  ];
  const calculatedScore = contributions.reduce((total, value) => total + value, 0);
  await expect(workedExample).toContainText('Persisted Candidate Evidence（持久化候选证据）');
  await expect(workedExample).toContainText('base_network_relevance');
  await expect(workedExample).toContainText('engaged_neighbor_signal');
  await expect(workedExample).toContainText('historical_tag_affinity');
  await expect(workedExample).toContainText('recommendation_score');
  await expect(workedExample).toContainText(
    `${candidate.base_network_relevance.toFixed(4)} × ${weightPercent(weights.base_network)} = ${contributions[0].toFixed(4)}`,
  );
  await expect(workedExample).toContainText(
    `${candidate.engaged_neighbor_signal.toFixed(4)} × ${weightPercent(weights.engaged_neighbor)} = ${contributions[1].toFixed(4)}`,
  );
  await expect(workedExample).toContainText(
    `${candidate.historical_tag_affinity.toFixed(4)} × ${weightPercent(weights.tag_affinity)} = ${contributions[2].toFixed(4)}`,
  );
  await expect(workedExample).toContainText(
    `User ${candidate.user_id} · Batch ${candidate.time_step} · Rank ${candidate.ranking_position} · ${candidate.selected ? '已曝光' : '未曝光'}`,
  );
  await expect(workedExample).toContainText(
    `${contributions.map((value) => value.toFixed(4)).join(' + ')} = ${calculatedScore.toFixed(4)} recommendation_score（持久化值 ${candidate.recommendation_score.toFixed(4)}）`,
  );
  await page.getByTestId('ranking-round-select').selectOption('1');
  await expect(page.getByTestId('round-summary')).toContainText('Eligible');
  await expect(page.getByTestId('round-summary')).toContainText(/Selected\s*20/);
  await expect(page.getByTestId('ranking-candidate-table').locator('tbody tr')).toHaveCount(20);
  await expect(page.getByTestId('ranking-candidate-table')).toContainText('Base network');
  await expect(page.getByTestId('ranking-candidate-table')).toContainText('Engaged neighbor');
  await expect(page.getByTestId('ranking-candidate-table')).toContainText('Tag affinity');

  const networkSection = page.getByTestId('network-effect-section');
  await expect(networkSection).toContainText('Recommendation Signal Inclusion（推荐信号已纳入）');
  await expect(networkSection).toContainText('网络项进入公式');
  await expect(networkSection).toContainText('不能单独证明投放结果改变');
  await expect(networkSection).toContainText('Observed Recommendation Signal Effect（推荐信号产生可观测影响）');
  await expect(networkSection).toContainText(
    `${payload.ranking_diagnostics_summary.batches_with_top_selection_change} / ${payload.ranking_rounds.length} 个批次`,
  );
  await expect(networkSection).toContainText(`同批 Top${payload.run.delivery_capacity} membership`);
  const ablationSection = page.getByTestId('paired-ablation-section');
  await expect(ablationSection).toContainText('shadow diagnostic');
  await expect(ablationSection).toContainText('冻结 persisted candidate evidence（持久化候选证据）');
  await expect(ablationSection).toContainText('零额外 Decision Adapter calls');
  await expect(ablationSection).toContainText('不是第二条完整 trajectory（轨迹）');
  await expect(ablationSection).toContainText('不是因果实验');
  await page.getByTestId('ablation-round-select').selectOption('1');
  await expect(page.getByTestId('ablation-summary')).toContainText(
    `Top${payload.run.delivery_capacity} overlap`,
  );
  await expect(page.getByTestId('ablation-summary')).toContainText('network-added');
  await expect(page.getByTestId('ablation-summary')).toContainText('network-removed');
  await expect(page.getByTestId('ablation-rank-deltas')).toContainText(/rank delta/i);
  await expect(page.getByTestId('sensitivity-section').locator('[data-variant-id]')).toHaveCount(3);
  const sensitivitySection = page.getByTestId('sensitivity-section');
  const ratio = (variant: SensitivityVariant): string =>
    `${(variant.weights.base_network * 100).toFixed(0)}/${(variant.weights.engaged_neighbor * 100).toFixed(0)}/${(variant.weights.tag_affinity * 100).toFixed(0)}`;
  const [mainVariant, weakerVariant, noNetworkVariant] = payload.ranking_diagnostics.weight_sensitivity.variants;
  await expect(sensitivitySection).toContainText(`主方案（${ratio(mainVariant)}）`);
  await expect(sensitivitySection).toContainText(`网络较弱（${ratio(weakerVariant)}）`);
  await expect(sensitivitySection).toContainText(`无网络（${ratio(noNetworkVariant)}）`);
  await expect(page.getByTestId('sensitivity-section')).toContainText('平均 changed selections');
  const weakerAverages = sensitivityAverages(weakerVariant);
  await expect(sensitivitySection).toContainText(
    `${weakerAverages.overlap.toFixed(1)} overlap 约等于 ${weakerAverages.changed.toFixed(1)} 个不同选择`,
  );
  await expect(sensitivitySection).toContainText('结果解读');
  await expect(page.getByTestId('sensitivity-section')).not.toContainText('parameter optimization');
  await expect(page.getByTestId('sensitivity-section')).not.toContainText('production accuracy');

  const promptSection = page.getByTestId('prompt-contract-section');
  await expect(promptSection).toContainText('平台排序决定谁看到视频');
  await expect(promptSection).toContainText('LLM 决定曝光后的 action');
  await expect(promptSection).toContainText('防止评论网络 evidence 同时进入 ranking 和 LLM 决策');
  await expect(promptSection).toContainText('不是数据丢失');
  await expect(promptSection).toContainText('允许字段（Allowed）');
  await expect(promptSection).toContainText('空缺 / 中性字段（Neutral）');
  await expect(promptSection).toContainText('排除字段（Excluded）');
  await expect(promptSection).toContainText('recommendation_score（推荐排序分数）');
  await expect(promptSection).toContainText('Target Holdout answers（目标留出答案）');
  await expect(promptSection).toContainText('raw Prompt 与 provider payload 保持不可见');

  for (const chartId of [
    'sample-composition-chart',
    'batch-delivery-chart',
    'action-chart',
    'provider-failure-chart',
    'network-activation-chart',
    'ablation-overlap-chart',
  ]) {
    await expectChart(page.getByTestId(chartId));
  }

  const users = payload.users;
  await expect(page.getByTestId('visible-user-count')).toHaveText('1,000 / 1,000');
  const tagUser = users.find((user) => user.interest_tags.length > 1) ?? users[0];
  await page.getByTestId('user-search').fill(tagUser.interest_tags[1] ?? tagUser.user_id);
  await expect(page.getByTestId('user-table')).toContainText(tagUser.user_id);
  await page.getByTestId('user-search').fill('controlled ignore');
  await expect(page.getByTestId('user-table').locator('tbody tr').first()).toContainText('controlled ignore');
  await page.getByTestId('user-search').fill('');

  const failedUser = users.find((user) => user.result_status === 'provider_failed');
  expect(failedUser).toBeDefined();
  await page.getByTestId('result-filter').selectOption('provider_failed');
  await expect(page.getByTestId('user-table').locator('tbody tr')).toHaveCount(1);
  await page.getByTestId('user-table').locator('tbody tr').click();
  await expect(page.getByTestId('user-detail')).toContainText(failedUser?.user_id ?? '');
  for (const group of ['直接观测', '历史行为', '派生代理', '合成标签', '样本与 ranking', '曝光与 provider', '最终 action']) {
    await expect(page.getByTestId('user-detail')).toContainText(group);
  }
  await expect(page.getByTestId('user-detail')).toContainText('provider_failed');

  await page.getByTestId('result-filter').selectOption('below_delivery_capacity');
  await expect(page.getByTestId('user-table').locator('tbody tr').first()).toContainText('below_delivery_capacity');
  await page.getByTestId('user-table').locator('tbody tr').first().click();
  expect(await page.getByTestId('ranking-history-table').locator('tbody tr').count()).toBeGreaterThan(1);
  await page.getByTestId('result-filter').selectOption('ignore');
  await expect(page.getByTestId('user-table').locator('tbody tr').first()).toContainText('ignore');
  await page.getByTestId('result-filter').selectOption('');
  await page.getByTestId('role-filter').selectOption('seed');
  await expect(page.getByTestId('user-table').locator('tbody tr')).toHaveCount(
    users.filter((user) => user.sample_role === 'seed').length,
  );
  await page.getByTestId('role-filter').selectOption('');
  await page.getByTestId('scope-filter').selectOption(users[0].sample_source_scope);
  await expect(page.getByTestId('user-table').locator('tbody tr')).toHaveCount(
    users.filter((user) => user.sample_source_scope === users[0].sample_source_scope).length,
  );
  await page.getByTestId('scope-filter').selectOption('');
  await page.getByTestId('seed-filter').selectOption('true');
  await expect(page.getByTestId('user-table').locator('tbody tr')).toHaveCount(
    users.filter((user) => user.is_seed).length,
  );
  await page.getByTestId('seed-filter').selectOption('');
  await page.getByTestId('cohort-filter').selectOption('true');
  await expect(page.getByTestId('user-table').locator('tbody tr')).toHaveCount(
    users.filter((user) => user.is_network_cohort).length,
  );

  for (const [label, relativePath] of Object.entries(payload.downloads)) {
    expect(existsSync(path.join(outputDir, relativePath)), `${label}: ${relativePath}`).toBeTruthy();
    const href = await page.getByTestId(`download-${label.replaceAll('_', '-')}`).getAttribute('href');
    expect(fileURLToPath(new URL(href ?? '', page.url()))).toBe(path.join(outputDir, relativePath));
  }
  await expectNoLayoutFailures(page);
}

test('ranking research report is complete and interactive on desktop', async ({ page }, testInfo) => {
  const { outputDir, payload } = generateRankingReport(testInfo);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await assertRankingReport(page, outputDir, payload, 1000);
  await page.screenshot({ path: testInfo.outputPath('ranking-report-desktop.png'), fullPage: true });
});

test('ranking research report remains usable on mobile', async ({ page }, testInfo) => {
  const { outputDir, payload } = generateRankingReport(testInfo);
  await page.setViewportSize({ width: 390, height: 844 });
  await assertRankingReport(page, outputDir, payload, 844);
  await page.screenshot({ path: testInfo.outputPath('ranking-report-mobile.png'), fullPage: true });
});

test('ranking research report exposes complete paired selection identities', async ({ page }, testInfo) => {
  const { outputDir } = generateRankingReport(testInfo, 'effect');
  await page.goto(pathToFileURL(path.join(outputDir, 'report.html')).toString());
  await page.getByTestId('ablation-round-select').selectOption('1');
  const deltas = page.getByTestId('ablation-rank-deltas');
  await expect(deltas).toContainText('u60');
  await expect(deltas).toContainText('network-added');
  expect(await deltas.locator('tbody tr').count()).toBeGreaterThan(20);
});

test('configured formal ranking run preserves exact evidence on desktop and mobile', async ({ page }, testInfo) => {
  const configuredRunDir = process.env.FINAL_RESEARCH_FORMAL_RUN_DIR;
  test.skip(!configuredRunDir, 'Set FINAL_RESEARCH_FORMAL_RUN_DIR to validate the local formal run.');
  if (!configuredRunDir) return;

  const runDir = path.resolve(configuredRunDir);
  const payloadPath = path.join(runDir, 'final_research_report_payload.json');
  const reportPath = path.join(runDir, 'report.html');
  expect(existsSync(payloadPath)).toBeTruthy();
  const payloadBeforeRebuild = readFileSync(payloadPath);
  execFileSync(path.resolve('.venv/bin/python'), [
    '-c',
    'import sys; from llm_abm_sim.final_research_report import rebuild_final_research_report; rebuild_final_research_report(sys.argv[1])',
    runDir,
  ]);
  expect(readFileSync(payloadPath).equals(payloadBeforeRebuild)).toBeTruthy();

  const payload = JSON.parse(readFileSync(payloadPath, 'utf8')) as RankingPayload;
  expect(payload.ranking_diagnostics_summary.batches_with_top_selection_change).toBe(8);
  expect(payload.ranking_rounds).toHaveLength(30);
  const weakerVariant = payload.ranking_diagnostics.weight_sensitivity.variants.find(
    (variant) => variant.variant_id === 'weaker_network_40_20_40',
  );
  expect(weakerVariant).toBeDefined();
  if (!weakerVariant) return;
  const weakerAverages = sensitivityAverages(weakerVariant);
  expect(weakerAverages.overlap).toBeCloseTo(19.7, 1);
  expect(weakerAverages.changed).toBeCloseTo(0.3, 1);

  const candidate = selectWorkedCandidate(payload);
  const weights = payload.ranking_diagnostics_summary.main_weights;
  const contributions = [
    candidate.base_network_relevance * weights.base_network,
    candidate.engaged_neighbor_signal * weights.engaged_neighbor,
    candidate.historical_tag_affinity * weights.tag_affinity,
  ];
  const calculatedScore = contributions.reduce((total, value) => total + value, 0);
  expect(candidate.recommendation_score).toBeCloseTo(calculatedScore, 10);

  for (const viewport of [
    { name: 'desktop', width: 1440, height: 1000 },
    { name: 'mobile', width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(pathToFileURL(reportPath).toString());
    await expect(page.getByTestId('network-effect-section')).toContainText('8 / 30 个批次');
    await expect(page.getByTestId('sensitivity-section')).toContainText(
      `${weakerAverages.overlap.toFixed(1)} overlap 约等于 ${weakerAverages.changed.toFixed(1)} 个不同选择`,
    );
    const example = page.getByTestId('ranking-worked-example');
    await expect(example).toContainText(
      `User ${candidate.user_id} · Batch ${candidate.time_step} · Rank ${candidate.ranking_position} · 已曝光`,
    );
    await expect(example).toContainText(
      `${contributions.map((value) => value.toFixed(4)).join(' + ')} = ${calculatedScore.toFixed(4)} recommendation_score（持久化值 ${candidate.recommendation_score.toFixed(4)}）`,
    );
    await expectNoLayoutFailures(page);
    await page.screenshot({
      path: testInfo.outputPath(`formal-ranking-report-${viewport.name}.png`),
      fullPage: true,
    });
  }
});
