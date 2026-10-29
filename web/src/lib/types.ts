/** Shapes of the data the backend already publishes. Nothing here is new on the server. */

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
  notepad: Record<string, string>;
  log: string | null;
}

/** LiveKit Agents publishes this as the agent participant's "lk.agent.state" attribute. */
export type AgentState = "initializing" | "idle" | "listening" | "thinking" | "speaking";

export type Connection = "disconnected" | "connecting" | "connected" | "reconnecting";

/** What the avatar is doing. Derived from agent state, mic level and agent audio level. */
export type Mood = "idle" | "listening" | "thinking" | "speaking" | "interrupted";

export interface Caption {
  id: string;
  who: "user" | "agent";
  text: string;
}

export interface LogLine {
  id: number;
  time: string;
  text: string;
}
