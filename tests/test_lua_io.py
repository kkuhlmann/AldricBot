"""Tests for aldricbot.lua_io — Lua SavedVariables parser."""

import json

import pytest

from aldricbot.lua_io import parse_lua_value, parse_saved_variables


# ── Primitives ───────────────────────────────────────────────────


def test_parse_nil():
    assert parse_lua_value("nil") is None


def test_parse_true():
    assert parse_lua_value("true") is True


def test_parse_false():
    assert parse_lua_value("false") is False


def test_parse_integer():
    assert parse_lua_value("42") == 42


def test_parse_negative_integer():
    assert parse_lua_value("-7") == -7


def test_parse_float():
    assert parse_lua_value("3.14") == pytest.approx(3.14)


def test_parse_scientific():
    assert parse_lua_value("1e3") == pytest.approx(1000.0)


def test_parse_hex():
    assert parse_lua_value("0xFF") == 255


# ── Strings ──────────────────────────────────────────────────────


def test_parse_double_quoted_string():
    assert parse_lua_value('"hello world"') == "hello world"


def test_parse_single_quoted_string():
    assert parse_lua_value("'hello world'") == "hello world"


def test_parse_string_escape_newline():
    assert parse_lua_value(r'"line1\nline2"') == "line1\nline2"


def test_parse_string_escape_tab():
    assert parse_lua_value(r'"col1\tcol2"') == "col1\tcol2"


def test_parse_string_escape_backslash():
    assert parse_lua_value(r'"back\\slash"') == "back\\slash"


def test_parse_string_escape_quote():
    assert parse_lua_value(r'"say \"hello\""') == 'say "hello"'


def test_parse_string_decimal_escape():
    # \065 = 'A' in ASCII
    assert parse_lua_value(r'"char:\065"') == "char:A"


def test_parse_long_string():
    assert parse_lua_value("[[hello world]]") == "hello world"


def test_parse_long_string_strips_leading_newline():
    assert parse_lua_value("[[\nhello]]") == "hello"


# ── Tables ───────────────────────────────────────────────────────


def test_parse_empty_table():
    result = parse_lua_value("{}")
    assert result == [] or result == {}


def test_parse_array_table():
    result = parse_lua_value('{"a", "b", "c"}')
    assert result == ["a", "b", "c"]


def test_parse_dict_table():
    result = parse_lua_value('{name = "Aldric", level = 70}')
    assert result == {"name": "Aldric", "level": 70}


def test_parse_nested_table():
    result = parse_lua_value('{player = {name = "Aldric"}, active = true}')
    assert result == {"player": {"name": "Aldric"}, "active": True}


def test_parse_bracket_key_table():
    result = parse_lua_value('{[1] = "a", [2] = "b"}')
    assert result == ["a", "b"]


def test_parse_trailing_comma():
    result = parse_lua_value('{"a", "b", "c",}')
    assert result == ["a", "b", "c"]


def test_parse_semicolon_separator():
    result = parse_lua_value('{name = "Aldric"; level = 70}')
    assert result == {"name": "Aldric", "level": 70}


def test_parse_mixed_table():
    """Non-sequential integer keys become a dict with string keys."""
    result = parse_lua_value('{[1] = "a", [3] = "c"}')
    assert isinstance(result, dict)
    assert result["1"] == "a"
    assert result["3"] == "c"


# ── Comments ─────────────────────────────────────────────────────


def test_single_line_comment():
    result = parse_lua_value('42 -- this is a comment')
    assert result == 42


def test_block_comment():
    result = parse_lua_value('--[[ block comment ]] 42')
    assert result == 42


# ── SavedVariables format ────────────────────────────────────────


def test_parse_saved_variables():
    text = '''
    MyAddonDB = {
        setting = true,
        count = 42,
    }
    '''
    result = parse_saved_variables(text)
    assert "MyAddonDB" in result
    assert result["MyAddonDB"]["setting"] is True
    assert result["MyAddonDB"]["count"] == 42


def test_parse_multiple_variables():
    text = '''
    VarA = "hello"
    VarB = 123
    '''
    result = parse_saved_variables(text)
    assert result["VarA"] == "hello"
    assert result["VarB"] == 123


def test_parse_realistic_addon_output():
    """Parse something resembling AldricBotAddon's actual output."""
    state_json = json.dumps({
        "timestamp": 12345.678,
        "player": {
            "name": "Aldric",
            "class": "Paladin",
            "level": 70,
            "zone": "Stormwind",
            "subZone": "Trade District",
            "isDead": False,
            "isGhost": False,
        },
        "chatMessages": [
            {
                "type": "guild",
                "text": "Fenwick: Hey Aldric, tell me about Arthas",
                "time": 12340.0,
            }
        ],
    })
    # The addon stores state as a JSON string in a Lua variable
    escaped = state_json.replace('"', '\\"')
    lua_text = f'''
    AldricBotAddonDB = {{
        lastState = "{escaped}",
    }}
    '''
    result = parse_saved_variables(lua_text)
    assert "AldricBotAddonDB" in result
    last_state = json.loads(result["AldricBotAddonDB"]["lastState"])
    assert last_state["player"]["name"] == "Aldric"
    assert len(last_state["chatMessages"]) == 1
    assert last_state["chatMessages"][0]["type"] == "guild"
