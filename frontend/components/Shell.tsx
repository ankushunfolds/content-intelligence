"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, getToken, setToken } from "@/lib/api";

const NAV = [
  { href: "/dashboard", label: "Today" },
  { href: "/competitors", label: "Competitors" },
  { href: "/trends", label: "Trends" },
  { href: "/briefs", label: "Briefs" },
];

/** App chrome + the auth gate. Unauthenticated users are sent to the landing page. */
export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [checked, setChecked] = useState(false);
  const [email, setEmail] = useState<string | null>(null);
  const [isVerified, setIsVerified] = useState(true);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/");
      return;
    }
    api
      .me()
      .then((user) => {
        setEmail(user.email);
        setIsVerified(user.is_verified);
      })
      .catch(() => {
        setToken(null);
        router.replace("/");
      })
      .finally(() => setChecked(true));
  }, [router]);

  if (!checked) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-neutral-600">
        Loading your intelligence…
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-ink-800 bg-ink-950/85 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-3 py-3 sm:gap-6 sm:px-6 sm:py-3.5">
          <Link
            href="/dashboard"
            className="shrink-0 text-sm font-semibold tracking-tight text-white"
          >
            <span className="sm:hidden">CI</span>
            <span className="hidden sm:inline">Content Intelligence</span>
          </Link>

          {/* Scrolls horizontally instead of overflowing the header on
              narrow screens — four nav items plus the logo and sign-out
              button don't fit a phone width otherwise. */}
          <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {NAV.map((item) => {
              const active = pathname === item.href || pathname.startsWith(item.href + "/");
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`shrink-0 whitespace-nowrap rounded-md px-2.5 py-1.5 text-sm transition-colors ${
                    active ? "bg-ink-800 text-white" : "text-neutral-500 hover:text-neutral-200"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="ml-auto flex shrink-0 items-center gap-3">
            {email ? <span className="hidden text-xs text-neutral-600 md:inline">{email}</span> : null}
            <button
              onClick={() => {
                setToken(null);
                router.replace("/");
              }}
              className="shrink-0 text-xs text-neutral-600 hover:text-neutral-300"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      {!isVerified ? <VerifyBanner /> : null}

      <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
    </div>
  );
}

function VerifyBanner() {
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");

  async function resend() {
    setStatus("sending");
    try {
      await api.resendVerification();
      setStatus("sent");
    } catch {
      setStatus("error");
    }
  }

  return (
    <div className="border-b border-amber-900/40 bg-amber-950/40">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-6 py-2.5 text-xs text-amber-200">
        <span>
          {status === "sent"
            ? "Verification email sent — check your inbox."
            : "Please verify your email address to make sure you don't lose access to your account."}
        </span>
        {status !== "sent" ? (
          <button
            onClick={resend}
            disabled={status === "sending"}
            className="rounded-md border border-amber-800/60 px-2 py-0.5 font-medium text-amber-100 hover:bg-amber-900/40 disabled:opacity-60"
          >
            {status === "sending" ? "Sending…" : status === "error" ? "Try again" : "Resend email"}
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function EmptyState({ title, body, action }: { title: string; body: string; action?: React.ReactNode }) {
  return (
    <div className="panel p-10 text-center">
      <h3 className="text-sm font-semibold text-neutral-200">{title}</h3>
      <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-neutral-500">{body}</p>
      {action ? <div className="mt-5 flex justify-center">{action}</div> : null}
    </div>
  );
}

export function SectionHeader({
  icon,
  title,
  caption,
  action,
}: {
  icon: string;
  title: string;
  caption?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-3 flex items-end justify-between gap-4">
      <div>
        <h2 className="flex items-center gap-2 text-sm font-semibold text-neutral-200">
          <span aria-hidden>{icon}</span>
          {title}
        </h2>
        {caption ? <p className="mt-0.5 text-xs text-neutral-600">{caption}</p> : null}
      </div>
      {action}
    </div>
  );
}
