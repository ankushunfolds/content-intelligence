"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api } from "@/lib/api";

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetPasswordContent />
    </Suspense>
  );
}

function ResetPasswordContent() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get("token");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState<"idle" | "saving" | "done" | "error">("idle");
  const [message, setMessage] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!token) {
      setStatus("error");
      setMessage("This reset link is missing its token.");
      return;
    }
    setStatus("saving");
    try {
      const res = await api.resetPassword(token, password);
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
            <h1 className="text-lg font-semibold text-white">Password updated</h1>
            <p className="mt-2 text-sm text-neutral-500">{message}</p>
            <button onClick={() => router.push("/")} className="btn-primary mt-6 w-full">
              Sign in
            </button>
          </>
        ) : (
          <>
            <h1 className="text-lg font-semibold text-white">Choose a new password</h1>
            <p className="mt-2 text-sm text-neutral-500">
              This link works once and expires in an hour.
            </p>
            <form onSubmit={submit} className="mt-6 space-y-3">
              <input
                type="password"
                required
                minLength={6}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="New password (6+ characters)"
                className="field"
                autoComplete="new-password"
              />
              {status === "error" ? <p className="text-sm text-fall">{message}</p> : null}
              <button type="submit" disabled={status === "saving"} className="btn-primary w-full">
                {status === "saving" ? "Saving…" : "Update password"}
              </button>
            </form>
            <Link href="/" className="mt-4 block text-center text-xs text-neutral-600 hover:text-neutral-400">
              Back to sign in
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
