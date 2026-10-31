// Phone actions for Live: call, SMS, WhatsApp, directions, YouTube, a website, or sharing text. ATLAS
// opens the dialer, the message or the page by itself when the browser lets it (app.js), and shows a
// button with everything filled in when the browser blocks that. It never dials or sends: the user
// presses Call or Send in their own app. Nothing is read from the phone (no contacts, messages or
// notifications) unless the user picks a contact. Loaded only when the Live screen opens.
(function () {
  'use strict';

  const str = (description) => ({ type: 'string', description });
  const obj = (properties, required) => ({ type: 'object', properties, required: required || Object.keys(properties) });
  const TOOLS = [
    // Named dial_number: with the name "call_phone", Google's Gemini Live server ended the session with
    // "Internal error occurred" whenever the model called it (seen on the owner's phone, 2026-10-28).
    { name: 'dial_number', description: 'Open the phone dialer with this number filled in; the user presses Call. Give the number with country code if known, or only the name of the person if the user did not say a number.', parameters: obj({ number: str('Phone number, digits with optional +'), name: str('Who is called, if said') }, []) },
    { name: 'send_sms', description: 'Open an SMS on this device with the text filled in; the user presses Send in their messages app.', parameters: obj({ number: str('Phone number, or empty to choose in the app'), name: str('Who it is for, if said'), text: str('Message text') }, ['text']) },
    { name: 'send_whatsapp', description: 'Open a WhatsApp message with the text filled in; the user presses Send in WhatsApp. Number with country code (e.g. 919876543210), or empty to choose the chat in WhatsApp.', parameters: obj({ number: str('Number with country code, or empty'), name: str('Who it is for, if said'), text: str('Message text') }, ['text']) },
    { name: 'navigate_to', description: 'Open directions to a place in Google Maps on this device.', parameters: obj({ place: str('Place or address') }) },
    { name: 'play_youtube', description: 'Open a YouTube search on this device, to play a song or video.', parameters: obj({ query: str('What to play') }) },
    { name: 'open_website', description: 'Open a web address (http or https) on this device.', parameters: obj({ url: str('Full http(s) address') }) },
    { name: 'share_text', description: 'Show the share button for text to share to any app on this device (the share sheet).', parameters: obj({ text: str('Text to share') }) },
  ];
  const NAMES = new Set([...TOOLS.map((t) => t.name), 'call_phone']); // the old name still works (ACTION lines)

  // Checked against the real Gemini Live service: with a softer wording the model said "tap the button"
  // without calling the tool, so no button appeared. The "must call in that same turn" wording stays.
  const PROMPT = 'You have phone tools: dial_number, send_sms, send_whatsapp, navigate_to, play_youtube, open_website and share_text. ' +
    'When the user asks to call someone, send an SMS or WhatsApp, get directions, play something on YouTube, open a website or share text, you must call the matching tool in that same turn: nothing opens and no button appears unless you call the tool. ' +
    'After the tool result, say in a few natural words exactly what its message says happened: if it opened, say it is open; if it says a button is on the screen, ask the user to tap it. ' +
    'Never say a call was made or a message was sent: the user presses Call or Send in their own app. Never claim something opened unless the result says so. ' +
    'You cannot read contacts, messages, notifications or call history; if the user names a person without a number, call the tool with only the name. ';

  const isIOS = () => /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

  /** A phone number as dialable characters, or '' when there is none or it does not look like one. */
  function cleanNumber(raw) {
    const n = String(raw || '').replace(/[\s().-]/g, '');
    return /^\+?\d{3,15}$/.test(n) ? n : '';
  }
  const text = (raw, max) => String(raw || '').trim().slice(0, max);

  /**
   * Turns a tool call into what the screen shows: { ok, message, card: { title, label, href, share, pickContact } }.
   * href is only ever tel:, sms: or https: to a fixed site (or the user's own http(s) address for open_website).
   */
  function plan(name, args) {
    const a = args && typeof args === 'object' ? args : {};
    const who = text(a.name, 60);
    const number = cleanNumber(a.number);
    const body = text(a.text, 1000);
    const fail = (message) => ({ ok: false, message });
    switch (name) {
      case 'dial_number':
      case 'call_phone': {
        if (!number && !who) return fail('Say the number or who to call.');
        return card('Call ' + (who || number) + (who && number ? ' (' + number + ')' : ''), 'Call ' + (number || who), number ? 'tel:' + number : '', !number && who);
      }
      case 'send_sms': {
        if (!body) return fail('Say what the message should say.');
        const href = 'sms:' + number + (isIOS() ? '&' : '?') + 'body=' + encodeURIComponent(body);
        return card('SMS ' + (who || number || '') + ': "' + body + '"', 'Open messages', href, !number && who, { number, body, kind: 'sms' });
      }
      case 'send_whatsapp': {
        if (!body) return fail('Say what the message should say.');
        const digits = number.replace(/^\+/, '');
        return card('WhatsApp ' + (who || (digits ? '+' + digits : 'a chat you choose')) + ': "' + body + '"', 'Open WhatsApp',
          'https://wa.me/' + digits + '?text=' + encodeURIComponent(body));
      }
      case 'navigate_to': {
        const place = text(a.place, 200);
        if (!place) return fail('Say where to go.');
        return card('Directions to ' + place, 'Open Google Maps', 'https://www.google.com/maps/dir/?api=1&destination=' + encodeURIComponent(place));
      }
      case 'play_youtube': {
        const q = text(a.query, 200);
        if (!q) return fail('Say what to play.');
        return card('YouTube: ' + q, 'Open YouTube', 'https://www.youtube.com/results?search_query=' + encodeURIComponent(q));
      }
      case 'open_website': {
        let u;
        try { u = new URL(text(a.url, 2000)); } catch { return fail('That is not a web address.'); }
        if (u.protocol !== 'https:' && u.protocol !== 'http:') return fail('Only http and https web addresses can be opened.');
        return card('Open ' + u.host, 'Open ' + u.host, u.href);
      }
      case 'share_text': {
        if (!body) return fail('Say what to share.');
        return { ok: true, message: 'A Share button is on the screen; the user taps it to choose an app.', card: { title: 'Share: "' + body + '"', label: 'Share', share: body } };
      }
      default:
        return fail('Unknown phone action "' + name + '".');
    }
  }

  // app.js replaces this message when it opened the link by itself.
  function card(title, label, href, pickContact, sms) {
    const what = href ? 'A button "' + label + '" is on the screen; the user taps it to do it.' : 'The user needs to pick the contact on the screen first.';
    return { ok: true, message: what, card: { title, label, href, pickContact: !!pickContact, sms } };
  }

  /** Gemini wants the type names in capitals (its own schema format). */
  function geminiSchema(s) {
    if (Array.isArray(s)) return s.map(geminiSchema);
    if (!s || typeof s !== 'object') return s;
    const out = {};
    for (const [k, v] of Object.entries(s)) out[k] = k === 'type' ? String(v).toUpperCase() : k === 'properties' ? Object.fromEntries(Object.entries(v).map(([n, p]) => [n, geminiSchema(p)])) : v;
    return out;
  }

  window.AtlasPhone = {
    TOOLS,
    PROMPT,
    has: (name) => NAMES.has(name),
    geminiDecls: () => TOOLS.map((t) => ({ name: t.name, description: t.description, parameters: geminiSchema(t.parameters) })),
    openaiTools: () => TOOLS.map((t) => ({ type: 'function', name: t.name, description: t.description, parameters: t.parameters })),
    /** Tool list for the ACTION-line prompt (turn by turn). */
    describe: () => TOOLS.map((t) => t.name + '(' + Object.keys(t.parameters.properties).join(', ') + '): ' + t.description).join(' | '),
    /** {name, args} from a model reply that is an ACTION line, or null (same format as pc.js). */
    parseAction(reply) {
      const t = String(reply || '');
      const at = t.search(/\bACTION\b:?\s*\{/);
      if (at < 0) return null;
      try {
        const a = JSON.parse(t.slice(t.indexOf('{', at), t.lastIndexOf('}') + 1));
        return a && typeof a.name === 'string' ? { name: a.name, args: a.args && typeof a.args === 'object' ? a.args : {} } : null;
      } catch { return null; }
    },
    plan,
    cleanNumber,
    isIOS,
    /** The Contact Picker (Android Chrome): the user picks one contact; only its name and numbers are read. */
    canPickContact: () => !!(navigator.contacts && navigator.contacts.select),
    async pickContact() {
      const [c] = await navigator.contacts.select(['name', 'tel'], { multiple: false });
      return c ? { name: (c.name && c.name[0]) || '', number: cleanNumber((c.tel && c.tel[0]) || '') } : null;
    },
  };
})();
