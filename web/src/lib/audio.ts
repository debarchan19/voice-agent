/**
 * Read-only audio level meters.
 *
 * Each meter taps a MediaStreamTrack into an AnalyserNode and nothing else: the analyser is never
 * connected to the AudioContext destination, so it can't change what you hear or add latency.
 * The agent's voice keeps playing through the normal <audio> element LiveKit attaches.
 */

const FFT_SIZE = 256;

let shared: AudioContext | null = null;

/** The one AudioContext for the page. Create or resume it inside a click handler. */
export function audioContext(): AudioContext {
  shared ??= new AudioContext();
  return shared;
}

export class LevelMeter {
  readonly track: MediaStreamTrack;
  private readonly source: MediaStreamAudioSourceNode;
  private readonly analyser: AnalyserNode;
  private readonly buffer: Uint8Array;

  constructor(track: MediaStreamTrack) {
    const ctx = audioContext();
    this.track = track;
    this.source = ctx.createMediaStreamSource(new MediaStream([track]));
    this.analyser = ctx.createAnalyser();
    this.analyser.fftSize = FFT_SIZE;
    this.analyser.smoothingTimeConstant = 0;
    this.source.connect(this.analyser);
    this.buffer = new Uint8Array(this.analyser.fftSize);
  }

  /** RMS of the latest time-domain frame, roughly 0 (silence) to 0.3 (loud speech). */
  read(): number {
    this.analyser.getByteTimeDomainData(this.buffer);
    let sum = 0;
    for (let i = 0; i < this.buffer.length; i++) {
      const v = ((this.buffer[i] ?? 128) - 128) / 128;
      sum += v * v;
    }
    return Math.sqrt(sum / this.buffer.length);
  }

  dispose(): void {
    this.source.disconnect();
  }
}
