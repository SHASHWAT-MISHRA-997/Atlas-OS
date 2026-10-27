// Screenshots of the real app for the README, taken from the local preview with the labelled FAKE
// model (every reply says "FAKE") and FAKE Google, Gemini Live and speech services. No real key,
// account or personal data is used.
//
//   node scripts/netlify/build.mjs && node scripts/netlify/screenshots.mjs
//
// Writes docs/images/*.png. Set ATLAS_E2E_CHROMIUM to use an installed Chromium.
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const root = fileURLToPath(new URL('../../', import.meta.url));
const out = fileURLToPath(new URL('../../docs/images/', import.meta.url));
const port = 8870 + Math.floor(Math.random() * 20);
const base = 'http://localhost:' + port;
mkdirSync(out, { recursive: true });

const server = spawn(process.execPath, ['scripts/netlify/dev-server.mjs'], { cwd: root, env: { ...process.env, PORT: String(port), ATLAS_FAKE_MODEL: '1' }, stdio: ['ignore', 'pipe', 'inherit'] });
await new Promise((resolve) => server.stdout.on('data', (d) => { if (String(d).includes('preview on')) resolve(); }));
const args = ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'];
const browser = await chromium.launch(process.env.ATLAS_E2E_CHROMIUM ? { executablePath: process.env.ATLAS_E2E_CHROMIUM, args } : { args });

// Demo keys (not real) so the screens show the app as it looks once set up.
const seed = (theme) => {
  localStorage.setItem('atlas.theme', theme);
  localStorage.setItem('atlas.cloud.key.groq', JSON.stringify('gsk_FAKE_demo_key_for_screenshots'));
  localStorage.setItem('atlas.cloud.key.gemini', JSON.stringify('AIza-FAKE-demo-key'));
  localStorage.setItem('atlas.cloud.ack.groq', 'true');
  localStorage.setItem('atlas.os.chat.settings.v1', JSON.stringify({ provider: 'groq', model: 'fake-large' }));
  localStorage.setItem('atlas.google.clientid.v1', JSON.stringify('123456789012-fakeclientidforscreens.apps.googleusercontent.com'));
};

const FAKE_GIS = `window.google = { accounts: { oauth2: {
  initTokenClient(cfg) { return { requestAccessToken() { setTimeout(() => cfg.callback({ access_token: 'FAKE', expires_in: 3599, scope: cfg.scope }), 10); } }; },
  revoke(t, done) { if (done) done({}); } } } };`;

async function fakeServices(page) {
  await page.route('https://accounts.google.com/gsi/client', (r) => r.fulfill({ contentType: 'text/javascript', body: FAKE_GIS }));
  const at = (days, h, m) => { const d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() + days); d.setHours(h, m); return d.toISOString(); };
  await page.route(/^https:\/\/(www|gmail)\.googleapis\.com\//, (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/events')) return route.fulfill({ json: { items: [
      { summary: 'Team standup (demo)', start: { dateTime: at(0, 9, 30) }, end: { dateTime: at(0, 10, 0) } },
      { summary: 'Project review (demo)', start: { dateTime: at(0, 15, 0) }, end: { dateTime: at(0, 16, 0) } },
      { summary: 'Gym (demo)', start: { dateTime: at(1, 7, 0) }, end: { dateTime: at(1, 8, 0) } }] } });
    if (url.pathname.endsWith('/messages')) return route.fulfill({ json: { messages: [{ id: 'a' }, { id: 'b' }, { id: 'c' }] } });
    const n = { a: ['Demo Bank', 'Your monthly statement is ready (demo)'], b: ['Demo Airline', 'Your boarding pass (demo)'], c: ['Demo Team', 'Notes from today\'s review (demo)'] }[url.pathname.split('/').pop()];
    return route.fulfill({ json: { internalDate: String(Date.now()), payload: { headers: [{ name: 'From', value: n[0] + ' <noreply@example.com>' }, { name: 'Subject', value: n[1] }] } } });
  });
  await page.routeWebSocket(/generativelanguage\.googleapis\.com/, (ws) => ws.onMessage((raw) => { if (JSON.parse(String(raw)).setup) ws.send(JSON.stringify({ setupComplete: {} })); }));
}

async function open(theme, size) {
  const context = await browser.newContext({ viewport: size, deviceScaleFactor: size.width < 500 ? 2 : 1, colorScheme: theme, serviceWorkers: 'block', reducedMotion: 'reduce', ...(size.width < 500 ? { isMobile: true, hasTouch: true } : {}) });
  const page = await context.newPage();
  await page.addInitScript(seed, theme);
  await fakeServices(page);
  await page.goto(base + '/');
  await page.waitForSelector('#topstatus >> text=AI ready');
  return page;
}

const go = async (page, section) => {
  const tab = page.locator('.tabbar [data-section="' + section + '"]');
  if (await tab.isVisible()) { await tab.click(); return; }
  if (await page.locator('#morebtn').isVisible()) await page.click('#morebtn');
  await page.click('.nav [data-section="' + section + '"]');
};
const snap = (page, name) => page.screenshot({ path: out + name + '.png' }).then(() => console.log('wrote docs/images/' + name + '.png'));
const DESKTOP = { width: 1440, height: 900 };
const PHONE = { width: 390, height: 844 };

try {
  // Home with a plan (desktop, dark).
  let page = await open('dark', DESKTOP);
  await page.fill('#command', 'Plan my exam week');
  await page.click('#run');
  await page.waitForSelector('#tasksteps >> text=FAKE step one');
  await snap(page, 'home-desktop-dark');

  // AI Chat (desktop, dark).
  await go(page, 'chat');
  await page.waitForSelector('.composer-input');
  for (const q of ['What should I revise first for physics?', 'Make it a 3-day plan']) {
    await page.fill('.composer-input', q);
    await page.click('.sendbtn');
    await page.waitForSelector('text=FAKE reply to: ' + q);
  }
  await snap(page, 'chat-desktop-dark');

  // Integrations with Google Calendar and Gmail connected (desktop, dark).
  await go(page, 'integrations');
  await page.click('#googleconnect:not([disabled])');
  await page.waitForSelector('#googlemail >> text=Demo Bank');
  await page.locator('#googlepanel').scrollIntoViewIfNeeded();
  await snap(page, 'integrations-google-desktop-dark');
  await page.context().close();

  // Phone: Home, Live with the voice check, System (light).
  page = await open('dark', PHONE);
  await snap(page, 'home-phone-dark');
  await go(page, 'live');
  await page.waitForSelector('#liveorb');
  await snap(page, 'live-phone-dark');
  await page.click('#livetest');
  await page.waitForSelector('#livestatus >> text=Voice check done', { timeout: 30000 });
  await page.locator('#livetestresults').scrollIntoViewIfNeeded();
  await snap(page, 'voice-check-phone-dark');
  await page.context().close();

  page = await open('light', PHONE);
  await snap(page, 'home-phone-light');
  await go(page, 'chat');
  await page.fill('.composer-input', 'Kal ka plan batao');
  await page.click('.sendbtn');
  await page.waitForSelector('text=FAKE reply to: Kal ka plan batao');
  await snap(page, 'chat-phone-light');
  await page.context().close();
} finally {
  await browser.close();
  server.kill();
}
