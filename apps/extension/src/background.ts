/**
 * The service worker. Two doors into the panel, both on a click by the renter:
 *
 * - the toolbar icon reads the open tab (activeTab grants this tab, this once) and opens the side panel;
 * - the right-click item "Score this with Hush IQ" sends the selected text instead.
 *
 * Nothing runs on any page until one of those clicks, and nothing is sent anywhere from here: the panel shows
 * what was read, the renter trims it, and only the panel's "Score it" sends it to the Hush IQ API.
 */
import { captureListing, captureSelection } from './capture.ts';
import type { Capture, CaptureMessage } from './lib/capture-types.ts';
import { MAX_CHARS, MAX_PHOTOS } from './lib/capture-types.ts';

const MENU_ID = 'hush-iq-score-selection';

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: MENU_ID, title: 'Score this with Hush IQ', contexts: ['selection'] });
});

const newId = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

function hand(msg: CaptureMessage): Promise<void> {
  return chrome.storage.session.set({ capture: msg });
}

function why(e: unknown, url?: string): string {
  const m = String((e as Error)?.message ?? e);
  if (/cannot be scripted|cannot access|chrome:\/\/|extensions gallery|webstore/i.test(m) || /^(chrome|edge|about|view-source|devtools):/.test(url ?? '')) {
    return 'Chrome does not let extensions read this page. Open the listing itself, or paste its text below.';
  }
  if (/permission|activeTab/i.test(m)) return 'Click the Hush IQ icon on the listing to let it read that page.';
  return `Could not read this page: ${m}`;
}

chrome.action.onClicked.addListener((tab) => {
  // The panel opens inside the click; anything awaited first would lose the gesture.
  void chrome.sidePanel.open({ windowId: tab.windowId });
  void readTab(tab);
});

async function readTab(tab: chrome.tabs.Tab): Promise<void> {
  const id = newId();
  await chrome.storage.session.set({ capture: { id, ok: false, error: 'reading', url: tab.url } satisfies CaptureMessage });
  if (tab.id === undefined) return hand({ id, ok: false, error: 'No tab to read.' });
  try {
    const [res] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: captureListing, args: [MAX_CHARS, MAX_PHOTOS] });
    const capture = res?.result as Capture | undefined;
    if (!capture) return hand({ id, ok: false, error: 'The page returned nothing to read.', url: tab.url });
    await hand({ id, ok: true, capture });
  } catch (e) {
    await hand({ id, ok: false, error: why(e, tab.url), url: tab.url });
  }
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId !== MENU_ID || !tab) return;
  void chrome.sidePanel.open({ windowId: tab.windowId });
  void readSelection(info, tab);
});

async function readSelection(info: chrome.contextMenus.OnClickData, tab: chrome.tabs.Tab): Promise<void> {
  let text = info.selectionText ?? '';
  if (tab.id !== undefined) {
    try {
      const [res] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: captureSelection });
      if (typeof res?.result === 'string' && res.result.length >= text.length * 0.8) text = res.result;
    } catch {
      /* the menu's own copy of the selection is enough */
    }
  }
  let host = '';
  try {
    host = new URL(tab.url ?? '').hostname.replace(/^www\./, '');
  } catch {
    /* no URL on this tab */
  }
  await hand({
    id: newId(),
    ok: true,
    capture: {
      url: tab.url ?? '', host, site: 'other', title: tab.title ?? '', text: text.slice(0, MAX_CHARS), photos: [], postal: null,
      selection: true, captured_at: new Date().toISOString(),
    },
  });
}
