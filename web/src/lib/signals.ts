import type { LevelMeter } from "./audio";
import type { Mood } from "./types";

/**
 * Per-frame data shared between the call controller and the avatar loop.
 *
 * This is a plain mutable object, deliberately outside React: the loop reads and writes it 60
 * times a second, and none of it should ever cause a re-render.
 */
export interface Signals {
  mood: Mood;
  micMeter: LevelMeter | null;
  agentMeter: LevelMeter | null;
  muted: boolean;
  /** Smoothed mic level, 0 to 1. Written by the avatar loop. */
  micLevel: number;
  /** performance.now() when the mic was last above the speech threshold. Written by the loop. */
  micActiveAt: number;
  /** performance.now() when the agent's audio was last audible. Written by the loop. */
  agentActiveAt: number;
  /** Start of the current reply gap: the caller's last sound before the agent began thinking. */
  gapStart: number | null;
  /** Last measured gap from the caller's last sound to the agent's first audio, in ms. */
  lastGapMs: number | null;
  /** The debug overlay's text element, when it is open. */
  debugEl: HTMLElement | null;
}

export function createSignals(): Signals {
  return {
    mood: "idle",
    micMeter: null,
    agentMeter: null,
    muted: false,
    micLevel: 0,
    micActiveAt: -Infinity,
    agentActiveAt: -Infinity,
    gapStart: null,
    lastGapMs: null,
    debugEl: null,
  };
}
