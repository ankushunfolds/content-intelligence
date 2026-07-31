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

  useEffect(() => {
    if (!getToken()) {
      router.replace("/");
      return;
    }
    api
      .me()
      .then((user) => setEmail(user.email))
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
        <div className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-3.5">
          <Link href="/dashboard" className="text-sm font-semibold tracking-tight text-white">
            Content Intelligence
          </Link>

          <nav className="flex items-center gap-1">
            {NAV.map((item) => {
              const active = pathname === item.href || pathname.startsWith(item.href + "/");
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`rounded-md px-2.5 py-1.5 text-sm transition-colors ${
                    active ? "bg-ink-800 text-white" : "text-neutral-500 hover:text-neutral-200"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            {email ? <span className="hidden text-xs text-neutral-600 sm:inline">{email}</span> : null}
            <button
              onClick={() => {
                setToken(null);
                router.replace("/");
              }}
              className="text-xs text-neutral-600 hover:text-neutral-300"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
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
