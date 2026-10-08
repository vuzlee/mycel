/** Who is signed in, for the whole app. */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { User } from "../api";
import * as api from "../api";

interface AuthValue {
  user: User | null | undefined;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  forget: () => void;
}

const Ctx = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null | undefined>(undefined);

  useEffect(() => {
    let live = true;
    void api.me().then((found) => live && setUser(found));
    return () => {
      live = false;
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    setUser(await api.login(email, password));
  }, []);

  const signOut = useCallback(async () => {
    await api.logout();
    setUser(null);
  }, []);

  // A 401 from any other call: the session died server-side, so drop it here too rather
  // than leave the page showing a name that no longer signs anything.
  const forget = useCallback(() => setUser(null), []);

  const value = useMemo(() => ({ user, signIn, signOut, forget }), [user, signIn, signOut, forget]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthValue {
  const found = useContext(Ctx);
  if (!found) throw new Error("useAuth outside AuthProvider");
  return found;
}
