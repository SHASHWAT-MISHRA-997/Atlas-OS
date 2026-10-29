// ATLAS OS online edition: the server half, one Netlify Function under /cloud/*.
//
// Bring your own key: every visitor types their own AI provider key in the app. The key travels
// with each request over HTTPS, is used for that one provider call, and is never stored or logged
// here. The site owner's keys and Netlify AI Gateway credentials are never used, even if Netlify
// injects them into the environment, so nobody can spend the owner's quota or credits.
//
// It only forwards chat messages and lists models. Memories, chat history and tasks stay in the
// visitor's browser. Nothing here touches any computer.
//
// fetch and the provider table are injectable so tests run without Netlify or real models.

export const VERSION = '0.29.1';

const MAX_MESSAGES = 60;
const MAX_TOTAL_CHARS = 100_000;
const MAX_OUTPUT_TOKENS = 2048;
// Thinking levels: extra output tokens the model may spend on reasoning before it answers.
const THINKING = { low: 2048, medium: 6144, high: 14336 };
// Images and PDFs ride on user messages, base64-encoded. Netlify accepts request bodies up to 6 MB.
const ATTACH_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif', 'application/pdf'];
const MAX_ATTACHMENTS = 4;
const MAX_ATTACH_CHARS = 4_000_000;
const BASE64_RE = /^[A-Za-z0-9+/]+={0,2}$/;
const MODEL_RE = /^[\w.:/@-]{1,120}$/;
const KEY_RE = /^[\x21-\x7e]{8,400}$/;

// Only providers with a free tier, at their official endpoints only. There is deliberately no way to point a provider at another URL, so the
// function cannot be used to send keys or traffic to arbitrary hosts.
export const PROVIDERS = {
  groq: {
    label: 'Groq', kind: 'openai', base: 'https://api.groq.com/openai/v1', keyUrl: 'https://console.groq.com/keys',
    pdf: false, thinking: 'effort',
    note: 'Free tier with rate limits.', prefer: [/llama-3\.3-70b/, /llama-3\.1-8b/, /llama/],
    skip: /whisper|guard|tts|playai|orpheus|prompt|compound/i,
  },
  gemini: {
    label: 'Google Gemini', kind: 'gemini', pdf: true, base: 'https://generativelanguage.googleapis.com', keyUrl: 'https://aistudio.google.com/apikey',
    note: 'Free tier with limits. A paid Google key also lists paid models such as Gemini 4 Argon, billed to your Google account.', prefer: [/flash-lite/, /flash/], skip: /image|tts|embedding|aqa|live|audio|vision|learnlm|gemma/i,
    suggested: ['gemini-2.5-flash'],
  },
  openrouter: {
    label: 'OpenRouter', kind: 'openai', pdf: true, thinking: 'openrouter', base: 'https://openrouter.ai/api/v1', keyUrl: 'https://openrouter.ai/settings/keys',
    note: 'Only its free models (IDs ending in ":free") are offered.', prefer: [/llama|deepseek|qwen|gemma/], skip: /^$/, only: /:free$/,
    checkKey: '/key',
  },
  // Optional and paid (the owner chose to offer it): never a default, never an auto-switch target.
  openai: {
    label: 'OpenAI (paid)', kind: 'openai', pdf: true, thinking: 'effort', base: 'https://api.openai.com/v1', keyUrl: 'https://platform.openai.com/api-keys', paid: true,
    note: 'Paid, no free tier: every message is billed to your own OpenAI account. GPT-6 Astra costs far more per message than the free providers.',
    prefer: [/^gpt-6-astra$/, /^gpt-6/, /^gpt-5/], tokensField: 'max_completion_tokens',
    skip: /embedding|tts|whisper|dall-e|image|audio|realtime|moderation|transcribe|search|babbage|davinci|instruct|codex/i,
  },
};
export const PROVIDER_ORDER = ['groq', 'gemini', 'openrouter', 'openai'];

const MAX_BODY = 5_000_000; // a chat with up to about 3 MB of images or PDFs
// Speech to text for browsers without a working speech service (Brave, Firefox): a short WAV
// recording, written down by the visitor's own provider. OpenRouter has no speech model.
// A Whisper piece more likely silence than speech is dropped (Whisper's own no-speech estimate).
const NO_SPEECH = 0.5;
const TRANSCRIBE_MODELS = { groq: 'whisper-large-v3-turbo', gemini: 'gemini-2.5-flash', openai: 'gpt-4o-mini-transcribe' };
const MAX_AUDIO = 3_000_000; // base64 characters, about 70 seconds of 16 kHz speech
// Text to speech in a natural voice for spoken answers (Live turn-by-turn, Read aloud). Gemini's TTS
// models are free on a Gemini key; OpenAI's is paid and is used only when OpenAI is the chosen provider.
const SPEAK_MODELS = { gemini: ['gemini-2.5-flash-preview-tts', 'gemini-2.5-pro-preview-tts'], openai: ['gpt-4o-mini-tts'] };
const MAX_SPEAK = 1500; // characters per request; the page sends long answers in pieces
const VOICE_RE = /^[A-Za-z]{2,20}$/;
const SPEAK_STYLE = 'Speak in a warm, natural, conversational human tone at a relaxed pace. Hinglish should sound like a fluent Indian speaker.';
const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' },
});
const fail = (status, code, detail) => json({ code, detail }, status);

/**
 * True when a browser says the request came from another website. The app itself always calls
 * from the same origin; other sites get no answer (and no CORS headers, so they could not read one).
 */
function fromOtherSite(req, url) {
  const site = req.headers.get('sec-fetch-site');
  if (site === 'cross-site' || site === 'same-site') return true;
  const origin = req.headers.get('origin');
  if (!origin || site === 'same-origin') return false;
  try { return new URL(origin).host !== url.host; } catch { return true; }
}

/** The provider with the visitor's key for this one request, or an error message. */
function withKey(providers, id, key) {
  const preset = typeof id === 'string' && Object.hasOwn(providers, id) ? providers[id] : null;
  if (!preset) return { error: 'Unknown provider.' };
  if (typeof key !== 'string' || !KEY_RE.test(key.trim())) return { error: 'Enter your ' + preset.label + ' API key (Model settings → API key).' };
  return { p: { id, ...preset, key: key.trim() } };
}

// ---------------------------------------------------------------- model calls

/** Writes down a WAV recording with the visitor's provider: Whisper on Groq and OpenAI, Gemini itself on Google. */
async function transcribe(fetchImpl, p, audio, signal) {
  const model = TRANSCRIBE_MODELS[p.id];
  if (p.kind === 'gemini') {
    const response = await fetchImpl(p.base + '/v1beta/models/' + model + ':generateContent', {
      method: 'POST', signal, headers: { 'Content-Type': 'application/json', 'x-goog-api-key': p.key },
      body: JSON.stringify({ contents: [{ role: 'user', parts: [{ inlineData: { mimeType: 'audio/wav', data: audio } },
        { text: 'Write down exactly what is said in this recording, in the words and language used (Hindi in Devanagari, Hinglish in Latin letters, as spoken). Reply with only those words. If nobody speaks, reply with nothing.' }] }],
      generationConfig: { temperature: 0 } }),
    });
    if (!response.ok) throw upstreamError(response.status, await response.text().catch(() => ''), p.key);
    const data = await response.json();
    return ((data.candidates && data.candidates[0] && data.candidates[0].content && data.candidates[0].content.parts) || []).map((x) => x.text || '').join('').trim();
  }
  const form = new FormData();
  form.append('file', new Blob([Buffer.from(audio, 'base64')], { type: 'audio/wav' }), 'speech.wav');
  form.append('model', model);
  // Whisper on Groq: ask how likely each piece is to be speech, so words it invents for silence or
  // noise ("Gracias.", "Thank you.", seen on the owner's phone) can be dropped.
  if (p.id === 'groq') { form.append('response_format', 'verbose_json'); form.append('temperature', '0'); }
  const response = await fetchImpl(p.base + '/audio/transcriptions', { method: 'POST', signal, headers: { Authorization: 'Bearer ' + p.key }, body: form });
  if (!response.ok) throw upstreamError(response.status, await response.text().catch(() => ''), p.key);
  const data = await response.json();
  if (Array.isArray(data.segments) && data.segments.length) {
    return data.segments.filter((x) => !(Number(x.no_speech_prob) > NO_SPEECH)).map((x) => String(x.text || '')).join('').replace(/\s+/g, ' ').trim();
  }
  return String(data.text || '').trim();
}

/** Speaks `text` with the visitor's provider; returns 16-bit mono PCM (base64) and its sample rate. */
async function speak(fetchImpl, p, text, voice, signal) {
  if (p.kind === 'gemini') {
    let last;
    for (const model of SPEAK_MODELS.gemini) {
      const response = await fetchImpl(p.base + '/v1beta/models/' + model + ':generateContent', {
        method: 'POST', signal, headers: { 'Content-Type': 'application/json', 'x-goog-api-key': p.key },
        body: JSON.stringify({
          contents: [{ role: 'user', parts: [{ text: SPEAK_STYLE + ' Say this:\n' + text }] }],
          generationConfig: { responseModalities: ['AUDIO'], speechConfig: { voiceConfig: { prebuiltVoiceConfig: { voiceName: voice || 'Kore' } } } },
        }),
      });
      if (!response.ok) {
        last = upstreamError(response.status, await response.text().catch(() => ''), p.key);
        // Try the other TTS model only when this one is missing for the key.
        if (response.status === 404) continue;
        throw last;
      }
      const data = await response.json();
      const parts = (data.candidates && data.candidates[0] && data.candidates[0].content && data.candidates[0].content.parts) || [];
      const part = parts.find((x) => x.inlineData && x.inlineData.data);
      if (!part) throw new Error('The provider sent no audio.');
      const rate = Number((/rate=(\d+)/.exec(part.inlineData.mimeType || '') || [])[1]) || 24000;
      return { model, audio: part.inlineData.data, rate };
    }
    throw last;
  }
  const model = SPEAK_MODELS.openai[0];
  const response = await fetchImpl(p.base + '/audio/speech', {
    method: 'POST', signal, headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + p.key },
    body: JSON.stringify({ model, voice: (voice || 'marin').toLowerCase(), input: text, instructions: SPEAK_STYLE, response_format: 'pcm' }),
  });
  if (!response.ok) throw upstreamError(response.status, await response.text().catch(() => ''), p.key);
  return { model, audio: Buffer.from(await response.arrayBuffer()).toString('base64'), rate: 24000 };
}

function upstreamError(status, text, key) {
  let detail = '';
  try {
    const data = JSON.parse(text);
    const e = Array.isArray(data) ? data[0]?.error : data.error;
    detail = typeof e === 'string' ? e : (e && e.message) || data.message || '';
  } catch { detail = ''; }
  detail = String(detail || text || '').split(key || '\u0000').join('[your key]').replace(/\s+/g, ' ').slice(0, 300);
  const badKey = status === 401 || status === 403 || (status === 400 && /api[ _-]?key/i.test(detail));
  const hint = badKey ? ' Check your API key.'
    : status === 404 ? ' The model ID may be wrong or not available to this key.'
      : status === 429 ? ' Rate limit or free-tier quota reached; wait and try again.' : '';
  const err = new Error('Provider answered HTTP ' + status + (detail ? ': ' + detail.replace(/[.\s]+$/, '') : '') + '.' + hint);
  err.status = status;
  err.badKey = badKey;
  return err;
}

/** Splits a fetch response body into SSE `data:` payloads. */
async function* sseData(body) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
    let index;
    while ((index = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      const data = block.split('\n').filter((l) => l.startsWith('data:')).map((l) => l.slice(5).trim()).join('');
      if (data) yield data;
    }
  }
  const tail = buffer.split('\n').filter((l) => l.startsWith('data:')).map((l) => l.slice(5).trim()).join('');
  if (tail) yield tail;
}

/** OpenAI-style content: plain text, or text plus image and PDF parts. */
function openaiContent(m) {
  if (!m.attachments) return m.content;
  return [{ type: 'text', text: m.content }, ...m.attachments.map((a) => (a.mime === 'application/pdf'
    ? { type: 'file', file: { filename: a.name, file_data: 'data:application/pdf;base64,' + a.data } }
    : { type: 'image_url', image_url: { url: 'data:' + a.mime + ';base64,' + a.data } }))];
}

function requestFor(p, model, messages, maxTokens, thinking) {
  const system = messages.filter((m) => m.role === 'system').map((m) => m.content).join('\n\n');
  const turns = messages.filter((m) => m.role !== 'system');
  const budget = thinking ? THINKING[thinking] : 0;
  if (p.kind === 'openai') {
    const body = { model, messages: messages.map((m) => ({ role: m.role, content: openaiContent(m) })), stream: true, [p.tokensField || 'max_tokens']: maxTokens + budget };
    if (thinking && p.thinking === 'effort') body.reasoning_effort = thinking;
    if (thinking && p.thinking === 'openrouter') body.reasoning = { effort: thinking, exclude: true };
    return { url: p.base + '/chat/completions', headers: { Authorization: 'Bearer ' + p.key }, body };
  }
  return {
    url: p.base + '/v1beta/models/' + encodeURIComponent(model) + ':streamGenerateContent?alt=sse',
    headers: { 'x-goog-api-key': p.key },
    body: {
      contents: turns.map((m) => ({
        role: m.role === 'assistant' ? 'model' : 'user',
        parts: [{ text: m.content }, ...(m.attachments || []).map((a) => ({ inlineData: { mimeType: a.mime, data: a.data } }))],
      })),
      ...(system ? { systemInstruction: { parts: [{ text: system }] } } : {}),
      generationConfig: { maxOutputTokens: maxTokens + budget, ...(budget ? { thinkingConfig: { thinkingBudget: budget } } : {}) },
    },
  };
}

/** Yields text pieces from the provider; fills `result` with finish reason and token usage when known. */
async function* generate(fetchImpl, p, model, messages, maxTokens, signal, result, thinking) {
  const open = (level) => {
    const r = requestFor(p, model, messages, maxTokens, level);
    return fetchImpl(r.url, {
      method: 'POST', signal,
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...r.headers },
      body: JSON.stringify(r.body),
    });
  };
  let response = await open(thinking);
  // Not every model accepts a thinking setting; such a model answers once more without it.
  if (thinking && response.status === 400) {
    const text = await response.text().catch(() => '');
    if (!/reason|think|budget|effort/i.test(text)) throw upstreamError(400, text, p.key);
    result.thinking = 'not supported by this model';
    response = await open(null);
  } else if (thinking) {
    result.thinking = thinking;
  }
  if (!response.ok) throw upstreamError(response.status, await response.text().catch(() => ''), p.key);
  for await (const data of sseData(response.body)) {
    if (data === '[DONE]') break;
    let msg;
    try { msg = JSON.parse(data); } catch { continue; }
    if (msg.error) throw upstreamError(502, JSON.stringify(msg), p.key);
    if (p.kind === 'openai') {
      const choice = msg.choices && msg.choices[0];
      if (choice && choice.delta && choice.delta.content) yield choice.delta.content;
      if (choice && choice.finish_reason) result.finish_reason = choice.finish_reason;
      const usage = msg.usage || (msg.x_groq && msg.x_groq.usage);
      if (usage) result.usage = { total_tokens: usage.total_tokens };
    } else {
      const cand = msg.candidates && msg.candidates[0];
      for (const part of (cand && cand.content && cand.content.parts) || []) if (part.text && !part.thought) yield part.text;
      if (cand && cand.finishReason) result.finish_reason = cand.finishReason.toLowerCase();
      if (msg.usageMetadata && msg.usageMetadata.totalTokenCount) result.usage = { total_tokens: msg.usageMetadata.totalTokenCount };
    }
  }
}

// Offered when the key cannot list models: Google's native-audio Live model, OpenAI's realtime model.
const LIVE_SUGGESTED = { gemini: ['gemini-2.5-flash-native-audio-preview-12-2025'], openai: ['gpt-realtime'] };

async function listModels(fetchImpl, p, live) {
  let url = p.base + '/models';
  const headers = {};
  if (p.kind === 'openai') headers.Authorization = 'Bearer ' + p.key;
  if (p.kind === 'gemini') { url = p.base + '/v1beta/models?pageSize=200'; headers['x-goog-api-key'] = p.key; }
  if (p.checkKey) {
    // OpenRouter lists its models to anyone, so a wrong key would pass; ask its key endpoint first.
    const check = await fetchImpl(p.base + p.checkKey, { headers });
    if (!check.ok) throw upstreamError(check.status, await check.text().catch(() => ''), p.key);
  }
  const response = await fetchImpl(url, { headers });
  if (!response.ok) throw upstreamError(response.status, await response.text().catch(() => ''), p.key);
  const data = await response.json();
  let ids;
  if (live && p.id === 'openai') {
    // Real-time voice with a paid OpenAI key: its realtime models, released ones before previews, full before mini.
    ids = (data.data || []).map((m) => m.id).filter((id) => typeof id === 'string' && MODEL_RE.test(id) && /realtime/.test(id));
    const rank = (id) => (/preview/.test(id) ? 2 : 0) + (/mini/.test(id) ? 1 : 0);
    return [...new Set(ids)].sort((a, b) => rank(a) - rank(b) || a.length - b.length || b.localeCompare(a));
  }
  if (live) {
    // Real-time voice: Gemini models that support the Live API (bidiGenerateContent), native audio first.
    ids = (data.models || []).filter((m) => (m.supportedGenerationMethods || []).includes('bidiGenerateContent'))
      .map((m) => String(m.name).replace(/^models\//, '')).filter((id) => MODEL_RE.test(id));
    const rank = (id) => (/native-audio/.test(id) ? 0 : /live/.test(id) ? 1 : 2);
    return [...new Set(ids)].sort((a, b) => rank(a) - rank(b) || b.localeCompare(a));
  }
  if (p.kind === 'gemini') {
    ids = (data.models || []).filter((m) => (m.supportedGenerationMethods || []).includes('generateContent'))
      .map((m) => String(m.name).replace(/^models\//, ''));
  } else {
    ids = (data.data || []).map((m) => m.id);
  }
  ids = ids.filter((id) => typeof id === 'string' && MODEL_RE.test(id) && !p.skip.test(id) && (!p.only || p.only.test(id)));
  const rank = (id) => { const i = p.prefer.findIndex((re) => re.test(id)); return i < 0 ? p.prefer.length : i; };
  return [...new Set(ids)].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

function validateChat(body, providers) {
  const { p, error } = withKey(providers, body.provider, body.api_key);
  if (error) return { error };
  if (typeof body.model !== 'string' || !MODEL_RE.test(body.model)) return { error: 'Enter a valid model ID.' };
  const msgs = body.messages;
  if (!Array.isArray(msgs) || !msgs.length || msgs.length > MAX_MESSAGES) return { error: 'Send between 1 and ' + MAX_MESSAGES + ' messages.' };
  let total = 0;
  let attachChars = 0;
  for (const m of msgs) {
    if (!m || !['system', 'user', 'assistant'].includes(m.role) || typeof m.content !== 'string') return { error: 'Each message needs a role and text.' };
    total += m.content.length;
    if (m.attachments === undefined) continue;
    if (m.role !== 'user' || !Array.isArray(m.attachments) || m.attachments.length > MAX_ATTACHMENTS) return { error: 'Attach up to ' + MAX_ATTACHMENTS + ' files, on your own messages only.' };
    for (const a of m.attachments) {
      if (!a || !ATTACH_TYPES.includes(a.mime) || typeof a.data !== 'string' || !BASE64_RE.test(a.data)) return { error: 'Attachments must be PNG, JPEG, WebP or GIF images, or PDF files.' };
      if (a.mime === 'application/pdf' && !p.pdf) return { error: p.label + ' cannot read PDFs. Pick Google Gemini or OpenRouter for PDFs, or attach an image.' };
      attachChars += a.data.length;
    }
  }
  if (attachChars > MAX_ATTACH_CHARS) return { error: 'The attached files are too large (about 3 MB in total at most).' };
  if (total > MAX_TOTAL_CHARS) return { error: 'The conversation is too long (over ' + MAX_TOTAL_CHARS.toLocaleString('en') + ' characters).' };
  if (!msgs.some((m) => m.role === 'user')) return { error: 'Send at least one user message.' };
  const maxTokens = Math.max(1, Math.min(MAX_OUTPUT_TOKENS, Number(body.max_tokens) || 1024));
  if (body.thinking !== undefined && body.thinking !== null && !Object.hasOwn(THINKING, body.thinking)) return { error: 'Thinking must be low, medium or high.' };
  const clean = (a, i) => ({ mime: a.mime, data: a.data, name: (typeof a.name === 'string' && a.name.replace(/[^\w. -]/g, '').slice(0, 80)) || 'file-' + (i + 1) });
  return {
    p, maxTokens, thinking: body.thinking || null,
    msgs: msgs.map((m) => ({ role: m.role, content: m.content, ...(m.attachments && m.attachments.length ? { attachments: m.attachments.map(clean) } : {}) })),
  };
}

// ---------------------------------------------------------------- handler

export function createHandler({ fetchImpl = fetch, providers = PROVIDERS } = {}) {
  async function chat(req, body) {
    const v = validateChat(body, providers);
    if (v.error) return fail(422, 'invalid_request', v.error);
    const { p, msgs, maxTokens, thinking } = v;
    const model = body.model;
    const started = Date.now();
    const result = {};
    const meta = () => ({ provider: p.id, model, local: false, latency_ms: Date.now() - started, ...result });

    if (body.stream === false) {
      let answer = '';
      try {
        for await (const piece of generate(fetchImpl, p, model, msgs, maxTokens, req.signal, result, thinking)) answer += piece;
      } catch (err) {
        return fail(502, 'provider_error', err.message);
      }
      if (!answer.trim()) return fail(502, 'empty_answer', 'The model returned an empty answer.');
      return json({ ...meta(), answer });
    }

    const enc = new TextEncoder();
    const send = (controller, event, data) => controller.enqueue(enc.encode('event: ' + event + '\ndata: ' + JSON.stringify(data) + '\n\n'));
    // Open the upstream first so a bad key or model is a normal HTTP error, not a broken stream.
    const iterator = generate(fetchImpl, p, model, msgs, maxTokens, req.signal, result, thinking);
    let first;
    try {
      first = await iterator.next();
    } catch (err) {
      return fail(502, 'provider_error', err.message);
    }
    const firstTokenMs = Date.now() - started;
    const stream = new ReadableStream({
      async start(controller) {
        send(controller, 'start', { provider: p.id, model, local: false });
        try {
          if (!first.done) send(controller, 'delta', { text: first.value });
          if (!first.done) for await (const piece of { [Symbol.asyncIterator]: () => iterator }) send(controller, 'delta', { text: piece });
          send(controller, 'done', { ...meta(), first_token_ms: firstTokenMs });
        } catch (err) {
          send(controller, 'error', { detail: err.message || 'Provider error.' });
        }
        controller.close();
      },
    });
    return new Response(stream, { headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no', 'X-Content-Type-Options': 'nosniff' } });
  }

  return async function handle(req) {
    const url = new URL(req.url);
    const path = url.pathname.replace(/^\/cloud/, '').replace(/\/+$/, '') || '/';
    const method = req.method.toUpperCase();

    if (path === '/status' && method === 'GET') {
      return json({
        version: VERSION,
        key_mode: 'bring-your-own',
        providers: PROVIDER_ORDER.filter((id) => providers[id]).map((id) => ({
          id, label: providers[id].label, key_url: providers[id].keyUrl, note: providers[id].note, paid: !!providers[id].paid, pdf: !!providers[id].pdf,
        })),
      });
    }
    if (method !== 'POST' || !['/chat', '/models', '/transcribe', '/speak'].includes(path)) return fail(404, 'not_found', 'Unknown ATLAS cloud endpoint.');
    if (fromOtherSite(req, url)) return fail(403, 'cross_site', 'ATLAS online only answers its own page.');
    // JSON only: a plain HTML form on another site cannot send this content type.
    if (!/^application\/json\s*(;|$)/i.test(req.headers.get('content-type') || '')) return fail(415, 'json_only', 'Send JSON (Content-Type: application/json).');
    // Only chat and speech carry files; listing models needs a few hundred bytes.
    const limit = path === '/chat' || path === '/transcribe' ? MAX_BODY : 20_000;
    if (Number(req.headers.get('content-length')) > limit) return fail(413, 'too_large', 'Request too large.');

    const text = await req.text();
    if (text.length > limit) return fail(413, 'too_large', 'Request too large.');
    let body;
    try { body = text ? JSON.parse(text) : {}; } catch { return fail(400, 'invalid_json', 'Request body must be JSON.'); }
    if (!body || typeof body !== 'object') return fail(400, 'invalid_json', 'Request body must be a JSON object.');

    try {
      if (path === '/chat') return await chat(req, body);
      const { p, error } = withKey(providers, body.provider, body.api_key);
      if (error) return fail(422, 'invalid_request', error);
      if (path === '/transcribe') {
        if (!TRANSCRIBE_MODELS[p.id]) return fail(422, 'invalid_request', p.label + ' cannot write down speech. Add a free Groq or Google Gemini key.');
        const audio = body.audio;
        // A WAV file starts with "RIFF" ("UklGR" in base64).
        if (typeof audio !== 'string' || audio.length > MAX_AUDIO || !BASE64_RE.test(audio) || !audio.startsWith('UklGR')) return fail(422, 'invalid_request', 'Send a WAV recording of at most about a minute.');
        try {
          return json({ provider: p.id, model: TRANSCRIBE_MODELS[p.id], text: (await transcribe(fetchImpl, p, audio, req.signal)).slice(0, 4000) });
        } catch (err) {
          return fail(502, 'provider_error', err.message);
        }
      }
      if (path === '/speak') {
        if (!SPEAK_MODELS[p.id]) return fail(422, 'invalid_request', p.label + ' has no natural voice here. Add a free Google Gemini key.');
        const words = typeof body.text === 'string' ? body.text.trim() : '';
        if (!words || words.length > MAX_SPEAK) return fail(422, 'invalid_request', 'Send between 1 and ' + MAX_SPEAK + ' characters to speak.');
        if (body.voice !== undefined && (typeof body.voice !== 'string' || !VOICE_RE.test(body.voice))) return fail(422, 'invalid_request', 'Unknown voice name.');
        try {
          return json({ provider: p.id, ...(await speak(fetchImpl, p, words, body.voice, req.signal)) });
        } catch (err) {
          return fail(502, 'provider_error', err.message);
        }
      }
      const live = body.live === true;
      if (live && !LIVE_SUGGESTED[p.id]) return fail(422, 'invalid_request', 'Real-time voice needs a Google Gemini key or an OpenAI key.');
      try {
        return json({ provider: p.id, models: await listModels(fetchImpl, p, live) });
      } catch (err) {
        if (err.badKey) return fail(502, 'provider_error', err.message);
        // Some providers do not list models for every key; offer the documented default so chat still works.
        return json({ provider: p.id, models: (live ? LIVE_SUGGESTED[p.id] : p.suggested) || [], suggested_only: true, warning: 'Could not list models: ' + err.message });
      }
    } catch (err) {
      console.error('atlas cloud error:', err && err.name);
      return fail(500, 'server_error', 'ATLAS cloud had a problem. Try again.');
    }
  };
}
