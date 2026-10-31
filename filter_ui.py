"""Is the game's "Default Ratio (Filter Applied)" setting on? (the "filtered" UI)

The filter is a sharpening plus a contrast curve that the game applies where it ENLARGES its UI (F01 findings): at
1024x768, 1280x720 and 1366x768 the UI is drawn 1:1 and nothing changes, from 1600x900 up it does. So the answer is
one of four states, and only "on" lets a reader use its filtered assets (everything else = Default, as before):

    "off"        sure it is not on (measured, or the UI size is Ideal, which has no filter)
    "on"         sure it is on
    "unknown"    not sure yet (just started, or the bar can't be seen): a miss, never a guess
    "no_effect"  the UI is drawn 1:1, so the setting changes nothing

The cue is the status bar at the bottom of the window (HP / MP / EXP gauges and buttons): its art is the same for every
player, so the probe grabs ONE small crop of it (design area x 80-900, y 722-768) and measures two things:
- match: how much the crop (shrunk to design size) looks like the stored reference bar (assets/filter_bar.npz). This
  says "it really is the bar, at the Default scale, with nothing over it" (Ideal's whole-step UI, a popup, a window
  or this app on top of it, a window that is part off screen all fail it: no vote).
- bright: the share of nearly white pixels (grey >= 250). The filter clips light greys to white: 6.4-7.5% in
  Default, 10.1-10.8% filtered (1920x1080 and 5120x2880 measured).
A state only changes after VOTES agreeing looks in a row, so a cursor or a flicker never flips it.

Pure: no screen, no files except the reference (loaded by the caller and passed in)."""
import cv2
import numpy as np

import ui_layout

OFF, ON, UNKNOWN, NO_EFFECT = "off", "on", "unknown", "no_effect"
STATES = (OFF, ON, UNKNOWN, NO_EFFECT)

REGION = (80, 900, 722, 768)        # the cue in the design area: x0, x1, y0, y1
REF_SIZE = (820, 46)                # the reference's size (width, height) = the region at 1x
MIN_SCALE = 1.05                    # below this the UI is drawn 1:1 (or nearly): the filter does nothing
MATCH_MIN = 0.72                    # least match for a vote (Default and filtered 0.74-1.0, Ideal / covered <= 0.64)
BRIGHT_LEVEL = 250                  # a grey level this high counts as white
BRIGHT_SPLIT = 0.088                # share of white: above = filtered (Default 0.064-0.075, filtered 0.101-0.108)
VOTES = 3                           # looks in a row that agree before the state changes
EVERY = 2.0                         # seconds between two probes
RUN_AGE = 30.0                      # votes older than this don't count towards VOTES


def load_reference(path):
    """The reference bar (REF_SIZE, float32 grey) from assets/filter_bar.npz, or None if it can't be read."""
    try:
        with np.load(path) as f:
            ref = f["bar"].astype(np.float32)
    except Exception:
        return None
    return ref if ref.shape == (REF_SIZE[1], REF_SIZE[0]) else None


def scale_of(window_h):
    """The UI scale at Default (the only UI size the filter exists for)."""
    return ui_layout.default_scale(window_h)


def probe_box(window_w, window_h):
    """Where the cue is in the game window, as (left, top, width, height) in window pixels."""
    s = scale_of(window_h)
    x0, y0 = ui_layout.design_to_window(REGION[0], REGION[2], window_w, window_h, s)
    x1, y1 = ui_layout.design_to_window(REGION[1], REGION[3], window_w, window_h, s)
    return int(round(x0)), int(round(y0)), int(round(x1)) - int(round(x0)), int(round(y1)) - int(round(y0))


def _grey(bgr):
    return cv2.cvtColor(np.ascontiguousarray(bgr[:, :, :3]), cv2.COLOR_BGR2GRAY)


def shrink(bgr):
    """The probe crop at design size (grey, float32): what the reference looks like."""
    return cv2.resize(_grey(bgr), REF_SIZE, interpolation=cv2.INTER_AREA).astype(np.float32)


def _ncc(a, b):
    a, b = a - a.mean(), b - b.mean()
    return float((a * b).sum() / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-9))


def measure(bgr, ref):
    """(match, bright) of a probe crop: how much it looks like the bar, and its share of white pixels."""
    return _ncc(shrink(bgr), ref), float((_grey(bgr) >= BRIGHT_LEVEL).mean())


def vote(match, bright):
    """ON, OFF, or None (this crop is not the bar, so it says nothing)."""
    if match < MATCH_MIN:
        return None
    return ON if bright > BRIGHT_SPLIT else OFF


class FilterWatch:
    """The held answer. `settle` and `due` first (no picture needed), then `feed` with a probe picture."""

    def __init__(self, ref):
        self.ref = ref                  # None = no reference file: the state stays "unknown" at enlarged sizes
        self.state = UNKNOWN
        self.last = None                # (match, bright) of the last measured probe (for diagnostics)
        self._size = None
        self._run = (None, 0, 0.0)      # (vote, how many in a row, time of the last one)
        self._next = 0.0

    @property
    def filtered(self):
        return self.state == ON

    def reset(self):
        self.state, self.last, self._size, self._run, self._next = UNKNOWN, None, None, (None, 0, 0.0), 0.0

    def settle(self, window_w, window_h, known_mode=None):
        """Decides without a picture where it can; True = decided (nothing to probe). `known_mode` is "default" or
        "ideal" when the EXP bar's digit height says so, else None."""
        size = (window_w, window_h)
        if size != self._size:          # a new window size is a new layout: start over
            self.reset()
            self._size = size
        if scale_of(window_h) < MIN_SCALE:
            self.state = NO_EFFECT
            return True
        if self.state == NO_EFFECT:
            self.state = UNKNOWN
        if known_mode == "ideal":
            self.state, self._run = OFF, (None, 0, 0.0)
            return True
        return self.ref is None

    def due(self, now):
        """Is it time for a probe? (Marks it taken: call only when going to grab.)"""
        if now < self._next:
            return False
        self._next = now + EVERY
        return True

    def feed(self, now, bgr, expected):
        """One probe picture (BGR, or None when it couldn't be taken or is covered), `expected` the (width, height)
        it should have. A picture of the wrong size (part off screen) is no vote. Returns the state."""
        if bgr is None or abs(bgr.shape[1] - expected[0]) > 1 or abs(bgr.shape[0] - expected[1]) > 1:
            return self.state
        self.last = measure(bgr, self.ref)
        v = vote(*self.last)
        if v is None:
            return self.state
        kind, n, at = self._run
        n = n + 1 if (kind == v and now - at <= RUN_AGE) else 1
        self._run = (v, n, now)
        if n >= VOTES:
            self.state = v
        return self.state
