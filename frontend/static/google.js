// Google Calendar and Gmail, read-only. The visitor signs in with Google Identity Services' token
// client; the access token is kept in this page's memory only (never stored, never sent to ATLAS's
// server) and is used straight from the browser with two read-only scopes. Nothing is sent,
// deleted or changed. Loaded only when the Integrations screen opens.
(function () {
  'use strict';

  const SCOPES = ['https://www.googleapis.com/auth/calendar.readonly', 'https://www.googleapis.com/auth/gmail.readonly'];
  const GIS_URL = 'https://accounts.google.com/gsi/client';
  const CALENDAR = 'https://www.googleapis.com/calendar/v3/calendars/primary/events';
  const GMAIL = 'https://gmail.googleapis.com/gmail/v1/users/me/messages';
  /** What a Google OAuth Web client ID looks like: digits-letters.apps.googleusercontent.com */
  const CLIENT_ID = /^[0-9]{6,30}-[a-z0-9_]{8,64}\.apps\.googleusercontent\.com$/;

  let token = null; // { value, expires, scopes }
  let gis = null;

  /** Loads Google's sign-in script once. */
  function load() {
    if (!gis) {
      gis = new Promise((resolve, reject) => {
        if (window.google && window.google.accounts && window.google.accounts.oauth2) { resolve(); return; }
        const tag = document.createElement('script');
        tag.src = GIS_URL;
        tag.async = true;
        tag.onload = () => (window.google && window.google.accounts && window.google.accounts.oauth2 ? resolve() : reject(new Error('Google sign-in did not load.')));
        tag.onerror = () => { gis = null; reject(new Error('Google sign-in could not be loaded. Check your internet, or turn off a blocker for accounts.google.com.')); };
        document.head.append(tag);
      });
    }
    return gis;
  }

  const loaded = () => !!(window.google && window.google.accounts && window.google.accounts.oauth2);

  /** Why Google refused, in words a person can act on. */
  function signInError(code, description) {
    if (code === 'access_denied') return 'Google sign-in was cancelled or refused. While the Google app is in Testing mode, only accounts added as test users can sign in.';
    if (code === 'popup_closed') return 'The Google sign-in window was closed before it finished.';
    if (code === 'popup_failed_to_open') return 'The browser blocked the Google sign-in window. Allow pop-ups for this site and try again.';
    return 'Google sign-in failed: ' + (description || code || 'unknown error') + '.';
  }

  /**
   * Opens Google's sign-in window (call it straight from a tap, so it is not blocked) and resolves
   * with the scopes the user allowed. Google may let the user untick one of the two.
   */
  function connect(clientId) {
    if (!CLIENT_ID.test(clientId)) return Promise.reject(new Error('That is not a Google OAuth client ID.'));
    if (!loaded()) return Promise.reject(new Error('Google sign-in is still loading. Try again in a moment.'));
    return new Promise((resolve, reject) => {
      const client = window.google.accounts.oauth2.initTokenClient({
        client_id: clientId,
        scope: SCOPES.join(' '),
        include_granted_scopes: false,
        callback: (resp) => {
          if (!resp || resp.error || !resp.access_token) { reject(new Error(signInError(resp && resp.error, resp && resp.error_description))); return; }
          const granted = String(resp.scope || '').split(/\s+/).filter((s) => SCOPES.includes(s));
          token = { value: resp.access_token, expires: Date.now() + (Number(resp.expires_in) || 3600) * 1000 - 60000, scopes: granted };
          resolve(granted);
        },
        error_callback: (err) => reject(new Error(signInError(err && err.type, err && err.message))),
      });
      client.requestAccessToken();
    });
  }

  const connected = () => !!token && Date.now() < token.expires;
  const has = (scope) => connected() && token.scopes.includes(scope);

  /** A GET to a Google API with the token. Only GETs exist here: nothing is ever changed. */
  async function get(url) {
    if (!connected()) { token = null; throw new Error('Not connected to Google. Connect again.'); }
    const response = await fetch(url, { headers: { Authorization: 'Bearer ' + token.value } });
    let data = {};
    try { data = await response.json(); } catch { /* not JSON */ }
    if (response.status === 401) { token = null; throw new Error('Your Google sign-in expired. Connect again.'); }
    if (!response.ok) {
      const why = (data.error && data.error.message) || 'HTTP ' + response.status;
      throw new Error(response.status === 403 && /has not been used|is disabled/i.test(why)
        ? 'Google says this API is not turned on for the sign-in app: ' + why
        : 'Google answered: ' + why);
    }
    return data;
  }

  const startOfDay = (d, plus) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + plus);

  /** Events on the primary calendar today and tomorrow, as { day, title, start, end, allDay }. */
  async function events(now = new Date()) {
    if (!has(SCOPES[0])) throw new Error('Calendar access was not allowed. Sign out and connect again, and tick Calendar.');
    const from = startOfDay(now, 0);
    const tomorrow = startOfDay(now, 1);
    const q = new URLSearchParams({ timeMin: from.toISOString(), timeMax: startOfDay(now, 2).toISOString(), singleEvents: 'true', orderBy: 'startTime', maxResults: '50' });
    const data = await get(CALENDAR + '?' + q);
    return (data.items || []).filter((e) => e.status !== 'cancelled').map((e) => {
      const allDay = !!(e.start && e.start.date && !e.start.dateTime);
      const start = allDay ? new Date(e.start.date + 'T00:00:00') : new Date(e.start && e.start.dateTime);
      const end = allDay ? null : new Date(e.end && e.end.dateTime);
      return { day: start < tomorrow ? 'today' : 'tomorrow', title: String(e.summary || '(no title)'), start, end, allDay };
    }).filter((e) => !Number.isNaN(e.start.getTime()));
  }

  /** The 10 latest unread emails, as { from, address, subject, date }. Headers only, never the body. */
  async function unread() {
    if (!has(SCOPES[1])) throw new Error('Gmail access was not allowed. Sign out and connect again, and tick Gmail.');
    const list = await get(GMAIL + '?' + new URLSearchParams({ q: 'is:unread', maxResults: '10' }));
    const ids = (list.messages || []).slice(0, 10).map((m) => String(m.id)).filter((id) => /^[0-9a-zA-Z_-]+$/.test(id));
    const metaQuery = 'format=metadata&metadataHeaders=Subject&metadataHeaders=From&metadataHeaders=Date';
    const messages = await Promise.all(ids.map((id) => get(GMAIL + '/' + id + '?' + metaQuery)));
    return messages.map((m) => {
      const header = (name) => ((m.payload && m.payload.headers) || []).find((h) => String(h.name).toLowerCase() === name);
      const from = String((header('from') || {}).value || '');
      const named = /^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$/.exec(from);
      return {
        from: named && named[1] ? named[1] : named ? named[2] : from,
        address: named ? named[2] : from,
        subject: String((header('subject') || {}).value || '(no subject)'),
        date: m.internalDate ? new Date(Number(m.internalDate)) : null,
      };
    });
  }

  /** Revokes the token with Google and forgets it. */
  function signOut() {
    const value = token && token.value;
    token = null;
    if (!value || !loaded()) return Promise.resolve();
    return new Promise((resolve) => window.google.accounts.oauth2.revoke(value, () => resolve()));
  }

  window.AtlasGoogle = { SCOPES, validClientId: (id) => CLIENT_ID.test(String(id || '')), load, loaded, connect, connected, has, events, unread, signOut };
})();
