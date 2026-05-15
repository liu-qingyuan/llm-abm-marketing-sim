import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { expect, test } from '@playwright/test';

test('generated interactive report renders bilingual product sections and trace controls', async ({ page }, testInfo) => {
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
  expect(existsSync(path.join(outputDir, 'input-builder.html'))).toBeTruthy();

  await page.goto(pathToFileURL(reportPath).toString());
  await expect(page.getByTestId('simulation-report')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'LLM-ABM Simulation Report' })).toBeVisible();
  await expect(page.getByTestId('how-to-read-section')).toContainText('How to Read This Simulation');
  await expect(page.getByTestId('inputs-section')).toContainText('Inputs Used');
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
  const trace = JSON.parse(readFileSync(tracePath, 'utf8'));
  expect(JSON.stringify(trace)).toContain('trace_summary');

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
  await expect(page.getByTestId('node-detail-panel')).toContainText('Agent input');
  await expect(page.getByTestId('node-detail-panel')).toContainText('peer_context');
  await expect(page.getByTestId('node-detail-panel')).toContainText('Agent output');
  await expect(page.getByTestId('node-detail-panel')).toContainText('probability');

  await page.getByTestId('language-toggle').selectOption('zh-CN');
  await expect(page.getByTestId('run-summary')).toContainText('运行摘要');
  await expect(page.getByTestId('metrics-section')).toContainText('最终互动');
  await expect(page.getByTestId('interactive-trace-section')).toContainText('交互式 ABM 轨迹');
  await expect(page.getByTestId('provider-evidence-section')).toContainText('Provider / 决策来源证据');
  await expect(page.getByTestId('node-detail-panel')).toContainText('Agent 输入');
});

test('static input builder exposes bilingual config template', async ({ page }, testInfo) => {
  const outputDir = path.join(testInfo.outputDir, 'builder-run');
  execFileSync('python', [
    '-m',
    'llm_abm_sim.run',
    '--config',
    'configs/default.yaml',
    '--output',
    outputDir,
  ], { stdio: 'inherit' });
  const builderPath = path.join(outputDir, 'input-builder.html');
  await page.goto(pathToFileURL(builderPath).toString());
  await expect(page.getByTestId('input-builder')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'LLM-ABM Input Builder' })).toBeVisible();
  const yaml = await page.getByTestId('generated-config').inputValue();
  expect(yaml).toContain('run_id: builder-sample-run');
  expect(yaml).toContain('provider_llm:');
  expect(yaml).toContain('default_language: en-US');
  expect(yaml).toContain('profiles:');
  await page.getByTestId('builder-language').selectOption('zh-CN');
  await expect(page.getByTestId('input-builder')).toContainText('LLM-ABM 输入构建器');
  await expect(page.getByTestId('input-builder')).toContainText('字段说明');
});


test('report honors zh-CN default language from config', async ({ page }, testInfo) => {
  const outputDir = path.join(testInfo.outputDir, 'zh-default-run');
  const configPath = path.join(testInfo.outputDir, 'zh-default.yaml');
  execFileSync('python', ['-c', `
from pathlib import Path
from llm_abm_sim.runner import load_simulation_input
import yaml
config = load_simulation_input('configs/default.yaml')
config = config.model_copy(update={'report': config.report.model_copy(update={'default_language': 'zh-CN'})})
Path(r'${configPath}').parent.mkdir(parents=True, exist_ok=True)
Path(r'${configPath}').write_text(yaml.safe_dump(config.model_dump(mode='json'), allow_unicode=True, sort_keys=False), encoding='utf-8')
`], { stdio: 'inherit' });
  execFileSync('python', [
    '-m',
    'llm_abm_sim.run',
    '--config',
    configPath,
    '--output',
    outputDir,
  ], { stdio: 'inherit' });

  await page.goto(pathToFileURL(path.join(outputDir, 'report.html')).toString());
  await expect(page.getByTestId('language-toggle')).toHaveValue('zh-CN');
  await expect(page.getByTestId('run-summary')).toContainText('运行摘要');
  await expect(page.getByTestId('inputs-section')).toContainText('本次输入');
  await expect(page.getByTestId('metrics-section')).toContainText('核心指标');
});
