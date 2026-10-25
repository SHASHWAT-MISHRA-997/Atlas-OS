// Netlify entry point for the ATLAS OS cloud edition. All logic lives in ../lib/cloud.mjs.
import { getStore } from '@netlify/blobs';
import { createHandler } from '../lib/cloud.mjs';

const ENV_NAMES = [
  'GROQ_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_GEMINI_BASE_URL', 'OPENAI_API_KEY', 'OPENAI_BASE_URL',
  'ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL', 'ATLAS_ACCESS_CODE',
];

export default async (req, context) => {
  const env = Object.fromEntries(ENV_NAMES.map((name) => [name, Netlify.env.get(name) || '']));
  env.SITE_NAME = (context && context.site && context.site.name) || '';
  const store = getStore({ name: 'atlas-cloud', consistency: 'strong' });
  return createHandler({ store, env })(req);
};

export const config = {
  path: '/cloud/*',
  // Caps how fast one visitor can call the function (and so spend model credits).
  rateLimit: { windowLimit: 60, windowSize: 60, aggregateBy: ['ip', 'domain'] },
};
