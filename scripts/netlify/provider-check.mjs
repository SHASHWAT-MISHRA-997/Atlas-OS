// Daily check that the live site and the real providers still behave as ATLAS expects. It uses
// deliberately invalid keys, so nothing is billed and no account is needed: each real service must
// refuse the key in the way ATLAS turns into a clear message. A change on a provider's side (a moved
// endpoint, a public list that accepts any key, new error wording) fails this check.
//
//   node scripts/netlify/provider-check.mjs [https://atlas-os-sm.netlify.app]
const site = (process.argv[2] || 'https://atlas-os-sm.netlify.app').replace(/\/$/, '');
const BAD = { groq: 'gsk_atlas_daily_check_invalid', gemini: 'AIzaAtlasDailyCheckInvalidKey000000000', openrouter: 'sk-or-atlas-daily-check-invalid', openai: 'sk-atlas-daily-check-invalid-0000' };
const results = [];
const check = async (name, fn) => {
  try { results.push([name, 'PASS', await fn()]); } catch (err) { results.push([name, 'FAIL', err.message]); }
};
const expect = (ok, detail) => { if (!ok) throw new Error(detail); return detail; };

async function cloud(path, body) {
  const r = await fetch(site + '/cloud/' + path, { method: 'POST', headers: { 'Content-Type': 'application/json', Origin: site }, body: JSON.stringify(body) });
  return { status: r.status, data: await r.json().catch(() => ({})) };
}

function socket(url, protocols, first) {
  return new Promise((resolve) => {
    const ws = protocols ? new WebSocket(url, protocols) : new WebSocket(url);
    const messages = [];
    const timer = setTimeout(() => { try { ws.close(); } catch { /* closed */ } resolve({ code: 'timeout', reason: '', messages }); }, 20000);
    ws.onopen = () => { if (first) ws.send(JSON.stringify(first)); };
    ws.onmessage = (e) => messages.push(String(e.data));
    ws.onclose = (e) => { clearTimeout(timer); resolve({ code: e.code, reason: e.reason, messages }); };
    ws.onerror = () => {};
  });
}

await check('live site: version.json', async () => {
  const v = await (await fetch(site + '/version.json?t=' + Date.now())).json();
  return expect(/^\d+\.\d+\.\d+$/.test(v.version), 'version ' + v.version);
});
await check('live site: /cloud/status lists the four providers', async () => {
  const s = await (await fetch(site + '/cloud/status')).json();
  const ids = (s.providers || []).map((p) => p.id).join(',');
  return expect(ids === 'groq,gemini,openrouter,openai', ids);
});
for (const provider of ['groq', 'gemini', 'openrouter', 'openai']) {
  await check(provider + ': a wrong key is refused when checking it', async () => {
    const r = await cloud('models', { provider, api_key: BAD[provider] });
    return expect(r.status === 502 && /HTTP 40[013].*Check your API key/.test(r.data.detail || ''), r.status + ' ' + (r.data.detail || JSON.stringify(r.data)).slice(0, 160));
  });
}
await check('gemini: real-time model list refuses a wrong key', async () => {
  const r = await cloud('models', { provider: 'gemini', api_key: BAD.gemini, live: true });
  return expect(r.status === 502 && /Check your API key/.test(r.data.detail || ''), r.status + ' ' + (r.data.detail || '').slice(0, 160));
});
await check('groq: chat refuses a wrong key', async () => {
  const r = await cloud('chat', { provider: 'groq', api_key: BAD.groq, model: 'llama-3.1-8b-instant', messages: [{ role: 'user', content: 'hi' }], stream: false });
  return expect(r.status === 502 && /HTTP 401/.test(r.data.detail || ''), r.status + ' ' + (r.data.detail || '').slice(0, 160));
});
await check('gemini: speech refuses a wrong key', async () => {
  const r = await cloud('speak', { provider: 'gemini', api_key: BAD.gemini, text: 'hello', voice: 'Puck' });
  return expect(r.status === 502 && /Check your API key/.test(r.data.detail || ''), r.status + ' ' + (r.data.detail || '').slice(0, 160));
});
// One second of 16 kHz silence as a WAV file, like the app's recorder makes.
const n = 16000;
const wav = Buffer.alloc(44 + n * 2);
wav.write('RIFF', 0); wav.writeUInt32LE(36 + n * 2, 4); wav.write('WAVEfmt ', 8); wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
wav.writeUInt32LE(16000, 24); wav.writeUInt32LE(32000, 28); wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write('data', 36); wav.writeUInt32LE(n * 2, 40);
for (const provider of ['groq', 'gemini']) {
  await check(provider + ': transcription refuses a wrong key', async () => {
    const r = await cloud('transcribe', { provider, api_key: BAD[provider], audio: wav.toString('base64') });
    return expect(r.status === 502 && /Check your API key/.test(r.data.detail || ''), r.status + ' ' + (r.data.detail || '').slice(0, 160));
  });
}
await check('gemini: Live WebSocket closes with Google\'s reason for a wrong key', async () => {
  const r = await socket('wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key=' + BAD.gemini, null,
    { setup: { model: 'models/gemini-2.5-flash-native-audio-preview-12-2025', generationConfig: { responseModalities: ['AUDIO'] } } });
  return expect(/api key/i.test(r.reason), 'close ' + r.code + ' "' + r.reason + '"');
});
await check('openai: Realtime WebSocket sends an error, then closes, for a wrong key', async () => {
  const r = await socket('wss://api.openai.com/v1/realtime?model=gpt-realtime', ['realtime', 'openai-insecure-api-key.' + BAD.openai]);
  const err = r.messages.map((m) => { try { return JSON.parse(m); } catch { return {}; } }).find((m) => m.type === 'error');
  return expect(err && err.error && /api key/i.test(err.error.message || ''), 'close ' + r.code + ' "' + r.reason + '", error: ' + (err ? err.error.message : 'none').slice(0, 100));
});
for (const [name, state, detail] of results) console.log(state.padEnd(5) + name + ' — ' + detail);
const failed = results.filter((r) => r[1] === 'FAIL').length;
console.log('\n' + (results.length - failed) + ' passed, ' + failed + ' failed');
process.exitCode = failed ? 1 : 0;
