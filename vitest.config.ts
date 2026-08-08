import path from 'node:path';
import react from '@vitejs/plugin-react';
import { playwright } from '@vitest/browser-playwright';
import { defineConfig } from 'vitest/config';
import { changelogPlugin } from './app/plugins/changelog';

const appSrc = path.resolve(__dirname, 'app/src');

const shared = {
  plugins: [react(), changelogPlugin(__dirname)],
  resolve: {
    alias: { '@': appSrc },
  },
};

export default defineConfig({
  ...shared,
  test: {
    projects: [
      {
        ...shared,
        test: {
          name: 'unit',
          environment: 'happy-dom',
          include: ['app/src/**/*.test.{ts,tsx}'],
          exclude: ['app/src/**/*.browser.test.{ts,tsx}'],
          setupFiles: ['app/src/test/setup.ts'],
        },
      },
      {
        ...shared,
        publicDir: path.resolve(__dirname, 'app/src/test/public'),
        test: {
          name: 'browser',
          include: ['app/src/**/*.browser.test.{ts,tsx}'],
          setupFiles: ['app/src/test/setup.ts', 'app/src/test/setup.browser.ts'],
          browser: {
            enabled: true,
            headless: true,
            provider: playwright(),
            instances: [{ browser: 'chromium' }],
          },
        },
      },
    ],
  },
});
