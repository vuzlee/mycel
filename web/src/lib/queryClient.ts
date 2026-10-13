/** One cache for every server read. A 401 anywhere drops the session once, here. */

import { QueryCache, QueryClient } from "@tanstack/react-query";
import { Unauthorized } from "../api";

let onUnauthorized: () => void = () => {};

/** Set by the auth provider: what a dead session means for the page. */
export function whenUnauthorized(handler: () => void): void {
  onUnauthorized = handler;
}

export const makeQueryClient = (): QueryClient =>
  new QueryClient({
    queryCache: new QueryCache({
      onError: (error) => {
        if (error instanceof Unauthorized) onUnauthorized();
      },
    }),
    defaultOptions: {
      queries: {
        // A 401 or 404 is an answer, not a blip.
        retry: (failures, error) => !(error instanceof Unauthorized) && failures < 2,
        refetchOnWindowFocus: false,
      },
    },
  });

export const queryClient = makeQueryClient();
