// pace.test.mjs — detection pacing (web/js/pace.js).
// On a CPU-only laptop the hand model takes 100-300 ms per frame. The old
// pause (1.5x the detect time) ran detection at 40% duty, so a 200 ms model
// ran at 2 frames a second where it could run at 4; held signs were caught
// late. Run: node --test tests/pace.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { detectGap, MIN_KP_MS } from '../web/js/pace.js';

test('fast model: capped at about 30 detections a second', () => {
  assert.equal(detectGap(0), MIN_KP_MS);
  assert.equal(detectGap(12), MIN_KP_MS);
});

test('slow model: detection gets most of the time, not 40%', () => {
  const gap = detectGap(200);
  assert.ok(gap <= 260, `gap ${gap} ms for a 200 ms model`);
  assert.ok(gap > 200, 'the page keeps some time for drawing and taps');
});

test('bad input is treated as not measured yet', () => {
  assert.equal(detectGap(NaN), MIN_KP_MS);
  assert.equal(detectGap(-5), MIN_KP_MS);
});
