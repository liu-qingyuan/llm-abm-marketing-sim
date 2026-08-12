import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { expect, test, type Locator, type Page } from '@playwright/test';

type RobustnessFixture = {
  candidateDir: string;
  productionDir: string;
};

function generateRobustnessFixture(outputDir: string): RobustnessFixture {
  const root = path.join(outputDir, 'robustness-fixture');
  const command = `
set -euo pipefail
. .venv/bin/activate
python - <<'PY'
from pathlib import Path
from unittest.mock import patch

from llm_abm_sim import ConcurrentRobustnessStudy
from llm_abm_sim import concurrent_robustness_release as release
from tests.integration.test_concurrent_message_experiment_runner import (
    _install_deterministic_robustness_cell_fixture,
    _make_validation_report_source,
    _robustness_manifest_for_source,
)
from tests.unit.test_concurrent_robustness_release import (
    _FakeCellEvidenceModel,
    _fake_manifest,
    _write_json,
)

root = Path(${JSON.stringify(root)}).resolve()
root.mkdir(parents=True, exist_ok=True)
formal = _make_validation_report_source(root, 'formal-source')
manifest = _robustness_manifest_for_source(formal, output_identity='browser-report-fixture-v1')
workspace = root / 'workspace'
candidate = root / 'candidate'
study = ConcurrentRobustnessStudy()
study.run(manifest, None, workspace)
_install_deterministic_robustness_cell_fixture(workspace, manifest)
complete = study.run(manifest, None, workspace)
assert complete.study_root is not None
published = study.run(manifest, None, workspace, report_destination=candidate)
assert published.report_candidate == candidate

contracts = root / 'contracts'
contracts.mkdir()
execution_contract = contracts / 'formal-run-contract.json'
_write_json(execution_contract, {'fixture': True})
fake_manifest = _fake_manifest(formal)
fake_manifest.source.manifest_sha256 = manifest.source.manifest_sha256

class FakeManifestModel:
    @staticmethod
    def model_validate(_payload):
        return fake_manifest

    @staticmethod
    def model_validate_json(_payload):
        return fake_manifest

execution_document = {
    'implementation_commit': '1234567',
    'closure_implementation_commit': '7654321',
    'closure_replay_sha256': 'e' * 64,
    'physical_provider_attempts': 28_800,
    'subscription_nominal_reference_cost_usd': 1.25,
    'subscription_billed_cost_usd': 0.0,
}
with (
    patch.object(release, 'ConcurrentRobustnessManifest', FakeManifestModel),
    patch.object(release, '_CellEvidenceDocument', _FakeCellEvidenceModel),
    patch.object(release, '_validate_cell_evidence_contract', lambda *_args, **_kwargs: None),
    patch.object(release, '_validate_completed_dynamic_root', lambda **_kwargs: None),
    patch.object(release, '_validate_execution_contract', lambda **_kwargs: execution_document),
):
    release.promote_concurrent_robustness_release(
        repo_root=root,
        formal_root=formal,
        study_root=complete.study_root,
        workspace_root=workspace,
        candidate_dir=candidate,
        execution_contract_path=execution_contract,
        destination_dir=root / 'production-release',
        release_contract_path=contracts / 'production-release.json',
        release_id='browser-production-release-v1',
    )
PY`;
  execFileSync('bash', ['-lc', command], { stdio: 'inherit' });
  return {
    candidateDir: path.join(root, 'candidate'),
    productionDir: path.join(root, 'production-release'),
  };
}

async function expectWeightFamily(page: Page, familyId: string): Promise<void> {
  const families = ['network-feedback', 'network-fit', 'feedback-fit'];
  await expect(page.getByTestId('ranking-weight-family-select')).toHaveValue(familyId);
  await expect(page.locator(`[data-weight-family="${familyId}"]:visible`)).toHaveCount(3);
  for (const otherFamily of families.filter((value) => value !== familyId)) {
    await expect(page.locator(`[data-weight-family="${otherFamily}"]:visible`)).toHaveCount(0);
  }
  const visibleFamilies = page.locator('.robustness-weight-family:visible');
  await expect(visibleFamilies).toHaveCount(3);
  for (let index = 0; index < 3; index += 1) {
    const family = visibleFamilies.nth(index);
    await expect(family.locator('svg .robustness-series > g:visible')).toHaveCount(6);
    await expect(family.locator('.robustness-legend-item:visible')).toHaveCount(6);
  }
}

async function expectPromptView(page: Page, messageId: string, metricId: string): Promise<void> {
  await expect(page.locator('[data-prompt-view]:visible')).toHaveCount(1);
  const view = page.locator(`[data-prompt-view="${messageId}|${metricId}"]`);
  await expect(view).toBeVisible();
  await expect(view.locator('.robustness-model-panel')).toHaveCount(4);
  for (let index = 0; index < 4; index += 1) {
    const panel = view.locator('.robustness-model-panel').nth(index);
    const series = panel.locator('svg .robustness-series > g:visible');
    const legends = panel.locator('.robustness-legend-item:visible');
    await expect(series).toHaveCount(4);
    await expect(legends).toHaveCount(4);
    const expectedDisclosureIds = [
      'prompt-contract-row-p0',
      'prompt-contract-row-p1',
      'prompt-contract-row-p2',
      'prompt-contract-row-p3',
    ];
    expect(await series.evaluateAll((rows) => rows.map((row) => row.getAttribute('data-prompt-disclosure-id')))).toEqual(
      expectedDisclosureIds,
    );
    expect(await legends.evaluateAll((rows) => rows.map((row) => row.getAttribute('data-prompt-disclosure-id')))).toEqual(
      expectedDisclosureIds,
    );
  }
  const sharedRows = page.getByTestId('shared-seed-exact-table').locator('tbody tr:visible');
  await expect(sharedRows).toHaveCount(16);
  expect(await sharedRows.evaluateAll((rows) => rows.map((row) => row.getAttribute('data-row-message-id')))).toEqual(
    Array(16).fill(messageId),
  );
}

async function expectSemanticEdge(
  diagram: Locator,
  edgeId: string,
  expected: {
    from: string;
    to: string;
    condition: string;
    timing: string;
    effect: string;
    provenance: string;
  },
): Promise<void> {
  const edge = diagram.locator(`[data-diagram-edge-id="${edgeId}"]`);
  await expect(edge).toHaveCount(1);
  await expect(edge).toHaveAttribute('data-from', expected.from);
  await expect(edge).toHaveAttribute('data-to', expected.to);
  await expect(edge).toHaveAttribute('data-direction', /^(forward|reverse)$/);
  await expect(edge).toHaveAttribute('data-condition', expected.condition);
  await expect(edge).toHaveAttribute('data-timing', expected.timing);
  await expect(edge).toHaveAttribute('data-effect', expected.effect);
  await expect(edge).toHaveAttribute('data-provenance', expected.provenance);
}

async function expectReaderDiagrams(page: Page): Promise<void> {
  const project = page.getByTestId('project-evidence-chain-diagram');
  await expect(project).toBeVisible();
  await expect(project).toHaveAccessibleName('项目证据链');
  await expect(project.locator('[data-diagram-node-id]')).toHaveCount(12);
  await expect(project.locator('[data-diagram-edge-id]')).toHaveCount(14);
  await expectSemanticEdge(project, 'project-edge-kernel-adapter', {
    from: 'Kernel',
    to: 'Adapter',
    condition: 'user_message_pair_exposed',
    timing: 'after_exposure',
    effect: 'create_decision_input',
    provenance: '_ConcurrentRuntimeKernel',
  });
  await expectSemanticEdge(project, 'project-edge-report-release', {
    from: 'Report',
    to: 'Release',
    condition: 'presentation_bundle_valid',
    timing: 'release_closure',
    effect: 'close_inventory_and_hashes',
    provenance: 'abm-report-release-contract-v5',
  });

  const batch = page.getByTestId('batch-mechanism-diagram');
  await expect(batch).toBeVisible();
  await expect(batch).toHaveAccessibleName('Concurrent Message 真实批次机制');
  await expect(batch.locator('[data-diagram-node-id]')).toHaveCount(24);
  await expect(batch.locator('[data-diagram-edge-id]')).toHaveCount(31);
  await expect(batch.locator('[data-diagram-node-id="Rank1"]')).toContainText(/Message 1 独立 Per-Message Top\d+/);
  await expect(batch.locator('[data-diagram-node-id="Rank2"]')).toContainText(/Message 2 独立 Per-Message Top\d+/);
  await expect(batch.locator('[data-diagram-node-id="Rank3"]')).toContainText(/Message 3 独立 Per-Message Top\d+/);
  await expect(batch.locator('[data-diagram-node-id="Exposure"]')).toContainText('每个 user-message pair 最多一次');
  const compatibilityRasters = page.locator('[data-testid$="-visual-media"][aria-hidden="true"]');
  await expect(compatibilityRasters).toHaveCount(5);
  expect(await compatibilityRasters.evaluateAll(
    (images) => images.every((image) => image.getAttribute('alt') === ''),
  )).toBe(true);
  await expect(page.locator('.robustness-compatibility-legend')).toHaveCount(5);
  expect(await page.locator('.robustness-compatibility-legend').evaluateAll(
    (legends) => legends.every((legend) => legend.getAttribute('aria-hidden') === 'true'),
  )).toBe(true);
  await expectSemanticEdge(batch, 'batch-edge-seed-fill', {
    from: 'Seed',
    to: 'Fill',
    condition: 'seed_union_below_delivery_capacity',
    timing: 'batch_zero_before_exposure',
    effect: 'fill_each_message_independently_to_top_k',
    provenance: 'SharedSeedLaunch',
  });
  await expectSemanticEdge(batch, 'batch-edge-rank1-exposure', {
    from: 'Rank1',
    to: 'Exposure',
    condition: 'message_1_top_k_selected',
    timing: 'ranking_before_exposure',
    effect: 'expose_selected_message_1_pairs',
    provenance: 'PlatformEnvironment',
  });
  await expectSemanticEdge(batch, 'batch-edge-historical-terminal', {
    from: 'HistoricalMode',
    to: 'Terminal',
    condition: 'historical_formal_mode',
    timing: 'terminal_closure',
    effect: 'require_primary_and_shadow',
    provenance: 'historical-formal-terminal-contract',
  });
  await expectSemanticEdge(batch, 'batch-edge-robustness-terminal', {
    from: 'RobustnessMode',
    to: 'Terminal',
    condition: 'robustness_cell_mode',
    timing: 'terminal_closure',
    effect: 'require_primary_only',
    provenance: 'primary-only-terminal-contract',
  });
  await expectSemanticEdge(batch, 'batch-edge-exposure-shadow', {
    from: 'Exposure',
    to: 'Shadow',
    condition: 'historical_formal_mode',
    timing: 'after_same_exposure',
    effect: 'request_report_only_shadow',
    provenance: 'DemographicShadowDecision',
  });
  await expectSemanticEdge(batch, 'batch-edge-positive-collect', {
    from: 'Positive',
    to: 'Collect',
    condition: 'action_in_like_comment_share',
    timing: 'pending_set_build',
    effect: 'add_user_id',
    provenance: 'campaign-positive-user-contract',
  });
  await expectSemanticEdge(batch, 'batch-edge-join-commit', {
    from: 'Join',
    to: 'Commit',
    condition: 'barrier_closed_and_pending_set_finalized',
    timing: 'after_full_batch',
    effect: 'commit_campaign_user_set_unique_by_user_id',
    provenance: 'campaign-user-id-deduplication-contract',
  });
  for (const [edgeId, target] of [
    ['batch-edge-commit-next1', 'Next1'],
    ['batch-edge-commit-next2', 'Next2'],
    ['batch-edge-commit-next3', 'Next3'],
  ] as const) {
    await expectSemanticEdge(batch, edgeId, {
      from: 'Commit',
      to: target,
      condition: 'next_batch_exists',
      timing: 'next_batch_before_ranking',
      effect: 'ranking_context_only_no_queue_injection_no_same_batch_writeback',
      provenance: 'CampaignEngagementRankingSignal',
    });
  }
  await expect(batch.locator('[data-from="Shadow"][data-to="Pending"], [data-from="Shadow"][data-to="Commit"]')).toHaveCount(0);
  await expect(batch.locator('[data-from="NoFeedback"][data-to="Commit"]')).toHaveCount(0);
  await expect(batch.locator('[data-from="Commit"][data-to="Rank1"], [data-from="Commit"][data-to="Rank2"], [data-from="Commit"][data-to="Rank3"]')).toHaveCount(0);

  for (const [legendId, diagramId] of [
    ['project-evidence-chain-legend', 'project-evidence-chain-diagram'],
    ['batch-mechanism-legend', 'batch-mechanism-diagram'],
  ] as const) {
    const legend = page.getByTestId(legendId);
    const diagramForLegend = page.getByTestId(diagramId);
    const markIds = await legend.locator('[data-legend-mark-id]').evaluateAll((items) =>
      items.map((item) => item.getAttribute('data-legend-mark-id') ?? ''),
    );
    for (const markId of markIds) {
      await expect(diagramForLegend.locator(`[data-diagram-mark-id="${markId}"]`)).toHaveCount(1);
    }
  }

  for (const testId of ['project-evidence-chain-mermaid-source', 'batch-mechanism-mermaid-source']) {
    const source = page.getByTestId(testId);
    await source.locator('summary').focus();
    await source.locator('summary').press('Enter');
    await expect(source).toHaveAttribute('open', '');
    await expect(source.locator('pre:visible')).toContainText('flowchart TB');
    await expect(source.locator('pre:visible')).toContainText('condition=');
    await source.locator('summary').press('Enter');
  }

  for (const anchor of ['overview', 'sample', 'exposure-ranking', 'llm-decision', 'network-feedback']) {
    await page.evaluate((value) => { window.location.hash = value; }, anchor);
    await expect(page.locator(`[data-section-anchor="${anchor}"]:visible`).first()).toBeFocused();
  }

  const englishButton = page.locator('[data-report-language="en-US"]');
  await englishButton.click();
  await expect(project).toHaveAccessibleName('Project evidence chain');
  await expect(batch).toHaveAccessibleName('Concurrent Message real batch mechanism');
  await expect(project.locator('[data-diagram-node-id="Weight"]')).toContainText('Ranking Weight points');
  await expect(batch.locator('[data-diagram-node-id="Rank1"]')).toContainText(/Message 1 independent Per-Message Top\d+/);
  await expect(page.getByTestId('project-evidence-chain-fallback')).toContainText('Only a post-exposure DecisionInput');
  await expect(page.getByTestId('batch-mechanism-fallback')).toContainText('neither injects users into a queue nor rewrites same-batch ranking');
  await page.locator('[data-report-language="zh-CN"]').click();
}

async function expectPromptContractAndDiagram(page: Page): Promise<void> {
  const disclosure = page.getByTestId('prompt-model-contract-disclosure');
  await expect(disclosure).toBeVisible();
  await expect(disclosure).toContainText('4 Prompt × 4 model = 16 execution cells');
  await expect(disclosure).toContainText('16 cells × 3 messages = 48 message-level reporting slices');
  await expect(disclosure).toContainText('Message 是每个 cell 内的报告维度，不是额外独立运行');

  const expectedContracts = [
    {
      variant: 'P0',
      change: 'baseline',
      token: 'jinjiang-concurrent-message-primary-prompt-v1',
      hash: 'sha256:cc50affc4e658a9a1804f5e1824710cb073003aff3cc6af8f8c5cd8edf5cdc7c',
    },
    {
      variant: 'P1',
      change: 'wording_only',
      token: 'jinjiang-concurrent-message-primary-robustness-p1-v1',
      hash: 'sha256:67b38d5edfc562bf43a115d9a7aaebc856d51049614dc4cc633c431dd57bf0e1',
    },
    {
      variant: 'P2',
      change: 'information_order_only',
      token: 'jinjiang-concurrent-message-primary-robustness-p2-v1',
      hash: 'sha256:6784ecc2163e6b2426631d81672994376c3781791fa265c3e0f67d1428b71cb4',
    },
    {
      variant: 'P3',
      change: 'structured_rubric_only',
      token: 'jinjiang-concurrent-message-primary-robustness-p3-v1',
      hash: 'sha256:a3ac934d194437f6ee86011b92666cf1ea19fb086a383fb7b7407cf5f44bd7ea',
    },
  ];
  for (const contract of expectedContracts) {
    const row = page.getByTestId(`prompt-contract-row-${contract.variant.toLowerCase()}`);
    await expect(row).toHaveAttribute('data-controlled-change', contract.change);
    await expect(row).toHaveAttribute('data-prompt-version', contract.token);
    await expect(row).toHaveAttribute('data-prompt-canonical-hash', contract.hash);
    const hashDisclosure = row.locator('details');
    await hashDisclosure.locator('summary').focus();
    await hashDisclosure.locator('summary').press('Enter');
    await expect(hashDisclosure).toHaveAttribute('open', '');
    await expect(hashDisclosure.locator('code')).toHaveText(contract.hash);
  }

  const sharedContract = page.getByTestId('prompt-model-shared-contract');
  await sharedContract.locator('summary').focus();
  await sharedContract.locator('summary').press('Enter');
  await expect(sharedContract).toHaveAttribute('open', '');
  await expect(sharedContract).toContainText('engage / probability / reason / confidence / action');
  await expect(sharedContract).toContainText('engage=false => action=ignore');

  const diagram = page.getByTestId('prompt-model-factorial-diagram');
  await expect(diagram).toBeVisible();
  await expect(diagram).toHaveAccessibleName('Prompt-Model factorial 设计');
  await expect(diagram.locator('[data-diagram-node-id]')).toHaveCount(14);
  await expect(diagram.locator('[data-diagram-edge-id]')).toHaveCount(17);
  await expect(diagram).toContainText('每 cell 60 个 Primary judgments');
  await expect(diagram).toContainText('960 个 logical judgments');
  await expect(diagram).toContainText('每 cell 一条 2-batch realized path');
  await expect(page.getByTestId('prompt-model-factorial-fallback')).toContainText('message 不是额外运行');
  const diagramScroller = page.locator('.robustness-factorial-scroll');
  await diagramScroller.focus();
  await expect(diagramScroller).toBeFocused();

  const mermaid = page.getByTestId('prompt-model-factorial-mermaid-source');
  await mermaid.locator('summary').focus();
  await mermaid.locator('summary').press('Enter');
  await expect(mermaid).toHaveAttribute('open', '');
  await expect(mermaid.locator('pre:visible')).toContainText('flowchart TB');
  await expect(mermaid.locator('pre:visible')).toContainText('Contract edge_contract_p0@--> P0');
  const svgEdgeIds = await diagram.locator('[data-diagram-edge-id]').evaluateAll(
    (edges) => edges.map((edge) => edge.getAttribute('data-diagram-edge-id') ?? ''),
  );
  const mermaidSource = await mermaid.locator('pre:visible').innerText();
  expect(svgEdgeIds.every((edgeId) => mermaidSource.includes(`${edgeId}@-->`))).toBe(true);
  await expect(page.locator('script[src*="mermaid"], link[href*="mermaid"]')).toHaveCount(0);

  const englishButton = page.locator('[data-report-language="en-US"]');
  await englishButton.focus();
  await englishButton.press('Enter');
  await expect(disclosure).toContainText('Message is a reporting dimension inside each cell');
  await expect(diagram).toHaveAccessibleName('Prompt-Model factorial design');
  await expect(mermaid.locator('pre:visible')).toContainText('Same declared fields');
  await page.locator('[data-report-language="zh-CN"]').click();
  await expect(diagram).toHaveAccessibleName('Prompt-Model factorial 设计');
}

async function exerciseRobustnessInteractions(page: Page): Promise<void> {
  const familySelect = page.getByTestId('ranking-weight-family-select');
  for (const familyId of ['network-feedback', 'network-fit', 'feedback-fit', 'network-feedback']) {
    await familySelect.selectOption(familyId);
    await expectWeightFamily(page, familyId);
  }
  await familySelect.focus();
  await expect(familySelect).toBeFocused();
  await familySelect.pressSequentially('Campaign');
  await expectWeightFamily(page, 'feedback-fit');
  await familySelect.selectOption('network-feedback');

  const firstFamily = page.locator('.robustness-weight-family:visible').first();
  const encodingCount = await firstFamily.locator('svg .robustness-series > g').evaluateAll((groups) =>
    new Set(groups.map((group) => {
      const line = group.querySelector('polyline');
      const marker = group.querySelector('circle, rect, polygon, path');
      return `${line?.getAttribute('stroke')}|${line?.getAttribute('stroke-dasharray') ?? 'solid'}|${marker?.tagName}`;
    })).size,
  );
  expect(encodingCount).toBe(6);

  const messageSelect = page.getByTestId('prompt-model-message-select');
  const metricSelect = page.getByTestId('prompt-model-metric-select');
  for (const messageId of ['message_1', 'message_2', 'message_3']) {
    await messageSelect.selectOption(messageId);
    for (const metricId of ['engagement', 'audience']) {
      await metricSelect.selectOption(metricId);
      await expectPromptView(page, messageId, metricId);
    }
  }
  await messageSelect.selectOption('message_1');
  await metricSelect.selectOption('engagement');
  await messageSelect.focus();
  await expect(messageSelect).toBeFocused();
  await messageSelect.pressSequentially('message_2');
  await expectPromptView(page, 'message_2', 'engagement');
  await metricSelect.focus();
  await expect(metricSelect).toBeFocused();
  await metricSelect.pressSequentially('Audience');
  await expectPromptView(page, 'message_2', 'audience');

  const growthPanels = page.getByTestId('prompt-model-growth-panels').locator('.robustness-model-panel');
  await expect(growthPanels).toHaveCount(4);
  for (let index = 0; index < 4; index += 1) {
    const panel = growthPanels.nth(index);
    const expectedDisclosureIds = [
      'prompt-contract-row-p0',
      'prompt-contract-row-p1',
      'prompt-contract-row-p2',
      'prompt-contract-row-p3',
    ];
    await expect(panel.locator('svg .robustness-series > g:visible')).toHaveCount(4);
    expect(await panel.locator('.robustness-legend-item').evaluateAll(
      (rows) => rows.map((row) => row.getAttribute('data-prompt-disclosure-id')),
    )).toEqual(expectedDisclosureIds);
  }
  await expect(page.getByTestId('practical-threshold-summary')).toContainText('small_observed_difference');
}

test('candidate and promoted production keep closed downloads, full controls, and responsive keyboard behavior', async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  const fixture = generateRobustnessFixture(testInfo.outputDir);
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
  await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'reduce' });

  for (const stage of [
    { directory: fixture.candidateDir, rootTestId: 'robustness-report-candidate', eligible: 'false' },
    { directory: fixture.productionDir, rootTestId: 'robustness-report-release', eligible: 'true' },
  ]) {
    for (const viewport of [
      { width: 1440, height: 1000 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      await page.goto(pathToFileURL(path.join(stage.directory, 'report.html')).toString());

      await expect(page.getByTestId('mechanism-overview-section')).toBeVisible();
      await expect(page.getByTestId('run-evidence-mode-panel')).toBeHidden();
      await expect(page.getByTestId('run-trace-lineage-data')).toHaveCount(1);
      await expect(page.getByTestId('mechanism-primary-boundary')).toBeVisible();
      await expect(page.getByTestId('mechanism-shadow-boundary')).toBeVisible();

      const robustness = page.getByTestId(stage.rootTestId);
      await robustness.scrollIntoViewIfNeeded();
      await expect(robustness).toBeVisible();
      await expect(page.getByTestId('robustness-source-lineage')).toContainText('Historical Concurrent Formal source');
      await expect(page.getByTestId('robustness-source-lineage')).toContainText('Immutable complete study root');
      await expect(page.getByTestId('robustness-shadow-source-label')).toContainText('not a factorial Prompt–Model result');
      await expect(page.getByTestId('robustness-production-eligibility')).toHaveText(
        `production_deploy_eligible=${stage.eligible}`,
      );

      await expectReaderDiagrams(page);
      await expectPromptContractAndDiagram(page);
      await exerciseRobustnessInteractions(page);

      const visibleMappingFailures = await page.locator('.robustness-chart-shell:visible').evaluateAll((shells) =>
        shells.flatMap((shell) => [...shell.querySelectorAll<HTMLElement>('[data-legend-series-id]')]
          .filter((legend) => {
            const id = legend.dataset.legendSeriesId;
            const series = [...shell.querySelectorAll<SVGGElement>('svg g[data-series-id]')]
              .find((group) => group.dataset.seriesId === id);
            return !series || getComputedStyle(series).display === 'none';
          })
          .map((legend) => legend.dataset.legendSeriesId ?? 'missing')),
      );
      expect(visibleMappingFailures).toEqual([]);

      const rankingDisclosure = page.getByTestId('ranking-weight-exact-table');
      await rankingDisclosure.locator('summary').focus();
      await rankingDisclosure.locator('summary').press('Enter');
      await expect(page.getByTestId('ranking-weight-message-table')).toBeVisible();
      await expect(page.getByTestId('ranking-weight-message-table').locator('tbody tr')).toHaveCount(57);
      const rankDisclosure = page.getByTestId('ranking-weight-rank-exact-table');
      await rankDisclosure.locator('summary').press('Enter');
      await expect(page.getByTestId('ranking-weight-batch-table')).toBeVisible();
      await expect(page.getByTestId('ranking-weight-batch-table').locator('tbody tr')).toHaveCount(114);

      const downloadLinks = page.getByTestId('robustness-downloads-section').getByRole('link');
      expect(await downloadLinks.count()).toBeGreaterThan(10);
      const hrefs = await downloadLinks.evaluateAll((links) => links.map((link) => link.getAttribute('href') ?? ''));
      expect(hrefs.every((href) => href.length > 0 && !href.startsWith('/') && !href.includes('..'))).toBe(true);
      expect(hrefs.every((href) => existsSync(path.join(stage.directory, href)))).toBe(true);
      if (stage.rootTestId === 'robustness-report-release') {
        await expect(page.getByTestId('robustness-download-release_evidence')).toHaveAttribute(
          'href',
          'robustness_production_release_evidence.json',
        );
      }

      const geometry = await page.evaluate((rootTestId) => {
        const section = document.querySelector<HTMLElement>(`[data-testid="${rootTestId}"]`);
        const visibleCharts = [...document.querySelectorAll<HTMLElement>('.robustness-chart-shell')]
          .filter((chart) => chart.offsetParent !== null);
        const diagramScrollers = [...document.querySelectorAll<HTMLElement>(
          '.robustness-factorial-scroll, .robustness-reader-scroll',
        )];
        return {
          horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
          sectionWidth: section?.getBoundingClientRect().width ?? 0,
          overflowingCharts: visibleCharts.filter((chart) => chart.scrollWidth > chart.clientWidth + 2).length,
          diagramContained: diagramScrollers.every(
            (scroller) => scroller.getBoundingClientRect().right <= window.innerWidth + 1,
          ),
        };
      }, stage.rootTestId);
      expect(geometry.horizontalOverflow).toBe(false);
      expect(geometry.sectionWidth).toBeLessThanOrEqual(viewport.width + 1);
      expect(geometry.overflowingCharts).toBe(0);
      expect(geometry.diagramContained).toBe(true);
    }
  }

  expect(externalRequests).toEqual([]);
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});
