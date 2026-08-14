import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';

type FullPoolFixture = {
  bundleDir: string;
  index: {
    partitions: Array<{
      message_id: string;
      time_step: number;
      relative_path: string;
      row_count: number;
    }>;
  };
};

function generateFullPoolFixture(outputDir: string): FullPoolFixture {
  const explicitBundle = process.env.FULL_POOL_PRESENTATION_BUNDLE;
  if (explicitBundle) {
    const bundleDir = path.resolve(explicitBundle);
    const reportPath = path.join(bundleDir, 'report.html');
    const indexPath = path.join(bundleDir, 'trace', 'full-pool-trace-index.json');
    if (!existsSync(reportPath) || !existsSync(indexPath)) {
      throw new Error('FULL_POOL_PRESENTATION_BUNDLE must contain report.html and the trace index');
    }
    return { bundleDir, index: JSON.parse(readFileSync(indexPath, 'utf8')) };
  }
  const root = path.join(outputDir, 'full-pool-presentation-fixture');
  const command = `
set -euo pipefail
. .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD"
python - <<'PY'
from pathlib import Path
from llm_abm_sim import concurrent_robustness_report as report
from tests.integration.test_full_pool_presentation_bundle import (
    _full_pool_source,
    _historical_candidate,
)

root = Path(${JSON.stringify(root)}).resolve()
root.mkdir(parents=True, exist_ok=True)
source, manifest_sha256 = _full_pool_source(root / 'full-pool')
formal, study, historical = _historical_candidate(root / 'historical')
report._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
    full_pool_source_root=source,
    full_pool_manifest_sha256=manifest_sha256,
    historical_formal_root=formal,
    historical_study_root=study,
    historical_candidate_dir=historical,
    destination_dir=root / 'bundle',
)
PY`;
  execFileSync('bash', ['-lc', command], { stdio: 'inherit' });
  const bundleDir = path.join(root, 'bundle');
  const index = JSON.parse(
    readFileSync(path.join(bundleDir, 'trace', 'full-pool-trace-index.json'), 'utf8'),
  );
  return { bundleDir, index };
}

async function availablePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (!address || typeof address === 'string') {
        server.close();
        reject(new Error('could not allocate a local HTTP port'));
        return;
      }
      const port = address.port;
      server.close((error) => (error ? reject(error) : resolve(port)));
    });
  });
}

async function serveFixture(bundleDir: string): Promise<{ baseURL: string; server: ChildProcess }> {
  const port = await availablePort();
  const baseURL = `http://127.0.0.1:${port}`;
  const server = spawn(
    'python',
    ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '--directory', bundleDir],
    { stdio: ['ignore', 'ignore', 'pipe'] },
  );
  return { baseURL, server };
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    sections: [...document.querySelectorAll<HTMLElement>('.full-pool-hero, .full-pool-section')]
      .filter((element) => element.getBoundingClientRect().width > window.innerWidth + 1)
      .map((element) => element.id),
  }));
  expect(overflow).toEqual({ document: false, sections: [] });
}

function stopServer(server: ChildProcess): void {
  if (!server.killed) server.kill('SIGTERM');
}

test('Full-Pool report is bilingual, responsive, lazy, filterable, and keyboard accessible', async ({ page, request }, testInfo) => {
  test.setTimeout(180_000);
  const fixture = generateFullPoolFixture(testInfo.outputDir);
  const { baseURL, server } = await serveFixture(fixture.bundleDir);
  const firstPartition = fixture.index.partitions.find(
    (entry) => entry.message_id === 'message_1' && entry.time_step === 0,
  );
  const secondMessagePartition = fixture.index.partitions.find(
    (entry) => entry.message_id === 'message_2' && entry.time_step === 0,
  );
  const secondMessageFinalPartition = fixture.index.partitions
    .filter((entry) => entry.message_id === 'message_2')
    .sort((left, right) => right.time_step - left.time_step)[0];
  if (!firstPartition || !secondMessagePartition || !secondMessageFinalPartition) {
    throw new Error('Full-Pool trace index is missing required message/batch partitions');
  }
  const traceRequests: string[] = [];
  const thirdPartyRequests: string[] = [];
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  page.on('request', (observed) => {
    const url = new URL(observed.url());
    if (url.origin !== baseURL) thirdPartyRequests.push(observed.url());
    if (url.pathname.startsWith('/trace/')) traceRequests.push(url.pathname);
  });
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));

  try {
    await expect.poll(async () => {
      try {
        return (await request.get(`${baseURL}/report.html`)).status();
      } catch {
        return 0;
      }
    }).toBe(200);
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(`${baseURL}/report.html`);

    await expect(page).toHaveTitle('Full-Pool 主实验');
    await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
    await expect(page.getByTestId('full-pool-presentation')).toHaveAttribute(
      'data-production-deploy-eligible',
      'false',
    );
    await expect(page.getByTestId('full-pool-main-experiment').getByRole('heading', { level: 1 })).toContainText('Full-Pool 主实验');
    await expect(page.getByTestId('full-pool-run-evidence')).toContainText('36,400');
    await expect(page.getByTestId('full-pool-run-evidence')).toContainText('109,200');
    await expect(page.getByTestId('full-pool-run-evidence')).toContainText('实际值');
    await expect(page.getByTestId('full-pool-claim-boundary')).toContainText('排序只改变曝光批次与顺序');
    await expect(page.getByTestId('historical-sensitivity-1000')).toContainText(
      'Historical Sensitivity · 1,000 users',
    );
    await expect(page.getByTestId('full-pool-mechanism-section').locator('[data-mechanism-node-id]')).toHaveCount(8);
    await expect(page.getByTestId('full-pool-mechanism-section').locator('[data-mechanism-edge-id]')).toHaveCount(8);
    await expect(page.getByTestId('full-pool-mechanism-section')).toContainText('Primary-only');

    const traceState = page.getByTestId('full-pool-trace-state');
    await expect(traceState).toHaveAttribute('data-trace-state', 'ready');
    await expect(page.getByTestId('full-pool-trace-reader')).toHaveAttribute('data-trace-state', 'ready');
    await expect(page.getByTestId('full-pool-trace-reader')).toHaveAttribute('aria-busy', 'false');
    await expect(page.getByTestId('full-pool-trace-message')).toBeEnabled();
    await expect(page.getByTestId('full-pool-trace-batch')).toBeEnabled();
    await expect(page.getByTestId('full-pool-trace-search')).toBeEnabled();
    await expect(page.getByTestId('full-pool-trace-action')).toBeEnabled();
    await expect(page.getByTestId('full-pool-trace-table')).toBeVisible();
    await expect(page.getByTestId('full-pool-trace-table-body').locator('tr')).toHaveCount(
      firstPartition.row_count,
    );
    expect(traceRequests).toEqual([
      '/trace/full-pool-trace-index.json',
      `/${firstPartition.relative_path}`,
    ]);

    const messageResponse = page.waitForResponse((response) =>
      response.url().endsWith(`/${secondMessagePartition.relative_path}`),
    );
    await page.getByTestId('full-pool-trace-message').selectOption('message_2');
    await messageResponse;
    await expect(traceState).toHaveAttribute('data-trace-state', 'ready');
    await expect(page.getByTestId('full-pool-trace-table-body').locator('tr')).toHaveCount(
      secondMessagePartition.row_count,
    );

    const batchResponse = page.waitForResponse((response) =>
      response.url().endsWith(`/${secondMessageFinalPartition.relative_path}`),
    );
    await page.getByTestId('full-pool-trace-batch').selectOption(
      String(secondMessageFinalPartition.time_step),
    );
    await batchResponse;
    await expect(traceState).toHaveAttribute('data-trace-state', 'ready');
    await expect(page.getByTestId('full-pool-trace-table-body').locator('tr')).toHaveCount(
      secondMessageFinalPartition.row_count,
    );
    expect(traceRequests).toEqual([
      '/trace/full-pool-trace-index.json',
      `/${firstPartition.relative_path}`,
      `/${secondMessagePartition.relative_path}`,
      `/${secondMessageFinalPartition.relative_path}`,
    ]);

    const firstRow = page.getByTestId('full-pool-trace-table-body').locator('tr').first();
    const userId = (await firstRow.locator('td').first().textContent()) ?? '';
    await page.getByTestId('full-pool-trace-search').fill(userId);
    await expect(page.getByTestId('full-pool-trace-filtered-count')).toContainText('1');
    await expect(page.getByTestId('full-pool-trace-table-body').locator('tr')).toHaveCount(1);

    const detailButton = page.getByTestId('full-pool-trace-row').first();
    await detailButton.focus();
    await detailButton.press('Enter');
    const drawer = page.getByTestId('full-pool-trace-drawer');
    await expect(drawer).toBeVisible();
    await expect(drawer.getByTestId('full-pool-trace-detail')).toContainText(userId);
    await expect(drawer.getByTestId('full-pool-trace-drawer-close')).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(drawer.getByTestId('full-pool-trace-drawer-close')).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(drawer).toBeHidden();
    await expect(detailButton).toBeFocused();

    const fallback = page.getByTestId('full-pool-mechanism-fallback');
    const summary = fallback.locator('summary');
    await summary.focus();
    await summary.press('Enter');
    await expect(fallback).toHaveAttribute('open', '');
    await summary.press('Space');
    await expect(fallback).not.toHaveAttribute('open', '');

    await page.locator('[data-full-pool-language="en-US"]').click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'en-US');
    await expect(page.getByTestId('full-pool-main-experiment').getByRole('heading', { level: 1 })).toHaveText('Full-Pool Main Experiment');
    await expect(page.getByTestId('full-pool-claim-boundary')).toContainText(
      'ranking changes exposure timing and order only',
    );
    await expect(page.getByTestId('full-pool-trace-state')).toContainText('ready');

    const downloadHrefs = await page.getByTestId('full-pool-downloads').locator('a[href]').evaluateAll(
      (links) => links.map((link) => (link as HTMLAnchorElement).getAttribute('href') ?? ''),
    );
    expect(downloadHrefs.length).toBeGreaterThanOrEqual(10);
    expect(downloadHrefs.every((href) => href && !href.startsWith('http') && existsSync(path.join(fixture.bundleDir, href)))).toBe(true);
    const mermaidDownloads = await page.locator('a[href$=".mmd"]').evaluateAll(
      (links) => links.map((link) => (link as HTMLAnchorElement).getAttribute('href')),
    );
    expect(new Set(mermaidDownloads).size).toBe(8);
    const allLocalDownloads = await page.locator('a[href]').evaluateAll((links) => links
      .map((link) => (link as HTMLAnchorElement).getAttribute('href') ?? '')
      .filter((href) => href && !href.startsWith('#')));
    expect(allLocalDownloads.every((href) => !href.startsWith('http') && existsSync(path.join(fixture.bundleDir, href)))).toBe(true);

    await expectNoHorizontalOverflow(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await expectNoHorizontalOverflow(page);
    await expect(page.getByTestId('full-pool-run-evidence')).toBeVisible();
    await expect(page.getByTestId('full-pool-trace-reader')).toBeVisible();
    const mobileColumns = await page.locator('.full-pool-scope-grid').evaluate(
      (element) => getComputedStyle(element).gridTemplateColumns.split(' ').length,
    );
    expect(mobileColumns).toBe(1);

    expect(thirdPartyRequests).toEqual([]);
    expect(consoleErrors).toEqual([]);
    expect(pageErrors).toEqual([]);
  } finally {
    stopServer(server);
  }
});

test('Full-Pool trace failure remains an accessible fail-closed state', async ({ page, request }, testInfo) => {
  test.setTimeout(180_000);
  const fixture = generateFullPoolFixture(testInfo.outputDir);
  const { baseURL, server } = await serveFixture(fixture.bundleDir);
  let releasePartition: (() => void) | undefined;
  const partitionGate = new Promise<void>((resolve) => {
    releasePartition = resolve;
  });
  await page.route('**/trace/message_1/batch-000000.json', async (route) => {
    await partitionGate;
    await route.fulfill({ status: 503, body: 'partition unavailable' });
  });

  try {
    await expect.poll(async () => {
      try {
        return (await request.get(`${baseURL}/report.html`)).status();
      } catch {
        return 0;
      }
    }).toBe(200);
    await page.goto(`${baseURL}/report.html`);
    const state = page.getByTestId('full-pool-trace-state');
    await expect(state).toHaveAttribute('data-trace-state', 'loading');
    await expect(page.getByTestId('full-pool-trace-reader')).toHaveAttribute('aria-busy', 'true');
    await expect(state).toHaveAttribute('role', 'status');
    await expect(state).toHaveAttribute('aria-live', 'polite');
    await expect(page.getByTestId('full-pool-trace-search')).toBeDisabled();
    releasePartition?.();

    await expect(state).toHaveAttribute('data-trace-state', 'error');
    await expect(state).toContainText('不可用');
    await expect(page.getByTestId('full-pool-trace-reader')).toHaveAttribute('data-trace-state', 'error');
    await expect(page.getByTestId('full-pool-trace-reader')).toHaveAttribute('aria-busy', 'false');
    await expect(page.getByTestId('full-pool-trace-message')).toBeDisabled();
    await expect(page.getByTestId('full-pool-trace-batch')).toBeDisabled();
    await expect(page.getByTestId('full-pool-trace-search')).toBeDisabled();
    await expect(page.getByTestId('full-pool-trace-action')).toBeDisabled();
    await expect(page.getByTestId('full-pool-trace-table')).toBeHidden();
    await expect(page.getByTestId('full-pool-trace-table-body').locator('tr')).toHaveCount(0);
    await expect(page.getByTestId('full-pool-trace-filtered-count')).toContainText('0');
  } finally {
    stopServer(server);
  }
});
