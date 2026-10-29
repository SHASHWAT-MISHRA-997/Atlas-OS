// PC control for Live: talks to the ATLAS PC helper, a small program the user runs on their own
// Windows PC (pc-helper/ in the repository). The helper listens only on this computer
// (127.0.0.1), needs the token this browser got by pairing with the code it shows, and asks
// "Allow?" on the PC itself before typing, pressing keys or closing a window. It has no shell, no
// delete and no shutdown. Loaded only when the Live screen opens.
(function () {
  'use strict';

  const BASE = 'http://127.0.0.1:47823';
  const TOKEN_KEY = 'atlas.pc.v1'; // { token, computer, on }
  const DOWNLOAD = 'https://github.com/SHASHWAT-MISHRA-997/Atlas-OS/releases/latest/download/AtlasHelper.exe';

  const str = (description) => ({ type: 'string', description });
  const obj = (properties, required) => ({ type: 'object', properties, required: required || Object.keys(properties) });
  /** What Live may ask the helper to do: the same list goes to Gemini, OpenAI and turn by turn. */
  const TOOLS = [
    { name: 'open_app', description: 'Open an installed app on the user\'s Windows PC by its Start menu name, e.g. Notepad, Google Chrome, Spotify, WhatsApp, Word, Settings.', parameters: obj({ name: str('App name') }) },
    { name: 'list_apps', description: 'List installed apps on the PC, optionally filtered, to find the exact name before open_app.', parameters: obj({ filter: str('Part of the name, or empty for all') }, []) },
    { name: 'open_url', description: 'Open a web address (http or https) in the PC\'s browser.', parameters: obj({ url: str('Full http(s) address') }) },
    { name: 'web_search', description: 'Search the web on the PC and show the results in the browser. site: google, youtube, bing, maps or wikipedia. Use youtube to play a song or video.', parameters: obj({ query: str('What to search for'), site: { type: 'string', enum: ['google', 'youtube', 'bing', 'maps', 'wikipedia'] } }, ['query']) },
    { name: 'media', description: 'Press a media key: play_pause, next, previous, stop, mute, volume_up or volume_down. steps (1-50) is for volume; each step is 2%.', parameters: obj({ key: { type: 'string', enum: ['play_pause', 'next', 'previous', 'stop', 'mute', 'volume_up', 'volume_down'] }, steps: { type: 'integer', description: 'Volume steps of 2%' } }, ['key']) },
    { name: 'find_files', description: 'Find files by name in the user\'s Desktop, Documents, Downloads, Pictures, Music, Videos and OneDrive. Returns full paths.', parameters: obj({ query: str('Words from the file name') }) },
    { name: 'open_file', description: 'Open a document, picture, song or video (full path, usually from find_files) in its usual app. Programs and scripts are never opened.', parameters: obj({ path: str('Full path') }) },
    { name: 'open_folder', description: 'Open a folder in File Explorer: desktop, documents, downloads, pictures, music, videos, home, or a full path inside the user folder.', parameters: obj({ folder: str('Folder name or path') }) },
    { name: 'write_note', description: 'Save a new text note in Documents\\ATLAS Notes (never overwrites).', parameters: obj({ title: str('Short title'), text: str('Note text') }) },
    { name: 'type_text', description: 'Type text into the window that is in front on the PC. The user must click Allow on the PC first.', parameters: obj({ text: str('Text to type') }) },
    { name: 'press_keys', description: 'Press a keyboard shortcut like "ctrl+s", "alt+tab", "pagedown", "ctrl+plus". Most shortcuts ask the user to Allow on the PC first.', parameters: obj({ keys: str('Keys joined with +') }) },
    { name: 'window', description: 'Act on the window in front: show_desktop, switch, maximize, minimize, snap_left, snap_right, fullscreen, or close (close asks to Allow on the PC).', parameters: obj({ action: { type: 'string', enum: ['show_desktop', 'switch', 'maximize', 'minimize', 'snap_left', 'snap_right', 'fullscreen', 'close'] } }) },
    { name: 'lock_pc', description: 'Lock the PC (Windows sign-in screen).', parameters: obj({}, []) },
    { name: 'system_info', description: 'Read the PC\'s time, battery, free disk space and the title of the window in front.', parameters: obj({}, []) },
  ];

  /** Gemini wants the type names in capitals (its own schema format). */
  function geminiSchema(s) {
    if (Array.isArray(s)) return s.map(geminiSchema);
    if (!s || typeof s !== 'object') return s;
    const out = {};
    for (const [k, v] of Object.entries(s)) out[k] = k === 'type' ? String(v).toUpperCase() : k === 'properties' ? Object.fromEntries(Object.entries(v).map(([n, p]) => [n, geminiSchema(p)])) : v;
    return out;
  }

  const PROMPT = 'You can control the user\'s Windows PC through the ATLAS PC helper tools: open apps, websites and files, search, play media, change volume, type, press shortcuts and manage windows. ' +
    'When the user asks for something on the PC, call the tool, then say in a few words what happened, from the tool result. Never say something was done unless the result says ok. ' +
    'If the result says the user did not allow it, say so. Typing, most shortcuts and closing windows show an Allow box on the PC: tell the user to click Yes there. ' +
    'You cannot delete files, run commands, install software or shut down; say so if asked.';

  function saved() {
    try { return JSON.parse(localStorage.getItem(TOKEN_KEY) || 'null'); } catch { return null; }
  }
  function save(v) {
    try { if (v) localStorage.setItem(TOKEN_KEY, JSON.stringify(v)); else localStorage.removeItem(TOKEN_KEY); } catch { /* storage blocked */ }
  }

  /**
   * What to do when the browser could not reach the helper at all. The browser does not say
   * whether the helper is closed or the site was blocked from this PC, so both are named,
   * with the setting for this browser (Brave blocked it on the owner's PC until "Localhost access" was allowed).
   */
  async function blockedHint() {
    let denied = false;
    try { denied = (await navigator.permissions.query({ name: 'local-network-access' })).state === 'denied'; } catch { /* not in this browser */ }
    if (navigator.brave) {
      return 'In Brave, this site must be allowed to reach this PC: click the icon left of the address, open Site settings, set Localhost access to Allow (or go to brave://settings/content/localhostAccess), then reload the page.';
    }
    if (denied) {
      return 'This browser is blocking this site from reaching this PC: click the icon left of the address, open Site settings, set Local network access to Allow, then reload the page.';
    }
    if (/Chrome|Edg\//.test(navigator.userAgent)) {
      return 'If the browser asked to let this site access devices on your local network, allow it (Site settings, Local network access), then reload the page.';
    }
    return 'If your browser blocks sites from reaching this PC, allow it for this site, then reload the page.';
  }

  async function call(path, { method = 'GET', body, timeout = 4000 } = {}) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeout);
    const s = saved();
    let res;
    try {
      res = await fetch(BASE + path, {
        method, signal: ctrl.signal, cache: 'no-store', credentials: 'omit',
        headers: { 'Content-Type': 'application/json', ...(s && s.token ? { Authorization: 'Bearer ' + s.token } : {}) },
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch (err) {
      const e = new Error(err.name === 'AbortError' ? 'The ATLAS helper did not answer in time. Check that AtlasHelper is open on this PC.'
        : 'Could not reach the ATLAS helper. Open AtlasHelper on this PC if it is closed. ' + await blockedHint());
      e.offline = true;
      throw e;
    } finally {
      clearTimeout(timer);
    }
    const data = await res.json().catch(() => ({}));
    if (res.status === 401 && s) { save(null); const e = new Error('This browser is no longer paired. Pair again with a new code.'); e.unpaired = true; throw e; }
    if (!res.ok) throw new Error(data.error || 'The ATLAS helper said ' + res.status + '.');
    return data;
  }

  window.AtlasPC = {
    TOOLS,
    PROMPT,
    DOWNLOAD,
    BASE,
    // Gemini refuses an OBJECT with no properties, so tools without arguments send no parameters.
    geminiTools: () => [{ functionDeclarations: TOOLS.map((t) => ({ name: t.name, description: t.description, ...(Object.keys(t.parameters.properties).length ? { parameters: geminiSchema(t.parameters) } : {}) })) }],
    openaiTools: () => TOOLS.map((t) => ({ type: 'function', name: t.name, description: t.description, parameters: t.parameters })),
    /** For models without tool calling (turn by turn): one ACTION line per step. */
    textPrompt: () => PROMPT + ' To use a tool, reply with only one line: ACTION {"name": "<tool>", "args": {...}} and nothing else; you will get the result back. Tools: ' +
      TOOLS.map((t) => t.name + '(' + Object.keys(t.parameters.properties).join(', ') + '): ' + t.description).join(' | '),
    /** {name, args} from a model reply that is an ACTION line, or null. */
    parseAction(text) {
      // Models sometimes add a code fence or a word around the line: take the JSON after ACTION.
      const t = String(text || '');
      const at = t.search(/\bACTION\b:?\s*\{/);
      if (at < 0) return null;
      try {
        const a = JSON.parse(t.slice(t.indexOf('{', at), t.lastIndexOf('}') + 1));
        return a && typeof a.name === 'string' ? { name: a.name, args: a.args && typeof a.args === 'object' ? a.args : {} } : null;
      } catch { return null; }
    },
    saved,
    /** Paired and switched on. */
    enabled: () => { const s = saved(); return !!(s && s.token && s.on !== false); },
    setOn(on) { const s = saved(); if (s) save({ ...s, on: !!on }); },
    hello: () => call('/hello', { timeout: 2500 }),
    async pair(code) {
      const d = await call('/pair', { method: 'POST', body: { code } });
      save({ token: d.token, computer: d.computer, on: true });
      return d;
    },
    async unpair() {
      try { await call('/unpair', { method: 'POST', body: {} }); } catch { /* helper closed: forget it here anyway */ }
      save(null);
    },
    /** Runs one action; always resolves with a result object the model can read. */
    async run(name, args) {
      try {
        // Allow boxes wait up to a minute for the user on the PC.
        return await call('/action', { method: 'POST', body: { name, args: args || {} }, timeout: 75000 });
      } catch (err) {
        return { ok: false, message: err.message };
      }
    },
  };
})();
