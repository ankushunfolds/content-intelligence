import Link from "next/link";

export const metadata = {
  title: "Privacy — Content Intelligence",
};

export default function PrivacyPage() {
  return (
    <div className="mx-auto max-w-2xl px-6 py-16 text-sm leading-relaxed text-neutral-400">
      <Link href="/" className="text-xs text-neutral-600 hover:text-neutral-300">
        ← Back
      </Link>

      <h1 className="mt-6 text-2xl font-semibold tracking-tight text-white">Privacy</h1>
      <p className="mt-2 text-xs text-neutral-600">Last updated 2026-08-02 · Beta version</p>

      <p className="mt-6">
        Content Intelligence is currently in a limited beta. This page explains what we collect and
        why, in plain language. It isn&apos;t a substitute for legal advice, and it will be replaced
        with a fuller policy before any wider release.
      </p>

      <h2 className="mt-8 text-base font-semibold text-white">What we collect</h2>
      <ul className="mt-3 space-y-2">
        <li>
          <span className="font-medium text-neutral-200">Your email and password</span> — used to
          create and secure your account. Passwords are hashed and never stored in plain text.
        </li>
        <li>
          <span className="font-medium text-neutral-200">YouTube channel URLs you add</span> — your
          own channel and any competitors you choose to track, used to pull public video and channel
          statistics via the YouTube Data API.
        </li>
        <li>
          <span className="font-medium text-neutral-200">Usage data</span> — basic operational logs
          (errors, timing) to keep the product working, not used for tracking or advertising.
        </li>
      </ul>

      <h2 className="mt-8 text-base font-semibold text-white">Who we share it with</h2>
      <p className="mt-3">
        We use a small number of third-party services to run the product, and only send them what
        they need to do their job:
      </p>
      <ul className="mt-3 space-y-2">
        <li>
          <span className="font-medium text-neutral-200">Google / YouTube Data API</span> — to fetch
          public video and channel statistics for channels you track.
        </li>
        <li>
          <span className="font-medium text-neutral-200">Google Gemini</span> — to generate the
          written analysis in your daily brief, based on the numbers already computed from your
          tracked channels.
        </li>
        <li>
          <span className="font-medium text-neutral-200">Brevo</span> — to send account emails
          (email verification and password resets).
        </li>
      </ul>
      <p className="mt-3">We don&apos;t sell your data, and we don&apos;t share it for advertising.</p>

      <h2 className="mt-8 text-base font-semibold text-white">Your data</h2>
      <p className="mt-3">
        You can untrack any channel at any time from the Competitors page. If you&apos;d like your
        account and data deleted entirely, contact us using the email below and we&apos;ll remove it.
      </p>

      <h2 className="mt-8 text-base font-semibold text-white">Contact</h2>
      <p className="mt-3">
        Questions about this policy or your data:{" "}
        <a href="mailto:ankushunfolds@gmail.com" className="text-neutral-200 hover:text-white">
          ankushunfolds@gmail.com
        </a>
      </p>
    </div>
  );
}
