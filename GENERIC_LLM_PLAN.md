# Plan: Dual-Provider Support (Claude Code + Ollama/Any LLM)

## Context

Currently, Claude Code is both the **game loop controller** (deciding when to reload, checking messages, managing anti-AFK) and the **RP brain** (generating in-character responses). This means only Claude Code can run the bot.

To support Ollama or any other LLM, we split these roles: a **Python agent** handles the deterministic game loop, and the **LLM only generates RP text**. This means even models with zero tool-calling support work — they just receive a prompt and return text.

Both modes coexist:
- **Mode A** (unchanged): Claude Code → MCP Server (stdio) → SavedVariables → WoW
- **Mode B** (new): `python -m agent` → core functions (direct import) → SavedVariables → WoW, with LLM calls for chat responses only

## File Structure (new/modified files)

```
WoW_MCP/
├── mcp_server/
│   ├── core.py              # NEW — extracted tool logic, no MCP dependency
│   └── server.py            # MODIFIED — thin wrappers delegating to core.py
├── agent/
│   ├── __init__.py           # NEW
│   ├── __main__.py           # NEW — entry point (python -m agent / wow-agent CLI)
│   ├── config.py             # NEW — YAML + env var config loader
│   ├── loop.py               # NEW — the game loop in Python
│   ├── chat.py               # NEW — message parsing, classification, chunking
│   ├── persona.py            # NEW — character persona dataclass + system prompt builder
│   └── llm/
│       ├── __init__.py       # NEW — factory function + re-exports
│       ├── base.py           # NEW — LLMProvider ABC (just a generate() method)
│       ├── ollama.py         # NEW — Ollama provider (httpx → /api/chat)
│       ├── claude.py         # NEW — Claude API provider (anthropic SDK)
│       └── openai_compat.py  # NEW — OpenAI-compatible provider (vLLM, LM Studio, etc.)
├── agent_config.yaml         # NEW — example configuration
└── pyproject.toml            # MODIFIED — add optional deps + wow-agent entry point
```

## Implementation Steps

### Step 1: Extract `mcp_server/core.py`

Move the three helper functions from `server.py` into `core.py` as plain functions (no MCP imports, no decorators). Also add async wrappers for the movement/reload/game_loop_step logic.

- `read_game_state()` ← from `_read_state_from_file()`
- `get_sync_status()` ← from the `get_sync_status` tool body
- `write_command(command)` ← from `_write_command_to_file()`
- `write_command_queue(commands)` ← from `_write_command_queue_to_file()`
- `reload_ui()`, `game_loop_step()`, `move_forward/backward()`, `turn_left/right()`, `jump()` ← async functions wrapping `input_control`

Then update `server.py` to import from `core` and have each `@mcp.tool()` function be a one-liner delegating to `core.*`.

**Why**: `server.py` imports `FastMCP` at module level. The standalone agent shouldn't need the `mcp` package at all. `core.py` has zero MCP dependency.

### Step 2: LLM Provider Abstraction (`agent/llm/`)

**`base.py`** — ABC with one method:
```python
async def generate(messages: list[ChatMessage], max_tokens: int = 512) -> str
```

No tool calling in the interface. The game loop is deterministic — the LLM only generates creative text. This means any model works, even without tool support.

**`ollama.py`** — `httpx.AsyncClient` → `POST /api/chat` (Ollama's native API)

**`claude.py`** — `anthropic.AsyncAnthropic` → `messages.create()`

**`openai_compat.py`** — `httpx.AsyncClient` → `POST /v1/chat/completions` (covers vLLM, LM Studio, text-generation-webui, any OpenAI-compatible server)

**`__init__.py`** — `create_provider(config_dict)` factory function

### Step 3: Chat Processing (`agent/chat.py`)

Codifies the CLAUDE.md chat logic as Python:
- `parse_chat_message(raw_msg)` → extracts sender, content, type
- `classify_message(content)` → keyword heuristic returning `lore_rp | raid_mechanics | personal_backstory | out_of_scope` (used to add context hints in the LLM prompt)
- `chunk_response(text, msg_type, sender)` → splits into 255-char macro-safe chunks with correct `/g`, `/p`, `/w SenderName` prefixes

### Step 4: Persona (`agent/persona.py`)

`CharacterPersona` dataclass loaded from `agent_config.yaml`. Has a `system_prompt()` method that builds the full system prompt including name, race, class, backstory, speaking style, personality, and tone rules.

### Step 5: Game Loop (`agent/loop.py`)

`GameLoopAgent` class implementing the CLAUDE.md game loop pseudocode:
1. `await core.game_loop_step()` — reload + read state
2. Scan `chatMessages` for new guild/party/whisper messages
3. For each new message: classify → build LLM prompt → `await llm.generate()` → chunk response → `core.write_command_queue()` → `await core.reload_ui()` + sleep to dispatch
4. Anti-AFK: `await core.jump()` every N cycles
5. Loop forever until KeyboardInterrupt

### Step 6: Config & Entry Point

**`agent/config.py`** — loads from YAML file with env var overrides for `WOW_INSTALL_PATH`, `WOW_ACCOUNT_NAME`, `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL`

**`agent/__main__.py`** — argparse CLI:
```
wow-agent                                    # uses ./agent_config.yaml + Ollama defaults
wow-agent --provider ollama --model mistral
wow-agent --provider claude --model claude-sonnet-4-20250514
wow-agent -c my_config.yaml
```

**`agent_config.yaml`** — example config with all options documented:
```yaml
# LLM Provider
llm:
  type: ollama               # ollama | claude | openai
  model: llama3.1:8b
  base_url: http://localhost:11434

# Character Persona
character:
  name: Aldric
  race: Human
  class: Paladin
  backstory: >
    A veteran of the Third War, now wandering Azeroth as a chronicler
    of its conflicts. Carries the weight of battles won and friends lost.
  speaking_style: >
    Formal, duty-bound. References the Light and honor naturally.
    Deeply affected by Arthas's fall.

# Game Loop Settings
loop:
  afk_interval: 120           # cycles between anti-AFK jumps (~5 min)
```

### Step 7: Update `pyproject.toml`

```toml
[project.optional-dependencies]
agent = ["httpx>=0.27.0", "pyyaml>=6.0"]
claude = ["anthropic>=0.45.0"]

[project.scripts]
wow-mcp = "mcp_server.server:main"     # existing
wow-agent = "agent.__main__:main"       # new

[tool.hatch.build.targets.wheel]
packages = ["mcp_server", "agent"]
```

Install commands:
- `uv sync` — MCP server only (existing flow, unchanged)
- `uv sync --extra agent` — standalone agent with Ollama
- `uv sync --extra agent --extra claude` — standalone agent with Claude API

### Step 8: Update install.py and README

Add standalone agent setup option to `install.py`. Update README with both usage modes.

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| No tool calling in LLM interface | Game loop is deterministic. LLM only generates text. Works with any model. |
| Separate `core.py` from `server.py` | Agent shouldn't need `mcp` package installed. Clean dependency boundary. |
| YAML config | Persona has multi-line fields (backstory) awkward in env vars. Env vars still work as overrides. |
| `httpx` for HTTP providers | Game loop is async (input_control uses async). httpx keeps it non-blocking. |
| Keyword classification in Python | Simple heuristic is enough to add context hints to the LLM prompt. The LLM itself handles nuance. |

## Future Enhancements (out of scope for initial implementation)

- **Web search for raid mechanics**: Add `duckduckgo-search` or similar library, triggered by `classify_message() == raid_mechanics`, results included in LLM prompt as context
- **Conversation memory**: Keep a rolling window of recent exchanges so the LLM can maintain conversational context
- **Multiple character support**: Run multiple agents with different personas simultaneously

## Verification

1. **MCP mode still works**: Run `wow-mcp` via Claude Code, confirm `game_loop_step()` and `send_command_queue()` behave identically
2. **Ollama standalone**: Start Ollama with a model, run `wow-agent --provider ollama --model llama3.1:8b`, send "Hey Aldric" in guild chat, confirm response appears in-game
3. **Claude API standalone**: Run `wow-agent --provider claude`, same test
4. **Anti-AFK**: Let agent run for 5+ minutes, confirm periodic jumps
5. **Message chunking**: Send a question that produces a long response, confirm it splits correctly at word boundaries within 255-char limits
