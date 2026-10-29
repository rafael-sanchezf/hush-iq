/**
 * The own-key settings, in the classmates' build only: options.ts mounts this card behind `if (__BYOK__)`, so the
 * judged build ships none of it. Provider, key and model; the key is shown masked once saved and never put back in
 * a field. Test key asks the API's `POST /key-check`; Remove key deletes it from this browser.
 */
import { OWN, PROVIDERS, checkKey, loadKey, looksLikeKey, mask, removeKey, saveKey } from '../lib/byok.ts';
import type { OwnKey, Provider } from '../lib/byok.ts';
import { CONFIG, REPO_URL, load } from '../lib/config.ts';
import { h } from '../panel/dom.ts';

const link = (href: string, text: string) => h('a', { href, target: '_blank', rel: 'noopener' }, text);

export async function ownKeyCard(): Promise<HTMLElement> {
  await load();
  await loadKey();

  const provider = h('select', { id: 'provider', 'aria-label': 'Provider' },
    (Object.keys(PROVIDERS) as Provider[]).map((p) => h('option', { value: p }, PROVIDERS[p].name)));
  const key = h('input', { id: 'own-key', type: 'password', autocomplete: 'off', spellcheck: 'false', placeholder: 'Paste your API key' });
  const model = h('input', { id: 'own-model', type: 'text', autocomplete: 'off', spellcheck: 'false', placeholder: 'The server’s default for this provider' });
  const saved = h('p', { class: 'small' });
  const status = h('p', { class: 'small', role: 'status' });
  const where = h('span');
  const remove = h('button', { type: 'button', class: 'btn ghost small' }, 'Remove key');

  const draw = () => {
    const k = OWN.key;
    if (k) {
      provider.value = k.provider;
      model.value = k.model;
    }
    saved.textContent = k ? `Saved: ${PROVIDERS[k.provider].name} key ${mask(k.key)}${k.model ? `, model ${k.model}` : ''}.` : 'No key saved. The house model reads, while it is on.';
    remove.disabled = !k;
    where.textContent = CONFIG.apiBase;
  };

  /** What the fields hold, or the saved key when the key field is empty and the provider has not changed. */
  const typed = (): OwnKey | null => {
    const p = provider.value as Provider;
    const k = key.value.trim();
    if (k) return looksLikeKey(k) ? { provider: p, key: k, model: model.value.trim() } : null;
    return OWN.key && OWN.key.provider === p ? { ...OWN.key, model: model.value.trim() } : null;
  };

  const save = h('button', {
    type: 'button', class: 'btn small',
    onclick: async () => {
      const k = typed();
      if (!k) {
        status.textContent = key.value.trim() ? 'That does not look like an API key: one string, no spaces.' : `Paste your ${PROVIDERS[provider.value as Provider].name} key first.`;
        return;
      }
      await saveKey(k);
      key.value = '';
      draw();
      status.textContent = 'Saved in this browser. The panel uses it from the next listing.';
    },
  }, 'Save key');

  const test = h('button', {
    type: 'button', class: 'btn ghost small',
    onclick: async () => {
      const k = typed();
      if (!k) {
        status.textContent = 'Paste a key, or save one, to test it.';
        return;
      }
      status.textContent = 'Asking the provider through the Hush IQ API…';
      test.disabled = true;
      const r = await checkKey(k);
      test.disabled = false;
      status.textContent = `${r.ok ? '✓' : '✕'} ${r.message}`;
    },
  }, 'Test key');

  remove.addEventListener('click', async () => {
    await removeKey();
    key.value = '';
    model.value = '';
    draw();
    status.textContent = 'Removed from this browser.';
  });

  draw();
  return h('section', { class: 'card', id: 'own-key-card' },
    h('div', { class: 'q-title' }, h('span', null, 'Your own model key')),
    h('p', { class: 'small' }, 'Use your own Meta, OpenAI or Anthropic key for the AI reading, for when the house model is off or to try another. Same prompt, same checks on every line it cites, whichever provider reads.'),
    h('label', { class: 'select' }, h('span', null, 'Provider'), provider),
    h('label', { class: 'field', for: 'own-key' }, 'API key', key),
    saved,
    h('label', { class: 'field', for: 'own-model' }, 'Model (optional)', model),
    h('p', { class: 'small' }, 'Leave it blank for the default the eval picked. The server takes only the model ids on its list.'),
    h('div', { class: 'actions' }, save, test, remove),
    status,
    h('p', { class: 'small' },
      'Your key is sent to the Hush IQ server at ', where, ' with each reading, over https, in a request header. The server uses it once, for that request, to call your provider, and never stores or logs it. In this browser it stays in Chrome’s local storage, which is not synced to your Google account. The code is public, so you can read what happens to it: ',
      link(REPO_URL, 'the repository'), '.'),
    h('p', { class: 'small' },
      'A Claude Pro or ChatGPT Plus subscription is not an API key. Make one on ',
      link(PROVIDERS.anthropic.keyPage!, 'Anthropic’s API keys page'), ' or ', link(PROVIDERS.openai.keyPage!, 'OpenAI’s API keys page'),
      '; the provider bills you for what it uses, separately from any subscription.'),
  );
}
