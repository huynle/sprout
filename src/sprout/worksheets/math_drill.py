"""Vertical addition and subtraction drill, with an answer key on page 2.

CLI:     python -m sprout.worksheets.math_drill [seed] [out.pdf] [--ops mixed|add|sub] [--digits 1|2] [--regroup] [--count N]
Library: make_math_drill(seed, ...) -> PDF bytes

The defaults are mixed, 1 digit, 60 problems. A seed always gives the same problems.
"""

import argparse
import io
import random

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

OPS = ("mixed", "add", "sub")
COUNTS = (20, 30, 40, 60)
FONT = "Helvetica"


def _one_digit(rng, op):
    if op == "+":
        a, b = rng.randint(1, 9), rng.randint(1, 9)
        return (a, "+", b, a + b)
    a = rng.randint(1, 18)
    b = rng.randint(0, min(a, 9))
    return (a, "-", b, a - b)


def _two_digit(rng, op, regroup):
    while True:
        a, b = rng.randint(10, 99), rng.randint(10, 99)
        if op == "+":
            if a + b > 198 or (not regroup and (a % 10 + b % 10 >= 10 or a + b >= 100)):
                continue
            return (a, "+", b, a + b)
        if b > a:
            a, b = b, a
        if not regroup and a % 10 < b % 10:
            continue
        return (a, "-", b, a - b)


def make_problems(n, seed, ops="mixed", digits=1, regroup=False):
    if ops not in OPS:
        raise ValueError(f"ops must be one of {OPS}")
    if digits not in (1, 2):
        raise ValueError("digits must be 1 or 2")
    rng = random.Random(seed)
    problems = []
    while len(problems) < n:
        if ops == "mixed":
            op = "+" if rng.random() < 0.5 else "-"
        else:
            op = "+" if ops == "add" else "-"
        p = _one_digit(rng, op) if digits == 1 else _two_digit(rng, op, regroup)
        if problems and problems[-1] == p:
            continue
        problems.append(p)
    return problems


def title_for(ops):
    return {
        "mixed": "Addition & Subtraction Practice",
        "add": "Addition Practice",
        "sub": "Subtraction Practice",
    }[ops]


def draw_page(c, problems, title, show_answers):
    n = len(problems)
    cols = 6 if n > 30 else 5
    rows = -(-n // cols)
    size = 20 if n > 30 else 26
    w, h = letter
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(w / 2, h - 50, title)
    c.setFont("Helvetica", 12)
    c.drawString(54, h - 78, "Name: ______________________")
    c.drawRightString(w - 54, h - 78, f"Date: ____________   Score: ____ / {n}")

    left, top = 54, h - 120
    col_w = (w - 2 * left) / cols
    row_h = (top - 40) / rows
    for i, (a, op, b, ans) in enumerate(problems):
        r, col = divmod(i, cols)
        x_right = left + col * col_w + col_w * 0.7
        y = top - r * row_h
        c.setFont(FONT, size)
        c.drawRightString(x_right, y, str(a))
        c.drawRightString(x_right, y - size - 2, str(b))
        c.drawString(x_right - 2.6 * size, y - size - 2, op)
        line_y = y - size - 9
        c.setLineWidth(1.5)
        c.line(x_right - 2.7 * size, line_y, x_right + 2, line_y)
        if show_answers:
            c.setFillColorRGB(0.8, 0, 0)
            c.drawRightString(x_right, line_y - size - 2, str(ans))
            c.setFillColorRGB(0, 0, 0)
    c.showPage()


def make_math_drill(seed, ops="mixed", digits=1, regroup=False, count=60, answer_key=True):
    """Return the worksheet as PDF bytes (page 1 problems, page 2 answer key if answer_key)."""
    if count not in COUNTS:
        raise ValueError(f"count must be one of {COUNTS}")
    problems = make_problems(count, seed, ops, digits, regroup)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    title = title_for(ops)
    draw_page(c, problems, title, False)
    if answer_key:
        draw_page(c, problems, title + " - Answer Key", True)
    c.save()
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser(description="Vertical addition/subtraction drill with answer key")
    ap.add_argument("seed", nargs="?", type=int, help="same seed = same problems (default: random)")
    ap.add_argument("out", nargs="?", default="math_drill.pdf")
    ap.add_argument("--ops", choices=OPS, default="mixed")
    ap.add_argument("--digits", type=int, choices=(1, 2), default=1)
    ap.add_argument("--regroup", action="store_true", help="two-digit only: allow carrying/borrowing")
    ap.add_argument("--count", type=int, choices=COUNTS, default=60)
    args = ap.parse_args()
    seed = args.seed if args.seed is not None else random.randint(1, 10**6)
    with open(args.out, "wb") as f:
        f.write(make_math_drill(seed, args.ops, args.digits, args.regroup, args.count))
    print(args.out, "seed", seed)


if __name__ == "__main__":
    main()
