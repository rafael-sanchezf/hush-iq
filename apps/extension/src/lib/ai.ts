/**
 * The AI switch, from the shared contract: headers on `POST /read` and `POST /verdict`, never query parameters, so
 * nothing lands in a URL or a log line. `X-HushIQ-AI: on|off` goes in every build. The provider, key and model go
 * only in the classmates' build, and only where lib/byok.ts allows: the configured API base, over https.
 */
import { keyHeaders, scrub } from './byok.ts';
import { CONFIG } from './config.ts';
import type { AiInfo } from './types.ts';

export type AiPath = '/read' | '/verdict';

/** A request to a service that may call a model. The URL is always the API base's own. `ai` says whether this one
 * reads with a model: the settings' default, or on for a renter's "Power up with AI". */
export function aiFetch(path: AiPath, init: Omit<RequestInit, 'headers'> & { headers: Record<string, string> }, ai = CONFIG.ai): Promise<Response> {
  const url = `${CONFIG.apiBase}${path}`;
  const headers: Record<string, string> = { ...init.headers, 'X-HushIQ-AI': ai ? 'on' : 'off' };
  if (__BYOK__) Object.assign(headers, keyHeaders(url));
  return fetch(url, { ...init, headers });
}

/** Text from a service, safe to show: the classmates' build blanks the renter's key out of it. */
export function safe(text: string): string {
  return __BYOK__ ? scrub(text) : text;
}

/** The label for a result made here, without a model, because the switch is off and the service could not be reached. */
export const AI_OFF: AiInfo = {
  mode: 'basic',
  provider: null,
  model: null,
  key: null,
  reason: 'switched_off',
  message: 'AI reading is off in settings, so fixed rules read the listing and a template writes the verdict. The score is the same.',
};
