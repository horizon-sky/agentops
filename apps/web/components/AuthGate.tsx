"use client";

import { createContext, useContext, useEffect } from "react";
import { loginRequired } from "@/lib/auth";
import type { AuthUser } from "@/lib/types";

const UserContext = createContext<AuthUser | null>(null);

export function useAuthUser(): AuthUser | null {
  return useContext(UserContext);
}

export default function AuthGate({ user, children }: { user: AuthUser; children: React.ReactNode }) {
  useEffect(() => {
    const check = async () => {
      try {
        const response = await fetch("/api/auth/session", { cache: "no-store" });
        if (response.status === 401) loginRequired();
        else if (response.ok) {
          const data = await response.json() as { user: AuthUser };
          if (data.user.id !== user.id) window.location.reload();
        }
      } catch { /* A temporary network failure does not log the user out. */ }
    };
    const changed = (event: StorageEvent) => {
      if (event.key === "agentops_auth_changed") void check();
    };
    window.addEventListener("focus", check);
    window.addEventListener("storage", changed);
    const timer = window.setInterval(check, 60_000);
    return () => {
      window.removeEventListener("focus", check);
      window.removeEventListener("storage", changed);
      window.clearInterval(timer);
    };
  }, [user.id]);
  return <UserContext.Provider value={user}>{children}</UserContext.Provider>;
}
