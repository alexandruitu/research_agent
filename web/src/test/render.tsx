import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, type InitialEntry } from "react-router-dom";

import { AuthProvider } from "../auth/AuthProvider";

export const testQueryClient = () =>
  new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });

/** Renders inside a query client, a router and the real AuthProvider (mock /auth/me with mockApi first). */
export function renderWithProviders(ui: ReactElement, { route = "/", client = testQueryClient() }: { route?: InitialEntry; client?: QueryClient } = {}) {
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[route]}>
          <AuthProvider>{ui}</AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}
