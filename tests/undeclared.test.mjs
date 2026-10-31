// undeclared.test.mjs — every bare function call in web/js must resolve to
// something declared in that file (function, const/let/var, class, import,
// parameter) or to a browser global.
//
// Regression for QA-2: live.js called fmt(d) on every accepted sign, fmt was
// never defined, and the ReferenceError was swallowed by a promise .catch,
// so it went unnoticed and cut showMatch() short each time.
//
// Run: node --test tests/undeclared.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const WEB = join(dirname(fileURLToPath(import.meta.url)), '..', 'web', 'js');

const GLOBALS = new Set(`
  setTimeout clearTimeout setInterval clearInterval requestAnimationFrame
  cancelAnimationFrame requestIdleCallback cancelIdleCallback queueMicrotask
  fetch addEventListener removeEventListener dispatchEvent getComputedStyle
  matchMedia structuredClone createImageBitmap atob btoa alert confirm prompt
  encodeURIComponent decodeURIComponent encodeURI decodeURI escape unescape
  parseInt parseFloat isNaN isFinite String Number Boolean Array Object
  Symbol BigInt Date Error TypeError RangeError Promise Set Map WeakMap
  WeakSet Proxy Reflect RegExp URL URLSearchParams Blob File FormData
  Headers Request Response AbortController TextEncoder TextDecoder Image
  Audio AudioContext OfflineAudioContext Event CustomEvent KeyboardEvent
  MutationObserver ResizeObserver IntersectionObserver Intl Function
  import require super if for while switch catch return typeof void
  await function constructor async XMLHttpRequest Uint8Array Uint8ClampedArray
  Int8Array Uint16Array Int16Array Uint32Array Int32Array Float32Array
  Float64Array ArrayBuffer DataView WebAssembly
`.split(/\s+/).filter(Boolean));

function strip(src) {
  // one pass: drop comments, string and template text, and regex literals,
  // so the words inside them never count as calls or declarations
  let out = '', i = 0, prev = '';
  const n = src.length;
  const regexOk = () => /^$|[(,=:[!&|?{};+\-*%<>~^]$/.test(prev) || /\b(?:return|typeof|case|in|of|delete|void)$/.test(out.trimEnd());
  while (i < n) {
    const c = src[i], d = src[i + 1];
    if (c === '/' && d === '/') { while (i < n && src[i] !== '\n') i++; continue; }
    if (c === '/' && d === '*') { const e = src.indexOf('*/', i + 2); i = e < 0 ? n : e + 2; out += ' '; continue; }
    if (c === "'" || c === '"') {
      i++; while (i < n && src[i] !== c && src[i] !== '\n') { if (src[i] === '\\') i++; i++; }
      i++; out += c + c; prev = c; continue;
    }
    if (c === '`') {
      i++; let depth = 0;
      while (i < n) {
        if (src[i] === '\\') { i += 2; continue; }
        if (depth === 0 && src[i] === '`') break;
        if (src[i] === '$' && src[i + 1] === '{') { depth++; i += 2; continue; }
        if (depth && src[i] === '}') { depth--; i++; continue; }
        i++;
      }
      i++; out += '``'; prev = '`'; continue;
    }
    if (c === '/' && regexOk()) {
      i++; let cls = false;
      while (i < n && src[i] !== '\n') {
        if (src[i] === '\\') { i += 2; continue; }
        if (src[i] === '[') cls = true; else if (src[i] === ']') cls = false;
        else if (src[i] === '/' && !cls) break;
        i++;
      }
      i++; while (i < n && /[a-z]/i.test(src[i])) i++;
      out += '/r/'; prev = '/'; continue;
    }
    out += c;
    if (!/\s/.test(c)) prev = c;
    i++;
  }
  return out;
}

function declared(src) {
  const names = new Set();
  const add = s => s.split(',').forEach(p => {
    const n = p.replace(/=.*$/s, '').replace(/[{}[\]().\s]|\.\.\./g, ' ').trim().split(/\s+/);
    n.forEach(x => { if (/^[A-Za-z_$][\w$]*$/.test(x)) names.add(x); });
  });
  for (const m of src.matchAll(/\b(?:function\*?|class)\s+([A-Za-z_$][\w$]*)/g)) names.add(m[1]);
  for (const m of src.matchAll(/\b(?:const|let|var)\s+([^;=]+?)\s*(?:=|;|\bof\b|\bin\b)/g)) add(m[1]);
  for (const m of src.matchAll(/\bimport\s+([^'"]+?)\s+from\b/g)) add(m[1].replace(/[\w$]+\s+as\s+/g, ' '));
  for (const m of src.matchAll(/\bfunction\*?\s*[A-Za-z_$]*\s*\(([^)]*)\)/g)) add(m[1]);
  for (const m of src.matchAll(/\(([^()]*)\)\s*=>/g)) add(m[1]);
  for (const m of src.matchAll(/([A-Za-z_$][\w$]*)\s*=>/g)) names.add(m[1]);
  for (const m of src.matchAll(/\bcatch\s*\(\s*([A-Za-z_$][\w$]*)/g)) names.add(m[1]);
  // `let a = x, b = y` declares b too
  for (const m of src.matchAll(/\b(?:const|let|var)\s+[^;]*?,\s*([A-Za-z_$][\w$]*)\s*=/g)) names.add(m[1]);
  // object/class method shorthand: name(args) { ... }
  for (const m of src.matchAll(/(?:^|[,{;\n])\s*(?:async\s+|static\s+|get\s+|set\s+)?([A-Za-z_$][\w$]*)\s*\(([^)]*)\)\s*\{/g)) { names.add(m[1]); add(m[2]); }
  return names;
}

function calls(src) {
  const out = new Set();
  for (const m of src.matchAll(/(^|[^\w$.\]])([A-Za-z_$][\w$]*)\s*\(/g)) out.add(m[2]);
  return out;
}

const files = readdirSync(WEB).filter(f => f.endsWith('.js'));

for (const f of files) {
  test(`${f}: no call to an undeclared function`, () => {
    const src = strip(readFileSync(join(WEB, f), 'utf8'));
    const have = declared(src);
    const missing = [...calls(src)].filter(n => !have.has(n) && !GLOBALS.has(n));
    assert.deepEqual(missing, [], `${f} calls ${missing.join(', ')} but never declares it`);
  });
}

test('the checker catches the QA-2 case', () => {
  const src = strip("const d = 1; el.textContent = 'd=' + fmt(d);");
  const missing = [...calls(src)].filter(n => !declared(src).has(n) && !GLOBALS.has(n));
  assert.deepEqual(missing, ['fmt']);
});
