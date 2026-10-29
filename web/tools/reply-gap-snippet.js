// Reply-gap meter for the original index.html, so it can be compared with the new front end.
//
// Paste into the browser DevTools console on index.html AFTER the call has connected.
// It measures exactly what the new front end's debug overlay (press D) shows: the time from your
// last sound to the agent's first audible sound, using read-only analysers with the same
// thresholds. Nothing is connected to the speakers, so playback is unaffected.
(() => {
  const ctx = new AudioContext();
  const meter = (track) => {
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    ctx.createMediaStreamSource(new MediaStream([track])).connect(analyser);
    const buf = new Uint8Array(analyser.fftSize);
    return () => {
      analyser.getByteTimeDomainData(buf);
      let sum = 0;
      for (const b of buf) sum += ((b - 128) / 128) ** 2;
      return Math.sqrt(sum / buf.length);
    };
  };

  // `room` is the page's own top-level variable.
  const mic = meter(room.localParticipant.getTrackPublication("microphone").track.mediaStreamTrack);
  let agent = null;
  for (const p of room.remoteParticipants.values()) {
    for (const pub of p.audioTrackPublications.values()) if (pub.track) agent = meter(pub.track.mediaStreamTrack);
  }
  if (!agent) return console.warn("No agent audio track yet. Wait for the greeting, then paste again.");

  const MIC_ACTIVE_RMS = 0.0244; // same as the new front end's MIC_ACTIVE
  const AGENT_AUDIBLE_RMS = 0.0196; // same as AGENT_AUDIBLE
  let lastMic = -Infinity;
  let gapStart = null;
  let agentState = null;

  room.on("participantAttributesChanged", (changed, p) => {
    const next = changed["lk.agent.state"];
    if (p.isLocal || !next) return;
    // Thinking right after speaking is a tool call mid-reply, not the start of a new gap.
    if (next === "thinking" && agentState !== "speaking") {
      const now = performance.now();
      gapStart = now - lastMic < 5000 ? lastMic : now;
    }
    agentState = next;
  });

  const tick = () => {
    const now = performance.now();
    if (mic() > MIC_ACTIVE_RMS) lastMic = now;
    if (gapStart !== null && agent() > AGENT_AUDIBLE_RMS) {
      console.info(`reply gap ${Math.round(now - gapStart)} ms`);
      gapStart = null;
    }
    requestAnimationFrame(tick);
  };
  tick();
  console.info("Reply-gap meter running. Each agent reply logs one line.");
})();
