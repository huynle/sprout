"""Big two-digit addition as HTML, rendered to PDF by Studio.

12 (or 8 / 16) large problems in a grid, optional carrying, optional answer key on page 2. The page
has an empty "Name" line at a fixed place (``NAME_LINE``) where Sprout stamps the child's name after
rendering, so the name never leaves Sprout. Only integers go into the HTML.
"""

from __future__ import annotations

from sprout.worksheets.math_drill import make_problems

# The name line, in inches from the page's top-left corner (Letter, 0.5 in margins; see CSS below).
NAME_LINE = {"x": 6.1, "y": 0.9, "width": 1.9}

CSS = """
@page { size: letter; margin: 0.5in; }
* { box-sizing: border-box; }
body { margin: 0; font-family: 'DejaVu Sans', Arial, sans-serif; color: #1d2733; }
.namebox { position: absolute; top: 0; right: 0; width: 2.6in; height: 0.4in; display: flex;
  align-items: flex-end; font-size: 16px; }
.namebox .label { width: 0.7in; }
.namebox .line { flex: 1; border-bottom: 2px solid #1d2733; height: 100%; }
header { height: 0.62in; border-bottom: 3px solid #2a7ab0; margin-bottom: 0.12in; }
h1 { font-size: 28px; margin: 0; color: #2a7ab0; max-width: 4.6in; line-height: 0.6in; }
.tip { font-size: 15px; color: #555; margin: 0 0 0.25in; }
.grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.38in 0.28in; }
.p { width: 1.15in; margin: 0 auto; text-align: right; font-size: 40px; line-height: 1.15;
  font-variant-numeric: tabular-nums; }
.op { float: left; color: #2a7ab0; }
.rule { border-top: 3px solid #1d2733; margin: 4px 0 6px; }
.ans { min-height: 46px; }
.key { color: #b03a2a; }
.page2 { break-before: page; }
footer { margin-top: 0.3in; font-size: 12px; color: #999; text-align: center; }
"""


def _card(a: int, b: int, show: bool) -> str:
    ans = str(a + b) if show else "&nbsp;"
    cls = "ans key" if show else "ans"
    return (
        f"<div class='p'><div>{int(a)}</div><div><span class='op'>+</span>{int(b)}</div>"
        f"<div class='rule'></div><div class='{cls}'>{ans}</div></div>"
    )


def make_html(seed: int, count: int = 12, regroup: bool = False, answer_key: bool = True) -> str:
    problems = [(a, b) for a, _, b, _ in make_problems(count, seed, "add", 2, regroup)]
    tip = "Add the ones first, then the tens." + ("" if regroup else " No carrying on this page!")
    page1 = "".join(_card(a, b, False) for a, b in problems)
    key = ""
    if answer_key:
        cards = "".join(_card(a, b, True) for a, b in problems)
        key = (
            "<section class='page2'><header><h1>Answer key</h1></header>"
            f"<p class='tip'>&nbsp;</p><div class='grid'>{cards}</div>"
            f"<footer>seed {int(seed)}</footer></section>"
        )
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Big addition</title>"
        f"<style>{CSS}</style></head><body>"
        "<div class='namebox'><span class='label'>Name:</span><span class='line'></span></div>"
        "<header><h1>Two-Digit Addition</h1></header>"
        f"<p class='tip'>{tip}</p><div class='grid'>{page1}</div>"
        f"<footer>seed {int(seed)}</footer>{key}</body></html>"
    )
