// Netlify entry point for the ATLAS OS online edition. All logic lives in ../lib/cloud.mjs.
// Every visitor uses their own provider key. The one optional environment variable is
// ATLAS_YOUTUBE_KEY: a plain Google API key limited to the YouTube Data API, used only to find the
// video for "play …" (AI Studio keys cannot call that API). Without it, Gemini finds the video.
import { createHandler } from '../lib/cloud.mjs';

const handle = createHandler({ youtubeKey: process.env.ATLAS_YOUTUBE_KEY || '' });

export default (req) => handle(req);

export const config = {
  path: '/cloud/*',
  // Caps how fast one visitor can call the function.
  rateLimit: { windowLimit: 60, windowSize: 60, aggregateBy: ['ip', 'domain'] },
};
