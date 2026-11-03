import { memo, useEffect, useState } from "react";

import type { CallController } from "../lib/call";
import { useStore } from "../lib/store";
import { depthOf, formatMs, lastOf } from "../lib/trace";
import type { Span, Turn, VoiceLatency } from "../lib/types";

const KIND_ICON: Record<Span["kind"], string> = { turn: "", node: "◆", llm: "✦", tool: "⚙" };

/** Re-renders every 100 ms while `active`, so running bars grow live. */
function useNow(active: boolean, skew: number): number {
  const [now, setNow] = useState(() => Date.now() + skew);
  useEffect(() => {
    setNow(Date.now() + skew);
    if (!active) return;
    const id = window.setInterval(() => setNow(Date.now() + skew), 100);
    return () => window.clearInterval(id);
  }, [active, skew]);
  return now;
}

function Chip({ label, ms, strong }: { label: string; ms: number | null; strong?: boolean }) {
  if (ms === null) return null;
  return (
    <span className={`latency-chip ${strong ? "latency-chip-strong" : ""}`}>
      <span className="text-slate-400">{label}</span> {formatMs(ms)}
    </span>
  );
}

function VoiceRow({ voice }: { voice: VoiceLatency }) {
  const any = Object.values(voice).some((v) => v !== null);
  if (!any) return <p className="px-1 text-[11px] text-slate-500">Voice latency appears once the reply is spoken.</p>;
  return (
    <div className="flex flex-wrap items-center gap-1.5 px-1">
      <Chip label="end of speech → turn" ms={voice.endOfTurn} />
      <Chip label="speech → text" ms={voice.transcript} />
      <Chip label="LLM first token" ms={voice.firstToken} />
      <Chip label="TTS first audio" ms={voice.firstAudio} />
      <Chip label="caller stops → agent speaks" ms={voice.total} strong />
    </div>
  );
}

function Row({ turn, span, from, width, now }: { turn: Turn; span: Span; from: number; width: number; now: number }) {
  const end = span.end ?? now;
  const left = ((span.start - from) / width) * 100;
  const size = Math.max(0.6, ((end - span.start) / width) * 100);
  const first = span.firstToken !== null ? ((span.firstToken - span.start) / Math.max(1, end - span.start)) * 100 : null;
  const label = span.kind === "llm" ? `LLM ${span.name}` : span.name;
  return (
    <li className="wf-row" data-kind={span.kind} data-status={span.status}>
      <span className="wf-label" style={{ paddingLeft: `${depthOf(turn, span) * 14}px` }} title={span.error ?? span.name}>
        <span className="wf-icon">{KIND_ICON[span.kind]}</span>
        {label}
        {span.status === "blocked" && <span className="wf-flag wf-flag-blocked">blocked by gate</span>}
        {span.status === "cancelled" && <span className="wf-flag wf-flag-cancelled">cancelled</span>}
      </span>
      <span className="wf-track">
        <span className="wf-bar" style={{ left: `${left}%`, width: `${size}%` }}>
          {first !== null && <span className="wf-first" style={{ left: `${first}%` }} title="first token" />}
        </span>
      </span>
      <span className="wf-time">
        {span.status === "running" ? "…" : formatMs(end - span.start)}
        {span.firstToken !== null && <span className="block text-[10px] text-violet-300">1st {formatMs(span.firstToken - span.start)}</span>}
      </span>
    </li>
  );
}

/** Every turn of the call as one bar, height = graph run time. Click one to open it above. */
function TurnStrip({ turns, current, onPick }: { turns: Turn[]; current: Turn; onPick: (t: Turn) => void }) {
  const done = turns.filter((t) => t.end !== null);
  if (done.length < 2) return null;
  const max = Math.max(...done.map((t) => t.end! - t.start));
  const sorted = done.map((t) => t.end! - t.start).sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)]!;
  return (
    <div className="border-t border-white/10 pt-2">
      <div className="mb-1 flex justify-between px-1 text-[10px] uppercase tracking-[0.16em] text-slate-500">
        <span>Every turn · graph run time</span>
        <span className="normal-case tracking-normal">median {formatMs(median)}</span>
      </div>
      <div className="flex h-14 items-end gap-1 px-1">
        {turns.map((t) => {
          const ms = (t.end ?? t.start) - t.start;
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => onPick(t)}
              className="turn-bar"
              data-current={t === current}
              data-status={t.end === null ? "running" : t.interrupted ? "cancelled" : t.status}
              style={{ height: `${Math.max(8, (ms / max) * 100)}%` }}
              title={`Turn ${t.index}: ${formatMs(ms)}${t.interrupted ? ", caller barged in" : ""}`}
            >
              <span>{t.index}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** The latest graph run as a waterfall: every node, model call and tool call on one time axis. */
export const TraceView = memo(function TraceView({ call }: { call: CallController }) {
  const { turns, skew } = useStore(call.trace);
  const [picked, setPicked] = useState<number | null>(null); // a turn index, or null to follow the latest
  const latest = lastOf(turns);
  const turn = (picked !== null && turns.find((t) => t.index === picked)) || latest;
  const running = !!turn && turn.end === null;
  const now = useNow(running, skew);

  useEffect(() => {
    if (turns.length === 0) setPicked(null);
  }, [turns.length]);

  if (!turn) {
    return (
      <section className="card flex min-h-0 flex-col items-center justify-center p-3 text-center">
        <h2 className="text-[11px] font-medium uppercase tracking-[0.18em] text-slate-400">Trace</h2>
        <p className="mt-1 text-sm text-slate-500">Each turn's graph run appears here as a waterfall of timed spans.</p>
      </section>
    );
  }

  const end = turn.end ?? now;
  const width = Math.max(200, end - turn.start);
  const pos = turns.indexOf(turn);
  const go = (delta: number) => {
    const next = turns[pos + delta];
    if (next) setPicked(next === latest ? null : next.index);
  };

  return (
    <section className="card flex min-h-0 flex-col gap-2 overflow-hidden p-3">
      <header className="flex items-center justify-between gap-2 px-1">
        <div className="min-w-0">
          <h2 className="text-[11px] font-medium uppercase tracking-[0.18em] text-slate-400">
            Trace · turn {turn.index}
            {picked === null && running && <span className="ml-2 text-teal-300">live</span>}
          </h2>
          <p className="text-xs text-slate-400">
            Graph run {running ? formatMs(end - turn.start) + "…" : formatMs(end - turn.start)}
            {turn.interrupted && <span className="ml-2 font-semibold text-rose-300">✋ caller barged in</span>}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <button type="button" className="wf-nav" onClick={() => go(-1)} disabled={pos <= 0} aria-label="Previous turn">
            ‹
          </button>
          <button type="button" className="wf-nav" onClick={() => go(1)} disabled={pos >= turns.length - 1} aria-label="Next turn">
            ›
          </button>
        </div>
      </header>
      <VoiceRow voice={turn.voice} />
      <ol className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto pr-1">
        {turn.spans.map((s) => (
          <Row key={s.id} turn={turn} span={s} from={turn.start} width={width} now={now} />
        ))}
      </ol>
      <TurnStrip turns={turns} current={turn} onPick={(t) => setPicked(t === latest ? null : t.index)} />
    </section>
  );
});
