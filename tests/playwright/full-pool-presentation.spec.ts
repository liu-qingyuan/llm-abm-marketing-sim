import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';

type TracePartitionEntry = {
  message_id: string;
  time_step: number;
  relative_path: string;
  row_count: number;
  bytes: number;
  sha256: string;
  terminal_identity_sha256: string;
};

type FullPoolFixture = {
  bundleDir: string;
  synthetic: boolean;
  index: {
    terminal_count: number;
    partitions: TracePartitionEntry[];
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
    return { bundleDir, synthetic: false, index: JSON.parse(readFileSync(indexPath, 'utf8')) };
  }
  const root = path.join(outputDir, 'full-pool-presentation-fixture');
  const command = `
set -euo pipefail
. .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD"
mkdir -p ${JSON.stringify(root)}
cat > ${JSON.stringify(path.join(root, 'compose_source_v4_fixture_test.py'))} <<'PY'
from pathlib import Path
from llm_abm_sim import concurrent_robustness_report as report
from llm_abm_sim.full_pool_two_stage_replay import (
    FullPoolTwoStageReplay,
    FullPoolTwoStageReplayRequest,
)
from tests.integration.test_full_pool_presentation_bundle import _historical_candidate
from tests.integration.test_full_pool_two_stage_replay import _source_v4


def test_compose_two_stage_realized_fixture() -> None:
    root = Path(${JSON.stringify(root)}).resolve()
    upstream_root, upstream_manifest_sha256, upstream_identity = _source_v4(root / 'strict-inputs')
    realized = FullPoolTwoStageReplay().run_and_close(
        FullPoolTwoStageReplayRequest(
            source_root=upstream_root,
            source_manifest_sha256=upstream_manifest_sha256,
            source_identity=upstream_identity,
            output_dir=root / 'realized-source',
        )
    )
    formal, study, historical = _historical_candidate(root / 'historical')
    report._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=realized.output_dir,
        full_pool_manifest_sha256=realized.manifest_sha256,
        historical_formal_root=formal,
        historical_study_root=study,
        historical_candidate_dir=historical,
        destination_dir=root / 'bundle',
    )
PY
pytest -q ${JSON.stringify(path.join(root, 'compose_source_v4_fixture_test.py'))}
rm -f ${JSON.stringify(path.join(root, 'compose_source_v4_fixture_test.py'))}`;
  execFileSync('bash', ['-lc', command], { stdio: 'inherit' });
  const bundleDir = path.join(root, 'bundle');
  const index = JSON.parse(
    readFileSync(path.join(bundleDir, 'trace', 'full-pool-trace-index.json'), 'utf8'),
  );
  return { bundleDir, synthetic: true, index };
}

function sha256(value: Buffer | string): string {
  return createHash('sha256').update(value).digest('hex');
}

function expandFirstPartitionForPagination(fixture: FullPoolFixture): TracePartitionEntry {
  const entry = fixture.index.partitions.find(
    (candidate) => candidate.message_id === 'message_1' && candidate.time_step === 0,
  );
  if (!entry) throw new Error('Full-Pool fixture is missing the first trace partition');
  const partitionPath = path.join(fixture.bundleDir, entry.relative_path);
  const partition = JSON.parse(readFileSync(partitionPath, 'utf8'));
  const sourceRows = partition.rows as Array<Record<string, unknown>>;
  if (!sourceRows.length) throw new Error('Full-Pool fixture partition is empty');
  const rows = Array.from({ length: 60 }, (_, index) => {
    const source = sourceRows[index % sourceRows.length];
    return {
      ...source,
      terminal_row_id: `${String(source.terminal_row_id)}-page-${index.toString().padStart(2, '0')}`,
      user_id: `pagination-user-${index.toString().padStart(2, '0')}`,
    };
  });
  const terminalIdentity = sha256(JSON.stringify(rows.map((row) => row.terminal_row_id)));
  partition.rows = rows;
  partition.row_count = rows.length;
  partition.terminal_identity_sha256 = terminalIdentity;
  const partitionBytes = Buffer.from(JSON.stringify(partition));
  writeFileSync(partitionPath, partitionBytes);

  const indexPath = path.join(fixture.bundleDir, 'trace', 'full-pool-trace-index.json');
  const oldIndexBytes = readFileSync(indexPath);
  const oldIndexSha = sha256(oldIndexBytes);
  entry.row_count = rows.length;
  entry.bytes = partitionBytes.byteLength;
  entry.sha256 = sha256(partitionBytes);
  entry.terminal_identity_sha256 = terminalIdentity;
  fixture.index.terminal_count = fixture.index.partitions.reduce(
    (total, candidate) => total + candidate.row_count,
    0,
  );
  const newIndexBytes = Buffer.from(JSON.stringify(fixture.index));
  writeFileSync(indexPath, newIndexBytes);
  const reportPath = path.join(fixture.bundleDir, 'report.html');
  const report = readFileSync(reportPath, 'utf8');
  if (!report.includes(oldIndexSha)) throw new Error('Full-Pool report is missing the trace index hash');
  writeFileSync(reportPath, report.replaceAll(oldIndexSha, sha256(newIndexBytes)));
  return entry;
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
    path.join(process.cwd(), '.venv', 'bin', 'python'),
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
  const deliveryRunCount = 1;
  const firstPartition = fixture.synthetic
    ? expandFirstPartitionForPagination(fixture)
    : fixture.index.partitions.find(
      (entry) => entry.message_id === 'message_1' && entry.time_step === 0,
    );
  if (!firstPartition) throw new Error('Full-Pool trace index is missing the first partition');
  const protectedBytes = fixture.synthetic
    ? null
    : new Map(
      [
        'report.html',
        'trace/full-pool-trace-index.json',
        firstPartition.relative_path,
      ].map((relative) => [relative, readFileSync(path.join(fixture.bundleDir, relative))]),
    );
  const { baseURL, server } = await serveFixture(fixture.bundleDir);
  const secondMessagePartition = fixture.index.partitions.find(
    (entry) => entry.message_id === 'message_2' && entry.time_step === 0,
  );
  const secondMessageFinalPartition = fixture.index.partitions
    .filter((entry) => entry.message_id === 'message_2')
    .sort((left, right) => right.time_step - left.time_step)[0];
  if (!secondMessagePartition || !secondMessageFinalPartition) {
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

    await expect(page).toHaveTitle('Full-Pool 两阶段互动实现');
    await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
    await expect(page.getByTestId('full-pool-presentation')).toHaveAttribute(
      'data-production-deploy-eligible',
      'false',
    );
    await expect(page.getByTestId('full-pool-presentation')).toHaveAttribute(
      'data-presentation-semantics',
      'two_stage_realized',
    );
    await expect(page.getByTestId('full-pool-main-experiment').getByRole('heading', { level: 1 })).toContainText('Full-Pool 两阶段互动实现');
    await expect(page.getByTestId('full-pool-realized-headline')).toContainText('/');
    await expect(page.getByTestId('full-pool-run-evidence')).toContainText('同源 realized 运行口径');
    await expect(page.getByTestId('full-pool-claim-boundary')).toContainText('单次 user × message exposure');
    await expect(page.getByTestId('full-pool-result-conclusion')).toContainText('S1 尚未形成 M1 偏好证据');
    await expect(page.getByTestId('full-pool-probability-contract')).toContainText('effective gate expectation');
    await expect(page.getByTestId('full-pool-feedback-trajectory')).toContainText('Realized feedback barrier');
    await expect(page.getByTestId('historical-sensitivity-1000')).toContainText(
      'Historical Sensitivity · 1,000 users',
    );
    const mechanism = page.getByTestId('full-pool-mechanism-section');
    const mechanismSvg = page.getByTestId('full-pool-mechanism-svg');
    await expect(mechanismSvg).toBeVisible();
    await expect(mechanismSvg).toHaveAttribute('role', 'img');
    await expect(mechanismSvg.locator('[data-mechanism-node-id]')).toHaveCount(12);
    await expect(mechanismSvg.locator('[data-mechanism-edge-id]')).toHaveCount(13);
    await expect(mechanism.getByTestId('full-pool-mechanism-fallback').locator('[data-mechanism-node-id]')).toHaveCount(12);
    await expect(mechanism.getByTestId('full-pool-mechanism-fallback').locator('[data-mechanism-edge-id]')).toHaveCount(13);
    await expect(mechanism).toContainText('Provider Judgment');
    const firstMechanismNode = mechanismSvg.locator('[data-mechanism-node-id]').first();
    await firstMechanismNode.focus();
    await expect(firstMechanismNode).toBeFocused();

    const segmentTable = page.getByTestId('full-pool-segment-table');
    await expect(segmentTable).toBeVisible();
    await expect(segmentTable.locator('thead th')).toHaveText([
      'Group',
      'Exposure',
      'Likes',
      'Comments',
      'Shares',
      'Realized ignores',
      'Realized engagements',
      '单次曝光 realized engagement',
    ]);
    const segmentRows = segmentTable.locator('tbody tr');
    await expect(segmentRows).toHaveCount(deliveryRunCount * 9);
    expect(await segmentRows.locator('th').allTextContents()).toEqual(
      ['S1', 'S2', 'S3'].flatMap((segment) =>
        ['M1', 'M2', 'M3'].map((message) => `${segment} × ${message}`),
      ),
    );
    const resultCsv = await request.get(
      `${baseURL}/full-pool-source/full-pool-realized-projection.csv`,
    );
    expect(resultCsv.status()).toBe(200);
    expect(await resultCsv.text()).toContain(
      'Run,Message,Segment,Total Likes,Total Comments,Total Shares,Exposure',
    );
    const realizedEvidence = await request.get(
      `${baseURL}/full-pool-source/realization-evidence.json`,
    );
    expect(realizedEvidence.status()).toBe(200);
    expect((await realizedEvidence.json()).production_deploy_eligible).toBe(false);

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
      Math.min(firstPartition.row_count, 25),
    );
    expect(traceRequests).toEqual([
      '/trace/full-pool-trace-index.json',
      `/${firstPartition.relative_path}`,
    ]);
    const pagination = page.getByTestId('full-pool-trace-pagination');
    const pageStatus = page.getByTestId('full-pool-trace-page-status');
    const firstPartitionPageCount = Math.max(1, Math.ceil(firstPartition.row_count / 25));
    const previousPage = pagination.locator('[data-full-pool-trace-page="previous"]');
    const nextPage = pagination.locator('[data-full-pool-trace-page="next"]');
    await expect(pagination).toBeVisible();
    await expect(pageStatus).toContainText(`第 1 / ${firstPartitionPageCount} 页`);
    await expect(previousPage).toBeDisabled();
    await expect(nextPage).toBeEnabled();
    await nextPage.focus();
    await nextPage.press('Enter');
    await expect(pageStatus).toContainText(`第 2 / ${firstPartitionPageCount} 页`);
    await expect(page.getByTestId('full-pool-trace-table-body').locator('tr')).toHaveCount(25);
    await nextPage.click();
    await expect(pageStatus).toContainText(`第 3 / ${firstPartitionPageCount} 页`);
    await expect(page.getByTestId('full-pool-trace-table-body').locator('tr')).toHaveCount(
      Math.min(25, firstPartition.row_count - 50),
    );
    if (firstPartitionPageCount === 3) await expect(nextPage).toBeDisabled();
    else await expect(nextPage).toBeEnabled();
    await previousPage.click();
    await expect(pageStatus).toContainText(`第 2 / ${firstPartitionPageCount} 页`);
    expect(traceRequests).toEqual([
      '/trace/full-pool-trace-index.json',
      `/${firstPartition.relative_path}`,
    ]);
    if (fixture.synthetic) {
      await page.getByTestId('full-pool-trace-search').fill('pagination-user-00');
      await expect(pageStatus).toContainText('第 1 / 1 页');
      await expect(page.getByTestId('full-pool-trace-table-body').locator('tr')).toHaveCount(1);
      await expect(previousPage).toBeDisabled();
      await expect(nextPage).toBeDisabled();
      await page.getByTestId('full-pool-trace-search').fill('');
    } else {
      await previousPage.click();
    }
    await expect(pageStatus).toContainText(`第 1 / ${firstPartitionPageCount} 页`);
    await nextPage.click();
    await expect(pageStatus).toContainText(`第 2 / ${firstPartitionPageCount} 页`);

    const messageResponse = page.waitForResponse((response) =>
      response.url().endsWith(`/${secondMessagePartition.relative_path}`),
    );
    await page.getByTestId('full-pool-trace-message').selectOption('message_2');
    await messageResponse;
    await expect(traceState).toHaveAttribute('data-trace-state', 'ready');
    await expect(pageStatus).toContainText(
      `第 1 / ${Math.max(1, Math.ceil(secondMessagePartition.row_count / 25))} 页`,
    );
    await expect(page.getByTestId('full-pool-trace-table-body').locator('tr')).toHaveCount(
      Math.min(secondMessagePartition.row_count, 25),
    );

    const batchResponse = page.waitForResponse((response) =>
      response.url().endsWith(`/${secondMessageFinalPartition.relative_path}`),
    );
    await page.getByTestId('full-pool-trace-batch').selectOption({
      value: String(secondMessageFinalPartition.time_step),
    });
    await batchResponse;
    await expect(traceState).toHaveAttribute('data-trace-state', 'ready');
    await expect(page.getByTestId('full-pool-trace-table-body').locator('tr')).toHaveCount(
      Math.min(secondMessageFinalPartition.row_count, 25),
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
    await expect(drawer.getByTestId('full-pool-trace-detail')).toContainText('provider_judgment');
    await expect(drawer.getByTestId('full-pool-trace-detail')).toContainText('abm_realization');
    await expect(drawer.getByTestId('full-pool-trace-detail')).not.toContainText('realized_reason');
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
    await expect(page.getByTestId('full-pool-main-experiment').getByRole('heading', { level: 1 })).toHaveText('Full-Pool Two-Stage Engagement Realization');
    await expect(page.getByTestId('full-pool-claim-boundary')).toContainText(
      'single user × message exposure',
    );
    await expect(page.getByTestId('full-pool-result-conclusion')).toContainText(
      'S1 does not evidence a preference for M1',
    );
    await expect(page.getByTestId('full-pool-probability-contract')).toContainText(
      'fixed Judgment group',
    );
    await expect(page.getByTestId('full-pool-trace-state')).toContainText('ready');
    await expect(page.getByTestId('full-pool-trace-page-status')).toContainText('Page 1 of 1');
    await expect(page.locator('[data-full-pool-trace-page="previous"]')).toHaveAttribute(
      'aria-label',
      'Previous page',
    );
    await expect(page.locator('[data-full-pool-trace-page="next"]')).toHaveAttribute(
      'aria-label',
      'Next page',
    );

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
    await expect(page.getByTestId('full-pool-segment-results')).toBeVisible();
    const mobileColumns = await page.getByTestId('full-pool-run-evidence').locator('.full-pool-provider-grid').evaluate(
      (element) => getComputedStyle(element).gridTemplateColumns.split(' ').length,
    );
    expect(mobileColumns).toBe(1);

    expect(thirdPartyRequests).toEqual([]);
    expect(consoleErrors).toEqual([]);
    expect(pageErrors).toEqual([]);
  } finally {
    stopServer(server);
    if (protectedBytes) {
      for (const [relative, before] of protectedBytes) {
        expect(readFileSync(path.join(fixture.bundleDir, relative))).toEqual(before);
      }
    }
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
    await expect(page.locator('[data-full-pool-trace-page="previous"]')).toBeDisabled();
    await expect(page.locator('[data-full-pool-trace-page="next"]')).toBeDisabled();
    await expect(page.getByTestId('full-pool-trace-table')).toBeHidden();
    await expect(page.getByTestId('full-pool-trace-table-body').locator('tr')).toHaveCount(0);
    await expect(page.getByTestId('full-pool-trace-filtered-count')).toContainText('0');
  } finally {
    stopServer(server);
  }
});
