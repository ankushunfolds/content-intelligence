"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";

export default function VerifyPage() {
  return (
    <Suspense fallback={null}>
      <VerifyContent />
    </Suspense>
  );
}

function VerifyContent() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get("token");
  const [status, setStatus] = useState<"checking" | "done" | "error">("checking");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setMessage("This verification link is missing its token.");
      return;
    }
    api
      .verifyEmail(token)
      .then((res) => {
        setStatus("done");
        setMessage(res.message || "Email verified");
      })
      .catch((err) => {
        setStatus("error");
        setMessage(err instanceof Error ? err.message : "This link is invalid or has expired.");
      });
  }, [token]);

  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="panel w-full max-w-sm p-8 text-center">
        {status === "checking" ? (
          <p className="text-sm text-neutral-500">Verifying your email…</p>
        ) : status === "done" ? (
          <>
            <h1 className="text-lg font-semibold text-white">You&apos;re verified</h1>
            <p className="mt-2 text-sm text-neutral-500">{message}</p>
            <button
              onClick={() => router.push(getToken() ? "/dashboard" : "/")}
              className="btn-primary mt-6 w-full"
            >
              Continue
            </button>
          </>
        ) : (
          <>
            <h1 className="text-lg font-semibold text-white">Verification failed</h1>
            <p className="mt-2 text-sm text-neutral-500">{message}</p>
            <Link href={getToken() ? "/dashboard" : "/"} className="btn-ghost mt-6 block w-full">
              Back to {getToken() ? "dashboard" : "sign in"}
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
