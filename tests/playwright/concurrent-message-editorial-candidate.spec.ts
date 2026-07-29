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
