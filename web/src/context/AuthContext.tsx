/** Who is signed in, for the whole app. */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo } from "react";
import type { ReactNode } from "react";
import type { User } from "../api";
import * as api from "../api";
import { whenUnauthorized } from "../lib/queryClient";

const ME = ["me"] as const;

interface AuthValue {
  user: User | null | undefined;
  /** The API could not say who is signed in (down, restarting); `retry` asks again. */
  failed: boolean;
  retry: () => void;
  signInWithCode: (email: string, code: string) => Promise<void>;
  signOut: () => Promise<void>;
  forget: () => void;
}

const Ctx = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const {
    data: user,
    isError: failed,
    refetch,
  } = useQuery({ queryKey: ME, queryFn: api.me, staleTime: Infinity });
  const retry = useCallback(() => void refetch(), [refetch]);
  const setUser = useCallback(
    (next: User | null) => {
      client.setQueryData(ME, next);
      // Everything cached belonged to whoever was signed in.
      client.removeQueries({ predicate: (q) => q.queryKey[0] !== ME[0] });
    },
    [client],
  );

  const signInWithCode = useCallback(
    async (email: string, code: string) => {
      setUser(await api.verifyCode(email, code));
    },
    [setUser],
  );

  const signOut = useCallback(async () => {
    await api.logout();
    setUser(null);
  }, [setUser]);

  // A 401 from any other call: the session died server-side, so drop it here too rather
  // than leave the page showing a name that no longer signs anything.
  const forget = useCallback(() => setUser(null), [setUser]);
  useEffect(() => whenUnauthorized(forget), [forget]);

  const value = useMemo(
    () => ({ user, failed, retry, signInWithCode, signOut, forget }),
    [user, failed, retry, signInWithCode, signOut, forget],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthValue {
  const found = useContext(Ctx);
  if (!found) throw new Error("useAuth outside AuthProvider");
  return found;
}
