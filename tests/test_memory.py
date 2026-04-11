"""Tests for aldricbot.memory — guildmate and server memory I/O."""

from datetime import datetime
from unittest.mock import patch

from aldricbot import memory


# ── Guildmate CRUD ───────────────────────────────────────────────


def test_load_nonexistent():
    assert memory.load_guildmate("Nobody") is None


def test_save_and_load():
    data = {"name": "Fenwick", "summary": "A warrior who loves Ulduar."}
    memory.save_guildmate("Fenwick", data)
    loaded = memory.load_guildmate("Fenwick")
    assert loaded == data


def test_delete_existing():
    memory.save_guildmate("Fenwick", {"name": "Fenwick"})
    assert memory.delete_guildmate("Fenwick") is True
    assert memory.load_guildmate("Fenwick") is None


def test_delete_nonexistent():
    assert memory.delete_guildmate("Nobody") is False


def test_delete_all():
    for name in ("Fenwick", "Grukk", "Liora"):
        memory.save_guildmate(name, {"name": name})
    count = memory.delete_all_guildmates()
    assert count == 3
    for name in ("Fenwick", "Grukk", "Liora"):
        assert memory.load_guildmate(name) is None


# ── Guildmate metadata update ───────────────────────────────────


def test_update_new_guildmate():
    msg = {"senderClass": "Warrior", "senderLevel": 72, "senderZone": "Dalaran"}
    result = memory.update_guildmate_metadata("Fenwick", msg)
    assert result["name"] == "Fenwick"
    assert result["times_spoken"] == 1
    assert result["summary"] == ""
    assert result["class"] == "Warrior"
    assert result["level"] == 72
    assert result["zone_last_seen"] == "Dalaran"


def test_update_existing_guildmate():
    memory.save_guildmate("Fenwick", {
        "name": "Fenwick",
        "first_seen": "2026-03-01",
        "times_spoken": 5,
        "summary": "A gruff warrior.",
        "class": "Warrior",
        "level": 71,
    })
    msg = {"senderClass": "Warrior", "senderLevel": 72, "senderZone": "Stormwind"}
    result = memory.update_guildmate_metadata("Fenwick", msg)
    assert result["times_spoken"] == 6
    assert result["level"] == 72
    assert result["zone_last_seen"] == "Stormwind"
    assert result["summary"] == "A gruff warrior."
    assert result["first_seen"] == "2026-03-01"


def test_update_does_not_save_to_disk():
    msg = {"senderClass": "Mage"}
    memory.update_guildmate_metadata("NewPerson", msg)
    # update_guildmate_metadata does NOT save — caller decides
    assert memory.load_guildmate("NewPerson") is None


# ── Server memory ────────────────────────────────────────────────


def test_load_empty_server_memory():
    result = memory.load_server_memory()
    assert result == {"facts": []}


def test_add_server_fact():
    result = memory.add_server_fact("ICC Thursday at 8pm", "Fenwick")
    assert len(result["facts"]) == 1
    fact = result["facts"][0]
    assert fact["text"] == "ICC Thursday at 8pm"
    assert fact["added_by"] == "Fenwick"
    assert "added_at" in fact


def test_add_multiple_facts():
    memory.add_server_fact("Fact one", "Fenwick")
    memory.add_server_fact("Fact two", "Grukk")
    result = memory.add_server_fact("Fact three", "Liora")
    assert len(result["facts"]) == 3
    assert result["facts"][0]["text"] == "Fact one"
    assert result["facts"][2]["text"] == "Fact three"


def test_max_facts_cap():
    for i in range(22):
        memory.add_server_fact(f"Fact {i}", "Tester")
    loaded = memory.load_server_memory()
    assert len(loaded["facts"]) == 20
    # Oldest two should have been dropped
    assert loaded["facts"][0]["text"] == "Fact 2"
    assert loaded["facts"][-1]["text"] == "Fact 21"


def test_remove_fact_by_index():
    memory.add_server_fact("Alpha", "A")
    memory.add_server_fact("Beta", "B")
    memory.add_server_fact("Gamma", "C")
    assert memory.remove_server_fact(1) is True
    loaded = memory.load_server_memory()
    assert len(loaded["facts"]) == 2
    assert loaded["facts"][0]["text"] == "Alpha"
    assert loaded["facts"][1]["text"] == "Gamma"


def test_remove_fact_out_of_range():
    memory.add_server_fact("Only fact", "A")
    assert memory.remove_server_fact(99) is False
    assert memory.remove_server_fact(-1) is False


def test_clear_server_memory():
    memory.add_server_fact("Alpha", "A")
    memory.add_server_fact("Beta", "B")
    memory.add_server_fact("Gamma", "C")
    count = memory.clear_server_memory()
    assert count == 3
    assert memory.load_server_memory() == {"facts": []}


def test_clear_empty_server_memory():
    count = memory.clear_server_memory()
    assert count == 0


# ── Self memory ─────────────────────────────────────────────────


def test_load_empty_self_memory():
    result = memory.load_self_memory()
    assert result == {"summary": "", "last_updated": ""}


def test_save_and_load_self_memory():
    memory.save_self_memory("I once told Fenwick about fighting in Hillsbrad.")
    result = memory.load_self_memory()
    assert result["summary"] == "I once told Fenwick about fighting in Hillsbrad."
    assert result["last_updated"] != ""


def test_save_self_memory_overwrites():
    memory.save_self_memory("First version.")
    memory.save_self_memory("Second version, rewritten.")
    result = memory.load_self_memory()
    assert result["summary"] == "Second version, rewritten."


# ── Relationship tiers ─────────────────────────────────────────


def test_relationship_tier_stranger():
    tier, limit, phrasing = memory.get_relationship_tier("Nobody")
    assert tier == "stranger"
    assert limit == 0
    assert "not met this person" in phrasing


def test_relationship_tier_acquaintance_at_1():
    memory.save_guildmate("Fenwick", {"name": "Fenwick", "times_spoken": 1, "summary": "A warrior."})
    tier, limit, phrasing = memory.get_relationship_tier("Fenwick")
    assert tier == "acquaintance"
    assert limit == 6
    assert "a few times" in phrasing
    assert "A warrior." in phrasing


def test_relationship_tier_acquaintance_at_14():
    memory.save_guildmate("Fenwick", {"name": "Fenwick", "times_spoken": 14, "summary": "A warrior."})
    tier, limit, _ = memory.get_relationship_tier("Fenwick")
    assert tier == "acquaintance"
    assert limit == 6


def test_relationship_tier_familiar_at_15():
    memory.save_guildmate("Fenwick", {"name": "Fenwick", "times_spoken": 15, "summary": "A warrior."})
    tier, limit, phrasing = memory.get_relationship_tier("Fenwick")
    assert tier == "familiar"
    assert limit == 8
    assert "many times" in phrasing


def test_relationship_tier_familiar_at_49():
    memory.save_guildmate("Fenwick", {"name": "Fenwick", "times_spoken": 49, "summary": "A warrior."})
    tier, limit, _ = memory.get_relationship_tier("Fenwick")
    assert tier == "familiar"
    assert limit == 8


def test_relationship_tier_well_known_at_50():
    memory.save_guildmate("Fenwick", {"name": "Fenwick", "times_spoken": 50, "summary": "A warrior."})
    tier, limit, phrasing = memory.get_relationship_tier("Fenwick")
    assert tier == "well_known"
    assert limit == 10
    assert "extensively" in phrasing


def test_relationship_tier_no_summary():
    """Acquaintance with empty summary still gets correct tier."""
    memory.save_guildmate("Fenwick", {"name": "Fenwick", "times_spoken": 5, "summary": ""})
    tier, limit, phrasing = memory.get_relationship_tier("Fenwick")
    assert tier == "acquaintance"
    assert "a few times" in phrasing
    # Should not have a dangling ": " with no summary
    assert phrasing.endswith(".")


# ── Disposition tiers ──────────────────────────────────────────


def test_disposition_hostile():
    tier, phrasing = memory.get_disposition_tier(-10)
    assert tier == "hostile"
    assert "Hostile" in phrasing


def test_disposition_cold():
    tier, _ = memory.get_disposition_tier(-3)
    assert tier == "cold"


def test_disposition_neutral():
    tier, _ = memory.get_disposition_tier(0)
    assert tier == "neutral"


def test_disposition_warm():
    tier, _ = memory.get_disposition_tier(4)
    assert tier == "warm"


def test_disposition_fond():
    tier, _ = memory.get_disposition_tier(8)
    assert tier == "fond"


def test_disposition_boundary_negative():
    """Score -1 is still neutral."""
    tier, _ = memory.get_disposition_tier(-1)
    assert tier == "neutral"


def test_disposition_boundary_cold():
    """Score -2 is cold."""
    tier, _ = memory.get_disposition_tier(-2)
    assert tier == "cold"


def test_disposition_boundary_hostile():
    """Score -6 is hostile."""
    tier, _ = memory.get_disposition_tier(-6)
    assert tier == "hostile"


# ── Friendliness decay ────────────────────────────────────────


@patch("aldricbot.memory.datetime")
def test_decay_positive_score(mock_dt):
    mock_dt.now.return_value = datetime(2026, 3, 13)
    mock_dt.strptime = datetime.strptime
    data = {"friendliness": 4.0, "last_seen": "2026-03-09"}
    # 4 days inactive → 4 * 0.25 = 1.0 decay
    score = memory.apply_friendliness_decay(data)
    assert score == 3.0


@patch("aldricbot.memory.datetime")
def test_decay_negative_score(mock_dt):
    mock_dt.now.return_value = datetime(2026, 3, 13)
    mock_dt.strptime = datetime.strptime
    data = {"friendliness": -4.0, "last_seen": "2026-03-09"}
    # 4 days inactive → 4 * 0.25 = 1.0 decay toward 0
    score = memory.apply_friendliness_decay(data)
    assert score == -3.0


def test_decay_does_not_overshoot_zero():
    data = {"friendliness": 0.5, "last_seen": "2026-03-01"}
    # 11 days → 2.75 decay, but should clamp at 0
    score = memory.apply_friendliness_decay(data)
    assert score == 0.0


def test_decay_already_neutral():
    data = {"friendliness": 0.0, "last_seen": "2026-03-01"}
    score = memory.apply_friendliness_decay(data)
    assert score == 0.0


def test_decay_no_last_seen():
    data = {"friendliness": 5.0}
    score = memory.apply_friendliness_decay(data)
    assert score == 5.0


def test_decay_missing_friendliness():
    """Backward compatible — no friendliness field defaults to 0."""
    data = {"last_seen": "2026-03-01"}
    score = memory.apply_friendliness_decay(data)
    assert score == 0.0


# ── Daily friendliness cap ────────────────────────────────────────


def test_daily_cap_scales_delta():
    """Raw delta is scaled by 0.25 (e.g. +2 → +0.5)."""
    gm = {}
    effective = memory.clamp_daily_friendliness_delta(gm, 2)
    assert effective == 0.5


def test_daily_cap_negative_scales():
    """Negative raw delta is scaled (e.g. -1 → -0.25)."""
    gm = {}
    effective = memory.clamp_daily_friendliness_delta(gm, -1)
    assert effective == -0.25


def test_daily_cap_blocks_after_limit():
    """After ±1.0 accumulated, further same-direction deltas return 0."""
    gm = {}
    memory.clamp_daily_friendliness_delta(gm, 2)  # +0.5
    memory.clamp_daily_friendliness_delta(gm, 2)  # +0.5, total = 1.0
    effective = memory.clamp_daily_friendliness_delta(gm, 2)  # capped
    assert effective == 0.0


def test_daily_cap_partial_remainder():
    """When partially capped, only the remaining budget is returned."""
    gm = {}
    memory.clamp_daily_friendliness_delta(gm, 2)  # +0.5
    memory.clamp_daily_friendliness_delta(gm, 1)  # +0.25, total = 0.75
    effective = memory.clamp_daily_friendliness_delta(gm, 2)  # wants +0.5, only 0.25 left
    assert effective == 0.25


def test_daily_cap_resets_on_new_day():
    """A new date resets the daily accumulation."""
    gm = {"friendliness_daily_delta": 1.0, "friendliness_daily_date": "2020-01-01"}
    effective = memory.clamp_daily_friendliness_delta(gm, 2)
    assert effective == 0.5  # reset, full budget available


def test_daily_cap_opposite_direction_still_works():
    """Positive cap doesn't block negative deltas."""
    gm = {}
    memory.clamp_daily_friendliness_delta(gm, 2)  # +0.5
    memory.clamp_daily_friendliness_delta(gm, 2)  # +0.5, total = 1.0
    effective = memory.clamp_daily_friendliness_delta(gm, -2)  # -0.5
    assert effective == -0.5  # net daily becomes 0.5


# ── Nicknames ────────────────────────────────────────────────────


def test_get_nickname_existing():
    memory.save_guildmate("Fenwick", {"name": "Fenwick", "nickname": "the Scholar"})
    assert memory.get_nickname("Fenwick") == "the Scholar"


def test_get_nickname_missing():
    memory.save_guildmate("Fenwick", {"name": "Fenwick"})
    assert memory.get_nickname("Fenwick") is None


def test_get_nickname_no_memory():
    assert memory.get_nickname("Nobody") is None


# ── Hide and Seek ────────────────────────────────────────────


def test_load_hide_and_seek_default():
    result = memory.load_hide_and_seek()
    assert result == {"active": False, "finders": []}


def test_set_hide_and_seek_active(monkeypatch):
    monkeypatch.setattr("aldricbot.input_control.send_chat_command", lambda cmd: None)
    result = memory.set_hide_and_seek_active(True, "AdminGuy", 500)
    assert result["active"] is True
    assert result["activated_by"] == "AdminGuy"
    assert result["reward_copper"] == 5000000
    assert result["current_reward_copper"] == 5000000
    assert result["hint_count"] == 0
    assert result["hints"] == []


def test_set_hide_and_seek_active_preserves_finders(monkeypatch):
    monkeypatch.setattr("aldricbot.input_control.send_chat_command", lambda cmd: None)
    # Record a finder first
    memory.save_hide_and_seek({
        "active": False,
        "finders": [{"name": "Fenwick", "found_at": "2026-03-13T14:00:00", "copper_given": 4000000}],
    })
    result = memory.set_hide_and_seek_active(True, "AdminGuy", 500)
    assert len(result["finders"]) == 1
    assert result["finders"][0]["name"] == "Fenwick"


def test_set_hide_and_seek_active_resets_hints(monkeypatch):
    monkeypatch.setattr("aldricbot.input_control.send_chat_command", lambda cmd: None)
    memory.save_hide_and_seek({
        "active": True, "finders": [], "hints": ["old hint"],
        "hint_count": 3, "reward_copper": 5000000, "current_reward_copper": 4000000,
    })
    result = memory.set_hide_and_seek_active(True, "AdminGuy", 600)
    assert result["hints"] == []
    assert result["hint_count"] == 0
    assert result["reward_copper"] == 6000000


def test_record_finder():
    memory.save_hide_and_seek({"active": True, "finders": [], "reward_copper": 5000000, "current_reward_copper": 4500000})
    result = memory.record_finder("Fenwick", 4500000)
    assert result["active"] is False
    assert len(result["finders"]) == 1
    assert result["finders"][0]["name"] == "Fenwick"
    assert result["finders"][0]["copper_given"] == 4500000


def test_increment_hint_count_first_hint(monkeypatch):
    """First hint — no decay."""
    sent = []
    monkeypatch.setattr("aldricbot.input_control.send_chat_command", lambda cmd: sent.append(cmd))
    memory.save_hide_and_seek({"active": True, "finders": [], "hint_count": 0, "reward_copper": 5000000, "current_reward_copper": 5000000, "hints": []})
    count = memory.increment_hint_count()
    assert count == 1
    data = memory.load_hide_and_seek()
    assert data["current_reward_copper"] == 5000000  # no decay on first hint
    assert "5000000" in sent[-1]


def test_increment_hint_count_decay(monkeypatch):
    """Hints 2-5 decay by 20% of original each."""
    sent = []
    monkeypatch.setattr("aldricbot.input_control.send_chat_command", lambda cmd: sent.append(cmd))
    memory.save_hide_and_seek({"active": True, "finders": [], "hint_count": 1, "reward_copper": 5000000, "current_reward_copper": 5000000, "hints": []})
    count = memory.increment_hint_count()
    assert count == 2
    data = memory.load_hide_and_seek()
    assert data["current_reward_copper"] == 4000000  # 5000000 - (2-1)*1000000 = 4000000
    assert "4000000" in sent[-1]


def test_increment_hint_count_decay_at_5(monkeypatch):
    """Hint 5 — 80% total decay."""
    sent = []
    monkeypatch.setattr("aldricbot.input_control.send_chat_command", lambda cmd: sent.append(cmd))
    memory.save_hide_and_seek({"active": True, "finders": [], "hint_count": 4, "reward_copper": 5000000, "current_reward_copper": 2000000, "hints": []})
    count = memory.increment_hint_count()
    assert count == 5
    data = memory.load_hide_and_seek()
    assert data["current_reward_copper"] == 1000000  # 5000000 - (5-1)*1000000 = 1000000
    assert "1000000" in sent[-1]


def test_store_hint():
    memory.save_hide_and_seek({"active": True, "finders": [], "hints": []})
    memory.store_hint("The earth mourns here...")
    memory.store_hint("Spires of a fallen prince...")
    hints = memory.get_hints()
    assert len(hints) == 2
    assert hints[0] == "The earth mourns here..."
    assert hints[1] == "Spires of a fallen prince..."


def test_get_hints_empty():
    assert memory.get_hints() == []


def test_get_current_reward_copper():
    memory.save_hide_and_seek({"active": True, "finders": [], "reward_copper": 5000000, "current_reward_copper": 4000000})
    assert memory.get_current_reward_copper() == 4000000


def test_get_current_reward_copper_default():
    assert memory.get_current_reward_copper() == 0


def test_get_winner_stats():
    memory.save_hide_and_seek({
        "active": False,
        "finders": [
            {"name": "Fenwick", "found_at": "...", "copper_given": 5000000},
            {"name": "Grukk", "found_at": "...", "copper_given": 4500000},
            {"name": "Fenwick", "found_at": "...", "copper_given": 4000000},
        ],
    })
    stats = memory.get_winner_stats()
    assert len(stats) == 2
    assert stats[0]["name"] == "Fenwick"
    assert stats[0]["wins"] == 2
    assert stats[0]["total_copper"] == 9000000
    assert stats[1]["name"] == "Grukk"
    assert stats[1]["wins"] == 1


def test_get_winner_stats_empty():
    assert memory.get_winner_stats() == []


def test_init_paths_sets_hide_and_seek_file(tmp_path, monkeypatch):
    monkeypatch.setattr("aldricbot.memory.Path.home", lambda: tmp_path)
    memory.init_paths("TestChar")
    assert memory.HIDE_AND_SEEK_FILE == tmp_path / ".aldricbot" / "characters" / "TestChar" / "hide_and_seek.json"
