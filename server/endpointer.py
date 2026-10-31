#!/usr/bin/env python3
"""endpointer — decides when a sign happened in a kp42 hand-keypoint stream.

Pure stdlib. The browser runs the hand model and POSTs ~10-30 keypoint
frames a second; this turns that stream into sign events.

Wire format (same as signbank.py):
    frame = {"t_ms": int, "points": [{"x":..,"y":..,"score":..} x42]}
    points[0:21] = left hand, points[21:42] = right (MediaPipe order).
    A 21-point frame is one hand given by frame["hand"] ("left"|"right",
    default "right"). An absent hand is all score-0 (or zero-padded).

feed(frame) -> list of events:
    {"type": "segment", "how": "settle", "frames": [...], "hold_n": k, ...}
        THE SIGN EVENT. The hand settled into a shape: its finger layout
        and its position stayed put for `settle_s` (over at least
        `settle_n` frames). Emitted at once, so a held sign is caught
        about 0.2 s after the hand stops changing. frames = the movement
        that led into it (from `pre_roll` or the open segment) plus the
        k hold frames, which are copies marked {"hold": True}. A shape is
        emitted once; the hand must change shape (or leave view) before
        the same shape counts again, or travel at least `travel_min`
        palm lengths while holding it ("motion": True, a moving sign).
        An open palm or palms together never becomes a sign event: those
        are the listen / stop gestures below.
    {"type": "segment", "how": "quiet"|"absent"|"maxlen", "frames": [...]}
        a movement that never settled (the hand left view, the motion
        died away, or `max_seg_s` force-closed it). Too-short motion is
        dropped as {"type": "segment-drop", "reason": "short"}. The hand
        dropping out of view right after a settled sign is the end of that
        sign, not a new one, and is skipped silently.
    {"type": "mode", "name": <palm_sign|namaste_sign>}
        MODE EVENTS, not signs: a held open palm and held palms-together
        (namaste). The daemon maps them to listen start/stop. Names are
        configurable; defaults PALM-OPEN / NAMASTE. Fires once per hold
        and re-arms only after the pose releases.

Units: speeds are in PALM LENGTHS per second (each hand's own
wrist->middle-knuckle length is the ruler), so every threshold holds at
any camera distance and for pixel or normalized coordinates. Shapes come
from handshape.py: finger layout rotated upright in palm lengths, plus
finger extension (fingertip reach / knuckle reach).

Why settle detection: real camera landmarks never go quiet. On the
founder's own clips the motion energy of a held hand sat at 0.8-3.5,
above the old exit threshold, so segments ran to the 3 s cap and mixed
several shapes; the hold that should have ended them needed 1.1 s and
reset on every jittery frame. Shape stability is measured directly here.
"""
import math
from collections import deque

import handshape as hs

WRIST = 0
TIPS = (4, 8, 12, 16, 20)          # thumb,index,middle,ring,pinky tips
MID_MCP = 9                       # wrist->middle-MCP = palm size ref
ANCHORS = (0, 5, 9, 13, 17)       # wrist + MCPs -> stable palm centroid
PRESENCE_SCORE = 0.25             # min per-point score to count
PRESENCE_KEYS = 6                 # min confident points for "hand present"
SHAPE_KEYS = (4, 8, 12, 16, 20, 6, 10, 14, 18)   # tips + PIP joints


def _d(ax, ay, bx, by):
    return math.hypot(ax - bx, ay - by)


def _median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def _pt(p):
    """Tolerant point parse: {x,y,score} dict or [x,y,score] sequence."""
    if isinstance(p, dict):
        s = p.get("score", 1.0)
        return (float(p.get("x", 0.0)), float(p.get("y", 0.0)),
                1.0 if s is None else float(s))
    return (float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 1.0)


class _Hand:
    """One frame's worth of one hand: presence, wrist, palm centroid,
    palm size, openness (mean tip reach / palm size), this-frame speed,
    and its shape (handshape.layout / handshape.extension)."""
    __slots__ = ("present", "wx", "wy", "cx", "cy", "palm", "openness",
                 "speed", "shape", "layout", "ext", "pattern")

    def __init__(self, pts):
        self.present = False
        self.wx = self.wy = self.cx = self.cy = 0.0
        self.palm = 1e-6
        self.openness = 0.0
        self.speed = 0.0
        self.shape = None
        self.layout = None
        self.ext = None
        self.pattern = None
        if not pts or len(pts) < 21:
            return
        conf = sum(1 for p in pts[:21] if p[2] >= PRESENCE_SCORE)
        if conf < PRESENCE_KEYS:
            return
        # a zero-padded / frozen hand (every landmark identical) is absent
        if _d(pts[0][0], pts[0][1], pts[9][0], pts[9][1]) < 1e-4 and \
           _d(pts[0][0], pts[0][1], pts[17][0], pts[17][1]) < 1e-4:
            return
        self.present = True
        self.wx, self.wy = pts[WRIST][0], pts[WRIST][1]
        self.cx = sum(pts[i][0] for i in ANCHORS) / len(ANCHORS)
        self.cy = sum(pts[i][1] for i in ANCHORS) / len(ANCHORS)
        self.palm = max(_d(pts[0][0], pts[0][1], pts[9][0], pts[9][1]),
                        1e-6)
        self.openness = sum(
            _d(pts[t][0], pts[t][1], self.wx, self.wy)
            for t in TIPS) / (len(TIPS) * self.palm)
        # translation/scale-free finger layout: tips and PIP joints
        # relative to the wrist, in palm widths
        self.shape = tuple(
            ((pts[k][0] - self.wx) / self.palm,
             (pts[k][1] - self.wy) / self.palm) for k in SHAPE_KEYS)
        self.layout = hs.layout(pts)
        self.ext = hs.extension(pts)


class Endpointer:
    """feed() one frame at a time; collect segment + mode events.

    Knobs (speeds in palm lengths per second):
      settle_s/settle_n  a shape counts as held once layout and position
                       stayed put this long, over at least this many
                       frames (at 12 fps and up the 0.18 s window already
                       holds 3; the 2-frame floor matters when the hand
                       model runs slowly, on a CPU-only laptop)
      settle_tol       max layout deviation from the window mean
                       (palm lengths) that still counts as held. Real
                       held hands read 0.005-0.06, a fist or a drifting
                       hand up to ~0.15; the finger states (below) must
                       also hold, which is what catches shape changes
      settle_pos       max palm drift inside the window (palm lengths)
      new_tol          with the same straight/curled fingers, layout gap
                       from the last sign that still makes a new one (a
                       held fist drifts 0.1-0.3 as the hand turns)
      rearm_tol/rearm_pos  layout change / palm travel that ends a hold
                       (a change of straight/curled fingers always does)
      travel_min       palm travel while holding the final shape that
                       makes a settle a moving sign (palm lengths)
      finger_v         max spread of a straight finger's extension
                       inside the settle window (curled fingers: 3x)
      straight_on/off  finger extension hysteresis (straight / curled).
                       Real straight fingers read 1.10-1.40 (low when
                       pointing at the camera), curled 0.3-1.05
      enter_v/exit_v   EMA motion-energy hysteresis for movements that
                       never settle — start above, end below
      quiet_s          quiet end of such a movement (seconds)
      min_seg_s        shortest real movement — shorter motion is dropped
      max_seg_s        longest movement — force-close
      exit_s           a hand that drops out of view within this long
                       after a settled sign is ending that sign
      entry_s          the first moments of a hand coming into view are
                       never a moving sign (it is rising into place)
      pre_roll         frames kept before activation (lead-in)
      min_frames       floor on movement length in frames
      hold_s           palm/namaste hold time before the mode event fires
      hold_v           max hand speed that still counts as "held"
      open_ratio       openness (tips/palm) that always counts as a palm;
                       four straight fingers count from open_floor up
      rearm_ratio      openness must fall below this to re-arm palm
      namaste_gap      palms-together distance, in avg-palm-size units
      namaste_open     minimum openness for each hand in namaste
      smooth_n         median window (frames) applied to raw speeds before
                       the EMA; removes single-frame landmark jitter
      enter_shape_v    smoothed finger-layout change that starts a
                       movement even when the palm stays put
      palm_grace       consecutive failing frames tolerated inside a
                       palm/namaste hold before its timer restarts
      palm_sign / namaste_sign   emitted mode-event names (None disables)

    Calibrated on landmarks from real phone-camera footage of a hand at
    12 frames per second (point, open palm, fist, V).
    """

    def __init__(self, enter_v=1.5, exit_v=0.7, ema=0.45,
                 quiet_s=0.35, min_seg_s=0.20, max_seg_s=3.0,
                 pre_roll=4, min_frames=4,
                 hold_s=0.45, hold_v=1.2,
                 open_ratio=1.55, open_floor=1.25, rearm_ratio=1.40,
                 smooth_n=3, enter_shape_v=1.4, palm_grace=2,
                 settle_s=0.18, settle_n=2, settle_tol=0.15,
                 settle_pos=0.2, new_tol=0.35, rearm_tol=0.35,
                 rearm_pos=0.8, travel_min=1.2, exit_s=0.8, entry_s=0.4,
                 straight_on=1.10, straight_off=1.05, finger_v=0.12,
                 namaste_gap=1.4, namaste_open=1.35,
                 palm_sign="PALM-OPEN", namaste_sign="NAMASTE",
                 **_retired):
        # retired knobs (hold_end_s, hold_shape_v, hold_move_v,
        # min_hold_seg_s) are accepted and ignored: settle detection
        # replaced the old hold close.
        self.enter_v = float(enter_v)
        self.exit_v = float(exit_v)
        self.ema = float(ema)
        self.quiet_s = float(quiet_s)
        self.min_seg_s = float(min_seg_s)
        self.max_seg_s = float(max_seg_s)
        self.min_frames = int(min_frames)
        self.hold_s = float(hold_s)
        self.hold_v = float(hold_v)
        self.open_ratio = float(open_ratio)
        self.open_floor = float(open_floor)
        self.rearm_ratio = float(rearm_ratio)
        self.namaste_gap = float(namaste_gap)
        self.namaste_open = float(namaste_open)
        self.smooth_n = max(1, int(smooth_n))
        self.enter_shape_v = float(enter_shape_v)
        self.palm_grace = max(0, int(palm_grace))
        self.settle_s = float(settle_s)
        self.settle_n = max(2, int(settle_n))
        self.settle_tol = float(settle_tol)
        self.settle_pos = float(settle_pos)
        self.new_tol = float(new_tol)
        self.rearm_tol = float(rearm_tol)
        self.rearm_pos = float(rearm_pos)
        self.travel_min = float(travel_min)
        self.exit_s = float(exit_s)
        self.entry_s = float(entry_s)
        self.straight_on = float(straight_on)
        self.finger_v = float(finger_v)
        self.straight_off = float(straight_off)
        self.palm_sign = palm_sign or None
        self.namaste_sign = namaste_sign or None
        self._pre = deque(maxlen=max(1, int(pre_roll)))
        self.reset()

    def reset(self):
        self._state = "idle"          # idle | active | held
        self._seg = []
        self._seg_t0 = 0.0
        self._quiet = None
        self._absent = 0              # consecutive no-hand frames
        self._from_held = False       # the open movement left a held sign
        self._pre.clear()
        self._recent = deque(maxlen=24)
        self._prev = [None, None]     # last _Hand per slot
        self._t = None                # last frame time (s)
        self._ema = None
        self._palm = [{"since": None, "armed": False, "seen": False,
                       "miss": 0} for _ in range(2)]
        self._nam = {"since": None, "armed": True, "miss": 0}
        self._raw = deque(maxlen=self.smooth_n)      # raw energy
        self._spd = [deque(maxlen=self.smooth_n) for _ in range(2)]
        self._shp = deque(maxlen=self.smooth_n)      # finger-layout rate
        self._hist = [deque(maxlen=16), deque(maxlen=16)]
        self._fing = [[None] * 4, [None] * 4]       # straight/curled state
        self._held = None             # the pose the hand is holding
        self._last = None             # the last pose that was a sign/mode
        self._chg = 0                 # consecutive changed frames in held
        self._fchg = 0                # ... of them with other fingers
        self._entered = False         # a hand came into view after the start
        self._since = None            # when the hand in view appeared (s)
        self._n = 0                   # frames seen before the current one

    @property
    def active(self):
        return self._state == "active"

    @property
    def current_len(self):
        """Frames in the in-flight segment (0 when idle)."""
        return len(self._seg)

    def _hands(self, frame):
        raw = frame.get("points") or []
        pts = [_pt(p) for p in raw]
        if len(pts) == 21:            # single-hand stream — slot by hand
            idx = 0 if str(frame.get("hand", "right")).lower() == "left" \
                else 1
            hands = [None, None]
            hands[idx] = pts
        else:
            hands = [pts[0:21] or None, pts[21:42] or None]
        return [_Hand(hands[0]), _Hand(hands[1])]

    # -- shape helpers ------------------------------------------------

    def _pattern(self, i, ext):
        """Which fingers are straight, with hysteresis; None when the
        landmarks can't tell (degenerate PIP joints)."""
        if ext is None:
            return None
        st = self._fing[i]
        for k, r in enumerate(ext):
            if r >= self.straight_on:
                st[k] = True
            elif r <= self.straight_off:
                st[k] = False
            elif st[k] is None:
                st[k] = r >= hs.EXT_ON
        return tuple(st)

    def _is_open(self, h):
        if not h.present:
            return False
        if h.openness >= self.open_ratio:
            return True
        return h.pattern == (True, True, True, True) and \
            h.openness >= self.open_floor

    def _is_closed(self, h):
        if h.openness <= self.rearm_ratio:
            return True
        return h.pattern is not None and sum(h.pattern) <= 2

    def _together(self, hands):
        a, b = hands
        if not (a.present and b.present):
            return False
        gap = _d(a.cx, a.cy, b.cx, b.cy)
        return gap <= self.namaste_gap * (a.palm + b.palm) / 2.0

    def _stable(self, i):
        """The held pose of slot i, or None while it is still changing."""
        hist = self._hist[i]
        if not hist:
            return None
        t_end = hist[-1][0]
        win = [o for o in hist if t_end - o[0] <= self.settle_s + 1e-6]
        # the shape must have held for settle_s: when frames are sparse (a
        # slow hand model) reach back one frame so the window spans it
        span = 0.85 * self.settle_s
        if len(win) < self.settle_n or win[-1][0] - win[0][0] < span:
            k = len(hist) - len(win) - 1
            if k >= 0:
                win = [hist[k]] + win
        if len(win) < self.settle_n or win[-1][0] - win[0][0] < span:
            return None
        if len({o[5] for o in win}) != 1:
            return None
        # every finger must read clearly straight or clearly curled in the
        # whole window: a finger caught mid-curl (reach 1.0-1.15) is a
        # transition, not a held shape
        if win[-1][6] is not None:
            for k in range(4):
                vals = [o[6][k] for o in win if o[6] is not None]
                if not (all(v >= self.straight_on for v in vals) or
                        all(v <= self.straight_off for v in vals)):
                    return None
                # ...and a straight finger must not be bending: a hand
                # passing through a shape curls 0.1-0.4 per frame, a held
                # straight finger stays within ~0.1. Curled fingers are half
                # hidden and their landmarks jitter 0.2-0.3, so they get a
                # looser bound.
                lim = self.finger_v if vals[0] >= self.straight_on \
                    else 3 * self.finger_v
                if max(vals) - min(vals) > lim:
                    return None
        n = len(win)
        mean = [sum(o[1][k] for o in win) / n for k in range(hs.N_LAYOUT)]
        if max(hs.layout_distance(o[1], mean) for o in win) > self.settle_tol:
            return None
        pal = sum(o[4] for o in win) / n
        mx = sum(o[2] for o in win) / n
        my = sum(o[3] for o in win) / n
        if max(_d(o[2], o[3], mx, my) for o in win) > self.settle_pos * pal:
            return None
        return {"n": n, "layout": mean, "pattern": win[-1][5],
                "cx": mx, "cy": my, "palm": pal}

    def _settled(self, hands):
        """Pose dict when every present hand is held, else None."""
        slots = [i for i, h in enumerate(hands)
                 if h.present and h.layout is not None]
        if not slots or any(not h.present or h.layout is None
                            for h in hands if h.present):
            return None
        per = {}
        for i in slots:
            s = self._stable(i)
            if s is None:
                return None
            per[i] = s
        n = min(s["n"] for s in per.values())
        open_ = all(self._is_open(hands[i]) for i in slots)
        if len(slots) == 2 and self._together(hands):
            open_ = True              # palms together: the stop gesture
        return {"slots": tuple(slots), "per": per, "n": n, "open": open_}

    def _same(self, a, b, tol):
        """Two poses show the same shape (slots, fingers, layout)."""
        if a is None or b is None or a["slots"] != b["slots"]:
            return False
        for i in a["slots"]:
            pa, pb = a["per"][i], b["per"][i]
            if pa["pattern"] != pb["pattern"]:
                return False
            if hs.layout_distance(pa["layout"], pb["layout"]) > tol:
                return False
        return True

    def _changed(self, hands):
        """Held state: has the hand left the held pose? (2-frame debounce)"""
        held = self._held
        slots = tuple(i for i, h in enumerate(hands)
                      if h.present and h.layout is not None)
        moved = False
        fingers = False
        if held is None or slots != held["slots"]:
            moved = True
        else:
            for i in slots:
                h, p = hands[i], held["per"][i]
                if h.pattern != p["pattern"]:
                    moved = fingers = True
                elif hs.layout_distance(h.layout, p["layout"]) > \
                        self.rearm_tol or \
                        _d(h.cx, h.cy, p["cx"], p["cy"]) > \
                        self.rearm_pos * p["palm"]:
                    moved = True
        self._chg = self._chg + 1 if moved else 0
        self._fchg = self._fchg + 1 if fingers else 0
        if self._fchg >= 2:
            # the fingers changed: whatever shape settles next is a new
            # sign, even the one shown before (point, fist, point)
            self._last = None
        return self._chg >= 2

    def _desc(self, pose):
        return {"slots": list(pose["slots"]),
                "layout": {i: pose["per"][i]["layout"] for i in pose["slots"]},
                "ext": {}}

    # -- main loop ----------------------------------------------------

    def feed(self, frame):
        events = []
        t = float(frame.get("t_ms") or 0) / 1000.0
        dt = t - self._t if (self._t is not None and t > self._t) else 0.0
        hands = self._hands(frame)

        energy = 0.0
        shp = 0.0
        moving = False
        for i, h in enumerate(hands):
            p = self._prev[i]
            if h.present and p is not None and p.present and dt > 0:
                # speeds in palm-widths/s — unit-free across px/normalized
                ruler = max(h.palm, p.palm, 1e-6)
                vw = _d(h.wx, h.wy, p.wx, p.wy) / (dt * ruler)
                vc = _d(h.cx, h.cy, p.cx, p.cy) / (dt * ruler)
                vs = abs(h.openness - p.openness) / dt     # spread rate
                vf = sum(_d(a[0], a[1], b[0], b[1])
                         for a, b in zip(h.shape, p.shape)) / \
                    (len(SHAPE_KEYS) * dt)
                self._spd[i].append(vw)
                h.speed = _median(self._spd[i])
                energy += vw + 0.4 * vc + 0.5 * vs
                shp = max(shp, vf)
                moving = True
            elif not h.present:
                self._spd[i].clear()
        self._prev = hands
        self._t = t
        self._raw.append(energy)
        energy = _median(self._raw)
        self._ema = energy if self._ema is None else \
            self.ema * energy + (1.0 - self.ema) * self._ema
        if moving:
            self._shp.append(shp)

        # per-slot shape history (held-pose detection)
        for i, h in enumerate(hands):
            if h.present and h.layout is not None:
                h.pattern = self._pattern(i, h.ext)
                self._hist[i].append((t, h.layout, h.cx, h.cy, h.palm,
                                      h.pattern, h.ext))
            else:
                self._hist[i].clear()
                self._fing[i] = [None] * 4
        present = any(h.present for h in hands)

        mode = self._mode_events(hands, t)
        events.extend(mode)

        self._pre.append(frame)
        self._recent.append(frame)
        if present:
            if self._absent > 0:      # back in view after an empty frame
                self._entered = True
            if self._since is None or self._absent >= 2:
                self._since = t
            self._absent = 0
        else:
            self._absent += 1
            if self._absent >= 2:
                # the hand has left: the next shape it shows is a new sign
                self._last = None
                self._held = None

        if mode:
            # an open-palm or palms-together hold just fired: that hold
            # was the gesture, whatever movement led into it is no sign
            self._seg = []
            self._quiet = None
            self._state = "held"
            pose = self._settled(hands)
            if pose is not None:
                self._held = self._last = pose
            self._n += 1
            return events

        pose = self._settled(hands) if present else None
        if self._state == "active":
            self._seg.append(frame)
            if t - self._seg_t0 >= self.max_seg_s:
                events.append(self._close(t, "maxlen"))
            elif self._absent >= 2:
                if self._from_held and t - self._seg_t0 <= self.exit_s:
                    self._drop()      # the hand dropping away after a sign
                else:
                    events.append(self._close(t, "absent"))
                self._absent = 0
            elif pose is not None:
                ev = self._settle(pose, self._seg, t)
                if ev:
                    events.append(ev)
            elif self._ema < self.exit_v:
                if self._quiet is None:
                    self._quiet = t
                elif t - self._quiet >= self.quiet_s:
                    events.append(self._close(t, "quiet"))
            else:
                self._quiet = None
        elif self._state == "held":
            if not present:
                if self._absent >= 2:
                    self._state = "idle"
            elif self._changed(hands):
                self._start(from_held=True)
        elif present:
            shaping = bool(self._shp) and \
                _median(self._shp) >= self.enter_shape_v
            if pose is not None and not self._entered:
                # resting in view since the stream began: not a sign
                # (same rule as the palm), but remember the shape so only
                # a change counts
                self._state = "held"
                self._held = self._last = pose
            elif pose is not None:
                # the hand showed a still shape without moving into it
                ev = self._settle(pose, list(self._recent)[
                    -max(pose["n"], len(self._pre)):], t)
                if ev:
                    events.append(ev)
            elif self._ema >= self.enter_v or shaping:
                self._start(from_held=False)
        self._n += 1
        return events

    def _start(self, from_held):
        self._state = "active"
        self._seg = list(self._pre)   # pre-roll includes this frame
        self._seg_t0 = float(self._pre[0].get("t_ms") or 0) / 1000.0
        self._quiet = None
        self._chg = 0
        self._from_held = from_held

    def _drop(self):
        self._seg = []
        self._state = "idle"
        self._quiet = None
        self._ema = None
        self._from_held = False

    def _settle(self, pose, frames, t):
        """The hand is holding a pose: emit the sign it makes (or nothing
        when it is the same shape again, or the listen/stop gesture)."""
        self._seg = []
        self._state = "held"
        self._quiet = None
        self._chg = 0
        self._from_held = False
        self._held = pose
        n = min(pose["n"], len(frames))
        desc = self._desc(pose)
        # a hand rising into view is coming to sign, not signing a motion
        t_from = None if self._since is None else \
            (self._since + self.entry_s) * 1000.0
        travel = hs.rigid_travel(frames, desc, t_from=t_from)
        moved = travel >= self.travel_min
        if pose["open"] and not moved:
            # palm / palms together held in place: the mode events own
            # these. An open hand that travelled is a swipe, a real sign.
            self._last = pose
            return None
        if not moved and self._same(pose, self._last, self.new_tol):
            return None               # still the sign already reported
        self._last = pose
        seg = list(frames[:-n]) + [dict(f, hold=True, travel=round(travel, 3))
                                    for f in frames[-n:]]
        t0 = float(seg[0].get("t_ms") or 0) / 1000.0
        return {"type": "segment", "how": "settle", "frames": seg,
                "hold_n": n, "motion": moved, "travel": round(travel, 3),
                "dur_s": max(0.0, t - t0), "t_ms": int(t * 1000)}

    def _close(self, t, how):
        seg, self._seg = self._seg, []
        self._state = "idle"
        self._quiet = None
        self._absent = 0
        self._from_held = False
        # The EMA tail that ended this segment belongs to it — reset the
        # smoother so a just-closed sign can never re-trigger a phantom
        # segment on the very next frame.
        self._ema = None
        dur = t - self._seg_t0
        if len(seg) >= self.min_frames and dur >= self.min_seg_s:
            return {"type": "segment", "frames": seg, "dur_s": dur,
                    "t_ms": int(t * 1000), "how": how}
        return {"type": "segment-drop", "reason": "short",
                "n": len(seg), "dur_s": dur, "t_ms": int(t * 1000)}

    def _mode_events(self, hands, t):
        ev = []
        a, b = hands
        together = self._together(hands)

        # held open palm — but hands-together means namaste, never palm.
        # A palm that is ALREADY resting in view when the stream starts is
        # not a deliberate presentation: arm on hand entry (absent->present
        # after the first frame) or after the hand closes. An open palm
        # counts by openness or by four straight fingers (real palms read
        # openness 1.5-1.7, right at the old 1.55 cut). It may fire while
        # a movement is open: real hands never go fully quiet.
        for i, h in enumerate(hands):
            st = self._palm[i]
            if h.present and not st["seen"]:
                st["seen"] = True
                if self._n > 0:       # entered view after the stream began
                    st["armed"] = True
            elif not h.present and st["seen"]:
                st["seen"] = False
                st["armed"] = True    # leaving view re-arms the next entry
            held_open = h.present and not together and \
                self._is_open(h) and h.speed <= self.hold_v
            if held_open:
                st["miss"] = 0
                if st["since"] is None:
                    st["since"] = t
                if st["armed"] and t - st["since"] >= self.hold_s:
                    st["armed"] = False
                    if self.palm_sign:
                        ev.append({"type": "mode", "name": self.palm_sign,
                                   "t_ms": int(t * 1000)})
            else:
                # tolerate a jitter frame or two inside a real hold
                st["miss"] += 1
                if (not h.present) or st["miss"] > self.palm_grace:
                    st["since"] = None
                if (not h.present) or self._is_closed(h):
                    st["armed"] = True

        # held palms-together (namaste)
        st = self._nam
        if together and a.openness >= self.namaste_open and \
                b.openness >= self.namaste_open and \
                a.speed <= self.hold_v and b.speed <= self.hold_v:
            st["miss"] = 0
            if st["since"] is None:
                st["since"] = t
            if st["armed"] and t - st["since"] >= self.hold_s:
                st["armed"] = False
                if self.namaste_sign:
                    ev.append({"type": "mode", "name": self.namaste_sign,
                               "t_ms": int(t * 1000)})
        else:
            st["miss"] += 1
            if st["miss"] > self.palm_grace:
                st["since"] = None
                st["armed"] = True
        return ev


if __name__ == "__main__":
    # tiny self-check: still -> moving -> still emits exactly one segment
    def hand(cx, cy, tip=0.10):
        p = [[cx, cy, 0.9] for _ in range(21)]
        p[MID_MCP] = [cx, cy + 0.08, 0.9]
        for i, t_ in enumerate(TIPS):
            p[t_] = [cx + (i - 2) * 0.02, cy - tip, 0.9]
        return p
    ep = Endpointer()
    out = []
    t = 0
    for k in range(10):                       # still
        t += 33
        out += ep.feed({"t_ms": t, "points": hand(0.5, 0.5) + hand(0.9, 0.9, 0)})
    for k in range(15):                       # moving
        t += 33
        out += ep.feed({"t_ms": t, "points": hand(0.5 + k * 0.03, 0.5) + hand(0.9, 0.9, 0)})
    for k in range(25):                       # still -> quiet eos
        t += 33
        out += ep.feed({"t_ms": t, "points": hand(0.92, 0.5) + hand(0.9, 0.9, 0)})
    segs = [e for e in out if e["type"] == "segment"]
    assert len(segs) == 1 and len(segs[0]["frames"]) >= 15, out
    print("endpointer self-check ok: 1 segment, %d frames" % len(segs[0]["frames"]))
