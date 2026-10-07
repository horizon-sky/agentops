"use client";

import { createContext, useContext, useEffect } from "react";
import type { AuthUser } from "@/lib/types";

const UserContext = createContext<AuthUser | null>(null);

export function useAuthUser(): AuthUser | null {
  return useContext(UserContext);
}

export default function AuthGate({ user, children }: { user: AuthUser; children: React.ReactNode }) {
  useEffect(() => {
    const changed = (event: StorageEvent) => {
      if (event.key === "agentops_auth_changed") window.location.reload();
    };
    window.addEventListener("storage", changed);
    return () => {
      window.removeEventListener("storage", changed);
    };
  }, []);
  return <UserContext.Provider value={user}>{children}</UserContext.Provider>;
}
