import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';

function generateEditorialCandidate(outputDir: string): string {
  const reportPath = path.join(outputDir, 'report.html');
  const command = `
set -euo pipefail
. .venv/bin/activate
python - <<'PY'
import gzip
from pathlib import Path
from llm_abm_sim.concurrent_message_editorial_candidate import _render_editorial_candidate
from llm_abm_sim.concurrent_message_report import ConcurrentMessageReportPayload

fixture = Path('tests/fixtures/concurrent_message_renderer/formal_report_payload.json.gz')
output = Path(${JSON.stringify(reportPath)})
with gzip.open(fixture, 'rb') as stream:
    payload = ConcurrentMessageReportPayload.model_validate_json(stream.read())
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(_render_editorial_candidate(payload), encoding='utf-8')
PY`;
  execFileSync('bash', ['-lc', command], { stdio: 'inherit' });
  return reportPath;
}

async function expectEditorialGeometry(page: Page): Promise<void> {
  const result = await page.evaluate(() => {
    const visible = (element: HTMLElement) => element.offsetParent !== null;
    const textOverflow = [...document.querySelectorAll<HTMLElement>('button, a, h1, h2, h3, h4, dt, dd')]
      .filter(visible)
      .filter((element) => element.scrollWidth > element.clientWidth + 2)
      .map((element) => `${element.tagName}:${element.textContent?.trim().slice(0, 48)}`);
    const header = document.querySelector<HTMLElement>('.editorial-header');
    const target = document.querySelector<HTMLElement>('[data-report-mode-panel="mechanism"] [data-section-anchor="overview"]');
    return {
      horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
      textOverflow,
      headerHeight: header?.getBoundingClientRect().height ?? 0,
      targetTop: target?.getBoundingClientRect().top ?? 0,
    };
  });
  expect(result.horizontalOverflow).toBe(false);
  expect(result.textOverflow).toEqual([]);
  expect(result.targetTop).toBeGreaterThanOrEqual(result.headerHeight);
}

test('Editorial candidate keeps the mechanism contract visible at desktop and narrow widths', async ({ page }, testInfo) => {
  const reportPath = generateEditorialCandidate(testInfo.outputDir);
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

  for (const viewport of [
    { width: 1440, height: 1000 },
    { width: 1600, height: 1000 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(pathToFileURL(reportPath).toString());

    await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
    await expect(page.getByTestId('editorial-report')).toHaveAttribute('data-report-mode', 'mechanism');
    await expect(page.getByTestId('mechanism-mode-panel')).toBeVisible();
    await expect(page.getByTestId('run-evidence-mode-panel')).toBeHidden();
    await expect(page.locator('[data-report-anchor]')).toHaveCount(5);
    await expect(page.getByTestId('mechanism-sample-size')).toContainText('1,000');
    await expect(page.getByTestId('mechanism-eligible-pairs')).toContainText('3,000');
    await expect(page.getByTestId('mechanism-batch-contract')).toContainText('30 × Top20');
    await expect(page.locator('img[data-asset-file$="-v1.webp"]')).toHaveCount(5);

    const imageDimensions = await page.locator('img[data-asset-file$="-v1.webp"]').evaluateAll((images) =>
      images.map((image) => ({
        naturalWidth: (image as HTMLImageElement).naturalWidth,
        naturalHeight: (image as HTMLImageElement).naturalHeight,
      })),
    );
    expect(imageDimensions).toHaveLength(5);
    imageDimensions.forEach(({ naturalWidth, naturalHeight }) => {
      expect(naturalWidth).toBeGreaterThan(0);
      expect(naturalHeight).toBeGreaterThan(0);
      expect(naturalWidth / naturalHeight).toBeCloseTo(1.5, 2);
    });

    await expectEditorialGeometry(page);
  }

  expect(externalRequests).toEqual([]);
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test('Editorial candidate closes the hash, history, focus, mode, language, and drawer contracts', async ({ page }, testInfo) => {
  const reportPath = generateEditorialCandidate(testInfo.outputDir);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(pathToFileURL(reportPath).toString());

  await page.getByRole('link', { name: '样本', exact: true }).click();
  await expect(page).toHaveURL(/#sample$/);
  await expect(page.locator('[data-report-anchor="sample"]')).toHaveAttribute('aria-current', 'location');
  await expect(page.getByTestId('mechanism-sample-section')).toBeFocused();

  await page.getByTestId('run-evidence-mode-button').click();
  await expect(page).toHaveURL(/#run\/sample$/);
  await expect(page.getByTestId('run-evidence-mode-panel')).toBeVisible();
  await expect(page.getByTestId('mechanism-mode-panel')).toBeHidden();
  await page.goBack();
  await expect(page).toHaveURL(/#sample$/);
  await expect(page.getByTestId('mechanism-mode-panel')).toBeVisible();
  await expect(page.getByTestId('mechanism-sample-section')).toBeFocused();

  const hotspot = page.getByTestId('mechanism-sample-hotspot-network');
  await hotspot.focus();
  await hotspot.press('Enter');
  const drawer = page.getByTestId('evidence-drawer');
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText('Direct one-hop Network Cohort');
  await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe('hidden');
  const hashBeforeLanguage = await page.evaluate(() => window.location.hash);
  await page.getByRole('button', { name: 'English', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-US');
  await expect(page).toHaveURL(new RegExp(`${hashBeforeLanguage}$`));
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText('Direct one-hop Network Cohort');
  await expect(page.getByTestId('mechanism-sample-hotspot-network')).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('[data-report-anchor="sample"]')).toHaveAttribute('aria-current', 'location');

  await page.getByTestId('editorial-drawer-close').click();
  await expect(drawer).toBeHidden();
  await expect(page.getByTestId('mechanism-sample-hotspot-network')).toBeFocused();
  await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe('');

  await page.getByRole('button', { name: '中文', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
  await expect(page).toHaveURL(/#sample$/);
  await expect(page.getByTestId('mechanism-mode-panel')).toBeVisible();
});


test('Editorial run evidence recomputes summaries and paginates persisted batches', async ({ page }, testInfo) => {
  const reportPath = generateEditorialCandidate(testInfo.outputDir);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(pathToFileURL(reportPath).toString());

  await page.getByTestId('run-evidence-mode-button').click();
  await expect(page).toHaveURL(/#run\/overview$/);
  await expect(page.getByTestId('run-evidence-mode-panel')).toBeVisible();
  await expect(page.getByTestId('run-formal-status')).toContainText('Formal');
  await expect(page.getByTestId('run-sample-users')).toContainText('1,000');
  await expect(page.getByTestId('run-eligible-pairs')).toContainText('3,000');
  await expect(page.getByTestId('run-actual-exposures')).toContainText('1,800');
  await expect(page.getByTestId('run-coverage-sequence')).toHaveText('0/434/332/234');

  await page.getByRole('link', { name: '样本', exact: true }).click();
  await expect(page).toHaveURL(/#run\/sample$/);
  await expect(page.getByTestId('run-sample-roles')).toContainText('20');
  await expect(page.getByTestId('run-sample-roles')).toContainText('60');
  await expect(page.getByTestId('run-sample-roles')).toContainText('920');
  await expect(page.getByTestId('run-sample-classes')).toContainText('422');
  await expect(page.getByTestId('run-sample-classes')).toContainText('417');
  await expect(page.getByTestId('run-sample-classes')).toContainText('161');
  await expect(page.getByTestId('run-authoritative-message-message_1')).toContainText('每次在旅途中下榻酒店');

  await page.getByRole('link', { name: '曝光排序', exact: true }).click();
  await expect(page).toHaveURL(/#run\/exposure-ranking$/);
  await expect(page.getByTestId('run-exposure-summary-message_1')).toContainText('600');
  await expect(page.getByTestId('run-exposure-union')).toContainText('1,000');
  await expect(page.getByTestId('run-exposure-three-way')).toContainText('234');
  await expect(page.getByTestId('run-fit-range-message_1')).toContainText('.588');
  await expect(page.getByTestId('run-fit-range-message_1')).toContainText('.761');
  await expect(page.getByTestId('run-fit-range-message_1')).toContainText('.833');

  const rows = page.getByTestId('run-exposure-table-body').locator('tr');
  await expect(rows).toHaveCount(10);
  await expect(page.getByTestId('run-exposure-page-status')).toContainText('1 / 9');
  await page.locator('[data-run-exposure-page="next"]').click();
  await expect(rows.first()).toHaveAttribute('data-time-step', '10');
  await page.getByTestId('run-exposure-message-select').selectOption('message_2');
  await expect(rows).toHaveCount(10);
  await expect(rows.first()).toHaveAttribute('data-message-id', 'message_2');
  await expect(page.getByTestId('run-exposure-page-status')).toContainText('1 / 3');
  await page.locator('[data-run-exposure-page="next"]').click();
  await expect(rows.first()).toHaveAttribute('data-time-step', '10');
  await page.locator('[data-run-exposure-page="next"]').click();
  await expect(rows.last()).toHaveAttribute('data-time-step', '29');

  await page.getByRole('button', { name: 'English', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-US');
  await expect(page.getByTestId('run-exposure-message-select')).toHaveAttribute('aria-label', 'Filter batches by message');
  await expect(page.getByTestId('run-exposure-table')).toHaveAttribute('aria-label', 'Persisted exposure batch table');
  await expect(page.getByTestId('run-authoritative-message-message_1')).toContainText('每次在旅途中下榻酒店');

  for (const viewport of [{ width: 1600, height: 1000 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await page.evaluate(() => window.dispatchEvent(new Event('hashchange')));
    const geometry = await page.evaluate(() => {
      const header = document.querySelector<HTMLElement>('.editorial-header');
      const target = document.querySelector<HTMLElement>('[data-report-mode-panel="run-evidence"] [data-section-anchor="exposure-ranking"]');
      return {
        horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
        tableVisible: document.querySelector('[data-testid="run-exposure-table"]')?.getBoundingClientRect().width || 0,
        targetTop: target?.getBoundingClientRect().top || 0,
        headerBottom: header?.getBoundingClientRect().bottom || 0,
      };
    });
    expect(geometry.horizontalOverflow).toBe(false);
    expect(geometry.tableVisible).toBeGreaterThan(0);
    expect(geometry.targetTop).toBeGreaterThanOrEqual(geometry.headerBottom);
  }
});

test('Editorial trace filters, pagination, shared drawer, and language state remain closed over persisted rows', async ({ page }, testInfo) => {
  const reportPath = generateEditorialCandidate(testInfo.outputDir);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(pathToFileURL(reportPath).toString());
  await page.getByTestId('run-evidence-mode-button').click();
  await page.getByRole('link', { name: 'LLM 决策', exact: true }).click();

  const rows = page.getByTestId('run-trace-table-body').locator('tr');
  await expect(rows).toHaveCount(25);
  await expect(page.getByTestId('run-trace-page-status')).toContainText('1 / 72');
  await expect(page.getByTestId('run-trace-page-numbers').locator('button')).toHaveCount(4);
  await expect(page.getByTestId('run-trace-page-numbers').locator('button:disabled')).toHaveCount(1);
  const firstIdentity = await rows.first().getAttribute('data-trace-id');
  await page.locator('[data-trace-page="next"]').click();
  await expect(page.getByTestId('run-trace-page-status')).toContainText('2 / 72');
  expect(await rows.first().getAttribute('data-trace-id')).not.toBe(firstIdentity);

  await page.getByTestId('run-trace-message-select').selectOption('message_2');
  await expect(rows).toHaveCount(25);
  await expect(page.getByTestId('run-trace-page-status')).toContainText('1 / 24');
  await expect(rows.first()).toHaveAttribute('data-message-id', 'message_2');
  await page.getByTestId('run-trace-page-size').selectOption('50');
  await expect(rows).toHaveCount(50);
  await expect(page.getByTestId('run-trace-page-status')).toContainText('1 / 12');

  await rows.first().press('Enter');
  const drawer = page.getByTestId('evidence-drawer');
  await expect(drawer).toBeVisible();
  await expect(drawer).toHaveAttribute('role', 'dialog');
  await expect(drawer).toHaveAttribute('aria-modal', 'true');
  await expect(drawer.getByRole('tab')).toHaveCount(4);
  await expect(drawer.locator('[data-drawer-panel="summary"]')).toBeVisible();
  await expect(drawer.locator('[data-drawer-panel="summary"]')).not.toContainText('每次在旅途中下榻酒店');
  await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe('hidden');
  await page.getByRole('tab', { name: 'Context', exact: true }).click();
  await expect(drawer.locator('[data-drawer-panel="context"]')).toBeVisible();
  await expect(drawer.locator('[data-drawer-panel="context"]')).toContainText('一次好的入住体验');
  await page.getByRole('tab', { name: 'Lineage', exact: true }).click();
  await expect(drawer.locator('[data-drawer-panel="lineage"]')).toContainText('Field Provenance');
  await page.getByRole('tab', { name: 'Context', exact: true }).click();
  await expect(drawer.locator('[data-drawer-panel="context"]')).toBeVisible();
  await page.getByRole('button', { name: 'English', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-US');
  await expect(page.getByTestId('run-trace-page-size')).toHaveValue('50');
  await expect(page.getByTestId('run-trace-message-select')).toHaveValue('message_2');
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole('tab', { name: 'Context', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(drawer.locator('[data-drawer-panel="lineage"]')).toBeHidden();
  await page.getByRole('button', { name: 'Close detail', exact: true }).focus();
  await page.keyboard.press('Tab');
  await expect.poll(() => page.evaluate(() => document.activeElement?.closest('[role="dialog"]') !== null)).toBe(true);
  const selectedTraceId = await page.getByTestId('run-trace-table-body').locator('tr').first().getAttribute('data-trace-id');
  await page.keyboard.press('Escape');
  await expect(drawer).toBeHidden();
  await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe('');
  await expect.poll(() => page.evaluate((traceId) => document.activeElement?.getAttribute('data-trace-id'), selectedTraceId)).toBe(selectedTraceId);

  await rows.first().click();
  await expect(drawer).toBeVisible();
  await page.getByRole('button', { name: 'Close detail', exact: true }).click();
  await rows.first().press(' ');
  await expect(drawer).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(drawer).toBeHidden();

  await page.getByTestId('mechanism-mode-button').click();
  await expect(drawer).toBeHidden();
  await page.getByTestId('run-evidence-mode-button').click();
  await page.locator('[data-report-anchor="llm-decision"]').click();
  for (const viewport of [{ width: 1600, height: 1000 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await page.locator('#run-llm-decision').scrollIntoViewIfNeeded();
    const geometry = await page.evaluate(() => ({
      horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
      tableWidth: document.querySelector<HTMLElement>('[data-testid="run-trace-table"]')?.getBoundingClientRect().width || 0,
      sectionWidth: document.querySelector<HTMLElement>('#run-llm-decision')?.getBoundingClientRect().width || 0,
    }));
    expect(geometry.horizontalOverflow).toBe(false);
    expect(geometry.tableWidth).toBeGreaterThan(0);
    expect(geometry.sectionWidth).toBeLessThanOrEqual(viewport.width + 1);
  }
});


test('Editorial network feedback closes persisted batches and groups canonical downloads', async ({ page }, testInfo) => {
  const reportPath = generateEditorialCandidate(testInfo.outputDir);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(pathToFileURL(reportPath).toString());
  await page.getByTestId('run-evidence-mode-button').click();
  await page.getByRole('link', { name: '网络反馈', exact: true }).click();

  const feedback = page.getByTestId('run-network-feedback-section');
  await expect(feedback).toBeVisible();
  await expect(page.getByTestId('run-feedback-changed-total')).toContainText('15 / 90');
  for (const [messageId, changed, minimum, maximum] of [
    ['message_1', '5 / 30', '5', '20'],
    ['message_2', '5 / 30', '8', '20'],
    ['message_3', '5 / 30', '6', '20'],
  ]) {
    const card = page.getByTestId(`run-feedback-message-${messageId}`);
    await expect(card).toContainText(changed);
    await expect(card).toContainText(`${minimum}–${maximum}`);
  }

  const feedbackRows = page.getByTestId('run-feedback-table-body').locator('tr');
  await expect(feedbackRows).toHaveCount(15);
  await expect(feedbackRows.first()).toHaveAttribute('data-time-step', '1');
  await page.getByTestId('run-feedback-scope-select').selectOption('all');
  await expect(feedbackRows).toHaveCount(90);
  await page.getByTestId('run-feedback-message-select').selectOption('message_1');
  await expect(feedbackRows).toHaveCount(30);
  await page.getByTestId('run-feedback-scope-select').selectOption('changed');
  await expect(feedbackRows).toHaveCount(5);

  await feedbackRows.first().press('Enter');
  const drawer = page.getByTestId('evidence-drawer');
  await expect(drawer).toBeVisible();
  await expect(drawer.locator('[data-drawer-panel="summary"]')).toContainText('15');
  await page.getByRole('tab', { name: 'Context', exact: true }).click();
  await expect(drawer.locator('[data-drawer-panel="context"]')).toContainText('Feedback added user IDs');
  await expect(drawer.locator('[data-drawer-panel="context"] code')).toHaveCount(10);
  await page.getByRole('tab', { name: 'Lineage', exact: true }).click();
  await expect(drawer.locator('[data-drawer-panel="lineage"]')).toContainText('concurrent_campaign_diagnostics.json');
  await page.getByTestId('editorial-drawer-close').click();
  await expect(drawer).toBeHidden();

  const expectedDownloads = [
    'concurrent_message_report_payload.json',
    'concurrent_validation.json',
    'artifact_manifest.json',
    'sample_manifest.json',
    'sample_manifest.csv',
    'concurrent_message_users.json',
    'concurrent_message_users.csv',
    'concurrent_message_decision_trace.json',
    'concurrent_message_decision_trace.csv',
    'concurrent_message_primary_actions.csv',
    'concurrent_message_provider_failures.csv',
    'concurrent_message_runtime.json',
    'concurrent_message_diagnostics.json',
    'concurrent_message_field_lineage.json',
    'concurrent_runtime_candidates.csv',
    'concurrent_runtime_pairs.csv',
    'concurrent_runtime_terminal_rows.csv',
  ];
  await expect(page.getByTestId('run-downloads-section').getByRole('link')).toHaveCount(17);
  await expect(page.locator('[data-testid^="run-download-group-"]')).toHaveCount(4);
  const hrefs = await page.locator('[data-download-key]').evaluateAll((links) => links.map((link) => link.getAttribute('href')));
  expect(hrefs).toEqual(expectedDownloads);

  await page.getByRole('button', { name: 'English', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-US');
  await expect(page.getByTestId('run-feedback-scope-select')).toHaveValue('changed');
  await expect(page.getByTestId('run-feedback-message-select')).toHaveValue('message_1');
  await expect(page.getByTestId('run-downloads-section')).toContainText('17 approved artifacts grouped by research responsibility');
  await expect(page.locator('[data-download-key]').evaluateAll((links) => links.map((link) => link.getAttribute('href')))).resolves.toEqual(expectedDownloads);

  for (const viewport of [{ width: 1600, height: 1000 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await feedback.scrollIntoViewIfNeeded();
    const geometry = await page.evaluate(() => ({
      horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
      feedbackWidth: document.querySelector<HTMLElement>('[data-testid="run-network-feedback-section"]')?.getBoundingClientRect().width || 0,
      downloadsWidth: document.querySelector<HTMLElement>('[data-testid="run-downloads-section"]')?.getBoundingClientRect().width || 0,
    }));
    expect(geometry.horizontalOverflow).toBe(false);
    expect(geometry.feedbackWidth).toBeLessThanOrEqual(viewport.width + 1);
    expect(geometry.downloadsWidth).toBeLessThanOrEqual(viewport.width + 1);
  }
});
