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
  'concurrent-robustness': [
    'artifact_manifest.json',
    'concurrent_robustness_report_payload.json',
    'robustness_production_release_evidence.json',
    'ranking_weight_sensitivity.json',
    'prompt_model_analysis.json',
    'ranking_weight_message_summary.csv',
    'prompt_model_message_summary.csv',
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
    for (let attempt = 1; attempt <= 4; attempt += 1) {
      let response;
      try {
        response = await request.head(`${publicUrl}/${artifact}`, { timeout: 30_000 });
      } catch (error) {
        if (attempt === 4) throw error;
        await new Promise((resolve) => setTimeout(resolve, 2_000));
        continue;
      }
      try {
        expect(response.ok(), artifact).toBeTruthy();
      } finally {
        await response.dispose();
      }
      break;
    }
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

async function expectEditorialReport(page: Page): Promise<void> {
  const root = page.getByTestId('editorial-report');
  await expect(root).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
  await expect(root).toHaveAttribute('data-report-mode', 'mechanism');
  await expect(root).toHaveAttribute('data-report-language', 'zh-CN');
  await expect(root).toHaveAttribute('data-editorial-version', 'v3');
  await expect(page.getByTestId('mechanism-mode-panel')).toBeVisible();
  for (const anchor of ['overview', 'sample', 'exposure-ranking', 'llm-decision', 'network-feedback']) {
    await expect(page.locator(`[data-report-anchor="${anchor}"]`)).toHaveAttribute('href', `#${anchor}`);
    await expect(page.locator(`[data-report-mode-panel="mechanism"] [data-section-anchor="${anchor}"]`)).toBeAttached();
  }
  await expect(page.getByTestId('mechanism-sample-size')).toContainText('1,000');
  await expect(page.getByTestId('mechanism-eligible-pairs')).toContainText('3,000');
  await expect(page.locator('[data-legend-item="ranking-cross-message-overlap"]')).toHaveCount(1);
  await expect(page.locator('[data-legend-item="ranking-cross-message-overlap"] .editorial-mark-overlap-three')).toBeVisible();
  await expect(page.getByTestId('mechanism-exposure-ranking-section')).toContainText('任意两条或全部三条 queue');
  await expect(page.locator('[data-legend-item="feedback-engaged-user-dedup"] .editorial-mark-dedup-three')).toBeVisible();
  await expect(page.locator('[data-legend-item="feedback-next-batch-reranking"] .editorial-mark-shared-context')).toBeVisible();
  await expect(page.getByTestId('mechanism-network-feedback-section')).toContainText('不把用户直接注入任何 queue');

  await page.getByRole('button', { name: 'English', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-US');
  await expect(root).toHaveAttribute('data-report-language', 'en-US');
  await expect(page.locator('[data-legend-item="ranking-cross-message-overlap"]')).toContainText('any two or all three queues');
  await expect(page.getByTestId('mechanism-network-feedback-section')).toContainText('does not inject those users into any queue');
  await page.getByRole('button', { name: '中文', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
  await expect(root).toHaveAttribute('data-report-language', 'zh-CN');

  await page.getByTestId('run-evidence-mode-button').click();
  await expect(page.getByTestId('run-evidence-mode-panel')).toBeVisible();
  await expect(page.getByTestId('run-formal-status')).toContainText('Formal');
  await expect(page.getByTestId('run-sample-users')).toContainText('1,000');
  await expect(page.getByTestId('run-eligible-pairs')).toContainText('3,000');
  await expect(page.getByTestId('run-actual-exposures')).toContainText('1,800');
  await expect(page.getByTestId('run-coverage-sequence')).toBeVisible();

  await expect(page.getByTestId('run-trace-tool')).toBeVisible();
  await expect(page.getByTestId('run-trace-search')).toBeVisible();
  await expect(page.getByTestId('run-trace-message-select')).toBeVisible();
  const firstTraceRow = page.getByTestId('run-trace-table-body').locator('tr').first();
  await expect(firstTraceRow).toBeVisible();
  await firstTraceRow.click();
  const drawer = page.getByTestId('evidence-drawer');
  await expect(drawer).toBeVisible();
  await page.getByTestId('editorial-drawer-close').click();
  await expect(drawer).toBeHidden();

  await expect(page.getByTestId('run-downloads-section')).toBeVisible();
  for (const group of ['report', 'sample-users', 'decision', 'runtime-diagnostics']) {
    await expect(page.getByTestId(`run-download-group-${group}`)).toBeVisible();
  }
}

async function expectConcurrentMessageReport(page: Page): Promise<void> {
  if (await page.getByTestId('editorial-report').count()) {
    await expectEditorialReport(page);
    return;
  }

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

async function expectConcurrentRobustnessReport(page: Page): Promise<void> {
  await expectConcurrentMessageReport(page);
  const root = page.getByTestId('robustness-report-release');
  await expect(root).toBeVisible();
  await expect(page.getByTestId('robustness-production-eligibility')).toHaveText(
    'production_deploy_eligible=true',
  );
  await expect(page.getByTestId('robustness-source-lineage')).toBeVisible();
  await expect(page.getByTestId('robustness-shadow-source-label')).toContainText(
    'Demographic Shadow evidence remains bound to the historical Formal source',
  );
  await expect(page.getByTestId('ranking-weight-sensitivity-section')).toBeVisible();
  await expect(page.getByTestId('ranking-weight-family-select')).toBeVisible();
  await expect(page.getByTestId('prompt-model-robustness-section')).toBeVisible();
  await expect(page.getByTestId('prompt-model-message-select')).toBeVisible();
  await expect(page.getByTestId('prompt-model-metric-select')).toBeVisible();
  await expect(page.getByTestId('prompt-model-growth-panels')).toBeVisible();
  await expect(page.getByTestId('practical-threshold-summary')).toBeVisible();
  await expect(page.getByTestId('robustness-downloads-section')).toBeVisible();
}

async function expectReportByKind(page: Page): Promise<void> {
  if (reportKind === 'concurrent-robustness') {
    await expectConcurrentRobustnessReport(page);
  } else if (reportKind === 'concurrent-message') {
    await expectConcurrentMessageReport(page);
  } else {
    await expectFinalResearchReport(page);
  }
}

test.describe('deployed Seed-First report', () => {
  test.skip(!publicUrl, 'ABM_DEPLOY_PUBLIC_URL is required for explicit public deployment acceptance');

  test('serves the approved report and artifacts without responsive errors', async ({ page, request }) => {
    test.setTimeout(300_000);
    const consoleErrors: string[] = [];
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });
    page.on('pageerror', (error) => consoleErrors.push(error.message));

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(`${publicUrl}/`, { waitUntil: 'domcontentloaded', timeout: 150_000 });
    await expectReportByKind(page);
    await expectNoHorizontalOverflow(page);
    await expectArtifactHeads(request);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${publicUrl}/`, { waitUntil: 'domcontentloaded', timeout: 150_000 });
    await expectReportByKind(page);
    await expectNoHorizontalOverflow(page);

    expect(consoleErrors).toEqual([]);
  });
});
