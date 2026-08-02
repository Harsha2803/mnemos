"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

export function Providers({ children }: { children: ReactNode }) {
  // Created in state, not at module scope. A module-level client is shared
  // across every request the server process handles, which on a server-rendered
  // app means one user's cached data can be handed to the next.
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // The API's answer about its own dependencies is worth ten seconds
            // and no more; anything longer and a recovered Postgres stays
            // reported as down.
            staleTime: 10_000,
            // One retry. A readiness probe that failed is information, and
            // retrying it five times just delays showing the user that
            // information.
            retry: 1,
            refetchOnWindowFocus: true,
          },
        },
      }),
  );

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
