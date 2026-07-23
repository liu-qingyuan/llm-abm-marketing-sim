import { expect, test } from '@playwright/test';

const publicUrl = process.env.ABM_DEPLOY_PUBLIC_URL;

test.describe('deployed Seed-First report', () => {
  test.skip(!publicUrl, 'ABM_DEPLOY_PUBLIC_URL is required for explicit public deployment acceptance');

  test('serves the approved report and artifacts without responsive errors', async ({ page, request }) => {
    test.setTimeout(180_000);
    const consoleErrors: string[] = [];
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });
    page.on('pageerror', (error) => consoleErrors.push(error.message));
    await page.setViewportSize({ width: 1440, height: 1000 });

    await page.goto(`${publicUrl}/`, { waitUntil: 'domcontentloaded', timeout: 150_000 });
    await expect(page).toHaveTitle('锦江酒店 Target Delivery Ranking Research Report');
    await expect(page.getByTestId('final-research-ranking-report')).toBeVisible();
    await expect(page.locator('#network-feedback')).toBeAttached();

    await page.getByTestId('run-evidence-mode-button').click();
    await expect(page.getByTestId('sample-comparison-section')).toContainText('Seed-First Research Sample');
    await expect(page.getByTestId('run-evidence-method-status')).toContainText('Persisted Seed-First Formal Run');

    const hasHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    );
    expect(hasHorizontalOverflow).toBeFalsy();

    for (const artifact of [
      'artifact_manifest.json',
      'final_research_report_payload.json',
      'final_research_users.csv',
      'seed_first_sample_audit.json',
      'field_lineage_catalog.json',
      'user_field_trace.json',
    ]) {
      const response = await request.head(`${publicUrl}/${artifact}`);
      expect(response.ok(), artifact).toBeTruthy();
    }

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${publicUrl}/`, { waitUntil: 'domcontentloaded', timeout: 150_000 });
    const runEvidenceButton = page.getByTestId('run-evidence-mode-button');
    if ((await runEvidenceButton.getAttribute('aria-selected')) !== 'true') await runEvidenceButton.click();
    await expect(page.getByTestId('final-research-ranking-report')).toBeVisible();
    await expect(page.getByTestId('run-evidence-method-status')).toContainText('Persisted Seed-First Formal Run');
    const hasMobileHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    );
    expect(hasMobileHorizontalOverflow).toBeFalsy();

    expect(consoleErrors).toEqual([]);
  });
});
