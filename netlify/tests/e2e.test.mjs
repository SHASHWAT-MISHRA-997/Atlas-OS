// Browser test of the online edition: built dist/ + the /cloud function with a FAKE model (labelled
// "FAKE" in every reply). Run: node scripts/netlify/build.mjs && node --test netlify/tests/e2e.test.mjs
// Set ATLAS_E2E_CHROMIUM to use an already installed Chromium; SHOTS=dir saves phone screenshots.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { after, before, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const root = fileURLToPath(new URL('../../', import.meta.url));
const port = 8900 + Math.floor(Math.random() * 90);
const base = 'http://localhost:' + port;
let server;
let browser;

function startServer(port, extraEnv) {
  const child = spawn(process.execPath, ['scripts/netlify/dev-server.mjs'], { cwd: root, env: { ...process.env, PORT: String(port), GROQ_API_KEY: '', GEMINI_API_KEY: '', OPENAI_API_KEY: '', ANTHROPIC_API_KEY: '', ...extraEnv }, stdio: ['ignore', 'pipe', 'inherit'] });
  return new Promise((resolve, reject) => {
    child.stdout.on('data', (d) => { if (String(d).includes('preview on')) resolve(child); });
    child.on('exit', (code) => reject(new Error('dev server exited ' + code)));
  });
}

before(async () => {
  server = await startServer(port, { ATLAS_FAKE_MODEL: '1' });
  browser = await chromium.launch(process.env.ATLAS_E2E_CHROMIUM ? { executablePath: process.env.ATLAS_E2E_CHROMIUM } : {});
});

after(async () => {
  await browser?.close();
  server?.kill();
});

async function phone() {
  const context = await browser.newContext({ viewport: { width: 360, height: 760 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  page.errors = [];
  page.on('pageerror', (e) => page.errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error' && !/status of (40[139]|422|502)/.test(m.text())) page.errors.push(m.text()); });
  return page;
}

const shot = async (page, name) => { if (process.env.SHOTS) await page.screenshot({ path: process.env.SHOTS + '/' + name + '.png', fullPage: false }); };
const noSideScroll = async (page) => assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'page scrolls sideways');
const go = async (page, section) => {
  const tab = page.locator('.tabbar [data-section="' + section + '"]');
  if (await tab.count()) { await tab.click(); return; }
  await page.click('#morebtn');
  await page.click('.nav [data-section="' + section + '"]');
};

const noOllama = async (page) => assert.ok(!/ollama/i.test(await page.evaluate(() => document.body.innerText)), 'the online app mentions Ollama');

test('a visitor gets a free key, chats, plans, and the key stays on their phone', async () => {
  const page = await phone();
  await page.goto(base + '/');
  await page.waitForSelector('#topstatus >> text=Add your key · Cloud');
  assert.equal(await page.locator('#cloudgate').count(), 0, 'no sign-in screen');
  // Home starts with a "get a free key" banner linking to the free providers' key pages.
  await page.waitForSelector('#keybanner >> text=Start here: get a free AI key');
  assert.deepEqual(await page.$$eval('#keybanner a', (as) => as.map((a) => a.href)),
    ['https://console.groq.com/keys', 'https://aistudio.google.com/apikey', 'https://openrouter.ai/settings/keys']);
  await noOllama(page);
  await shot(page, '1-home');
  await noSideScroll(page);

  // Home plan without a key explains what to do.
  await page.fill('#command', 'Plan my exam week');
  await page.click('#run');
  await page.waitForSelector('#message >> text=Add your own Groq API key first');

  // "Set up my free key" opens AI Chat with the key card.
  await page.click('#keybanner >> text=Set up my free key');
  await page.waitForSelector('#keycard:not(.hidden)');
  assert.equal(await page.inputValue('#atlasprovider'), 'groq');
  assert.deepEqual(await page.$$eval('#keycardprovider option', (os) => os.map((o) => o.value)), ['groq', 'gemini', 'openrouter']);
  assert.equal(await page.getAttribute('#getkeylink', 'href'), 'https://console.groq.com/keys');
  await page.selectOption('#keycardprovider', 'gemini');
  await page.waitForSelector('#getkeylink[href="https://aistudio.google.com/apikey"]');
  assert.equal(await page.inputValue('#atlasprovider'), 'gemini');
  await page.selectOption('#keycardprovider', 'groq');
  await page.waitForSelector('#getkeylink >> text=Open Groq key page');
  await noOllama(page);
  await shot(page, '2-keycard');
  await noSideScroll(page);

  // Until there is a key, only the key card is shown (no chat box to type into yet).
  assert.equal(await page.isVisible('.composer'), false);
  assert.equal(await page.isVisible('#chatsettings'), false);

  // A wrong key is checked with the provider and not saved.
  await page.fill('#keycardinput', 'wrong-key-123');
  await page.click('#keycardsave');
  await page.waitForSelector('#keycard >> text=Invalid API Key');
  assert.equal(await page.isVisible('#keycard'), true);
  assert.equal(await page.evaluate(() => localStorage.getItem('atlas.cloud.key.groq')), null);

  // The visitor's own key: saved, models load, chat works.
  await page.fill('#keycardinput', 'my-own-test-key-456');
  await page.click('#keycardsave');
  await page.waitForSelector('#keycard', { state: 'hidden' });
  await page.waitForFunction(() => /^fake-/.test(document.querySelector('#atlasmodel')?.value || ''));
  await page.fill('.composer-input', 'namaste');
  await page.click('.sendbtn');
  await page.waitForSelector('.bubble >> text=FAKE reply to: namaste');
  await page.waitForSelector('.bubble .meta >> text=Answered by Groq (cloud)');
  await shot(page, '3-chat');
  await noSideScroll(page);
  assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('atlas.cloud.key.groq'))), 'my-own-test-key-456');

  // Remembered on this phone: after a reload the key and history are still there.
  await page.reload();
  await page.waitForSelector('#topstatus >> text=AI ready · Cloud');
  assert.equal(await page.locator('#keybanner').count(), 0, 'no banner once a key is added');
  await go(page, 'chat');
  await page.waitForSelector('.bubble >> text=FAKE reply to: namaste');
  assert.equal(await page.inputValue('#atlaskey'), 'my-own-test-key-456');
  assert.equal(await page.isVisible('#keycard'), false);
  assert.equal(await page.$eval('#chatsettings', (d) => d.open), false, 'notice already confirmed on this device');

  // Home plan uses the same key.
  await go(page, 'home');
  await page.fill('#command', 'Plan my exam week');
  await page.click('#run');
  await page.waitForSelector('#tasksteps >> text=FAKE step one');
  assert.match(await page.textContent('#message'), /on Groq \(cloud\)/);

  // Tasks screen fills in the key; PC-only features say so.
  await go(page, 'tasks');
  await page.waitForSelector('text=need ATLAS installed on your Windows PC');
  assert.equal(await page.inputValue('#taskkey'), 'my-own-test-key-456');
  await go(page, 'automations');
  await page.waitForSelector('text=Scheduled tasks need ATLAS running on your PC');
  await go(page, 'devices');
  await page.waitForSelector('text=there is no sign-in or pairing');
  await go(page, 'integrations');
  await page.waitForSelector('text=Free cloud AI with your own key');
  await noOllama(page);

  // Untick "Remember": the key is removed from this browser.
  await go(page, 'chat');
  await page.click('#chatsettings summary');
  await page.uncheck('#atlasremember');
  assert.equal(await page.evaluate(() => localStorage.getItem('atlas.cloud.key.groq')), null);

  // Another phone starts empty: no key, no history.
  const other = await phone();
  await other.goto(base + '/');
  await go(other, 'chat');
  await other.waitForSelector('#keycard:not(.hidden)');
  assert.equal(await other.inputValue('#atlaskey'), '');
  assert.equal(await other.locator('.bubble').count(), 0);

  for (const p of [page, other]) assert.deepEqual(p.errors, []);
  await Promise.all([page, other].map((p) => p.context().close()));
});
