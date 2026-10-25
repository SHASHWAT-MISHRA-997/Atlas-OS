// Builds dist/ for the Netlify cloud edition: the normal frontend with frontend/cloud/ loaded first.
import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const out = join(root, 'dist');
rmSync(out, { recursive: true, force: true });
mkdirSync(out);
cpSync(join(root, 'frontend', 'static'), join(out, 'static'), { recursive: true });
// /cloud/* belongs to the function, so the cloud files are served from /static/.
for (const name of ['cloud.js', 'cloud.css']) cpSync(join(root, 'frontend', 'cloud', name), join(out, 'static', name));
cpSync(join(root, 'frontend', 'static', 'sw.js'), join(out, 'sw.js'));

const version = readFileSync(join(root, 'VERSION'), 'utf8').trim();
let html = readFileSync(join(root, 'frontend', 'index.html'), 'utf8');
const appScript = '<script src="/static/app.js" defer></script>';
if (!html.includes(appScript)) throw new Error('index.html no longer loads /static/app.js the expected way');
// The online edition has no local models: say so in the page itself, before app.js runs.
const swap = (from, to) => {
  if (!html.includes(from)) throw new Error('index.html no longer contains: ' + from);
  html = html.replace(from, to);
};
swap('<small>Local models (Ollama)</small>', '<small>Your AI keys</small>');
swap('ATLAS asks your local model for a plan', 'ATLAS asks your cloud AI model for a plan');
html = html
  .replace(appScript, '<link rel="stylesheet" href="/static/cloud.css">\n<script src="/static/cloud.js" defer></script>\n' + appScript)
  .replace('<title>ATLAS OS — Agentic Workspace</title>', '<title>ATLAS OS — Online</title>')
  .replace(/(\/static\/(?:app|cloud)\.(?:js|css))/g, '$1?v=' + version);
writeFileSync(join(out, 'index.html'), html);
console.log('ATLAS cloud build ' + version + ' written to dist/');
