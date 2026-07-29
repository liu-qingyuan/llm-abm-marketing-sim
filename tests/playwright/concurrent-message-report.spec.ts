import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { expect, test, type Page } from '@playwright/test';

const existingConcurrentReportDir = process.env.CONCURRENT_MESSAGE_REPORT_DIR;

type ConcurrentTraceRow = {
  message_id: string;
  latent_class: string;
  primary_action: string;
  primary_shadow_disagreement: boolean;
};

type ConcurrentPayload = {
  schema_version: string;
  downloads: Record<string, string>;
  exposure_rows: ConcurrentTraceRow[];
};

function generateConcurrentReport(testInfo: { outputDir: string }): { outputDir: string; payload: ConcurrentPayload } {
  if (existingConcurrentReportDir) {
    const outputDir = path.resolve(existingConcurrentReportDir);
    const payload = JSON.parse(
      readFileSync(path.join(outputDir, 'concurrent_message_report_payload.json'), 'utf8'),
    ) as ConcurrentPayload;
    return { outputDir, payload };
  }

  const outputDir = path.join(testInfo.outputDir, 'concurrent-run');
  const command = `
set -euo pipefail
. .venv/bin/activate
python3 - <<'PY'
import hashlib
import json
from pathlib import Path
from llm_abm_sim import ConcurrentMessageExperimentConfig, ConcurrentMessageExperimentRunner
from llm_abm_sim.concurrent_message_renderer import _CURRENT_ADAPTER
from llm_abm_sim.concurrent_message_report import ConcurrentMessageReportPayload
from llm_abm_sim.prompt_field_summary import (
    CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
    CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
)
from tests.integration.test_concurrent_message_experiment_runner import (
    _ScriptedConcurrentAdapter,
    _make_concurrent_fixture,
)

root = Path(${JSON.stringify(outputDir)}).resolve()
dataset_dir = _make_concurrent_fixture(root.parent / 'fixture')
config = ConcurrentMessageExperimentConfig(
    dataset_dir=dataset_dir,
    sample_size=30,
    horizon=2,
    delivery_capacity=10,
    configuration_profile='validation',
)
ConcurrentMessageExperimentRunner(
    config,
    _ScriptedConcurrentAdapter(
        name='primary',
        prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        positive_user_ids={'u1'},
        fail_pairs={(0, 'message_3', 'u4')},
    ),
    _ScriptedConcurrentAdapter(
        name='shadow',
        prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
        positive_user_ids={'u2'},
        fail_pairs={(0, 'message_2', 'u3')},
    ),
).run_and_write(root)
payload = ConcurrentMessageReportPayload.model_validate_json(
    (root / 'concurrent_message_report_payload.json').read_bytes()
)
compatibility_html = _CURRENT_ADAPTER.render(payload)
(root / 'report.html').write_text(compatibility_html, encoding='utf-8')
manifest_path = root / 'artifact_manifest.json'
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
manifest['sha256']['report_html'] = hashlib.sha256(compatibility_html.encode('utf-8')).hexdigest()
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True) + '\\n', encoding='utf-8')
PY`;
  execFileSync('bash', ['-lc', command], { stdio: 'inherit' });
  const payload = JSON.parse(
    readFileSync(path.join(outputDir, 'concurrent_message_report_payload.json'), 'utf8'),
  ) as ConcurrentPayload;
  return { outputDir, payload };
}

async function expectNoLayoutFailures(page: Page): Promise<void> {
  const failures = await page.evaluate(() => {
    const visible = (element: HTMLElement) => element.offsetParent !== null;
    const textOverflow = [...document.querySelectorAll<HTMLElement>('button, a, th, td, label, h1, h2, h3')]
      .filter(visible)
      .filter((element) => element.scrollWidth > element.clientWidth + 2 && getComputedStyle(element).overflowX !== 'auto')
      .map((element) => `${element.tagName}:${element.textContent?.trim().slice(0, 40)}`);
    const overlapSelectors = ['.summary-grid > article', '.filters > label', '.split-grid > *'];
    const overlaps: string[] = [];
    for (const selector of overlapSelectors) {
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
  expect(failures).toEqual({
    horizontalOverflow: false,
    textOverflow: [],
    overlaps: [],
  });
}

test('concurrent message report exposes sections, filters, drawer, and safe downloads across desktop and mobile', async ({ page }, testInfo) => {
  const { outputDir, payload } = generateConcurrentReport(testInfo);
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));

  for (const viewport of [
    { width: 1440, height: 1000 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(pathToFileURL(path.join(outputDir, 'report.html')).toString());
    await page.getByTestId('run-evidence-mode-button').click();
    await expect(page.getByTestId('run-evidence-mode-panel')).toBeVisible();

    await expect(page.getByTestId('concurrent-message-report')).toBeVisible();
    await expect(page.getByTestId('validation-status')).toContainText(/Validation only|Persisted Seed-First Formal Run/);
    await expect(page.getByTestId('campaign-funnel-section')).toContainText('Campaign Funnel');
    await expect(page.getByTestId('message-allocation-section')).toContainText('Message Allocation');
    await expect(page.getByTestId('primary-audience-response-section')).toContainText('Primary Audience Response');
    await expect(page.getByTestId('campaign-feedback-effect-section')).toContainText('Campaign Feedback Effect');
    await expect(page.getByTestId('demographic-decision-sensitivity-section')).toContainText('Demographic Decision Sensitivity');
    await expect(page.getByTestId('messages-section')).toContainText('not exposure eligibility');
    await expect(page.getByTestId('messages-section')).toContainText('not a Prompt field');
    await expect(page.getByTestId('decision-trace-section')).toContainText('Exposure trace table');
    await expect(page.getByTestId('downloads-section')).toContainText('Safe downloads');

    const traces = payload.exposure_rows;
    const traceRows = page.getByTestId('decision-trace-table').locator('tbody tr');
    const traceMatchCount = page.getByTestId('trace-match-count');
    const tracePageStatus = page.getByTestId('trace-page-status');
    const tracePageSize = page.getByTestId('trace-page-size');
    const tracePageNumbers = page.getByTestId('trace-page-numbers');
    const nextTracePage = page.getByTestId('trace-next-page');
    const selectedMessage = traces[0].message_id;
    const selectedClass = traces.find((row) => row.message_id === selectedMessage)?.latent_class ?? traces[0].latent_class;
    await expect(tracePageSize).toHaveValue('50');
    await expect(traceMatchCount).toContainText(`${traces.length.toLocaleString()} matching trace row(s)`);
    await expect(traceRows).toHaveCount(Math.min(50, traces.length));
    await expect(tracePageStatus).toContainText(`Page 1 of ${Math.max(1, Math.ceil(traces.length / 50))}`);

    await page.getByTestId('message-filter').selectOption(selectedMessage);
    const messageFiltered = traces.filter((row) => row.message_id === selectedMessage).length;
    await expect(traceMatchCount).toContainText(`${messageFiltered.toLocaleString()} matching trace row(s)`);
    await expect(traceRows).toHaveCount(Math.min(50, messageFiltered));
    await page.getByTestId('class-filter').selectOption(selectedClass);
    const classFiltered = traces.filter(
      (row) => row.message_id === selectedMessage && row.latent_class === selectedClass,
    ).length;
    await expect(traceMatchCount).toContainText(`${classFiltered.toLocaleString()} matching trace row(s)`);
    await expect(traceRows).toHaveCount(Math.min(50, classFiltered));
    await page.getByTestId('class-filter').selectOption('');
    await page.getByTestId('message-filter').selectOption('');

    const disagreementCount = traces.filter((row) => row.primary_shadow_disagreement).length;
    if (disagreementCount > 0) {
      await page.getByTestId('disagreement-filter').selectOption('true');
      await expect(traceMatchCount).toContainText(`${disagreementCount.toLocaleString()} matching trace row(s)`);
      await expect(traceRows).toHaveCount(Math.min(50, disagreementCount));
      await page.getByTestId('disagreement-filter').selectOption('');
    }

    await tracePageSize.selectOption('25');
    await expect(tracePageStatus).toContainText('Page 1 of');
    await expect(traceRows).toHaveCount(Math.min(25, traces.length));
    if (traces.length > 25) {
      await nextTracePage.click();
      await expect(tracePageStatus).toContainText('Page 2 of');
      await expect(traceRows).toHaveCount(Math.min(25, traces.length - 25));
      await tracePageNumbers.getByRole('button', { name: 'Go to trace page 1', exact: true }).click();
      await expect(tracePageStatus).toContainText('Page 1 of');
      await expect(traceRows).toHaveCount(Math.min(25, traces.length));
      await page.getByTestId('message-filter').selectOption(selectedMessage);
      await expect(tracePageStatus).toContainText('Page 1 of');
      await expect(traceRows).toHaveCount(Math.min(25, messageFiltered));
      await page.getByTestId('message-filter').selectOption('');
    }
    await tracePageSize.selectOption('100');
    await expect(tracePageStatus).toContainText('Page 1 of');
    if (traces.length <= 100) await expect(nextTracePage).toBeDisabled();
    else await expect(nextTracePage).toBeEnabled();
    await expect(traceRows).toHaveCount(Math.min(100, traces.length));

    const firstRow = traceRows.first();
    await firstRow.click();
    const drawer = page.getByTestId('trace-drawer');
    await expect(drawer).toBeVisible();
    await expect(drawer).toHaveAttribute('aria-modal', 'true');
    await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe('hidden');
    await expect(drawer).toContainText('Message and ranking evidence');
    await expect(drawer).toContainText('Primary decision');
    await expect(drawer).toContainText('Shadow decision');
    await expect(drawer).toContainText('Field differences');
    await expect(drawer).toContainText('Aggregate evidence');
    await page.getByTestId('trace-drawer').getByRole('button', { name: 'Close trace detail' }).click();
    await expect(drawer).toBeHidden();
    await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe('');
    await expect(firstRow).toBeFocused();

    await firstRow.press('Enter');
    await expect(drawer).toBeVisible();
    await page.getByTestId('trace-drawer').getByRole('button', { name: 'Close trace detail' }).click();
    await expect(firstRow).toBeFocused();
    await firstRow.press('Space');
    await expect(drawer).toBeVisible();
    await page.getByTestId('trace-drawer').getByRole('button', { name: 'Close trace detail' }).click();
    await expect(firstRow).toBeFocused();

    for (const downloadName of ['manifest', 'report_payload', 'users_json', 'decision_trace_json']) {
      const link = page.getByTestId(`download-${downloadName.replaceAll('_', '-')}`);
      await expect(link).toBeVisible();
      await expect(link).toHaveAttribute('href', payload.downloads[downloadName]);
    }

    await expectNoLayoutFailures(page);
  }

  expect(pageErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});

test('mechanism scenes explain the Multi-Message contract with one accessible detail drawer', async ({ page }, testInfo) => {
  const { outputDir } = generateConcurrentReport(testInfo);
  const reportUrl = pathToFileURL(path.join(outputDir, 'report.html')).toString();
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));

  for (const viewport of [
    { width: 1440, height: 1000 },
    { width: 1600, height: 1000 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(reportUrl);
    const mechanism = page.getByTestId('mechanism-mode-panel');
    await expect(mechanism).toBeVisible();
    await expect(mechanism.getByTestId('mechanism-sample-size')).toContainText('1,000');
    await expect(mechanism.getByTestId('mechanism-eligible-pairs')).toContainText('3,000');
    await expect(mechanism.getByTestId('mechanism-batch-contract')).toContainText('30 × Top20');
    await expect(mechanism.getByTestId('mechanism-message-queue-1')).toBeVisible();
    await expect(mechanism.getByTestId('mechanism-message-queue-2')).toBeVisible();
    await expect(mechanism.getByTestId('mechanism-message-queue-3')).toBeVisible();

    for (const text of [
      'Full-Pool Influence Seed Union',
      'network cohort',
      'Synthetic Experiment Labels',
      'three independent queues',
      'same pair at most once',
      'Message-User Fit',
      '[-1,1] → [0,1]',
      '0.50',
      '0.30',
      '0.20',
      'historical_tag_affinity = 0',
      'Platform Environment',
      'Decision Adapter',
      'Ranking evidence、Class 和其他 messages 不进入当前 pair 的 Prompt',
      'Shadow 仅作 report-only',
      'gender',
      'age',
      'education',
      'monthly_income',
      'like / comment / share',
      'provider_failed',
      '同批 context 保持冻结',
      'Recommendation Signal Inclusion',
      'Observed Recommendation Signal Effect',
    ]) {
      await expect(mechanism).toContainText(text);
    }

    const mechanismImages = mechanism.locator('img[data-testid^="multi-message-"]');
    await expect(mechanismImages).toHaveCount(5);
    const imageDimensions = await mechanismImages.evaluateAll((images) => images.map((image) => ({
      naturalWidth: (image as HTMLImageElement).naturalWidth,
      naturalHeight: (image as HTMLImageElement).naturalHeight,
    })));
    expect(imageDimensions).toHaveLength(5);
    imageDimensions.forEach(({ naturalWidth, naturalHeight }) => {
      expect(naturalWidth).toBeGreaterThan(0);
      expect(naturalHeight).toBeGreaterThan(0);
      expect(naturalWidth / naturalHeight).toBeCloseTo(16 / 9, 2);
    });

    for (const excluded of ['current action distribution', 'message winner', 'demographic causality']) {
      await expect(mechanism).not.toContainText(excluded);
    }

    if (viewport.width === 1440 || viewport.width === 390) {
      await expect(page).toHaveScreenshot(`concurrent-message-mechanism-${viewport.width}.png`, {
        animations: 'disabled',
        caret: 'hide',
        fullPage: false,
      });
    }

    const firstHotspot = mechanism.locator('[data-mechanism-key]').first();
    await firstHotspot.focus();
    await expect(firstHotspot).toBeFocused();
    await firstHotspot.press('Enter');
    const drawer = page.getByTestId('trace-drawer');
    await expect(drawer).toBeVisible();
    await expect(drawer).toHaveAttribute('data-selection-kind', 'mechanism');
    await expect(drawer).toHaveAttribute('aria-modal', 'true');
    await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe('hidden');
    await expect(drawer).toContainText('Field Provenance');
    await expect(drawer).toContainText('研究限制');
    await drawer.getByRole('button', { name: 'Close trace detail' }).click();
    await expect(drawer).toBeHidden();
    await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe('');
    await expect(firstHotspot).toBeFocused();

    await expectNoLayoutFailures(page);
  }

  expect(pageErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});

test('current shell keeps mode, anchor hash, focus, and history synchronized', async ({ page }, testInfo) => {
  const { outputDir } = generateConcurrentReport(testInfo);
  const reportUrl = pathToFileURL(path.join(outputDir, 'report.html')).toString();
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));

  for (const viewport of [
    { width: 1440, height: 1000 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(reportUrl);
    await expect(page.getByTestId('final-research-ranking-report')).toHaveCount(0);
    await expect(page.getByTestId('concurrent-message-report')).toHaveAttribute('data-report-mode', 'mechanism');
    await expect(page.getByTestId('mechanism-mode-panel')).toBeVisible();
    await expect(page.getByTestId('run-evidence-mode-panel')).toBeHidden();
    await expect(page.locator('[data-report-mode-panel]:not([hidden])')).toHaveCount(1);
    await expect(page.getByTestId('mechanism-mode-panel')).toContainText('三条 message 同时进入独立 queue');
    await expect(page.getByTestId('mechanism-mode-panel')).toContainText('平台先决定 exposure');
    await expect(page.getByTestId('mechanism-mode-panel')).toContainText('LLM 只处理已经曝光');
    await expect(page.getByTestId('mechanism-mode-panel')).toContainText('Shadow 仅作 report-only');
    await expectNoLayoutFailures(page);
  }

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${reportUrl}#run/sample`);
  await expect(page).toHaveURL(/report\.html#run\/sample$/);
  await expect(page.getByTestId('run-evidence-mode-panel')).toBeVisible();
  await expect(page.getByTestId('mechanism-mode-panel')).toBeHidden();
  await expect(page.getByTestId('run-evidence-mode-panel').locator('[data-section-anchor="sample"]')).toBeFocused();

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(reportUrl);
  const mechanismTab = page.getByTestId('mechanism-mode-button');
  const runTab = page.getByTestId('run-evidence-mode-button');
  await mechanismTab.focus();
  await expect(mechanismTab).toBeFocused();
  expect(await mechanismTab.evaluate((node) => node.matches(':focus-visible'))).toBe(true);
  await mechanismTab.press('Enter');
  await expect(page.getByTestId('mechanism-mode-panel')).toBeVisible();
  await mechanismTab.press('ArrowRight');
  await expect(runTab).toBeFocused();
  await expect(runTab).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByTestId('concurrent-message-report')).toHaveAttribute('data-report-mode', 'run-evidence');
  await expect(page).toHaveURL(/report\.html#run\/overview$/);
  await expect(page.locator('[data-report-mode-panel]:not([hidden])')).toHaveCount(1);
  await runTab.press('Space');
  await expect(runTab).toBeFocused();
  await runTab.press('ArrowLeft');
  await expect(mechanismTab).toBeFocused();
  await expect(mechanismTab).toHaveAttribute('aria-selected', 'true');
  await mechanismTab.press('ArrowRight');
  await expect(runTab).toBeFocused();
  await page.goto(reportUrl);
  await page.getByTestId('run-evidence-mode-button').click();

  await page.getByRole('link', { name: '曝光排序' }).click();
  await expect(page).toHaveURL(/report\.html#run\/exposure-ranking$/);
  await expect(page.getByTestId('run-evidence-mode-panel').locator('[data-section-anchor="exposure-ranking"]')).toBeFocused();
  await expect(page.getByRole('link', { name: '曝光排序' })).toHaveAttribute('aria-current', 'location');
  await page.goBack();
  await expect(page).toHaveURL(/report\.html#run\/overview$/);
  await expect(runTab).toHaveAttribute('aria-selected', 'true');
  await page.goBack();
  await expect(page).toHaveURL(/report\.html(?:#overview)?$/);
  await expect(page.getByTestId('mechanism-mode-panel')).toBeVisible();
  await expect(page.getByTestId('run-evidence-mode-panel')).toBeHidden();

  await page.evaluate(() => {
    window.location.hash = '#run/llm-decision';
  });
  await expect(page).toHaveURL(/report\.html#run\/llm-decision$/);
  await expect(page.getByTestId('run-evidence-mode-panel')).toBeVisible();
  await expect(page.getByTestId('run-evidence-mode-panel').locator('[data-section-anchor="llm-decision"]')).toBeFocused();
  await page.evaluate(() => {
    window.location.hash = '#sample';
  });
  await expect(page).toHaveURL(/report\.html#sample$/);
  await expect(page.getByTestId('mechanism-mode-panel')).toBeVisible();
  await expect(page.getByTestId('mechanism-mode-panel').locator('[data-section-anchor="sample"]')).toBeFocused();

  expect(pageErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
