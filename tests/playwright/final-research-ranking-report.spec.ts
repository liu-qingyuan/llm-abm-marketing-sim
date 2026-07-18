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
  engaged_neighbor_count: number;
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

type PairedAblationBatch = {
  time_step: number;
  eligible_count: number;
  top_overlap_count: number;
  network_added_user_ids: string[];
  network_removed_user_ids: string[];
  full_top_user_ids: string[];
  no_network_top_user_ids: string[];
  rank_deltas: Array<{
    user_id: string;
    full_rank: number;
    no_network_rank: number;
    network_rank_delta: number;
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
    provenance: string;
    usage_stages: string[];
  }>;
  prompt_contract: {
    allowed_profile_fields: string[];
  };
  run: {
    sample_size: number;
    horizon: number;
    delivery_capacity: number;
    maximum_target_exposures: number;
  };
  ranking_rounds: Array<{
    time_step: number;
    target_exposures: number;
    selected_count: number;
    engagements: number;
    ignored: number;
    provider_failed: number;
    candidates_with_positive_engaged_neighbor_signal: number;
    selected_with_positive_engaged_neighbor_signal: number;
    candidates: RankingCandidate[];
  }>;
  ranking_diagnostics_summary: {
    batches_with_top_selection_change: number;
    top_selection_changed: boolean;
    main_weights: {
      base_network: number;
      engaged_neighbor: number;
      tag_affinity: number;
    };
  };
  ranking_diagnostics: {
    paired_ablation: {
      batches: PairedAblationBatch[];
    };
    weight_sensitivity: {
      variants: SensitivityVariant[];
    };
  };
  downloads: Record<string, string>;
};

type CandidateWithBatch = RankingCandidate & { time_step: number };
type SampleRoleCounts = Record<'seed' | 'network_cohort' | 'ordinary', number>;

const REFERENCE_SNAPSHOT_PLATFORM = 'darwin';

function sampleRoleCounts(payload: RankingPayload): SampleRoleCounts {
  const counts: SampleRoleCounts = { seed: 0, network_cohort: 0, ordinary: 0 };
  for (const user of payload.users) {
    if (user.sample_role in counts) counts[user.sample_role as keyof SampleRoleCounts] += 1;
  }
  return counts;
}

async function expectDarwinPageScreenshot(page: Page, name: string): Promise<void> {
  if (process.platform !== REFERENCE_SNAPSHOT_PLATFORM) return;
  await expect(page).toHaveScreenshot(name, { animations: 'disabled' });
}

async function expectDarwinLocatorScreenshot(locator: Locator, name: string): Promise<void> {
  if (process.platform !== REFERENCE_SNAPSHOT_PLATFORM) return;
  await expect(locator).toHaveScreenshot(name, { animations: 'disabled' });
}

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
      '.run-evidence-facts > article',
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

async function expectSceneOverlaysInsideAndSeparate(visual: Locator, selector: string): Promise<void> {
  const failures = await visual.locator(selector).evaluateAll((overlays) => {
    const visualBox = overlays[0]?.parentElement?.getBoundingClientRect();
    if (!visualBox) return ['missing visual'];
    const boxes = overlays.map((overlay) => overlay.getBoundingClientRect());
    const failures: string[] = [];
    boxes.forEach((box, index) => {
      if (box.left < visualBox.left || box.right > visualBox.right ||
          box.top < visualBox.top || box.bottom > visualBox.bottom) {
        failures.push(`outside:${index}`);
      }
      boxes.slice(index + 1).forEach((other, offset) => {
        if (Math.min(box.right, other.right) - Math.max(box.left, other.left) > 1 &&
            Math.min(box.bottom, other.bottom) - Math.max(box.top, other.top) > 1) {
          failures.push(`overlap:${index}-${index + offset + 1}`);
        }
      });
    });
    return failures;
  });
  expect(failures).toEqual([]);
}

async function expectMechanismPromptContract(detail: Locator, allowedProfileFields: string[]): Promise<void> {
  await expect(detail).toContainText('Target Marketing Video content');
  await expect(detail).toContainText('neutral PeerContext');
  for (const allowed of allowedProfileFields) await expect(detail).toContainText(allowed);
  for (const excluded of ['ranking', 'network evidence', 'Target Holdout', 'raw Provider Payload']) {
    await expect(detail).toContainText(excluded);
  }
  await expect(detail).toContainText('不进入 Final Research LLM Prompt');
}

async function expectBilingualReaderSurface(page: Page): Promise<void> {
  const failures = await page.evaluate(() => {
    const selectors = [
      '.topbar',
      '.run-method-status',
      '.run-evidence-facts > article > span',
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
  const runEvidenceButton = page.getByTestId('run-evidence-mode-button');
  if ((await runEvidenceButton.getAttribute('aria-selected')) !== 'true') await runEvidenceButton.click();
  await expect(page.getByTestId('run-evidence-mode-panel')).toBeVisible();

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
  const roleCounts = sampleRoleCounts(payload);
  await expect(hero).toHaveClass('run-evidence-intro');
  await expect(hero.getByTestId('run-evidence-method-status')).toContainText('Persisted runtime evidence');
  await expect(hero).toContainText('当高端酒店开始');
  await expect(hero).toContainText(payload.run.sample_size.toLocaleString());
  await expect(hero.getByTestId('run-evidence-seed-count')).toHaveText(roleCounts.seed.toLocaleString());
  await expect(hero.getByTestId('run-evidence-network-cohort-count'))
    .toHaveText(roleCounts.network_cohort.toLocaleString());
  await expect(hero.getByTestId('run-evidence-ordinary-count')).toHaveText(roleCounts.ordinary.toLocaleString());
  await expect(hero).toContainText('不使用 Proposed `20 / 60 / 920` 投影改写本次运行');
  await expect(hero.locator('.run-evidence-facts article')).toHaveCount(6);
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

  await page.getByTestId('shared-batch-timeline').getByRole('button', { name: 'Batch 1', exact: true }).click();
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
  await expect(rankingSection).toContainText(`Batch 1-${payload.run.horizon - 1}`);
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
  await expect(page.getByTestId('round-summary')).toContainText('Eligible');
  const selectedRound = payload.ranking_rounds.find((round) => round.time_step === 1);
  expect(selectedRound).toBeDefined();
  await expect(page.getByTestId('round-summary')).toContainText(
    `Selected（已选择）${selectedRound?.selected_count ?? 0}`,
  );
  await expect(page.getByTestId('ranking-candidate-table').locator('tbody tr')).toHaveCount(
    selectedRound?.selected_count ?? 0,
  );
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
    `Batch 1-${payload.run.horizon - 1}`,
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
  await expect(page.getByTestId('visible-user-count')).toHaveText(
    `${payload.users.length.toLocaleString()} / ${payload.users.length.toLocaleString()}`,
  );
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
  await expect(page.getByTestId('user-table').locator('tbody tr')).toHaveCount(providerFailureCount);
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
  await expect(mechanismPanel).toContainText('三路信号形成相对排序');
  await expect(mechanismPanel).toContainText('平台先决定谁获得 Recommendation Opportunity');
  await expect(mechanismPanel).toContainText('Decision Adapter 只为已曝光用户输出结构化 Decision');
  await page.getByTestId('mechanism-network-impact-details').locator('summary').click();
  for (const imageId of [
    'sample-construction-illustration',
    'batch-zero-seeds-illustration',
    'global-reranking-illustration',
    'platform-llm-boundary-illustration',
    'neighbor-feedback-illustration',
    'capacity-network-impact-illustration',
  ]) {
    const image = page.getByTestId(imageId);
    await expect(image).toBeVisible();
    await expect(image).toHaveAttribute('src', /^data:image\/webp;base64,/);
    expect(await image.evaluate((node: HTMLImageElement) => ({ complete: node.complete, width: node.naturalWidth })))
      .toEqual({ complete: true, width: 1672 });
  }
  expect(externalRequests).toEqual([]);
  await page.evaluate(() => {
    document.documentElement.style.scrollBehavior = 'auto';
    window.scrollTo(0, 0);
  });
  await page.screenshot({ path: testInfo.outputPath('mechanism-report-desktop.png'), fullPage: true });

  await page.getByTestId('run-evidence-mode-button').click();
  await expect(page.getByTestId('final-research-ranking-report')).toHaveAttribute('data-report-mode', 'run-evidence');
  await expect(page.getByTestId('mechanism-mode-panel')).toBeHidden();
  await expect(page.getByTestId('run-evidence-mode-panel')).toBeVisible();
  const runIntro = page.getByTestId('ranking-hero');
  const roleCounts = sampleRoleCounts(payload);
  await expect(runIntro).toContainText(payload.users.length.toLocaleString());
  await expect(runIntro.getByTestId('run-evidence-seed-count')).toHaveText(
    roleCounts.seed.toLocaleString(),
  );
  await expect(runIntro.getByTestId('run-evidence-network-cohort-count')).toHaveText(
    roleCounts.network_cohort.toLocaleString(),
  );
  await expect(runIntro.getByTestId('run-evidence-ordinary-count')).toHaveText(
    roleCounts.ordinary.toLocaleString(),
  );
  await expect(page.getByTestId('sample-comparison-section')).toContainText(
    payload.sample_comparison.final_sample_count.toLocaleString(),
  );
  await expect(page.getByTestId('sample-comparison-section').getByTestId('field-lineage-section')).toBeVisible();
  await expect(page.getByTestId('ranking-rounds-section').getByTestId('batch-delivery-chart')).toBeVisible();
  const decisionSection = page.getByTestId('prompt-contract-section');
  await expect(decisionSection.getByTestId('action-chart')).toBeVisible();
  await expect(decisionSection.getByTestId('provider-failure-chart')).toBeVisible();
  await expect(decisionSection.getByTestId('ranking-users-section')).toBeVisible();
  const feedbackSection = page.getByTestId('network-feedback-section');
  await expect(feedbackSection.getByTestId('network-activation-chart')).toBeVisible();
  await expect(feedbackSection.getByTestId('ablation-overlap-chart')).toBeVisible();
  await expect(page.getByTestId('aggregate-charts-section')).toHaveCount(0);
  await expect(page.getByTestId('run-evidence-mode-panel')).not.toContainText('同源聚合图表');
  expect(
    await page.getByTestId('run-evidence-mode-panel').locator('[data-section-anchor]').evaluateAll((sections) =>
      sections.map((section) => section.getAttribute('data-section-anchor')),
    ),
  ).toEqual(['overview', 'sample', 'exposure-ranking', 'llm-decision', 'network-feedback']);
  await expect(page.locator('select[id*="batch" i], select[id*="round" i]')).toHaveCount(0);

  await page.getByTestId('mechanism-mode-button').focus();
  await page.getByTestId('mechanism-mode-button').press('ArrowRight');
  await expect(page.getByTestId('run-evidence-mode-button')).toBeFocused();
  await expect(page.getByTestId('run-evidence-mode-button')).toHaveAttribute('aria-selected', 'true');
});

test('sample-led opening replaces the generic hero and keeps navigation focus in sync', async ({ page }, testInfo) => {
  const { outputDir } = generateRankingReport(testInfo);
  const reportUrl = pathToFileURL(path.join(outputDir, 'report.html')).toString();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(reportUrl);

  const topbar = page.locator('.topbar');
  const opening = page.getByTestId('mechanism-sample-opening');
  const sampleDetail = page.getByTestId('mechanism-sample-detail');
  const navigation = page.locator('.workflow-nav');
  await expect(page.locator('.brand')).toHaveText('推荐机制');
  await expect(page.locator('.topbar')).toHaveCSS('background-color', 'rgb(251, 252, 254)');
  expect((await topbar.boundingBox())?.height ?? Infinity).toBeLessThanOrEqual(80);
  await expect(page.locator('.mechanism-overview')).toHaveCount(0);
  await expect(opening).toBeVisible();
  await expect(opening.getByRole('heading', { name: '从 36,400 到 1,000' })).toBeVisible();
  await expect(navigation.getByRole('link', { name: '概览' })).toHaveAttribute('aria-current', 'location');

  const [openingBox, visualBox] = await Promise.all([
    opening.boundingBox(),
    sampleDetail.boundingBox(),
  ]);
  expect(openingBox).not.toBeNull();
  expect(visualBox).not.toBeNull();
  expect(((visualBox?.width ?? 0) * (visualBox?.height ?? 0)) / ((openingBox?.width ?? 1) * (openingBox?.height ?? 1)))
    .toBeGreaterThanOrEqual(0.6);
  await expect(opening.locator('figcaption')).toHaveCount(0);

  await navigation.getByRole('link', { name: '样本' }).click();
  await expect(page).toHaveURL(/#sample$/);
  await expect(sampleDetail).toBeFocused();
  await expect(navigation.getByRole('link', { name: '样本' })).toHaveAttribute('aria-current', 'location');
  await expect(navigation.getByRole('link', { name: '概览' })).not.toHaveAttribute('aria-current', 'location');

  await page.getByTestId('mechanism-batch-zero-section').scrollIntoViewIfNeeded();
  await expect(navigation.getByRole('link', { name: '曝光排序' })).toHaveAttribute('aria-current', 'location');

  await page.goto(`${reportUrl}#sample`);
  await expect(page.getByTestId('mechanism-sample-detail')).toBeFocused();
  await expect(navigation.getByRole('link', { name: '样本' })).toHaveAttribute('aria-current', 'location');
});

test('sample hotspots share the detail drawer and clear mechanism selection on mode change', async ({ page }, testInfo) => {
  const { outputDir } = generateRankingReport(testInfo);
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto(pathToFileURL(path.join(outputDir, 'report.html')).toString());

  const drawer = page.getByTestId('evidence-drawer');
  const detail = page.getByTestId('mechanism-detail');
  const seedHotspot = page.getByTestId('sample-hotspot-seed');
  await seedHotspot.focus();
  await seedHotspot.press('Enter');
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole('button', { name: '关闭详情' })).toBeFocused();
  await expect(drawer).toHaveAttribute('data-selection-kind', 'mechanism');
  await expect(detail).toContainText('Full-Pool Influence Seed Union');
  await expect(detail).toContainText('Field Provenance');
  await expect(detail).toContainText('Derived Proxy Metric');
  await expect(detail).toContainText('Field Usage Stage');
  await expect(detail).toContainText('Seed Selection');
  await expect(detail).toContainText('研究限制');
  await drawer.getByRole('button', { name: '关闭详情' }).click();
  await expect(seedHotspot).toBeFocused();

  const neighborHotspot = page.getByTestId('sample-hotspot-neighbor');
  await neighborHotspot.click();
  await expect(detail).toContainText('Seed Neighbor Cohort');
  await expect(detail).toContainText('Comment-Derived User Interaction Graph');
  await expect(detail).toContainText('Historical Behavioral Evidence');
  await expect(detail).toContainText('Sampling');
  await expect(detail).toContainText('Ranking');
  await page.keyboard.press('Escape');
  await expect(neighborHotspot).toBeFocused();

  const ordinaryHotspot = page.getByTestId('sample-hotspot-ordinary');
  await ordinaryHotspot.focus();
  await ordinaryHotspot.press('Space');
  await expect(detail).toContainText('普通补足用户');
  await expect(detail).toContainText('Primary Video Source Scope');
  await expect(detail).toContainText('Report Only');
  await expect(detail).toContainText('不是合成用户');
  await page.getByTestId('run-evidence-mode-button').click();
  await expect(drawer).toBeHidden();
  await expect(drawer).not.toHaveAttribute('data-selection-kind', 'mechanism');
  await expect(ordinaryHotspot).toHaveAttribute('aria-expanded', 'false');
});

test('sample opening keeps its visual contract on both desktop reference viewports', async ({ page }, testInfo) => {
  const { outputDir } = generateRankingReport(testInfo);
  const reportUrl = pathToFileURL(path.join(outputDir, 'report.html')).toString();
  const externalRequests: string[] = [];
  page.on('request', (request) => {
    const protocol = new URL(request.url()).protocol;
    if (protocol !== 'file:' && protocol !== 'data:') externalRequests.push(request.url());
  });

  for (const viewport of [
    { name: '1440x900', width: 1440, height: 900 },
    { name: '1600x1000', width: 1600, height: 1000 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(reportUrl);
    const opening = page.getByTestId('mechanism-sample-opening');
    const headingLines = await opening.getByRole('heading', { name: '从 36,400 到 1,000' }).evaluate((node) => {
      const style = getComputedStyle(node);
      return Math.round(node.getBoundingClientRect().height / Number.parseFloat(style.lineHeight));
    });
    expect(headingLines).toBeLessThanOrEqual(2);

    for (const [countId, hotspotId] of [
      ['sample-count-seed', 'sample-hotspot-seed'],
      ['sample-count-neighbor', 'sample-hotspot-neighbor'],
      ['sample-count-ordinary', 'sample-hotspot-ordinary'],
    ] as const) {
      await expect(page.getByTestId(countId)).toBeVisible();
      const [countBox, hotspotBox] = await Promise.all([
        page.getByTestId(countId).boundingBox(),
        page.getByTestId(hotspotId).boundingBox(),
      ]);
      expect(countBox).not.toBeNull();
      expect(hotspotBox).not.toBeNull();
      expect(Math.abs(
        (countBox?.x ?? 0) + (countBox?.width ?? 0) / 2 -
        ((hotspotBox?.x ?? 0) + (hotspotBox?.width ?? 0) / 2),
      )).toBeLessThanOrEqual(2);
    }

    const image = page.getByTestId('sample-construction-illustration');
    expect(await image.evaluate((node: HTMLImageElement) => ({ complete: node.complete, width: node.naturalWidth })))
      .toEqual({ complete: true, width: 1672 });
    const seedHotspot = page.getByTestId('sample-hotspot-seed');
    await seedHotspot.click();
    await expect(page.getByTestId('evidence-drawer')).toBeVisible();
    await page.getByTestId('evidence-drawer').getByRole('button', { name: '关闭详情' }).click();
    await expect(seedHotspot).toBeFocused();
    await expectNoLayoutFailures(page);
    await expectDarwinPageScreenshot(page, `sample-opening-${viewport.name}.png`);
  }
  expect(externalRequests).toEqual([]);
});

test('Batch 0 and Global Reranking are distinct accessible mechanism scenes', async ({ page }, testInfo) => {
  test.slow();
  const { outputDir } = generateRankingReport(testInfo);
  const reportUrl = pathToFileURL(path.join(outputDir, 'report.html')).toString();
  const externalRequests: string[] = [];
  page.on('request', (request) => {
    const protocol = new URL(request.url()).protocol;
    if (protocol !== 'file:' && protocol !== 'data:') externalRequests.push(request.url());
  });

  for (const viewport of [
    { name: '1440x900', width: 1440, height: 900 },
    { name: '1600x1000', width: 1600, height: 1000 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(reportUrl);
    const navigation = page.locator('.workflow-nav');
    await navigation.getByRole('link', { name: '曝光排序' }).click();
    await expect(page).toHaveURL(/#exposure-ranking$/);
    await expect(navigation.getByRole('link', { name: '曝光排序' })).toHaveAttribute('aria-current', 'location');

    const batchSection = page.getByTestId('mechanism-batch-zero-section');
    const batchVisual = page.getByTestId('batch-zero-scene-visual');
    await expect(batchSection).toBeFocused();
    await expect(batchSection).toContainText('Full-Pool Influence Seed Union');
    await expect(batchSection).toContainText('不是普通 Top20 胜出者');
    const [batchSectionBox, batchVisualBox] = await Promise.all([batchSection.boundingBox(), batchVisual.boundingBox()]);
    expect(batchSectionBox).not.toBeNull();
    expect(batchVisualBox).not.toBeNull();
    expect(((batchVisualBox?.width ?? 0) * (batchVisualBox?.height ?? 0)) /
      ((batchSectionBox?.width ?? 1) * (batchSectionBox?.height ?? 1))).toBeGreaterThanOrEqual(0.6);

    const drawer = page.getByTestId('evidence-drawer');
    const detail = page.getByTestId('mechanism-detail');
    const seedHotspot = page.getByTestId('batch-zero-hotspot-seeds');
    await seedHotspot.focus();
    await seedHotspot.press('Enter');
    await expect(drawer).toHaveAttribute('data-selection-kind', 'mechanism');
    await expect(detail).toContainText('Batch 0 seeds 直接曝光');
    await expect(detail).toContainText('Field Provenance');
    await expect(detail).toContainText('Field Usage Stage');
    await expect(detail).toContainText('Recommendation Signal Inclusion');
    await expect(detail).toContainText('不是普通 Global Reranking Top20 胜出者');
    await drawer.getByRole('button', { name: '关闭详情' }).click();
    await expect(seedHotspot).toBeFocused();

    await expect(page.getByTestId('batch-zero-video-label')).toContainText('Target Marketing Video');
    await expectDarwinLocatorScreenshot(batchSection, `batch-zero-scene-${viewport.name}.png`);

    const rerankingSection = page.getByTestId('mechanism-global-reranking-section');
    const rerankingVisual = page.getByTestId('global-reranking-scene-visual');
    await rerankingSection.scrollIntoViewIfNeeded();
    const [rerankingSectionBox, rerankingVisualBox] = await Promise.all([
      rerankingSection.boundingBox(),
      rerankingVisual.boundingBox(),
    ]);
    expect(rerankingSectionBox).not.toBeNull();
    expect(rerankingVisualBox).not.toBeNull();
    expect(((rerankingVisualBox?.width ?? 0) * (rerankingVisualBox?.height ?? 0)) /
      ((rerankingSectionBox?.width ?? 1) * (rerankingSectionBox?.height ?? 1))).toBeGreaterThanOrEqual(0.6);
    await expect(rerankingSection).toContainText('预声明研究假设');
    await expect(rerankingSection).toContainText('不是抖音平台学习参数或已观测效果');

    const interactions = [
      ['reranking-hotspot-network', 'Enter', '50% 历史评论网络位置', 'holdout-safe P95'],
      ['reranking-hotspot-neighbor', 'Space', '30% 已互动直接邻居', '不是用户可见同伴行为'],
      ['reranking-hotspot-affinity', 'Enter', '20% 历史标签亲和度', 'Historical Set'],
      ['reranking-hotspot-top20', 'Space', 'Global Reranking Top20', 'Delivery Capacity'],
    ] as const;
    for (const [testId, key, title, evidence] of interactions) {
      const hotspot = page.getByTestId(testId);
      await hotspot.focus();
      await hotspot.press(key);
      await expect(detail).toContainText(title);
      await expect(detail).toContainText(evidence);
      await expect(detail).toContainText('Field Provenance');
      await expect(detail).toContainText('Field Usage Stage');
      await expect(detail).toContainText('Recommendation Signal Inclusion');
      await expect(detail).toContainText('Observed Recommendation Signal Effect');
      await drawer.getByRole('button', { name: '关闭详情' }).click();
      await expect(hotspot).toBeFocused();
    }

    for (const section of [batchSection, rerankingSection]) {
      const heading = section.getByRole('heading', { level: 2 });
      const headingLines = await heading.evaluate((node) => {
        const style = getComputedStyle(node);
        return Math.round(node.getBoundingClientRect().height / Number.parseFloat(style.lineHeight));
      });
      expect(headingLines).toBeLessThanOrEqual(2);
    }
    await expectSceneOverlaysInsideAndSeparate(rerankingVisual, '.mechanism-hotspot, .scene-status');
    await expectNoLayoutFailures(page);
    await expectDarwinLocatorScreenshot(rerankingSection, `global-reranking-scene-${viewport.name}.png`);
  }
  expect(externalRequests).toEqual([]);
});

test('Platform Environment and Decision Adapter keep exposure and action responsibilities separate', async ({ page }, testInfo) => {
  test.slow();
  const { outputDir, payload } = generateRankingReport(testInfo);
  const reportUrl = pathToFileURL(path.join(outputDir, 'report.html')).toString();
  const externalRequests: string[] = [];
  page.on('request', (request) => {
    const protocol = new URL(request.url()).protocol;
    if (protocol !== 'file:' && protocol !== 'data:') externalRequests.push(request.url());
  });

  for (const viewport of [
    { name: '1440x900', width: 1440, height: 900 },
    { name: '1600x1000', width: 1600, height: 1000 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(reportUrl);
    const navigation = page.locator('.workflow-nav');
    await navigation.getByRole('link', { name: 'LLM 决策' }).click();
    await expect(page).toHaveURL(/#llm-decision$/);
    await expect(navigation.getByRole('link', { name: 'LLM 决策' })).toHaveAttribute('aria-current', 'location');

    const section = page.getByTestId('mechanism-platform-llm-section');
    const visual = page.getByTestId('platform-llm-scene-visual');
    await expect(section).toBeFocused();
    await expect(section.getByRole('heading', {
      name: '平台先决定谁获得 Recommendation Opportunity',
    })).toBeVisible();
    await expect(section).toContainText('LLM 不负责曝光调度');
    await expect(section).toContainText('Decision Adapter 只为已曝光用户输出结构化 Decision');

    const [sectionBox, visualBox] = await Promise.all([section.boundingBox(), visual.boundingBox()]);
    expect(sectionBox).not.toBeNull();
    expect(visualBox).not.toBeNull();
    expect(((visualBox?.width ?? 0) * (visualBox?.height ?? 0)) /
      ((sectionBox?.width ?? 1) * (sectionBox?.height ?? 1))).toBeGreaterThanOrEqual(0.6);

    const drawer = page.getByTestId('evidence-drawer');
    const detail = page.getByTestId('mechanism-detail');
    const responsibilityInteractions = [
      ['platform-gate-hotspot', 'Enter', 'Platform Environment gate', 'Global Reranking', 'Delivery Capacity'],
      ['decision-adapter-hotspot', 'Space', 'Decision Adapter', 'allowlisted profile fields', 'neutral PeerContext'],
    ] as const;
    for (const [testId, key, title, firstEvidence, secondEvidence] of responsibilityInteractions) {
      const hotspot = page.getByTestId(testId);
      await hotspot.focus();
      await hotspot.press(key);
      await expect(drawer).toHaveAttribute('data-selection-kind', 'mechanism');
      await expect(detail).toContainText(title);
      await expect(detail).toContainText(firstEvidence);
      await expect(detail).toContainText(secondEvidence);
      await expectMechanismPromptContract(detail, payload.prompt_contract.allowed_profile_fields);
      await drawer.getByRole('button', { name: '关闭详情' }).click();
      await expect(hotspot).toBeFocused();
    }

    const actionInteractions = [
      ['decision-like-hotspot', 'like', '正向轻量互动'],
      ['decision-comment-hotspot', 'comment', '生成文字互动'],
      ['decision-share-hotspot', 'share', '进一步传播内容'],
      ['decision-ignore-hotspot', 'ignore', '已曝光但不互动'],
    ] as const;
    for (const [testId, action, meaning] of actionInteractions) {
      const hotspot = page.getByTestId(testId);
      await hotspot.focus();
      await hotspot.press('Enter');
      await expect(detail).toContainText(`${action} action`);
      await expect(detail).toContainText(meaning);
      await expect(detail).toContainText('engage / probability / reason / confidence / action');
      await expect(detail).toContainText('结构化 Decision');
      await expectMechanismPromptContract(detail, payload.prompt_contract.allowed_profile_fields);
      await expect(detail.locator('dl div', { hasText: 'Field Usage Stage' }).locator('dd'))
        .toHaveText('Report Only（仅报告展示）');
      await drawer.getByRole('button', { name: '关闭详情' }).click();
      await expect(hotspot).toBeFocused();
    }

    await expectSceneOverlaysInsideAndSeparate(visual, '.platform-llm-label, .platform-llm-hotspot');

    await navigation.getByRole('link', { name: 'LLM 决策' }).click();
    const headingLines = await section.getByRole('heading', { level: 2 }).evaluate((node) => {
      const style = getComputedStyle(node);
      return Math.round(node.getBoundingClientRect().height / Number.parseFloat(style.lineHeight));
    });
    expect(headingLines).toBeLessThanOrEqual(2);
    await expect.poll(async () => {
      const [topbarBox, headingBox] = await Promise.all([
        page.locator('.topbar').boundingBox(),
        section.getByRole('heading', { level: 2 }).boundingBox(),
      ]);
      if (!topbarBox || !headingBox) return Number.NEGATIVE_INFINITY;
      return headingBox.y - (topbarBox.y + topbarBox.height);
    }).toBeGreaterThanOrEqual(0);
    await expectNoLayoutFailures(page);
    await expectDarwinLocatorScreenshot(section, `platform-llm-scene-${viewport.name}.png`);

    await page.getByTestId('decision-like-hotspot').click();
    await expect(drawer).toBeVisible();
    await page.getByTestId('run-evidence-mode-button').click();
    await expect(drawer).toBeHidden();
    await expect(page.getByTestId('run-evidence-mode-panel')).toBeVisible();
  }
  expect(externalRequests).toEqual([]);
});

test('successful actions activate direct neighbors only in the next Global Reranking', async ({ page }, testInfo) => {
  test.slow();
  const { outputDir } = generateRankingReport(testInfo);
  const reportUrl = pathToFileURL(path.join(outputDir, 'report.html')).toString();
  const externalRequests: string[] = [];
  page.on('request', (request) => {
    const protocol = new URL(request.url()).protocol;
    if (protocol !== 'file:' && protocol !== 'data:') externalRequests.push(request.url());
  });

  for (const viewport of [
    { name: '1440x900', width: 1440, height: 900 },
    { name: '1600x1000', width: 1600, height: 1000 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(reportUrl);
    const navigation = page.locator('.workflow-nav');
    await navigation.getByRole('link', { name: '网络反馈' }).click();
    await expect(page).toHaveURL(/#network-feedback$/);
    await expect(navigation.getByRole('link', { name: '网络反馈' })).toHaveAttribute('aria-current', 'location');
    await expect(navigation.getByRole('link')).toHaveCount(5);

    const section = page.getByTestId('mechanism-network-feedback-section');
    const visual = page.getByTestId('neighbor-feedback-scene-visual');
    await expect(section).toBeFocused();
    await expect(section.getByRole('heading', { name: '成功互动只激活一跳直接邻居' })).toBeVisible();
    await expect(section).toContainText('只进入下一轮 Global Reranking');
    await expect(section).toContainText('不表示用户真实看见了邻居互动');

    const [sectionBox, visualBox] = await Promise.all([section.boundingBox(), visual.boundingBox()]);
    expect(sectionBox).not.toBeNull();
    expect(visualBox).not.toBeNull();
    expect(((visualBox?.width ?? 0) * (visualBox?.height ?? 0)) /
      ((sectionBox?.width ?? 1) * (sectionBox?.height ?? 1))).toBeGreaterThanOrEqual(0.6);

    const image = page.getByTestId('neighbor-feedback-illustration');
    expect(await image.evaluate((node: HTMLImageElement) => ({ complete: node.complete, width: node.naturalWidth })))
      .toEqual({ complete: true, width: 1672 });

    const drawer = page.getByTestId('evidence-drawer');
    const detail = page.getByTestId('mechanism-detail');
    const propagatingActions = [
      ['feedback-like-hotspot', 'like 激活直接邻居'],
      ['feedback-comment-hotspot', 'comment 激活直接邻居'],
      ['feedback-share-hotspot', 'share 激活直接邻居'],
    ] as const;
    for (const [testId, title] of propagatingActions) {
      const hotspot = page.getByTestId(testId);
      await hotspot.focus();
      await hotspot.press('Enter');
      await expect(drawer).toHaveAttribute('data-selection-kind', 'mechanism');
      await expect(detail).toContainText(title);
      await expect(detail).toContainText('一跳直接邻居');
      await expect(detail).toContainText('下一轮 Global Reranking');
      await expect(detail).toContainText('不是用户可见同伴行为');
      await drawer.getByRole('button', { name: '关闭详情' }).click();
      await expect(hotspot).toBeFocused();
    }

    const ignoreHotspot = page.getByTestId('feedback-ignore-hotspot');
    await ignoreHotspot.focus();
    await ignoreHotspot.press('Space');
    await expect(detail).toContainText('ignore 停止传播');
    await expect(detail).toContainText('不会激活任何直接邻居');
    await drawer.getByRole('button', { name: '关闭详情' }).click();
    await expect(ignoreHotspot).toBeFocused();

    for (const [testId, title, evidence] of [
      ['feedback-neighbors-hotspot', '一跳直接邻居', 'Comment-Derived User Interaction Graph'],
      ['feedback-next-round-hotspot', '下一轮 Global Reranking', 'engaged_neighbor_signal'],
    ] as const) {
      const hotspot = page.getByTestId(testId);
      await hotspot.click();
      await expect(detail).toContainText(title);
      await expect(detail).toContainText(evidence);
      await drawer.getByRole('button', { name: '关闭详情' }).click();
    }

    for (const forbiddenRunResult of ['Top20 overlap', 'network-added', 'network-removed', 'rank delta']) {
      await expect(section).not.toContainText(forbiddenRunResult);
    }
    const headingLines = await section.getByRole('heading', { level: 2 }).evaluate((node) => {
      const style = getComputedStyle(node);
      return Math.round(node.getBoundingClientRect().height / Number.parseFloat(style.lineHeight));
    });
    expect(headingLines).toBeLessThanOrEqual(2);
    await expectSceneOverlaysInsideAndSeparate(visual, '.feedback-hotspot, .scene-status');
    for (const [testId, maximumRightRatio] of [
      ['feedback-like-hotspot', 0.27],
      ['feedback-comment-hotspot', 0.27],
      ['feedback-share-hotspot', 0.25],
      ['feedback-ignore-hotspot', 0.16],
    ] as const) {
      const [hotspotBox, currentVisualBox] = await Promise.all([
        page.getByTestId(testId).boundingBox(),
        visual.boundingBox(),
      ]);
      expect(hotspotBox).not.toBeNull();
      expect(currentVisualBox).not.toBeNull();
      expect(((hotspotBox?.x ?? 0) + (hotspotBox?.width ?? 0) - (currentVisualBox?.x ?? 0)) /
        (currentVisualBox?.width ?? 1)).toBeLessThanOrEqual(maximumRightRatio);
    }
    const [topbarBox, feedbackStatusBox] = await Promise.all([
      page.locator('.topbar').boundingBox(),
      visual.locator('.feedback-status').boundingBox(),
    ]);
    expect(feedbackStatusBox?.y ?? 0).toBeGreaterThanOrEqual((topbarBox?.y ?? 0) + (topbarBox?.height ?? 0));
    await expectNoLayoutFailures(page);
    await navigation.getByRole('link', { name: '网络反馈' }).click();
    await expect(section).toBeFocused();
    await expectDarwinPageScreenshot(page, `neighbor-feedback-scene-${viewport.name}.png`);
  }
  expect(externalRequests).toEqual([]);
});

test('Delivery Capacity compares full and no-network ranking on frozen candidate evidence', async ({ page }, testInfo) => {
  test.slow();
  const { outputDir } = generateRankingReport(testInfo);
  const reportUrl = pathToFileURL(path.join(outputDir, 'report.html')).toString();
  const externalRequests: string[] = [];
  page.on('request', (request) => {
    const protocol = new URL(request.url()).protocol;
    if (protocol !== 'file:' && protocol !== 'data:') externalRequests.push(request.url());
  });

  for (const viewport of [
    { name: '1440x900', width: 1440, height: 900 },
    { name: '1600x1000', width: 1600, height: 1000 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(reportUrl);
    await page.locator('.workflow-nav').getByRole('link', { name: '网络反馈' }).click();

    const disclosure = page.getByTestId('mechanism-network-impact-details');
    const section = page.getByTestId('mechanism-capacity-comparison-section');
    await expect(section).toBeHidden();
    await disclosure.locator('summary').click();
    await expect(section).toBeVisible();
    await expect(disclosure).toHaveAttribute('open', '');

    const visual = page.getByTestId('capacity-network-scene-visual');
    await expect(section.getByRole('heading', { name: '600 人容量内并列比较两种排序' })).toBeVisible();
    await expect(section).toContainText('1,000 人 Proposed Research Sample');
    await expect(section).toContainText('600 人最多获得 Recommendation Opportunity');
    await expect(section).toContainText('400 人保持 below_delivery_capacity');
    await expect(section).toContainText('未曝光，不是 ignore');
    await expect(section).toContainText('同批冻结 candidate evidence');
    await expect(section).toContainText('零额外 Decision Adapter calls');
    await expect(section).toContainText('不推进第二条 trajectory');
    await expect(section).toContainText('不预设网络一定改变 Top20');

    const [sectionBox, visualBox] = await Promise.all([section.boundingBox(), visual.boundingBox()]);
    expect(sectionBox).not.toBeNull();
    expect(visualBox).not.toBeNull();
    expect(((visualBox?.width ?? 0) * (visualBox?.height ?? 0)) /
      ((sectionBox?.width ?? 1) * (sectionBox?.height ?? 1))).toBeGreaterThanOrEqual(0.6);
    const image = page.getByTestId('capacity-network-impact-illustration');
    expect(await image.evaluate((node: HTMLImageElement) => ({ complete: node.complete, width: node.naturalWidth })))
      .toEqual({ complete: true, width: 1672 });

    const drawer = page.getByTestId('evidence-drawer');
    const detail = page.getByTestId('mechanism-detail');
    const interactions = [
      ['capacity-limit-hotspot', 'Delivery Capacity 上限', '30 个 Batch', '最多 600'],
      ['below-capacity-hotspot', 'below_delivery_capacity', '没有获得目标视频曝光', '不是 ignore'],
      ['frozen-evidence-hotspot', '同批冻结 candidate evidence', '不调用 Decision Adapter', '不是第二条完整 trajectory'],
      ['full-ranking-hotspot', 'full ranking', '保留网络信号', '不预设改变 Top20'],
      ['no-network-ranking-hotspot', 'no-network ranking', '移除评论网络贡献', '同一批候选'],
    ] as const;
    for (const [testId, title, firstEvidence, secondEvidence] of interactions) {
      const hotspot = page.getByTestId(testId);
      await hotspot.focus();
      await hotspot.press('Enter');
      await expect(drawer).toHaveAttribute('data-selection-kind', 'mechanism');
      await expect(detail).toContainText(title);
      await expect(detail).toContainText(firstEvidence);
      await expect(detail).toContainText(secondEvidence);
      await drawer.getByRole('button', { name: '关闭详情' }).click();
      await expect(hotspot).toBeFocused();
    }

    for (const forbiddenRunResult of ['Top20 overlap', 'network-added', 'network-removed', 'rank delta']) {
      await expect(section).not.toContainText(forbiddenRunResult);
    }
    const headingLines = await section.getByRole('heading', { level: 2 }).evaluate((node) => {
      const style = getComputedStyle(node);
      return Math.round(node.getBoundingClientRect().height / Number.parseFloat(style.lineHeight));
    });
    expect(headingLines).toBeLessThanOrEqual(2);
    await expectSceneOverlaysInsideAndSeparate(visual, '.capacity-hotspot, .scene-status');
    const safeCapacityLabels = [
      ['capacity-limit-hotspot', 0.24, 0.34],
      ['below-capacity-hotspot', 0.24, 0.42],
      ['frozen-evidence-hotspot', 0.58, 0.54],
    ] as const;
    for (const [testId, maximumRightRatio, maximumBottomRatio] of safeCapacityLabels) {
      const [hotspotBox, currentVisualBox] = await Promise.all([
        page.getByTestId(testId).boundingBox(),
        visual.boundingBox(),
      ]);
      expect(hotspotBox).not.toBeNull();
      expect(currentVisualBox).not.toBeNull();
      expect(((hotspotBox?.x ?? 0) + (hotspotBox?.width ?? 0) - (currentVisualBox?.x ?? 0)) /
        (currentVisualBox?.width ?? 1)).toBeLessThanOrEqual(maximumRightRatio);
      expect(((hotspotBox?.y ?? 0) + (hotspotBox?.height ?? 0) - (currentVisualBox?.y ?? 0)) /
        (currentVisualBox?.height ?? 1)).toBeLessThanOrEqual(maximumBottomRatio);
    }
    await expectNoLayoutFailures(page);
    await section.evaluate((element) => {
      const top = element.getBoundingClientRect().top + window.scrollY - 68;
      window.scrollTo({ top, behavior: 'instant' });
    });
    await expectDarwinPageScreenshot(page, `capacity-network-scene-${viewport.name}.png`);
  }
  expect(externalRequests).toEqual([]);
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
  await expect(page.getByTestId('ranking-batch-title')).toContainText('Seed direct exposure');
  await expect(page.getByTestId('reranking-evidence-contract')).toBeHidden();
  await expect(page.getByTestId('ranking-candidate-table').getByRole('columnheader')).toHaveText([
    'Seed order（种子顺序）',
    'User（用户）',
  ]);

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
  await expect(page.getByTestId('ranking-batch-title')).toContainText('Global Reranking');
  await expect(page.getByTestId('reranking-evidence-contract')).toBeVisible();
  await expect(page.getByTestId('ranking-candidate-table')).toContainText(selectedCandidate?.user_id ?? '');
  await expect(page.getByTestId('batch-decision-evidence')).toContainText(exposedUser?.user_id ?? '');
  await expect(page.getByTestId('batch-decision-evidence')).toContainText(exposedUser?.provider_status ?? '');

  await page.getByTestId('ranking-candidate-table').locator('tbody tr').first().click();
  await expect(page.getByTestId('evidence-drawer')).toBeVisible();
  const batchTwoButton = timeline.getByRole('button', { name: 'Batch 2', exact: true });
  await batchTwoButton.click();
  await expect(page.getByTestId('evidence-drawer')).toBeHidden();
  await expect(batchTwoButton).toBeFocused();
});

test('one persisted Batch selection updates direct-neighbor feedback without propagating ignore', async ({ page }, testInfo) => {
  const { outputDir, payload } = generateRankingReport(testInfo, 'effect');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(pathToFileURL(path.join(outputDir, 'report.html')).toString());
  await page.getByTestId('run-evidence-mode-button').click();

  const sourceRound = payload.ranking_rounds.find(
    (round) => round.time_step < payload.run.horizon - 1 && round.target_exposures > 0,
  );
  expect(sourceRound).toBeDefined();
  const sourceBatch = sourceRound?.time_step ?? 0;
  const nextRound = payload.ranking_rounds.find((round) => round.time_step === sourceBatch + 1);
  expect(nextRound).toBeDefined();
  const actions = payload.users.filter((user) => user.exposure_time_step === sourceBatch);
  const propagatingActions = actions.filter((user) => ['like', 'comment', 'share'].includes(user.action));
  const ignored = actions.filter((user) => user.action === 'ignore');
  const sourceNeighborCounts = new Map(
    sourceRound?.candidates.map((candidate) => [candidate.user_id, candidate.engaged_neighbor_count]),
  );
  const nextBatchActivated = nextRound?.candidates.filter(
    (candidate) => candidate.engaged_neighbor_count > (sourceNeighborCounts.get(candidate.user_id) ?? 0),
  ) ?? [];

  await page.getByTestId('shared-batch-timeline').getByRole('button', {
    name: `Batch ${sourceBatch}`,
    exact: true,
  }).click();
  const feedback = page.getByTestId('network-feedback-section');
  const feedbackSummary = page.getByTestId('network-feedback-summary');
  await expect(feedback).toContainText(`Batch ${sourceBatch}`);
  await expect(feedbackSummary.locator('article', { hasText: '可传播 action（动作）' })).toContainText(
    `${propagatingActions.length.toLocaleString()} 个`,
  );
  await expect(feedbackSummary.locator('article', { hasText: 'ignore（忽略）' })).toContainText(
    `${ignored.length.toLocaleString()} 个`,
  );
  await expect(feedback).toContainText(`Batch ${sourceBatch + 1}`);
  await expect(feedbackSummary.locator('article', { hasText: '新增直接邻居信号' })).toContainText(
    `${nextBatchActivated.length.toLocaleString()} 位候选`,
  );
  await expect(feedback).toContainText('相对上一批的 engaged_neighbor_count（已互动邻居数）增加');
  await expect(feedback).toContainText('只影响下一轮 Global Reranking');
  await expect(feedback).toContainText('ignore 不传播');
  await expect(feedback).toContainText('不表示用户真实看见了邻居互动');
  await expect(feedback).toContainText('每次反馈只作用于一跳直接邻居');
  await expect(feedback).toContainText('后续互动可能跨批形成新的直接邻居反馈');

  await feedbackSummary.locator('article', { hasText: '新增直接邻居信号' }).click();
  const drawer = page.getByTestId('evidence-drawer');
  await expect(drawer).toBeVisible();
  await expect(drawer).toHaveAttribute('data-selection-kind', 'network');
  await expect(drawer).toContainText('ranking_rounds.candidates.engaged_neighbor_count');
  await expect(drawer).toContainText('Field Provenance（字段来源）');
  await expect(drawer).toContainText('Field Usage Stage（字段使用阶段）');
  await expect(drawer).toContainText('每次反馈只作用于一跳直接邻居');
});

test('network impact expands inside feedback with payload-derived capacity and paired ranking', async ({ page }, testInfo) => {
  const { outputDir, payload } = generateRankingReport(testInfo, 'effect');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(pathToFileURL(path.join(outputDir, 'report.html')).toString());
  await page.getByTestId('run-evidence-mode-button').click();

  const diagnostic = payload.ranking_diagnostics.paired_ablation.batches.find((batch) => batch.time_step === 1);
  expect(diagnostic).toBeDefined();
  const configuredCapacity = payload.run.horizon * payload.run.delivery_capacity;
  const batchZeroExposures = payload.ranking_rounds.find((round) => round.time_step === 0)?.target_exposures ?? 0;
  const runtimeCapacity = batchZeroExposures + (payload.run.horizon - 1) * payload.run.delivery_capacity;
  const maximumExposures = Math.min(
    payload.run.sample_size,
    runtimeCapacity,
  );
  expect(payload.run.maximum_target_exposures).toBe(configuredCapacity);
  const belowCapacity = payload.users.filter((user) => user.result_status === 'below_delivery_capacity').length;
  const ignored = payload.users.filter((user) => user.result_status === 'ignore').length;

  await page.getByTestId('shared-batch-timeline').getByRole('button', { name: 'Batch 1', exact: true }).click();
  const feedback = page.getByTestId('network-feedback-section');
  const impact = feedback.getByTestId('network-impact-details');
  await expect(impact).toBeVisible();
  await impact.locator('summary').click();
  await expect(impact).toContainText(
    `${payload.run.horizon} 批 × 每批 ${payload.run.delivery_capacity} 人 = ${payload.run.horizon * payload.run.delivery_capacity}`,
  );
  await expect(impact).toContainText(`Batch 0 持久化曝光 ${batchZeroExposures.toLocaleString()} 人`);
  await expect(impact).toContainText(`运行调度上限为 ${runtimeCapacity.toLocaleString()} 人`);
  await expect(impact).toContainText(`样本 ${payload.run.sample_size.toLocaleString()} 人`);
  await expect(impact).toContainText(`最多曝光 ${maximumExposures.toLocaleString()} 人`);
  await expect(impact).toContainText(`${belowCapacity.toLocaleString()} 个 below_delivery_capacity`);
  await expect(impact).toContainText('未曝光');
  await expect(impact).toContainText(`${ignored.toLocaleString()} 个 ignore`);
  await expect(impact).toContainText('已曝光后选择不互动');
  await expect(impact).toContainText(
    payload.ranking_diagnostics_summary.top_selection_changed
      ? 'Observed Recommendation Signal Effect：本次运行存在可观测变化'
      : 'Observed Recommendation Signal Effect：本次运行未观察到变化',
  );
  await expect(impact).toContainText(`Top${payload.run.delivery_capacity} overlap`);
  await expect(impact).toContainText(diagnostic?.top_overlap_count.toLocaleString() ?? '');
  await expect(impact).toContainText(`network-added（网络新增）${diagnostic?.network_added_user_ids.length ?? 0}`);
  await expect(impact).toContainText(`network-removed（网络移除）${diagnostic?.network_removed_user_ids.length ?? 0}`);
  await expect(impact).toContainText('同批冻结 persisted candidate evidence');
  await expect(impact).toContainText('零额外 Decision Adapter calls');
  await expect(impact).toContainText('不是第二条完整 trajectory');
  await expect(impact).toContainText('不是因果实验');
});

test('paired ranking differences use the unified right detail drawer', async ({ page }, testInfo) => {
  const { outputDir, payload } = generateRankingReport(testInfo, 'effect');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(pathToFileURL(path.join(outputDir, 'report.html')).toString());
  await page.getByTestId('run-evidence-mode-button').click();
  await page.getByTestId('shared-batch-timeline').getByRole('button', { name: 'Batch 1', exact: true }).click();
  await page.getByTestId('network-impact-details').locator('summary').click();

  const diagnostic = payload.ranking_diagnostics.paired_ablation.batches.find((batch) => batch.time_step === 1);
  expect(diagnostic).toBeDefined();
  const delta = diagnostic?.rank_deltas.find((row) =>
    diagnostic.network_added_user_ids.includes(row.user_id) || diagnostic.network_removed_user_ids.includes(row.user_id),
  ) ?? diagnostic?.rank_deltas[0];
  expect(delta).toBeDefined();
  const user = payload.users.find((row) => row.user_id === delta?.user_id);
  expect(user).toBeDefined();
  const selectionEffect = diagnostic?.network_added_user_ids.includes(delta?.user_id ?? '')
    ? 'network-added（网络新增）'
    : diagnostic?.network_removed_user_ids.includes(delta?.user_id ?? '')
      ? 'network-removed（网络移除）'
      : diagnostic?.full_top_user_ids.includes(delta?.user_id ?? '')
        ? 'retained（保留）'
        : 'not-selected（未入选）';

  await page.getByTestId('ablation-rank-deltas').locator('tbody tr', { hasText: delta?.user_id }).click();
  const drawer = page.getByTestId('evidence-drawer');
  await expect(drawer).toBeVisible();
  await expect(drawer).toHaveAttribute('data-selection-kind', 'network');
  await expect(drawer).toContainText(delta?.user_id ?? '');
  await expect(drawer).toContainText(user?.nickname ?? '');
  await expect(drawer).toContainText('Batch（批次）1');
  await expect(drawer).toContainText(`full rank（完整排序名次）${delta?.full_rank ?? ''}`);
  await expect(drawer).toContainText(`no-network rank（无网络排序名次）${delta?.no_network_rank ?? ''}`);
  await expect(drawer).toContainText(`rank delta（名次变化）${delta?.network_rank_delta ?? ''}`);
  await expect(drawer).toContainText(selectionEffect);
  await expect(drawer).toContainText(user?.action ?? '');
  await expect(drawer).toContainText(user?.reason ?? '');
  await expect(drawer).toContainText('Field Provenance（字段来源）');
  await expect(drawer).toContainText('Field Usage Stage（字段使用阶段）');
  await expect(drawer).toContainText('同批冻结 candidate evidence');
  await expect(drawer).toContainText('不调用 Decision Adapter');
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
  const candidateUser = payload.users.find((row) => row.user_id === candidate?.user_id);
  expect(candidateUser).toBeDefined();
  await page.getByTestId('ranking-candidate-table').locator('tbody tr').first().click();
  await expect(drawer).toBeVisible();
  await expect(drawer).toHaveAttribute('data-selection-kind', 'candidate');
  await expect(drawer).toContainText(candidate?.user_id ?? '');
  await expect(drawer).toContainText(candidateUser?.nickname ?? '');
  await expect(drawer).toContainText(candidateUser?.sample_role ?? '');
  await expect(drawer).toContainText('Batch（批次）1');
  await expect(drawer).toContainText(`ranking position（排序名次）${candidate?.ranking_position ?? ''}`);
  await expect(drawer).toContainText(candidateUser?.action ?? '');
  await expect(drawer).toContainText(candidateUser?.confidence?.toFixed(4) ?? '');
  await expect(drawer).toContainText(candidateUser?.reason ?? '');
  await expect(drawer).toContainText('Score contribution（分数贡献）');
  for (const value of [
    candidate?.base_network_relevance,
    candidate?.engaged_neighbor_signal,
    candidate?.historical_tag_affinity,
  ]) {
    await expect(drawer).toContainText(value?.toFixed(4) ?? '');
  }
  await page.screenshot({ path: testInfo.outputPath('ranking-candidate-drawer-desktop.png') });

  await page.getByTestId('shared-batch-timeline').getByRole('button', { name: 'Batch 2', exact: true }).click();
  await expect(drawer).toBeHidden();
  await expect(drawer).not.toHaveAttribute('data-selection-kind', /.+/);
  await page.getByTestId('shared-batch-timeline').getByRole('button', { name: 'Batch 1', exact: true }).click();

  const user = payload.users.find((row) => row.exposure_time_step === 1);
  expect(user).toBeDefined();
  await page.getByTestId('user-search').fill(user?.user_id ?? '');
  await page.getByTestId('user-table').locator('.profile-id').filter({
    hasText: new RegExp(`^${user?.user_id ?? ''}$`),
  }).click();
  await expect(drawer).toHaveAttribute('data-selection-kind', 'user');
  await expect(drawer).toContainText(user?.user_id ?? '');
  await expect(drawer).toContainText(user?.nickname ?? '');
  await expect(drawer).toContainText(user?.sample_role ?? '');
  await expect(drawer).toContainText(user?.action ?? '');
  await expect(drawer).toContainText(user?.confidence?.toFixed(4) ?? '');
  await expect(drawer).toContainText(user?.reason ?? '');
  await expect(drawer).toContainText('Field Provenance（字段来源）');
  await expect(drawer).toContainText('Field Usage Stage（字段使用阶段）');

  const promptField = page.getByTestId('prompt-contract-section').getByRole('button').first();
  const promptFieldName = (await promptField.textContent())?.split('（')[0] ?? '';
  await promptField.click();
  await expect(drawer).toHaveAttribute('data-selection-kind', 'field');
  await expect(drawer).toContainText(promptFieldName);
  const promptFieldLineage = payload.field_lineage.find((entry) => entry.field_name === promptFieldName);
  expect(promptFieldLineage).toBeDefined();
  await expect(drawer).toContainText(promptFieldLineage?.provenance ?? '');
  for (const stage of promptFieldLineage?.usage_stages ?? []) await expect(drawer).toContainText(stage);
  await expect(drawer).toContainText('Field Provenance（字段来源）');
  await expect(drawer).toContainText('Field Usage Stage（字段使用阶段）');

  await page.getByTestId('mechanism-mode-button').click();
  await expect(drawer).toBeHidden();
  await expect(drawer).not.toHaveAttribute('data-selection-kind', /.+/);
});

test('ranking research report is complete and interactive on desktop viewports', async ({ page }, testInfo) => {
  test.slow();
  const { outputDir, payload } = generateRankingReport(testInfo);
  for (const viewport of [
    { name: 'laptop', width: 1280, height: 800 },
    { name: 'desktop', width: 1440, height: 1000 },
  ]) {
    await page.setViewportSize(viewport);
    await assertRankingReport(page, outputDir, payload, viewport.height);
    await page.screenshot({ path: testInfo.outputPath(`ranking-report-${viewport.name}.png`), fullPage: true });
  }
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

test('configured formal ranking run preserves payload-derived evidence on desktop', async ({ page }, testInfo) => {
  const configuredRunDir = process.env.FINAL_RESEARCH_FORMAL_RUN_DIR;
  test.skip(!configuredRunDir, 'Set FINAL_RESEARCH_FORMAL_RUN_DIR to validate the local formal run.');
  if (!configuredRunDir) return;

  const runDir = path.resolve(configuredRunDir);
  const payloadPath = path.join(runDir, 'final_research_report_payload.json');
  const reportPath = path.join(runDir, 'report.html');
  expect(existsSync(payloadPath)).toBeTruthy();
  const artifactManifest = JSON.parse(
    readFileSync(path.join(runDir, 'artifact_manifest.json'), 'utf8'),
  ) as { artifacts: Record<string, string> };
  const expectedPreservedArtifactNames = [
    ...Object.values(artifactManifest.artifacts).filter((name) => name !== 'report.html'),
    'artifact_manifest.json',
  ].sort();
  const preservedArtifactNames = readdirSync(runDir).filter((name) => name !== 'report.html').sort();
  const artifactsBeforeRebuild = new Map(
    preservedArtifactNames.map((name) => [name, readFileSync(path.join(runDir, name))]),
  );
  execFileSync(path.resolve('.venv/bin/python'), [
    '-c',
    'import sys; from llm_abm_sim.final_research_report import rebuild_final_research_report; rebuild_final_research_report(sys.argv[1])',
    runDir,
  ]);
  expect(preservedArtifactNames).toEqual(expectedPreservedArtifactNames);
  expect(readdirSync(runDir).filter((name) => name !== 'report.html').sort()).toEqual(preservedArtifactNames);
  for (const [name, before] of artifactsBeforeRebuild) {
    expect(readFileSync(path.join(runDir, name)).equals(before), name).toBeTruthy();
  }

  const payload = JSON.parse(readFileSync(payloadPath, 'utf8')) as RankingPayload;
  const formalRoleCounts = sampleRoleCounts(payload);
  expect(formalRoleCounts).toEqual({ seed: 20, network_cohort: 13, ordinary: 967 });
  const changedBatches = payload.ranking_diagnostics.paired_ablation.batches.filter(
    (batch) => batch.network_added_user_ids.length > 0 || batch.network_removed_user_ids.length > 0,
  ).length;
  expect(payload.ranking_diagnostics_summary.batches_with_top_selection_change).toBe(changedBatches);
  expect(payload.ranking_diagnostics_summary.top_selection_changed).toBe(changedBatches > 0);
  expect(payload.ranking_rounds).toHaveLength(payload.run.horizon);
  const weakerVariant = payload.ranking_diagnostics.weight_sensitivity.variants.find(
    (variant) => variant.variant_id === 'weaker_network_40_20_40',
  );
  expect(weakerVariant).toBeDefined();
  if (!weakerVariant) return;
  const weakerAverages = sensitivityAverages(weakerVariant);
  expect(weakerAverages.overlap).toBeGreaterThanOrEqual(0);
  expect(weakerAverages.overlap).toBeLessThanOrEqual(payload.run.delivery_capacity);
  expect(weakerAverages.changed).toBeGreaterThanOrEqual(0);

  const candidate = selectWorkedCandidate(payload);
  const weights = payload.ranking_diagnostics_summary.main_weights;
  const contributions = [
    candidate.base_network_relevance * weights.base_network,
    candidate.engaged_neighbor_signal * weights.engaged_neighbor,
    candidate.historical_tag_affinity * weights.tag_affinity,
  ];
  const calculatedScore = contributions.reduce((total, value) => total + value, 0);
  expect(candidate.recommendation_score).toBeCloseTo(calculatedScore, 10);
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
        .filter((row) => row.selected && row.engaged_neighbor_signal > 0)
        .map((row) => row.user_id),
    ),
  );
  const positiveSignalActions = payload.users.filter(
    (user) => positiveSelectedUserIds.has(user.user_id) && user.action,
  ).length;

  for (const viewport of [
    { name: 'laptop', width: 1280, height: 800 },
    { name: 'desktop', width: 1440, height: 1000 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(pathToFileURL(reportPath).toString());
    await assertReaderComprehensionContract(page, runDir, payload);
    const runIntro = page.getByTestId('ranking-hero');
    await expect(runIntro.getByTestId('run-evidence-seed-count')).toHaveText('20');
    await expect(runIntro.getByTestId('run-evidence-network-cohort-count')).toHaveText('13');
    await expect(runIntro.getByTestId('run-evidence-ordinary-count')).toHaveText('967');
    await expect(page.getByTestId('network-effect-section')).toContainText(
      `${changedBatches} / ${payload.run.horizon} 个批次`,
    );
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
      `${belowCapacityCount.toLocaleString()} 个 below_delivery_capacity（未获得投放）用户从未曝光`,
    );
    await expect(page.getByTestId('action-status-explanation')).toContainText(
      `${ignoreCount.toLocaleString()} 个 ignore（忽略）用户已曝光但选择不互动`,
    );
    await expect(page.getByTestId('provider-failure-explanation')).toContainText(
      `${providerFailureCount.toLocaleString()} / ${totalExposures.toLocaleString()} 个任务重试耗尽`,
    );
    await expect(page.getByTestId('network-activation-explanation')).toContainText(
      `${positiveCandidateRows.toLocaleString()} 条 candidates（候选）`,
    );
    await expect(page.getByTestId('network-activation-explanation')).toContainText(
      `${positiveSelectedUsers.toLocaleString()} 位 selected users（已选择用户）`,
    );
    await expect(page.getByTestId('network-activation-explanation')).toContainText(
      `${positiveSignalActions.toLocaleString()} 条 actions（动作）`,
    );
    await page.screenshot({
      path: testInfo.outputPath(`formal-ranking-report-${viewport.name}.png`),
      fullPage: true,
    });
  }
});
