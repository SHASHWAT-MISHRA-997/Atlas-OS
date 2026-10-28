// Builds dist/ for Netlify: the web app, with the version added to its script and style URLs.
import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const out = join(root, 'dist');
rmSync(out, { recursive: true, force: true });
mkdirSync(out);
cpSync(join(root, 'frontend', 'static'), join(out, 'static'), { recursive: true });
cpSync(join(root, 'frontend', 'static', 'sw.js'), join(out, 'sw.js'));
// The privacy policy app stores (Microsoft Store) and visitors can read: /privacy.html
cpSync(join(root, 'frontend', 'privacy.html'), join(out, 'privacy.html'));

const version = readFileSync(join(root, 'VERSION'), 'utf8').trim();
const html = readFileSync(join(root, 'frontend', 'index.html'), 'utf8');
if (!html.includes('<script src="/static/app.js" defer></script>')) throw new Error('index.html no longer loads /static/app.js the expected way');
// ?v= makes browsers fetch new files after an update; app.js also reads it to know its own version.
writeFileSync(join(out, 'index.html'), html.replace(/(\/static\/(?:app|cloud)\.(?:js|css))/g, '$1?v=' + version));
// The app compares this with its own version to show "New version available".
writeFileSync(join(out, 'version.json'), JSON.stringify({ version }) + '\n');
console.log('ATLAS build ' + version + ' written to dist/');
