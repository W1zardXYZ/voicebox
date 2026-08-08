import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { render } from 'vitest-browser-react';
import { PlatformProvider } from '@/platform/PlatformContext';
import { createMockPlatform, type MockPlatform } from './mockPlatform';

export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      // Retries and interval refetching are disabled so tests are
      // deterministic — polling components get their data exactly once.
      queries: {
        retry: false,
        refetchInterval: false,
        refetchOnWindowFocus: false,
        gcTime: Number.POSITIVE_INFINITY,
      },
      mutations: { retry: false },
    },
  });
}

export interface RenderWithProvidersOptions {
  platform?: MockPlatform;
  queryClient?: QueryClient;
}

export async function renderWithProviders(ui: ReactNode, options: RenderWithProvidersOptions = {}) {
  const platform = options.platform ?? createMockPlatform();
  const queryClient = options.queryClient ?? createTestQueryClient();

  const result = await render(
    <QueryClientProvider client={queryClient}>
      <PlatformProvider platform={platform}>{ui}</PlatformProvider>
    </QueryClientProvider>,
  );

  // Object.assign keeps the render result's prototype methods (locators)
  // intact — spreading would drop them.
  return Object.assign(result, { platform, queryClient });
}
