import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { expect, test, type Page } from '@playwright/test';

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
  const outputDir = path.join(testInfo.outputDir, 'concurrent-run');
  const command = `
set -euo pipefail
. .venv/bin/activate
python3 - <<'PY'
from pathlib import Path
from llm_abm_sim import ConcurrentMessageExperimentConfig, ConcurrentMessageExperimentRunner
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

    await expect(page.getByTestId('concurrent-message-report')).toBeVisible();
    await expect(page.getByTestId('validation-status')).toContainText('Validation only');
    await expect(page.getByTestId('campaign-funnel-section')).toContainText('Campaign Funnel');
    await expect(page.getByTestId('message-allocation-section')).toContainText('Message Allocation');
    await expect(page.getByTestId('primary-audience-response-section')).toContainText('Primary Audience Response');
    await expect(page.getByTestId('campaign-feedback-effect-section')).toContainText('Campaign Feedback Effect');
    await expect(page.getByTestId('demographic-decision-sensitivity-section')).toContainText('Demographic Decision Sensitivity');
    await expect(page.getByTestId('decision-trace-section')).toContainText('Exposure trace table');
    await expect(page.getByTestId('downloads-section')).toContainText('Safe downloads');

    const traces = payload.exposure_rows;
    const selectedMessage = traces[0].message_id;
    const selectedClass = traces.find((row) => row.message_id === selectedMessage)?.latent_class ?? traces[0].latent_class;
    await page.getByTestId('message-filter').selectOption(selectedMessage);
    const messageFiltered = traces.filter((row) => row.message_id === selectedMessage).length;
    await expect(page.getByTestId('decision-trace-table').locator('tbody tr')).toHaveCount(messageFiltered);
    await page.getByTestId('class-filter').selectOption(selectedClass);
    const classFiltered = traces.filter(
      (row) => row.message_id === selectedMessage && row.latent_class === selectedClass,
    ).length;
    await expect(page.getByTestId('decision-trace-table').locator('tbody tr')).toHaveCount(classFiltered);
    await page.getByTestId('class-filter').selectOption('');
    await page.getByTestId('message-filter').selectOption('');

    const disagreementCount = traces.filter((row) => row.primary_shadow_disagreement).length;
    if (disagreementCount > 0) {
      await page.getByTestId('disagreement-filter').selectOption('true');
      await expect(page.getByTestId('decision-trace-table').locator('tbody tr')).toHaveCount(disagreementCount);
      await page.getByTestId('disagreement-filter').selectOption('');
    }

    await page.getByTestId('decision-trace-table').locator('tbody tr').first().click();
    const drawer = page.getByTestId('trace-drawer');
    await expect(drawer).toBeVisible();
    await expect(drawer).toContainText('Message and ranking evidence');
    await expect(drawer).toContainText('Primary decision');
    await expect(drawer).toContainText('Shadow decision');
    await expect(drawer).toContainText('Field differences');
    await expect(drawer).toContainText('Aggregate evidence');
    await page.getByTestId('trace-drawer').getByRole('button', { name: 'Close trace detail' }).click();
    await expect(drawer).toBeHidden();

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
