// Microphone capture for real-time voice: turns the browser's audio into 16-bit mono PCM at the rate
// the service expects (16 kHz for Gemini Live, 24 kHz for OpenAI) and posts it in ~100 ms chunks,
// with the loudness for the orb.
class AtlasMicCapture extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.rate = (options && options.processorOptions && options.processorOptions.rate) || 16000;
    this.ratio = sampleRate / this.rate;
    this.pos = 0;
    this.chunk = new Int16Array(this.rate / 10);
    this.fill = 0;
    this.level = 0;
  }

  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input) return true;
    let sum = 0;
    for (let i = 0; i < input.length; i += 1) sum += input[i] * input[i];
    this.level = Math.max(this.level * 0.85, Math.sqrt(sum / input.length));
    // Pick samples at the target spacing, averaging the samples in between (a simple low-pass).
    while (this.pos < input.length) {
      const start = Math.floor(this.pos);
      const end = Math.min(input.length, Math.max(start + 1, Math.floor(this.pos + this.ratio)));
      let v = 0;
      for (let i = start; i < end; i += 1) v += input[i];
      v /= end - start;
      this.chunk[this.fill] = Math.max(-32768, Math.min(32767, Math.round(v * 32767)));
      this.fill += 1;
      if (this.fill === this.chunk.length) {
        this.port.postMessage({ pcm: this.chunk.buffer, level: this.level }, [this.chunk.buffer]);
        this.chunk = new Int16Array(this.rate / 10);
        this.fill = 0;
      }
      this.pos += this.ratio;
    }
    this.pos -= input.length;
    return true;
  }
}

registerProcessor('atlas-mic-capture', AtlasMicCapture);
