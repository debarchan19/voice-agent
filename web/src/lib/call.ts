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
import type { AgentState, Caption, Connection, LogLine, Mood, PanelState } from "./types";

const TOKEN_URL = "/token"; // proxied to the FastAPI token server by Vite
const STATE_TOPIC = "wismo.state"; // wismo/panel.py
const TRANSCRIPTION_TOPIC = "lk.transcription"; // LiveKit Agents' built-in captions
const AGENT_STATE_ATTR = "lk.agent.state";

const MAX_CAPTIONS = 4;
const MAX_LOG_LINES = 8;
const INTERRUPT_REACTION_MS = 450;
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
}

const IDLE_STATUS: CallStatus = { connection: "disconnected", agentState: null, muted: false, error: null };
const EMPTY_PANEL: PanelView = { state: null, log: [] };

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

/**
 * Owns the LiveKit room. Low-frequency data (connection, agent state, panel, captions) goes into
 * small stores that only the components showing it subscribe to. Per-frame data lives in
 * `signals`, which the avatar loop reads without involving React.
 */
export class CallController {
  readonly status = createStore<CallStatus>(IDLE_STATUS);
  readonly panel = createStore<PanelView>(EMPTY_PANEL);
  readonly captions = createStore<Caption[]>([]);
  readonly signals: Signals = createSignals();

  private room: Room | null = null;
  private interruptTimer: number | undefined;
  private logId = 0;

  private patchStatus(patch: Partial<CallStatus>): void {
    this.status.set({ ...this.status.get(), ...patch });
  }

  async start(): Promise<void> {
    if (this.room) return;
    // Resume inside the click, before any await, so the browser allows audio.
    void audioContext().resume();
    this.patchStatus({ connection: "connecting", error: null });

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

  async stop(): Promise<void> {
    await this.room?.disconnect();
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
      if (topic !== STATE_TOPIC) return;
      try {
        this.onPanelState(JSON.parse(new TextDecoder().decode(payload)) as PanelState);
      } catch (err) {
        console.warn("Bad call state message", err);
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
      return;
    }
    if (s.mood !== "interrupted") s.mood = moodFor(next);
  }

  private onPanelState(state: PanelState): void {
    const { log } = this.panel.get();
    let nextLog = log;
    if (state.log) {
      const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      nextLog = [...log, { id: ++this.logId, time, text: state.log }].slice(-MAX_LOG_LINES);
    }
    this.panel.set({ state, log: nextLog });
  }

  private upsertCaption(caption: Caption): void {
    const list = this.captions.get();
    const i = list.findIndex((c) => c.id === caption.id);
    if (i === -1) {
      this.captions.set([...list, caption].slice(-MAX_CAPTIONS));
    } else if (list[i]?.text !== caption.text) {
      const next = list.slice();
      next[i] = caption;
      this.captions.set(next);
    }
  }

  private reset(): void {
    window.clearTimeout(this.interruptTimer);
    this.room = null;
    const s = this.signals;
    s.micMeter?.dispose();
    s.agentMeter?.dispose();
    Object.assign(s, { mood: "idle", micMeter: null, agentMeter: null, muted: false, micLevel: 0, gapStart: null });
    this.status.set({ ...IDLE_STATUS, error: this.status.get().error });
    this.panel.set(EMPTY_PANEL);
    this.captions.set([]);
  }
}
