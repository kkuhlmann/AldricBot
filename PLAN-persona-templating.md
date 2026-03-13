# Plan: Template CLAUDE.md with Character Persona

## Context

CLAUDE.md currently hardcodes Aldric's identity (name, race, class, backstory, emotes, voice). Python code also hardcodes character-specific emotes and pre-written responses. This makes it impossible to run the bot as a different character without editing multiple files.

**Goal:** Extract all character-specific content into a YAML persona file, use Jinja2 to render CLAUDE.md at runtime, and load emotes/responses from the persona. A `--persona` flag selects which character to use.

## Files to Create

- `aldricbot/persona.py` — YAML loading, Jinja2 rendering, emote accessors, CLI entry point
- `personas/aldric.yaml` — All Aldric-specific content (identity, backstory, emotes, response pools)
- `CLAUDE.md.j2` — Jinja2 template (current CLAUDE.md with character sections replaced by `{{ variables }}`)
- `tests/test_persona.py` — Tests for loading, rendering, and emote extraction

## Files to Modify

- `daemon.py` — Add `--persona` flag; load persona at startup; render CLAUDE.md; pass persona through EventContext; use persona emotes with fallback to defaults
- `aldricbot/events.py` — Add `persona: dict | None = None` to EventContext; read response pools from persona when available (fallback to hardcoded defaults)
- `aldricbot/chat_handler.py` — Read THINKING_EMOTES and AUTH_DOWN_RESPONSES from `ctx.persona` when available
- `pyproject.toml` — Add `jinja2` and `pyyaml` dependencies
- `.gitignore` — Add `CLAUDE.md`
- `.env.sample` — Add `ALDRICBOT_PERSONA=`

## Persona YAML Structure

```yaml
name: Aldric
race: Human
class: Paladin
age: 55
location: ""

# Freeform text fields
build: "Broad-shouldered but weathered..."
scars: "A jagged scar runs from..."
eyes: "Grey-blue, heavy-lidded..."
speaking_style: "Formal, duty-bound..."

# Lists
backstory:
  - title: "Second War (~20 years old)"
    text: "Enlisted young as a footman..."
personality_anchors:
  - "Refers to his bad knee in cold weather..."

# Emotes (used by daemon.py and chat_handler.py)
emotes:
  idle: ["/e adjusts his journal...", ...]
  seasonal:
    Winter: ["/e winces and rubs his knee...", ...]
  thinking: ["/e strokes his beard...", ...]
  auth_down: ["Forgive me, friend...", ...]
  farewell: "/e closes his journal..."

# Pre-written response pools (used by events.py)
responses:
  login_greetings: ["Ah, {name}. Good to see you...", ...]
  achievement_reactions: ["Well earned, {name}...", ...]
  levelup_reactions: ["{name} grows stronger...", ...]
```

## CLAUDE.md.j2 Template

Convert CLAUDE.md to Jinja2, replacing character-specific sections:
- `{{ name }}` for all character name references
- `{{ race }}`, `{{ class_ }}`, `{{ age }}`, etc. for persona fields
- `{% for entry in backstory %}` for backstory list
- `{% for anchor in personality_anchors %}` for personality anchors
- Use `{% raw %}...{% endraw %}` around JSON code blocks containing `{{ }}`

Generic system logic (SavedVariables, daemon mode, memory system, commands, game loop) stays as literal template text.

## aldricbot/persona.py

```python
def load_persona(path: str | Path) -> dict          # Parse YAML, validate required fields
def render_claude_md(persona: dict, ...) -> None     # Jinja2 render -> write CLAUDE.md
def get_idle_emotes(persona: dict) -> list[str]      # With sensible defaults
def get_seasonal_emotes(persona: dict) -> dict
def get_thinking_emotes(persona: dict) -> list[str]
def get_auth_down_responses(persona: dict) -> list[str]
def get_farewell_emote(persona: dict) -> str
def get_login_greetings(persona: dict) -> list[str]
def get_achievement_reactions(persona: dict) -> list[str]
def get_levelup_reactions(persona: dict) -> list[str]
```

CLI entry point for interactive sessions:
```bash
uv run python -m aldricbot.persona --persona personas/aldric.yaml
```

## Integration: daemon.py

```python
parser.add_argument("--persona", default=os.environ.get("ALDRICBOT_PERSONA"))
```

At startup, before the game loop:
1. `persona = load_persona(args.persona)` if flag provided
2. Derive `args.character` from `persona["name"]` if `--character` not explicitly set
3. `render_claude_md(persona)` — writes CLAUDE.md to project root
4. Load emotes into local variables (with fallback to module-level defaults when no persona)
5. Pass `persona` via `EventContext` to all handlers

## Integration: events.py

- Add `persona: dict | None = None` to `EventContext`
- In LoginHandler, AchievementHandler, LevelUpHandler: read response pools from `ctx.persona["responses"]` when available, fall back to module-level constants

## Integration: chat_handler.py

- In `_send_thinking_emote()`: use `ctx.persona` emotes when available
- In `_send_auth_down()`: use `ctx.persona` responses when available

## Git Strategy

- Add `CLAUDE.md` to `.gitignore`
- Track `CLAUDE.md.j2` and `personas/aldric.yaml`
- Remove current `CLAUDE.md` from git tracking

## Implementation Order

1. Add `jinja2` and `pyyaml` to pyproject.toml
2. Create `personas/aldric.yaml` — extract all character content from CLAUDE.md + Python code
3. Create `CLAUDE.md.j2` — convert CLAUDE.md to template
4. Create `aldricbot/persona.py` — loading, rendering, accessors, CLI
5. Update `aldricbot/events.py` — add persona field to EventContext, read response pools from persona
6. Update `aldricbot/chat_handler.py` — read emotes from ctx.persona
7. Update `daemon.py` — add --persona flag, render pipeline, pass persona through
8. Update `.gitignore` and `.env.sample`
9. Create `tests/test_persona.py`

## Verification

1. `uv run python -m aldricbot.persona --persona personas/aldric.yaml` renders CLAUDE.md matching original content
2. `uv run pytest` — all existing tests pass, new persona tests pass
3. `daemon.py --persona personas/aldric.yaml` starts and uses persona emotes
4. Running without `--persona` still works (backward compatible with hardcoded defaults)
