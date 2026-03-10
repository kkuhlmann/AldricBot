#!/usr/bin/env python3
"""WoW MCP Server - Interactive Installation Script.

Automates the full setup: prerequisite checks, addon installation,
dependency install, and MCP server registration with Claude Code.

Usage: python install.py

Requires only the Python standard library.
"""

# Python version guard — uses syntax compatible with Python 3.6+
import sys

if sys.version_info < (3, 10):
    print("Error: Python 3.10 or newer is required (found {}.{})".format(*sys.version_info[:2]))
    print("Install from https://www.python.org/downloads/")
    sys.exit(1)

import os
import platform
import shutil
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

class Colors:
    """ANSI color codes, disabled when NO_COLOR is set or on dumb terminals."""

    def __init__(self):
        force_off = os.environ.get("NO_COLOR") is not None or os.environ.get("TERM") == "dumb"
        if platform.system() == "Windows" and not force_off:
            self._enable_windows_ansi()
        if force_off:
            self.RESET = self.BOLD = self.GREEN = self.YELLOW = self.RED = self.CYAN = ""
        else:
            self.RESET = "\033[0m"
            self.BOLD = "\033[1m"
            self.GREEN = "\033[32m"
            self.YELLOW = "\033[33m"
            self.RED = "\033[31m"
            self.CYAN = "\033[36m"

    @staticmethod
    def _enable_windows_ansi():
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            pass


C = Colors()


def ok(msg: str) -> None:
    print(f"  {C.GREEN}[OK]{C.RESET} {msg}")


def warn(msg: str) -> None:
    print(f"  {C.YELLOW}[!!]{C.RESET} {msg}")


def error(msg: str) -> None:
    print(f"  {C.RED}[ERR]{C.RESET} {msg}")


def step(title: str) -> None:
    print(f"\n{C.BOLD}{C.CYAN}==> {title}{C.RESET}")


def info(msg: str) -> None:
    print(f"    {msg}")


def ask(prompt: str, default: str = "") -> str:
    """Prompt the user for input with an optional default."""
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"    {prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(1)
    return value or default


# ---------------------------------------------------------------------------
# Repo root (directory containing this script)
# ---------------------------------------------------------------------------

REPO_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

def check_python() -> bool:
    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    ok(f"Python {ver}")
    return True


def get_tool_version(name: str) -> str | None:
    """Return the version string for a CLI tool, or None if not found."""
    path = shutil.which(name)
    if not path:
        return None
    try:
        result = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=10
        )
        output = (result.stdout + result.stderr).strip()
        # Extract first line, strip common prefixes
        first_line = output.splitlines()[0] if output else ""
        for prefix in (f"{name} ", f"{name}/", ""):
            if first_line.lower().startswith(prefix):
                return first_line[len(prefix):].strip()
        return first_line
    except Exception:
        return "unknown"


def check_uv() -> bool:
    """Check for uv, auto-install if missing."""
    ver = get_tool_version("uv")
    if ver:
        ok(f"uv {ver}")
        return True

    warn("uv not found — attempting automatic install")
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.run(
                ["powershell", "-ExecutionPolicy", "ByPass", "-c",
                 "irm https://astral.sh/uv/install.ps1 | iex"],
                check=True, timeout=120,
            )
        else:
            subprocess.run(
                ["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"],
                check=True, timeout=120,
            )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        error("Failed to auto-install uv")
        info("Install manually: https://docs.astral.sh/uv/getting-started/installation/")
        return False

    # Refresh PATH for common install locations
    for extra in [
        Path.home() / ".local" / "bin",
        Path.home() / ".cargo" / "bin",
    ]:
        if str(extra) not in os.environ.get("PATH", ""):
            os.environ["PATH"] = f"{extra}{os.pathsep}{os.environ.get('PATH', '')}"

    ver = get_tool_version("uv")
    if ver:
        ok(f"uv {ver} (just installed)")
        return True

    error("uv installed but not found on PATH — restart your terminal and re-run")
    return False


def check_claude_cli() -> bool:
    """Check for Claude Code CLI. Soft prerequisite — returns False if missing."""
    ver = get_tool_version("claude")
    if ver:
        ok(f"Claude Code {ver}")
        return True
    warn("Claude Code CLI not found — MCP registration will be skipped")
    info("Install: https://docs.anthropic.com/en/docs/claude-code/overview")
    return False


# ---------------------------------------------------------------------------
# WoW path detection
# ---------------------------------------------------------------------------

def _common_wow_paths() -> list[Path]:
    """Return platform-specific common WoW install locations."""
    system = platform.system()
    home = Path.home()
    candidates: list[Path] = []

    if system == "Darwin":
        candidates = [
            Path("/Applications/World of Warcraft"),
            home / "Applications" / "World of Warcraft",
        ]
    elif system == "Linux":
        candidates = [
            home / ".wine" / "drive_c" / "Program Files (x86)" / "World of Warcraft",
            home / ".wine" / "drive_c" / "Program Files" / "World of Warcraft",
            home / "Games" / "world-of-warcraft" / "drive_c" / "World of Warcraft",
            home / "Games" / "World of Warcraft",
        ]
    elif system == "Windows":
        for drive in ("C", "D", "E"):
            candidates.append(Path(f"{drive}:\\Program Files (x86)\\World of Warcraft"))
            candidates.append(Path(f"{drive}:\\Program Files\\World of Warcraft"))
            candidates.append(Path(f"{drive}:\\World of Warcraft"))
            candidates.append(Path(f"{drive}:\\Games\\World of Warcraft"))

    return candidates


def validate_wow_path(path: Path) -> bool:
    """Check that a path looks like a WoW install (has Interface/ and WTF/)."""
    return (path / "Interface").is_dir() and (path / "WTF").is_dir()


def detect_wow_path() -> Path | None:
    for p in _common_wow_paths():
        if p.is_dir() and validate_wow_path(p):
            return p
    return None


def prompt_wow_path() -> Path:
    """Interactive loop to get a valid WoW install path."""
    detected = detect_wow_path()
    if detected:
        info(f"Auto-detected: {detected}")

    while True:
        default = str(detected) if detected else ""
        raw = ask("WoW install path", default)
        if not raw:
            error("A WoW install path is required")
            continue
        path = Path(raw).expanduser().resolve()
        if not path.is_dir():
            error(f"Directory not found: {path}")
            continue
        if not validate_wow_path(path):
            warn("Directory exists but missing Interface/ or WTF/ subdirectories")
            confirm = ask("Use this path anyway? (y/n)", "n")
            if confirm.lower() != "y":
                continue
        ok("Valid WoW installation found")
        return path


# ---------------------------------------------------------------------------
# Account name detection
# ---------------------------------------------------------------------------

def detect_account_names(wow_path: Path) -> list[str]:
    """List account directories under WTF/Account/."""
    account_dir = wow_path / "WTF" / "Account"
    if not account_dir.is_dir():
        return []
    return sorted(
        d.name for d in account_dir.iterdir()
        if d.is_dir() and d.name != "SavedVariables" and not d.name.startswith(".")
    )


def prompt_account_name(wow_path: Path) -> str:
    """Interactive prompt to select or enter an account name."""
    accounts = detect_account_names(wow_path)

    if not accounts:
        warn("No account directories found under WTF/Account/")
        info("You may need to log in to WoW at least once first")
        while True:
            name = ask("Enter your WoW account name")
            if name:
                return name.upper()
            error("Account name is required")

    if len(accounts) == 1:
        info(f"Found account: {accounts[0]}")
        result = ask("Account name", accounts[0])
        return result

    info("Found accounts:")
    for i, name in enumerate(accounts, 1):
        info(f"  {i}) {name}")

    while True:
        choice = ask("Enter number or account name", "1")
        # Try as a number
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(accounts):
                ok(f"Using account: {accounts[idx]}")
                return accounts[idx]
            error(f"Invalid number — enter 1-{len(accounts)}")
            continue
        except ValueError:
            pass
        # Try as a name
        upper = choice.upper()
        if upper in accounts:
            ok(f"Using account: {upper}")
            return upper
        # Allow arbitrary input
        ok(f"Using account: {upper}")
        return upper


# ---------------------------------------------------------------------------
# Addon installation
# ---------------------------------------------------------------------------

def install_addon(wow_path: Path) -> bool:
    addon_dir = wow_path / "Interface" / "AddOns" / "ClaudeBot"
    try:
        addon_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        error(f"Permission denied creating {addon_dir}")
        info("Try running with elevated permissions or copy the files manually")
        return False

    files = ["ClaudeBot.lua", "ClaudeBot.toc"]
    for fname in files:
        src = REPO_DIR / fname
        if not src.exists():
            error(f"Source file not found: {src}")
            return False
        try:
            shutil.copy2(src, addon_dir / fname)
            ok(f"Copied {fname}")
        except PermissionError:
            error(f"Permission denied copying {fname}")
            return False

    info(f"Installed to: {addon_dir}")
    return True


# ---------------------------------------------------------------------------
# Python dependencies
# ---------------------------------------------------------------------------

def install_dependencies() -> bool:
    uv = shutil.which("uv")
    if not uv:
        error("uv not found on PATH")
        return False
    try:
        result = subprocess.run(
            [uv, "sync"],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            error("uv sync failed")
            if result.stdout.strip():
                info(result.stdout.strip())
            if result.stderr.strip():
                info(result.stderr.strip())
            return False
        ok("Dependencies installed")
        return True
    except subprocess.TimeoutExpired:
        error("uv sync timed out")
        return False


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------

def register_mcp(wow_path: Path, account_name: str) -> bool:
    claude = shutil.which("claude")
    if not claude:
        return False

    # Remove existing registration (ignore errors)
    subprocess.run(
        [claude, "mcp", "remove", "wow-mcp", "-s", "user"],
        capture_output=True, timeout=30,
    )

    # Register
    cmd = [
        claude, "mcp", "add", "wow-mcp",
        "--scope", "user",
        "-e", f"WOW_INSTALL_PATH={wow_path}",
        "-e", f"WOW_ACCOUNT_NAME={account_name}",
        "--", "uv", "run", "--directory", str(REPO_DIR), "wow-mcp",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            error("MCP registration failed")
            if result.stderr.strip():
                info(result.stderr.strip())
            _print_manual_mcp_command(wow_path, account_name)
            return False
        ok("MCP server registered as 'wow-mcp' (user scope)")
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        error("Failed to run claude CLI")
        _print_manual_mcp_command(wow_path, account_name)
        return False


def _print_manual_mcp_command(wow_path: Path, account_name: str) -> None:
    info("Register manually with:")
    info('  claude mcp add wow-mcp --scope user \\')
    info(f'    -e WOW_INSTALL_PATH="{wow_path}" \\')
    info(f'    -e WOW_ACCOUNT_NAME="{account_name}" \\')
    info(f'    -- uv run --directory "{REPO_DIR}" wow-mcp')


# ---------------------------------------------------------------------------
# Post-install instructions
# ---------------------------------------------------------------------------

def print_post_install() -> None:
    step("Setup Complete!")
    info("Next steps:")
    info("  1. Launch WoW and log in")
    info("  2. Verify ClaudeBot is enabled in the AddOns panel (character select)")
    info("  3. Type /reload once in-game to create initial SavedVariables")
    info("  4. Start Claude Code and type /mcp to verify connection")
    print()

    system = platform.system()
    if system == "Darwin":
        warn("macOS: Grant Accessibility permissions to your terminal")
        info("  System Settings > Privacy & Security > Accessibility")
        info("  Add your terminal app (Terminal, iTerm2, VS Code, etc.)")
        print()
    elif system == "Linux":
        wmctrl = shutil.which("wmctrl")
        if not wmctrl:
            warn("Linux: Install wmctrl for window activation")
            info("  sudo apt install wmctrl   # Debian/Ubuntu")
            info("  sudo dnf install wmctrl   # Fedora")
            print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"\n{C.BOLD}WoW MCP Server - Installation Script{C.RESET}")
    print("Sets up the ClaudeBot addon and MCP server for Claude Code\n")

    # --- Prerequisites ---
    step("Checking Prerequisites")
    check_python()
    if not check_uv():
        error("uv is required — install it and re-run this script")
        sys.exit(1)
    has_claude = check_claude_cli()

    # --- WoW path ---
    step("WoW Installation Path")
    wow_path = prompt_wow_path()

    # --- Account name ---
    step("WoW Account Name")
    account_name = prompt_account_name(wow_path)

    # --- Install addon ---
    step("Installing WoW Addon")
    if not install_addon(wow_path):
        error("Addon installation failed")
        sys.exit(1)

    # --- Dependencies ---
    step("Installing Python Dependencies")
    if not install_dependencies():
        error("Dependency installation failed — try running 'uv sync' manually")
        sys.exit(1)

    # --- MCP registration ---
    step("Registering MCP Server with Claude Code")
    if has_claude:
        register_mcp(wow_path, account_name)
    else:
        warn("Skipping MCP registration (Claude Code CLI not found)")
        _print_manual_mcp_command(wow_path, account_name)

    # --- Done ---
    print_post_install()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {C.YELLOW}Installation cancelled.{C.RESET}\n")
        sys.exit(1)
