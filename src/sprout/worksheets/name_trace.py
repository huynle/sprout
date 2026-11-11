"""Name tracing sheet: single-stroke letters with green start dots and stroke-order numbers.

CLI:     python -m sprout.worksheets.name_trace NAME [out.pdf] [--size 88]
Library: make_name_trace(name, size) -> PDF bytes
"""

import argparse
import io
import math
import threading

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def arc(cx, cy, r, a0, a1, n=48):
    """Points along a circle, from angle a0 to a1 in degrees (a1 < a0 = clockwise)."""
    return [
        (
            cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
            cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n)),
        )
        for i in range(n + 1)
    ]


# Single-stroke letters: (width, [strokes]); points are (x, y) as a
# fraction of letter height, drawn in stroke order from the first point.
LETTERS = {
    "E": (0.6, [[(0, 1), (0, 0)], [(0, 1), (0.6, 1)], [(0, 0.5), (0.5, 0.5)], [(0, 0), (0.6, 0)]]),
    "L": (0.55, [[(0, 1), (0, 0)], [(0, 0), (0.55, 0)]]),
    "A": (0.8, [[(0.4, 1), (0, 0)], [(0.4, 1), (0.8, 0)], [(0.16, 0.4), (0.64, 0.4)]]),
    "G": (0.9, [arc(0.45, 0.5, 0.45, 45, 360) + [(0.5, 0.5)]]),
    "a": (0.5, [arc(0.25, 0.25, 0.25, 30, 390), [(0.5, 0.5), (0.5, 0)]]),
    "b": (0.5, [[(0, 1), (0, 0)], arc(0.25, 0.25, 0.25, 180, -180)]),
    "e": (0.5, [[(0, 0.25), (0.5, 0.25)] + arc(0.25, 0.25, 0.25, 0, 320)]),
    "i": (0.0, [[(0, 0.5), (0, 0)], [(0, 0.72)]]),
    "l": (0.0, [[(0, 1), (0, 0)]]),
    "r": (0.42, [[(0, 0.5), (0, 0)], arc(0.22, 0.28, 0.22, 180, 40)]),
    # Capitals: ball-and-stick manuscript, cap height 1.
    "B": (
        0.55,
        [
            [(0, 1), (0, 0)],
            [(0, 1), (0.3, 1)] + arc(0.3, 0.75, 0.25, 90, -90) + [(0, 0.5)],
            [(0, 0.5), (0.3, 0.5)] + arc(0.3, 0.25, 0.25, 90, -90) + [(0, 0)],
        ],
    ),
    "C": (0.85, [arc(0.45, 0.5, 0.45, 45, 315)]),
    "D": (0.7, [[(0, 1), (0, 0)], [(0, 1), (0.2, 1)] + arc(0.2, 0.5, 0.5, 90, -90) + [(0, 0)]]),
    "F": (0.55, [[(0, 1), (0, 0)], [(0, 1), (0.55, 1)], [(0, 0.5), (0.45, 0.5)]]),
    "H": (0.65, [[(0, 1), (0, 0)], [(0.65, 1), (0.65, 0)], [(0, 0.5), (0.65, 0.5)]]),
    "I": (0.4, [[(0.2, 1), (0.2, 0)], [(0, 1), (0.4, 1)], [(0, 0), (0.4, 0)]]),
    "J": (0.5, [[(0.5, 1), (0.5, 0.25)] + arc(0.25, 0.25, 0.25, 0, -180)]),
    "K": (0.6, [[(0, 1), (0, 0)], [(0.6, 1), (0, 0.4)], [(0.2, 0.55), (0.6, 0)]]),
    "M": (0.8, [[(0, 1), (0, 0)], [(0, 1), (0.4, 0.35), (0.8, 1), (0.8, 0)]]),
    "N": (0.65, [[(0, 1), (0, 0)], [(0, 1), (0.65, 0), (0.65, 1)]]),
    "O": (0.9, [arc(0.45, 0.5, 0.45, 90, 450)]),
    "P": (0.55, [[(0, 1), (0, 0)], [(0, 1), (0.3, 1)] + arc(0.3, 0.75, 0.25, 90, -90) + [(0, 0.5)]]),
    "Q": (0.9, [arc(0.45, 0.5, 0.45, 90, 450), [(0.55, 0.25), (0.9, -0.05)]]),
    "R": (
        0.6,
        [
            [(0, 1), (0, 0)],
            [(0, 1), (0.3, 1)] + arc(0.3, 0.75, 0.25, 90, -90) + [(0, 0.5)],
            [(0.25, 0.5), (0.6, 0)],
        ],
    ),
    "S": (0.6, [arc(0.3, 0.75, 0.25, 20, 270) + arc(0.3, 0.25, 0.25, 90, -160)]),
    "T": (0.6, [[(0, 1), (0.6, 1)], [(0.3, 1), (0.3, 0)]]),
    "U": (0.65, [[(0, 1), (0, 0.325)] + arc(0.325, 0.325, 0.325, 180, 360) + [(0.65, 1)]]),
    "V": (0.7, [[(0, 1), (0.35, 0), (0.7, 1)]]),
    "W": (0.9, [[(0, 1), (0.22, 0), (0.45, 0.7), (0.68, 0), (0.9, 1)]]),
    "X": (0.65, [[(0, 1), (0.65, 0)], [(0.65, 1), (0, 0)]]),
    "Y": (0.7, [[(0, 1), (0.35, 0.5)], [(0.7, 1), (0.35, 0.5), (0.35, 0)]]),
    "Z": (0.6, [[(0, 1), (0.6, 1), (0, 0), (0.6, 0)]]),
    # Lowercase: x-height 0.5, ascenders to 1, descenders to -0.25.
    "c": (0.5, [arc(0.25, 0.25, 0.25, 40, 320)]),
    "d": (0.5, [arc(0.25, 0.25, 0.25, 30, 390), [(0.5, 1), (0.5, 0)]]),
    "f": (0.35, [arc(0.27, 0.85, 0.15, 20, 180) + [(0.12, 0)], [(0, 0.5), (0.3, 0.5)]]),
    "g": (0.5, [arc(0.25, 0.25, 0.25, 30, 390), [(0.5, 0.5), (0.5, -0.1)] + arc(0.3, -0.1, 0.2, 0, -170)]),
    "h": (0.5, [[(0, 1), (0, 0)], arc(0.25, 0.25, 0.25, 180, 0) + [(0.5, 0)]]),
    "j": (0.25, [[(0.25, 0.5), (0.25, -0.1)] + arc(0.08, -0.1, 0.17, 0, -180), [(0.25, 0.72)]]),
    "k": (0.45, [[(0, 1), (0, 0)], [(0.45, 0.5), (0, 0.2)], [(0.12, 0.27), (0.45, 0)]]),
    "m": (
        0.8,
        [
            [(0, 0.5), (0, 0)],
            arc(0.2, 0.3, 0.2, 180, 0) + [(0.4, 0)],
            arc(0.6, 0.3, 0.2, 180, 0) + [(0.8, 0)],
        ],
    ),
    "n": (0.5, [[(0, 0.5), (0, 0)], arc(0.25, 0.25, 0.25, 180, 0) + [(0.5, 0)]]),
    "o": (0.5, [arc(0.25, 0.25, 0.25, 90, 450)]),
    "p": (0.5, [[(0, 0.5), (0, -0.25)], arc(0.25, 0.25, 0.25, 180, -180)]),
    "q": (0.5, [arc(0.25, 0.25, 0.25, 30, 390), [(0.5, 0.5), (0.5, -0.25)]]),
    "s": (0.4, [arc(0.2, 0.375, 0.125, 20, 270) + arc(0.2, 0.125, 0.125, 90, -160)]),
    "t": (0.35, [[(0.15, 0.85), (0.15, 0)], [(0, 0.5), (0.35, 0.5)]]),
    "u": (
        0.5,
        [[(0, 0.5), (0, 0.25)] + arc(0.25, 0.25, 0.25, 180, 360) + [(0.5, 0.5)], [(0.5, 0.5), (0.5, 0)]],
    ),
    "v": (0.5, [[(0, 0.5), (0.25, 0), (0.5, 0.5)]]),
    "w": (0.7, [[(0, 0.5), (0.17, 0), (0.35, 0.4), (0.53, 0), (0.7, 0.5)]]),
    "x": (0.45, [[(0, 0.5), (0.45, 0)], [(0.45, 0.5), (0, 0)]]),
    "y": (0.5, [[(0, 0.5), (0.25, 0)], [(0.5, 0.5), (0.12, -0.25)]]),
    "z": (0.45, [[(0, 0.5), (0.45, 0.5), (0, 0), (0.45, 0)]]),
    " ": (0.35, []),
}

H = 88  # letter height in points (set from --size)
GREEN = (0.1, 0.65, 0.2)


def gap(name):
    return 0.4 if name.isupper() else 0.36


def name_width(name):
    return sum(LETTERS[ch][0] for ch in name) * H + gap(name) * H * (len(name) - 1)


def guide_lines(c, x0, x1, base):
    c.setDash()
    c.setStrokeColorRGB(0.35, 0.55, 0.85)
    c.setLineWidth(1)
    c.line(x0, base + H, x1, base + H)
    c.setLineWidth(2)
    c.line(x0, base, x1, base)
    c.setDash(6, 5)
    c.setLineWidth(1)
    c.setStrokeColorRGB(0.6, 0.75, 0.95)
    c.line(x0, base + H / 2, x1, base + H / 2)
    c.setDash()


def draw_name(c, name, x, base, style):
    k = H / 88
    for ch in name:
        w, strokes = LETTERS[ch]
        labels = {}
        for n, stroke in enumerate(strokes, 1):
            labels.setdefault(stroke[0], []).append(str(n))
        for n, stroke in enumerate(strokes, 1):
            pts = [(x + px * H, base + py * H) for px, py in stroke]
            if len(pts) == 1:
                gray = 0 if style == "example" else 0.55
                c.setFillColorRGB(gray, gray, gray)
                c.circle(pts[0][0], pts[0][1], max(2.5, 5 * k), stroke=0, fill=1)
                continue
            if style == "example":
                c.setDash()
                c.setStrokeColorRGB(0, 0, 0)
                c.setLineWidth(max(2.5, 7 * k))
            else:
                c.setDash(max(1.5, 3 * k), max(3.5, 9 * k))
                c.setStrokeColorRGB(0.55, 0.55, 0.55)
                c.setLineWidth(max(2, 5 * k))
            c.setLineCap(1)
            c.setLineJoin(1)
            p = c.beginPath()
            p.moveTo(*pts[0])
            for pt in pts[1:]:
                p.lineTo(*pt)
            c.drawPath(p, stroke=1, fill=0)

            sx, sy = pts[0]
            c.setFillColorRGB(*GREEN)
            c.circle(sx, sy, max(2, 5 * k), stroke=0, fill=1)
            nums = labels[stroke[0]]
            if style == "example" and nums[0] == str(n) and len(strokes) > 1:
                fs = max(6, 11 * k)
                c.setFont("Helvetica-Bold", fs)
                text = " ".join(nums)
                if sy >= base + (H / 2 if ch.islower() else H) - 1:
                    tx = sx - c.stringWidth(text, "Helvetica-Bold", fs) / 2
                    c.drawString(tx, sy + 0.8 * fs, text)
                else:
                    c.drawRightString(sx - 0.8 * fs, sy - 0.35 * fs, text)
        x += w * H + gap(name) * H


_LOCK = threading.Lock()


def missing_letters(name):
    """Letters in name that have no single-stroke drawing yet."""
    return sorted({ch for ch in name if ch not in LETTERS})


def make_name_trace(name, size=88):
    """Return the tracing sheet as PDF bytes. size = letter height in points (88 = big)."""
    global H
    if not name:
        raise ValueError("name is empty")
    missing = missing_letters(name)
    if missing:
        raise ValueError("letters not defined yet: " + " ".join(missing))
    if not 20 <= size <= 120:
        raise ValueError("size must be between 20 and 120 points")
    if len(name) > 20:
        raise ValueError("names longer than 20 characters don't fit on a line")
    with _LOCK:
        H = size
        usable = letter[0] - 2 * 50 - 20
        while name_width(name) > usable and H > 20:
            H *= 0.95
        buf = io.BytesIO()
        _draw_sheet(canvas.Canvas(buf, pagesize=letter), name)
        return buf.getvalue()


def _draw_sheet(c, name):
    pw, ph = letter
    c.setFont("Helvetica-Bold", 26)
    c.setFillColorRGB(0, 0, 0)
    c.drawCentredString(pw / 2, ph - 58, "Trace my name: " + name)
    c.setFont("Helvetica", 12)
    c.drawCentredString(pw / 2, ph - 80, "Start at the green dot and follow the dots.")

    margin = 50
    row_h = 1.5 * H if H >= 60 else 2.0 * H
    width = name_width(name)
    sep = max(0.8 * H, 30)
    per_row = max(1, int((pw - 2 * margin - 20 + sep) // (width + sep)))
    block = per_row * width + (per_row - 1) * sep
    x0 = (pw - block) / 2
    base = ph - 110 - H
    rows = int((base - 36) // row_h) + 1
    for r in range(rows):
        guide_lines(c, margin, pw - margin, base)
        if r < rows - 1:
            for i in range(per_row):
                style = "example" if r == 0 and i == 0 else "trace"
                draw_name(c, name, x0 + i * (width + sep), base, style)
        base -= row_h

    c.showPage()
    c.save()


def main():
    ap = argparse.ArgumentParser(description="Name tracing worksheet")
    ap.add_argument("name", help="exact case is kept, e.g. SAM or Sam")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--size", type=float, default=88, help="letter height in points (88 = big, 40 = small)")
    args = ap.parse_args()
    try:
        pdf = make_name_trace(args.name, args.size)
    except ValueError as e:
        raise SystemExit(str(e))
    out = args.out or "trace_" + args.name.lower() + ("" if args.size == 88 else "_small") + ".pdf"
    with open(out, "wb") as f:
        f.write(pdf)
    print(out)


if __name__ == "__main__":
    main()
