// Real-time voice, like the Gemini app's Live mode and ChatGPT's voice mode: the microphone streams
// to the service, it answers in its own voice, and you can talk over it to interrupt. Two services:
// - Google's Gemini Live API, with the user's own Gemini key (free tier available);
// - OpenAI's Realtime API, with the user's own OpenAI key (paid, used only when the user picks it).
// The browser connects straight to the service over a secure WebSocket with the user's own key;
// nothing passes through ATLAS's server. Loaded only when the Live screen opens.
(function () {
  'use strict';

  const SERVICES = {
    gemini: {
      label: 'Google Gemini',
      voices: ['Puck', 'Charon', 'Kore', 'Fenrir', 'Aoede', 'Leda', 'Orus', 'Zephyr'],
      micRate: 16000,
      connect: (o) => new WebSocket('wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key=' + encodeURIComponent(o.key)),
    },
    openai: {
      label: 'ChatGPT (OpenAI)',
      voices: ['marin', 'cedar', 'alloy', 'ash', 'ballad', 'coral', 'echo', 'sage', 'shimmer', 'verse'],
      micRate: 24000,
      // Browsers cannot set headers on a WebSocket, so OpenAI takes the key as a subprotocol.
      connect: (o) => new WebSocket('wss://api.openai.com/v1/realtime?model=' + encodeURIComponent(o.model), ['realtime', 'openai-insecure-api-key.' + o.key]),
    },
  };

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
   * Starts a session. opts: service ('gemini' or 'openai'), key, model, voice, system, worklet (URL
   * of live-worklet.js) and on: { state(s), level(x), heard(text), said(text), turn({ user, model }),
   * ended(reason, info) }, where info.step is 'connect' (the service never finished setting up) or
   * 'session' (the connection dropped later) and info.code is the WebSocket close code. States:
   * connecting, listening, speaking. Resolves once the microphone is on; a microphone error has
   * err.step = 'microphone'.
   */
  async function start(opts) {
    const service = SERVICES[opts.service];
    const isGemini = opts.service === 'gemini';
    const on = opts.on;
    let ws = null;
    let ready = false;
    // True once the service has accepted the key and settings (Gemini setupComplete, OpenAI session.created).
    let accepted = false;
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
    let video = null;
    let lastError = '';
    let awaitingTranscript = false;
    let finishTimer = null;
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
      err.step = 'microphone';
      throw err;
    }
    try {
      await ctx.audioWorklet.addModule(opts.worklet);
    } catch (err) {
      mic.getTracks().forEach((t) => t.stop());
      ctx.close();
      err.step = 'audio';
      throw err;
    }
    const node = new AudioWorkletNode(ctx, 'atlas-mic-capture', { processorOptions: { rate: service.micRate } });
    const silent = ctx.createGain();
    silent.gain.value = 0;
    ctx.createMediaStreamSource(mic).connect(node);
    node.connect(silent).connect(ctx.destination);
    node.port.onmessage = (e) => {
      on.level(muted ? 0 : e.data.level);
      if (muted) return;
      const data = toBase64(new Uint8Array(e.data.pcm));
      send(isGemini ? { realtimeInput: { audio: { data, mimeType: 'audio/pcm;rate=16000' } } } : { type: 'input_audio_buffer.append', audio: data });
    };

    function send(obj) {
      if (ws && ready && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
    }

    /** The current camera or screen picture as base64 JPEG, or null. */
    function picture() {
      if (!video || !video.videoWidth) return null;
      const canvas = document.createElement('canvas');
      const scale = Math.min(1, 768 / Math.max(video.videoWidth, video.videoHeight));
      canvas.width = Math.round(video.videoWidth * scale);
      canvas.height = Math.round(video.videoHeight * scale);
      canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
      return canvas.toDataURL('image/jpeg', 0.7).split(',')[1];
    }

    /** OpenAI has no video stream: the picture goes with each thing the user says or types. */
    function sendPictureToOpenAI() {
      const data = isGemini ? null : picture();
      if (data) send({ type: 'conversation.item.create', item: { type: 'message', role: 'user', content: [{ type: 'input_image', image_url: 'data:image/jpeg;base64,' + data }] } });
    }

    function flush() {
      sources.forEach((s) => { try { s.stop(); } catch { /* already stopped */ } });
      sources.clear();
      nextTime = 0;
    }

    function play(b64, rate) {
      if (dropAudio || ended || !b64) return;
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
      clearTimeout(finishTimer);
      if (fresh) return;
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

    function onGemini(msg) {
      if (msg.setupComplete) {
        ready = true;
        accepted = true;
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
      for (const part of parts) {
        const data = part.inlineData;
        if (data && /^audio\//.test(data.mimeType || 'audio/')) play(data.data, Number((/rate=(\d+)/.exec(data.mimeType || '') || [])[1]) || 24000);
      }
      if (sc.turnComplete) finishTurn();
    }

    function onOpenAI(msg) {
      switch (msg.type) {
        case 'session.created':
        case 'session.updated':
          accepted = true;
          on.state(sources.size ? 'speaking' : 'listening');
          break;
        case 'input_audio_buffer.speech_started':
          // The user started talking: stop the voice at once (OpenAI cancels the rest of the answer).
          flush();
          finishTurn();
          newTurnIfNeeded();
          on.state('listening');
          sendPictureToOpenAI();
          break;
        case 'input_audio_buffer.committed':
          awaitingTranscript = true;
          break;
        case 'conversation.item.input_audio_transcription.delta':
          newTurnIfNeeded();
          userText += msg.delta || '';
          on.heard(userText.trim());
          break;
        case 'conversation.item.input_audio_transcription.completed':
          newTurnIfNeeded();
          userText = msg.transcript || userText;
          on.heard(userText.trim());
          awaitingTranscript = false;
          if (finishTimer) finishTurn();
          break;
        case 'conversation.item.input_audio_transcription.failed':
          awaitingTranscript = false;
          if (finishTimer) finishTurn();
          break;
        case 'response.output_audio.delta':
        case 'response.audio.delta':
          play(msg.delta, 24000);
          break;
        case 'response.output_audio_transcript.delta':
        case 'response.audio_transcript.delta':
          newTurnIfNeeded();
          modelText += msg.delta || '';
          on.said(modelText.trim());
          break;
        case 'response.done':
          // What the user said is written down separately and can arrive a moment later.
          if (awaitingTranscript) finishTimer = setTimeout(finishTurn, 2500); else finishTurn();
          dropAudio = false;
          break;
        case 'error':
          if (msg.error && msg.error.code !== 'response_cancel_not_active') lastError = (msg.error && msg.error.message) || 'error';
          break;
        default:
      }
    }

    function connect() {
      const old = ws;
      if (old) { old.onclose = null; old.onmessage = null; try { old.close(1000); } catch { /* closed */ } }
      ready = false;
      on.state('connecting');
      const socket = service.connect(opts);
      ws = socket;
      socket.binaryType = 'arraybuffer';
      socket.onopen = () => {
        if (isGemini) {
          socket.send(JSON.stringify({ setup: {
            model: 'models/' + opts.model,
            generationConfig: { responseModalities: ['AUDIO'], speechConfig: { voiceConfig: { prebuiltVoiceConfig: { voiceName: opts.voice } } } },
            systemInstruction: { parts: [{ text: opts.system }] },
            inputAudioTranscription: {},
            outputAudioTranscription: {},
            contextWindowCompression: { slidingWindow: {} },
            sessionResumption: handle ? { handle } : {},
          } }));
          return;
        }
        ready = true;
        send({ type: 'session.update', session: {
          type: 'realtime',
          instructions: opts.system,
          output_modalities: ['audio'],
          audio: {
            input: { format: { type: 'audio/pcm', rate: 24000 }, transcription: { model: 'gpt-4o-mini-transcribe' }, turn_detection: { type: 'semantic_vad' } },
            output: { format: { type: 'audio/pcm', rate: 24000 }, voice: opts.voice },
          },
        } });
      };
      socket.onmessage = (e) => {
        let msg;
        try { msg = JSON.parse(typeof e.data === 'string' ? e.data : new TextDecoder().decode(e.data)); } catch { return; }
        if (isGemini) onGemini(msg); else onOpenAI(msg);
      };
      socket.onclose = (e) => {
        if (ended || ws !== socket) return;
        // A dropped Gemini connection after the session started carries on with the same conversation.
        if (isGemini && ready && handle && reconnects < 3) { reconnects += 1; connect(); return; }
        // The service's own words when it gave any (for example Google's "API key not valid").
        const why = lastError || e.reason;
        stop(why || (accepted ? 'the connection closed (code ' + e.code + ')' : 'the connection closed before setup finished (code ' + e.code + ')'), { step: accepted ? 'session' : 'connect', code: e.code });
      };
    }

    function stop(reason, info) {
      if (ended) return;
      ended = true;
      clearInterval(frameTimer);
      clearTimeout(finishTimer);
      flush();
      if (ws) { ws.onclose = null; try { ws.close(1000); } catch { /* closed */ } }
      mic.getTracks().forEach((t) => t.stop());
      ctx.close();
      on.level(0);
      on.ended(reason || '', info || null);
    }

    connect();

    return {
      end: () => stop(''),
      /** Mute or unmute the microphone (the session stays open). */
      setMuted(m) {
        muted = !!m;
        if (muted && isGemini) send({ realtimeInput: { audioStreamEnd: true } });
      },
      /** Stop the current spoken answer; the rest of that answer is skipped. */
      stopSpeaking() {
        if (!sources.size) return;
        flush();
        dropAudio = true;
        if (!isGemini) send({ type: 'response.cancel' });
        on.state('listening');
      },
      /**
       * Lets the service see this video element, or stops with null. Gemini gets about one picture a
       * second; OpenAI gets the current picture each time the user speaks or types.
       */
      setVideo(el) {
        clearInterval(frameTimer);
        video = el;
        if (!el || !isGemini) return;
        frameTimer = setInterval(() => {
          if (!ready) return;
          const data = picture();
          if (data) send({ realtimeInput: { video: { data, mimeType: 'image/jpeg' } } });
        }, 1000);
      },
      /** A typed message, answered aloud like a spoken one. */
      sendText(text) {
        finishTurn();
        newTurnIfNeeded();
        userText = text;
        on.heard(text);
        if (isGemini) {
          send({ clientContent: { turns: [{ role: 'user', parts: [{ text }] }], turnComplete: true } });
          return;
        }
        flush();
        sendPictureToOpenAI();
        send({ type: 'conversation.item.create', item: { type: 'message', role: 'user', content: [{ type: 'input_text', text }] } });
        send({ type: 'response.create' });
      },
    };
  }

  /**
   * The voice check's connection step: opens the Gemini Live WebSocket with the key, sends a minimal
   * setup and waits for setupComplete. No microphone and no audio. Resolves { ok, error, ms }, where
   * error is Google's own reason when it gave one.
   */
  function probe(opts) {
    return new Promise((resolve) => {
      const started = Date.now();
      let done = false;
      let socket;
      const finish = (ok, error) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        if (socket) { socket.onclose = null; socket.onmessage = null; try { socket.close(1000); } catch { /* closed */ } }
        resolve({ ok, error: error || '', ms: Date.now() - started });
      };
      const timer = setTimeout(() => finish(false, 'no answer from Google within ' + Math.round((opts.timeoutMs || 15000) / 1000) + ' seconds'), opts.timeoutMs || 15000);
      try {
        socket = SERVICES.gemini.connect(opts);
      } catch (err) {
        finish(false, err.message);
        return;
      }
      socket.binaryType = 'arraybuffer';
      socket.onopen = () => socket.send(JSON.stringify({ setup: { model: 'models/' + opts.model, generationConfig: { responseModalities: ['AUDIO'] } } }));
      socket.onmessage = (e) => {
        let msg;
        try { msg = JSON.parse(typeof e.data === 'string' ? e.data : new TextDecoder().decode(e.data)); } catch { return; }
        if (msg.setupComplete) finish(true);
      };
      socket.onclose = (e) => finish(false, e.reason || 'the connection closed before setup finished (code ' + e.code + ')');
    });
  }

  window.AtlasRealtime = {
    start,
    probe,
    SERVICES,
    supported: () => !!(window.WebSocket && window.AudioContext && window.AudioWorkletNode && navigator.mediaDevices && navigator.mediaDevices.getUserMedia),
  };
})();
