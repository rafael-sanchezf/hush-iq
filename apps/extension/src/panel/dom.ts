/** A small element builder, so the panel needs no framework. Strings are always text, never HTML. */
type Child = Node | string | number | null | undefined | false;
type Attrs = Record<string, string | number | boolean | null | undefined | EventListener>;

export function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs?: Attrs | null, ...kids: (Child | Child[])[]): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs ?? {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v as EventListener);
    else if (k === 'class') el.className = String(v);
    else if (k === 'style') el.setAttribute('style', String(v));
    else if (k in el && typeof v !== 'string') (el as unknown as Record<string, unknown>)[k] = v;
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  append(el, kids);
  return el;
}

export function append(el: Element, kids: (Child | Child[])[]): void {
  for (const k of kids.flat()) {
    if (k === null || k === undefined || k === false) continue;
    el.append(k instanceof Node ? k : String(k));
  }
}

export function clear(el: Element): void {
  while (el.firstChild) el.firstChild.remove();
}

export function glyph(status: string | undefined): HTMLSpanElement {
  const s = status ?? 'ok';
  const mark = s === 'ok' ? '✓' : s === 'cant_tell' ? '?' : s === 'refused' ? '✕' : s === 'working' ? '' : '!';
  return h('span', { class: `glyph ${s}`, 'aria-hidden': 'true' }, mark);
}
