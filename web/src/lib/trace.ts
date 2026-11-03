import type { Span, TraceMessage, TraceView, Turn, VoiceLatency } from "./types";

/** Turns kept for the waterfall's back and forward buttons. */
const MAX_TURNS = 30;

export const EMPTY_TRACE: TraceView = { turns: [], skew: 0 };

const NO_VOICE: VoiceLatency = { endOfTurn: null, transcript: null, firstToken: null, firstAudio: null, total: null };

/** A caller turn's end-of-speech timings arrive just before its graph run starts; held here until it does. */
let pendingUser: Pick<VoiceLatency, "endOfTurn" | "transcript"> | null = null;

export function resetTrace(): TraceView {
  pendingUser = null;
  return EMPTY_TRACE;
}

function patchTurn(view: TraceView, index: number, patch: (t: Turn) => Turn): TraceView {
  const turns = view.turns.slice();
  turns[index] = patch(turns[index]!);
  return { ...view, turns };
}

function findTurn(view: TraceView, spanId: string | null): number {
  if (spanId === null) return -1;
  for (let i = view.turns.length - 1; i >= 0; i--) {
    const t = view.turns[i]!;
    if (t.id === spanId || t.spans.some((s) => s.id === spanId)) return i;
  }
  return -1;
}

/** Anything still open in earlier turns was cut off by the caller: LiveKit cancelled the run. */
function closeOpen(turn: Turn, at: number): Turn {
  if (turn.end !== null) return turn;
  return {
    ...turn,
    end: at,
    status: "cancelled",
    spans: turn.spans.map((s) => (s.end === null ? { ...s, end: at, status: "cancelled" } : s)),
  };
}

/** Folds one "wismo.trace" message into the view. Pure apart from `pendingUser`. */
export function applyTrace(view: TraceView, msg: TraceMessage, receivedAt: number): TraceView {
  // Messages arrive after they were sent, so the largest (sent - received) is closest to the true skew.
  const skew = view.turns.length === 0 && view.skew === 0 ? msg.at - receivedAt : Math.max(view.skew, msg.at - receivedAt);
  view = skew === view.skew ? view : { ...view, skew };

  switch (msg.type) {
    case "span": {
      if (msg.phase === "start" && msg.kind === "turn") {
        const last = view.turns[view.turns.length - 1];
        const turns = view.turns.map((t) => closeOpen(t, msg.at));
        const turn: Turn = {
          id: msg.id,
          index: (last?.index ?? 0) + 1,
          start: msg.at,
          end: null,
          status: "running",
          spans: [],
          interrupted: false,
          voice: { ...NO_VOICE, ...pendingUser },
        };
        pendingUser = null;
        return { ...view, turns: [...turns, turn].slice(-MAX_TURNS) };
      }
      if (msg.phase === "start") {
        const i = findTurn(view, msg.parent);
        if (i === -1) return view;
        const span: Span = {
          id: msg.id,
          parent: msg.parent,
          kind: msg.kind,
          name: msg.name,
          start: msg.at,
          end: null,
          status: "running",
          firstToken: null,
        };
        return patchTurn(view, i, (t) => ({ ...t, spans: [...t.spans, span] }));
      }
      const i = findTurn(view, msg.id);
      if (i === -1) return view;
      if (msg.kind === "turn") {
        return patchTurn(view, i, (t) => ({ ...closeOpen({ ...t }, msg.at), end: msg.at, status: msg.status }));
      }
      return patchTurn(view, i, (t) => ({
        ...t,
        spans: t.spans.map((s) => (s.id === msg.id ? { ...s, end: msg.at, status: msg.status, error: msg.error } : s)),
      }));
    }
    case "first_token": {
      const i = findTurn(view, msg.id);
      if (i === -1) return view;
      return patchTurn(view, i, (t) => ({
        ...t,
        spans: t.spans.map((s) => (s.id === msg.id && s.firstToken === null ? { ...s, firstToken: msg.at } : s)),
      }));
    }
    case "voice": {
      const last = view.turns.length - 1;
      if (msg.role === "user") {
        const timings = { endOfTurn: msg.end_of_turn, transcript: msg.transcript };
        const t = view.turns[last];
        // Usually this arrives just before the run starts; if the run beat it, attach it directly.
        if (t && t.voice.endOfTurn === null && msg.at - t.start < 400 && msg.at >= t.start - 50) {
          return patchTurn(view, last, (turn) => ({ ...turn, voice: { ...turn.voice, ...timings } }));
        }
        pendingUser = timings;
        return view;
      }
      if (last === -1) return view; // the greeting: no graph run behind it
      return patchTurn(view, last, (t) => ({
        ...t,
        interrupted: t.interrupted || msg.interrupted,
        voice: { ...t.voice, firstToken: msg.first_token, firstAudio: msg.first_audio, total: msg.total },
      }));
    }
    default:
      return view;
  }
}

/** Graph nodes in the order this turn visited them. */
export function nodePath(turn: Turn | undefined): Span[] {
  return turn ? turn.spans.filter((s) => s.kind === "node") : [];
}

/** How deep a span sits under the turn, for indenting the waterfall. */
export function depthOf(turn: Turn, span: Span): number {
  let depth = 0;
  let parent = span.parent;
  while (parent && parent !== turn.id && depth < 6) {
    const p = turn.spans.find((s) => s.id === parent);
    if (!p) break;
    parent = p.parent;
    depth++;
  }
  return depth;
}

export function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)} s` : `${Math.max(0, Math.round(ms))} ms`;
}

/** `arr.at(-1)`, which the ES2020 target doesn't have. */
export function lastOf<T>(arr: readonly T[]): T | undefined {
  return arr[arr.length - 1];
}
