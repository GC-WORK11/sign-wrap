// tap-targets.test.mjs — the composer's buttons are at least 48 px
// (founder rule 23). Regression for QA-14: the Go Live / send button was
// 46x36 px. Run: node --test tests/tap-targets.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const CSS = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'web', 'css', 'compose.css'), 'utf8');

function size(selector) {
  const m = CSS.match(new RegExp('(^|\\n)' + selector.replace(/[.#]/g, '\\$&') + '\\s*\\{([^}]*)\\}'));
  assert.ok(m, selector + ' rule not found');
  const px = k => { const v = m[2].match(new RegExp('(?:^|[;\\s])' + k + ':\\s*(\\d+(?:\\.\\d+)?)px')); return v ? +v[1] : null; };
  return { w: px('width'), h: px('height') };
}

for (const sel of ['.act', '.plusbtn']) {
  test(`${sel} is at least 48x48 px`, () => {
    const { w, h } = size(sel);
    assert.ok(w >= 48 && h >= 48, `${sel} is ${w}x${h} px`);
  });
}
