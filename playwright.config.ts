import { defineConfig } from '@playwright/test';

const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const useEnvironmentProxy = process.env.ABM_DEPLOY_PUBLIC_TRANSPORT === 'environment-proxy';
const environmentProxy = process.env.https_proxy ?? process.env.HTTPS_PROXY ?? process.env.all_proxy ?? process.env.ALL_PROXY;
if (useEnvironmentProxy && !environmentProxy) throw new Error('Explicit environment-proxy transport requires a configured proxy');
const proxyUrl = useEnvironmentProxy ? new URL(environmentProxy!) : undefined;
const proxy = proxyUrl ? {
  server: `${proxyUrl.protocol}//${proxyUrl.host}`,
  ...(proxyUrl.username ? { username: decodeURIComponent(proxyUrl.username) } : {}),
  ...(proxyUrl.password ? { password: decodeURIComponent(proxyUrl.password) } : {}),
} : undefined;

export default defineConfig({
  testDir: './tests/playwright',
  outputDir: './test-results/playwright',
  timeout: 60_000,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],
  use: {
    proxy,
    launchOptions: executablePath ? { executablePath } : undefined,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
});
