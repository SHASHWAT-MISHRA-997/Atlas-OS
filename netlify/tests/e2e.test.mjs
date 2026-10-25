// Browser test of the cloud edition: built dist/ + the /cloud function with a FAKE model (labelled
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
  page.on('console', (m) => { if (m.type() === 'error' && !/status of 40[139]/.test(m.text())) page.errors.push(m.text()); });
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

test('owner claims, chats with the cloud model, plans, and pairs a second device', async () => {
  const owner = await phone();
  await owner.goto(base + '/');
  await owner.waitForSelector('#cloudgate');
  assert.equal(await owner.textContent('#cgtitle'), 'Make this ATLAS yours');
  await shot(owner, '1-claim');
  await noSideScroll(owner);
  await owner.fill('#cgname', 'Shashwat phone');
  await owner.click('#cloudgate button[type=submit]');
  await owner.waitForSelector('#sysstatus >> text=Signed in: Shashwat phone (owner)', { state: 'attached' });
  assert.equal(await owner.locator('#cloudgate').count(), 0);
  await owner.waitForSelector('#topstatus >> text=AI ready · Cloud');

  // AI Chat: real round trip through the function (FAKE upstream model).
  await go(owner, 'chat');
  await owner.waitForFunction(() => /^fake-/.test(document.querySelector('#atlasmodel')?.value || ''));
  assert.equal(await owner.inputValue('#atlasprovider'), 'groq');
  await owner.click('#atlasbilling');
  await owner.fill('.composer-input', 'namaste');
  await owner.click('.sendbtn');
  await owner.waitForSelector('.bubble >> text=FAKE reply to: namaste');
  await owner.waitForSelector('.bubble .meta >> text=Answered by Groq (cloud)');
  await shot(owner, '2-chat');
  await noSideScroll(owner);
  // History is kept in this browser.
  await owner.reload();
  await go(owner, 'chat');
  await owner.waitForSelector('.bubble >> text=FAKE reply to: namaste');
  assert.equal(await owner.$eval('#chatsettings', (d) => d.open), false, 'notice already confirmed on this device');
  assert.equal(await owner.isChecked('#atlasbilling'), true);
  await shot(owner, '2b-chat-again');

  // Home plan is written by the cloud model.
  await go(owner, 'home');
  await owner.fill('#command', 'Plan my exam week');
  await owner.click('#run');
  await owner.waitForSelector('#tasksteps >> text=FAKE step one');
  assert.match(await owner.textContent('#message'), /on Groq \(cloud\)/);

  // PC-only features say so instead of pretending.
  await go(owner, 'tasks');
  await owner.waitForSelector('text=need ATLAS installed on your Windows PC');
  await go(owner, 'automations');
  await owner.waitForSelector('text=Scheduled tasks need ATLAS running on your PC');

  // Pair a second device.
  await go(owner, 'devices');
  await owner.fill('#devicename', 'Tablet');
  await owner.click('text=Create pairing link');
  const link = await (await owner.waitForSelector('#pairlink')).textContent();
  assert.match(link, new RegExp('^' + base + '/#pair=[\\w-]{40,}$'));
  await shot(owner, '3-devices');

  const tablet = await phone();
  await tablet.goto(link);
  await tablet.waitForSelector('#cgtitle >> text=Join this ATLAS');
  await tablet.click('#cloudgate button[type=submit]');
  await tablet.waitForSelector('#sysstatus >> text=Signed in: Tablet', { state: 'attached' });
  assert.ok(!tablet.url().includes('pair='), 'pairing code removed from the address bar');

  // The same link does not work twice.
  const stranger = await phone();
  await stranger.goto(link);
  await stranger.click('#cloudgate button[type=submit]');
  await stranger.waitForSelector('.cg-msg >> text=invalid, already used or expired');
  await stranger.goto(base + '/');
  await stranger.waitForSelector('#cgtitle >> text=This ATLAS is private');
  assert.equal(await stranger.locator('#cloudgate button').count(), 0);

  // Owner removes the tablet; it is signed out.
  await owner.reload();
  await go(owner, 'devices');
  await owner.waitForSelector('#devicelist >> text=Tablet');
  owner.once('dialog', (d) => d.accept());
  await owner.click('#devicelist button');
  await owner.waitForSelector('#devicelist >> text=No other devices are paired.');
  await tablet.reload();
  await tablet.waitForSelector('#cgtitle >> text=This ATLAS is private');

  for (const p of [owner, tablet, stranger]) assert.deepEqual(p.errors, []);
  await Promise.all([owner, tablet, stranger].map((p) => p.context().close()));
});

test('without an AI key the app explains how to add one in Netlify', async () => {
  const bare = await startServer(port + 1, {});
  try {
    const page = await phone();
    await page.goto('http://localhost:' + (port + 1) + '/');
    await page.click('#cloudgate button[type=submit]');
    await page.waitForSelector('#cloudsetup >> text=Set up AI: no model key yet');
    await page.waitForSelector('#topstatus >> text=AI not set up · Cloud');
    await shot(page, '4-setup');
    await noSideScroll(page);
    await go(page, 'chat');
    await page.waitForSelector('#atlasprovider', { state: 'attached' });
    assert.equal(await page.$eval('#atlasprovider', (s) => s.selectedOptions[0].textContent), 'No AI key set up yet');
    assert.deepEqual(page.errors, []);
    await page.context().close();
  } finally {
    bare.kill();
  }
});
