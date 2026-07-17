import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { expect, test, type Locator, type Page, type TestInfo } from '@playwright/test';

type RankingUser = {
  user_id: string;
  nickname: string;
  interest_tags: string[];
  reason: string;
  result_status: string;
  action: string;
  sample_source_scope: string;
  sample_role: string;
  is_seed: boolean;
  is_network_cohort: boolean;
  exposure_time_step: number | null;
  provider_status: string;
  confidence: number | null;
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
    target_exposures: number;
    provider_failed: number;
    candidates_with_positive_engaged_neighbor_signal: number;
    selected_with_positive_engaged_neighbor_signal: number;
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
      navigationOverflow: [...document.querySelectorAll<HTMLElement>('.brand, .workflow-nav')]
        .filter(visible)
        .filter((element) => element.scrollWidth > element.clientWidth + 2)
        .map((element) => `${element.className}:${element.clientWidth}/${element.scrollWidth}`),
      textOverflow,
      overlaps,
    };
  });
  expect(failures).toEqual({
    horizontalOverflow: false,
    navigationOverflow: [],
    textOverflow: [],
    overlaps: [],
  });
}

async function expectBilingualReaderSurface(page: Page): Promise<void> {
  const failures = await page.evaluate(() => {
    const selectors = [
      '.topbar',
      '.ranking-hero .eyebrow',
      '.hero-meta',
      '.hero-funnel > article > span',
      '.object-band',
      '.section-heading',
      '.section-explanation',
      '.scope-intro',
      '.lineage-legends',
      '.ranking-term-grid',
      '.ranking-method-notes',
      '.ranking-worked-example h3',
      '.ranking-worked-example-grid strong',
      '.network-reading-note',
      '[data-testid="paired-ablation-section"] > .section-heading',
      '.ablation-summary span',
      '.effect-label',
      '.effect-grid',
      '.sensitivity-variants',
      '.prompt-reading-note',
      '.prompt-grid > article > h3',
      '.chart-grid h3',
      '.chart-explanation',
      '.bar-row > span',
      '.filters label',
      'select option',
      'table thead',
      '.status',
      '.provider-status',
      '.trace-groups h3',
      '.trace-groups dt',
      '.ranking-history h3',
      '.proxy-explanation-guide > p',
      '.downloads',
      '.limitations-band',
    ];
    const elements = [...new Set(selectors.flatMap((selector) => [...document.querySelectorAll<HTMLElement>(selector)]))];
    return elements.flatMap((element) => {
      const copy = element.cloneNode(true) as HTMLElement;
      copy.querySelectorAll('code, .formula, input, select, option').forEach((child) => child.remove());
      const text = (copy.textContent ?? '').replace(/\s+/g, ' ').trim();
      const withoutPairs = text
        .replace(/[A-Za-z][A-Za-z0-9_./–-]*(?: [A-Za-z0-9_./–-]+)*（[^）]+）/g, '')
        .replace(/\bLLM\b/g, '');
      const unpaired = withoutPairs.match(/[A-Za-z][A-Za-z0-9_./-]*/g) ?? [];
      return unpaired.length ? [`${element.tagName}.${element.className}: ${unpaired.join(', ')}`] : [];
    });
  });
  expect(failures).toEqual([]);
}

async function assertReaderComprehensionContract(
  page: Page,
  outputDir: string,
  payload: RankingPayload,
): Promise<void> {
  for (const explanationId of [
    'sample-section-explanation',
    'lineage-section-explanation',
    'ranking-section-explanation',
    'network-section-explanation',
    'prompt-section-explanation',
    'aggregate-section-explanation',
    'users-section-explanation',
  ]) {
    const explanation = page.getByTestId(explanationId);
    for (const label of ['是什么', '为什么需要', '怎么形成或计算', '本次结果怎么看']) {
      await expect(explanation).toContainText(label);
    }
  }
  await expect(page.getByTestId('sample-section-explanation')).toContainText('Base Sample（基础样本）');
  await expect(page.getByTestId('sample-section-explanation')).toContainText('Final Sample（最终样本）');

  await expect(page.getByTestId('lineage-table')).toContainText('Meaning（简要含义）');
  await page.getByTestId('lineage-search').fill('recommendation_score');
  await expect(page.getByTestId('lineage-table').locator('tbody tr')).not.toHaveCount(0);
  await page.getByTestId('lineage-table').getByRole('button', { name: 'recommendation_score', exact: true }).click();
  await expect(page.getByTestId('lineage-detail')).toContainText('recommendation_score（推荐排序分数）');
  await page.getByTestId('lineage-search').fill('');
  const detailDrawer = page.getByTestId('evidence-drawer');
  await detailDrawer.getByRole('button', { name: '关闭详情' }).click();

  const promptSection = page.getByTestId('prompt-contract-section');
  await expect(promptSection).toContainText('平台排序决定谁看到视频');
  await expect(promptSection).toContainText('Target Holdout answers（目标留出答案）');

  for (const chartExplanationId of [
    'sample-composition-explanation',
    'batch-delivery-explanation',
    'action-status-explanation',
    'provider-failure-explanation',
    'network-activation-explanation',
    'ablation-overlap-explanation',
  ]) {
    const explanation = page.getByTestId(chartExplanationId);
    for (const label of ['统计什么', '单位 / 分母', '为什么需要', '本次结果']) {
      await expect(explanation).toContainText(label);
    }
  }

  const users = payload.users;
  for (const id of ['result-filter', 'role-filter', 'scope-filter', 'seed-filter', 'cohort-filter']) {
    await page.getByTestId(id).selectOption('');
  }
  await expect(page.getByTestId('visible-user-count')).toHaveText(
    `${users.length.toLocaleString()} / ${users.length.toLocaleString()}`,
  );
  for (const [filterId, value, expected] of [
    ['result-filter', 'below_delivery_capacity', users.filter((user) => user.result_status === 'below_delivery_capacity').length],
    ['result-filter', 'ignore', users.filter((user) => user.result_status === 'ignore').length],
    ['role-filter', 'seed', users.filter((user) => user.sample_role === 'seed').length],
    ['seed-filter', 'true', users.filter((user) => user.is_seed).length],
    ['cohort-filter', 'true', users.filter((user) => user.is_network_cohort).length],
  ] as const) {
    await page.getByTestId(filterId).selectOption(value);
    await expect(page.getByTestId('user-table').locator('tbody tr')).toHaveCount(expected);
    await page.getByTestId(filterId).selectOption('');
  }
  await page.getByTestId('user-table').locator('tbody tr').first().click();
  await expect(page.getByTestId('proxy-values')).toContainText('Activity（活跃度代理）');
  const proxyExplanation = page.getByTestId('proxy-explanation-guide');
  if (await proxyExplanation.getAttribute('open') !== null) {
    await proxyExplanation.locator('summary').click();
  }
  await expect(proxyExplanation).not.toHaveAttribute('open', '');
  await proxyExplanation.locator('summary').click();
  await expect(proxyExplanation).toContainText('不能用于因果或心理推断');
  await detailDrawer.getByRole('button', { name: '关闭详情' }).click();

  for (const [label, relativePath] of Object.entries(payload.downloads)) {
    expect(existsSync(path.join(outputDir, relativePath)), `${label}: ${relativePath}`).toBeTruthy();
    const link = page.getByTestId(`download-${label.replaceAll('_', '-')}`);
    await expect(link).toContainText('（');
    const href = await link.getAttribute('href');
    expect(fileURLToPath(new URL(href ?? '', page.url()))).toBe(path.join(outputDir, relativePath));
  }
  await expectBilingualReaderSurface(page);
  await expectNoLayoutFailures(page);
}

async function assertRankingReport(
  page: Page,
  outputDir: string,
  payload: RankingPayload,
  viewportHeight: number,
): Promise<void> {
  await page.goto(pathToFileURL(path.join(outputDir, 'report.html')).toString());
  await expect(page.getByTestId('final-research-ranking-report')).toBeVisible();
  await page.getByTestId('run-evidence-mode-button').click();

  const hero = page.getByTestId('ranking-hero');
  await expect(hero).toContainText('当高端酒店开始');
  await expect(hero).toContainText('1,000');
  await expect(hero).toContainText('Exposures（曝光）');
  await expect(hero).toContainText('Decisions（决策）');
  await expect(hero).toContainText('Actions');
  await expect(hero).toContainText('ignore');
  await expect(hero).toContainText('Below capacity（未投放）');
  await expect(page.getByTestId('target-video-link')).toHaveAttribute('href', payload.target_video.video_url);
  const nextSectionTop = await page.getByTestId('core-objects-section').evaluate(
    (element) => element.getBoundingClientRect().top,
  );
  expect(nextSectionTop).toBeLessThan(viewportHeight);

  await expect(page.getByTestId('core-objects-section')).toContainText('TargetVideo');
  await expect(page.getByTestId('core-objects-section')).toContainText('ResearchUser');
  await expect(page.getByTestId('core-objects-section')).toContainText('PlatformRecommendationModel');
  await page.getByRole('link', { name: '曝光排序' }).click();
  await expect(page).toHaveURL(/#exposure-ranking$/);

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
  await expect(page.getByTestId('lineage-table')).toContainText('实验用月收入区间，不是观测收入。');
  await page.getByTestId('lineage-table').getByRole('button', { name: 'latent_monthly_income', exact: true }).click();
  const lineageDetail = page.getByTestId('lineage-detail');
  await expect(lineageDetail).toContainText('latent_monthly_income（合成月收入标签）');
  for (const label of ['含义', '来源', '计算 / 形成方式', '范围', '用途', '高低值解读', '限制']) {
    await expect(lineageDetail).toContainText(label);
  }
  await page.getByTestId('lineage-search').fill('推荐排序分数');
  const recommendationField = page.getByTestId('lineage-table').getByRole('button', {
    name: 'recommendation_score',
    exact: true,
  });
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
  await expect(rankingSection).toContainText(`Delivery Capacity（每批投放容量）${payload.run.delivery_capacity}`);
  await expect(rankingSection).toContainText(`历史评论网络相关性 ${weightPercent(weights.base_network)}`);
  await expect(rankingSection).toContainText(`已互动直接邻居信号 ${weightPercent(weights.engaged_neighbor)}`);
  await expect(rankingSection).toContainText(`目标标签亲和度 ${weightPercent(weights.tag_affinity)}`);
  await expect(rankingSection).toContainText('0..1');
  await expect(rankingSection).toContainText('三位已互动直接邻居达到封顶');
  await expect(rankingSection).toContainText('只影响后续批次');
  await expect(rankingSection).toContainText(`每批最多投放 ${payload.run.delivery_capacity} 人`);
  await expect(rankingSection).toContainText('不是用户互动概率或 action（动作）配额');
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
    `User（用户）${candidate.user_id} · Batch（批次）${candidate.time_step} · Rank（名次）${candidate.ranking_position} · ${candidate.selected ? '已曝光' : '未曝光'}`,
  );
  await expect(workedExample).toContainText(
    `${contributions.map((value) => value.toFixed(4)).join(' + ')} = ${calculatedScore.toFixed(4)} recommendation_score（推荐排序分数；持久化值 ${candidate.recommendation_score.toFixed(4)}）`,
  );
  const evidenceDrawer = page.getByTestId('evidence-drawer');
  if (await evidenceDrawer.isVisible()) {
    await evidenceDrawer.getByRole('button', { name: '关闭详情' }).click();
  }
  await page.getByTestId('shared-batch-timeline').getByRole('button', { name: 'Batch 1', exact: true }).click();
  await expect(page.getByTestId('round-summary')).toContainText('Eligible');
  await expect(page.getByTestId('round-summary')).toContainText('Selected（已选择）20');
  await expect(page.getByTestId('ranking-candidate-table').locator('tbody tr')).toHaveCount(20);
  for (const heading of [
    'Rank（名次）',
    'User（用户）',
    'Base network（历史网络）',
    'Engaged neighbor（已互动邻居）',
    'Tag affinity（标签亲和度）',
    'Score（分数）',
  ]) {
    await expect(page.getByTestId('ranking-candidate-table')).toContainText(heading);
  }

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
  await page.getByTestId('shared-batch-timeline').getByRole('button', { name: 'Batch 1', exact: true }).click();
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
    `${weakerAverages.overlap.toFixed(1)} overlap（重合人数）约等于 ${weakerAverages.changed.toFixed(1)} 个不同选择`,
  );
  await expect(sensitivitySection).toContainText('结果解读');
  await expect(page.getByTestId('sensitivity-section')).not.toContainText('parameter optimization');
  await expect(page.getByTestId('sensitivity-section')).not.toContainText('production accuracy');

  const promptSection = page.getByTestId('prompt-contract-section');
  await expect(promptSection).toContainText('平台排序决定谁看到视频');
  await expect(promptSection).toContainText('LLM（大模型）决定曝光后的 action（动作）');
  await expect(promptSection).toContainText('防止评论网络 evidence（证据）同时进入 ranking（排序）和 LLM（大模型）决策');
  await expect(promptSection).toContainText('不是数据丢失');
  await expect(promptSection).toContainText('Allowed（允许字段）');
  await expect(promptSection).toContainText('Neutral（空缺 / 中性字段）');
  await expect(promptSection).toContainText('Excluded（排除字段）');
  await expect(promptSection).toContainText('recommendation_score（推荐排序分数）');
  await expect(promptSection).toContainText('Target Holdout answers（目标留出答案）');
  await expect(promptSection).toContainText('raw Prompt（原始提示）与 provider payload（服务提供方载荷）保持不可见');

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

  const totalExposures = payload.ranking_rounds.reduce((total, round) => total + round.target_exposures, 0);
  const belowCapacityCount = payload.users.filter((user) => user.result_status === 'below_delivery_capacity').length;
  const ignoreCount = payload.users.filter((user) => user.result_status === 'ignore').length;
  const providerFailureCount = payload.users.filter((user) => user.result_status === 'provider_failed').length;
  const positiveCandidateRows = payload.ranking_rounds.reduce(
    (total, round) => total + round.candidates_with_positive_engaged_neighbor_signal,
    0,
  );
  const positiveSelectedUsers = payload.ranking_rounds.reduce(
    (total, round) => total + round.selected_with_positive_engaged_neighbor_signal,
    0,
  );
  const positiveSelectedUserIds = new Set(
    payload.ranking_rounds.flatMap((round) =>
      round.candidates
        .filter((candidate) => candidate.selected && candidate.engaged_neighbor_signal > 0)
        .map((candidate) => candidate.user_id),
    ),
  );
  const positiveSignalActions = payload.users.filter(
    (user) => positiveSelectedUserIds.has(user.user_id) && user.action,
  ).length;
  await expect(page.getByTestId('sample-composition-explanation')).toContainText(
    `Final Sample（最终样本）${payload.sample_comparison.final_sample_count.toLocaleString()} 人`,
  );
  await expect(page.getByTestId('batch-delivery-explanation')).toContainText(`Batch 0`);
  await expect(page.getByTestId('batch-delivery-explanation')).toContainText(
    `Batch 1–${payload.run.horizon - 1}`,
  );
  await expect(page.getByTestId('batch-delivery-explanation')).toContainText(
    `Top${payload.run.delivery_capacity}`,
  );
  await expect(page.getByTestId('batch-delivery-explanation')).toContainText(
    `合计 ${totalExposures.toLocaleString()} 次 exposure`,
  );
  const actionExplanation = page.getByTestId('action-status-explanation');
  await expect(actionExplanation).toContainText(
    `${belowCapacityCount.toLocaleString()} 个 below_delivery_capacity（未获得投放）用户从未曝光`,
  );
  await expect(actionExplanation).toContainText(
    `${ignoreCount.toLocaleString()} 个 ignore（忽略）用户已曝光但选择不互动`,
  );
  await expect(actionExplanation).toContainText('like（点赞）/ comment（评论）/ share（分享）');
  await expect(actionExplanation).toContainText('provider_failed（Provider 失败）');
  const providerExplanation = page.getByTestId('provider-failure-explanation');
  await expect(providerExplanation).toContainText('重试耗尽任务');
  await expect(providerExplanation).toContainText(
    `${providerFailureCount.toLocaleString()} / ${totalExposures.toLocaleString()}`,
  );
  await expect(providerExplanation).toContainText('不代表 provider（服务提供方）永不失败');
  const networkExplanation = page.getByTestId('network-activation-explanation');
  await expect(networkExplanation).toContainText('candidate evidence rows（候选证据行）');
  await expect(networkExplanation).toContainText(`${positiveCandidateRows.toLocaleString()} 条 candidates（候选）`);
  await expect(networkExplanation).toContainText(`${positiveSelectedUsers.toLocaleString()} 位 selected users（已选择用户）`);
  await expect(networkExplanation).toContainText(`${positiveSignalActions.toLocaleString()} 条 actions（动作）`);
  const ablationExplanation = page.getByTestId('ablation-overlap-explanation');
  await expect(ablationExplanation).toContainText(
    `Top${payload.run.delivery_capacity} overlap（前列重合人数）=${payload.run.delivery_capacity}`,
  );
  await expect(ablationExplanation).toContainText('选择集合相同');
  await expect(ablationExplanation).toContainText('数值降低');

  const users = payload.users;
  await expect(page.getByTestId('visible-user-count')).toHaveText('1,000 / 1,000');
  const tagUser = users.find((user) => user.interest_tags.length > 1) ?? users[0];
  await page.getByTestId('user-search').fill(tagUser.interest_tags[1] ?? tagUser.user_id);
  await expect(page.getByTestId('user-table')).toContainText(tagUser.user_id);
  await page.getByTestId('user-search').fill('controlled ignore');
  await expect(page.getByTestId('user-table').locator('tbody tr').first()).toContainText('controlled ignore');
  await expect(page.getByTestId('user-table')).toContainText('remaining_users（其余用户）');
  await page.getByTestId('user-table').locator('tbody tr').first().click();
  await expect(page.getByTestId('user-detail')).toContainText('mocked_provider（决策来源）');
  await evidenceDrawer.getByRole('button', { name: '关闭详情' }).click();
  await page.getByTestId('user-search').fill('');

  const failedUser = users.find((user) => user.result_status === 'provider_failed');
  expect(failedUser).toBeDefined();
  await page.getByTestId('result-filter').selectOption('provider_failed');
  await expect(page.getByTestId('user-table').locator('tbody tr')).toHaveCount(1);
  await page.getByTestId('user-table').locator('tbody tr').click();
  await expect(page.getByTestId('user-detail')).toContainText(failedUser?.user_id ?? '');
  await expect(page.getByTestId('user-detail')).toContainText('（Provider 失败类型）');
  for (const group of ['直接观测', '历史行为', '派生代理', '合成标签', '样本与 ranking', '曝光与 provider', '最终 action']) {
    await expect(page.getByTestId('user-detail')).toContainText(group);
  }
  const proxyValues = page.getByTestId('proxy-values');
  await expect(proxyValues).toBeVisible();
  for (const label of [
    'Activity（活跃度代理）',
    'Global influence（全平台影响力代理）',
    'Local influence（局部影响力代理）',
    'Local network（局部网络分量）',
    'Local recognition（局部认可分量）',
  ]) {
    await expect(proxyValues).toContainText(label);
  }
  const proxyExplanation = page.getByTestId('proxy-explanation-guide');
  await expect(proxyExplanation).toBeVisible();
  await expect(proxyExplanation).not.toHaveAttribute('open', '');
  await proxyExplanation.locator('summary').click();
  await expect(proxyExplanation).toHaveAttribute('open', '');
  await expect(proxyExplanation).toContainText('0..1 的归一化数值');
  await expect(proxyExplanation).toContainText('历史视频、评论和回复活跃度');
  await expect(proxyExplanation).toContainText('以 follower evidence（粉丝证据） 为主');
  await expect(proxyExplanation).toContainText('不是平台官方指数');
  await expect(proxyExplanation).toContainText('评论网络中的位置与评论获赞认可');
  await expect(proxyExplanation).toContainText('local influence（局部影响力代理）的两个组成部分');
  await expect(proxyExplanation).toContainText('不是独立心理特征');
  await expect(proxyExplanation).toContainText('不能用于因果或心理推断');
  await expect(proxyValues).toBeVisible();
  await expect(page.getByTestId('user-detail')).toContainText('provider_failed');
  await evidenceDrawer.getByRole('button', { name: '关闭详情' }).click();

  await page.getByTestId('result-filter').selectOption('below_delivery_capacity');
  await expect(page.getByTestId('user-table').locator('tbody tr').first()).toContainText('below_delivery_capacity');
  await page.getByTestId('user-table').locator('tbody tr').first().click();
  expect(await page.getByTestId('ranking-history-table').locator('tbody tr').count()).toBeGreaterThan(1);
  await evidenceDrawer.getByRole('button', { name: '关闭详情' }).click();
  await page.getByTestId('result-filter').selectOption('');
  await page.getByTestId('scope-filter').selectOption(users[0].sample_source_scope);
  await expect(page.getByTestId('user-table').locator('tbody tr')).toHaveCount(
    users.filter((user) => user.sample_source_scope === users[0].sample_source_scope).length,
  );
  await page.getByTestId('scope-filter').selectOption('');
  await assertReaderComprehensionContract(page, outputDir, payload);
}

test('mechanism shell defaults to explanation and keeps run evidence available on desktop', async ({ page }, testInfo) => {
  const { outputDir, payload } = generateRankingReport(testInfo);
  const externalRequests: string[] = [];
  page.on('request', (request) => {
    const protocol = new URL(request.url()).protocol;
    if (protocol !== 'file:' && protocol !== 'data:') externalRequests.push(request.url());
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(pathToFileURL(path.join(outputDir, 'report.html')).toString());

  await expect(page).toHaveURL(/^file:/);
  await expect(page.getByTestId('final-research-ranking-report')).toHaveAttribute('data-report-mode', 'mechanism');
  await expect(page.getByTestId('mechanism-mode-button')).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByTestId('run-evidence-mode-button')).toHaveAttribute('aria-selected', 'false');
  await expect(page.getByTestId('mechanism-mode-panel')).toBeVisible();
  await expect(page.getByTestId('run-evidence-mode-panel')).toBeHidden();

  const navigation = page.locator('.workflow-nav');
  await expect(navigation.getByRole('link')).toHaveText([
    '概览',
    '样本',
    '曝光排序',
    'LLM 决策',
    '网络反馈',
  ]);
  await expect(navigation).not.toContainText('网络影响');
  for (const [label, anchor] of [
    ['概览', 'overview'],
    ['样本', 'sample'],
    ['曝光排序', 'exposure-ranking'],
    ['LLM 决策', 'llm-decision'],
    ['网络反馈', 'network-feedback'],
  ] as const) {
    await navigation.getByRole('link', { name: label }).click();
    await expect(page).toHaveURL(new RegExp(`#${anchor}$`));
    await expect(page.locator(`[data-report-mode-panel="mechanism"] [data-section-anchor="${anchor}"]`)).toBeVisible();
  }

  const mechanismPanel = page.getByTestId('mechanism-mode-panel');
  await expect(mechanismPanel).toContainText('Proposed Seed-First Research Sample');
  await expect(mechanismPanel).toContainText('20 seeds');
  await expect(mechanismPanel).toContainText('60 Seed Neighbor Cohort');
  await expect(mechanismPanel).toContainText('920 ordinary users');
  await expect(mechanismPanel).toContainText('offline projection');
  await expect(mechanismPanel).toContainText('不是旧正式 run 的新结果');
  await expect(mechanismPanel).toContainText('Full-Pool Influence Seed Union');
  await expect(mechanismPanel).toContainText('not Global Reranking Top20 winners');
  await expect(mechanismPanel).toContainText('三路证据汇入同一条排序');
  await expect(mechanismPanel).toContainText('平台决定 Recommendation Opportunity');
  await expect(mechanismPanel).toContainText('Decision Adapter 只输出曝光后的结构化 action');
  for (const imageId of [
    'sample-construction-illustration',
    'batch-zero-seeds-illustration',
    'global-reranking-illustration',
    'platform-llm-boundary-illustration',
  ]) {
    const image = page.getByTestId(imageId);
    await expect(image).toBeVisible();
    await expect(image).toHaveAttribute('src', /^data:image\/webp;base64,/);
    expect(await image.evaluate((node: HTMLImageElement) => ({ complete: node.complete, width: node.naturalWidth })))
      .toEqual({ complete: true, width: 1672 });
  }
  expect(externalRequests).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath('mechanism-report-desktop.png'), fullPage: true });

  await page.getByTestId('run-evidence-mode-button').click();
  await expect(page.getByTestId('final-research-ranking-report')).toHaveAttribute('data-report-mode', 'run-evidence');
  await expect(page.getByTestId('mechanism-mode-panel')).toBeHidden();
  await expect(page.getByTestId('run-evidence-mode-panel')).toBeVisible();
  await expect(page.getByTestId('ranking-hero')).toContainText(payload.users.length.toLocaleString());
  await expect(page.getByTestId('sample-comparison-section')).toContainText(
    payload.sample_comparison.final_sample_count.toLocaleString(),
  );

  await page.getByTestId('mechanism-mode-button').focus();
  await page.getByTestId('mechanism-mode-button').press('ArrowRight');
  await expect(page.getByTestId('run-evidence-mode-button')).toBeFocused();
  await expect(page.getByTestId('run-evidence-mode-button')).toHaveAttribute('aria-selected', 'true');
});

test('one persisted Batch selection updates ranking and LLM evidence together', async ({ page }, testInfo) => {
  const { outputDir, payload } = generateRankingReport(testInfo);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(pathToFileURL(path.join(outputDir, 'report.html')).toString());
  await page.getByTestId('run-evidence-mode-button').click();

  const timeline = page.getByTestId('shared-batch-timeline');
  await expect(timeline.getByRole('button')).toHaveCount(payload.run.horizon);
  await expect(timeline.getByRole('button', { name: 'Batch 0', exact: true })).toHaveAttribute('aria-current', 'step');
  await expect(page.getByTestId('batch-mechanism-label')).toContainText('Seed direct exposure');

  const selectedBatch = payload.ranking_rounds.find((round) => round.time_step === 1);
  expect(selectedBatch).toBeDefined();
  const selectedCandidate = selectedBatch?.candidates.find((candidate) => candidate.selected);
  const exposedUser = payload.users.find((user) => user.exposure_time_step === 1);
  expect(selectedCandidate).toBeDefined();
  expect(exposedUser).toBeDefined();

  await timeline.getByRole('button', { name: 'Batch 1', exact: true }).click();
  await expect(page.getByTestId('final-research-ranking-report')).toHaveAttribute('data-current-batch', '1');
  await expect(timeline.getByRole('button', { name: 'Batch 1', exact: true })).toHaveAttribute('aria-current', 'step');
  await expect(page.getByTestId('batch-mechanism-label')).toContainText('Global Reranking');
  await expect(page.getByTestId('ranking-candidate-table')).toContainText(selectedCandidate?.user_id ?? '');
  await expect(page.getByTestId('batch-decision-evidence')).toContainText(exposedUser?.user_id ?? '');
  await expect(page.getByTestId('batch-decision-evidence')).toContainText(exposedUser?.provider_status ?? '');
  await expect(page.getByTestId('ranking-round-select')).toHaveValue('1');
  await expect(page.getByTestId('ablation-round-select')).toHaveValue('1');
  await expect(page.getByTestId('ranking-round-select')).toBeHidden();
  await expect(page.getByTestId('ablation-round-select')).toBeHidden();
});

test('ranking candidates users and prompt fields share one right detail drawer', async ({ page }, testInfo) => {
  const { outputDir, payload } = generateRankingReport(testInfo);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(pathToFileURL(path.join(outputDir, 'report.html')).toString());
  await page.getByTestId('run-evidence-mode-button').click();
  await page.getByTestId('shared-batch-timeline').getByRole('button', { name: 'Batch 1', exact: true }).click();

  const drawer = page.getByTestId('evidence-drawer');
  await expect(drawer).toBeHidden();
  const candidate = payload.ranking_rounds
    .find((round) => round.time_step === 1)
    ?.candidates.find((row) => row.selected);
  expect(candidate).toBeDefined();
  await page.getByTestId('ranking-candidate-table').locator('tbody tr').first().click();
  await expect(drawer).toBeVisible();
  await expect(drawer).toHaveAttribute('data-selection-kind', 'candidate');
  await expect(drawer).toContainText(candidate?.user_id ?? '');
  await expect(drawer).toContainText('Batch（批次）1');
  await expect(drawer).toContainText('Score contribution（分数贡献）');
  await page.screenshot({ path: testInfo.outputPath('ranking-candidate-drawer-desktop.png') });

  const user = payload.users.find((row) => row.exposure_time_step === 1);
  expect(user).toBeDefined();
  await page.getByTestId('user-search').fill(user?.user_id ?? '');
  await page.getByTestId('user-table').locator('.profile-id').filter({
    hasText: new RegExp(`^${user?.user_id ?? ''}$`),
  }).click();
  await expect(drawer).toHaveAttribute('data-selection-kind', 'user');
  await expect(drawer).toContainText(user?.user_id ?? '');
  await expect(drawer).toContainText('Field Provenance（字段来源）');
  await expect(drawer).toContainText('Field Usage Stage（字段使用阶段）');

  const promptField = page.getByTestId('prompt-contract-section').getByRole('button').first();
  const promptFieldName = (await promptField.textContent())?.split('（')[0] ?? '';
  await promptField.click();
  await expect(drawer).toHaveAttribute('data-selection-kind', 'field');
  await expect(drawer).toContainText(promptFieldName);
  await expect(drawer).toContainText('Field Provenance（字段来源）');
  await expect(drawer).toContainText('Field Usage Stage（字段使用阶段）');

  await drawer.getByRole('button', { name: '关闭详情' }).click();
  await expect(drawer).toBeHidden();
});

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
  await page.getByTestId('run-evidence-mode-button').click();
  await page.getByTestId('shared-batch-timeline').getByRole('button', { name: 'Batch 1', exact: true }).click();
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
  const preservedArtifactNames = readdirSync(runDir).filter((name) => name !== 'report.html').sort();
  const artifactsBeforeRebuild = new Map(
    preservedArtifactNames.map((name) => [name, readFileSync(path.join(runDir, name))]),
  );
  execFileSync(path.resolve('.venv/bin/python'), [
    '-c',
    'import sys; from llm_abm_sim.final_research_report import rebuild_final_research_report; rebuild_final_research_report(sys.argv[1])',
    runDir,
  ]);
  expect(preservedArtifactNames).toHaveLength(24);
  expect(readdirSync(runDir).filter((name) => name !== 'report.html').sort()).toEqual(preservedArtifactNames);
  for (const [name, before] of artifactsBeforeRebuild) {
    expect(readFileSync(path.join(runDir, name)).equals(before), name).toBeTruthy();
  }

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
    await assertReaderComprehensionContract(page, runDir, payload);
    await expect(page.getByTestId('network-effect-section')).toContainText('8 / 30 个批次');
    await expect(page.getByTestId('sensitivity-section')).toContainText(
      `${weakerAverages.overlap.toFixed(1)} overlap（重合人数）约等于 ${weakerAverages.changed.toFixed(1)} 个不同选择`,
    );
    const example = page.getByTestId('ranking-worked-example');
    await expect(example).toContainText(
      `User（用户）${candidate.user_id} · Batch（批次）${candidate.time_step} · Rank（名次）${candidate.ranking_position} · 已曝光`,
    );
    await expect(example).toContainText(
      `${contributions.map((value) => value.toFixed(4)).join(' + ')} = ${calculatedScore.toFixed(4)} recommendation_score（推荐排序分数；持久化值 ${candidate.recommendation_score.toFixed(4)}）`,
    );
    await expect(page.getByTestId('action-status-explanation')).toContainText(
      '400 个 below_delivery_capacity（未获得投放）用户从未曝光',
    );
    await expect(page.getByTestId('action-status-explanation')).toContainText(
      '342 个 ignore（忽略）用户已曝光但选择不互动',
    );
    await expect(page.getByTestId('provider-failure-explanation')).toContainText('0 / 600 个任务重试耗尽');
    await expect(page.getByTestId('network-activation-explanation')).toContainText('30 条 candidates（候选）');
    await expect(page.getByTestId('network-activation-explanation')).toContainText('23 位 selected users（已选择用户）');
    await expect(page.getByTestId('network-activation-explanation')).toContainText('23 条 actions（动作）');
    await page.screenshot({
      path: testInfo.outputPath(`formal-ranking-report-${viewport.name}.png`),
      fullPage: true,
    });
  }
});
