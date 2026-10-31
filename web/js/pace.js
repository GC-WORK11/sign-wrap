// pace.js — how often Go Live and Teach run the hand model.
//
// Detection runs on each new camera frame, at most 30 times a second. When
// the model is slow on this device (CPU only, no GPU), each run is followed
// by a pause of a quarter of its own time, so the page keeps about 20% of
// its time for drawing and taps. The old pause (1.5x the detect time, i.e.
// detection at 40% duty) halved the rate on slow laptops, and a held sign
// needs a few frames to be caught, so it was caught much later there.
export const MIN_KP_MS = 33;      // at most ~30 detections a second
export const DUTY = 0.8;          // share of the page's time detection may use

/** ms to wait between the starts of two detections, given the average
 *  time one detection takes (0 when not measured yet). */
export function detectGap(detMs) {
  const d = Number.isFinite(detMs) && detMs > 0 ? detMs : 0;
  return Math.max(MIN_KP_MS, d / DUTY);
}
