"""Persona loading, CLAUDE.md rendering, and emote/response accessors."""

from __future__ import annotations

from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

REQUIRED_FIELDS = ("race", "class")

# Project root (one level up from this file's directory)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CLASS_PERSONALITIES_PATH = _PROJECT_ROOT / "personas" / "class_personalities.yaml"


def load_persona(path: str | Path) -> dict:
    """Parse a persona YAML file and validate required fields."""
    path = Path(path)
    with open(path) as f:
        persona = yaml.safe_load(f)
    if not isinstance(persona, dict):
        raise ValueError(f"Persona file must be a YAML mapping: {path}")
    missing = [f for f in REQUIRED_FIELDS if not persona.get(f)]
    if missing:
        raise ValueError(f"Persona missing required fields: {', '.join(missing)}")
    return persona


def render_claude_md(
    persona: dict,
    template_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> str:
    """Render CLAUDE.md.j2 with persona data and write to output_path.

    Returns the rendered text.
    """
    if template_path is None:
        template_path = _PROJECT_ROOT / "CLAUDE.md.j2"
    template_path = Path(template_path)

    if output_path is None:
        output_path = _PROJECT_ROOT / "CLAUDE.md"
    output_path = Path(output_path)

    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        keep_trailing_newline=True,
    )
    template = env.get_template(template_path.name)

    # Map 'class' to 'class_' for Jinja2 (class is a Python reserved word)
    variables = dict(persona)
    variables.setdefault("class_", variables.get("class", ""))

    # Look up class personality from shared file
    if "class_personality" not in variables:
        cls = variables.get("class", "")
        with open(_CLASS_PERSONALITIES_PATH) as f:
            all_personalities = yaml.safe_load(f)
        variables["class_personality"] = all_personalities.get(cls, "")

    rendered = template.render(**variables)
    output_path.write_text(rendered)
    return rendered


# ── Emote & response accessors with sensible defaults ──────────


def get_idle_emotes(persona: dict | None) -> list[str]:
    """Return idle emotes from persona, or empty list."""
    if persona is None:
        return []
    return persona.get("emotes", {}).get("idle", [])


def get_seasonal_emotes(persona: dict | None) -> dict[str, list[str]]:
    """Return seasonal emote mapping from persona, or empty dict."""
    if persona is None:
        return {}
    return persona.get("emotes", {}).get("seasonal", {})


def get_thinking_emotes(persona: dict | None) -> list[str]:
    """Return thinking emotes from persona, or empty list."""
    if persona is None:
        return []
    return persona.get("emotes", {}).get("thinking", [])


def get_auth_down_responses(persona: dict | None) -> list[str]:
    """Return auth-down responses from persona, or empty list."""
    if persona is None:
        return []
    return persona.get("emotes", {}).get("auth_down", [])


def get_farewell_emote(persona: dict | None) -> str:
    """Return farewell emote from persona, or empty string."""
    if persona is None:
        return ""
    return persona.get("emotes", {}).get("farewell", "")


def get_login_greetings(persona: dict | None) -> list[str]:
    """Return login greetings from persona, or empty list."""
    if persona is None:
        return []
    return persona.get("responses", {}).get("login_greetings", [])


def get_achievement_reactions(persona: dict | None) -> list[str]:
    """Return achievement reactions from persona, or empty list."""
    if persona is None:
        return []
    return persona.get("responses", {}).get("achievement_reactions", [])


def get_levelup_reactions(persona: dict | None) -> list[str]:
    """Return level-up reactions from persona, or empty list."""
    if persona is None:
        return []
    return persona.get("responses", {}).get("levelup_reactions", [])


# ── CLI entry point ────────────────────────────────────────────

def main() -> None:
    """Render CLAUDE.md from a persona file (CLI entry point)."""
    import argparse

    parser = argparse.ArgumentParser(description="Render CLAUDE.md from a persona YAML")
    parser.add_argument(
        "--persona",
        required=True,
        help="Path to persona YAML file",
    )
    parser.add_argument(
        "--template",
        default=None,
        help="Path to CLAUDE.md.j2 template (default: project root)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path for rendered CLAUDE.md (default: project root)",
    )
    args = parser.parse_args()

    persona = load_persona(args.persona)
    rendered = render_claude_md(persona, args.template, args.output)
    print(f"Rendered CLAUDE.md ({len(rendered)} chars) for persona '{persona['name']}'")


if __name__ == "__main__":
    main()
