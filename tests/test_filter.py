"""Tests for telling whether the game's "Default Ratio (Filter Applied)" UI is on (filter_ui.py + the probe in
ScreenReader). The pictures are made here from the stored reference bar: Default is the bar enlarged smoothly,
"filtered" the same with its light greys pushed to white (what the real filter does; measured on real recordings
in .scratch/0916/filter, not shipped). No game or screen needed.

Run from the project folder:  python tests/test_filter.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["MAPLE_EXP_DATA"] = tempfile.mkdtemp()           # never touch your real data
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cv2  # noqa: E402
import numpy as np  # noqa: E402
import filter_ui as fu  # noqa: E402
import maple_exp as m  # noqa: E402
import ui_layout as ul  # noqa: E402
from capture import Capture  # noqa: E402

failures = 0


def check(name, ok):
    global failures
    print(("PASS " if ok else "FAIL ") + name)
    failures += not ok


REF = fu.load_reference(m.FILTER_BAR_PATH)
check("the reference bar loads from assets/filter_bar.npz at the right size",
      REF is not None and REF.shape == (fu.REF_SIZE[1], fu.REF_SIZE[0]) and 0 < REF.mean() < 255)
check("a missing or unreadable reference file gives None, not an error",
      fu.load_reference(Path(tempfile.mkdtemp()) / "none.npz") is None)
bad = Path(tempfile.mkdtemp()) / "bad.npz"
np.savez(bad, bar=np.zeros((5, 5)))
check("a reference of the wrong size is refused", fu.load_reference(bad) is None)


def bar_crop(w, h, filtered=False):
    """The probe crop at window size w x h: the reference enlarged to the probe's size; filtered = whites pushed up."""
    _, _, cw, ch = fu.probe_box(w, h)
    up = cv2.resize(REF, (cw, ch), interpolation=cv2.INTER_CUBIC)
    if filtered:
        up = up * (250.0 / np.quantile(up, 0.885))          # 11.5% of the pixels reach 250: well above the split
    return cv2.cvtColor(np.clip(up, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)


# ---- where the probe looks
for w, h in [s for s in ul.GAME_SIZES + ((5120, 2880), (1600, 900)) if fu.scale_of(s[1]) >= fu.MIN_SCALE]:
    x, y, cw, ch = fu.probe_box(w, h)
    check(f"{w}x{h}: the probe box is inside the window, at its bottom edge, in the bar's proportions",
          x >= 0 and y >= 0 and x + cw <= w and y + ch <= h and h - (y + ch) <= 1
          and abs(cw / ch - fu.REF_SIZE[0] / fu.REF_SIZE[1]) < 0.35)
x, y, cw, ch = fu.probe_box(1920, 1080)
check("1920x1080: the box is the 820 x 46 design area at 1.406x", (cw, ch) == (1154, 65))

# ---- one picture: Default is "off", filtered is "on", anything else is no vote
for w, h in ((1920, 1080), (2560, 1440), (3840, 2160), (5120, 2880), (1600, 900)):
    d, f = fu.measure(bar_crop(w, h), REF), fu.measure(bar_crop(w, h, True), REF)
    check(f"{w}x{h}: Default bar votes off and the filtered bar votes on",
          fu.vote(*d) == fu.OFF and fu.vote(*f) == fu.ON and d[0] > 0.9 and f[0] > 0.9)
w, h = 1920, 1080
good = bar_crop(w, h, True)
rng = np.random.default_rng(3)
covered = good.copy()
covered[:, : good.shape[1] // 2] = 255                      # a window over half of it
shifted = np.roll(good, good.shape[0] // 3, axis=0)         # the bar at another scale / place (Ideal's step, a wrong size)
other = {"black": np.zeros_like(good), "white": np.full_like(good, 255), "noise": rng.integers(0, 256, good.shape, np.uint8),
         "half covered": covered, "shifted a third of its height": shifted}
for name, pic in other.items():
    check(f"a picture that is not the bar ({name}) casts no vote", fu.vote(*fu.measure(pic, REF)) is None)
check("filtered and Default differ only in the brightness share, the match stays high",
      abs(fu.measure(bar_crop(w, h), REF)[0] - fu.measure(good, REF)[0]) < 0.1)

# ---- the held state
def feed_n(watch, pic, n, t0=100.0, step=fu.EVERY, expected=None):
    exp = expected or (pic.shape[1], pic.shape[0])
    t = t0
    for _ in range(n):
        watch.feed(t, pic, exp)
        t += step
    return t


off_pic, on_pic = bar_crop(1920, 1080), bar_crop(1920, 1080, True)
wt = fu.FilterWatch(REF)
check("a new watch is unknown (not off, not on)", wt.state == fu.UNKNOWN and not wt.filtered)
wt.settle(1920, 1080)
feed_n(wt, on_pic, fu.VOTES - 1)
check(f"{fu.VOTES - 1} filtered looks are not enough: still unknown", wt.state == fu.UNKNOWN and not wt.filtered)
feed_n(wt, on_pic, 1, t0=110)
check(f"{fu.VOTES} filtered looks in a row: on", wt.state == fu.ON and wt.filtered)
t = feed_n(wt, off_pic, fu.VOTES - 1, t0=120)
check("two Default looks after it don't flip it back (a flicker)", wt.state == fu.ON)
t = feed_n(wt, on_pic, 1, t0=t)
t = feed_n(wt, off_pic, fu.VOTES - 1, t0=t)
check("a filtered look in between starts the count again", wt.state == fu.ON)
feed_n(wt, off_pic, 1, t0=t)
check(f"{fu.VOTES} Default looks in a row: off", wt.state == fu.OFF and not wt.filtered)
t = feed_n(wt, off_pic, 1, t0=500)
black = np.zeros_like(off_pic)
for _ in range(10):
    t = feed_n(wt, black, 1, t0=t)
check("pictures that aren't the bar (cursor, popup, chat) change nothing, however many", wt.state == fu.OFF)
wt2 = fu.FilterWatch(REF)
wt2.settle(1920, 1080)
t = feed_n(wt2, on_pic, 2, t0=100)
feed_n(wt2, black, 1, t0=t)
feed_n(wt2, on_pic, 1, t0=t + 1)
check("a no-vote picture between agreeing looks doesn't restart the count", wt2.state == fu.ON)
wt3 = fu.FilterWatch(REF)
wt3.settle(1920, 1080)
feed_n(wt3, on_pic, 2, t0=100)
feed_n(wt3, on_pic, 1, t0=100 + 2 * fu.EVERY + fu.RUN_AGE + 1)
check("looks far apart in time don't add up", wt3.state == fu.UNKNOWN)
wt4 = fu.FilterWatch(REF)
wt4.settle(1920, 1080)
feed_n(wt4, on_pic[:, :-30], 6, expected=(on_pic.shape[1], on_pic.shape[0]))
feed_n(wt4, None, 6, expected=(on_pic.shape[1], on_pic.shape[0]))
check("a picture of the wrong size (part of the window off screen) or none at all is no vote", wt4.state == fu.UNKNOWN)
check("the probe is taken every EVERY seconds, not more often",
      [fu.FilterWatch(REF).due(0.0)] == [True] and not (lambda w: (w.due(10.0), w.due(10.5))[1])(fu.FilterWatch(REF))
      and (lambda w: (w.due(10.0), w.due(10.0 + fu.EVERY))[1])(fu.FilterWatch(REF)))

# ---- sizes where the filter does nothing, Ideal, no reference
for w, h in ((1024, 768), (1280, 720), (1366, 768), (800, 600)):
    wn = fu.FilterWatch(REF)
    check(f"{w}x{h}: the UI is drawn 1:1, so the state is no_effect without any picture",
          wn.settle(w, h) and wn.state == fu.NO_EFFECT and not wn.filtered)
for w, h in ((1600, 900), (1920, 1080), (1920, 1200), (2560, 1440), (3840, 2160), (5120, 2880)):
    wn = fu.FilterWatch(REF)
    check(f"{w}x{h}: an enlarged UI is probed (not no_effect)", not wn.settle(w, h) and wn.state == fu.UNKNOWN)
wi = fu.FilterWatch(REF)
check("a known Ideal UI is off at once (the filter has no Ideal version), never on",
      wi.settle(1920, 1080, "ideal") and wi.state == fu.OFF)
check("a known Default UI is probed", not fu.FilterWatch(REF).settle(1920, 1080, "default"))
wr = fu.FilterWatch(None)
check("with no reference file the state stays unknown at an enlarged size and nothing is probed",
      wr.settle(1920, 1080) and wr.state == fu.UNKNOWN)
wz = fu.FilterWatch(REF)
wz.settle(1920, 1080)
feed_n(wz, on_pic, fu.VOTES)
wz.settle(2560, 1440)
check("a new window size starts over (unknown)", wz.state == fu.UNKNOWN)
wz.settle(1920, 1080)
feed_n(wz, on_pic, fu.VOTES)
wz.settle(1366, 768)
check("shrinking to a 1:1 size says no_effect, and growing again starts unknown", wz.state == fu.NO_EFFECT
      and (wz.settle(1920, 1080), wz.state)[1] == fu.UNKNOWN)


# ---- the reader's probe: a fake game window on a fake screen
class FakeCapture(Capture):
    """Shows `scene` (the whole game window, at screen position 0, 0) and counts the pictures asked for."""
    sees_through_windows = False

    def __init__(self, scene):
        self.scene, self.grabs = scene, 0

    def grab(self, left, top, width, height):
        self.grabs += 1
        crop = self.scene[top:top + height, left:left + width]
        return (crop.copy(), left, top) if crop.size else None


def scene_of(w, h, filtered):
    s = np.zeros((h, w, 3), np.uint8)
    x, y, cw, ch = fu.probe_box(w, h)
    s[y:y + ch, x:x + cw] = bar_crop(w, h, filtered)
    return s


clock = [1000.0]
m.time.monotonic = lambda: clock[0]          # (the reader's clock, so the 2 s wait costs nothing)


def reader_at(w, h, **kw):
    r = m.ScreenReader(m.DigitTemplates.load())
    r.hwnd, r.mode = 1, "window"
    r.__dict__.update(kw)
    return r


def looks(r, cap, rect, n):
    for _ in range(n):
        r._look_at_filter(cap, rect)
        clock[0] += fu.EVERY + 0.1


rect = (0, 0, 1920, 1080)
r = reader_at(1920, 1080)
check("a reader starts with the filter unknown and not filtered", r.filter_state == "unknown" and r.filtered is False)
cap = FakeCapture(scene_of(1920, 1080, True))
looks(r, cap, rect, fu.VOTES - 1)
check("the reader says unknown until sure", r.filter_state == "unknown" and not r.filtered)
looks(r, cap, rect, 1)
check("the reader says on, and `filtered` is True, after enough filtered looks", r.filter_state == "on" and r.filtered is True)
cap2 = FakeCapture(scene_of(1920, 1080, False))
looks(r, cap2, rect, fu.VOTES)
check("and off again after enough Default looks", r.filter_state == "off" and r.filtered is False)
cap3 = FakeCapture(scene_of(1920, 1080, True))
r._look_at_filter(cap3, rect)
r._look_at_filter(cap3, rect)
check("two looks in the same 2 seconds take only one picture", cap3.grabs == 1)

r = reader_at(1366, 768)
capn = FakeCapture(scene_of(1366, 768, True))
looks(r, capn, (0, 0, 1366, 768), 6)
check("1366x768: no_effect, and not one picture is taken", r.filter_state == "no_effect" and capn.grabs == 0 and not r.filtered)

r = reader_at(1920, 1080, gh=7.0)
capi = FakeCapture(scene_of(1920, 1080, True))
looks(r, capi, rect, 6)
check("the EXP bar's digits say Ideal (gh 7 at 1080p): off, no picture taken, never filtered",
      r.filter_state == "off" and capi.grabs == 0 and not r.filtered)

r = reader_at(1920, 1080, mode="region")
looks(r, FakeCapture(scene_of(1920, 1080, True)), rect, 6)
check("a selected area has no game window to look at: unknown", r.filter_state == "unknown" and not r.filtered)
r = reader_at(1920, 1080)
looks(r, FakeCapture(scene_of(1920, 1080, True)), None, 6)
check("no game window (minimized, closed): unknown", r.filter_state == "unknown")

x, y, cw, ch = fu.probe_box(1920, 1080)
r = reader_at(1920, 1080, own_rect=(x + 10, y - 5, 200, 100))
capc = FakeCapture(scene_of(1920, 1080, True))
looks(r, capc, rect, 6)
check("this app's own window over the bar: no picture taken, state stays unknown",
      capc.grabs == 0 and r.filter_state == "unknown")

r = reader_at(1920, 1080)
looks(r, FakeCapture(scene_of(1920, 1080, True)), rect, fu.VOTES)
r.look_again()
r._forget_places()
check("'look again' forgets the filter answer too", r.filter_state == "unknown")

r = reader_at(1920, 1080)
looks(r, FakeCapture(scene_of(1920, 1080, True)), rect, 1)
looks(r, FakeCapture(scene_of(2560, 1440, True)), (0, 0, 2560, 1440), fu.VOTES)
check("a size change is a new start: the same reader says on at the new size after enough looks", r.filter_state == "on")

# a whole look: the probe is part of it, and a probe that fails never stops the look
def whole_look(r, cap, rect):
    r._game_rect = lambda: rect
    r._read_window = lambda capture, rect_: m.Reading("not found", exp_kind="not_found")
    return r._look(cap)


r = reader_at(1920, 1080)
cap = FakeCapture(scene_of(1920, 1080, True))
for _ in range(fu.VOTES):
    whole_look(r, cap, rect)
    clock[0] += fu.EVERY + 0.1
check("a whole look runs the probe: on after enough looks", r.filter_state == "on")


def broken(*a):
    raise OSError("screen gone")


r = reader_at(1920, 1080)
r._look_at_filter = broken
reading = whole_look(r, FakeCapture(scene_of(1920, 1080, True)), rect)
check("a probe that fails is counted as a failed 'filter' part and the look still finishes",
      r.part_errors["filter"] == 1 and reading.exp_kind == "not_found")

print("\nALL PASSED" if not failures else f"\n{failures} FAILED")
sys.exit(1 if failures else 0)
