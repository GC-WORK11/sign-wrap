#!/usr/bin/env python3
"""Regression tests for "signs don't fire, or aren't caught immediately".

On landmarks extracted (with the app's own hand model) from real phone
footage of a hand, the old pipeline never fired at all:

  * PALM-OPEN never fired: landmark jitter kept a segment "active" all the
    time, and the palm could only fire while idle; real palms also read
    openness 1.5-1.6, right at the 1.55 cut;
  * segments ran to the 3 s cap (or 1-2 s holds) and mixed several shapes,
    because jitter kept the motion energy above the exit threshold;
  * a taught still sign was matched on the trajectory of the hand moving
    into it, which is different every time.

These tests use a synthetic hand with real proportions and real-sized
landmark jitter (no recorded data ships in the repo).

Run: python3 -m unittest tests.test_settle -v   (from server/)
"""
import math
import os
import random
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import endpointer  # noqa: E402
import handshape  # noqa: E402
import signbank  # noqa: E402

FPS = 12
DT = 1000.0 / FPS

# hand-local layout, wrist at (0, 0), +y towards the fingers, palm length 1
MCP = {5: (0.30, 0.95), 9: (0.05, 1.00), 13: (-0.17, 0.95), 17: (-0.36, 0.84)}
SEG = {5: (0.38, 0.24, 0.21), 9: (0.43, 0.28, 0.23),
       13: (0.39, 0.24, 0.20), 17: (0.29, 0.18, 0.16)}
DIR = {5: 0.12, 9: 0.02, 13: -0.10, 17: -0.30}       # finger fan (x per y)
SHAPES = {                                            # index, middle, ring, pinky
    "open": (1, 1, 1, 1), "v": (1, 1, 0, 0), "point": (1, 0, 0, 0),
    "fist": (0, 0, 0, 0), "three": (1, 1, 1, 0),
}


def local(shape):
    """21 hand-local points for a shape name."""
    fing = SHAPES[shape]
    P = [(0.0, 0.0)] * 21
    thumb_out = shape == "open"
    P[1] = (0.25, 0.15)
    if thumb_out:
        P[2], P[3], P[4] = (0.45, 0.35), (0.60, 0.55), (0.72, 0.72)
    else:
        P[2], P[3], P[4] = (0.38, 0.40), (0.25, 0.62), (0.08, 0.72)
    for k, (m, straight) in enumerate(zip((5, 9, 13, 17), fing)):
        mx, my = MCP[m]
        dx = DIR[m]
        n = math.hypot(dx, 1.0)
        ux, uy = dx / n, 1.0 / n
        l1, l2, l3 = SEG[m]
        P[m] = (mx, my)
        if straight:
            P[m + 1] = (mx + ux * l1, my + uy * l1)
            P[m + 2] = (mx + ux * (l1 + l2), my + uy * (l1 + l2))
            P[m + 3] = (mx + ux * (l1 + l2 + l3), my + uy * (l1 + l2 + l3))
        else:   # folded towards the camera: tip comes back down over the palm
            P[m + 1] = (mx + ux * 0.55 * l1 / 0.38, my + 0.55)
            P[m + 2] = (P[m + 1][0], P[m + 1][1] - 0.25)
            P[m + 3] = (P[m + 1][0], P[m + 1][1] - 0.45)
    return P


def place(P, cx, cy, size, rot=0.0):
    c, s = math.cos(rot), math.sin(rot)
    return [(cx + (x * c - y * s) * size, cy - (x * s + y * c) * size) for x, y in P]


class Hand:
    """A stream of kp42 frames from one synthetic right hand."""

    def __init__(self, seed=1, jitter=0.012, size=0.12):
        self.rng = random.Random(seed)
        self.t = 0.0
        self.jitter = jitter
        self.size = size
        self.frames = []
        self.cx, self.cy = 0.5, 0.62
        self.shape = "open"

    def _pts(self, P):
        j = self.jitter * self.size
        out = [{"x": 0.0, "y": 0.0, "score": 0.0} for _ in range(21)]
        for i, (x, y) in enumerate(P):
            # half-hidden curled fingertips jitter far more on real cameras
            jj = j * (3.0 if i in (7, 8, 11, 12, 15, 16, 19, 20) and
                      self._curled(i) else 1.0)
            out.append({"x": x + self.rng.gauss(0, jj),
                        "y": y + self.rng.gauss(0, jj), "score": 1.0})
        return out

    def _curled(self, i):
        f = {7: 0, 8: 0, 11: 1, 12: 1, 15: 2, 16: 2, 19: 3, 20: 3}[i]
        return not SHAPES[self.shape][f]

    def emit(self, P):
        self.t += DT
        fr = {"t_ms": int(self.t), "points": self._pts(P) if P else
              [{"x": 0.0, "y": 0.0, "score": 0.0} for _ in range(42)]}
        self.frames.append(fr)
        return fr

    def absent(self, s):
        return [self.emit(None) for _ in range(int(round(s * FPS)))]

    def hold(self, shape, s, drift=0.0):
        self.shape = shape
        out = []
        for k in range(int(round(s * FPS))):
            self.cx += drift * self.size / FPS
            out.append(self.emit(place(local(shape), self.cx, self.cy,
                                       self.size)))
        return out

    def enter(self, shape, s=0.35):
        """Rise into view from below the picture while forming the shape."""
        out = []
        n = int(round(s * FPS))
        y0, y1 = 1.05, self.cy
        for k in range(n):
            u = (k + 1) / n
            self.shape = shape
            out.append(self.emit(place(local(shape), self.cx,
                                       y0 + (y1 - y0) * (1 - (1 - u) ** 2),
                                       self.size)))
        return out

    def morph(self, shape, s=0.25):
        """Change shape in place (fingers move together)."""
        A, B = local(self.shape), local(shape)
        out = []
        n = int(round(s * FPS))
        for k in range(n):
            u = (k + 1) / n
            P = [(a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)
                 for a, b in zip(A, B)]
            out.append(self.emit(place(P, self.cx, self.cy, self.size)))
        self.shape = shape
        return out

    def move(self, dx, s):
        out = []
        n = int(round(s * FPS))
        for k in range(n):
            self.cx += dx * self.size / n
            out.append(self.emit(place(local(self.shape), self.cx, self.cy,
                                       self.size)))
        return out

    def drop(self, s=0.3):
        out = []
        n = int(round(s * FPS))
        for k in range(n):
            self.cy += 0.12
            P = place(local(self.shape), self.cx, self.cy, self.size)
            out.append(self.emit(P if self.cy < 1.1 else None))
        self.cy = 0.62
        return out


def run(frames, ep=None):
    ep = ep or endpointer.Endpointer()
    evs = []
    for fr in frames:
        for e in ep.feed(fr):
            e = dict(e)
            e["at"] = fr["t_ms"]
            evs.append(e)
    return evs


def signs(evs):
    return [e for e in evs if e["type"] == "segment"]


def pattern(e):
    d = handshape.descriptor([f for f in e["frames"] if f.get("hold")])
    ext = d["ext"][d["slots"][0]]
    return tuple(int(x >= handshape.EXT_ON) for x in ext)


class SyntheticHandIsRealistic(unittest.TestCase):
    def test_finger_extension_reads_like_real_landmarks(self):
        h = Hand(jitter=0.0)
        fr = h.hold("v", 0.1)[-1]
        pts = handshape.hands_of(fr)[1]
        e = handshape.extension(pts)
        self.assertGreater(e[0], 1.2)
        self.assertGreater(e[1], 1.2)
        self.assertLess(e[2], 0.9)
        self.assertLess(e[3], 0.9)


class Settle(unittest.TestCase):
    def test_held_sign_is_caught_within_a_quarter_second(self):
        h = Hand()
        h.absent(0.5)
        h.enter("v")
        t_shape = h.t                       # the hand is in its shape now
        h.hold("v", 1.0)
        h.drop()
        h.absent(0.5)
        s = signs(run(h.frames))
        self.assertEqual(len(s), 1, [(e["how"], e["at"]) for e in s])
        self.assertEqual(s[0]["how"], "settle")
        self.assertEqual(pattern(s[0]), (1, 1, 0, 0))
        self.assertLessEqual(s[0]["at"] - t_shape, 260)
        self.assertGreaterEqual(s[0]["hold_n"], 3)

    def test_slow_hand_model_still_catches_a_held_sign_quickly(self):
        # a CPU-only laptop runs the hand model at about 4 frames a second;
        # waiting for 3 held frames there meant 0.75 s before a sign counted
        h = Hand()
        h.absent(0.6)
        h.hold("v", 1.5)                    # the hand appears already in its shape
        h.absent(0.6)
        slow = h.frames[::3]                # 250 ms between frames
        t1 = next(f["t_ms"] for f in slow if f["points"][21]["score"] > 0)
        s = signs(run(slow))
        self.assertEqual(len(s), 1, [(e["how"], e["at"]) for e in s])
        self.assertEqual(pattern(s[0]), (1, 1, 0, 0))
        self.assertLessEqual(s[0]["at"] - t1, 300)   # its 2nd frame, not its 3rd

    def test_long_hold_with_jitter_never_makes_a_3s_segment(self):
        h = Hand(jitter=0.03)
        h.absent(0.3)
        h.enter("point")
        h.hold("point", 4.0, drift=0.1)
        s = signs(run(h.frames))
        self.assertEqual(len(s), 1)
        self.assertNotEqual(s[0]["how"], "maxlen")
        self.assertLess(s[0]["dur_s"], 1.5)

    def test_each_shape_in_a_sequence_counts_once(self):
        h = Hand()
        h.absent(0.3)
        h.enter("point")
        for shape in ("point", "fist", "point", "v", "fist"):
            if shape != h.shape:
                h.morph(shape)
            h.hold(shape, 0.6)
        got = [pattern(e) for e in signs(run(h.frames))]
        self.assertEqual(got, [(1, 0, 0, 0), (0, 0, 0, 0), (1, 0, 0, 0),
                               (1, 1, 0, 0), (0, 0, 0, 0)])

    def test_jittery_fist_is_one_sign(self):
        h = Hand(jitter=0.03, seed=5)
        h.absent(0.3)
        h.enter("fist")
        h.hold("fist", 2.0)
        self.assertEqual(len(signs(run(h.frames))), 1)

    def test_dropping_the_hand_after_a_sign_is_not_another_sign(self):
        h = Hand()
        h.absent(0.3)
        for _ in range(3):
            h.enter("v")
            h.hold("v", 0.8)
            h.drop()
            h.absent(0.6)
        s = signs(run(h.frames))
        self.assertEqual([e["how"] for e in s], ["settle"] * 3)

    def test_hand_resting_in_view_at_start_is_not_a_sign(self):
        h = Hand()
        h.hold("v", 1.0)
        self.assertEqual(signs(run(h.frames)), [])

    def test_open_hand_swipe_is_a_moving_sign_not_a_palm(self):
        h = Hand()
        h.absent(0.3)
        h.enter("open")
        h.move(3.0, 0.5)
        h.hold("open", 0.4)
        s = signs(run(h.frames))
        self.assertEqual(len(s), 1)
        self.assertTrue(s[0]["motion"])


class Palm(unittest.TestCase):
    def palms(self, evs):
        return [e for e in evs if e["type"] == "mode" and
                e["name"] == "PALM-OPEN"]

    def test_jittery_open_palm_starts_listening(self):
        # the old endpointer only fired while idle; jitter kept it active
        h = Hand(jitter=0.04)
        h.absent(0.3)
        h.enter("open")
        t0 = h.t
        h.hold("open", 1.0, drift=0.2)
        evs = run(h.frames)
        p = self.palms(evs)
        self.assertEqual(len(p), 1)
        self.assertLessEqual(p[0]["at"] - t0, 700)
        self.assertEqual(signs(evs), [])      # the palm is never a sign

    def test_four_straight_fingers_count_below_the_old_openness_cut(self):
        h = Hand(jitter=0.0)
        fr = h.hold("open", 0.1)[-1]
        hand = endpointer.Endpointer()._hands(fr)[1]
        hand.pattern = (True, True, True, True)
        ep = endpointer.Endpointer()
        hand.openness = 1.45                  # real palms read 1.5-1.6
        self.assertTrue(ep._is_open(hand))


def take(h, shape, enter=True):
    if enter:
        h.absent(0.4)
        h.enter(shape)
    elif shape != h.shape:
        h.morph(shape)
    h.hold(shape, 0.8)
    if enter:
        h.drop()


class HeldShapeMatching(unittest.TestCase):
    def bank(self):
        b = signbank.SignBank()
        for gloss, shape in (("V", "v"), ("POINT", "point"), ("FIST", "fist")):
            for seed in (1, 2, 3):
                h = Hand(seed=seed)
                take(h, shape)              # taught by raising the hand in
                s = signs(run(h.frames))
                self.assertEqual(len(s), 1)
                self.assertTrue(b.add_exemplar(gloss, s[0]["frames"]))
        return b

    def test_taught_signs_are_held_shapes(self):
        b = self.bank()
        self.assertTrue(all(b.is_static(t) for t in b.templates))

    def test_sign_formed_in_place_matches_sign_taught_by_raising(self):
        b = self.bank()
        h = Hand(seed=9, jitter=0.02)
        h.absent(0.3)
        h.enter("fist")
        h.hold("fist", 0.6)
        h.morph("v")
        h.hold("v", 0.6)
        h.morph("point")
        h.hold("point", 0.6)
        got = [b.match(e["frames"]) for e in signs(run(h.frames))]
        self.assertEqual([m.gloss for m in got if m.accepted],
                         ["FIST", "V", "POINT"])

    def test_untaught_shape_is_refused(self):
        b = self.bank()
        h = Hand(seed=4)
        take(h, "three")
        m = b.match(signs(run(h.frames))[0]["frames"])
        self.assertFalse(m.accepted, m)

    def test_look_alike_signs_refuse_instead_of_guessing(self):
        b = signbank.SignBank()
        for gloss in ("A", "B"):            # two signs, same shape
            for seed in (1, 2):
                h = Hand(seed=seed)
                take(h, "v")
                b.add_exemplar(gloss, signs(run(h.frames))[0]["frames"])
        h = Hand(seed=7)
        take(h, "v")
        m = b.match(signs(run(h.frames))[0]["frames"])
        self.assertFalse(m.accepted)
        self.assertEqual(m.reason, "margin")

    def test_bank_file_keeps_held_shapes(self):
        b = self.bank()
        with tempfile.TemporaryDirectory() as d:
            p = b.save(os.path.join(d, "bank.json"))
            b2 = signbank.SignBank.load(p)
        h = Hand(seed=11)
        take(h, "point")
        m = b2.match(signs(run(h.frames))[0]["frames"])
        self.assertTrue(m.accepted)
        self.assertEqual(m.gloss, "POINT")


class DaemonPipeline(unittest.TestCase):
    """Teach 3 takes through wfd.live_kp, then Go Live: palm, then the sign."""

    @classmethod
    def setUpClass(cls):
        import wfd
        cls.wfd = wfd

    def setUp(self):
        w = self.wfd
        self.tmp = tempfile.mkdtemp(prefix="wf-settle-")
        self._saved = (w.BANK, w.BANK_FILE, w.OPS, w._rate_limited)
        # frames arrive faster than real time here; the limiter has its
        # own tests (test_live_session)
        w._rate_limited = lambda key, now: False
        w.BANK = signbank.SignBank()
        w.BANK_FILE = os.path.join(self.tmp, "signbank.json")
        w.OPS = None
        w.live_reset()
        w.LIVE.update(observe=True, text_mode=False, listening=False)
        w.TEACH.update(active=False, name="", takes=0, got=0, label="",
                       action=None, session=None, frames=[], holds=[],
                       added=0, reject=None, reject_frames=None)
        self.seq = 0

    def tearDown(self):
        w = self.wfd
        w.BANK, w.BANK_FILE, w.OPS, w._rate_limited = self._saved
        w.live_reset()
        w.LIVE.update(observe=False, listening=False)
        w.TEACH.update(active=False, name="", got=0, session=None)

    def feed(self, frames, session="S"):
        outs = []
        for fr in frames:
            pts = fr["points"]
            # send the hand in the LEFT slot: the camera's label must not matter
            left = pts[21:] + pts[:21]
            body = {"t_ms": fr["t_ms"], "points": left}
            if session:
                body["session"] = session
            code, out = self.wfd.live_kp(body)
            self.assertEqual(code, 200, out)
            outs.append(out)
        return outs

    def test_teach_three_takes_then_sign_fires(self):
        w = self.wfd
        code, _ = w.teach_begin({"name": "V", "takes": 3, "session": "S"})
        self.assertEqual(code, 200)
        h = Hand(seed=3)
        for _ in range(3):
            take(h, "v")
        outs = self.feed(h.frames)
        got = [o["teach"]["got"] for o in outs if o.get("teach")]
        self.assertEqual(got, [1, 2, 3])
        self.assertFalse(w.TEACH["active"])
        code, end = w.teach_end({})
        # Go Live: open palm, then the sign
        g = Hand(seed=8, jitter=0.02)
        g.t = h.t
        g.absent(0.5)
        g.enter("open")
        g.hold("open", 0.8)
        outs = self.feed(g.frames)
        self.assertTrue(any(o.get("mode") == "PALM-OPEN" for o in outs))
        self.assertTrue(w.LIVE["listening"])
        n0 = len(g.frames)
        g.morph("v")
        t_shape = g.t
        g.hold("v", 0.8)
        outs = self.feed(g.frames[n0:])
        hits = [(o["match"], fr) for o, fr in zip(outs, g.frames[n0:])
                if o.get("match") and o["match"].get("accepted")]
        self.assertEqual(len(hits), 1, [o.get("match") for o in outs])
        m, fr = hits[0]
        self.assertEqual(m["gloss"], "V")
        self.assertLessEqual(fr["t_ms"] - t_shape, 260)

    def test_go_live_leftover_movement_is_not_a_teach_take(self):
        # QA-7: Go Live closed with a movement still open; the first Teach
        # frame used to close it as take 1 ("too short" on screen at once)
        w = self.wfd
        h = Hand(seed=6)
        h.absent(0.3)
        h.enter("open")
        h.move(4.0, 0.6)                    # still moving when Go Live closes
        self.feed(h.frames)
        self.assertTrue(w.LIVE["ep"].active)
        w.teach_begin({"name": "V", "takes": 3, "session": "S"})
        n0 = len(h.frames)
        h.t += 4000                         # Record tapped a few seconds later
        h.absent(0.3)
        outs = self.feed(h.frames[n0:])
        self.assertEqual([o["teach"] for o in outs if o.get("teach")], [])
        self.assertEqual(w.TEACH["got"], 0)

    # -- QA-8: the action fires with the decision, no /live/state poll --
    def _ops(self, window_ms=1200):
        import signflow_ops
        fired = []
        ops = signflow_ops.SignFlowOps(
            self.wfd.BANK, event_sink=lambda e: None, window_ms=window_ms,
            action_router=lambda a, c: (fired.append(time.time()), {"ok": True})[1],
            compositions_path=os.path.join(self.tmp, "compositions.json"))
        self.wfd.OPS = ops
        self.wfd.LIVE.update(observe=False, text_mode=False)
        return ops, fired

    def _teach_v_and_listen(self):
        w = self.wfd
        w.teach_begin({"name": "V", "takes": 3, "session": "S"})
        h = Hand(seed=3)
        for _ in range(3):
            take(h, "v")
        self.feed(h.frames)
        w.teach_end({})
        w.BANK.set_action("V", action={"kind": "builtin", "tool": "type.text",
                                       "args": {"text": "hello"}})
        g = Hand(seed=8, jitter=0.02)
        g.t = h.t
        g.absent(0.5)
        g.enter("open")
        g.hold("open", 0.8)
        self.feed(g.frames)
        self.assertTrue(w.LIVE["listening"])
        n0 = len(g.frames)
        g.morph("v")
        g.hold("v", 0.8)
        return g.frames[n0:]

    def test_sign_action_fires_without_a_state_poll(self):
        ops, fired = self._ops()
        for fr in self._teach_v_and_listen():
            out = self.feed([fr])[0]
            if (out.get("match") or {}).get("accepted"):
                self.assertEqual(len(fired), 1, "action not dispatched with the decision")
                return
        self.fail("V was never decided")

    def test_held_prefix_waits_for_its_window_on_the_laptop_clock(self):
        ops, fired = self._ops(window_ms=400)
        ops.set_composition("V FIST", {"kind": "builtin", "tool": "key.press",
                                       "args": {"keys": "Return"}})
        outs = self.feed(self._teach_v_and_listen())
        self.assertTrue(any((o.get("match") or {}).get("accepted") for o in outs))
        self.assertEqual(fired, [])         # held: V may start "V FIST"
        self.wfd.live_state()               # a poll must not cut the window short
        self.assertEqual(fired, [])
        time.sleep(0.5)
        self.wfd.live_state()
        self.assertEqual(len(fired), 1)     # after the window: V alone fires

    # -- QA-11: a new sign with the shape of a taught one --
    def _teach(self, name, shape, seed, **kw):
        w = self.wfd
        w.teach_begin(dict({"name": name, "takes": 3, "session": "S"}, **kw))
        h = Hand(seed=seed)
        for _ in range(3):
            take(h, shape)
        outs = self.feed(h.frames)
        w.teach_end({})
        return [o["teach"] for o in outs if o.get("teach")]

    def test_new_sign_with_the_shape_of_a_taught_one_says_so(self):
        w = self.wfd
        self._teach("HELLO", "v", 3, label="Hello")
        t = self._teach("SWITCH-APP", "v", 5)
        self.assertEqual(t[0].get("reason"), "like")
        self.assertEqual(t[0].get("like"), "Hello")
        self.assertIsNone(w.BANK._find("SWITCH-APP"))   # nothing stored
        # HELLO still fires
        g = Hand(seed=9)
        take(g, "v")
        m = w.BANK.match(signs(run(g.frames))[0]["frames"])
        self.assertTrue(m.accepted)
        self.assertEqual(m.gloss, "HELLO")

    def test_a_different_shape_is_taught_as_usual(self):
        self._teach("HELLO", "v", 3, label="Hello")
        t = self._teach("FIST", "fist", 5)
        self.assertEqual([x["got"] for x in t], [1, 2, 3])
        self.assertNotIn("like", t[0])

    def test_use_it_anyway_keeps_the_takes(self):
        w = self.wfd
        self._teach("HELLO", "v", 3, label="Hello")
        t = self._teach("SWITCH-APP", "v", 5, allow_like=True)
        self.assertEqual([x["got"] for x in t], [1, 2, 3])
        self.assertIsNotNone(w.BANK._find("SWITCH-APP"))

    def test_adding_takes_to_the_same_sign_is_not_a_lookalike(self):
        self._teach("HELLO", "v", 3, label="Hello")
        t = self._teach("HELLO", "v", 5)
        self.assertEqual([x["got"] for x in t], [1, 2, 3])

    def test_teach_whose_page_is_gone_does_not_eat_go_live_signs(self):
        # QA-12: Teach stored 1 take, then its page died (no /teach/end).
        # A new Go Live stream (no session id) must match and fire, not add
        # takes to the old Teach.
        w = self.wfd
        w.teach_begin({"name": "HELLO", "takes": 3, "session": "S", "label": "Hello"})
        h = Hand(seed=3)
        take(h, "v")
        self.feed(h.frames)
        self.assertEqual(w.TEACH["got"], 1)
        # the page has been silent for a while: the daemon clock moves on
        real_time = w.time.time
        self.addCleanup(setattr, w.time, "time", real_time)
        w.time.time = lambda: real_time() + 10.0
        # one more take, as if HELLO had been taught fully on an earlier day
        w.BANK.add_exemplar("HELLO", self._v_frames(5), "Hello")
        g = Hand(seed=8, jitter=0.02)
        g.t = h.t + 5000
        g.absent(0.5)
        g.enter("open")
        g.hold("open", 0.8)
        n0 = len(g.frames)
        g.morph("v")
        g.hold("v", 0.8)
        outs = self.feed(g.frames, session=None)
        self.assertFalse(w.TEACH["active"])
        self.assertEqual([o["teach"] for o in outs if o.get("teach")], [])
        self.assertTrue(any((o.get("match") or {}).get("accepted") and
                            o["match"]["gloss"] == "HELLO" for o in outs))

    def _v_frames(self, seed):
        h = Hand(seed=seed)
        take(h, "v")
        return signs(run(h.frames))[0]["frames"]

    def test_a_teach_still_streaming_keeps_its_frames(self):
        # the owner is active: a stray session-less client must not end it
        w = self.wfd
        w.teach_begin({"name": "HELLO", "takes": 3, "session": "S"})
        h = Hand(seed=3)
        take(h, "v")
        self.feed(h.frames)
        code, _ = w.live_kp({"t_ms": h.t + 50, "points": h.frames[-1]["points"]})
        self.assertTrue(w.TEACH["active"])
        self.assertEqual(w.TEACH["got"], 1)

    def test_open_palm_during_teach_says_so(self):
        w = self.wfd
        w.teach_begin({"name": "V", "takes": 3, "session": "S"})
        h = Hand()
        h.absent(0.3)
        h.enter("open")
        h.hold("open", 1.0)
        outs = self.feed(h.frames)
        reasons = [o["teach"].get("reason") for o in outs if o.get("teach")]
        self.assertIn("palm", reasons)
        self.assertEqual(w.TEACH["got"], 0)

    def test_a_take_of_another_shape_is_refused(self):
        w = self.wfd
        w.teach_begin({"name": "V", "takes": 3, "session": "S"})
        h = Hand()
        take(h, "v")
        take(h, "fist")
        outs = self.feed(h.frames)
        t = [o["teach"] for o in outs if o.get("teach")]
        self.assertEqual(t[0]["got"], 1)
        self.assertFalse(t[1]["ok"])
        self.assertEqual(t[1].get("reason"), "different")

    def test_odd_first_take_is_replaced_when_the_next_two_agree(self):
        w = self.wfd
        w.teach_begin({"name": "V", "takes": 3, "session": "S"})
        h = Hand()
        take(h, "fist")                     # odd one out
        take(h, "v")
        take(h, "v")
        take(h, "v")
        self.feed(h.frames)
        self.assertFalse(w.TEACH["active"])     # 3 takes reached
        t = w.BANK._find("V")
        pats = []
        for s in t["samples"]:
            e = s["hold"]["ext"]
            e = e.get(1, e.get("1")) or e.get(0, e.get("0"))
            pats.append(tuple(int(x >= handshape.EXT_ON) for x in e))
        self.assertEqual(pats, [(1, 1, 0, 0)] * 3)


class CanonicalSlot(unittest.TestCase):
    def test_one_hand_always_lands_in_slot_1(self):
        import wfd
        h = Hand()
        pts = h.hold("v", 0.1)[-1]["points"]
        left = pts[21:] + pts[:21]
        out = wfd._canon_points(left)
        self.assertEqual(out[0]["score"], 0.0)
        self.assertEqual(out[21:], pts[21:])

    def test_same_hand_reported_twice_is_one_hand(self):
        import wfd
        h = Hand()
        pts = h.hold("v", 0.1)[-1]["points"]
        twice = pts[21:] + [dict(p, x=p["x"] + 0.002) for p in pts[21:]]
        out = wfd._canon_points(twice)
        self.assertEqual(sum(1 for p in out[:21] if p["score"] > 0), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
