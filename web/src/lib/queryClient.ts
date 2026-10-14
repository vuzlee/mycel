/** One cache for every server read. A 401 drops the session in `api.ts`, for writes too. */

import { QueryClient } from "@tanstack/react-query";
import { Unauthorized } from "../api";

export { whenUnauthorized } from "../api";

export const makeQueryClient = (): QueryClient =>
  new QueryClient({
    defaultOptions: {
      queries: {
        // A 401 or 404 is an answer, not a blip.
        retry: (failures, error) => !(error instanceof Unauthorized) && failures < 2,
        refetchOnWindowFocus: false,
      },
    },
  });

export const queryClient = makeQueryClient();
