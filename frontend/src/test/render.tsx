import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import { vi } from "vitest";

import { Providers } from "@/app/providers";

/**
 * Render inside the real application providers.
 *
 * A test-only QueryClient with different defaults would prove the component
 * works under settings the app does not use, which is the standard way a retry
 * or staleTime bug survives a green suite.
 */
export function renderWithProviders(ui: ReactElement): RenderResult {
  return render(<Providers>{ui}</Providers>);
}

/** Stub `fetch` with a single JSON response, as the API would send it. */
export function stubJsonResponse(status: number, body: unknown) {
  const fetchMock = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** Stub `fetch` with a transport failure — nothing listening at all. */
export function stubNetworkFailure() {
  const fetchMock = vi.fn(async () => {
    throw new TypeError("fetch failed");
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
