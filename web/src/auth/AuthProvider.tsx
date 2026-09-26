import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, onUnauthorized, setCsrfToken } from "../api/client";
import type { SessionOut, UserOut } from "../api/types";

type Status = "loading" | "anonymous" | "authenticated";
type AuthValue = {
  status: Status;
  user: UserOut | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ status: Status; user: UserOut | null }>({ status: "loading", user: null });
  const queryClient = useQueryClient();

  const adopt = useCallback((session: SessionOut | null) => {
    setCsrfToken(session?.csrf_token ?? null);
    setState(session ? { status: "authenticated", user: session.user } : { status: "anonymous", user: null });
  }, []);

  useEffect(() => {
    let cancelled = false;
    api.get<SessionOut>("/auth/me").then(
      (session) => !cancelled && adopt(session),
      () => !cancelled && adopt(null),
    );
    return () => {
      cancelled = true;
    };
  }, [adopt]);

  useEffect(() => onUnauthorized(() => adopt(null)), [adopt]);

  const value = useMemo<AuthValue>(
    () => ({
      ...state,
      login: async (email, password) => adopt(await api.post<SessionOut>("/auth/login", { body: { email, password } })),
      logout: async () => {
        await api.post("/auth/logout").catch(() => undefined);
        adopt(null);
        queryClient.clear();
      },
    }),
    [state, adopt, queryClient],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
