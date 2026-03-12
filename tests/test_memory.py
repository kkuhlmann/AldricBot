"""Tests for aldricbot.memory — guildmate and server memory I/O."""

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
