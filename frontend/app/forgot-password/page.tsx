"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [message, setMessage] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setStatus("sending");
    try {
      const res = await api.forgotPassword(email.trim());
      setMessage(res.message);
      setStatus("sent");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Something went wrong");
      setStatus("error");
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="panel w-full max-w-sm p-8">
        <h1 className="text-lg font-semibold text-white">Reset your password</h1>
        <p className="mt-2 text-sm text-neutral-500">
          Enter the email on your account and we&apos;ll send you a link to reset your password.
        </p>

        {status === "sent" ? (
          <p className="mt-6 text-sm text-neutral-300">{message}</p>
        ) : (
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
            {status === "error" ? <p className="text-sm text-fall">{message}</p> : null}
            <button type="submit" disabled={status === "sending"} className="btn-primary w-full">
              {status === "sending" ? "Sending…" : "Send reset link"}
            </button>
          </form>
        )}

        <Link href="/" className="mt-4 block text-center text-xs text-neutral-600 hover:text-neutral-400">
          Back to sign in
        </Link>
      </div>
    </div>
  );
}
