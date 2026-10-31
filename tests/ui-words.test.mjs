// ui-words.test.mjs — the words the app shows on screen.
//
// Regression for QA-5: Go Live cards carried explanatory paragraphs ("Your
// browser is asking to use it...", "Loading the hand model onto this
// device..."), Teach said "older wrap" / "update wrap" (the CLI name), and a
// hidden line read "gloss HELLO" to screen readers. Founder rules: no helper
// text, and no developer words on screen.
//
// Checks the string literals passed to the UI in web/js:
//   card(title, message, ...)  -> the message is empty
//   card / toast / actFlash / mkBtn / .textContent / .innerHTML / errors
//                              -> no developer words
// Run: node --test tests/ui-words.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const WEB = join(dirname(fileURLToPath(import.meta.url)), '..', 'web', 'js');
const BANNED = /\b(gloss|daemon|python|dtw|wfd|keypoints?|kp42|confidence|wrap|engine|landmarks?)\b/i;
const STR = String.raw`'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*"|` + '`(?:\\\\.|[^`\\\\])*`';
const lit = s => s.slice(1, -1);
// what a person reads: template code, tags and commands to type are not prose
const shown = t => t.replace(/\$\{[^}]*\}/g, ' ').replace(/<code>[\s\S]*?<\/code>/g, ' ').replace(/<[^>]*>/g, ' ');

function uiStrings(src) {
  const out = [], seen = new Set();
  const take = (re, kind) => {
    for (const m of src.matchAll(re)) {
      const at = src.slice(0, m.index).split('\n').length, text = lit(m[1]);
      if (seen.has(at + text)) continue;
      seen.add(at + text);
      out.push({ kind, text, at });
    }
  };
  take(new RegExp(String.raw`\b(?:card|toast|App\.toast|actFlash|mkBtn)\(\s*(${STR})`, 'g'), 'call');
  take(new RegExp(String.raw`\.(?:textContent|innerHTML)\s*=\s*(?:[^;\n]*?\?\s*)?(${STR})`, 'g'), 'text');
  take(new RegExp(String.raw`\.(?:textContent|innerHTML)\s*=[^;\n]*?:\s*(${STR})`, 'g'), 'text');
  take(new RegExp(String.raw`recErr\.textContent\s*=[\s\S]*?(${STR})`, 'g'), 'text');
  return out;
}

const files = readdirSync(WEB).filter(f => f.endsWith('.js'));

test('Go Live cards carry no explanatory paragraph', () => {
  const src = readFileSync(join(WEB, 'live.js'), 'utf8');
  const bad = [];
  for (const m of src.matchAll(new RegExp(String.raw`\bcard\(\s*(${STR})\s*,\s*(${STR})`, 'g'))) {
    if (lit(m[2]).trim()) bad.push(lit(m[1]) + ' / ' + lit(m[2]));
  }
  assert.deepEqual(bad, []);
});

for (const f of files) {
  test(`${f}: no developer words in what the screen shows`, () => {
    const src = readFileSync(join(WEB, f), 'utf8');
    const bad = uiStrings(src).filter(s => BANNED.test(shown(s.text)))
      .map(s => `${f}:${s.at} "${s.text}"`);
    assert.deepEqual(bad, []);
  });
}

test('the checker catches the QA-5 strings', () => {
  const old = `recErr.textContent = 'This laptop runs an older wrap — update it and try again.';
    glossPre.innerHTML = g ? 'gloss&nbsp; <b>' + g + '</b>' : '';`;
  assert.equal(uiStrings(old).filter(s => BANNED.test(shown(s.text))).length, 2);
});

test('Teach bind step has no secondary label under the action (QA-9)', () => {
  const src = readFileSync(join(WEB, 'teach.js'), 'utf8');
  for (const s of ['runs instantly', 'asks for a yes on your laptop', 'confirm on laptop'])
    assert.ok(!src.includes(s), `teach.js still shows "${s}"`);
});

test('no old product names in shipped files (QA-15)', () => {
  const root = join(WEB, '..', '..');
  const files = ['server/wfd.py', 'server/wrap_cli.py', 'bin/wrap', 'package.json', 'LICENSE', 'README.md']
    .concat(readdirSync(join(root, 'web', 'js')).map(f => 'web/js/' + f));
  const bad = files.filter(f => /flow composer|wispr.?wrap/i.test(readFileSync(join(root, f), 'utf8')));
  assert.deepEqual(bad, []);
});
