import { afterEach, beforeAll } from 'vitest';
import { worker } from './msw/worker';

beforeAll(async () => {
  await worker.start({ onUnhandledRequest: 'error', quiet: true });
  return () => worker.stop();
});

afterEach(() => {
  worker.resetHandlers();
});
