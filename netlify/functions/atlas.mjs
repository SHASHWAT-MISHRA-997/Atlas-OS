// Netlify entry point for the ATLAS OS online edition. All logic lives in ../lib/cloud.mjs.
// No environment variables are read: every visitor uses their own provider key.
import { createHandler } from '../lib/cloud.mjs';

const handle = createHandler();

export default (req) => handle(req);

export const config = {
  path: '/cloud/*',
  // Caps how fast one visitor can call the function.
  rateLimit: { windowLimit: 60, windowSize: 60, aggregateBy: ['ip', 'domain'] },
};
