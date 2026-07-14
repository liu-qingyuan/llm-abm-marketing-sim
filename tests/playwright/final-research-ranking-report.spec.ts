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

type RankingPayload = {
  users: RankingUser[];
  target_video: {
    video_url: string;
  };
  sample_comparison: {
    seed_count: number;
    network_cohort_count: number;
    replacement_count: number;
  };
  downloads: Record<string, string>;
};

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
  await expect(hero).toContainText('当高端酒店开始限塑');
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
  await expect(sampleSection).toContainText(`Seeds ${payload.sample_comparison.seed_count}`);
  await expect(sampleSection).toContainText(`Network Cohort ${payload.sample_comparison.network_cohort_count}`);
  await expect(sampleSection).toContainText(`普通用户替换 ${payload.sample_comparison.replacement_count}`);
  await expect(sampleSection).toContainText('Base Sample');
  await expect(sampleSection).toContainText('Network-Augmented Research Sample');

  await expect(page.getByTestId('field-lineage-section')).toContainText('Field Lineage Matrix');
  await page.getByTestId('lineage-stage-filter').selectOption('LLM Prompt');
  await expect(page.getByTestId('lineage-table').locator('tbody tr')).not.toHaveCount(0);
  await expect(page.getByTestId('lineage-table')).toContainText('LLM Prompt');

  const rankingSection = page.getByTestId('ranking-rounds-section');
  await expect(rankingSection).toContainText('0.50');
  await expect(rankingSection).toContainText('0.30');
  await expect(rankingSection).toContainText('0.20');
  await expect(rankingSection).toContainText('Delivery Capacity 20');
  await page.getByTestId('ranking-round-select').selectOption('1');
  await expect(page.getByTestId('round-summary')).toContainText('Eligible');
  await expect(page.getByTestId('round-summary')).toContainText(/Selected\s*20/);
  await expect(page.getByTestId('ranking-candidate-table').locator('tbody tr')).toHaveCount(20);
  await expect(page.getByTestId('ranking-candidate-table')).toContainText('Base network');
  await expect(page.getByTestId('ranking-candidate-table')).toContainText('Engaged neighbor');
  await expect(page.getByTestId('ranking-candidate-table')).toContainText('Tag affinity');

  const networkSection = page.getByTestId('network-effect-section');
  await expect(networkSection).toContainText('Recommendation Signal Inclusion');
  await expect(networkSection).toContainText('Observed Recommendation Signal Effect');
  const ablationSection = page.getByTestId('paired-ablation-section');
  await expect(ablationSection).toContainText('shadow diagnostic');
  await page.getByTestId('ablation-round-select').selectOption('1');
  await expect(page.getByTestId('ablation-summary')).toContainText('Top20 overlap');
  await expect(page.getByTestId('ablation-summary')).toContainText('network-added');
  await expect(page.getByTestId('ablation-summary')).toContainText('network-removed');
  await expect(page.getByTestId('ablation-rank-deltas')).toContainText(/rank delta/i);
  await expect(page.getByTestId('sensitivity-section').locator('[data-variant-id]')).toHaveCount(3);
  await expect(page.getByTestId('sensitivity-section')).not.toContainText('parameter optimization');
  await expect(page.getByTestId('sensitivity-section')).not.toContainText('production accuracy');

  const promptSection = page.getByTestId('prompt-contract-section');
  await expect(promptSection).toContainText('允许字段');
  await expect(promptSection).toContainText('空缺 / 中性字段');
  await expect(promptSection).toContainText('排除字段');
  await expect(promptSection).toContainText('recommendation_score');
  await expect(promptSection).toContainText('Target Holdout answers');

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
