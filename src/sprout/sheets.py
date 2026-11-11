"""Worksheet kinds. Each kind declares its fields once; the same spec drives the web form,
the validation of AI-produced parameters and the call into the shared generator at the repo root.
"""

from __future__ import annotations

import io
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sprout.worksheets import math_drill
from sprout.worksheets import name_trace as trace_name


class InvalidParams(ValueError):
    pass


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    type: str  # choice | bool | int | text
    default: Any = None
    choices: tuple = ()  # (value, label) pairs for choice
    help: str = ""
    min: int | None = None
    max: int | None = None
    max_len: int = 40


@dataclass(frozen=True)
class Kind:
    id: str
    label: str
    description: str
    fields: tuple[Field, ...]
    render: Callable[[dict], tuple[str, bytes]]
    ages: str = ""
    extra: dict = field(default_factory=dict)

    def validate(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Coerce and check raw values (form strings or JSON); unknown keys are refused."""
        unknown = set(raw) - {f.name for f in self.fields}
        if unknown:
            raise InvalidParams(f"unknown fields: {', '.join(sorted(unknown))}")
        out: dict[str, Any] = {}
        for f in self.fields:
            v = raw.get(f.name)
            if v in (None, ""):
                if f.type == "bool" and f.name in raw:
                    v = False
                elif f.type == "text" and f.default is None:
                    raise InvalidParams(f"{f.label}: required")
                else:
                    out[f.name] = f.default
                    continue
            if f.type == "choice":
                allowed = {str(c[0]): c[0] for c in f.choices}
                if str(v) not in allowed:
                    raise InvalidParams(f"{f.label}: choose one of {', '.join(allowed)}")
                out[f.name] = allowed[str(v)]
            elif f.type == "bool":
                out[f.name] = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "on", "yes")
            elif f.type == "int":
                try:
                    n = int(v)
                except (TypeError, ValueError):
                    raise InvalidParams(f"{f.label}: must be a whole number") from None
                if (f.min is not None and n < f.min) or (f.max is not None and n > f.max):
                    raise InvalidParams(f"{f.label}: must be between {f.min} and {f.max}")
                out[f.name] = n
            elif f.type == "text":
                s = str(v).strip()
                if not s or len(s) > f.max_len or any(ord(ch) < 32 for ch in s):
                    raise InvalidParams(f"{f.label}: 1 to {f.max_len} plain characters")
                out[f.name] = s
        return out

    def json_schema(self) -> dict:
        props = {}
        for f in self.fields:
            if f.type == "choice":
                props[f.name] = {"enum": [c[0] for c in f.choices], "description": f.help or f.label}
            elif f.type == "bool":
                props[f.name] = {"type": "boolean", "description": f.help or f.label}
            elif f.type == "int":
                props[f.name] = {
                    "type": "integer",
                    "minimum": f.min,
                    "maximum": f.max,
                    "description": f.help or f.label,
                }
            else:
                props[f.name] = {"type": "string", "maxLength": f.max_len, "description": f.help or f.label}
        return {"type": "object", "properties": props, "additionalProperties": False}


def _render_math(p: dict) -> tuple[str, bytes]:
    seed = p["seed"] or random.randint(1, 10**6)
    p["seed"] = seed
    pdf = math_drill.make_math_drill(seed, p["ops"], p["digits"], p["regroup"], p["count"], p["answer_key"])
    digits = "2-digit" if p["digits"] == 2 else "1-digit"
    regroup = " with carrying" if p["digits"] == 2 and p["regroup"] else ""
    return f"{math_drill.title_for(p['ops'])}: {p['count']} {digits}{regroup}", pdf


def _render_trace(p: dict) -> tuple[str, bytes]:
    try:
        pdf = trace_name.make_name_trace(p["name"], p["size"])
    except ValueError as e:
        raise InvalidParams(str(e)) from None
    size = {88: "big", 60: "medium", 36: "small", 28: "smaller"}.get(p["size"], f"{p['size']}pt")
    return f"Trace my name: {p['name']} ({size})", pdf


KINDS: dict[str, Kind] = {
    "math_drill": Kind(
        id="math_drill",
        label="Math drill",
        description="Vertical addition and subtraction with an answer key on page 2.",
        ages="5+",
        fields=(
            Field(
                "ops",
                "Problems",
                "choice",
                "mixed",
                (
                    ("mixed", "Addition and subtraction"),
                    ("add", "Addition only"),
                    ("sub", "Subtraction only"),
                ),
            ),
            Field("digits", "Numbers", "choice", 1, ((1, "1 digit (up to 18)"), (2, "2 digits"))),
            Field("regroup", "Carrying / borrowing (2 digits only)", "bool", False),
            Field(
                "count",
                "How many problems",
                "choice",
                60,
                ((20, "20 (big print)"), (30, "30 (big print)"), (40, "40"), (60, "60")),
            ),
            Field("answer_key", "Add answer key page", "bool", True),
            Field(
                "seed",
                "Seed (leave empty for new problems)",
                "int",
                None,
                min=1,
                max=10**9,
                help="same seed = same problems; omit for new ones",
            ),
        ),
        render=_render_math,
    ),
    "name_trace": Kind(
        id="name_trace",
        label="Name tracing",
        description="Trace a name with single-stroke letters, green start dots and stroke order.",
        ages="3-6",
        fields=(
            Field(
                "name",
                "Name or word (exact case)",
                "text",
                None,
                help="letters defined so far: " + " ".join(sorted(trace_name.LETTERS)),
                max_len=20,
            ),
            Field(
                "size",
                "Letter size",
                "choice",
                88,
                ((88, "Big"), (60, "Medium"), (36, "Small"), (28, "Smaller")),
            ),
        ),
        render=_render_trace,
        extra={"letters": "".join(sorted(trace_name.LETTERS))},
    ),
}


def preview_png(pdf: bytes, page: int = 0, width: int = 900) -> bytes:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf)
    try:
        pg = doc[min(page, len(doc) - 1)]
        scale = width / pg.get_width()
        img = pg.render(scale=scale).to_pil()
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        return buf.getvalue()
    finally:
        doc.close()


def page_count(pdf: bytes) -> int:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf)
    try:
        return len(doc)
    finally:
        doc.close()
