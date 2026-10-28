// Phone actions for Live: call, SMS, WhatsApp, directions, YouTube, a website, or sharing text. A web
// page may not dial, send or open other apps by itself, so the model only prepares the action: ATLAS
// shows it as a button with everything filled in, and nothing happens until the user taps it. Nothing
// is read from the phone (no contacts, messages or notifications) unless the user picks a contact.
// Loaded only when the Live screen opens.
(function () {
  'use strict';

  const str = (description) => ({ type: 'string', description });
  const obj = (properties, required) => ({ type: 'object', properties, required: required || Object.keys(properties) });
  const TOOLS = [
    { name: 'call_phone', description: 'Prepare a phone call on this device. Give the number with country code if known (e.g. +919876543210), or only the contact name if the user did not say a number.', parameters: obj({ number: str('Phone number, digits with optional +'), name: str('Who is called, if said') }, []) },
    { name: 'send_sms', description: 'Prepare an SMS on this device with the text filled in; the user taps Send in their messages app.', parameters: obj({ number: str('Phone number, or empty to choose in the app'), name: str('Who it is for, if said'), text: str('Message text') }, ['text']) },
    { name: 'send_whatsapp', description: 'Prepare a WhatsApp message with the text filled in; the user taps Send in WhatsApp. Number with country code (e.g. 919876543210), or empty to choose the chat in WhatsApp.', parameters: obj({ number: str('Number with country code, or empty'), name: str('Who it is for, if said'), text: str('Message text') }, ['text']) },
    { name: 'navigate_to', description: 'Prepare directions to a place in Google Maps on this device.', parameters: obj({ place: str('Place or address') }) },
    { name: 'play_youtube', description: 'Prepare a YouTube search on this device, to play a song or video.', parameters: obj({ query: str('What to play') }) },
    { name: 'open_website', description: 'Prepare a web address (http or https) to open on this device.', parameters: obj({ url: str('Full http(s) address') }) },
    { name: 'share_text', description: 'Prepare text to share to any app on this device (the share sheet).', parameters: obj({ text: str('Text to share') }) },
  ];
  const NAMES = new Set(TOOLS.map((t) => t.name));

  const PROMPT = 'On this device you can prepare actions with the phone tools: call, SMS, WhatsApp, Google Maps directions, YouTube, a website, or sharing text. ' +
    'A tool only shows a button on the screen; nothing happens until the user taps it, so say "tap the button to …", never that you called, sent or opened anything. ' +
    'You cannot read contacts, messages, notifications or call history; if the user names a person without a number, pass the name and they can pick the contact. ';

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
