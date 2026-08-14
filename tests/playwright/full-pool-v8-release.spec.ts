import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
import { existsSync } from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';

function generateV8Release(outputDir: string): string {
  const root = path.join(outputDir, 'full-pool-v8-fixture');
  const command = `
set -euo pipefail
. .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD"
python - <<'PY'
from pathlib import Path
from llm_abm_sim import concurrent_robustness_release as release
from tests.integration.test_full_pool_v8_release import (
    _closed_candidate,
    _injected_formal_facts,
)

root = Path(${JSON.stringify(root)}).resolve()
root.mkdir(parents=True, exist_ok=True)
inputs = _closed_candidate(root)
release.promote_concurrent_robustness_release(
    repo_root=root,
    formal_root=inputs['historical_formal'],
    study_root=inputs['historical_study'],
    workspace_root=None,
    candidate_dir=inputs['candidate'],
    execution_contract_path=None,
    destination_dir=root / 'production-v8',
    release_contract_path=root / 'release-contract-v8.json',
    release_id='full-pool-v8-playwright',
    presentation_closure_path=inputs['closure_path'],
    full_pool_source_root=inputs['source'],
    full_pool_manifest_sha256=inputs['source_hash'],
    implementation_commit='abcdef0',
    _closed_full_pool_formal_facts=_injected_formal_facts(inputs),
)
PY`;
  execFileSync('bash', ['-lc', command], { stdio: 'inherit' });
  return path.join(root, 'production-v8');
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
      server.close((error) => (error ? reject(error) : resolve(address.port)));
    });
  });
}

async function serve(root: string): Promise<{ baseURL: string; server: ChildProcess }> {
  const port = await availablePort();
  const server = spawn(
    'python3',
    ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '--directory', root],
    { stdio: ['ignore', 'ignore', 'pipe'] },
  );
  return { baseURL: `http://127.0.0.1:${port}`, server };
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  await expect.poll(async () => page.evaluate(() => (
    document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1
  ))).toBe(true);
}

test('v8 local production release stays healthy on desktop and mobile', async ({ page, request }, testInfo) => {
  test.setTimeout(180_000);
  const releaseDir = generateV8Release(testInfo.outputDir);
  const { baseURL, server } = await serve(releaseDir);
  const thirdPartyRequests: string[] = [];
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  page.on('request', (observed) => {
    if (new URL(observed.url()).origin !== baseURL) thirdPartyRequests.push(observed.url());
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

    const report = page.getByTestId('full-pool-presentation');
    await expect(report).toHaveAttribute('data-production-deploy-eligible', 'true');
    await expect(page.getByTestId('full-pool-run-evidence')).toContainText('36,400');
    await expect(page.getByTestId('historical-sensitivity-1000')).toContainText(
      'Historical Sensitivity · 1,000 users',
    );
    await expect(page.getByTestId('full-pool-trace-state')).toHaveAttribute(
      'data-trace-state',
      'ready',
    );
    await expect(page.getByTestId('full-pool-trace-table-body').locator('tr')).toHaveCount(3);
    await expectNoHorizontalOverflow(page);

    const mermaidHrefs = await page.locator('a[href$=".mmd"]').evaluateAll((links) =>
      links.map((link) => (link as HTMLAnchorElement).getAttribute('href') ?? ''),
    );
    expect(new Set(mermaidHrefs).size).toBe(8);
    expect(mermaidHrefs.every((href) => existsSync(path.join(releaseDir, href)))).toBe(true);

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByTestId('full-pool-main-experiment')).toBeVisible();
    await expect(page.getByTestId('full-pool-trace-reader')).toBeVisible();
    await expectNoHorizontalOverflow(page);

    expect(thirdPartyRequests).toEqual([]);
    expect(consoleErrors).toEqual([]);
    expect(pageErrors).toEqual([]);
  } finally {
    if (!server.killed) server.kill('SIGTERM');
  }
});
