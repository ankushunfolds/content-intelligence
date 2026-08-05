"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api } from "@/lib/api";

export default function UnsubscribePage() {
  return (
    <Suspense fallback={null}>
      <UnsubscribeContent />
    </Suspense>
  );
}

/**
 * Deliberately requires a click rather than unsubscribing on page load.
 * Mail clients and security scanners fetch every link in a message to preview
 * or vet it, so acting automatically here would silently turn off emails for
 * people who never opened the message.
 */
function UnsubscribeContent() {
  const params = useSearchParams();
  const token = params.get("token");
  const [status, setStatus] = useState<"idle" | "saving" | "done" | "error">("idle");
  const [message, setMessage] = useState("");

  async function confirm() {
    if (!token) {
      setStatus("error");
      setMessage("This link is missing its token.");
      return;
    }
    setStatus("saving");
    try {
      const res = await api.unsubscribe(token);
      setMessage(res.message);
      setStatus("done");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "This link is invalid or has expired.");
      setStatus("error");
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="panel w-full max-w-sm p-8">
        {status === "done" ? (
          <>
            <h1 className="text-lg font-semibold text-white">Unsubscribed</h1>
            <p className="mt-2 text-sm text-neutral-500">{message}</p>
            <p className="mt-3 text-xs text-neutral-600">
              Your account is untouched — the brief is still on your dashboard whenever you want it.
            </p>
          </>
        ) : (
          <>
            <h1 className="text-lg font-semibold text-white">Stop the daily email?</h1>
            <p className="mt-2 text-sm text-neutral-500">
              You&apos;ll keep your account and can still read every brief in the app. Only the
              email stops.
            </p>
            {status === "error" ? <p className="mt-3 text-sm text-fall">{message}</p> : null}
            <button
              onClick={confirm}
              disabled={status === "saving"}
              className="btn-primary mt-6 w-full"
            >
              {status === "saving" ? "Saving…" : "Yes, stop emailing me"}
            </button>
          </>
        )}

        <Link
          href="/dashboard"
          className="mt-4 block text-center text-xs text-neutral-600 hover:text-neutral-400"
        >
          Back to dashboard
        </Link>
      </div>
    </div>
  );
}
