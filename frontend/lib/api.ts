"use client";

import type {
  Brief,
  RefreshResult,
  TodayIntelligence,
  TrackedChannel,
  Trend,
  Video,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const TOKEN_KEY = "ci_token";

// In-memory first so the app works even where storage is unavailable.
let memoryToken: string | null = null;

export function setToken(token: string | null) {
  memoryToken = token;
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage blocked — memory token still works for this session */
  }
}

export function getToken(): string | null {
  if (memoryToken) return memoryToken;
  try {
    memoryToken = window.localStorage.getItem(TOKEN_KEY);
  } catch {
    memoryToken = null;
  }
  return memoryToken;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers || {}),
    },
  });

  if (response.status === 204) return undefined as T;

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, detail);
  }

  return (await response.json()) as T;
}

export const api = {
  signup: (email: string, password: string, niche?: string) =>
    request<{ access_token: string }>("/auth/signup", {
      method: "POST",
      body: JSON.stringify({ email, password, niche }),
    }),

  login: (email: string, password: string) =>
    request<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  me: () =>
    request<{ id: number; email: string; niche: string | null; is_verified: boolean }>("/auth/me"),

  resendVerification: () => request<{ message: string }>("/auth/resend-verification", { method: "POST" }),

  verifyEmail: (token: string) =>
    request<{ message: string }>(`/auth/verify?token=${encodeURIComponent(token)}`),

  forgotPassword: (email: string) =>
    request<{ message: string }>("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

  resetPassword: (token: string, password: string) =>
    request<{ message: string }>("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, password }),
    }),

  onboarding: (own_channel: string, competitors: string[], niche?: string) =>
    request<TrackedChannel[]>("/channels/onboarding", {
      method: "POST",
      body: JSON.stringify({ own_channel, competitors, niche }),
    }),

  trackChannel: (url: string, type: "own" | "competitor" = "competitor") =>
    request<TrackedChannel>("/channels/track", {
      method: "POST",
      body: JSON.stringify({ url, type }),
    }),

  untrackChannel: (channelId: number) =>
    request<void>(`/channels/${channelId}`, { method: "DELETE" }),

  trackedChannels: () => request<TrackedChannel[]>("/channels/tracked"),

  channel: (channelId: number) => request<TrackedChannel>(`/channels/${channelId}`),

  channelVideos: (channelId: number, sort: "recent" | "performance" | "views" = "performance") =>
    request<Video[]>(`/channels/${channelId}/videos?sort=${sort}&limit=40`),

  breakouts: () => request<Video[]>("/videos/breakouts"),

  trends: () => request<Trend[]>("/trends"),

  trend: (trendId: number) => request<Trend>(`/trends/${trendId}`),

  trendVideos: (trendId: number) => request<Video[]>(`/trends/${trendId}/videos`),

  today: () => request<TodayIntelligence>("/intelligence/today"),

  refresh: () => request<RefreshResult>("/intelligence/refresh", { method: "POST" }),

  briefs: () => request<Brief[]>("/briefs"),

  briefToday: () => request<Brief>("/briefs/today"),
};
