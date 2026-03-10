"""Configuration from environment variables."""

import os
from pathlib import Path


WOW_INSTALL_PATH: str = os.environ.get("WOW_INSTALL_PATH", "")
WOW_ACCOUNT_NAME: str = os.environ.get("WOW_ACCOUNT_NAME", "")


def saved_variables_path() -> Path:
    """Return the path to ClaudeBot's SavedVariables file."""
    if not WOW_INSTALL_PATH:
        raise RuntimeError("WOW_INSTALL_PATH environment variable is not set")
    if not WOW_ACCOUNT_NAME:
        raise RuntimeError("WOW_ACCOUNT_NAME environment variable is not set")
    return (
        Path(WOW_INSTALL_PATH)
        / "WTF"
        / "Account"
        / WOW_ACCOUNT_NAME
        / "SavedVariables"
        / "ClaudeBot.lua"
    )
