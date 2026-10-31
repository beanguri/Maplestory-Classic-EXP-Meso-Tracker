"""Adds the controller slots' own fingerprints to assets/potion_table.json.

Fingerprints are a few numbers per icon (no pictures, ADR 0002). The keyboard's were measured on real slots earlier;
a controller slot draws the same icon a little differently (no key label plate, the icon fills more of the slot), so
the table also holds, per item recorded on controller slots, "seen_controller": the mean fingerprint of its slots
(one per UI mode and brightness, cut where the finder puts the slot), a few "Controller skill icon N" entries
(kind "skill", fingerprints of the skill icons seen there, plus damaged copies of them: a blurred or tinted skill
must never pass for a potion), and, with the icon folder given, "fingerprint_controller" for every item: its
database icon drawn the way the controller's slot draws it (size and place fitted to the items seen there).

Usage (from the repo root):
    python -I tools/make_potion_seen.py <truth_tune.json> [--variants <folder>] [--icons <catalog.json> <icons_folder>]
  truth_tune.json: the potion test library's tune truth (frames with each slot's rectangle, item and quality; the
  pictures are read from its "root" folder). Only TUNE frames: the gate is never looked at. --variants: the
  folder with reader-v2's variants.py (damage kinds); without it, no damaged copies are added. --icons: the
  catalog (name, icon_id, origin per item) and the folder of icon PNGs (untrusted downloads kept outside the repo,
  read only to compute numbers); without them, "fingerprint_controller" is left as it is.
Re-running replaces what an earlier run added.

Filtered (the game's "Default Ratio (Filter Applied)", 0.9.16):
    python -I tools/make_potion_seen.py --filtered <truth_tune.json> [--real <filtered_truth_tune.json>]
  Adds "seen_filtered" (keyboard slots) and "seen_controller_filtered" (controller slots) to the items, and touches nothing else. The
  filter is a sharpening (a blurred copy of the picture, SHARP_SIGMA UI scales wide, SHARP_AMOUNT of its difference added back; fitted on real
  filtered/Default pairs, see level_ocr.py); it does nothing where the UI is drawn 1:1, and Ideal has no filter. So the Default-UI tune slots
  at a UI scale of 1.05 or more are cut out of the frame, sharpened that way, and fingerprinted like the real ones. Checked on the real
  filtered tune recordings: the made fingerprints are 0.01-0.10 from the real filtered ones (Default's are 0.17-0.65). Skill icons only
  join the skill entries they are 0.10 or less from (the others are left out). Used only while the filter is known to be on.
  --real: the filtered tune recordings' own truth ({setup: {full|strip: {frame: {"filter", "slots"}}}}, "root" = C:/mxp/rec, a setup's window
  size from its notes.json): an item the Default libraries never recorded (Red Potion, White Potion) gets its rows from the real filtered
  slots (the filter on, quality clean) instead. Tune recordings only: the exam is never looked at.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import potion_bar                                      # noqa: E402
import potions                                         # noqa: E402

TABLE = ROOT / "assets" / "potion_table.json"
MIN_SAMPLES = 5            # a group of slots needs this many pictures to make an entry
SAME_SKILL = 0.04          # two skill fingerprints this close (mean absolute difference) are the same icon
SKILL_NAME = "Controller skill icon "
DAMAGES = ("hue+8", "hue-8", "hue+15", "hue-15", "sat0.5", "sat1.6", "gamma0.7", "gamma1.5", "contrast0.7", "warm",
           "grey", "lifted", "chroma420", "resize0.9")
# the controller slot as drawn for the references: size (a slot is 31.8 x 29.9 design px, the icon cell 32 icon px) and the
# icon's scale and place are searched around these
REF_SLOT = (119, 112)
REF_SCALES = (3.7, 3.8, 3.9, 4.0, 4.1, 4.2)
REF_SHIFTS = range(-12, 3, 2)
REF_BACKGROUND = (246, 248, 252)


def slot_pictures(truth):
    """(frame, slot truth, crop) for every controller slot of the tune frames, cut where the finder puts it."""
    root = Path(truth["root"])
    for f in truth["frames"]:
        if f["layout"] != "controller-cross" or not f["visible"]:
            continue
        img = cv2.imread(str(root / f["path"]))
        if img is None:
            continue
        w, h = f["window"]
        at = (0, h - img.shape[0])
        bar = potion_bar.find_bar(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), at, w, h)
        if bar is None or bar.layout != "controller-cross":
            continue
        for spot in bar.slots:
            x, y, sw, sh = spot.rect
            truth_slot = f["slots"][spot.index]
            if truth_slot["index"] != spot.index or abs(truth_slot["rect"][0] - x) > 3 or abs(truth_slot["rect"][1] - y) > 3:
                continue
            crop = img[y - at[1]:y - at[1] + sh, x:x + sw]
            if crop.shape[:2] == (sh, sw):
                yield f, truth_slot, crop


def fingerprint_of(crop):
    return potions.fingerprint(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB), style="controller")


def render_reference(icon, origin, scale, dx, dy):
    """A database icon (BGRA) drawn on a plain controller slot (an RGB picture): scaled, bottom-aligned by its origin, shifted by (dx, dy)."""
    w, h = REF_SLOT
    ih, iw = icon.shape[:2]
    t = cv2.resize(icon, (int(round(iw * scale)), int(round(ih * scale))), interpolation=cv2.INTER_LINEAR)
    alpha = t[..., 3].astype(np.float32) / 255.0
    alpha = np.where(alpha < 0.6, 0.0, alpha)                       # (the soft ground shadow the database icons carry)
    canvas = np.zeros((h, w, 3), np.float32) + np.array(REF_BACKGROUND, np.float32)
    x0 = int(round(-origin[0] * scale)) + 2 + dx
    y0 = int(round((32 - origin[1]) * scale)) + 2 + dy
    ys, xs = np.nonzero(alpha > 0)
    ok = (ys + y0 >= 0) & (ys + y0 < h) & (xs + x0 >= 0) & (xs + x0 < w)
    ys, xs = ys[ok], xs[ok]
    a = alpha[ys, xs][:, None]
    canvas[ys + y0, xs + x0] = canvas[ys + y0, xs + x0] * (1 - a) + t[ys, xs, 2::-1] * a
    return canvas.astype(np.uint8)


def controller_references(data, catalog, icons):
    """Adds "fingerprint_controller" to every item with an icon: the drawing's size and place are the ones whose drawn
    fingerprints are closest to the items recorded on controller slots (printed)."""
    by_name = {c["name"]: c for c in catalog}
    drawn = {}
    for item in data["items"]:
        c = by_name.get(item["name"])
        path = Path(icons) / f"{c['icon_id']}.png" if c else None
        if path is not None and path.exists():
            drawn[item["name"]] = (cv2.imread(str(path), cv2.IMREAD_UNCHANGED), tuple(c["origin"]) if c.get("origin") else (-3, 30))
    seen = {i["name"]: np.array(i["seen_controller"][0], np.float32) for i in data["items"]
            if i.get("seen_controller") and i["name"] in drawn}
    if not seen:
        print("no item recorded on a controller slot has an icon: nothing fitted")
        return

    def fp(name, scale, dx, dy):
        icon, origin = drawn[name]
        return potions.fingerprint(render_reference(icon, origin, scale, dx, dy), reference=True)
    best = min(((np.mean([float(potions.PotionTable._distances(fp(n, sc, dx, dy)[None, :], v)[0]) for n, v in seen.items()]), sc, dx, dy)
                for sc in REF_SCALES for dx in REF_SHIFTS for dy in REF_SHIFTS))
    print(f"controller references: icon scale {best[1]}, shift ({best[2]}, {best[3]}); mean distance to the {len(seen)} recorded items {best[0]:.2f}")
    for item in data["items"]:
        if item["name"] in drawn:
            item["fingerprint_controller"] = [round(float(v), 4) for v in fp(item["name"], *best[1:])]


SHARP_SIGMA, SHARP_AMOUNT = 0.55, 1.1      # as in level_ocr.py and glyphs.py
SKILL_JOIN = 0.10          # a sharpened skill icon joins the skill entry it is this close to (the metric of PotionTable._distances)
FILTER_MIN_SCALE = 1.05    # below this the UI is drawn 1:1 and the filter does nothing (ScreenReader.filter_state "no_effect")


def sharpen_slot(img, rect, scale):
    """The slot's crop (BGR) of img with the filter's sharpening applied (computed over the crop plus a margin, so its edges are right)."""
    x, y, w, h = rect
    pad = int(np.ceil(4 * SHARP_SIGMA * scale)) + 2
    x0, y0 = max(x - pad, 0), max(y - pad, 0)
    part = img[y0:y + h + pad, x0:x + w + pad].astype(np.float32)
    blur = cv2.GaussianBlur(part, (0, 0), SHARP_SIGMA * scale, borderType=cv2.BORDER_REPLICATE)
    out = np.clip(part + SHARP_AMOUNT * (part - blur), 0, 255).astype(np.uint8)
    return out[y - y0:y - y0 + h, x - x0:x - x0 + w]


def filtered_rows(truth, data):
    """Sets "seen_filtered" / "seen_controller_filtered" on the items of `data` from the sharpened Default tune slots of `truth`."""
    root = Path(truth["root"])
    groups = defaultdict(list)                 # (style, item name or skill entry name, quality) -> fingerprints
    skill_rows = [(i["name"], np.array(fp, np.float32)) for i in data["items"] if i.get("kind") == "skill" for fp in i.get("seen", ())]
    skill_rows += [(i["name"], np.array(fp, np.float32)) for i in data["items"] if i.get("kind") == "skill" for fp in i.get("seen_controller", ())]
    n_frames = 0
    for f in truth["frames"]:
        if f["mode"] != "default" or not f["visible"] or f["scale"] < FILTER_MIN_SCALE:
            continue
        img = cv2.imread(str(root / f["path"]))
        if img is None:
            continue
        w, h = f["window"]
        at = (0, h - img.shape[0])
        bar = potion_bar.find_bar(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), at, w, h)
        if bar is None or bar.layout not in potion_bar.FIND_LAYOUTS:
            continue
        n_frames += 1
        truth_slots = {s["index"]: s for s in f["slots"]}
        for spot in bar.slots:
            slot = truth_slots.get(spot.index)
            x, y, sw, sh = spot.rect
            if slot is None or abs(slot["rect"][0] - x) > 3 or abs(slot["rect"][1] - y) > 3 or slot["quality"] not in ("clean", "dim"):
                continue
            if slot["kind"] not in ("consumable", "skill", "other"):
                continue
            crop = sharpen_slot(img, (x, y - at[1], sw, sh), bar.scale)
            if crop.shape[:2] != (sh, sw):
                continue
            vec = potions.fingerprint(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB), style=spot.style)
            if vec is None:
                continue
            if slot["kind"] == "skill":
                d = [(float(potions.PotionTable._distances(row[None], vec)[0]), name) for name, row in skill_rows]
                best = min(d) if d else None
                if best is None or best[0] > SKILL_JOIN:
                    continue
                name = best[1]
            elif slot["item"]:
                name = slot["item"].replace(" (Alt)", "")
            else:
                continue
            groups[(spot.style, name, slot["quality"])].append(vec)
    print(f"{n_frames} Default frames at a UI scale of {FILTER_MIN_SCALE} or more")
    by_name = {i["name"]: i for i in data["items"]}
    for i in data["items"]:
        i.pop("seen_filtered", None)
        i.pop("seen_controller_filtered", None)
    for (style, name, quality), vecs in sorted(groups.items()):
        key = "seen_filtered" if style == "keyboard" else "seen_controller_filtered"
        print(f"{name:20s} {style:10s} {quality:6s} {len(vecs):4d} slots", "" if len(vecs) >= MIN_SAMPLES else "(too few: left out)")
        if len(vecs) >= MIN_SAMPLES and name in by_name:
            by_name[name].setdefault(key, []).append([round(float(v), 4) for v in np.mean(vecs, axis=0)])


def real_rows(path, data, root="C:/mxp/rec"):
    """Adds "seen_filtered" rows for the consumables that have none yet, from the filter-on slots of the filtered tune recordings."""
    truth = json.loads(Path(path).read_text(encoding="utf-8"))
    by_name = {i["name"]: i for i in data["items"]}
    groups = defaultdict(list)
    for setup, kinds in truth.items():
        notes = json.loads((Path(root) / setup / "notes.json").read_text(encoding="utf-8"))
        w, h = notes["sizes"][0]["rect"][2:4]
        for kind, frames in kinds.items():
            for name, f in frames.items():
                wanted = {k: s for k, s in f["slots"].items() if s["kind"] == "consumable" and s["quality"] == "clean" and s["item"] in by_name
                          and not by_name[s["item"]].get("seen_filtered")}
                if f["filter"]["state"] != "on" or not wanted:
                    continue
                img = cv2.imread(str(Path(root) / setup / kind / name))
                if img is None:
                    continue
                at = (0, h - img.shape[0])
                bar = potion_bar.find_bar(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), at, w, h)
                if bar is None or bar.layout != "keyboard":
                    continue
                for spot in bar.slots:
                    row, col = divmod(spot.index, 4)
                    slot = wanted.get(f"{row},{col}")
                    if slot is None:
                        continue
                    x, y, sw, sh = spot.rect
                    crop = img[y - at[1]:y - at[1] + sh, x:x + sw]
                    vec = potions.fingerprint(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB), style="keyboard") if crop.shape[:2] == (sh, sw) else None
                    if vec is not None:
                        groups[slot["item"]].append(vec)
    for name, vecs in sorted(groups.items()):
        print(f"{name:20s} real filtered slots {len(vecs):4d}", "" if len(vecs) >= MIN_SAMPLES else "(too few: left out)")
        if len(vecs) >= MIN_SAMPLES:
            by_name[name]["seen_filtered"] = [[round(float(v), 4) for v in np.mean(vecs, axis=0)]]


def main():
    if sys.argv[1] == "--filtered":
        data = json.loads(TABLE.read_text(encoding="utf-8"))
        filtered_rows(json.loads(Path(sys.argv[2]).read_text()), data)
        if "--real" in sys.argv:
            real_rows(sys.argv[sys.argv.index("--real") + 1], data)
        TABLE.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print("written", TABLE)
        return
    truth = json.loads(Path(sys.argv[1]).read_text())
    args = sys.argv[2:]
    damage = {}
    if "--variants" in args:
        sys.path.insert(0, args[args.index("--variants") + 1])
        from variants import VARIANTS
        damage = {k: VARIANTS[k] for k in DAMAGES}
    rng = np.random.default_rng(1)
    items = defaultdict(list)          # (item, mode, brightness) -> fingerprints
    skills = []                        # (fingerprint, crop)
    for f, slot, crop in slot_pictures(truth):
        if slot["quality"] not in ("clean", "dim"):
            continue
        if slot["kind"] == "consumable" and slot["item"]:
            vec = fingerprint_of(crop)
            if vec is not None:
                items[(slot["item"].replace(" (Alt)", ""), f["mode"], slot["quality"])].append(vec)
        elif slot["kind"] == "skill":
            vec = fingerprint_of(crop)
            if vec is not None:
                skills.append((vec, crop, (f["mode"], slot["quality"])))

    data = json.loads(TABLE.read_text(encoding="utf-8"))
    data["items"] = [i for i in data["items"] if not i["name"].startswith(SKILL_NAME)]
    for i in data["items"]:
        i.pop("seen_controller", None)
    by_name = {i["name"]: i for i in data["items"]}
    for (name, mode, quality), vecs in sorted(items.items()):
        print(f"{name:16s} {mode:8s} {quality:6s} {len(vecs):4d} slots", "" if len(vecs) >= MIN_SAMPLES else "(too few: left out)")
        if len(vecs) >= MIN_SAMPLES and name in by_name:
            by_name[name].setdefault("seen_controller", []).append([round(float(v), 4) for v in np.mean(vecs, axis=0)])

    clusters = []                      # [(first fingerprint, [crops], [(mode, brightness)])]
    for vec, crop, kind in skills:
        for c in clusters:
            if np.abs(c[0] - vec).mean() < SAME_SKILL:
                c[1].append(crop)
                c[2].append(kind)
                break
        else:
            clusters.append((vec, [crop], [kind]))
    n = 0
    for vec, crops, kinds in clusters:
        if len(crops) < MIN_SAMPLES:
            continue
        n += 1
        vecs = [fingerprint_of(c) for c in crops]
        copies = [np.mean([v for v, k in zip(vecs, kinds) if k == kind], axis=0) for kind in sorted(set(kinds))]
        for name, fn in damage.items():
            hurt = [fingerprint_of(fn(c, rng, {})) for c in crops[:: max(1, len(crops) // 6)]]
            hurt = [v for v in hurt if v is not None]
            if hurt:
                copies.append(np.mean(hurt, axis=0))
        data["items"].append({"name": SKILL_NAME + str(n), "item_id": 0, "kind": "skill", "category": "Skill", "price": 0,
                              "unpriced": True, "fingerprint": [round(float(v), 4) for v in copies[0]],
                              "seen_controller": [[round(float(v), 4) for v in c] for c in copies]})
        print(f"{SKILL_NAME}{n}: {len(crops)} slots, {len(copies)} fingerprints")
    if "--icons" in args:
        at = args.index("--icons")
        controller_references(data, json.loads(Path(args[at + 1]).read_text(encoding="utf-8")), args[at + 2])
    TABLE.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("written", TABLE)


if __name__ == "__main__":
    main()
