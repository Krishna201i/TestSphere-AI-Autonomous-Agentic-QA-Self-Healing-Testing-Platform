/**
 * Design-system lint: sizes, spacing, radii and colours come from the tokens
 * in theme.css, and components do not carry one-off inline styles.
 */
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = join(__dirname, '..');
const CSS = readFileSync(join(SRC, 'styles', 'theme.css'), 'utf8');

function files(dir, ext) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = join(dir, e.name);
    if (e.isDirectory()) return e.name === '__tests__' ? [] : files(p, ext);
    return p.endsWith(ext) ? [p] : [];
  });
}

const JSX = files(SRC, '.jsx').map((p) => [relative(SRC, p).replace(/\\/g, '/'), readFileSync(p, 'utf8')]);

/** CSS declarations outside the token blocks (:root, [data-theme]) and print styles. */
function componentDeclarations() {
  const out = [];
  const stack = [];
  let selector = '';
  CSS.replace(/\/\*[\s\S]*?\*\//g, '').split('\n').forEach((line, i) => {
    const text = line.trim();
    if (text.endsWith('{')) selector = text;
    for (const ch of text) {
      if (ch === '{') stack.push(selector);
      if (ch === '}') stack.pop();
    }
    const inTokens = stack.some((s) => s.startsWith(':root') || s.startsWith('@media print') || s.startsWith('@keyframes'));
    if (inTokens) return;
    for (const m of text.matchAll(/([a-z-]+)\s*:\s*([^;{}]+)/g)) out.push({ line: i + 1, prop: m[1], value: m[2].trim() });
  });
  return out;
}

/** "0 calc(-1 * var(--s-4))" → ["0", "calc(-1 * var(--s-4))"]: split on spaces outside parentheses. */
function words(value) {
  const out = [''];
  let depth = 0;
  for (const ch of value) {
    if (ch === '(') depth += 1;
    if (ch === ')') depth -= 1;
    if (ch === ' ' && depth === 0) out.push('');
    else out[out.length - 1] += ch;
  }
  return out.filter(Boolean);
}

const SCALE_OK = /^(var\(--[a-z0-9-]+\)|0|auto|inherit|50%|100%|calc\(.*var\(--.*\)|max\(.*cqw\)|[0-9.]+cqw|1px|2px|-?1px)$/;

describe('theme.css', () => {
  const decls = componentDeclarations();

  it('uses the type scale for every font size', () => {
    const bad = decls.filter((d) => d.prop === 'font-size' && !SCALE_OK.test(d.value));
    expect(bad.map((d) => `line ${d.line}: font-size: ${d.value}`)).toEqual([]);
  });

  it('uses radius tokens for every corner', () => {
    const bad = decls.filter((d) => d.prop === 'border-radius' && !SCALE_OK.test(d.value));
    expect(bad.map((d) => `line ${d.line}: border-radius: ${d.value}`)).toEqual([]);
  });

  it('uses the spacing scale for padding, margin and gap', () => {
    const spacing = /^(padding|margin|gap|row-gap|column-gap)(-(top|right|bottom|left))?$/;
    const bad = decls.filter((d) => spacing.test(d.prop) && !words(d.value).every((v) => SCALE_OK.test(v)));
    expect(bad.map((d) => `line ${d.line}: ${d.prop}: ${d.value}`)).toEqual([]);
  });

  it('keeps every colour in the token blocks', () => {
    const bad = decls.filter((d) => /#[0-9a-f]{3,8}\b/i.test(d.value));
    expect(bad.map((d) => `line ${d.line}: ${d.prop}: ${d.value}`)).toEqual([]);
  });

  it('defines the dark theme for every colour token', () => {
    const light = CSS.slice(CSS.indexOf(':root {'), CSS.indexOf('/* Dark theme'));
    const dark = CSS.slice(CSS.indexOf(':root[data-theme="dark"]'), CSS.indexOf('/* ── Base'));
    const colours = [...light.matchAll(/(--[a-z0-9-]+):\s*(#|rgba)/g)].map((m) => m[1]);
    const missing = colours.filter((t) => !dark.includes(`${t}:`) && !['--chart-1', '--chart-2', '--chart-3', '--chart-4', '--chart-5', '--chart-6', '--chart-7'].includes(t));
    expect(missing).toEqual([]);
  });
});

describe('components', () => {
  // Brand artwork (the logo, Google's mark) keeps its own colours
  const BRAND_ART = /(fill|stopColor)="#[0-9a-fA-F]{3,8}"/;

  it('have no inline styles made only of fixed values', () => {
    const literal = /^\s*(['"][^'"]*['"]|-?\d+(\.\d+)?)\s*$/;
    const bad = [];
    for (const [name, text] of JSX) {
      for (const m of text.matchAll(/style=\{\{([^}]*)\}\}/g)) {
        const values = m[1].split(',').map((kv) => kv.split(':').slice(1).join(':')).filter((v) => v.trim());
        if (values.length && values.every((v) => literal.test(v))) bad.push(`${name}: style={{${m[1]}}}`);
      }
    }
    expect(bad).toEqual([]);
  });

  it('take colours from tokens, not hex codes', () => {
    const bad = [];
    for (const [name, text] of JSX) {
      text.split('\n').forEach((line, i) => {
        if (/#[0-9a-fA-F]{3,8}\b/.test(line.replace(/href="#[^"]*"|`#\$\{|'#\/|"#\//g, '')) && !BRAND_ART.test(line) && !/#\{|#\d+\b|`#|'#|>#/.test(line)) {
          bad.push(`${name}:${i + 1}: ${line.trim()}`);
        }
      });
    }
    expect(bad).toEqual([]);
  });

  it('only reference CSS variables that theme.css defines', () => {
    const defined = new Set([...CSS.matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1]));
    const bad = [];
    for (const [name, text] of JSX) {
      for (const m of text.matchAll(/var\((--[a-z0-9-]+)\)/g)) if (!defined.has(m[1])) bad.push(`${name}: ${m[1]}`);
    }
    expect(bad).toEqual([]);
  });

  it('use classes that theme.css defines', () => {
    const defined = new Set([...CSS.matchAll(/\.([a-zA-Z][\w-]*)/g)].map((m) => m[1]));
    const bad = new Set();
    for (const [name, text] of JSX) {
      for (const m of text.matchAll(/className="([^"]+)"/g)) {
        m[1].split(/\s+/).filter((c) => c && !defined.has(c)).forEach((c) => bad.add(`${name}: ${c}`));
      }
    }
    expect([...bad]).toEqual([]);
  });
});
