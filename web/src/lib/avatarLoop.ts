import type { Signals } from "./signals";

/** The SVG parts the loop moves. Each one is only ever touched by this loop. */
export interface AvatarParts {
  root: SVGSVGElement;
  head: SVGGElement;
  shoulders: SVGGElement;
  brows: SVGGElement;
  lidL: SVGGElement;
  lidR: SVGGElement;
  irisL: SVGGElement;
  irisR: SVGGElement;
  ring: SVGGElement;
  micTip: SVGCircleElement;
  /** Mouth shapes: closed, small, medium, wide, then "o" for the surprised reaction. */
  mouths: SVGGElement[];
}

const TAU = Math.PI * 2;
const MOUTH_O = 4;
/** Levels that move the mouth up to shapes 1, 2 and 3. Going down needs HYSTERESIS less. */
const MOUTH_UP = [0.1, 0.32, 0.6];
const HYSTERESIS = 0.06;
const MOUTH_HOLD = 0.07; // seconds a mouth shape is held, so it can't flicker
const BLINK_TIME = 0.17;
const LID_TRAVEL = 14; // how far the eyelid slides down to fully close the eye
const MIC_ACTIVE = 0.12; // normalised mic level that counts as the caller speaking
const AGENT_AUDIBLE = 0.06;

/** RMS to 0..1. Speech sits roughly between 0.02 and 0.25 RMS. */
const norm = (rms: number, ceiling: number) => Math.min(1, Math.max(0, (rms - 0.01) / ceiling));
/** Frame-rate independent exponential smoothing. */
const ease = (from: number, to: number, tau: number, dt: number) => from + (to - from) * (1 - Math.exp(-dt / tau));
const rand = (a: number, b: number) => a + Math.random() * (b - a);

/**
 * The single requestAnimationFrame loop for the avatar.
 *
 * It reads both analysers once per frame and writes only `transform` and `opacity` attributes,
 * skipping any write whose value hasn't changed. It never touches React state, pauses while the
 * tab is hidden, and switches to a calmer animation under prefers-reduced-motion.
 * Returns a function that stops it.
 */
export function startAvatarLoop(parts: AvatarParts, signals: Signals): () => void {
  const written = new Map<Element, string>();
  const set = (el: Element, attr: "transform" | "opacity", value: string) => {
    if (written.get(el) === value) return;
    written.set(el, value);
    el.setAttribute(attr, value);
  };
  const f = (n: number) => n.toFixed(2);

  const reducedQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  let reduced = reducedQuery.matches;
  const onReduced = () => (reduced = reducedQuery.matches);
  reducedQuery.addEventListener("change", onReduced);

  // Animation state, all local to the loop.
  let mic = 0;
  let agent = 0;
  let loud = 0;
  let ringVis = 0;
  let mouth = 0;
  let mouthSince = 0;
  let nextBlink = rand(1, 3);
  let blinkAt = -1;
  let doubleBlink = false;
  let lookX = 0;
  let lookY = 0;
  let lookTargetX = 0;
  let lookTargetY = 0;
  let nextLook = rand(1, 3);
  let lastMood = "";

  // Debug stats, flushed to the overlay twice a second.
  let frames = 0;
  let workMs = 0;
  let worstMs = 0;
  let statsFrom = performance.now();

  let raf = 0;
  let last = performance.now();

  const frame = (now: number) => {
    raf = requestAnimationFrame(frame);
    const start = performance.now();
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    const t = now / 1000;
    const s = signals;
    const motion = reduced ? 0 : 1;

    if (s.mood !== lastMood) {
      parts.root.dataset.mood = s.mood;
      lastMood = s.mood;
    }

    // ---- audio levels
    const micRaw = s.micMeter && !s.muted ? norm(s.micMeter.read(), 0.12) : 0;
    const agentRaw = s.agentMeter ? norm(s.agentMeter.read(), 0.16) : 0;
    mic = ease(mic, micRaw, micRaw > mic ? 0.04 : 0.15, dt);
    agent = ease(agent, agentRaw, agentRaw > agent ? 0.03 : 0.09, dt);
    s.micLevel = mic;
    if (micRaw > MIC_ACTIVE) s.micActiveAt = now;
    if (agentRaw > AGENT_AUDIBLE) s.agentActiveAt = now;
    if (s.gapStart !== null && agentRaw > AGENT_AUDIBLE) {
      s.lastGapMs = now - s.gapStart;
      s.gapStart = null;
      console.info(`reply gap ${Math.round(s.lastGapMs)} ms`); // same line as tools/reply-gap-snippet.js
    }

    const speaking = s.mood === "speaking";
    loud = ease(loud, speaking ? Math.max(0, agent - 0.45) / 0.55 : 0, 0.12, dt);

    // ---- breathing and head sway (the idle layer, always running underneath the moods)
    const breath = Math.sin((t * TAU) / 4.2) * motion;
    const sway = (Math.sin(t * 0.45) * 1.1 + Math.sin(t * 0.23 + 1.3) * 0.6) * motion;
    const nod = speaking ? Math.sin(t * 5.3) * loud * 1.4 * motion : 0;
    const headRot = sway + nod;
    const headY = breath * 0.9 - loud * 2.5 * motion;
    const head = `translate(0 ${f(headY)}) rotate(${f(headRot)} 200 300)`;
    set(parts.head, "transform", head);
    set(parts.shoulders, "transform", `translate(0 ${f(breath * 1.5)})`);

    // ---- blinking at random 2-5 s intervals, sometimes twice
    if (t >= nextBlink) {
      blinkAt = t;
      doubleBlink = !doubleBlink && Math.random() < 0.15;
      nextBlink = t + (doubleBlink ? 0.28 : rand(2, 5));
    }
    const p = (t - blinkAt) / BLINK_TIME;
    const closed = p >= 0 && p < 1 ? Math.sin(p * Math.PI) : 0;
    const lid = `translate(0 ${f(closed * LID_TRAVEL)})`;
    set(parts.lidL, "transform", lid);
    set(parts.lidR, "transform", lid);

    // ---- small eye movements (the big "thinking" glance is a CSS transition on a parent group)
    if (t >= nextLook) {
      const calm = s.mood === "listening" || s.mood === "speaking";
      lookTargetX = rand(-1.4, 1.4) * (calm ? 0.6 : 1);
      lookTargetY = rand(-0.8, 0.8);
      nextLook = t + rand(1.2, 3.5);
    }
    lookX = ease(lookX, lookTargetX * motion, 0.06, dt);
    lookY = ease(lookY, lookTargetY * motion, 0.06, dt);
    const look = `translate(${f(lookX)} ${f(lookY)})`;
    set(parts.irisL, "transform", look);
    set(parts.irisR, "transform", look);

    // ---- brows lift a little on louder moments
    set(parts.brows, "transform", `translate(0 ${f(-loud * 4)})`);

    // ---- mouth: pick one of the shapes from the smoothed agent level, with hysteresis and a hold
    let target = 0;
    if (s.mood === "interrupted") target = MOUTH_O;
    else if (speaking) {
      target = mouth === MOUTH_O ? 0 : mouth;
      while (target < MOUTH_UP.length && agent > (MOUTH_UP[target] ?? 1)) target++;
      while (target > 0 && agent < (MOUTH_UP[target - 1] ?? 0) - HYSTERESIS) target--;
      if (reduced) target = target > 0 ? 2 : 0;
    }
    if (target !== mouth && t - mouthSince >= MOUTH_HOLD) {
      parts.mouths.forEach((m, i) => set(m, "opacity", i === target ? "1" : "0"));
      mouth = target;
      mouthSince = t;
    }

    // ---- listening ring pulses with the caller's voice
    const listening = s.mood === "listening" || s.mood === "interrupted";
    ringVis = ease(ringVis, listening ? 1 : 0, 0.2, dt);
    const ringScale = 1 + mic * 0.07 * motion;
    set(parts.ring, "opacity", f(ringVis * (0.3 + mic * 0.7)));
    set(parts.ring, "transform", `translate(${f(200 * (1 - ringScale))} ${f(210 * (1 - ringScale))}) scale(${f(ringScale)})`);
    set(parts.micTip, "opacity", f(s.micMeter && !s.muted ? 0.35 + mic * 0.65 : 0.2));

    // ---- debug overlay
    const spent = performance.now() - start;
    frames++;
    workMs += spent;
    worstMs = Math.max(worstMs, spent);
    if (now - statsFrom >= 500) {
      if (s.debugEl) {
        const fps = (frames * 1000) / (now - statsFrom);
        const gap = s.lastGapMs === null ? "–" : `${Math.round(s.lastGapMs)} ms`;
        s.debugEl.textContent =
          `${fps.toFixed(0)} fps\nloop ${(workMs / frames).toFixed(3)} ms avg, ${worstMs.toFixed(2)} max\n` +
          `mood ${s.mood}${reduced ? " (reduced motion)" : ""}\nreply gap ${gap}`;
      }
      frames = 0;
      workMs = 0;
      worstMs = 0;
      statsFrom = now;
    }
  };

  const run = () => {
    if (raf) return;
    last = performance.now();
    statsFrom = last;
    frames = 0;
    raf = requestAnimationFrame(frame);
  };
  const pause = () => {
    cancelAnimationFrame(raf);
    raf = 0;
  };
  const onVisibility = () => (document.hidden ? pause() : run());

  document.addEventListener("visibilitychange", onVisibility);
  if (!document.hidden) run();

  return () => {
    pause();
    document.removeEventListener("visibilitychange", onVisibility);
    reducedQuery.removeEventListener("change", onReduced);
  };
}
