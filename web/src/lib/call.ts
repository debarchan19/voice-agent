import {
  ConnectionState,
  type Participant,
  type RemoteTrack,
  Room,
  RoomEvent,
  Track,
} from "livekit-client";

import { LevelMeter, audioContext } from "./audio";
import { type Signals, createSignals } from "./signals";
import { createStore } from "./store";
import { applyTrace, resetTrace } from "./trace";
import type {
  AgentState,
  Caption,
  CallSummary,
  Connection,
  LogLine,
  Mood,
  PanelState,
  SummaryState,
  TraceMessage,
  TraceView,
} from "./types";

const TOKEN_URL = "/token"; // proxied to the FastAPI token server by Vite
const STATE_TOPIC = "wismo.state"; // wismo/panel.py
const TRACE_TOPIC = "wismo.trace"; // wismo/trace.py and agent.py
const TRANSCRIPTION_TOPIC = "lk.transcription"; // LiveKit Agents' built-in captions
const AGENT_STATE_ATTR = "lk.agent.state";
const WRAP_UP_RPC = "wrap_up"; // agent.py: returns the after-call summary as JSON

const MAX_CAPTIONS = 4;
const MAX_LOG_LINES = 12;
const INTERRUPT_REACTION_MS = 450;
/** Two interruption signals this close together (browser heuristic, then the agent's report) are one barge-in. */
const SAME_INTERRUPT_MS = 3000;
/**
 * "Agent stopped speaking" counts as a barge-in only if the caller was talking AND the agent was
 * still audible at that moment. A natural end of speech has a moment of silence first.
 */
const BARGE_IN_WINDOW_MS = 400;
const CUT_OFF_WINDOW_MS = 200;

export interface CallStatus {
  connection: Connection;
  agentState: AgentState | null;
  muted: boolean;
  error: string | null;
}

export interface PanelView {
  state: PanelState | null;
  log: LogLine[];
  /** Tool calls the verification gate refused this call, and the last one's name. */
  blocked: number;
  blockedTool: string | null;
  /** Wrong last-four attempts this call. Unlike the state's verify_attempts, never reset. */
  failedVerifications: number;
}

/** Bumped once per barge-in; components replay their flash when `count` changes. */
export interface Interrupts {
  count: number;
}

const IDLE_STATUS: CallStatus = { connection: "disconnected", agentState: null, muted: false, error: null };
const EMPTY_PANEL: PanelView = { state: null, log: [], blocked: 0, blockedTool: null, failedVerifications: 0 };

function moodFor(state: AgentState | null): Mood {
  switch (state) {
    case "listening":
    case "thinking":
    case "speaking":
      return state;
    default:
      return "idle";
  }
}

function toneOf(text: string): LogLine["tone"] {
  if (/blocked/i.test(text)) return "blocked";
  if (/failed|not found/i.test(text)) return "warn";
  if (/passed|sent|rescheduled|handed off|requested|opened|escalated/i.test(text)) return "good";
  return undefined;
}

/**
 * Owns the LiveKit room. Low-frequency data (connection, agent state, panel, trace, captions)
 * goes into small stores that only the components showing it subscribe to. Per-frame data lives
 * in `signals`, which the avatar loop reads without involving React.
 *
 * When a call ends, the panel, trace, captions and summary are kept on screen until the next
 * call starts, so the end state can be shown and screenshotted.
 */
export class CallController {
  readonly status = createStore<CallStatus>(IDLE_STATUS);
  readonly panel = createStore<PanelView>(EMPTY_PANEL);
  readonly captions = createStore<Caption[]>([]);
  readonly trace = createStore<TraceView>(resetTrace());
  readonly summary = createStore<SummaryState>({ phase: "idle" });
  readonly interrupts = createStore<Interrupts>({ count: 0 });
  readonly signals: Signals = createSignals();

  private room: Room | null = null;
  private interruptTimer: number | undefined;
  private lastInterruptAt = -Infinity;
  private logId = 0;

  private patchStatus(patch: Partial<CallStatus>): void {
    this.status.set({ ...this.status.get(), ...patch });
  }

  async start(): Promise<void> {
    if (this.room) return;
    // Resume inside the click, before any await, so the browser allows audio.
    void audioContext().resume();
    this.patchStatus({ connection: "connecting", error: null });
    this.panel.set(EMPTY_PANEL);
    this.captions.set([]);
    this.trace.set(resetTrace());
    this.summary.set({ phase: "idle" });

    const room = new Room({ adaptiveStream: true, dynacast: true });
    this.room = room;
    this.wire(room);

    try {
      const res = await fetch(TOKEN_URL);
      if (!res.ok) throw new Error(`Token server returned ${res.status}. Is token_server.py running on port 8000?`);
      const { token, url } = (await res.json()) as { token: string; url: string };
      await room.connect(url, token);
      await room.localParticipant.setMicrophoneEnabled(true);
      this.patchStatus({ connection: "connected", muted: false });
      // The agent may have joined (and set its state) before we subscribed.
      room.remoteParticipants.forEach((p) => this.readAgentState(p));
    } catch (err) {
      console.error(err);
      const message = err instanceof Error ? err.message : String(err);
      await room.disconnect();
      this.reset();
      this.patchStatus({ error: `Couldn't connect. ${message}` });
    }
  }

  /** End call: ask the agent for its after-call summary, then hang up. */
  async stop(): Promise<void> {
    const room = this.room;
    if (!room) return;
    const agent = [...room.remoteParticipants.values()].find((p) => AGENT_STATE_ATTR in p.attributes);
    if (agent && room.state === ConnectionState.Connected) {
      this.patchStatus({ connection: "wrapping_up" });
      this.summary.set({ phase: "writing" });
      try {
        await room.localParticipant.setMicrophoneEnabled(false); // nothing more reaches the agent
        const reply = await room.localParticipant.performRpc({
          destinationIdentity: agent.identity,
          method: WRAP_UP_RPC,
          payload: "",
          responseTimeout: 20000,
        });
        this.summary.set({ phase: "done", note: JSON.parse(reply) as CallSummary });
      } catch (err) {
        console.warn("No call summary", err);
        this.summary.set({ phase: "failed" });
      }
    }
    await room.disconnect();
  }

  async toggleMute(): Promise<void> {
    const room = this.room;
    if (!room) return;
    const muted = !this.status.get().muted;
    await room.localParticipant.setMicrophoneEnabled(!muted);
    this.signals.muted = muted;
    this.patchStatus({ muted });
    if (!muted) this.meterMic(room);
  }

  private wire(room: Room): void {
    // Agent audio plays through LiveKit's own <audio> element, exactly as in index.html.
    // The meter is a read-only tap on the same track.
    room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
      if (track.kind !== Track.Kind.Audio) return;
      document.body.appendChild(track.attach());
      this.signals.agentMeter?.dispose();
      this.signals.agentMeter = new LevelMeter(track.mediaStreamTrack);
    });
    room.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => {
      track.detach().forEach((el) => el.remove());
      if (this.signals.agentMeter?.track === track.mediaStreamTrack) {
        this.signals.agentMeter.dispose();
        this.signals.agentMeter = null;
      }
    });

    room.on(RoomEvent.LocalTrackPublished, () => this.meterMic(room));

    room.on(RoomEvent.ParticipantConnected, (p) => this.readAgentState(p));
    room.on(RoomEvent.ParticipantAttributesChanged, (changed, participant) => {
      if (!participant.isLocal && AGENT_STATE_ATTR in changed) this.readAgentState(participant);
    });

    room.on(RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
      if (topic !== STATE_TOPIC && topic !== TRACE_TOPIC) return;
      try {
        const data = JSON.parse(new TextDecoder().decode(payload));
        if (topic === STATE_TOPIC) this.onPanelState(data as PanelState);
        else this.onTrace(data as TraceMessage);
      } catch (err) {
        console.warn(`Bad ${topic} message`, err);
      }
    });

    // The agent sends both the caller's and its own transcriptions as text streams on this topic.
    room.registerTextStreamHandler(TRANSCRIPTION_TOPIC, async (reader, participantInfo) => {
      const id = reader.info.attributes?.["lk.segment_id"] ?? reader.info.id;
      const who = participantInfo.identity === room.localParticipant.identity ? "user" : "agent";
      let text = "";
      for await (const chunk of reader) {
        text += chunk;
        this.upsertCaption({ id, who, text });
      }
    });

    room.on(RoomEvent.ConnectionStateChanged, (state) => {
      if (state === ConnectionState.Reconnecting || state === ConnectionState.SignalReconnecting) {
        this.patchStatus({ connection: "reconnecting" });
      } else if (state === ConnectionState.Connected && this.status.get().connection === "reconnecting") {
        this.patchStatus({ connection: "connected" });
      }
    });

    room.on(RoomEvent.Disconnected, () => this.reset());
  }

  // ------------------------------------------------------------------ dev replay (lib/replay.ts)

  /** Plays a recorded call through the same handlers a live one uses. Dev only. */
  replayBegin(): void {
    this.panel.set(EMPTY_PANEL);
    this.captions.set([]);
    this.trace.set(resetTrace());
    this.summary.set({ phase: "idle" });
    this.patchStatus({ connection: "connected", agentState: "idle", error: null });
  }

  replayMessage(topic: string, data: unknown): void {
    if (topic === STATE_TOPIC) this.onPanelState(data as PanelState);
    else if (topic === TRACE_TOPIC) this.onTrace(data as TraceMessage);
  }

  replayAgentState(state: AgentState): void {
    this.onAgentState(state);
  }

  replayCaption(id: string, who: Caption["who"], text: string): void {
    this.upsertCaption({ id, who, text });
  }

  replayInterrupt(): void {
    this.signals.mood = "interrupted";
    window.setTimeout(() => (this.signals.mood = moodFor(this.status.get().agentState)), INTERRUPT_REACTION_MS);
    this.onInterrupted();
  }

  replayEnd(summary: CallSummary | null): void {
    if (summary) this.summary.set({ phase: "done", note: summary });
    else this.summary.set({ phase: "writing" });
    if (summary) {
      this.signals.mood = "idle";
      this.patchStatus({ connection: "disconnected", agentState: null });
    }
    else this.patchStatus({ connection: "wrapping_up" });
  }

  private meterMic(room: Room): void {
    const track = room.localParticipant.getTrackPublication(Track.Source.Microphone)?.track?.mediaStreamTrack;
    if (!track || this.signals.micMeter?.track === track) return;
    this.signals.micMeter?.dispose();
    this.signals.micMeter = new LevelMeter(track);
  }

  private readAgentState(participant: Participant): void {
    const value = participant.attributes[AGENT_STATE_ATTR] as AgentState | undefined;
    if (value) this.onAgentState(value);
  }

  private onAgentState(next: AgentState): void {
    const prev = this.status.get().agentState;
    if (next === prev) return;
    this.patchStatus({ agentState: next });
    const s = this.signals;
    const now = performance.now();

    if (next === "thinking" && prev !== "speaking") {
      // Start of the reply gap: the caller's last sound. The avatar loop stops the clock when
      // the agent's audio arrives. (Thinking right after speaking is a tool call mid-reply.)
      s.gapStart = now - s.micActiveAt < 5000 ? s.micActiveAt : now;
    }

    const userTalking =
      !s.muted && (now - s.micActiveAt < BARGE_IN_WINDOW_MS || this.room?.localParticipant.isSpeaking === true);
    const cutOff = now - s.agentActiveAt < CUT_OFF_WINDOW_MS;
    if (prev === "speaking" && next !== "speaking" && userTalking && cutOff) {
      s.gapStart = null;
      s.mood = "interrupted";
      window.clearTimeout(this.interruptTimer);
      this.interruptTimer = window.setTimeout(() => {
        s.mood = moodFor(this.status.get().agentState);
      }, INTERRUPT_REACTION_MS);
      this.onInterrupted();
      return;
    }
    if (s.mood !== "interrupted") s.mood = moodFor(next);
  }

  /**
   * A barge-in, seen either by the browser (instantly, from audio levels) or reported by the agent
   * (LiveKit marks the reply as interrupted). Whichever comes first triggers the flash.
   */
  private onInterrupted(): void {
    const now = performance.now();
    const fresh = now - this.lastInterruptAt > SAME_INTERRUPT_MS;
    this.lastInterruptAt = now;
    if (fresh) this.interrupts.set({ count: this.interrupts.get().count + 1 });

    const list = this.captions.get();
    const i = list.map((c) => c.who).lastIndexOf("agent");
    if (i !== -1 && !list[i]!.cut) {
      const next = list.slice();
      next[i] = { ...list[i]!, cut: true };
      this.captions.set(next);
    }
  }

  private addLog(text: string, tone = toneOf(text)): LogLine[] {
    const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    return [...this.panel.get().log, { id: ++this.logId, time, text, tone }].slice(-MAX_LOG_LINES);
  }

  private onPanelState(state: PanelState): void {
    const view = this.panel.get();
    const failed = state.log?.startsWith("Verification failed") ? 1 : 0;
    this.panel.set({
      ...view,
      state,
      log: state.log ? this.addLog(state.log) : view.log,
      failedVerifications: view.failedVerifications + failed,
    });
  }

  private onTrace(msg: TraceMessage): void {
    this.trace.set(applyTrace(this.trace.get(), msg, Date.now()));
    if (msg.type === "gate") {
      const tool = msg.tool ?? "a tool";
      const view = this.panel.get();
      this.panel.set({
        ...view,
        blocked: view.blocked + 1,
        blockedTool: tool,
        log: this.addLog(`Blocked by verification gate: ${tool}`, "blocked"),
      });
    } else if (msg.type === "voice" && msg.role === "agent" && msg.interrupted) {
      this.onInterrupted();
    }
  }

  private upsertCaption(caption: Caption): void {
    const list = this.captions.get();
    const i = list.findIndex((c) => c.id === caption.id);
    if (i === -1) {
      this.captions.set([...list, caption].slice(-MAX_CAPTIONS));
    } else if (list[i]?.text !== caption.text) {
      const next = list.slice();
      next[i] = { ...caption, cut: list[i]!.cut };
      this.captions.set(next);
    }
  }

  /** Back to idle. Panel, trace, captions and summary stay on screen until the next call. */
  private reset(): void {
    window.clearTimeout(this.interruptTimer);
    this.room = null;
    const s = this.signals;
    s.micMeter?.dispose();
    s.agentMeter?.dispose();
    Object.assign(s, { mood: "idle", micMeter: null, agentMeter: null, muted: false, micLevel: 0, gapStart: null });
    this.status.set({ ...IDLE_STATUS, error: this.status.get().error });
    if (this.summary.get().phase === "writing") this.summary.set({ phase: "failed" });
  }
}
