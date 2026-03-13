"""Tests for aldricbot.persona — YAML loading, CLAUDE.md rendering, and accessors."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from aldricbot import persona as persona_mod

# Path to the real Aldric persona in the repo
PERSONAS_DIR = Path(__file__).resolve().parent.parent / "personas"
ALDRIC_YAML = PERSONAS_DIR / "aldric.yaml"
TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "CLAUDE.md.j2"


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def aldric_persona():
    """Load the real Aldric persona YAML."""
    return persona_mod.load_persona(ALDRIC_YAML)


@pytest.fixture
def minimal_persona(tmp_path):
    """Create a minimal valid persona YAML for testing."""
    data = {
        "race": "Dwarf",
        "class": "Warrior",
        "age": 30,
        "build": "Stocky",
        "scars": "None visible",
        "eyes": "Brown",
        "speaking_style": "Blunt",
        "backstory": [{"title": "Origin", "text": "Born in Ironforge."}],
        "personality_anchors": ["Drinks ale constantly"],
        "emotes": {
            "idle": ["/e scratches his beard."],
            "seasonal": {"Winter": ["/e shivers."]},
            "thinking": ["/e ponders."],
            "auth_down": ["My mind is foggy."],
            "farewell": "/e waves goodbye.",
        },
        "responses": {
            "login_greetings": ["Oi, {name}!"],
            "achievement_reactions": ["Nice one, {name}."],
            "levelup_reactions": ["Gettin' stronger, {name}."],
        },
    }
    path = tmp_path / "test_persona.yaml"
    path.write_text(yaml.dump(data))
    return path, data


# ── Loading tests ─────────────────────────────────────────────


class TestLoadPersona:
    def test_load_aldric(self, aldric_persona):
        assert aldric_persona["race"] == "Human"
        assert aldric_persona["class"] == "Paladin"

    def test_load_minimal(self, minimal_persona):
        path, expected = minimal_persona
        persona = persona_mod.load_persona(path)
        assert persona["class"] == "Warrior"

    def test_missing_required_field(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(yaml.dump({"race": "Dwarf"}))
        with pytest.raises(ValueError, match="missing required fields"):
            persona_mod.load_persona(path)

    def test_non_mapping_yaml(self, tmp_path):
        path = tmp_path / "list.yaml"
        path.write_text("- item1\n- item2\n")
        with pytest.raises(ValueError, match="YAML mapping"):
            persona_mod.load_persona(path)


# ── Rendering tests ───────────────────────────────────────────


class TestRenderClaudeMd:
    def test_render_aldric(self, aldric_persona, tmp_path):
        aldric_persona["name"] = "Aldric"
        output = tmp_path / "CLAUDE.md"
        rendered = persona_mod.render_claude_md(
            aldric_persona, template_path=TEMPLATE_PATH, output_path=output
        )
        assert output.exists()
        assert "You are Aldric" in rendered
        assert "Human" in rendered
        assert "Paladin" in rendered

    def test_render_substitutes_name(self, aldric_persona, tmp_path):
        aldric_persona["name"] = "Aldric"
        output = tmp_path / "CLAUDE.md"
        rendered = persona_mod.render_claude_md(
            aldric_persona, template_path=TEMPLATE_PATH, output_path=output
        )
        # Name should appear in many places
        assert rendered.count("Aldric") > 10

    def test_render_uses_injected_name(self, aldric_persona, tmp_path):
        """Name comes from --character flag, not the persona YAML."""
        aldric_persona["name"] = "Theron"
        output = tmp_path / "CLAUDE.md"
        rendered = persona_mod.render_claude_md(
            aldric_persona, template_path=TEMPLATE_PATH, output_path=output
        )
        assert "You are Theron" in rendered
        assert "Theron" in rendered

    def test_render_backstory_entries(self, aldric_persona, tmp_path):
        aldric_persona["name"] = "Aldric"
        output = tmp_path / "CLAUDE.md"
        rendered = persona_mod.render_claude_md(
            aldric_persona, template_path=TEMPLATE_PATH, output_path=output
        )
        assert "Second War" in rendered
        assert "Silver Hand" in rendered
        assert "Mount Hyjal" in rendered

    def test_render_class_personality(self, aldric_persona, tmp_path):
        aldric_persona["name"] = "Aldric"
        output = tmp_path / "CLAUDE.md"
        rendered = persona_mod.render_claude_md(
            aldric_persona, template_path=TEMPLATE_PATH, output_path=output
        )
        assert "**Paladin:**" in rendered
        assert "Righteous and formal" in rendered
        # Only the matching class should appear, not all classes
        assert "**Warrior:**" not in rendered
        assert "**Mage:**" not in rendered

    def test_render_different_persona(self, minimal_persona, tmp_path):
        path, data = minimal_persona
        persona = persona_mod.load_persona(path)
        persona["name"] = "Bruni"
        output = tmp_path / "CLAUDE.md"
        rendered = persona_mod.render_claude_md(
            persona, template_path=TEMPLATE_PATH, output_path=output
        )
        assert "Bruni" in rendered
        assert "Dwarf" in rendered


# ── Accessor tests ────────────────────────────────────────────


class TestAccessors:
    def test_idle_emotes(self, aldric_persona):
        emotes = persona_mod.get_idle_emotes(aldric_persona)
        assert len(emotes) == 7
        assert all(e.startswith("/e") for e in emotes)

    def test_seasonal_emotes(self, aldric_persona):
        seasonal = persona_mod.get_seasonal_emotes(aldric_persona)
        assert "Winter" in seasonal
        assert "Summer" in seasonal
        assert len(seasonal["Winter"]) == 3

    def test_thinking_emotes(self, aldric_persona):
        emotes = persona_mod.get_thinking_emotes(aldric_persona)
        assert len(emotes) == 5

    def test_auth_down_responses(self, aldric_persona):
        responses = persona_mod.get_auth_down_responses(aldric_persona)
        assert len(responses) == 8
        assert all("Auth Token Expired" in r for r in responses)

    def test_farewell_emote(self, aldric_persona):
        farewell = persona_mod.get_farewell_emote(aldric_persona)
        assert farewell.startswith("/e")

    def test_login_greetings(self, aldric_persona):
        greetings = persona_mod.get_login_greetings(aldric_persona)
        assert len(greetings) == 10
        assert all("{name}" in g for g in greetings)

    def test_achievement_reactions(self, aldric_persona):
        reactions = persona_mod.get_achievement_reactions(aldric_persona)
        assert len(reactions) == 5

    def test_levelup_reactions(self, aldric_persona):
        reactions = persona_mod.get_levelup_reactions(aldric_persona)
        assert len(reactions) == 5

    def test_none_persona_returns_defaults(self):
        assert persona_mod.get_idle_emotes(None) == []
        assert persona_mod.get_seasonal_emotes(None) == {}
        assert persona_mod.get_thinking_emotes(None) == []
        assert persona_mod.get_auth_down_responses(None) == []
        assert persona_mod.get_farewell_emote(None) == ""
        assert persona_mod.get_login_greetings(None) == []
        assert persona_mod.get_achievement_reactions(None) == []
        assert persona_mod.get_levelup_reactions(None) == []
