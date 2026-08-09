import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { expect, test } from '@playwright/test';

function generateRobustnessCandidate(outputDir: string): string {
  const root = path.join(outputDir, 'robustness-fixture');
  const command = `
set -euo pipefail
. .venv/bin/activate
python - <<'PY'
from pathlib import Path
from llm_abm_sim import ConcurrentRobustnessStudy
from tests.integration.test_concurrent_message_experiment_runner import (
    _install_deterministic_robustness_cell_fixture,
    _make_validation_report_source,
    _robustness_manifest_for_source,
)

root = Path(${JSON.stringify(root)}).resolve()
root.mkdir(parents=True, exist_ok=True)
formal = _make_validation_report_source(root, 'formal-source')
manifest = _robustness_manifest_for_source(formal, output_identity='browser-report-fixture-v1')
workspace = root / 'workspace'
candidate = root / 'candidate'
study = ConcurrentRobustnessStudy()
study.run(manifest, None, workspace)
_install_deterministic_robustness_cell_fixture(workspace, manifest)
study.run(manifest, None, workspace)
study.run(manifest, None, workspace, report_destination=candidate)
PY`;
  execFileSync('bash', ['-lc', command], { stdio: 'inherit' });
  return path.join(root, 'candidate');
}

test('combined robustness candidate keeps both lineages, bounded visible series, and responsive keyboard controls', async ({ page }, testInfo) => {
  const candidateDir = generateRobustnessCandidate(testInfo.outputDir);
  const reportUrl = pathToFileURL(path.join(candidateDir, 'report.html')).toString();
  const externalRequests: string[] = [];
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  page.on('request', (request) => {
    const protocol = new URL(request.url()).protocol;
    if (protocol !== 'file:' && protocol !== 'data:') externalRequests.push(request.url());
  });
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'reduce' });

  for (const viewport of [
    { width: 1440, height: 1000 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(reportUrl);

    await expect(page.getByTestId('mechanism-overview-section')).toBeVisible();
    await expect(page.getByTestId('run-evidence-mode-panel')).toBeHidden();
    await expect(page.getByTestId('run-trace-lineage-data')).toHaveCount(1);
    await expect(page.getByTestId('mechanism-primary-boundary')).toBeVisible();
    await expect(page.getByTestId('mechanism-shadow-boundary')).toBeVisible();

    const robustness = page.getByTestId('robustness-report-candidate');
    await robustness.scrollIntoViewIfNeeded();
    await expect(robustness).toBeVisible();
    await expect(page.getByTestId('robustness-source-lineage')).toContainText('Historical Concurrent Formal source');
    await expect(page.getByTestId('robustness-source-lineage')).toContainText('Immutable complete study root');
    await expect(page.getByTestId('robustness-shadow-source-label')).toContainText('not a factorial Prompt–Model result');
    await expect(page.getByTestId('robustness-production-eligibility')).toHaveText('production_deploy_eligible=false');

    const visibleWeightFamilies = page.locator('.robustness-weight-family:visible');
    await expect(visibleWeightFamilies).toHaveCount(3);
    for (let index = 0; index < 3; index += 1) {
      const family = visibleWeightFamilies.nth(index);
      await expect(family.locator('svg .robustness-series > g:visible')).toHaveCount(6);
      await expect(family.locator('.robustness-legend-item:visible')).toHaveCount(6);
    }
    const encodingCount = await visibleWeightFamilies.first().locator('svg .robustness-series > g').evaluateAll((groups) =>
      new Set(groups.map((group) => {
        const line = group.querySelector('polyline');
        const marker = group.querySelector('circle, rect, polygon, path');
        return `${line?.getAttribute('stroke')}|${line?.getAttribute('stroke-dasharray') ?? 'solid'}|${marker?.tagName}`;
      })).size,
    );
    expect(encodingCount).toBe(6);

    const visibleMappingFailures = await page.locator('.robustness-chart-shell:visible').evaluateAll((shells) =>
      shells.flatMap((shell) => [...shell.querySelectorAll<HTMLElement>('[data-legend-series-id]')]
        .filter((legend) => {
          const id = legend.dataset.legendSeriesId;
          const series = [...shell.querySelectorAll<SVGGElement>('svg g[data-series-id]')]
            .find((group) => group.dataset.seriesId === id);
          return !series || getComputedStyle(series).display === 'none';
        })
        .map((legend) => legend.dataset.legendSeriesId ?? 'missing')),
    );
    expect(visibleMappingFailures).toEqual([]);

    const familySelect = page.getByTestId('ranking-weight-family-select');
    await familySelect.focus();
    await familySelect.selectOption('network-fit');
    await expect(familySelect).toHaveValue('network-fit');
    await expect(page.locator('[data-weight-family="network-fit"]:visible')).toHaveCount(3);
    await expect(page.locator('[data-weight-family="network-feedback"]:visible')).toHaveCount(0);

    const promptViews = page.locator('[data-prompt-view]:visible');
    await expect(promptViews).toHaveCount(1);
    await expect(promptViews.locator('.robustness-model-panel')).toHaveCount(4);
    for (let index = 0; index < 4; index += 1) {
      const panel = promptViews.locator('.robustness-model-panel').nth(index);
      await expect(panel.locator('svg .robustness-series > g:visible')).toHaveCount(4);
      await expect(panel.locator('.robustness-legend-item:visible')).toHaveCount(4);
    }

    const messageSelect = page.getByTestId('prompt-model-message-select');
    const metricSelect = page.getByTestId('prompt-model-metric-select');
    await messageSelect.selectOption('message_2');
    await metricSelect.selectOption('audience');
    await expect(page.locator('[data-prompt-view="message_2|audience"]')).toBeVisible();
    await expect(page.getByTestId('shared-seed-exact-table').locator('tbody tr:visible')).toHaveCount(16);
    await expect(page.getByTestId('shared-seed-exact-table').locator('tbody tr:visible').first()).toHaveAttribute(
      'data-row-message-id',
      'message_2',
    );

    const growthPanels = page.getByTestId('prompt-model-growth-panels').locator('.robustness-model-panel');
    await expect(growthPanels).toHaveCount(4);
    for (let index = 0; index < 4; index += 1) {
      await expect(growthPanels.nth(index).locator('svg .robustness-series > g:visible')).toHaveCount(4);
    }
    await expect(page.getByTestId('practical-threshold-summary')).toContainText('small_observed_difference');

    const rankingDisclosure = page.getByTestId('ranking-weight-exact-table');
    await rankingDisclosure.locator('summary').focus();
    await rankingDisclosure.locator('summary').press('Enter');
    await expect(page.getByTestId('ranking-weight-message-table')).toBeVisible();
    await expect(page.getByTestId('ranking-weight-message-table').locator('tbody tr')).toHaveCount(57);
    const rankDisclosure = page.getByTestId('ranking-weight-rank-exact-table');
    await rankDisclosure.locator('summary').press('Enter');
    await expect(page.getByTestId('ranking-weight-batch-table')).toBeVisible();
    await expect(page.getByTestId('ranking-weight-batch-table').locator('tbody tr')).toHaveCount(114);

    const downloadLinks = page.getByTestId('robustness-downloads-section').getByRole('link');
    expect(await downloadLinks.count()).toBeGreaterThan(10);
    const hrefs = await downloadLinks.evaluateAll((links) => links.map((link) => link.getAttribute('href') ?? ''));
    expect(hrefs.every((href) => href.length > 0 && !href.startsWith('/') && !href.includes('..'))).toBe(true);
    expect(hrefs.every((href) => existsSync(path.join(candidateDir, href)))).toBe(true);

    const geometry = await page.evaluate(() => {
      const section = document.querySelector<HTMLElement>('[data-testid="robustness-report-candidate"]');
      const visibleCharts = [...document.querySelectorAll<HTMLElement>('.robustness-chart-shell')]
        .filter((chart) => chart.offsetParent !== null);
      return {
        horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
        sectionWidth: section?.getBoundingClientRect().width ?? 0,
        overflowingCharts: visibleCharts.filter((chart) => chart.scrollWidth > chart.clientWidth + 2).length,
      };
    });
    expect(geometry.horizontalOverflow).toBe(false);
    expect(geometry.sectionWidth).toBeLessThanOrEqual(viewport.width + 1);
    expect(geometry.overflowingCharts).toBe(0);
  }

  expect(externalRequests).toEqual([]);
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});
