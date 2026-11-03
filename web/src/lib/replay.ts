import type { CallController } from "./call";
import type { AgentState, CallSummary } from "./types";

/**
 * Dev only: replays a call recorded by `python scripts/text_call.py --record web/public/replay.json`.
 * Open http://localhost:5173/?replay (or ?replay=other.json, &speed=2). No backend or microphone
 * needed, so the layout can be rehearsed and recorded on its own. There's no audio, so Sam's
 * mouth stays still; everything else runs through the same handlers as a live call.
 */
type ReplayEvent = { t: number } & (
  | { topic: string; data: unknown }
  | { agent_state: AgentState }
  | { caption: { who: "user" | "agent"; text: string } }
  | { interrupt: true }
  | { wrap_up: true }
  | { summary: CallSummary }
);

export async function startReplay(
  call: CallController,
  file: string,
  speed: number,
  current: () => boolean,
): Promise<() => void> {
  const res = await fetch(`/${file}`);
  if (!res.ok) throw new Error(`No ${file} in web/public. Record one with scripts/text_call.py --record.`);
  const events = (await res.json()) as ReplayEvent[];
  const timers: number[] = [];
  if (!current()) return () => {}; // superseded while loading
  let captionId = 0;
  call.replayBegin();
  for (const e of events) {
    timers.push(
      window.setTimeout(() => {
        if ("topic" in e) call.replayMessage(e.topic, e.data);
        else if ("agent_state" in e) call.replayAgentState(e.agent_state);
        else if ("caption" in e) call.replayCaption(`replay-${++captionId}`, e.caption.who, e.caption.text);
        else if ("interrupt" in e) call.replayInterrupt();
        else if ("wrap_up" in e) call.replayEnd(null);
        else if ("summary" in e) call.replayEnd(e.summary);
      }, e.t / speed),
    );
  }
  return () => timers.forEach((id) => window.clearTimeout(id));
}
