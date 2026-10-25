// ATLAS OS cloud edition: the server half that runs as one Netlify Function under /cloud/*.
//
// It does three things only:
//   1. Owner sign-in: the first visitor claims this ATLAS (optionally with an access code), then
//      pairs other devices with one-time links. Only SHA-256 hashes of device tokens are stored.
//   2. Chat: forwards a signed-in device's messages to a cloud model whose key is a Netlify
//      environment variable (or injected by Netlify AI Gateway). Keys never reach the browser.
//   3. Model lists for those providers.
// Memories, chat history and tasks stay in the browser. Nothing here touches any computer.
//
// Everything is injected (store, env, fetch, clock) so tests run without Netlify or real models.

import { createHash, randomBytes, timingSafeEqual } from 'node:crypto';

export const VERSION = '0.10.0';

const OWNER_KEY = 'owner';
const PAIRING_MINUTES = 10;
const MAX_DEVICES = 10;
const MAX_MESSAGES = 60;
const MAX_TOTAL_CHARS = 100_000;
const MAX_OUTPUT_TOKENS = 2048;
const MODEL_RE = /^[\w.:/@-]{1,120}$/;

// Provider presets. `baseEnv` is where Netlify AI Gateway injects its URL; when that URL is not the
// provider's own, requests go through the gateway and are paid with Netlify credits.
export const PROVIDERS = {
  groq: {
    label: 'Groq', kind: 'openai', keyEnv: 'GROQ_API_KEY', baseEnv: null, base: 'https://api.groq.com/openai/v1',
    docs: 'https://console.groq.com/keys', prefer: [/llama-3\.3-70b/, /llama-3\.1-8b/, /llama/],
    skip: /whisper|guard|tts|playai|orpheus|prompt|compound/i,
  },
  gemini: {
    label: 'Google Gemini', kind: 'gemini', keyEnv: 'GEMINI_API_KEY', baseEnv: 'GOOGLE_GEMINI_BASE_URL', base: 'https://generativelanguage.googleapis.com',
    docs: 'https://aistudio.google.com/apikey', prefer: [/flash-lite/, /flash/], skip: /image|tts|embedding|aqa|live|audio|vision|learnlm|gemma/i,
    suggested: ['gemini-2.5-flash'],
  },
  openai: {
    label: 'OpenAI', kind: 'openai', keyEnv: 'OPENAI_API_KEY', baseEnv: 'OPENAI_BASE_URL', base: 'https://api.openai.com/v1',
    docs: 'https://platform.openai.com/api-keys', prefer: [/mini/, /nano/], skip: /audio|realtime|image|tts|transcribe|search|embedding|moderation|dall-e|whisper|davinci|babbage|codex|instruct/i,
    only: /^(gpt|o\d|chatgpt)/i, suggested: ['gpt-5-mini'],
  },
  anthropic: {
    label: 'Anthropic Claude', kind: 'anthropic', keyEnv: 'ANTHROPIC_API_KEY', baseEnv: 'ANTHROPIC_BASE_URL', base: 'https://api.anthropic.com',
    docs: 'https://console.anthropic.com/settings/keys', prefer: [/haiku/], skip: /^$/, suggested: ['claude-haiku-4-5'],
  },
};
export const PROVIDER_ORDER = ['groq', 'gemini', 'openai', 'anthropic'];

const sha256 = (text) => createHash('sha256').update(text).digest('hex');
const newToken = () => randomBytes(32).toString('base64url');
const json = (body, status = 200) => new Response(status === 204 ? null : JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
});
const fail = (status, code, detail) => json({ code, detail }, status);
const cleanName = (value, fallback) => (typeof value === 'string' && value.trim() ? value.trim().replace(/[\u0000-\u001f]/g, '').slice(0, 40) : fallback);

function sameSecret(a, b) {
  const x = Buffer.from(sha256(String(a)));
  const y = Buffer.from(sha256(String(b)));
  return timingSafeEqual(x, y);
}

/** Provider settings that are usable with this deploy's environment, keys included (server side only). */
export function activeProviders(env) {
  const out = [];
  for (const id of PROVIDER_ORDER) {
    const p = PROVIDERS[id];
    const key = env[p.keyEnv];
    if (!key) continue;
    const custom = p.baseEnv && env[p.baseEnv] ? env[p.baseEnv].replace(/\/+$/, '') : '';
    const gateway = !!custom && custom !== p.base;
    out.push({ id, ...p, key, base: custom || p.base, gateway });
  }
  return out;
}

function publicProvider(p) {
  return {
    id: p.id,
    label: p.label + (p.gateway ? ' (via Netlify AI Gateway)' : ''),
    gateway: p.gateway,
    billing: p.gateway
      ? 'Paid from your Netlify team\'s credits through Netlify AI Gateway. Check your allowance in Netlify → Billing.'
      : 'Uses your own ' + p.label + ' key and account. Free tiers and prices are set by ' + p.label + ' and can change.',
    docs_url: p.docs,
  };
}

// ---------------------------------------------------------------- device records

async function loadOwner(store) {
  const found = await store.getWithMetadata(OWNER_KEY, { type: 'json' });
  return found ? { record: found.data, etag: found.etag } : { record: null, etag: null };
}

/** Read-modify-write with an etag check, retried a few times if another request wrote first. */
async function updateOwner(store, change) {
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const { record, etag } = await loadOwner(store);
    if (!record) return null;
    const next = change(structuredClone(record));
    if (!next) return record;
    const { modified } = await store.setJSON(OWNER_KEY, next, { onlyIfMatch: etag });
    if (modified) return next;
  }
  throw new Error('storage busy');
}

function findDevice(record, token) {
  if (!record || !token) return null;
  const hash = sha256(token);
  return record.devices.find((d) => d.hash === hash) || null;
}

const publicDevice = (d) => ({ id: d.id, name: d.name, kind: d.kind, created_at: d.created_at, last_seen_at: d.last_seen_at || null });

// ---------------------------------------------------------------- model calls

function upstreamError(status, text) {
  let detail = '';
  try {
    const data = JSON.parse(text);
    const e = Array.isArray(data) ? data[0]?.error : data.error;
    detail = typeof e === 'string' ? e : (e && e.message) || data.message || '';
  } catch { detail = ''; }
  detail = String(detail || text || '').replace(/\s+/g, ' ').slice(0, 300);
  const hint = status === 401 || status === 403 ? ' Check the API key set in Netlify.'
    : status === 404 ? ' The model ID may be wrong or not available to this key.'
      : status === 429 ? ' Rate limit or free-tier quota reached; wait and try again.' : '';
  const err = new Error('Provider answered HTTP ' + status + (detail ? ': ' + detail : '') + '.' + hint);
  err.status = status;
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

function requestFor(p, model, messages, maxTokens) {
  const system = messages.filter((m) => m.role === 'system').map((m) => m.content).join('\n\n');
  const turns = messages.filter((m) => m.role !== 'system');
  if (p.kind === 'openai') {
    return {
      url: p.base + '/chat/completions',
      headers: { Authorization: 'Bearer ' + p.key },
      body: { model, messages, stream: true, max_tokens: maxTokens },
    };
  }
  if (p.kind === 'anthropic') {
    return {
      url: p.base + '/v1/messages',
      headers: { 'x-api-key': p.key, 'anthropic-version': '2023-06-01' },
      body: { model, max_tokens: maxTokens, stream: true, ...(system ? { system } : {}), messages: turns },
    };
  }
  return {
    url: p.base + '/v1beta/models/' + encodeURIComponent(model) + ':streamGenerateContent?alt=sse',
    headers: { 'x-goog-api-key': p.key },
    body: {
      contents: turns.map((m) => ({ role: m.role === 'assistant' ? 'model' : 'user', parts: [{ text: m.content }] })),
      ...(system ? { systemInstruction: { parts: [{ text: system }] } } : {}),
      generationConfig: { maxOutputTokens: maxTokens },
    },
  };
}

/** Yields text pieces from the provider; fills `result` with finish reason and token usage when known. */
async function* generate(fetchImpl, p, model, messages, maxTokens, signal, result) {
  const r = requestFor(p, model, messages, maxTokens);
  const response = await fetchImpl(r.url, {
    method: 'POST', signal,
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...r.headers },
    body: JSON.stringify(r.body),
  });
  if (!response.ok) throw upstreamError(response.status, await response.text().catch(() => ''));
  for await (const data of sseData(response.body)) {
    if (data === '[DONE]') break;
    let msg;
    try { msg = JSON.parse(data); } catch { continue; }
    if (msg.error) throw upstreamError(502, JSON.stringify(msg));
    if (p.kind === 'openai') {
      const choice = msg.choices && msg.choices[0];
      if (choice && choice.delta && choice.delta.content) yield choice.delta.content;
      if (choice && choice.finish_reason) result.finish_reason = choice.finish_reason;
      const usage = msg.usage || (msg.x_groq && msg.x_groq.usage);
      if (usage) result.usage = { total_tokens: usage.total_tokens };
    } else if (p.kind === 'anthropic') {
      if (msg.type === 'content_block_delta' && msg.delta && msg.delta.text) yield msg.delta.text;
      if (msg.type === 'message_delta' && msg.delta && msg.delta.stop_reason) result.finish_reason = msg.delta.stop_reason;
      if (msg.type === 'message_delta' && msg.usage) result.usage = { total_tokens: msg.usage.output_tokens };
    } else {
      const cand = msg.candidates && msg.candidates[0];
      for (const part of (cand && cand.content && cand.content.parts) || []) if (part.text && !part.thought) yield part.text;
      if (cand && cand.finishReason) result.finish_reason = cand.finishReason.toLowerCase();
      if (msg.usageMetadata && msg.usageMetadata.totalTokenCount) result.usage = { total_tokens: msg.usageMetadata.totalTokenCount };
    }
  }
}

async function listModels(fetchImpl, p) {
  let url = p.base + '/models';
  const headers = {};
  if (p.kind === 'openai') headers.Authorization = 'Bearer ' + p.key;
  if (p.kind === 'anthropic') { url = p.base + '/v1/models?limit=100'; headers['x-api-key'] = p.key; headers['anthropic-version'] = '2023-06-01'; }
  if (p.kind === 'gemini') { url = p.base + '/v1beta/models?pageSize=200'; headers['x-goog-api-key'] = p.key; }
  const response = await fetchImpl(url, { headers });
  if (!response.ok) throw upstreamError(response.status, await response.text().catch(() => ''));
  const data = await response.json();
  let ids;
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
  const p = providers.find((x) => x.id === body.provider);
  if (!p) return { error: 'This provider is not set up on this ATLAS. Add its API key in Netlify (see Settings).' };
  if (typeof body.model !== 'string' || !MODEL_RE.test(body.model)) return { error: 'Enter a valid model ID.' };
  const msgs = body.messages;
  if (!Array.isArray(msgs) || !msgs.length || msgs.length > MAX_MESSAGES) return { error: 'Send between 1 and ' + MAX_MESSAGES + ' messages.' };
  let total = 0;
  for (const m of msgs) {
    if (!m || !['system', 'user', 'assistant'].includes(m.role) || typeof m.content !== 'string') return { error: 'Each message needs a role and text.' };
    total += m.content.length;
  }
  if (total > MAX_TOTAL_CHARS) return { error: 'The conversation is too long (over ' + MAX_TOTAL_CHARS.toLocaleString('en') + ' characters).' };
  if (!msgs.some((m) => m.role === 'user')) return { error: 'Send at least one user message.' };
  const maxTokens = Math.max(1, Math.min(MAX_OUTPUT_TOKENS, Number(body.max_tokens) || 1024));
  return { p, msgs: msgs.map((m) => ({ role: m.role, content: m.content })), maxTokens };
}

// ---------------------------------------------------------------- handler

export function createHandler({ store, env, fetchImpl = fetch, now = () => new Date() }) {
  const iso = () => now().toISOString();

  async function signedIn(req) {
    const header = req.headers.get('authorization') || '';
    const token = header.startsWith('Bearer ') ? header.slice(7).trim() : '';
    const { record } = await loadOwner(store);
    const device = findDevice(record, token);
    if (device && (!device.last_seen_at || now() - new Date(device.last_seen_at) > 3600e3)) {
      // Coarse "last used" stamp: at most one write per device per hour.
      await updateOwner(store, (r) => {
        const d = r.devices.find((x) => x.id === device.id);
        if (!d) return null;
        d.last_seen_at = iso();
        return r;
      }).catch(() => {});
    }
    return { record, device };
  }

  async function readBody(req) {
    const text = await req.text();
    if (text.length > 400_000) return { tooBig: true };
    try { return text ? JSON.parse(text) : {}; } catch { return { invalid: true }; }
  }

  async function chat(req, body, providers) {
    const v = validateChat(body, providers);
    if (v.error) return fail(422, 'invalid_request', v.error);
    const { p, msgs, maxTokens } = v;
    const model = body.model;
    const started = Date.now();
    const result = {};
    const meta = () => ({ provider: p.id, model, local: false, gateway: p.gateway, latency_ms: Date.now() - started, ...result });

    if (body.stream === false) {
      let answer = '';
      try {
        for await (const piece of generate(fetchImpl, p, model, msgs, maxTokens, req.signal, result)) answer += piece;
      } catch (err) {
        return fail(502, 'provider_error', err.message);
      }
      if (!answer.trim()) return fail(502, 'empty_answer', 'The model returned an empty answer.');
      return json({ ...meta(), answer });
    }

    const enc = new TextEncoder();
    const send = (controller, event, data) => controller.enqueue(enc.encode('event: ' + event + '\ndata: ' + JSON.stringify(data) + '\n\n'));
    // Open the upstream first so a bad key or model is a normal HTTP error, not a broken stream.
    const iterator = generate(fetchImpl, p, model, msgs, maxTokens, req.signal, result);
    let first;
    try {
      first = await iterator.next();
    } catch (err) {
      return fail(502, 'provider_error', err.message);
    }
    const firstTokenMs = Date.now() - started;
    const stream = new ReadableStream({
      async start(controller) {
        send(controller, 'start', { provider: p.id, model, local: false, gateway: p.gateway });
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
    return new Response(stream, { headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no' } });
  }

  return async function handle(req) {
    const url = new URL(req.url);
    const path = url.pathname.replace(/^\/cloud/, '').replace(/\/+$/, '') || '/';
    const method = req.method.toUpperCase();
    const providers = activeProviders(env);
    let body = {};
    if (method === 'POST' || method === 'DELETE') {
      body = await readBody(req);
      if (body.tooBig) return fail(413, 'too_large', 'Request too large.');
      if (body.invalid) return fail(400, 'invalid_json', 'Request body must be JSON.');
    }

    try {
      const { record, device } = await signedIn(req);

      if (path === '/status' && method === 'GET') {
        return json({
          version: VERSION,
          claimed: !!record,
          access_code_required: !!env.ATLAS_ACCESS_CODE,
          me: device ? { kind: device.kind, name: device.name } : null,
          providers: providers.map(publicProvider),
          setup: { netlify_env_url: env.SITE_NAME ? 'https://app.netlify.com/projects/' + env.SITE_NAME + '/configuration/env' : null },
        });
      }

      if (path === '/claim' && method === 'POST') {
        if (record) return fail(409, 'already_claimed', 'This ATLAS already has an owner. Open a pairing link from the owner\'s device to sign in here.');
        if (env.ATLAS_ACCESS_CODE && !sameSecret(body.access_code || '', env.ATLAS_ACCESS_CODE)) return fail(403, 'bad_access_code', 'Wrong access code.');
        const token = newToken();
        const owner = { id: randomBytes(6).toString('hex'), name: cleanName(body.name, 'Owner phone'), kind: 'owner', hash: sha256(token), created_at: iso(), last_seen_at: iso() };
        const { modified } = await store.setJSON(OWNER_KEY, { created_at: iso(), devices: [owner], pairings: [] }, { onlyIfNew: true });
        if (!modified) return fail(409, 'already_claimed', 'This ATLAS was just claimed by another device.');
        return json({ token, me: { kind: 'owner', name: owner.name } }, 201);
      }

      if (path === '/join' && method === 'POST') {
        if (!record) return fail(409, 'not_claimed', 'This ATLAS has no owner yet.');
        const code = typeof body.code === 'string' ? body.code : '';
        const hash = sha256(code);
        const token = newToken();
        let joined = null;
        let refusal = 'This pairing link is invalid, already used or expired. Create a new one on the owner\'s device.';
        await updateOwner(store, (r) => {
          r.pairings = (r.pairings || []).filter((x) => new Date(x.expires_at) > now());
          const pairing = code && r.pairings.find((x) => x.hash === hash);
          if (!pairing) return null;
          if (r.devices.length >= MAX_DEVICES) { refusal = 'Too many devices are paired. Remove one first.'; return null; }
          r.pairings = r.pairings.filter((x) => x !== pairing);
          joined = { id: randomBytes(6).toString('hex'), name: cleanName(body.name, pairing.name || 'Paired device'), kind: 'device', hash: sha256(token), created_at: iso(), last_seen_at: iso() };
          r.devices.push(joined);
          return r;
        });
        if (!joined) return fail(403, 'bad_pairing', refusal);
        return json({ token, me: { kind: 'device', name: joined.name } }, 201);
      }

      if (!device) return fail(401, 'unauthorized', record ? 'This device is not signed in to this ATLAS.' : 'This ATLAS has no owner yet. Open it and claim it first.');

      if (path === '/chat' && method === 'POST') return chat(req, body, providers);

      if (path === '/models' && method === 'GET') {
        const p = providers.find((x) => x.id === url.searchParams.get('provider'));
        if (!p) return fail(422, 'unknown_provider', 'This provider is not set up on this ATLAS.');
        try {
          return json({ provider: p.id, models: await listModels(fetchImpl, p) });
        } catch (err) {
          // Some gateways do not list models; offer the documented default so chat still works.
          return json({ provider: p.id, models: p.suggested || [], suggested_only: true, warning: 'Could not list models: ' + err.message });
        }
      }

      if (path === '/me' && method === 'DELETE') {
        if (device.kind === 'owner') {
          if (body.confirm !== 'RESET') return fail(422, 'confirm_required', 'Send confirm: "RESET" to remove the owner and every paired device.');
          await store.delete(OWNER_KEY);
          return json(null, 204);
        }
        await updateOwner(store, (r) => { r.devices = r.devices.filter((d) => d.id !== device.id); return r; });
        return json(null, 204);
      }

      if (device.kind !== 'owner') return fail(403, 'owner_only', 'Only the owner\'s device can manage devices.');

      if (path === '/pairing' && method === 'POST') {
        const code = newToken();
        const expires = new Date(now().getTime() + PAIRING_MINUTES * 60e3).toISOString();
        await updateOwner(store, (r) => {
          r.pairings = [...(r.pairings || []).filter((x) => new Date(x.expires_at) > now()), { hash: sha256(code), name: cleanName(body.name, null), expires_at: expires }].slice(-5);
          return r;
        });
        return json({ code, expires_at: expires }, 201);
      }

      if (path === '/devices' && method === 'GET') {
        return json({ devices: record.devices.filter((d) => d.kind !== 'owner').map(publicDevice) });
      }

      const m = path.match(/^\/devices\/([0-9a-f]{12})$/);
      if (m && method === 'DELETE') {
        let removed = false;
        await updateOwner(store, (r) => {
          const before = r.devices.length;
          r.devices = r.devices.filter((d) => d.kind === 'owner' || d.id !== m[1]);
          removed = r.devices.length !== before;
          return removed ? r : null;
        });
        return removed ? json(null, 204) : fail(404, 'not_found', 'No such device.');
      }

      return fail(404, 'not_found', 'Unknown ATLAS cloud endpoint.');
    } catch (err) {
      console.error('atlas cloud error:', err && err.message);
      return fail(500, 'server_error', 'ATLAS cloud had a problem. Try again.');
    }
  };
}

/** In-memory store with the same calls this file uses from @netlify/blobs (tests and the local dev server). */
export function memoryStore() {
  const items = new Map();
  let counter = 0;
  return {
    async getWithMetadata(key) {
      const item = items.get(key);
      return item ? { data: JSON.parse(item.value), etag: item.etag, metadata: {} } : null;
    },
    async setJSON(key, value, opts = {}) {
      const item = items.get(key);
      if (opts.onlyIfNew && item) return { modified: false };
      if (opts.onlyIfMatch && (!item || item.etag !== opts.onlyIfMatch)) return { modified: false };
      counter += 1;
      const etag = '"' + counter + '"';
      items.set(key, { value: JSON.stringify(value), etag });
      return { modified: true, etag };
    },
    async delete(key) { items.delete(key); },
  };
}
