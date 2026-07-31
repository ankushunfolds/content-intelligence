"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { TrackedChannel } from "@/lib/types";
import { CompetitorCard } from "@/components/CompetitorCard";
import { EmptyState, SectionHeader, Shell } from "@/components/Shell";

export default function CompetitorsPage() {
  return (
    <Shell>
      <Competitors />
    </Shell>
  );
}

function Competitors() {
  const [channels, setChannels] = useState<TrackedChannel[] | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setChannels(await api.trackedChannels());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load your channels");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function add(event: React.FormEvent) {
    event.preventDefault();
    if (!input.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.trackChannel(input.trim());
      setInput("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add that channel");
    } finally {
      setBusy(false);
    }
  }

  async function remove(channelId: number) {
    setChannels((prev) => prev?.filter((c) => c.id !== channelId) ?? null);
    try {
      await api.untrackChannel(channelId);
    } catch {
      await load(); // put it back if the delete failed
    }
  }

  const own = channels?.filter((c) => c.type === "own") ?? [];
  const competitors = channels?.filter((c) => c.type === "competitor") ?? [];

  return (
    <div>
      <div className="eyebrow">Competitor tracker</div>
      <h1 className="mt-2 text-xl font-semibold tracking-tight text-white">
        Channels you&apos;re watching
      </h1>

      <form onSubmit={add} className="mt-6 flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Add a competitor — URL, @handle, or channel ID"
          className="field flex-1"
        />
        <button type="submit" disabled={busy || !input.trim()} className="btn-primary shrink-0">
          {busy ? "Adding…" : "Track"}
        </button>
      </form>

      {error ? <p className="mt-3 text-sm text-fall">{error}</p> : null}

      {channels === null ? (
        <p className="mt-10 text-sm text-neutral-600">Loading…</p>
      ) : (
        <>
          {own.length ? (
            <section className="mt-10">
              <SectionHeader icon="🎬" title="Your channel" />
              <div className="grid gap-3 sm:grid-cols-2">
                {own.map((channel) => (
                  <CompetitorCard key={channel.id} channel={channel} />
                ))}
              </div>
            </section>
          ) : null}

          <section className="mt-10">
            <SectionHeader
              icon="👀"
              title="Competitors"
              caption={`${competitors.length} of 10 tracked. Metrics are relative to each channel's own baseline.`}
            />
            {competitors.length ? (
              <div className="grid gap-3 sm:grid-cols-2">
                {competitors.map((channel) => (
                  <CompetitorCard key={channel.id} channel={channel} onRemove={remove} />
                ))}
              </div>
            ) : (
              <EmptyState
                title="No competitors yet"
                body="Add five channels that make content near yours. Trend detection gets sharper with each one."
              />
            )}
          </section>
        </>
      )}
    </div>
  );
}
