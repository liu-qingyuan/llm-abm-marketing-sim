import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { expect, test } from '@playwright/test';

test('generated static report renders enriched static sections', async ({ page }, testInfo) => {
  const outputDir = path.join(testInfo.outputDir, 'sample-run');
  execFileSync('python', [
    '-m',
    'llm_abm_sim.run',
    '--config',
    'configs/default.yaml',
    '--output',
    outputDir,
  ], { stdio: 'inherit' });

  const reportPath = path.join(outputDir, 'report.html');
  expect(existsSync(reportPath)).toBeTruthy();

  await page.goto(pathToFileURL(reportPath).toString());
  await expect(page.getByTestId('simulation-report')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'LLM-ABM Simulation Report' })).toBeVisible();
  await expect(page.getByTestId('run-id')).toHaveText('sample-run');
  await expect(page.getByTestId('metrics-section')).toContainText('Final Engaged');
  await expect(page.getByTestId('metric-card-final_engaged')).toBeVisible();
  await expect(page.getByTestId('trend-section')).toContainText('Exposure / Engagement Trend');
  await expect(page.getByTestId('trend-chart')).toBeVisible();
  await expect(page.getByTestId('dataset-validation-section')).toContainText('Inline config dataset');
  await expect(page.getByTestId('seed-users-section')).toContainText('u1');
  await expect(page.getByTestId('provider-evidence-section')).toContainText('Decision sources');
});
