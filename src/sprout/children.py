"""Children: ages are always computed from the birth date, never stored."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Age:
    years: int
    months: int

    def __str__(self) -> str:
        if self.years == 0:
            return f"{self.months} mo"
        return f"{self.years} y {self.months} m"


def age_on(born: date, today: date) -> Age:
    months = (today.year - born.year) * 12 + today.month - born.month - (today.day < born.day)
    return Age(months // 12, months % 12)


def next_birthday(born: date, today: date) -> tuple[date, int]:
    """(date, days until it). Feb 29 birthdays fall on Mar 1 in other years."""

    def on(year: int) -> date:
        try:
            return born.replace(year=year)
        except ValueError:
            return date(year, 3, 1)

    nxt = on(today.year)
    if nxt < today:
        nxt = on(today.year + 1)
    return nxt, (nxt - today).days
