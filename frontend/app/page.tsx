"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, getToken, setToken } from "@/lib/api";

export default function LandingPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"signup" | "login">("signup");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (getToken()) router.replace("/dashboard");
  }, [router]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result =
        mode === "signup" ? await api.signup(email, password) : await api.login(email, password);
      setToken(result.access_token);

      // A returning user with channels goes straight to the dashboard.
      const tracked = await api.trackedChannels().catch(() => []);
      router.push(tracked.length ? "/dashboard" : "/onboarding");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col">
      <div className="mx-auto flex w-full max-w-6xl flex-1 items-center px-6 py-16">
        <div className="grid w-full items-center gap-16 lg:grid-cols-2">
          <div>
            <div className="eyebrow">Content Intelligence</div>
            <h1 className="mt-4 text-4xl font-semibold leading-tight tracking-tight text-white sm:text-5xl">
              Know what to create next.
              <br />
              <span className="text-signal">Before you create it.</span>
            </h1>
            <p className="mt-5 max-w-md text-base leading-relaxed text-neutral-400">
              Track competitors, discover emerging trends, and get a daily briefing on the content
              opportunities that matter.
            </p>

            <ul className="mt-8 space-y-3 text-sm text-neutral-400">
              {[
                ["Competitor intelligence", "What they publish, how often, and what's outperforming."],
                ["Trend detection", "Topics rising in volume and beating their creators' baselines."],
                ["A daily brief", "Three to five opportunities, each with the evidence behind it."],
              ].map(([title, body]) => (
                <li key={title} className="flex gap-3">
                  <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-signal" />
                  <span>
                    <span className="font-medium text-neutral-200">{title}</span> — {body}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div className="panel p-6 sm:p-8">
            <h2 className="text-lg font-semibold text-white">
              {mode === "signup" ? "Start tracking" : "Welcome back"}
            </h2>
            <p className="mt-1 text-sm text-neutral-500">
              {mode === "signup"
                ? "Three inputs and you're set up."
                : "Sign in to see today's intelligence."}
            </p>

            <form onSubmit={submit} className="mt-6 space-y-3">
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="field"
                autoComplete="email"
              />
              <input
                type="password"
                required
                minLength={6}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Password (6+ characters)"
                className="field"
                autoComplete={mode === "signup" ? "new-password" : "current-password"}
              />

              {error ? <p className="text-sm text-fall">{error}</p> : null}

              <button type="submit" disabled={busy} className="btn-primary w-full">
                {busy ? "Working…" : mode === "signup" ? "Start Tracking" : "Sign in"}
              </button>
            </form>

            <button
              onClick={() => {
                setMode(mode === "signup" ? "login" : "signup");
                setError(null);
              }}
              className="mt-4 w-full text-center text-xs text-neutral-600 hover:text-neutral-400"
            >
              {mode === "signup" ? "Already have an account? Sign in" : "Need an account? Sign up"}
            </button>
          </div>
        </div>
      </div>

      <footer className="border-t border-ink-800 px-6 py-5">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-neutral-700">
            Every recommendation is computed from your tracked channels&apos; real data. The AI
            explains the numbers — it never invents them.
          </p>
          <Link href="/privacy" className="text-xs text-neutral-700 hover:text-neutral-400">
            Privacy
          </Link>
        </div>
      </footer>
    </div>
  );
}
