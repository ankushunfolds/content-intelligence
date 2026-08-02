"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";

const NICHES = [
  "AI / Technology",
  "Business",
  "Creator Education",
  "Productivity",
  "Finance",
  "Gaming",
  "Marketing",
  "Personal Development",
  "Health & Fitness",
  "Cooking / Food",
  "Travel",
  "Beauty & Fashion",
  "Education / Study",
  "Parenting & Family",
  "DIY / Home",
  "Sports",
  "Music",
  "Entertainment / Pop Culture",
  "News & Commentary",
  "Science",
  "Real Estate",
  "Automotive",
  "Comedy",
  "Art & Design",
  "Other",
];

/** Section 6: ask for exactly three things. Nothing more. */
export default function OnboardingPage() {
  const router = useRouter();
  const [ownChannel, setOwnChannel] = useState("");
  const [competitors, setCompetitors] = useState<string[]>(["", "", "", "", ""]);
  const [niche, setNiche] = useState(NICHES[0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) router.replace("/");
  }, [router]);

  function updateCompetitor(index: number, value: string) {
    setCompetitors((prev) => prev.map((item, i) => (i === index ? value : item)));
  }

  const filled = competitors.filter((c) => c.trim()).length;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.onboarding(
        ownChannel.trim(),
        competitors.map((c) => c.trim()).filter(Boolean),
        niche
      );
      // The first pipeline run happens in the background; the dashboard polls for it.
      router.push("/dashboard?fresh=1");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not set up your account");
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl px-6 py-16">
      <div className="eyebrow">Setup</div>
      <h1 className="mt-3 text-2xl font-semibold tracking-tight text-white">
        Three things and you&apos;re done
      </h1>
      <p className="mt-2 text-sm text-neutral-500">
        We&apos;ll pull the last few weeks of video data for every channel and have your first brief
        ready in under a minute.
      </p>

      <form onSubmit={submit} className="mt-10 space-y-8">
        <section>
          <label className="eyebrow">1 · Your YouTube channel</label>
          <input
            required
            value={ownChannel}
            onChange={(e) => setOwnChannel(e.target.value)}
            placeholder="https://youtube.com/@yourchannel"
            className="field mt-2"
          />
          <p className="mt-1.5 text-xs text-neutral-600">
            A URL, an @handle, or a channel ID all work.
          </p>
        </section>

        <section>
          <label className="eyebrow">
            2 · Competitors{" "}
            <span className="ml-1 font-normal normal-case tracking-normal text-neutral-600">
              {filled} of 10
            </span>
          </label>
          <div className="mt-2 space-y-2">
            {competitors.map((value, index) => (
              <input
                key={index}
                value={value}
                onChange={(e) => updateCompetitor(index, e.target.value)}
                placeholder={`Competitor ${index + 1}`}
                className="field"
              />
            ))}
          </div>
          {competitors.length < 10 ? (
            <button
              type="button"
              onClick={() => setCompetitors((prev) => [...prev, ""])}
              className="mt-2 text-xs text-neutral-500 hover:text-neutral-300"
            >
              + Add another
            </button>
          ) : null}
          <p className="mt-2 text-xs text-neutral-600">
            Five is enough to start. More competitors sharpen trend detection.
          </p>
        </section>

        <section>
          <label className="eyebrow">3 · Your niche</label>
          <div className="mt-2 flex flex-wrap gap-2">
            {NICHES.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setNiche(option)}
                className={`rounded-lg border px-3 py-1.5 text-sm transition-colors ${
                  niche === option
                    ? "border-signal bg-signal/10 text-signal"
                    : "border-ink-700 text-neutral-400 hover:border-ink-600 hover:text-neutral-200"
                }`}
              >
                {option}
              </button>
            ))}
          </div>
          {/* Say plainly what this does today. It's stored but nothing reads it
              yet, and implying it tunes the results would be a promise the
              product doesn't currently keep. */}
          <p className="mt-2 text-xs text-neutral-600">
            Saved to your account for upcoming features — it doesn&apos;t affect your scores yet.
          </p>
        </section>

        {error ? <p className="text-sm text-fall">{error}</p> : null}

        <button type="submit" disabled={busy || !ownChannel.trim()} className="btn-primary w-full">
          {busy ? "Collecting data…" : "Build my intelligence"}
        </button>
      </form>
    </div>
  );
}
