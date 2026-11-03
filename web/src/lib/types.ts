/** Shapes of the data the backend publishes (wismo/panel.py, wismo/trace.py, agent.py). */

export type AgentName = "Greeter" | "Order Status" | "Resolution";

/** The JSON that wismo/panel.py sends on the "wismo.state" data topic. */
export interface PanelState {
  type: "state";
  agent: AgentName;
  verified: boolean;
  customer: string | null;
  order_id: string | null;
  status: string | null;
  promised_date: string | null;
  verify_attempts: number;
  max_verify_attempts: number;
  notepad: Record<string, string>;
  log: string | null;
}

/** Messages on the "wismo.trace" topic. Times are server epoch milliseconds. */
export type SpanKind = "turn" | "node" | "llm" | "tool";
export type SpanStatus = "running" | "ok" | "error" | "blocked" | "cancelled";

export type TraceMessage =
  | { type: "span"; phase: "start"; id: string; parent: string | null; kind: SpanKind; name: string; at: number }
  | { type: "span"; phase: "end"; id: string; kind: SpanKind; name: string; at: number; status: Exclude<SpanStatus, "running">; error?: string }
  | { type: "first_token"; id: string; at: number }
  | { type: "gate"; tool: string | null; reason: string; at: number }
  | { type: "voice"; role: "user"; at: number; end_of_turn: number | null; transcript: number | null }
  | {
      type: "voice";
      role: "agent";
      at: number;
      interrupted: boolean;
      first_token: number | null;
      first_audio: number | null;
      total: number | null;
    };

export interface Span {
  id: string;
  parent: string | null;
  kind: SpanKind;
  name: string;
  start: number;
  end: number | null;
  status: SpanStatus;
  firstToken: number | null;
  error?: string;
}

/** Voice-pipeline latency around one graph run, in ms. */
export interface VoiceLatency {
  endOfTurn: number | null;
  transcript: number | null;
  firstToken: number | null;
  firstAudio: number | null;
  total: number | null;
}

/** One graph run: everything that happened between the caller finishing and the agent replying. */
export interface Turn {
  id: string;
  index: number;
  start: number;
  end: number | null;
  status: SpanStatus;
  spans: Span[];
  interrupted: boolean;
  voice: VoiceLatency;
}

export interface TraceView {
  turns: Turn[];
  /** Server clock minus browser clock, so running bars can grow in real time. */
  skew: number;
}

/** The after-call note: facts from code plus the model's summary (wismo/summary.py). */
export interface CallSummary {
  outcome: string;
  order_id: string | null;
  customer: string | null;
  verified: boolean;
  ticket_id: number | null;
  email_sent: boolean;
  failed_verifications: number;
  gate_blocks: number;
  turns: number;
  summary: string;
  sentiment: "positive" | "neutral" | "frustrated" | "angry";
  sentiment_reason: string;
  next_steps: string[];
}

export type SummaryState = { phase: "idle" } | { phase: "writing" } | { phase: "done"; note: CallSummary } | { phase: "failed" };

/** LiveKit Agents publishes this as the agent participant's "lk.agent.state" attribute. */
export type AgentState = "initializing" | "idle" | "listening" | "thinking" | "speaking";

export type Connection = "disconnected" | "connecting" | "connected" | "reconnecting" | "wrapping_up";

/** What the avatar is doing. Derived from agent state, mic level and agent audio level. */
export type Mood = "idle" | "listening" | "thinking" | "speaking" | "interrupted";

export interface Caption {
  id: string;
  who: "user" | "agent";
  text: string;
  /** The caller cut this reply off mid-sentence. */
  cut?: boolean;
}

export interface LogLine {
  id: number;
  time: string;
  text: string;
  tone?: "good" | "warn" | "blocked";
}
