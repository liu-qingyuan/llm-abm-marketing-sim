import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { expect, test, type Page, type TestInfo } from '@playwright/test';

type ReportUser = {
  user_id: string;
  exposure_status: string;
  result_status: string;
  sample_source_scope: string;
  is_seed: boolean;
};

function generateReport(testInfo: TestInfo): { outputDir: string; users: ReportUser[] } {
  const fixtureDir = path.join(testInfo.outputDir, 'processed-fixture');
  const outputDir = path.join(testInfo.outputDir, 'final-report');
  const testModule = path.resolve('tests/integration/test_final_research_runner.py');
  execFileSync(path.resolve('.venv/bin/python'), ['-c', `
import importlib.util
import sys
from pathlib import Path

from llm_abm_sim import FinalResearchConfig, FinalResearchModel, FinalResearchRunner
from llm_abm_sim.providers.openai_compatible import OpenAICompatibleDecisionAdapter
from llm_abm_sim.schemas import ProviderLLMConfig

test_module, fixture_path, output_path = sys.argv[1:]
spec = importlib.util.spec_from_file_location("final_research_test_support", test_module)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
fixture_dir = module._make_processed_fixture(Path(fixture_path), user_count=80, dense_target_network=True)
provider_config = ProviderLLMConfig(
    enabled=True,
    model="mock-model",
    require_live_env=False,
    max_retries=5,
    retry_backoff_seconds=0.0,
)
client = module._ScriptedProviderClient()
provider = OpenAICompatibleDecisionAdapter(provider_config, client=client, sleep=lambda _delay: None)
adapter = module._RecordingAdapter(provider)
config = FinalResearchConfig(
    dataset_dir=fixture_dir,
    research_model=FinalResearchModel.PROBABILITY_V1,
    sample_size=70,
    random_seed=20260713,
    provider=provider_config,
)
FinalResearchRunner(config, adapter).run_and_write(Path(output_path))
`, testModule, fixtureDir, outputDir], { stdio: 'inherit' });
  const userDocument = JSON.parse(readFileSync(path.join(outputDir, 'final_research_users.json'), 'utf8'));
  return { outputDir, users: userDocument.users };
}

async function assertReport(page: Page, outputDir: string, users: ReportUser[]): Promise<void> {
  await page.goto(pathToFileURL(path.join(outputDir, 'report.html')).toString());
  await expect(page.getByTestId('final-research-report')).toBeVisible();
  await expect(page.getByTestId('target-video-section')).toContainText('当高端酒店开始限塑');
  await expect(page.getByTestId('core-objects-section')).toContainText('TargetVideo');
  await expect(page.getByTestId('core-objects-section')).toContainText('ResearchUser');
  await expect(page.getByTestId('core-objects-section')).toContainText('PlatformRecommendationModel');
  await expect(page.getByTestId('workflow-nav')).toContainText('运行漏斗');
  await page.getByRole('link', { name: '推荐与抽签' }).click();
  await expect(page).toHaveURL(/#recommendation$/);
  await expect(page.getByTestId('funnel-section').locator('article')).toHaveCount(7);
  await expect(page.getByTestId('funnel-section')).toContainText('Offline scoring');
  await expect(page.getByTestId('funnel-section')).toContainText('Background Content');
  await expect(page.getByTestId('methodology-section')).toContainText('唯一进入固定批次');
  await expect(page.getByTestId('methodology-section')).toContainText('不声称对背景视频完成了 runtime 排序');
  await expect(page.getByTestId('recommendation-section')).toContainText('dynamic_network_score');
  await expect(page.getByTestId('seed-example')).toContainText('强制曝光');
  await expect(page.getByTestId('non-seed-example')).toContainText('random_draw');
  await expect(page.getByTestId('decision-section')).toContainText('30 个批次');
  const seedExposureCount = users.filter((user) => user.is_seed && user.exposure_status === 'target_exposed').length;
  const nonSeedExposureCount = users.filter((user) => !user.is_seed && user.exposure_status === 'target_exposed').length;
  await expect(page.getByTestId('exposure-breakdown')).toHaveText(
    `${seedExposureCount + nonSeedExposureCount} 次 Provider Decision 调用来自 ${seedExposureCount} 个强制 seed 曝光和 ${nonSeedExposureCount} 个普通用户抽签曝光。`,
  );
  await expect(page.getByTestId('decision-section')).toContainText('完整原始 PeerContext 与 Provider Prompt 不可恢复');
  await expect(page.getByTestId('outcome-explanations').locator('article')).toHaveCount(5);

  for (const testId of ['trend-chart', 'action-chart', 'scope-chart', 'provider-chart', 'neighbor-chart']) {
    const chart = page.getByTestId(testId);
    await expect(chart).toBeVisible();
    expect((await chart.boundingBox())?.height ?? 0).toBeGreaterThan(100);
  }

  const selected = users.find((user) => user.result_status === 'provider_failed') ?? users[0];
  await page.getByTestId('user-search').fill(selected.user_id);
  await expect(page.getByTestId('user-table').locator('tbody tr')).toHaveCount(1);
  await expect(page.getByTestId('user-table')).toContainText(selected.user_id);
  await page.getByTestId('user-table').locator('tbody tr').click();
  await expect(page.getByTestId('user-detail')).toContainText(selected.user_id);
  await expect(page.getByTestId('trace-context')).toContainText('重建的决策上下文');
  await expect(page.getByTestId('trace-context')).toContainText('完整原始 Provider Prompt 无法');
  await expect(page.getByTestId('trace-evidence')).toContainText('action');
  await expect(page.getByTestId('trace-evidence')).toContainText('engage');
  await expect(page.getByTestId('trace-evidence')).toContainText('decision_source');

  await page.getByTestId('user-search').fill('');
  await page.getByTestId('result-filter').selectOption(selected.result_status);
  const expectedResultCount = users.filter((user) => user.result_status === selected.result_status).length;
  await expect(page.getByTestId('user-table').locator('tbody tr')).toHaveCount(expectedResultCount);
  await page.getByTestId('result-filter').selectOption('');
  await page.getByTestId('scope-filter').selectOption(selected.sample_source_scope);
  const expectedScopeCount = users.filter((user) => user.sample_source_scope === selected.sample_source_scope).length;
  await expect(page.getByTestId('user-table').locator('tbody tr')).toHaveCount(expectedScopeCount);
  await page.getByTestId('scope-filter').selectOption('');
  await page.getByTestId('seed-filter').selectOption('true');
  await expect(page.getByTestId('user-table').locator('tbody tr')).toHaveCount(
    users.filter((user) => user.is_seed).length,
  );

  for (const fileName of ['report.html', 'final_research_report_payload.json', 'final_research_users.csv', 'final_research_users.json', 'artifact_manifest.json']) {
    expect(existsSync(path.join(outputDir, fileName))).toBeTruthy();
  }
  const bodyHasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  );
  expect(bodyHasHorizontalOverflow).toBeFalsy();
  const overlappingSiblingGroups = await page.evaluate(() => {
    const groups = [
      '.topbar > *',
      '.downloads > a',
      '.target-facts > div',
      '.funnel-grid > article',
      '.method-grid > article',
      '.evidence-grid > article',
      '.formula-stack > article',
      '.example-grid > article',
      '.outcome-list > article',
      '.metrics-band > article',
      '.diagnostic-grid > article',
      '.chart-grid > article',
      '.filters > label',
    ];
    const overlaps: string[] = [];
    for (const selector of groups) {
      const elements = [...document.querySelectorAll<HTMLElement>(selector)].filter(
        (element) => element.offsetParent !== null,
      );
      for (let leftIndex = 0; leftIndex < elements.length; leftIndex += 1) {
        for (let rightIndex = leftIndex + 1; rightIndex < elements.length; rightIndex += 1) {
          const left = elements[leftIndex].getBoundingClientRect();
          const right = elements[rightIndex].getBoundingClientRect();
          const intersects =
            Math.min(left.right, right.right) - Math.max(left.left, right.left) > 1 &&
            Math.min(left.bottom, right.bottom) - Math.max(left.top, right.top) > 1;
          if (intersects) overlaps.push(`${selector}:${leftIndex}-${rightIndex}`);
        }
      }
    }
    return overlaps;
  });
  expect(overlappingSiblingGroups).toEqual([]);
}

test('final research report is complete and interactive on desktop', async ({ page }, testInfo) => {
  const { outputDir, users } = generateReport(testInfo);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await assertReport(page, outputDir, users);
  await page.screenshot({ path: testInfo.outputPath('final-research-desktop.png'), fullPage: true });
});

test('final research report remains usable on mobile', async ({ page }, testInfo) => {
  const { outputDir, users } = generateReport(testInfo);
  await page.setViewportSize({ width: 390, height: 844 });
  await assertReport(page, outputDir, users);
  await page.screenshot({ path: testInfo.outputPath('final-research-mobile.png'), fullPage: true });
});
