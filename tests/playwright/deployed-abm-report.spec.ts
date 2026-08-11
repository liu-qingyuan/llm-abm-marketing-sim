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

async function expectRobustnessWeightFamily(page: Page, familyId: string): Promise<void> {
  await expect(page.getByTestId('ranking-weight-family-select')).toHaveValue(familyId);
  await expect(page.locator(`[data-weight-family="${familyId}"]:visible`)).toHaveCount(3);
  for (const otherFamily of ['network-feedback', 'network-fit', 'feedback-fit'].filter(
    (value) => value !== familyId,
  )) {
    await expect(page.locator(`[data-weight-family="${otherFamily}"]:visible`)).toHaveCount(0);
  }
  const panels = page.locator('.robustness-weight-family:visible');
  await expect(panels).toHaveCount(3);
  for (let index = 0; index < 3; index += 1) {
    await expect(panels.nth(index).locator('svg .robustness-series > g:visible')).toHaveCount(6);
    await expect(panels.nth(index).locator('.robustness-legend-item:visible')).toHaveCount(6);
  }
}

async function expectRobustnessPromptView(
  page: Page,
  messageId: string,
  metricId: string,
): Promise<void> {
  await expect(page.locator('[data-prompt-view]:visible')).toHaveCount(1);
  const view = page.locator(`[data-prompt-view="${messageId}|${metricId}"]`);
  await expect(view).toBeVisible();
  await expect(view.locator('.robustness-model-panel')).toHaveCount(4);
  for (let index = 0; index < 4; index += 1) {
    const panel = view.locator('.robustness-model-panel').nth(index);
    await expect(panel.locator('svg .robustness-series > g:visible')).toHaveCount(4);
    await expect(panel.locator('.robustness-legend-item:visible')).toHaveCount(4);
  }
  const sharedRows = page.getByTestId('shared-seed-exact-table').locator('tbody tr:visible');
  await expect(sharedRows).toHaveCount(16);
  expect(
    await sharedRows.evaluateAll((rows) => rows.map((row) => row.getAttribute('data-row-message-id'))),
  ).toEqual(Array(16).fill(messageId));
}

async function expectConcurrentRobustnessInteractions(page: Page): Promise<void> {
  const familySelect = page.getByTestId('ranking-weight-family-select');
  for (const familyId of ['network-feedback', 'network-fit', 'feedback-fit', 'network-feedback']) {
    await familySelect.selectOption(familyId);
    await expectRobustnessWeightFamily(page, familyId);
  }
  await familySelect.focus();
  await familySelect.pressSequentially('Campaign');
  await expectRobustnessWeightFamily(page, 'feedback-fit');

  const messageSelect = page.getByTestId('prompt-model-message-select');
  const metricSelect = page.getByTestId('prompt-model-metric-select');
  for (const messageId of ['message_1', 'message_2', 'message_3']) {
    await messageSelect.selectOption(messageId);
    for (const metricId of ['engagement', 'audience']) {
      await metricSelect.selectOption(metricId);
      await expectRobustnessPromptView(page, messageId, metricId);
    }
  }
  await messageSelect.selectOption('message_1');
  await metricSelect.selectOption('engagement');
  await messageSelect.focus();
  await messageSelect.pressSequentially('message_2');
  await expectRobustnessPromptView(page, 'message_2', 'engagement');
  await metricSelect.focus();
  await metricSelect.pressSequentially('Audience');
  await expectRobustnessPromptView(page, 'message_2', 'audience');
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
  await expectConcurrentRobustnessInteractions(page);
}

async function expectRobustnessDownloadHeads(
  page: Page,
  request: APIRequestContext,
): Promise<void> {
  if (!publicUrl) throw new Error('ABM_DEPLOY_PUBLIC_URL is required');
  const publicOrigin = new URL(publicUrl).origin;
  const hrefs = await page.getByTestId('robustness-downloads-section').getByRole('link').evaluateAll(
    (links) => links.map((link) => link.getAttribute('href') ?? ''),
  );
  expect(hrefs.length).toBeGreaterThan(10);
  for (const href of hrefs) {
    expect(href.length > 0 && !href.startsWith('/') && !href.includes('..'), href).toBeTruthy();
    const target = new URL(href, `${publicUrl}/`);
    expect(target.origin, href).toBe(publicOrigin);
    const response = await request.head(target.toString(), { timeout: 30_000 });
    try {
      expect(response.ok(), href).toBeTruthy();
    } finally {
      await response.dispose();
    }
  }
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
    const thirdPartyRequests: string[] = [];
    const publicOrigin = new URL(publicUrl ?? 'https://invalid.local').origin;
    page.on('request', (observedRequest) => {
      const target = new URL(observedRequest.url());
      if (target.protocol !== 'data:' && target.origin !== publicOrigin) {
        thirdPartyRequests.push(observedRequest.url());
      }
    });
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });
    page.on('pageerror', (error) => consoleErrors.push(error.message));

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(`${publicUrl}/`, { waitUntil: 'domcontentloaded', timeout: 150_000 });
    await expectReportByKind(page);
    await expectNoHorizontalOverflow(page);
    await expectArtifactHeads(request);
    if (reportKind === 'concurrent-robustness') {
      await expectRobustnessDownloadHeads(page, request);
    }

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${publicUrl}/`, { waitUntil: 'domcontentloaded', timeout: 150_000 });
    await expectReportByKind(page);
    await expectNoHorizontalOverflow(page);

    expect(consoleErrors).toEqual([]);
    expect(thirdPartyRequests).toEqual([]);
  });
});
