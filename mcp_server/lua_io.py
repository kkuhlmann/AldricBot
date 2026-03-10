"""Pure-Python Lua SavedVariables parser and serializer.

Handles the subset of Lua used in WoW SavedVariables files:
  - nil, true, false, numbers, strings (with escape sequences)
  - tables (both array-style and key-value)
  - single-line (--) and block (--[[ ]]) comments
  - trailing commas

This is the primary communication layer between the MCP server and the
WoW addon.  The MCP server reads game state and writes commands by
manipulating the SavedVariables file on disk; WoW picks up changes on
each /reload.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Lua → Python parser
# ---------------------------------------------------------------------------

_WHITESPACE = re.compile(r"(?:\s|--\[\[.*?\]\]|--[^\n]*)+", re.DOTALL)
_NUMBER = re.compile(r"-?(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)")
_SIMPLE_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class _Parser:
    """Recursive descent parser for Lua values."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def _skip(self) -> None:
        m = _WHITESPACE.match(self.text, self.pos)
        if m:
            self.pos = m.end()

    def _peek(self) -> str:
        self._skip()
        if self.pos >= len(self.text):
            return ""
        return self.text[self.pos]

    def _expect(self, ch: str) -> None:
        self._skip()
        if self.pos >= len(self.text) or self.text[self.pos] != ch:
            raise ValueError(
                f"Expected '{ch}' at pos {self.pos}, got "
                f"'{self.text[self.pos] if self.pos < len(self.text) else 'EOF'}'"
            )
        self.pos += 1

    def parse_value(self) -> Any:
        self._skip()
        if self.pos >= len(self.text):
            raise ValueError("Unexpected end of input")

        ch = self.text[self.pos]

        if ch == "{":
            return self._parse_table()
        if ch == '"' or ch == "'":
            return self._parse_string()
        if ch == "[" and self.pos + 1 < len(self.text) and self.text[self.pos + 1] == "[":
            return self._parse_long_string()

        # keywords / numbers
        rest = self.text[self.pos:]
        if rest.startswith("nil"):
            self.pos += 3
            return None
        if rest.startswith("true"):
            self.pos += 4
            return True
        if rest.startswith("false"):
            self.pos += 5
            return False

        m = _NUMBER.match(rest)
        if m:
            self.pos += m.end()
            raw = m.group()
            if "." in raw or "e" in raw.lower():
                return float(raw)
            return int(raw, 0)

        raise ValueError(f"Unexpected character '{ch}' at pos {self.pos}")

    def _parse_string(self) -> str:
        quote = self.text[self.pos]
        self.pos += 1
        parts: list[str] = []
        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch == "\\":
                self.pos += 1
                esc = self.text[self.pos]
                if esc == "n":
                    parts.append("\n")
                elif esc == "t":
                    parts.append("\t")
                elif esc == "\\":
                    parts.append("\\")
                elif esc == '"':
                    parts.append('"')
                elif esc == "'":
                    parts.append("'")
                elif esc == "\n":
                    parts.append("\n")
                elif esc.isdigit():
                    # \ddd decimal escape
                    num_str = esc
                    for _ in range(2):
                        if self.pos + 1 < len(self.text) and self.text[self.pos + 1].isdigit():
                            self.pos += 1
                            num_str += self.text[self.pos]
                    parts.append(chr(int(num_str)))
                else:
                    parts.append(esc)
                self.pos += 1
            elif ch == quote:
                self.pos += 1
                return "".join(parts)
            else:
                parts.append(ch)
                self.pos += 1
        raise ValueError("Unterminated string")

    def _parse_long_string(self) -> str:
        # [[ ... ]]
        self.pos += 2  # skip [[
        end = self.text.find("]]", self.pos)
        if end == -1:
            raise ValueError("Unterminated long string")
        s = self.text[self.pos:end]
        self.pos = end + 2
        # Lua strips a leading newline in long strings
        if s.startswith("\n"):
            s = s[1:]
        return s

    def _parse_table(self) -> dict[str, Any] | list[Any]:
        self._expect("{")
        entries: list[tuple[Any, Any]] = []
        auto_index = 1

        while True:
            self._skip()
            if self.pos >= len(self.text):
                raise ValueError("Unterminated table")
            if self.text[self.pos] == "}":
                self.pos += 1
                break

            key: Any
            # [expr] = value
            if self.text[self.pos] == "[":
                self.pos += 1
                key = self.parse_value()
                self._expect("]")
                self._expect("=")
                val = self.parse_value()
            else:
                # Try simple_key = value
                m = _SIMPLE_KEY.match(self.text, self.pos)
                saved = self.pos
                if m:
                    after = m.end()
                    # skip whitespace after key
                    tmp = _WHITESPACE.match(self.text, after)
                    eq_pos = tmp.end() if tmp else after
                    if eq_pos < len(self.text) and self.text[eq_pos] == "=":
                        key = m.group()
                        self.pos = eq_pos + 1
                        val = self.parse_value()
                    else:
                        # It's a positional value
                        self.pos = saved
                        key = auto_index
                        auto_index += 1
                        val = self.parse_value()
                else:
                    key = auto_index
                    auto_index += 1
                    val = self.parse_value()

            entries.append((key, val))

            # optional comma/semicolon separator
            self._skip()
            if self.pos < len(self.text) and self.text[self.pos] in (",", ";"):
                self.pos += 1

        # Decide: array or dict
        if entries and all(isinstance(k, int) for k, _ in entries):
            keys = [k for k, _ in entries]
            if keys == list(range(1, len(keys) + 1)):
                return [v for _, v in entries]

        # Convert integer keys to strings for JSON compatibility
        result: dict[str, Any] = {}
        for k, v in entries:
            result[str(k) if isinstance(k, int) else k] = v
        return result


def parse_lua_value(text: str) -> Any:
    """Parse a single Lua value from a string."""
    p = _Parser(text)
    return p.parse_value()


def parse_saved_variables(text: str) -> dict[str, Any]:
    """Parse a WoW SavedVariables file into a dict of global name → value."""
    result: dict[str, Any] = {}
    p = _Parser(text)
    while True:
        p._skip()
        if p.pos >= len(p.text):
            break
        # Expect: VarName = value
        m = _SIMPLE_KEY.match(p.text, p.pos)
        if not m:
            raise ValueError(f"Expected variable name at pos {p.pos}")
        name = m.group()
        p.pos = m.end()
        p._expect("=")
        value = p.parse_value()
        result[name] = value
    return result


# ---------------------------------------------------------------------------
# Python → Lua serializer
# ---------------------------------------------------------------------------


def to_lua(value: Any, indent: str = "  ", depth: int = 0) -> str:
    """Serialize a Python value to a Lua literal string."""
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if isinstance(value, str):
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\t", "\\t")
        )
        return f'"{escaped}"'
    if isinstance(value, list):
        if not value:
            return "{}"
        pad = indent * (depth + 1)
        close = indent * depth
        items = [f"{pad}{to_lua(v, indent, depth + 1)}" for v in value]
        return "{\n" + ",\n".join(items) + ",\n" + close + "}"
    if isinstance(value, dict):
        if not value:
            return "{}"
        pad = indent * (depth + 1)
        close = indent * depth
        items = []
        for k, v in value.items():
            lua_key = k if isinstance(k, str) and _SIMPLE_KEY.fullmatch(k) else f'["{k}"]'
            items.append(f"{pad}{lua_key} = {to_lua(v, indent, depth + 1)}")
        return "{\n" + ",\n".join(items) + ",\n" + close + "}"

    return f'"{value}"'


def serialize_saved_variables(variables: dict[str, Any]) -> str:
    """Serialize a dict of globals into a WoW SavedVariables file."""
    lines = []
    for name, value in variables.items():
        lines.append(f"{name} = {to_lua(value)}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# File I/O with atomic write
# ---------------------------------------------------------------------------


def read_saved_variables(path: Path) -> dict[str, Any]:
    """Read and parse a SavedVariables file."""
    text = path.read_text(encoding="utf-8")
    return parse_saved_variables(text)


def write_saved_variables(path: Path, variables: dict[str, Any]) -> None:
    """Atomically write a SavedVariables file."""
    content = serialize_saved_variables(variables)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)
