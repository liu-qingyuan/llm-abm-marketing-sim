import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const publicUrl = process.env.ABM_DEPLOY_PUBLIC_URL;
const reportKind = process.env.ABM_DEPLOY_REPORT_KIND ?? 'final-research';
const artifactPaths = (() => {
  const raw = process.env.ABM_DEPLOY_PUBLIC_ARTIFACTS;
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.map(String) : null;
  } catch {
    return null;
  }
})();

const fallbackArtifactsByKind: Record<string, string[]> = {
  'final-research': [
    'artifact_manifest.json',
    'final_research_report_payload.json',
    'final_research_users.csv',
    'seed_first_sample_audit.json',
    'field_lineage_catalog.json',
    'user_field_trace.json',
  ],
  'concurrent-message': [
    'artifact_manifest.json',
    'concurrent_message_report_payload.json',
    'concurrent_message_users.json',
    'concurrent_validation.json',
    'concurrent_campaign_diagnostics.json',
    'seed_first_sample_audit.json',
  ],
};

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  );
  expect(hasHorizontalOverflow).toBeFalsy();
}

async function expectArtifactHeads(request: APIRequestContext): Promise<void> {
  const artifacts = artifactPaths ?? fallbackArtifactsByKind[reportKind] ?? fallbackArtifactsByKind['final-research'];
  for (const artifact of artifacts) {
    const response = await request.head(`${publicUrl}/${artifact}`);
    expect(response.ok(), artifact).toBeTruthy();
  }
}

async function expectFinalResearchReport(page: Page): Promise<void> {
  await expect(page).toHaveTitle('锦江酒店 Target Delivery Ranking Research Report');
  await expect(page.getByTestId('final-research-ranking-report')).toBeVisible();
  await expect(page.locator('#network-feedback')).toBeAttached();

  const runEvidenceButton = page.getByTestId('run-evidence-mode-button');
  if ((await runEvidenceButton.getAttribute('aria-selected')) !== 'true') await runEvidenceButton.click();
  await expect(page.getByTestId('sample-comparison-section')).toContainText('Seed-First Research Sample');
  await expect(page.getByTestId('run-evidence-method-status')).toContainText('Persisted Seed-First Formal Run');
}

async function expectConcurrentMessageReport(page: Page): Promise<void> {
  await expect(page.getByTestId('concurrent-message-report')).toBeVisible();
  await expect(page.getByTestId('mechanism-mode-panel')).toBeVisible();
  for (const anchor of ['overview', 'sample', 'exposure-ranking', 'llm-decision', 'network-feedback']) {
    await expect(page.locator(`[data-report-anchor="${anchor}"]`)).toHaveAttribute('href', `#${anchor}`);
  }
  const runEvidenceButton = page.getByTestId('run-evidence-mode-button');
  if ((await runEvidenceButton.getAttribute('aria-selected')) !== 'true') await runEvidenceButton.click();
  await expect(page.getByTestId('run-evidence-mode-panel')).toBeVisible();
  await expect(page.getByTestId('validation-status')).toContainText('Persisted Seed-First Formal Run');
  for (const testId of [
    'messages-section',
    'campaign-funnel-section',
    'message-allocation-section',
    'primary-audience-response-section',
    'campaign-feedback-effect-section',
    'demographic-decision-sensitivity-section',
    'decision-trace-section',
    'downloads-section',
  ]) {
    await expect(page.getByTestId(testId)).toBeVisible();
  }
  await expect(page.getByTestId('downloads-section')).toContainText('Safe downloads');
  const firstTraceRow = page.getByTestId('decision-trace-table').locator('tbody tr').first();
  await expect(firstTraceRow).toBeVisible();
  await firstTraceRow.click();
  const drawer = page.getByTestId('trace-drawer');
  await expect(drawer).toBeVisible();
  await drawer.getByRole('button', { name: 'Close trace detail' }).click();
  await expect(drawer).toBeHidden();
}

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
    if (reportKind === 'concurrent-message') {
      await expectConcurrentMessageReport(page);
    } else {
      await expectFinalResearchReport(page);
    }
    await expectNoHorizontalOverflow(page);
    await expectArtifactHeads(request);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${publicUrl}/`, { waitUntil: 'domcontentloaded', timeout: 150_000 });
    if (reportKind === 'concurrent-message') {
      await expectConcurrentMessageReport(page);
    } else {
      await expectFinalResearchReport(page);
    }
    await expectNoHorizontalOverflow(page);

    expect(consoleErrors).toEqual([]);
  });
});
