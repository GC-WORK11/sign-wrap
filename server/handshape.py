"""handshape — what a held hand shape looks like, independent of where the
hand is in the picture, how big it looks and how it is turned.

Shared by endpointer.py (has the hand settled into a shape?) and
signbank.py (which taught sign is this held shape?). Pure stdlib.

A shape is the 20 non-wrist landmarks relative to the wrist, rotated so
the wrist -> middle-knuckle line points up, measured in palm lengths
(wrist -> middle knuckle). Finger extension (fingertip reach over knuckle
reach, from the wrist) is kept beside it: on real camera landmarks a
straight finger reads 1.2-1.4 and a curled one 0.3-0.8, whatever the
camera distance or hand size.

Wire format is the kp42 frame used everywhere else:
    {"t_ms": int, "points": [{"x","y","score"} x42], "hand"?: "left"|"right"}
points[0:21] = slot 0, points[21:42] = slot 1. A 21-point frame is one hand
in the slot named by frame["hand"] (default right).
"""
import math

PRESENCE_SCORE = 0.25     # min per-point score to count
PRESENCE_KEYS = 6         # min confident points for "hand present"
FINGERS = ((8, 6), (12, 10), (16, 14), (20, 18))   # (tip, PIP) index..pinky
EXT_ON = 1.10             # reach ratio at or above which a finger is straight
N_LAYOUT = 40             # 20 landmarks x (x, y)
LAYOUT_WEIGHT = 0.1       # weight of the layout gap in shape_distance
INF = float("inf")


def pt(p):
    """Tolerant point parse: {x,y,score} dict or [x,y,score] sequence."""
    if isinstance(p, dict):
        s = p.get("score", 1.0)
        return (float(p.get("x", 0.0)), float(p.get("y", 0.0)),
                1.0 if s is None else float(s))
    return (float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 1.0)


def hands_of(frame):
    """[slot0, slot1]: each a list of 21 (x, y, score) or None when absent."""
    raw = frame.get("points") or []
    pts = [pt(p) for p in raw]
    if len(pts) == 21:
        idx = 0 if str(frame.get("hand", "right")).lower() == "left" else 1
        out = [None, None]
        out[idx] = pts
    else:
        out = [pts[0:21] or None, pts[21:42] or None]
    return [h if (h and len(h) >= 21 and present(h)) else None for h in out]


def present(h):
    if sum(1 for p in h[:21] if p[2] >= PRESENCE_SCORE) < PRESENCE_KEYS:
        return False
    # a zero-padded or frozen hand (every landmark identical) is absent
    return not (math.hypot(h[0][0] - h[9][0], h[0][1] - h[9][1]) < 1e-4 and
                math.hypot(h[0][0] - h[17][0], h[0][1] - h[17][1]) < 1e-4)


def palm_length(h):
    return math.hypot(h[9][0] - h[0][0], h[9][1] - h[0][1])


def layout(h):
    """40 floats (20 landmarks x, y) or None when the palm is unmeasurable."""
    wx, wy = h[0][0], h[0][1]
    L = palm_length(h)
    if L < 1e-6:
        return None
    a, b = (h[9][0] - wx) / L, (h[9][1] - wy) / L
    # rotation taking the wrist->middle-knuckle direction (a, b) to (0, -1)
    out = []
    for k in range(1, 21):
        dx, dy = h[k][0] - wx, h[k][1] - wy
        out.append((-b * dx + a * dy) / L)
        out.append((-a * dx - b * dy) / L)
    return tuple(out)


def extension(h):
    """Fingertip reach / PIP reach from the wrist, index..pinky. None when a
    PIP sits on the wrist (degenerate landmarks)."""
    wx, wy = h[0][0], h[0][1]
    L = palm_length(h)
    out = []
    for tip, pip in FINGERS:
        dp = math.hypot(h[pip][0] - wx, h[pip][1] - wy)
        if L < 1e-6 or dp < 0.3 * L:
            return None
        out.append(math.hypot(h[tip][0] - wx, h[tip][1] - wy) / dp)
    return tuple(out)


def layout_distance(a, b):
    """Mean landmark gap between two layouts, in palm lengths."""
    n = len(a) // 2
    return sum(math.hypot(a[2 * i] - b[2 * i], a[2 * i + 1] - b[2 * i + 1])
               for i in range(n)) / n


def _median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def descriptor(frames):
    """Held-shape descriptor of frames (normally a segment's hold frames):
    {"slots": [...], "layout": {slot: [40]}, "ext": {slot: [4]|None}}.
    Per-dimension medians over frames, per slot that is present in at
    least half the frames. None when no hand is present."""
    lays = {0: [], 1: []}
    exts = {0: [], 1: []}
    n = 0
    for fr in frames or []:
        n += 1
        for i, h in enumerate(hands_of(fr)):
            if h is None:
                continue
            lo = layout(h)
            if lo is None:
                continue
            lays[i].append(lo)
            e = extension(h)
            if e is not None:
                exts[i].append(e)
    if not n:
        return None
    out = {"slots": [], "layout": {}, "ext": {}}
    for i in (0, 1):
        if len(lays[i]) * 2 < n or not lays[i]:
            continue
        out["slots"].append(i)
        out["layout"][i] = [_median([lo[k] for lo in lays[i]])
                            for k in range(N_LAYOUT)]
        out["ext"][i] = ([_median([e[k] for e in exts[i]]) for k in range(4)]
                         if exts[i] else None)
    return out if out["slots"] else None


def _get(d, key, slot):
    v = d.get(key) or {}
    return v.get(slot, v.get(str(slot)))


def straightness(r):
    """Finger reach ratio -> 0 (curled, reach <= 0.8) .. 1 (straight,
    reach >= 1.25). Curled fingers are half hidden and their exact reach
    is noise; what tells real shapes apart is which fingers are straight."""
    return min(1.0, max(0.0, (r - 0.8) / 0.45))


def shape_distance(a, b):
    """How different two held shapes are (0 = identical): the mean gap in
    finger straightness, plus a small layout term. One finger straight in
    one shape and curled in the other gives 0.25 or more. On the founder's
    own clips the same shape across recordings stayed under 0.12 and
    point / V / fist never came closer than 0.25 to each other.
    One-hand shapes compare whatever slot each hand landed in (camera
    handedness flickers); a one-hand shape never matches a two-hand one."""
    if not a or not b:
        return INF
    sa, sb = list(a.get("slots") or []), list(b.get("slots") or [])
    if not sa or not sb or len(sa) != len(sb):
        return INF
    pairs = list(zip(sa, sb)) if len(sa) == 1 else [(0, 0), (1, 1)]
    total = 0.0
    for ia, ib in pairs:
        la, lb = _get(a, "layout", ia), _get(b, "layout", ib)
        if not la or not lb:
            return INF
        lay = layout_distance(la, lb)
        ea, eb = _get(a, "ext", ia), _get(b, "ext", ib)
        if ea and eb:
            d = sum(abs(straightness(x) - straightness(y))
                    for x, y in zip(ea, eb)) / 4.0 + LAYOUT_WEIGHT * lay
        else:
            d = lay               # landmarks too degenerate for fingers
        total += d
    return total / len(pairs)


def is_open(desc):
    """True when every hand in the descriptor shows four straight fingers."""
    if not desc:
        return False
    for i in desc.get("slots") or []:
        e = _get(desc, "ext", i)
        if not e or sum(1 for x in e if x >= EXT_ON) < 4:
            return False
    return True


def rigid_travel(frames, desc, tol=0.25, t_from=None):
    """How far the palm travelled while already holding the final shape,
    in palm lengths: the distance from the first frame whose shape is
    within `tol` of `desc` to the last frame. Separates a sign made of a
    moving held shape (a swipe) from a hand that moves into place while
    the shape forms (the lead-in to a still sign). Frames before `t_from`
    (ms; the hand still coming into view) never count."""
    if not desc or not frames:
        return 0.0
    if t_from is None:
        marked = [f.get("travel") for f in frames
                  if isinstance(f, dict) and f.get("hold") and
                  isinstance(f.get("travel"), (int, float))]
        if marked:                    # measured by the endpointer, which
            return float(max(marked))  # knows when the hand came into view
    slot = (desc.get("slots") or [None])[0]
    target = _get(desc, "layout", slot)
    if target is None:
        return 0.0
    path = []
    for fr in frames:
        if t_from is not None and float(fr.get("t_ms") or 0) < t_from:
            path.append(None)
            continue
        hs = hands_of(fr)
        h = hs[slot] if len(desc["slots"]) > 1 else (hs[1] or hs[0])
        if h is None:
            path.append(None)
            continue
        lo = layout(h)
        L = palm_length(h)
        if lo is None or L < 1e-6:
            path.append(None)
            continue
        cx = sum(h[k][0] for k in (0, 5, 9, 13, 17)) / 5.0
        cy = sum(h[k][1] for k in (0, 5, 9, 13, 17)) / 5.0
        path.append((cx, cy, L, layout_distance(lo, target) <= tol))
    end = next((p for p in reversed(path) if p is not None), None)
    if end is None:
        return 0.0
    best = 0.0
    # walk back from the end while the hand keeps the final shape
    for p in reversed(path):
        if p is None or not p[3]:
            break
        best = max(best, math.hypot(p[0] - end[0], p[1] - end[1]) / end[2])
    return best
