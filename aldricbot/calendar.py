"""WoW in-game calendar awareness for AldricBot.

Computes active WotLK seasonal events, Darkmoon Faire, and the current
season so Aldric can reference them naturally in conversation.
"""

from __future__ import annotations

from datetime import date, timedelta

# ── Chinese New Year lookup table (2025–2035) ────────────────────

CHINESE_NEW_YEAR: dict[int, date] = {
    2025: date(2025, 1, 29),
    2026: date(2026, 2, 17),
    2027: date(2027, 2, 6),
    2028: date(2028, 1, 26),
    2029: date(2029, 2, 13),
    2030: date(2030, 2, 3),
    2031: date(2031, 1, 23),
    2032: date(2032, 2, 11),
    2033: date(2033, 1, 31),
    2034: date(2034, 2, 19),
    2035: date(2035, 2, 8),
}

# ── Easter computation (Gauss/Meeus) ─────────────────────────────


def _easter(year: int) -> date:
    """Compute Easter Sunday for a given year using the Meeus algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


# ── Thanksgiving (4th Thursday of November) ──────────────────────


def _thanksgiving(year: int) -> date:
    """Compute US Thanksgiving (4th Thursday of November)."""
    # Find the first Thursday of November
    nov1 = date(year, 11, 1)
    # weekday(): Monday=0 .. Sunday=6; Thursday=3
    days_until_thu = (3 - nov1.weekday()) % 7
    first_thu = nov1 + timedelta(days=days_until_thu)
    return first_thu + timedelta(weeks=3)


# ── Event definitions ────────────────────────────────────────────

# Each event has: name, lore_name (Aldric's name for it), flavor text,
# and a callable that returns (start_date, end_date) for a given year.


def _fixed_event(start_month: int, start_day: int, end_month: int, end_day: int):
    """Build a date-range function for fixed-date events."""

    def _range(year: int) -> tuple[date, date]:
        start = date(year, start_month, start_day)
        if end_month < start_month:
            end = date(year + 1, end_month, end_day)
        else:
            end = date(year, end_month, end_day)
        return start, end

    return _range


EVENTS: list[dict] = [
    # ── Fixed-date events ──
    {
        "name": "Midsummer Fire Festival",
        "lore_name": "the Midsummer Fire Festival",
        "flavor": "Bonfires blaze across the land — the fires of midsummer warm even old bones.",
        "range": _fixed_event(6, 21, 7, 5),
    },
    {
        "name": "Brewfest",
        "lore_name": "Brewfest",
        "flavor": "The kegs are flowing and the ram races are on — Brewfest is upon us.",
        "range": _fixed_event(9, 20, 10, 6),
    },
    {
        "name": "Hallow's End",
        "lore_name": "Hallow's End",
        "flavor": "The Wickerman burns and the Headless Horseman rides — Hallow's End is here.",
        "range": _fixed_event(10, 18, 11, 1),
    },
    {
        "name": "Day of the Dead",
        "lore_name": "the Day of the Dead",
        "flavor": "The spirits walk among us — we honor those who have fallen.",
        "range": _fixed_event(11, 1, 11, 3),
    },
    {
        "name": "Feast of Winter Veil",
        "lore_name": "the Feast of Winter Veil",
        "flavor": "Gifts and merriment fill the cities — the Feast of Winter Veil is underway.",
        "range": _fixed_event(12, 15, 1, 2),
    },
    # ── Variable-date events ──
    {
        "name": "Lunar Festival",
        "lore_name": "the Lunar Festival",
        "flavor": "The elders gather and lanterns light the sky — the Lunar Festival has begun.",
        "range": lambda year: (
            CHINESE_NEW_YEAR[year] - timedelta(days=7),
            CHINESE_NEW_YEAR[year] - timedelta(days=7) + timedelta(days=13),
        )
        if year in CHINESE_NEW_YEAR
        else None,
    },
    {
        "name": "Love is in the Air",
        "lore_name": "Love is in the Air",
        "flavor": "Perfume and adoration fill the air — even old soldiers are not immune.",
        "range": lambda year: (date(year, 2, 10), date(year, 2, 23)),
    },
    {
        "name": "Noblegarden",
        "lore_name": "Noblegarden",
        "flavor": "Painted eggs and spring blossoms — Noblegarden brings renewal to the land.",
        "range": lambda year: (
            _easter(year) + timedelta(days=1),
            _easter(year) + timedelta(days=7),
        ),
    },
    {
        "name": "Children's Week",
        "lore_name": "Children's Week",
        "flavor": "The orphans of war deserve a week of wonder — Children's Week is here.",
        "range": lambda year: (
            _easter(year) + timedelta(days=1 + 7 + 7),
            _easter(year) + timedelta(days=1 + 7 + 7 + 6),
        ),
    },
    {
        "name": "Pilgrim's Bounty",
        "lore_name": "Pilgrim's Bounty",
        "flavor": "The harvest tables are set — Pilgrim's Bounty calls us to give thanks.",
        "range": lambda year: (
            _monday_before(_thanksgiving(year)),
            _monday_before(_thanksgiving(year)) + timedelta(days=6),
        ),
    },
    # ── Monthly recurring ──
    {
        "name": "Darkmoon Faire",
        "lore_name": "the Darkmoon Faire",
        "flavor": "The Darkmoon Faire has come to town — curiosities and games await.",
        "range": "darkmoon",
    },
]


def _monday_before(d: date) -> date:
    """Return the Monday on or before the given date."""
    return d - timedelta(days=d.weekday())


def _darkmoon_range(year: int, month: int) -> tuple[date, date]:
    """Compute Darkmoon Faire range: first Friday of the month, Fri–Sun."""
    first_of_month = date(year, month, 1)
    days_until_fri = (4 - first_of_month.weekday()) % 7
    first_friday = first_of_month + timedelta(days=days_until_fri)
    return first_friday, first_friday + timedelta(days=2)


# ── Seasons ──────────────────────────────────────────────────────

SEASONS = [
    {
        "name": "Winter",
        "flavor": "The cold winds blow across Azeroth.",
        "start": (12, 21),
        "end": (3, 19),
    },
    {
        "name": "Spring",
        "flavor": "New growth stirs across the land.",
        "start": (3, 20),
        "end": (6, 20),
    },
    {
        "name": "Summer",
        "flavor": "The sun beats down on Azeroth.",
        "start": (6, 21),
        "end": (9, 21),
    },
    {
        "name": "Autumn",
        "flavor": "The leaves turn and the harvest calls.",
        "start": (9, 22),
        "end": (12, 20),
    },
]


def get_season(d: date) -> dict:
    """Return the current season dict for the given date."""
    md = (d.month, d.day)
    for season in SEASONS:
        start = season["start"]
        end = season["end"]
        if start > end:
            # Wraps around year boundary (Winter)
            if md >= start or md <= end:
                return season
        else:
            if start <= md <= end:
                return season
    return SEASONS[0]  # fallback to Winter


# ── Public API ───────────────────────────────────────────────────


def get_active_events(d: date) -> list[dict]:
    """Return a list of currently active event dicts."""
    active = []
    for event in EVENTS:
        range_fn = event["range"]
        if range_fn == "darkmoon":
            start, end = _darkmoon_range(d.year, d.month)
            if start <= d <= end:
                active.append(event)
        elif callable(range_fn):
            result = range_fn(d.year)
            if result is None:
                continue
            start, end = result
            if start <= d <= end:
                active.append(event)
            # For year-boundary events, also check previous year's range
            prev = range_fn(d.year - 1)
            if prev and prev[0] <= d <= prev[1] and event not in active:
                active.append(event)
    return active


def _get_upcoming_events(d: date, within_days: int = 14) -> list[tuple[dict, int]]:
    """Return events starting within the next `within_days` days.

    Returns list of (event_dict, days_until_start) tuples.
    """
    upcoming = []
    horizon = d + timedelta(days=within_days)
    for event in EVENTS:
        range_fn = event["range"]
        if range_fn == "darkmoon":
            # Check current and next month
            start, _ = _darkmoon_range(d.year, d.month)
            if d < start <= horizon:
                upcoming.append((event, (start - d).days))
                continue
            # Next month
            if d.month == 12:
                nm_year, nm_month = d.year + 1, 1
            else:
                nm_year, nm_month = d.year, d.month + 1
            start, _ = _darkmoon_range(nm_year, nm_month)
            if d < start <= horizon:
                upcoming.append((event, (start - d).days))
        elif callable(range_fn):
            result = range_fn(d.year)
            if result is None:
                continue
            start, _ = result
            if d < start <= horizon:
                upcoming.append((event, (start - d).days))
            # Also check next year for events near year boundary
            next_result = range_fn(d.year + 1)
            if next_result:
                next_start, _ = next_result
                if d < next_start <= horizon:
                    upcoming.append((event, (next_start - d).days))
    return upcoming


def get_calendar_context(d: date) -> str:
    """Build the complete calendar context string for prompt injection."""
    season = get_season(d)
    lines = [f"Current season: {season['name']}. {season['flavor']}"]

    active = get_active_events(d)
    if active:
        event_names = [e["flavor"] for e in active]
        lines.append(f"Active events: {' '.join(event_names)}")

    upcoming = _get_upcoming_events(d)
    # Filter out events that are already active
    active_names = {e["name"] for e in active}
    upcoming = [(e, days) for e, days in upcoming if e["name"] not in active_names]
    if upcoming:
        for event, days in upcoming:
            if days == 1:
                lines.append(f"Upcoming: {event['lore_name']} begins tomorrow.")
            elif days <= 7:
                lines.append(f"Upcoming: {event['lore_name']} begins in {days} days.")
            else:
                weeks = round(days / 7)
                label = "1 week" if weeks == 1 else f"{weeks} weeks"
                lines.append(
                    f"Upcoming: {event['lore_name']} begins in approximately {label}."
                )

    return "\n".join(lines)
