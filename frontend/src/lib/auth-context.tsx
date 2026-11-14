"use client";

import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { getToken, setToken, clearToken, getTokenExpiryMs, api, AuthResponse, Me } from "./api";

// Refresh proactively once less than this much of the token's life remains,
// so an active user never gets surprised by a silent logout mid-session.
const REFRESH_THRESHOLD_MS = 7 * 24 * 60 * 60 * 1000;

function maybeRefreshToken() {
  const token = getToken();
  if (!token) return;
  const expiry = getTokenExpiryMs(token);
  if (expiry === null || expiry - Date.now() > REFRESH_THRESHOLD_MS) return;
  api.refreshToken().then(
    (auth) => setToken(auth.token),
    () => {
      /* refresh is best-effort — the existing token still works until it actually expires */
    }
  );
}

interface AuthContextValue {
  user: Me | null;
  loading: boolean;
  login: (auth: AuthResponse) => Promise<Me>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  async function refreshUser() {
    const me = await api.getMe();
    setUser(me);
  }

  useEffect(() => {
    (async () => {
      if (getToken()) {
        try {
          await refreshUser();
          maybeRefreshToken();
        } catch {
          clearToken();
        }
      }
      setLoading(false);
    })();
  }, []);

  async function login(auth: AuthResponse) {
    setToken(auth.token);
    const me = await api.getMe();
    setUser(me);
    return me;
  }

  function logout() {
    clearToken();
    setUser(null);
    window.location.href = "/login";
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
