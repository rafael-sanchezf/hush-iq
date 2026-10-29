/**
 * The service worker. Two doors into the panel, both on a click by the renter on a supported listing site:
 *
 * - the toolbar icon reads the open tab (activeTab grants this tab, this once) and opens the side panel;
 * - the right-click item "Score this with Hush IQ" sends the selected text instead.
 *
 * The panel belongs to the listing's tab (Rafa, 2026-10-29): the icon is live only on the sites in lib/sites.ts and
 * greys out elsewhere; switching to another tab hides the panel and switching back shows it again; navigating the
 * tab off those sites closes it; moving to another page on them asks for a new click. Nothing runs on any page
 * until a click, and nothing is sent anywhere from here: the panel sends the listing to the Hush IQ API.
 */
import { captureListing, captureSelection } from './capture.ts';
import type { Capture, CaptureMessage } from './lib/capture-types.ts';
import { MAX_CHARS, MAX_PHOTOS } from './lib/capture-types.ts';
import { SITE_PATTERNS, samePage, supported } from './lib/sites.ts';

const MENU_ID = 'hush-iq-score-selection';

const newId = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
const keyOf = (tabId: number) => `capture:${tabId}`;
const pathOf = (tabId: number) => `panel.html?tab=${tabId}`;

function hand(tabId: number, msg: CaptureMessage): Promise<void> {
  return chrome.storage.session.set({ [keyOf(tabId)]: msg });
}

// ---------------------------------------------------------------- the panel follows the listing's tab

/** Icon and panel for one tab: live on a supported site, greyed and closed anywhere else. */
async function sync(tabId: number, url: string | undefined): Promise<void> {
  const on = supported(url);
  try {
    await (on ? chrome.action.enable(tabId) : chrome.action.disable(tabId));
    const now = await chrome.sidePanel.getOptions({ tabId });
    // Setting the same options again could reload an open panel, and a reload scores the listing again.
    if (on && !(now.enabled && now.path === pathOf(tabId))) await chrome.sidePanel.setOptions({ tabId, path: pathOf(tabId), enabled: true });
    if (!on && now.enabled !== false) await chrome.sidePanel.setOptions({ tabId, enabled: false });
  } catch {
    /* the tab closed in between */
  }
}

/** A new page in the same tab: the old score no longer applies, so the panel asks for a click on this one. */
async function newPage(tabId: number, url: string): Promise<void> {
  const key = keyOf(tabId);
  const msg = (await chrome.storage.session.get(key))[key] as CaptureMessage | undefined;
  const was = msg?.ok ? msg.capture.url : undefined;
  if (was && !samePage(was, url)) await hand(tabId, { id: newId(), ok: false, error: 'new_page', url });
}

async function syncAll(): Promise<void> {
  // Off by default everywhere; each supported tab turns its own icon and panel on.
  await chrome.action.disable();
  await chrome.sidePanel.setOptions({ enabled: false });
  for (const tab of await chrome.tabs.query({})) if (tab.id !== undefined) await sync(tab.id, tab.url);
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: MENU_ID, title: 'Score this with Hush IQ', contexts: ['selection'], documentUrlPatterns: SITE_PATTERNS });
  void syncAll();
});
chrome.runtime.onStartup.addListener(() => void syncAll());

// Host permissions on the listing sites give their tabs' URLs, and only theirs: no URL means not supported.
chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  void sync(tabId, tab.url);
  if (info.url && supported(info.url)) void newPage(tabId, info.url);
});
chrome.tabs.onActivated.addListener(({ tabId }) => {
  chrome.tabs.get(tabId).then((tab) => sync(tabId, tab.url), () => undefined);
});
chrome.tabs.onRemoved.addListener((tabId) => void chrome.storage.session.remove(keyOf(tabId)));

function why(e: unknown, url?: string): string {
  const m = String((e as Error)?.message ?? e);
  if (/cannot be scripted|cannot access|chrome:\/\/|extensions gallery|webstore/i.test(m) || /^(chrome|edge|about|view-source|devtools):/.test(url ?? '')) {
    return 'Chrome does not let extensions read this page. Open the listing itself, or paste its text below.';
  }
  if (/permission|activeTab/i.test(m)) return 'Click the Hush IQ icon on the listing to let it read that page.';
  return `Could not read this page: ${m}`;
}

/** Opens this tab's panel. Called inside the click: anything awaited first would lose the gesture. */
function openPanel(tabId: number): void {
  void chrome.sidePanel.setOptions({ tabId, path: pathOf(tabId), enabled: true });
  void chrome.sidePanel.open({ tabId });
}

chrome.action.onClicked.addListener((tab) => {
  if (tab.id === undefined) return;
  openPanel(tab.id);
  void readTab(tab.id, tab);
});

async function readTab(tabId: number, tab: chrome.tabs.Tab): Promise<void> {
  const id = newId();
  await hand(tabId, { id, ok: false, error: 'reading', url: tab.url });
  try {
    const [res] = await chrome.scripting.executeScript({ target: { tabId }, func: captureListing, args: [MAX_CHARS, MAX_PHOTOS] });
    const capture = res?.result as Capture | undefined;
    if (!capture) return hand(tabId, { id, ok: false, error: 'The page returned nothing to read.', url: tab.url });
    await hand(tabId, { id, ok: true, capture });
  } catch (e) {
    await hand(tabId, { id, ok: false, error: why(e, tab.url), url: tab.url });
  }
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId !== MENU_ID || tab?.id === undefined) return;
  openPanel(tab.id);
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
  if (tab.id === undefined) return;
  await hand(tab.id, {
    id: newId(),
    ok: true,
    capture: {
      url: tab.url ?? '', host, site: 'other', title: tab.title ?? '', text: text.slice(0, MAX_CHARS), photos: [], postal: null,
      selection: true, captured_at: new Date().toISOString(),
    },
  });
}
