"""Where the reader's pictures of the screen come from.

The reader asks a Capture for a rectangle in SCREEN coordinates and gets it back as (bgr, left, top), or
None when it is off the monitors. Today the only source is a copy of the screen (ScreenCapture), which shows
whatever window is on top, this app's included. A source that can see the game through other windows
(window capture) says so with `sees_through_windows`, so the reader doesn't skip areas this app covers."""

import numpy as np


def grab(sct, left, top, width, height):
    """Screenshot of a screen rectangle, clipped to the monitors: (bgr, left, top) or None."""
    v = sct.monitors[0]
    x0, y0 = max(left, v["left"]), max(top, v["top"])
    x1 = min(left + width, v["left"] + v["width"])
    y1 = min(top + height, v["top"] + v["height"])
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    shot = np.array(sct.grab({"left": x0, "top": y0, "width": x1 - x0, "height": y1 - y0}))
    return np.ascontiguousarray(shot[:, :, :3]), x0, y0


def black_out(shot, rect):
    """The (bgr, left, top) screenshot with the screen rectangle `rect` blacked out (a copy, if any of it was inside)."""
    if not shot or not rect:
        return shot
    img, sx, sy = shot
    x0, y0 = max(0, rect[0] - sx), max(0, rect[1] - sy)
    x1, y1 = min(img.shape[1], rect[0] + rect[2] - sx), min(img.shape[0], rect[1] + rect[3] - sy)
    if x0 < x1 and y0 < y1:
        img = img.copy()
        img[y0:y1, x0:x1] = 0
    return img, sx, sy


class Capture:
    """The interface. Subclasses fill in grab() and, if they see through windows, the flag."""
    name = "screen"                     # for bug reports and health reports
    sees_through_windows = False        # True: a window on top of the game isn't in the picture

    def grab(self, left, top, width, height):
        raise NotImplementedError

    def begin_look(self):
        """Called before the reader's look at the screen (a source that fetches one frame per look does it here)."""

    def end_look(self):
        """Called after the look, whatever happened."""

    def window_at(self, handle, rect):
        """Called in a look once the reader knows the game window (its handle) and where it is on screen."""


class ScreenCapture(Capture):
    """A copy of the screen (mss): shows whatever is on top, so this app's own window is in the way."""
    name = "screen"

    def __init__(self, sct):
        self.sct = sct

    def grab(self, left, top, width, height):
        return grab(self.sct, left, top, width, height)


class WindowCapture(ScreenCapture):
    """The game window pictured alone (platform.capture_window; macOS), so nothing on top of it, this app's
    window included, is in the way. Each picture costs about the same whatever its size, so it's taken once per
    look, the whole window, and every part inside it is cut from that. A part reaching outside the window, or a
    look whose picture failed, is a screen copy as before: then this app's window does cover the game."""

    def __init__(self, sct, platform, own_rect):
        super().__init__(sct)
        self.platform, self.own_rect = platform, own_rect     # own_rect(): this app's window on screen, or None
        self.whole = self.rect = None

    @property
    def name(self):
        return "window" if self.whole is not None else "screen"

    @property
    def sees_through_windows(self):
        return self.whole is not None

    def begin_look(self):
        self.whole = self.rect = None

    def window_at(self, handle, rect):
        self.whole = self.platform.capture_window(handle, *rect) if handle and rect else None
        self.rect = rect if self.whole is not None else None

    def grab(self, left, top, width, height):
        if self.whole is not None:
            x, y, w, h = self.rect
            if x <= left and y <= top and left + width <= x + w and top + height <= y + h:
                part = self.whole[top - y:top - y + height, left - x:left - x + width, :3]
                return np.ascontiguousarray(part), left, top
        shot = super().grab(left, top, width, height)
        # (a screen copy in a see-through look: the reader won't hide this app's window from it, so it's hidden here)
        return black_out(shot, self.own_rect()) if self.whole is not None else shot


def as_capture(source):
    """A Capture from either a Capture or a bare mss-like object (the tests pass a fake screen)."""
    return source if isinstance(source, Capture) else ScreenCapture(source)
