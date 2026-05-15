import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { expect, test } from '@playwright/test';

test('generated interactive report renders static sections and trace controls', async ({ page }, testInfo) => {
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

  const tracePath = path.join(outputDir, 'graph_trace.json');
  expect(existsSync(tracePath)).toBeTruthy();
  await expect(page.getByTestId('interactive-trace-section')).toBeVisible();
  await expect(page.getByTestId('abm-graph')).toBeVisible();
  await expect(page.locator('#abm-graph canvas')).toHaveCount(3);
  await expect(page.getByTestId('selected-step-label')).toHaveText('Step 0');
  await page.getByTestId('step-slider').evaluate((element: HTMLInputElement) => {
    element.value = '1';
    element.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await expect(page.getByTestId('selected-step-label')).toHaveText('Step 1');
  await expect(page.getByTestId('event-stream-panel')).toContainText('Event Stream — Step 1');
  await expect(page.getByTestId('decision-trace-panel')).toContainText('Decision Trace — Step 1');
  await page.locator('button[data-node-id="u2"]').click();
  await expect(page.getByTestId('node-detail-panel')).toContainText('Node Detail: u2');
  await expect(page.getByTestId('node-detail-panel')).toContainText('Current decision');
  await expect(page.getByTestId('node-detail-panel')).toContainText('probability=');
});
