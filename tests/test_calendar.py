"""Tests for aldricbot.calendar — event scheduling and season logic."""

from datetime import date

from aldricbot.calendar import (
    _darkmoon_range,
    _easter,
    _thanksgiving,
    get_active_events,
    get_calendar_context,
    get_season,
)


# ── Easter computation ───────────────────────────────────────────


class TestEaster:
    def test_known_dates(self):
        assert _easter(2025) == date(2025, 4, 20)
        assert _easter(2026) == date(2026, 4, 5)
        assert _easter(2027) == date(2027, 3, 28)
        assert _easter(2028) == date(2028, 4, 16)
        assert _easter(2030) == date(2030, 4, 21)


# ── Thanksgiving computation ────────────────────────────────────


class TestThanksgiving:
    def test_known_dates(self):
        assert _thanksgiving(2025) == date(2025, 11, 27)
        assert _thanksgiving(2026) == date(2026, 11, 26)
        assert _thanksgiving(2027) == date(2027, 11, 25)

    def test_always_thursday(self):
        for year in range(2025, 2036):
            assert _thanksgiving(year).weekday() == 3  # Thursday


# ── Darkmoon Faire ──────────────────────────────────────────────


class TestDarkmoonFaire:
    def test_first_friday_of_month(self):
        start, end = _darkmoon_range(2026, 3)
        assert start == date(2026, 3, 6)  # First Friday of March 2026
        assert end == date(2026, 3, 8)    # Sunday
        assert start.weekday() == 4       # Friday

    def test_active_on_friday(self):
        active = get_active_events(date(2026, 3, 6))
        names = [e["name"] for e in active]
        assert "Darkmoon Faire" in names

    def test_active_on_sunday(self):
        active = get_active_events(date(2026, 3, 8))
        names = [e["name"] for e in active]
        assert "Darkmoon Faire" in names

    def test_inactive_on_thursday(self):
        active = get_active_events(date(2026, 3, 5))
        names = [e["name"] for e in active]
        assert "Darkmoon Faire" not in names

    def test_inactive_on_monday(self):
        active = get_active_events(date(2026, 3, 9))
        names = [e["name"] for e in active]
        assert "Darkmoon Faire" not in names


# ── Fixed-date event boundaries ──────────────────────────────────


class TestFixedDateEvents:
    def test_brewfest_start(self):
        active = get_active_events(date(2026, 9, 20))
        names = [e["name"] for e in active]
        assert "Brewfest" in names

    def test_brewfest_end(self):
        active = get_active_events(date(2026, 10, 6))
        names = [e["name"] for e in active]
        assert "Brewfest" in names

    def test_brewfest_before(self):
        active = get_active_events(date(2026, 9, 19))
        names = [e["name"] for e in active]
        assert "Brewfest" not in names

    def test_brewfest_after(self):
        active = get_active_events(date(2026, 10, 7))
        names = [e["name"] for e in active]
        assert "Brewfest" not in names

    def test_hallows_end(self):
        active = get_active_events(date(2026, 10, 25))
        names = [e["name"] for e in active]
        assert "Hallow's End" in names

    def test_midsummer(self):
        active = get_active_events(date(2026, 6, 30))
        names = [e["name"] for e in active]
        assert "Midsummer Fire Festival" in names


# ── Year-boundary events (Winter Veil) ───────────────────────────


class TestWinterVeil:
    def test_december_active(self):
        active = get_active_events(date(2026, 12, 25))
        names = [e["name"] for e in active]
        assert "Feast of Winter Veil" in names

    def test_january_active(self):
        active = get_active_events(date(2027, 1, 1))
        names = [e["name"] for e in active]
        assert "Feast of Winter Veil" in names

    def test_before_start(self):
        active = get_active_events(date(2026, 12, 14))
        names = [e["name"] for e in active]
        assert "Feast of Winter Veil" not in names

    def test_after_end(self):
        active = get_active_events(date(2027, 1, 3))
        names = [e["name"] for e in active]
        assert "Feast of Winter Veil" not in names


# ── Variable-date events ────────────────────────────────────────


class TestVariableDateEvents:
    def test_noblegarden_2026(self):
        # Easter 2026 = Apr 5, so Noblegarden starts Apr 6 (Easter Monday)
        active = get_active_events(date(2026, 4, 6))
        names = [e["name"] for e in active]
        assert "Noblegarden" in names

    def test_noblegarden_end_2026(self):
        # Noblegarden: Apr 6 – Apr 12
        active = get_active_events(date(2026, 4, 12))
        names = [e["name"] for e in active]
        assert "Noblegarden" in names

    def test_noblegarden_after_end_2026(self):
        active = get_active_events(date(2026, 4, 13))
        names = [e["name"] for e in active]
        assert "Noblegarden" not in names

    def test_childrens_week_2026(self):
        # Noblegarden ends Apr 12, Children's Week starts ~1 week later = Apr 20
        active = get_active_events(date(2026, 4, 20))
        names = [e["name"] for e in active]
        assert "Children's Week" in names

    def test_lunar_festival_2026(self):
        # Chinese New Year 2026 = Feb 17, Lunar Festival starts Feb 10
        active = get_active_events(date(2026, 2, 12))
        names = [e["name"] for e in active]
        assert "Lunar Festival" in names

    def test_love_is_in_the_air(self):
        active = get_active_events(date(2026, 2, 14))
        names = [e["name"] for e in active]
        assert "Love is in the Air" in names

    def test_pilgrims_bounty_2026(self):
        # Thanksgiving 2026 = Nov 26 (Thursday), Monday before = Nov 23
        active = get_active_events(date(2026, 11, 24))
        names = [e["name"] for e in active]
        assert "Pilgrim's Bounty" in names


# ── Seasons ──────────────────────────────────────────────────────


class TestSeasons:
    def test_winter_solstice(self):
        assert get_season(date(2026, 12, 21))["name"] == "Winter"

    def test_winter_january(self):
        assert get_season(date(2026, 1, 15))["name"] == "Winter"

    def test_spring_equinox(self):
        assert get_season(date(2026, 3, 20))["name"] == "Spring"

    def test_summer_solstice(self):
        assert get_season(date(2026, 6, 21))["name"] == "Summer"

    def test_autumn_equinox(self):
        assert get_season(date(2026, 9, 22))["name"] == "Autumn"

    def test_last_day_of_autumn(self):
        assert get_season(date(2026, 12, 20))["name"] == "Autumn"

    def test_last_day_of_winter(self):
        assert get_season(date(2026, 3, 19))["name"] == "Winter"


# ── get_calendar_context() ──────────────────────────────────────


class TestCalendarContext:
    def test_during_event(self):
        ctx = get_calendar_context(date(2026, 9, 25))
        assert "Brewfest" in ctx
        assert "Active events:" in ctx

    def test_between_events(self):
        # Mid-August: no events active
        ctx = get_calendar_context(date(2026, 8, 15))
        assert "Active events:" not in ctx
        assert "Current season:" in ctx

    def test_season_always_present(self):
        ctx = get_calendar_context(date(2026, 5, 10))
        assert "Current season: Spring" in ctx

    def test_upcoming_detection(self):
        # Sep 10 is 10 days before Brewfest (Sep 20)
        ctx = get_calendar_context(date(2026, 9, 10))
        assert "Upcoming:" in ctx
        assert "Brewfest" in ctx

    def test_no_upcoming_when_far(self):
        # Jul 1: Brewfest is ~80 days away
        ctx = get_calendar_context(date(2026, 7, 1))
        assert "Upcoming:" not in ctx or "Brewfest" not in ctx

    def test_winter_veil_context(self):
        ctx = get_calendar_context(date(2026, 12, 25))
        assert "Winter" in ctx
        assert "Winter Veil" in ctx
