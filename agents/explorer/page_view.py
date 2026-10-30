"""
TestSphere-AI — What the explorer sees of a live page.

A text-only model cannot look at a screenshot, so each step it gets the page
as text: where it is, the start of the visible text, and a numbered list of
the elements it can act on.  Each element carries the locators a recording
replays with: a primary locator that is unique on the page (the most stable
attribute first) and fallbacks the healer can use when the page changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MAX_ELEMENTS = 80
MAX_PAGE_TEXT = 1500

# Runs in the page: visible, interactive elements with a label and locators.
# CSS locators are checked for uniqueness here; text locators (Playwright's
# :has-text) are fallbacks only, since the DOM cannot evaluate them.
_READ_PAGE_JS = r"""
(max) => {
  const esc = (v) => (window.CSS && CSS.escape) ? CSS.escape(v) : v.replace(/[^\w-]/g, (c) => '\\' + c);
  const q = (v) => v.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  const unique = (sel) => { try { return document.querySelectorAll(sel).length === 1; } catch (e) { return false; } };
  const visible = (el) => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
  };
  const label = (el) => {
    const text = (el.getAttribute('aria-label') || el.innerText || el.value || el.getAttribute('placeholder')
      || el.getAttribute('title') || (el.querySelector('img[alt]') || {}).alt || el.getAttribute('name') || '');
    return text.replace(/\s+/g, ' ').trim().slice(0, 80);
  };
  const path = (el) => {
    const parts = [];
    for (let e = el; e && e.nodeType === 1 && e !== document.body; e = e.parentElement) {
      let i = 1, sib = e;
      while ((sib = sib.previousElementSibling)) if (sib.tagName === e.tagName) i++;
      parts.unshift(e.tagName.toLowerCase() + ':nth-of-type(' + i + ')');
    }
    return 'body > ' + parts.join(' > ');
  };
  const roleOf = (el) => {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase(), type = (el.getAttribute('type') || 'text').toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'button' || tag === 'summary') return 'button';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') {
      if (['submit', 'button', 'reset', 'image'].includes(type)) return 'button';
      if (['checkbox', 'radio'].includes(type)) return type;
      return 'textbox';
    }
    return 'button';  // [onclick], [tabindex] widgets act like buttons
  };
  const SEL = 'a[href], button, input:not([type=hidden]), select, textarea, summary, '
    + '[role=button], [role=link], [role=tab], [role=menuitem], [role=checkbox], [role=radio], [role=option], '
    + '[role=combobox], [role=switch], [onclick]';
  const out = [];
  for (const el of document.querySelectorAll(SEL)) {
    if (out.length >= max) break;
    if (!visible(el) || el.disabled) continue;
    const tag = el.tagName.toLowerCase(), name = label(el), candidates = [];
    const tid = el.getAttribute('data-testid'), id = el.id, nm = el.getAttribute('name'),
          aria = el.getAttribute('aria-label'), href = tag === 'a' ? el.getAttribute('href') : null,
          ph = el.getAttribute('placeholder');
    if (tid) candidates.push(`[data-testid="${q(tid)}"]`);
    if (id && /^[A-Za-z][\w-]*$/.test(id)) candidates.push('#' + esc(id));
    if (nm) candidates.push(`${tag}[name="${q(nm)}"]`);
    if (aria) candidates.push(`${tag}[aria-label="${q(aria)}"]`);
    if (ph) candidates.push(`${tag}[placeholder="${q(ph)}"]`);
    if (href && !href.startsWith('javascript:')) candidates.push(`a[href="${q(href)}"]`);
    const css = candidates.filter(unique);
    const structural = path(el);
    const primary = css[0] || structural;
    const fallbacks = [...css.slice(1)];
    if (name && name.length <= 60) fallbacks.push(`${tag}:has-text("${q(name)}")`);
    if (primary !== structural) fallbacks.push(structural);
    out.push({
      role: roleOf(el), tag, label: name, primary, fallbacks,
      href: href, input_type: tag === 'input' ? (el.getAttribute('type') || 'text').toLowerCase() : null,
      options: tag === 'select' ? Array.from(el.options).slice(0, 12).map((o) => o.text.trim()) : null,
    });
  }
  const text = (document.body ? document.body.innerText : '').replace(/\s+/g, ' ').trim();
  return { url: location.href, title: document.title, text, elements: out };
}
"""


@dataclass
class PageElement:
    index: int
    role: str
    tag: str
    label: str
    primary: str
    fallbacks: list[str] = field(default_factory=list)
    href: str | None = None
    input_type: str | None = None
    options: list[str] | None = None

    def line(self) -> str:
        """The element as the model sees it: ``[3] link "Patient portal" → /patient/``."""
        parts = [f"[{self.index}] {self.role}", f'"{self.label}"' if self.label else "(no label)"]
        if self.input_type and self.input_type not in ("text", "submit", "button"):
            parts.append(f"(type={self.input_type})")
        if self.href:
            parts.append(f"→ {self.href[:80]}")
        if self.options:
            parts.append("options: " + ", ".join(self.options))
        return " ".join(parts)


@dataclass
class PageView:
    url: str
    title: str
    text: str
    elements: list[PageElement]

    def element(self, index: Any) -> PageElement | None:
        try:
            return self.elements[int(index) - 1]
        except (TypeError, ValueError, IndexError):
            return None

    def describe(self) -> str:
        text = self.text[:MAX_PAGE_TEXT] + ("…" if len(self.text) > MAX_PAGE_TEXT else "")
        lines = [f"URL: {self.url}", f"Title: {self.title}", f"Visible text: {text}", "Elements you can act on:"]
        lines += [e.line() for e in self.elements] or ["(none)"]
        return "\n".join(lines)


async def read_page(page: Any, max_elements: int = MAX_ELEMENTS) -> PageView:
    """The page as the explorer sees it (*page* is a Playwright page)."""
    raw = await page.evaluate(_READ_PAGE_JS, max_elements)
    elements = [PageElement(index=i, **e) for i, e in enumerate(raw["elements"], start=1)]
    return PageView(url=raw["url"], title=raw["title"], text=raw["text"], elements=elements)
