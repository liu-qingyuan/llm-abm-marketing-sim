import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { createServer } from 'node:http';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { expect, test } from '@playwright/test';

function generateV2ReportFixture(outputDir: string): string {
  const root = path.join(outputDir, 'robustness-v2-report-fixture');
  const command = `
set -euo pipefail
. .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD"
python - <<'PY'
from pathlib import Path
from _pytest.monkeypatch import MonkeyPatch

from llm_abm_sim import concurrent_robustness_report as report_module
from tests.integration.test_concurrent_robustness_v2_report import _closed_v2_study
from tests.integration.test_full_pool_presentation_bundle import (
    _formal_realized_full_pool_source,
    _historical_candidate,
)

root = Path(${JSON.stringify(root)}).resolve()
root.mkdir(parents=True, exist_ok=True)
monkeypatch = MonkeyPatch()
try:
    full_pool, manifest_sha256 = _formal_realized_full_pool_source(
        root / 'full-pool',
        monkeypatch,
    )
    historical_formal, historical_study, historical_candidate = _historical_candidate(
        root / 'historical'
    )
    v2_study = _closed_v2_study(root / 'v2')
    destination = root / 'candidate'
    report_module._REPORT_PRESENTATION.compose_v2_realized_candidate(
        full_pool_source_root=full_pool,
        full_pool_manifest_sha256=manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        v2_study_root=v2_study,
        destination_dir=destination,
    )
finally:
    monkeypatch.undo()
PY`;
  execFileSync('bash', ['-lc', command], { stdio: 'inherit' });
  return path.join(root, 'candidate');
}

async function startCandidateServer(candidateDir: string): Promise<{
  baseUrl: string;
  close: () => Promise<void>;
}> {
  const root = path.resolve(candidateDir);
  const server = createServer((request, response) => {
    const pathname = decodeURIComponent(new URL(request.url ?? '/', 'http://candidate.test').pathname);
    const target = path.resolve(root, `.${pathname}`);
    if (target !== root && !target.startsWith(`${root}${path.sep}`)) {
      response.writeHead(403).end();
      return;
    }
    try {
      const body = readFileSync(target);
      response.writeHead(200, {
        'Content-Type': target.endsWith('.html') ? 'text/html; charset=utf-8' : 'application/octet-stream',
        'Content-Length': String(body.length),
      });
      response.end(body);
    } catch {
      response.writeHead(404).end();
    }
  });
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address();
  if (address === null || typeof address === 'string') throw new Error('candidate server has no TCP address');
  return {
    baseUrl: `http://127.0.0.1:${address.port}`,
    close: () => new Promise<void>((resolve, reject) => {
      server.close((error) => error ? reject(error) : resolve());
    }),
  };
}

test('table-first v2 report filters, localizes, downloads, and fails closed', async ({ browser }, testInfo) => {
  test.setTimeout(300_000);
  const candidateDir = generateV2ReportFixture(testInfo.outputDir);
  const reportUrl = pathToFileURL(path.join(candidateDir, 'report.html')).href;
  const context = await browser.newContext({ viewport: { width: 1024, height: 700 } });
  const page = await context.newPage();
  const externalRequests: string[] = [];
  const pageErrors: string[] = [];
  page.on('request', (request) => {
    const protocol = new URL(request.url()).protocol;
    if (protocol !== 'file:' && protocol !== 'data:') externalRequests.push(request.url());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await page.goto(reportUrl);
  const report = page.getByTestId('robustness-v2-report');
  await expect(report).toHaveAttribute('data-v2-state', 'ready');
  await expect(report).toHaveAttribute('data-v2-active-view', 'realized');
  await expect(page.getByTestId('robustness-v2-realized-view')).toBeVisible();
  await expect(page.getByTestId('robustness-v2-judgment-view')).toBeHidden();
  await expect(report.locator('[data-v2-result-panel]:visible')).toHaveCount(1);
  await expect(report.locator('[data-v2-result-panel]:visible tbody tr')).toHaveCount(9);

  await page.getByTestId('robustness-v2-model-select').selectOption('openai-codex/gpt-5.6-sol');
  await page.getByTestId('robustness-v2-prompt-select').selectOption('P3');
  await expect(report.locator('[data-v2-result-panel]:visible')).toHaveAttribute(
    'data-v2-model',
    'openai-codex/gpt-5.6-sol',
  );
  await expect(report.locator('[data-v2-result-panel]:visible')).toHaveAttribute('data-v2-prompt', 'P3');
  const promptLink = report.locator('[data-v2-result-panel]:visible').getByRole('link', { name: 'P3' }).first();
  await promptLink.focus();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/#prompt-catalog-P3$/);
  await expect(page.getByTestId('robustness-v2-prompt-p3')).toBeInViewport();
  const judgmentButton = report.getByRole('button', { name: 'Judgment Audit' });
  await judgmentButton.focus();
  await page.keyboard.press('Enter');
  await expect(report).toHaveAttribute('data-v2-active-view', 'judgment');
  await expect(page.getByTestId('robustness-v2-realized-view')).toBeHidden();
  await expect(page.getByTestId('robustness-v2-judgment-view')).toBeVisible();
  await expect(report.locator('[data-v2-judgment-panel]:visible tbody tr')).toHaveCount(9);

  await report.getByRole('button', { name: 'English', exact: true }).click();
  await expect(report).toHaveAttribute('data-v2-language', 'en-US');
  await expect(report.getByRole('heading', { name: 'Five-model Prompt–Model Realized results' })).toBeVisible();
  await expect(page.getByTestId('robustness-v2-prompt-p3')).toContainText('System template');
  const mechanismSvg = report.getByRole('img', {
    name: 'Five-Model Prompt–Model Two-Stage Realization',
  });
  const mechanismFallback = report.locator(
    '[data-testid="robustness-v2-mechanism-fallback"][data-mechanism-language="en-US"]',
  );
  await expect(mechanismSvg).toBeVisible();
  await mechanismSvg.evaluate((element) => element.remove());
  await expect(mechanismFallback).toBeVisible();

  const downloads = page.getByTestId('robustness-v2-downloads').getByRole('link');
  const hrefs = await downloads.evaluateAll(
    (links) => links.map((link) => (link as HTMLAnchorElement).getAttribute('href')),
  );
  const manifest = JSON.parse(
    readFileSync(path.join(candidateDir, 'artifact_manifest.json'), 'utf8'),
  ) as { approved_downloads: Record<string, string> };
  expect(new Set(hrefs)).toEqual(new Set(Object.values(manifest.approved_downloads)));
  expect(hrefs.every((href) => href !== null && existsSync(path.join(candidateDir, href)))).toBe(true);
  const candidateServer = await startCandidateServer(candidateDir);
  try {
    for (let index = 0; index < hrefs.length; index += 1) {
      const href = hrefs[index];
      expect(href).not.toBeNull();
      await test.step(`download ${href}`, async () => {
        const downloadContext = await browser.newContext({ acceptDownloads: true });
        const downloadPage = await downloadContext.newPage();
        try {
          await downloadPage.goto(`${candidateServer.baseUrl}/report.html`);
          const link = downloadPage.getByTestId('robustness-v2-downloads').getByRole('link').nth(index);
          const [download] = await Promise.all([
            downloadPage.waitForEvent('download', { timeout: 10_000 }),
            link.click(),
          ]);
          expect(download.suggestedFilename()).toBe(path.basename(href!));
          expect(await download.failure()).toBeNull();
          expect(await download.path()).not.toBeNull();
        } finally {
          await downloadContext.close();
        }
      });
    }
  } finally {
    await candidateServer.close();
  }
  expect(await report.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  expect(externalRequests).toEqual([]);
  expect(pageErrors).toEqual([]);

  const failedPage = await context.newPage();
  await failedPage.addInitScript(() => {
    (globalThis as typeof globalThis & { __ABM_ROBUSTNESS_V2_FORCE_ERROR__?: boolean })
      .__ABM_ROBUSTNESS_V2_FORCE_ERROR__ = true;
  });
  await failedPage.goto(reportUrl);
  const failedReport = failedPage.getByTestId('robustness-v2-report');
  await expect(failedReport).toHaveAttribute('data-v2-state', 'error');
  await expect(failedPage.getByTestId('robustness-v2-state')).toContainText('failed closed');
  await expect(failedReport.locator('[data-v2-view-button="judgment"]')).toBeDisabled();
  await expect(failedPage.getByTestId('robustness-v2-realized-view')).toBeHidden();
  await expect(failedPage.getByTestId('robustness-v2-judgment-view')).toBeHidden();

  await context.close();
});
