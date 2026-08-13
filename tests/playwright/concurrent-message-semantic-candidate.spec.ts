import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';

function generateSemanticV7Release(outputDir: string): string {
  const root = path.join(outputDir, 'semantic-v7-release-fixture');
  const command = `
set -euo pipefail
. .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD"
python - <<'PY'
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from llm_abm_sim import ConcurrentRobustnessStudy
from llm_abm_sim import concurrent_robustness_evidence as evidence
from llm_abm_sim import concurrent_robustness_release as release
from llm_abm_sim import concurrent_robustness_report as report
from tests.integration.test_concurrent_message_experiment_runner import (
    _install_deterministic_robustness_cell_fixture,
    _make_validation_report_source,
    _robustness_manifest_for_source,
)
from tests.unit.test_concurrent_robustness_release import (
    _FakeCellEvidenceModel,
    _V7_CONTRACT_FIELDS,
    _fake_manifest,
    _snapshot,
    _write_json,
)

root = Path(${JSON.stringify(root)}).resolve()
root.mkdir(parents=True, exist_ok=True)
formal = _make_validation_report_source(root, 'formal-source', report_sized=True)
manifest = _robustness_manifest_for_source(formal, output_identity='semantic-v7-browser-fixture')
workspace = root / 'workspace'
v1_candidate = root / 'payload-v1-candidate'
v2_candidate = root / 'payload-v2-candidate'
study = ConcurrentRobustnessStudy()
study.run(manifest, None, workspace)
_install_deterministic_robustness_cell_fixture(workspace, manifest)
complete = study.run(manifest, None, workspace)
assert complete.study_root is not None
published = study.run(manifest, None, workspace, report_destination=v1_candidate)
assert published.report_candidate == v1_candidate
report._REPORT_PRESENTATION.compose_presentation_candidate(
    formal_root=formal,
    study_root=complete.study_root,
    candidate_dir=v1_candidate,
    destination_dir=v2_candidate,
)

contracts = root / 'contracts'
contracts.mkdir()
replay = contracts / 'immutable-replay.json'
replay.write_text('fixture replay\\n', encoding='utf-8')
execution_contract = contracts / 'formal-run-contract.json'
execution_document = {
    'report_candidate': str(v1_candidate),
    'closure_replay_artifact': str(replay),
    'closure_replay_sha256': hashlib.sha256(replay.read_bytes()).hexdigest(),
    'implementation_commit': '1234567',
    'closure_implementation_commit': '7654321',
    'physical_provider_attempts': 28_800,
    'subscription_nominal_reference_cost_usd': 1.25,
    'subscription_billed_cost_usd': 0.0,
}
_write_json(execution_contract, execution_document)
closure = contracts / 'presentation-closure-v2.json'
immutable_inputs = (formal, complete.study_root, workspace, v1_candidate, v2_candidate, execution_contract, replay)
before_closure = {path: _snapshot(path) for path in immutable_inputs}
with (
    patch.object(evidence, '_validate_execution_contract', lambda **_kwargs: execution_document),
    patch.object(evidence, '_close_formal_cell_evidence', lambda **_kwargs: None),
):
    closure_facts = evidence.close_presentation(
        repo_root=root,
        formal_root=formal,
        study_root=complete.study_root,
        workspace_root=workspace,
        candidate_dir=v2_candidate,
        execution_contract_path=execution_contract,
        destination_path=closure,
        implementation_commit='abcdef0',
    )
assert closure_facts.closure_schema_version == evidence.PRESENTATION_CLOSURE_V2_SCHEMA
assert all(before == _snapshot(path) for path, before in before_closure.items())

fake_manifest = _fake_manifest(formal)
fake_manifest.source.manifest_sha256 = manifest.source.manifest_sha256

class FakeManifestModel:
    @staticmethod
    def model_validate(_payload):
        return fake_manifest

    @staticmethod
    def model_validate_json(_payload):
        return fake_manifest

promotion_inputs = (*immutable_inputs, closure)
before_promotion = {path: _snapshot(path) for path in promotion_inputs}
with (
    patch.object(release, 'ConcurrentRobustnessManifest', FakeManifestModel),
    patch.object(release, '_CellEvidenceDocument', _FakeCellEvidenceModel),
    patch.object(release, '_validate_cell_evidence_contract', lambda *_args, **_kwargs: None),
    patch.object(release, '_validate_completed_dynamic_root', lambda **_kwargs: None),
    patch.object(release, '_validate_execution_contract', lambda **_kwargs: execution_document),
    patch.object(evidence, '_validate_execution_contract', lambda **_kwargs: execution_document),
    patch.object(evidence, '_close_formal_cell_evidence', lambda **_kwargs: None),
):
    promoted = release.promote_concurrent_robustness_release(
        repo_root=root,
        formal_root=formal,
        study_root=complete.study_root,
        workspace_root=workspace,
        candidate_dir=v2_candidate,
        execution_contract_path=execution_contract,
        destination_dir=root / 'production-v7',
        release_contract_path=contracts / 'production-v7-release-contract.json',
        release_id='semantic-v7-browser-release',
        presentation_closure_path=closure,
    )
    contract = json.loads(promoted.contract_path.read_text(encoding='utf-8'))
    validated = release.validate_concurrent_robustness_production_release(
        repo_root=root,
        contract_document=contract,
        source_dir=promoted.source_dir,
    )
assert set(contract) == _V7_CONTRACT_FIELDS
assert contract['schema_version'] == 'abm-report-release-contract-v7'
assert contract['report_payload_schema_version'] == 'concurrent-robustness-report-payload-v2'
production_manifest = json.loads((promoted.source_dir / 'artifact_manifest.json').read_text(encoding='utf-8'))
assert {
    path for path in production_manifest['approved_downloads'].values() if path.endswith('.mmd')
} == {
    'mechanism-sample-first.mmd',
    'mechanism-pair-formation.mmd',
    'mechanism-independent-delivery.mmd',
    'mechanism-exposure-decisions.mmd',
    'mechanism-feedback-boundary.mmd',
    'real-batch-mechanism.mmd',
    'prompt-model-factorial.mmd',
}
assert 'project-evidence-chain.mmd' not in production_manifest['artifacts'].values()
assert 'mechanism-image-generation-audit.json' not in production_manifest['artifacts'].values()
assert validated['production_deploy_eligible'] is True
assert (promoted.source_dir / 'report.html').stat().st_size < 3 * 1024 * 1024
assert all(before == _snapshot(path) for path, before in before_promotion.items())
PY`;
  execFileSync('bash', ['-lc', command], { stdio: 'inherit' });
  return path.join(root, 'production-v7', 'report.html');
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const geometry = await page.evaluate(() => ({
    pageOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
    overflowingFigures: [...document.querySelectorAll<HTMLElement>('[data-mechanism-diagram-id]')]
      .filter((element) => element.offsetParent !== null)
      .filter((element) => element.getBoundingClientRect().width > window.innerWidth + 1)
      .map((element) => element.dataset.mechanismDiagramId),
    internalScrollers: [...document.querySelectorAll<HTMLElement>('.editorial-semantic-canvas, .robustness-factorial-scroll')]
      .filter((element) => element.offsetParent !== null)
      .filter((element) => element.scrollWidth > element.clientWidth + 1)
      .map((element) => element.closest<HTMLElement>('[data-mechanism-diagram-id], [data-testid]')?.dataset.mechanismDiagramId
        || element.closest<HTMLElement>('[data-testid]')?.dataset.testid),
  }));
  expect(geometry.pageOverflow).toBe(false);
  expect(geometry.overflowingFigures).toEqual([]);
  expect(geometry.internalScrollers).toEqual([]);
}

test('immutable v7 production keeps the bilingual mechanism and run evidence contracts accessible', async ({ page }, testInfo) => {
  test.setTimeout(420_000);
  const reportPath = generateSemanticV7Release(testInfo.outputDir);
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
    await expect(page.getByTestId('editorial-report')).toHaveAttribute('data-editorial-version', 'v4-semantic');
    await expect(page.getByTestId('editorial-report')).toHaveAttribute('data-production-deploy-eligible', 'true');
    await expect(page.locator('meta[name="abm-release-contract"]')).toHaveAttribute('content', 'abm-report-release-contract-v7');
    await expect(page.locator('[data-report-anchor]')).toHaveCount(5);
    await expect(page.locator('[data-report-anchor]').allTextContents()).resolves.toEqual([
      '样本先存在',
      '用户与消息配对',
      '三条消息独立投放',
      '曝光与配对决策',
      '反馈边界',
    ]);
    await expect(page.locator('[data-mechanism-diagram-id]')).toHaveCount(6);
    await expect(page.locator('[data-mechanism-method-disclosure]')).toHaveCount(6);
    await expect(page.locator('[data-mechanism-key]')).toHaveCount(0);
    await expect(page.locator('[data-legend-item]')).toHaveCount(0);
    await expect(page.locator('img')).toHaveCount(0);
    await expect(page.getByTestId('real-batch-mechanism-section')).toContainText('八个节点概括');
    await expect(page.getByTestId('robustness-report-release')).toBeHidden();
    await expect(page.getByTestId('robustness-report-candidate')).toHaveCount(0);
    await expect(page.getByTestId('prompt-model-factorial-diagram')).toBeHidden();
    await expect(page.getByTestId('project-evidence-chain-diagram')).toHaveCount(0);
    const downloadTargets = await page.locator('a[href]').evaluateAll((links) => links.map(
      (link) => (link as HTMLAnchorElement).href,
    ));
    expect(downloadTargets.every((href) => href.startsWith('file:'))).toBe(true);
    expect(downloadTargets.filter((href) => !existsSync(fileURLToPath(href)))).toEqual([]);

    if (viewport.width < 768) {
      await expect(page.locator('.editorial-semantic-canvas svg:visible')).toHaveCount(0);
      await expect(page.locator('.editorial-semantic-mobile-flow:visible')).toHaveCount(6);
    } else {
      await expect(page.locator('.editorial-semantic-canvas svg:visible')).toHaveCount(6);
      await expect(page.locator('.editorial-semantic-mobile-flow:visible')).toHaveCount(0);
    }

    for (let index = 0; index < 6; index += 1) {
      const disclosure = page.locator('[data-mechanism-method-disclosure]').nth(index);
      const summary = disclosure.locator('summary');
      await summary.focus();
      await summary.press('Enter');
      await expect(disclosure).toHaveAttribute('open', '');
      await expect(disclosure.locator('ol')).not.toBeEmpty();
      await summary.press('Space');
      await expect(disclosure).not.toHaveAttribute('open', '');
    }
    await expect(page.locator('[data-mechanism-method-disclosure]').first()).toContainText('runtime live database');

    for (const anchor of ['overview', 'sample', 'exposure-ranking', 'llm-decision', 'network-feedback']) {
      await page.locator(`[data-report-anchor="${anchor}"]`).click();
      await expect(page).toHaveURL(new RegExp(`#${anchor}$`));
      await expect(page.locator(`[data-report-mode-panel="mechanism"] [data-section-anchor="${anchor}"]`)).toBeFocused();
    }

    await page.getByRole('button', { name: 'English', exact: true }).click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'en-US');
    await expect(page.getByTestId('mechanism-mode-button')).toHaveText('Mechanism');
    await expect(page.getByTestId('run-evidence-mode-button')).toHaveText('This run');
    await expect(page.locator('[data-report-anchor]').allTextContents()).resolves.toEqual([
      'Sample First',
      'Pair Formation',
      'Independent Delivery',
      'Exposure & Decisions',
      'Feedback Boundary',
    ]);
    await expect(page.getByTestId('robustness-report-release')).toBeHidden();
    const feedbackSvg = page.getByTestId('mechanism-feedback_boundary-inline-svg');
    if (viewport.width >= 768) await expect(feedbackSvg).toBeVisible();
    else await expect(feedbackSvg).toBeHidden();

    await page.getByTestId('run-evidence-mode-button').click();
    await expect(page.getByTestId('run-evidence-mode-panel')).toBeVisible();
    await expect(page.getByTestId('mechanism-mode-panel')).toBeHidden();
    await expect(page.getByTestId('robustness-report-release')).toBeVisible();
    await expect(page.getByTestId('prompt-model-factorial-diagram')).toBeVisible();
    await expect(page.getByTestId('robustness-source-lineage')).toContainText('Immutable complete study root');
    await expect(page.getByTestId('ranking-weight-family-select').locator('option').first()).toHaveText('Network relevance and campaign feedback');
    await expect(page.getByTestId('prompt-model-metric-select').locator('option').first()).toHaveText('Cumulative exposure engagement rate');
    await expect(page.locator('.robustness-denominator-grid')).toHaveAttribute('aria-label', 'Prompt-Model denominators');
    await expect(page.getByTestId('prompt-model-cell-denominator').locator('[data-stable-token]')).toHaveCount(1);
    await expect(page.getByTestId('run-trace-state')).toHaveAttribute('data-trace-state', 'ready');
    await expect(page.getByTestId('run-trace-state')).toContainText('Trace ready');
    await expect(page.getByTestId('run-trace-filtered-count')).toContainText('1,800');
    await expect(page.getByTestId('run-trace-search')).toBeEnabled();
    const unmarkedChinese = await page.evaluate(() => {
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      const values: string[] = [];
      let node: Node | null;
      while ((node = walker.nextNode())) {
        const text = (node.textContent || '').replace(/\s+/g, ' ').trim();
        const element = node.parentElement;
        if (!text || !element || !/[\u3400-\u9fff]/.test(text) || element.getClientRects().length === 0) continue;
        if (element.closest('[hidden], script, style, [data-i18n], [data-robustness-i18n], [data-robustness-language-variant], [data-stable-token], [data-source-language], [data-report-language="zh-CN"]')) continue;
        values.push(text);
      }
      return values;
    });
    expect(unmarkedChinese).toEqual([]);

    await page.getByRole('button', { name: '中文', exact: true }).click();
    await expect(page.getByTestId('mechanism-mode-button')).toHaveText('机制说明');
    await expect(page.getByTestId('run-trace-state')).toContainText('决策轨迹已就绪');
    await expect(page.getByTestId('robustness-source-lineage')).toContainText('不可变完整研究根目录');
    await expect(page.getByTestId('ranking-weight-sensitivity-section')).toContainText('排序权重敏感性');
    await expect(page.getByTestId('ranking-weight-family-select').locator('option').first()).toHaveText('网络相关性与活动反馈');
    await expect(page.locator('.robustness-denominator-grid')).toHaveAttribute('aria-label', '提示词—模型分母');
    await expect(page.getByTestId('run-trace-search')).toHaveAttribute('aria-label', '搜索');
    await expect(page.getByTestId('run-trace-page-size')).toHaveAttribute('aria-label', '每页行数');
    await expect(page.locator('[data-trace-page="previous"]')).toHaveAttribute('aria-label', '上一页');
    await expect(page.locator('[data-testid^="run-trace-row-"]').first()).toHaveAttribute('data-stable-token', 'trace-id');
    await expect(page.locator('[data-testid^="run-trace-row-"]').first()).toHaveAttribute('aria-label', /^打开轨迹详情/);
    const unmarkedEnglish = await page.evaluate(() => {
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      const values: string[] = [];
      let node: Node | null;
      while ((node = walker.nextNode())) {
        const text = (node.textContent || '').replace(/\s+/g, ' ').trim();
        const element = node.parentElement;
        if (!text || !element || !/[A-Za-z]/.test(text) || element.getClientRects().length === 0) continue;
        if (element.closest('[hidden], script, style, [data-i18n], [data-robustness-i18n], [data-robustness-language-variant], [data-stable-token], [data-source-language], [data-report-language="en-US"]')) continue;
        values.push(text);
      }
      return values;
    });
    expect(unmarkedEnglish).toEqual([]);

    await expectNoHorizontalOverflow(page);
  }

  expect(externalRequests).toEqual([]);
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});
