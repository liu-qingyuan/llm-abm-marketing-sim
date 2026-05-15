import { expect, test } from '@playwright/test';
import { spawn, type ChildProcess } from 'node:child_process';
import net from 'node:net';
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';


async function freePort(): Promise<number> {
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      const port = typeof address === 'object' && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

async function waitForHealth(baseURL: string) {
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${baseURL}/api/health`);
      if (response.ok) return;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error(`server did not become healthy: ${baseURL}`);
}

test('local web console validates uploads, runs mock provider, renders rich bilingual results', async ({ page }, testInfo) => {
  const root = testInfo.outputDir;
  const port = await freePort();
  const baseURL = `http://127.0.0.1:${port}`;
  const artifactRoot = path.join(root, 'web-runs');
  let server: ChildProcess | undefined;
  try {
    server = spawn('python', ['-m', 'llm_abm_sim.web', '--host', '127.0.0.1', '--port', String(port), '--artifact-root', artifactRoot], {
      cwd: process.cwd(),
      env: { ...process.env, PYTHONPATH: path.join(process.cwd(), 'src') },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    await waitForHealth(baseURL);

    const fixtures = path.join(root, 'fixtures');
    mkdirSync(fixtures, { recursive: true });
    const usersPath = path.join(fixtures, 'users.csv');
    const edgesPath = path.join(fixtures, 'edges.json');
    writeFileSync(usersPath, 'user_id,interest_tags,brand_attitude,activity_level,authorization,segment\nu1,"eco,skincare",0.8,0.9,Bearer sk-hidden,A\nu2,"eco,beauty",0.4,0.7,Bearer sk-hidden,B\nu3,"gaming",0.0,0.4,Bearer sk-hidden,C\n');
    writeFileSync(edgesPath, JSON.stringify({ edges: [
      { source: 'u1', target: 'u2', weight: 1.0, relationship: 'follow' },
      { source: 'u2', target: 'u3', weight: 0.5, relationship: 'follow' },
    ] }));

    await page.route('**/api/datasets/validate', async route => {
      await new Promise(resolve => setTimeout(resolve, 350));
      await route.continue();
    });
    await page.route('**/api/runs', async route => {
      if (route.request().method() === 'POST') {
        await new Promise(resolve => setTimeout(resolve, 350));
      }
      await route.continue();
    });

    await page.goto(baseURL);
    await expect(page.getByTestId('web-console')).toBeVisible();
    await page.getByTestId('mock-provider-toggle').check();
    await expect(page.getByTestId('provider-state')).toContainText('mock');

    await page.getByTestId('users-file').setInputFiles(usersPath);
    await page.getByTestId('edges-file').setInputFiles(edgesPath);
    await expect(page.getByTestId('start-run')).toBeDisabled();
    await page.getByTestId('validate-dataset').click();
    await expect(page.getByTestId('validate-dataset')).toBeDisabled();
    await expect(page.getByTestId('validate-dataset')).toHaveAttribute('aria-busy', 'true');
    await expect(page.getByTestId('validation-output')).toContainText('profiles=3');
    await expect(page.getByTestId('validation-output')).toContainText('edges=2');
    await expect(page.getByTestId('validation-output')).not.toContainText('authorization');
    await expect(page.getByTestId('validate-dataset')).toBeEnabled();
    await expect(page.getByTestId('validate-dataset')).toHaveAttribute('aria-busy', 'false');
    await expect(page.getByTestId('start-run')).toBeEnabled();

    const runResponse = page.waitForResponse(response => response.url().endsWith('/api/runs') && response.request().method() === 'POST');
    await page.getByTestId('start-run').click();
    await expect(page.getByTestId('start-run')).toBeDisabled();
    await expect(page.getByTestId('start-run')).toHaveAttribute('aria-busy', 'true');
    await expect((await runResponse).request().postDataJSON()).toMatchObject({ mock_provider: true });
    await expect(page.getByTestId('run-output')).toContainText('succeeded', { timeout: 20_000 });
    await expect(page.getByTestId('start-run')).toBeEnabled();
    await expect(page.getByTestId('start-run')).toHaveAttribute('aria-busy', 'false');
    await expect(page.getByTestId('results-section')).toBeVisible();
    await expect(page.getByTestId('metric-cards')).toContainText('final_engaged');
    await expect(page.getByTestId('trend-chart')).toBeVisible();
    await expect(page.getByTestId('network-timeline')).toContainText('u1');
    await expect(page.getByTestId('dataset-summary')).toContainText('graph_edge_count');
    await expect(page.getByTestId('provider-summary')).toContainText('mock');
    await expect(page.getByTestId('agent-io')).toContainText('schema_version');
    const forbiddenFragments = ['authorization', 'cookie', 'access_token', 'token', 'secret', 'password', 'credential', 'raw_prompt', 'raw_provider', 'headers', 'bearer', 'sk-'];
    for (const fragment of forbiddenFragments) {
      await expect(page.getByTestId('validation-output')).not.toContainText(fragment);
      await expect(page.getByTestId('provider-summary')).not.toContainText(fragment);
      await expect(page.getByTestId('agent-io')).not.toContainText(fragment);
    }
    await expect(page.getByTestId('key-influencers')).toBeVisible();

    const runDirs = readdirSync(artifactRoot).filter((name) => name.startsWith('web-run-'));
    expect(runDirs.length).toBeGreaterThan(0);
    const latestRunDir = path.join(artifactRoot, runDirs.sort().at(-1)!);
    const artifactText = readdirSync(latestRunDir)
      .map((name) => readFileSync(path.join(latestRunDir, name), 'utf8'))
      .join('\n')
      .toLowerCase();
    for (const fragment of forbiddenFragments) {
      expect(artifactText).not.toContain(fragment);
    }

    await page.getByTestId('web-language').selectOption('zh-CN');
    await expect(page.getByTestId('results-section')).toContainText('结果');
    await expect(page.getByTestId('agent-io')).toBeVisible();
  } finally {
    server?.kill('SIGTERM');
  }
});

test('local web console shows blocked product provider path without offline success', async ({ page }, testInfo) => {
  const port = await freePort();
  const baseURL = `http://127.0.0.1:${port}`;
  let server: ChildProcess | undefined;
  try {
    server = spawn('python', ['-m', 'llm_abm_sim.web', '--host', '127.0.0.1', '--port', String(port), '--artifact-root', path.join(testInfo.outputDir, 'blocked-runs')], {
      cwd: process.cwd(),
      env: { ...process.env, PYTHONPATH: path.join(process.cwd(), 'src'), LLM_ABM_RUN_LIVE_LLM: '', OPENAI_API_KEY: '' },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    await waitForHealth(baseURL);
    await page.goto(baseURL);
    await expect(page.getByTestId('provider-state')).toContainText('blocked');
    await expect(page.getByTestId('provider-reasons')).toContainText('LLM_ABM_RUN_LIVE_LLM');
  } finally {
    server?.kill('SIGTERM');
  }
});
