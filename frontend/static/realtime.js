// Real-time voice through Google's Gemini Live API, like the Gemini app's Live mode: the microphone
// streams to Gemini, Gemini answers with its own voice, and you can talk over it to interrupt.
// The browser connects straight to Google over a secure WebSocket with the user's own Gemini key;
// nothing passes through ATLAS's server. Loaded only when the Live screen opens.
(function () {
  'use strict';

  const HOST = 'wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent';
  const VOICES = ['Puck', 'Charon', 'Kore', 'Fenrir', 'Aoede', 'Leda', 'Orus', 'Zephyr'];

  function toBase64(bytes) {
    let s = '';
    for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(s);
  }

  function fromBase64(b64) {
    const s = atob(b64);
    const out = new Uint8Array(s.length);
    for (let i = 0; i < s.length; i += 1) out[i] = s.charCodeAt(i);
    return out;
  }

  /**
   * Starts a session. opts: key, model, voice, system, worklet (URL of live-worklet.js) and
   * on: { state(s), level(x), heard(text), said(text), turn({ user, model }), ended(reason) }.
   * States: connecting, listening, speaking. Resolves once the microphone is on.
   */
  async function start(opts) {
    const on = opts.on;
    let ws = null;
    let ready = false;
    let ended = false;
    let handle = null;
    let reconnects = 0;
    let muted = false;
    let dropAudio = false;
    let fresh = true;
    let userText = '';
    let modelText = '';
    let nextTime = 0;
    let frameTimer = null;
    const sources = new Set();

    // One audio context for the microphone and the voice, created inside the tap that started Live
    // so phones allow sound.
    const ctx = new AudioContext();
    await ctx.resume();
    let mic;
    try {
      mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
    } catch (err) {
      ctx.close();
      throw err;
    }
    await ctx.audioWorklet.addModule(opts.worklet);
    const node = new AudioWorkletNode(ctx, 'atlas-mic-capture');
    const silent = ctx.createGain();
    silent.gain.value = 0;
    ctx.createMediaStreamSource(mic).connect(node);
    node.connect(silent).connect(ctx.destination);
    node.port.onmessage = (e) => {
      on.level(muted ? 0 : e.data.level);
      if (!muted) send({ realtimeInput: { audio: { data: toBase64(new Uint8Array(e.data.pcm)), mimeType: 'audio/pcm;rate=16000' } } });
    };

    function send(obj) {
      if (ws && ready && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
    }

    function flush() {
      sources.forEach((s) => { try { s.stop(); } catch { /* already stopped */ } });
      sources.clear();
      nextTime = 0;
    }

    function play(b64, mime) {
      if (dropAudio || ended) return;
      const rate = Number((/rate=(\d+)/.exec(mime || '') || [])[1]) || 24000;
      const bytes = fromBase64(b64);
      const n = bytes.byteLength >> 1;
      if (!n) return;
      const view = new DataView(bytes.buffer, bytes.byteOffset, n * 2);
      const buffer = ctx.createBuffer(1, n, rate);
      const channel = buffer.getChannelData(0);
      for (let i = 0; i < n; i += 1) channel[i] = view.getInt16(i * 2, true) / 32768;
      const src = ctx.createBufferSource();
      src.buffer = buffer;
      src.connect(ctx.destination);
      const at = Math.max(ctx.currentTime + 0.04, nextTime);
      src.start(at);
      nextTime = at + buffer.duration;
      sources.add(src);
      src.onended = () => {
        sources.delete(src);
        if (!sources.size && !ended) on.state('listening');
      };
      on.state('speaking');
    }

    function finishTurn() {
      if (userText.trim() || modelText.trim()) on.turn({ user: userText.trim(), model: modelText.trim() });
      fresh = true;
      dropAudio = false;
    }

    function newTurnIfNeeded() {
      if (!fresh) return;
      fresh = false;
      userText = '';
      modelText = '';
      on.heard('');
      on.said('');
    }

    function onMessage(msg) {
      if (msg.setupComplete) {
        ready = true;
        reconnects = 0;
        on.state(sources.size ? 'speaking' : 'listening');
        return;
      }
      if (msg.sessionResumptionUpdate) {
        if (msg.sessionResumptionUpdate.resumable && msg.sessionResumptionUpdate.newHandle) handle = msg.sessionResumptionUpdate.newHandle;
        return;
      }
      if (msg.goAway) {
        // Google ends each connection after a few minutes; carry on in a new one with the same conversation.
        if (handle) connect();
        return;
      }
      const sc = msg.serverContent;
      if (!sc) return;
      if (sc.interrupted) {
        flush();
        dropAudio = false;
        on.state('listening');
      }
      if (sc.inputTranscription && sc.inputTranscription.text) {
        newTurnIfNeeded();
        userText += sc.inputTranscription.text;
        on.heard(userText.trim());
      }
      if (sc.outputTranscription && sc.outputTranscription.text) {
        newTurnIfNeeded();
        modelText += sc.outputTranscription.text;
        on.said(modelText.trim());
      }
      const parts = (sc.modelTurn && sc.modelTurn.parts) || [];
      for (const part of parts) if (part.inlineData && /^audio\//.test(part.inlineData.mimeType || 'audio/')) play(part.inlineData.data, part.inlineData.mimeType);
      if (sc.turnComplete) finishTurn();
    }

    function connect() {
      const old = ws;
      if (old) { old.onclose = null; old.onmessage = null; try { old.close(1000); } catch { /* closed */ } }
      ready = false;
      on.state('connecting');
      const socket = new WebSocket(HOST + '?key=' + encodeURIComponent(opts.key));
      ws = socket;
      socket.binaryType = 'arraybuffer';
      socket.onopen = () => {
        socket.send(JSON.stringify({ setup: {
          model: 'models/' + opts.model,
          generationConfig: { responseModalities: ['AUDIO'], speechConfig: { voiceConfig: { prebuiltVoiceConfig: { voiceName: opts.voice } } } },
          systemInstruction: { parts: [{ text: opts.system }] },
          inputAudioTranscription: {},
          outputAudioTranscription: {},
          contextWindowCompression: { slidingWindow: {} },
          sessionResumption: handle ? { handle } : {},
        } }));
      };
      socket.onmessage = (e) => {
        let msg;
        try { msg = JSON.parse(typeof e.data === 'string' ? e.data : new TextDecoder().decode(e.data)); } catch { return; }
        onMessage(msg);
      };
      socket.onclose = (e) => {
        if (ended || ws !== socket) return;
        // A dropped connection after the session started carries on with the same conversation.
        if (ready && handle && reconnects < 3) { reconnects += 1; connect(); return; }
        stop(e.reason ? 'Google closed the connection: ' + e.reason : 'The connection to Google closed' + (ready ? '.' : ' before the session started (code ' + e.code + '). Check your Gemini key and internet.'));
      };
    }

    function stop(reason) {
      if (ended) return;
      ended = true;
      clearInterval(frameTimer);
      flush();
      if (ws) { ws.onclose = null; try { ws.close(1000); } catch { /* closed */ } }
      mic.getTracks().forEach((t) => t.stop());
      ctx.close();
      on.level(0);
      on.ended(reason || '');
    }

    connect();

    return {
      end: () => stop(''),
      /** Mute or unmute the microphone (the session stays open). */
      setMuted(m) {
        muted = !!m;
        if (muted) send({ realtimeInput: { audioStreamEnd: true } });
      },
      /** Stop the current spoken answer; the rest of that answer is skipped. */
      stopSpeaking() {
        if (!sources.size) return;
        flush();
        dropAudio = true;
        on.state('listening');
      },
      /** Send a picture of this video element about once a second, or stop with null. */
      setVideo(video) {
        clearInterval(frameTimer);
        if (!video) return;
        const canvas = document.createElement('canvas');
        frameTimer = setInterval(() => {
          if (!ready || !video.videoWidth) return;
          const scale = Math.min(1, 768 / Math.max(video.videoWidth, video.videoHeight));
          canvas.width = Math.round(video.videoWidth * scale);
          canvas.height = Math.round(video.videoHeight * scale);
          canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
          send({ realtimeInput: { video: { data: canvas.toDataURL('image/jpeg', 0.7).split(',')[1], mimeType: 'image/jpeg' } } });
        }, 1000);
      },
      /** A typed message, answered aloud like a spoken one. */
      sendText(text) {
        fresh = true;
        newTurnIfNeeded();
        userText = text;
        on.heard(text);
        send({ clientContent: { turns: [{ role: 'user', parts: [{ text }] }], turnComplete: true } });
      },
    };
  }

  window.AtlasRealtime = { start, VOICES, supported: () => !!(window.WebSocket && window.AudioContext && window.AudioWorkletNode && navigator.mediaDevices && navigator.mediaDevices.getUserMedia) };
})();
