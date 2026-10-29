import { memo } from "react";

import type { CallController } from "../lib/call";
import { useStore } from "../lib/store";

const LABELS: Record<string, string> = {
  initializing: "Agent joining",
  idle: "Agent ready",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
};

/** Connection status pill: what a viewer sees at a glance in a recording. */
export const StatusPill = memo(function StatusPill({ call }: { call: CallController }) {
  const { connection, agentState } = useStore(call.status);
  const label =
    connection === "connected" ? (agentState ? LABELS[agentState] : "Waiting for agent") : connection[0]!.toUpperCase() + connection.slice(1);
  const tone =
    connection === "disconnected"
      ? "bg-slate-500"
      : connection === "connected"
        ? agentState === "speaking"
          ? "bg-teal-300 shadow-[0_0_10px_#5eead4]"
          : agentState === "thinking"
            ? "bg-violet-300 shadow-[0_0_10px_#c4b5fd]"
            : "bg-sky-300 shadow-[0_0_10px_#7dd3fc]"
        : "bg-amber-300";
  return (
    <div className="flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-3 py-1" role="status" aria-live="polite">
      <span className={`h-2 w-2 rounded-full ${tone}`} />
      <span className="text-[11px] font-medium uppercase tracking-[0.16em] text-slate-300">{label}</span>
    </div>
  );
});

function MicIcon({ off }: { off: boolean }) {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
      {off && <path d="M4 4l16 16" />}
    </svg>
  );
}

export const ControlBar = memo(function ControlBar({ call }: { call: CallController }) {
  const { connection, muted, error } = useStore(call.status);
  const live = connection === "connected" || connection === "reconnecting";
  const busy = connection === "connecting";

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="flex items-center gap-3">
        {live && (
          <button
            type="button"
            onClick={() => void call.toggleMute()}
            aria-pressed={muted}
            className={`flex h-12 items-center gap-2 rounded-full px-5 text-sm font-semibold ring-1 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300 ${
              muted ? "bg-amber-400/15 text-amber-200 ring-amber-300/40" : "bg-white/10 text-slate-100 ring-white/20 hover:bg-white/15"
            }`}
          >
            <MicIcon off={muted} />
            {muted ? "Unmute" : "Mute"}
          </button>
        )}
        <button
          type="button"
          disabled={busy}
          onClick={() => void (live ? call.stop() : call.start())}
          className={`h-12 rounded-full px-8 text-sm font-semibold shadow-lg shadow-black/40 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300 disabled:cursor-wait disabled:opacity-60 ${
            live ? "bg-rose-500 text-white hover:bg-rose-400" : "bg-white text-slate-900 hover:bg-slate-200"
          }`}
        >
          {busy ? "Connecting…" : live ? "End call" : "Start call"}
        </button>
      </div>
      {error && <p className="max-w-md text-center text-sm text-rose-300">{error}</p>}
    </div>
  );
});
