import json
import pathlib

import pytest

from sprout.worksheets import math_drill
from sprout.worksheets import name_trace as trace_name

SEED2026 = pathlib.Path(__file__).parent / "fixtures" / "math_drill_seed2026.json"


def test_seed_2026_reproduces_printed_sheet():
    expected = [tuple(p) for p in json.loads(SEED2026.read_text())]
    assert math_drill.make_problems(60, 2026) == expected


def test_math_drill_pdf_and_determinism():
    a = math_drill.make_problems(60, 7)
    assert a == math_drill.make_problems(60, 7)
    pdf = math_drill.make_math_drill(7)
    assert pdf.startswith(b"%PDF-")
    assert pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page ") >= 1


@pytest.mark.parametrize("ops", ["add", "sub"])
def test_ops_only(ops):
    sym = "+" if ops == "add" else "-"
    assert {p[1] for p in math_drill.make_problems(60, 3, ops=ops)} == {sym}


@pytest.mark.parametrize("seed", range(20))
def test_two_digit_without_regrouping(seed):
    for a, op, b, ans in math_drill.make_problems(60, seed, digits=2):
        assert 10 <= a <= 99 and 10 <= b <= 99
        if op == "+":
            assert a % 10 + b % 10 < 10 and ans < 100 and ans == a + b
        else:
            assert a % 10 >= b % 10 and ans == a - b >= 0


def test_two_digit_with_regrouping_happens():
    probs = math_drill.make_problems(60, 1, ops="add", digits=2, regroup=True)
    assert any(a % 10 + b % 10 >= 10 for a, _, b, _ in probs)


def test_bad_options():
    with pytest.raises(ValueError):
        math_drill.make_math_drill(1, count=17)
    with pytest.raises(ValueError):
        math_drill.make_problems(10, 1, ops="mul")


def test_answer_key_optional():
    with_key = math_drill.make_math_drill(5)
    without = math_drill.make_math_drill(5, answer_key=False)
    assert len(without) < len(with_key)


def test_name_trace():
    assert trace_name.make_name_trace("SAM").startswith(b"%PDF-")
    assert trace_name.make_name_trace("Samantha", 36).startswith(b"%PDF-")
    assert trace_name.missing_letters("Zoë 2") == ["2", "ë"]
    with pytest.raises(ValueError, match="not defined"):
        trace_name.make_name_trace("Zoë")
    with pytest.raises(ValueError):
        trace_name.make_name_trace("SAM", 500)


def test_every_ascii_letter_is_defined():
    import string

    assert trace_name.missing_letters(string.ascii_letters + " ") == []


def test_long_names_shrink_to_fit():
    assert trace_name.make_name_trace("Maximilian Rose", 88).startswith(b"%PDF-")
    with pytest.raises(ValueError, match="20"):
        trace_name.make_name_trace("A" * 21)
