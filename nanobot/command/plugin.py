"""Plugin command metadata registry and discovery.

Plugins register custom slash commands via ``pyproject.toml`` entry points::

    [project.entry-points."nanobot.commands"]
    my_plugin = "my_package:get_commands"

Where ``get_commands`` is a callable ``() -> list[PluginCommand]``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.command.router import Handler

_builtin_commands: list[PluginCommand] = []
_plugin_commands: list[PluginCommand] = []


@dataclass
class PluginCommand:
    """Metadata for a single slash command registered by a built-in or plugin."""

    command: str  # e.g. "/deploy"
    description: str  # e.g. "Trigger a deployment"
    handler: Handler  # async (CommandContext) -> OutboundMessage | None
    title: str = ""  # UI palette title (defaults to command)
    icon: str = "zap"  # UI palette icon
    arg_hint: str = ""  # e.g. "<env>"
    telegram_command: str = ""  # Telegram-safe alias (auto-derived if empty)
    priority: bool = False  # If True, registered as priority tier

    def __post_init__(self) -> None:
        if not self.title:
            self.title = self.command
        if not self.telegram_command:
            self.telegram_command = self.command.lstrip("/").replace("-", "_")


def register_builtin(cmd: PluginCommand) -> None:
    """Register a built-in command's metadata in the global registry."""
    _builtin_commands.append(cmd)


def discover_plugin_commands() -> None:
    """Scan ``entry_points(group="nanobot.commands")`` for third-party commands.

    Each entry point must be a callable ``() -> list[PluginCommand]``.
    Failures are logged as warnings and skipped.
    """
    global _plugin_commands
    _plugin_commands.clear()

    try:
        from importlib.metadata import entry_points
    except ImportError:
        return

    try:
        eps = entry_points(group="nanobot.commands")
    except TypeError:
        # Python < 3.12 fallback: entry_points() takes no args
        try:
            eps = entry_points().get("nanobot.commands", [])
        except Exception:
            logger.warning("Failed to discover plugin commands: entry_points() not supported")
            return

    for ep in eps:
        try:
            factory = ep.load()
        except Exception:
            logger.warning("Failed to load command plugin entry point '{}'", ep.name)
            continue

        try:
            commands = factory()
        except Exception:
            logger.warning("Command plugin '{}' factory raised an exception", ep.name)
            continue

        if not isinstance(commands, list):
            logger.warning("Command plugin '{}' did not return a list, skipping", ep.name)
            continue

        for cmd in commands:
            if not isinstance(cmd, PluginCommand):
                logger.warning(
                    "Command plugin '{}' returned a non-PluginCommand item, skipping", ep.name
                )
                continue
            _plugin_commands.append(cmd)

    if _plugin_commands:
        logger.info("Discovered {} plugin command(s)", len(_plugin_commands))

    # Also discover loose plugins installed via `nanobot plugins install`
    _discover_loose_plugins()


def _discover_loose_plugins() -> None:
    """Scan ``~/.nanobot/plugins/`` for loose (non-pip) plugin installations.

    Each subdirectory that has an ``__init__.py`` (i.e. a Python package) is
    imported and checked for a ``get_commands()`` callable.
    """
    from pathlib import Path

    plugins_dir = Path.home() / ".nanobot" / "plugins"
    if not plugins_dir.is_dir():
        return

    for entry in sorted(plugins_dir.iterdir()):
        if not entry.is_dir():
            continue
        init_file = entry / "__init__.py"
        if not init_file.exists():
            continue
        name = entry.name
        # Avoid re-importing packages that are already available via pip
        try:
            mod = __import__(name, fromlist=["get_commands"])
        except ImportError:
            try:
                import sys
                if str(entry) not in sys.path:
                    sys.path.insert(0, str(entry.parent))
                mod = __import__(name, fromlist=["get_commands"])
            except Exception:
                logger.debug("Failed to import loose plugin '{}'", name)
                continue

        factory = getattr(mod, "get_commands", None)
        if factory is None:
            continue

        try:
            commands = factory()
        except Exception:
            logger.warning("Loose plugin '{}' factory raised an exception", name)
            continue

        if not isinstance(commands, list):
            continue

        for cmd in commands:
            if isinstance(cmd, PluginCommand):
                # Skip if already registered (avoids duplicate between pip and loose)
                if any(
                    c.command == cmd.command and c.handler == cmd.handler
                    for c in _plugin_commands
                ):
                    continue
                _plugin_commands.append(cmd)


def get_all_commands() -> list[PluginCommand]:
    """Return all registered commands (builtins first, then plugins)."""
    return list(_builtin_commands) + list(_plugin_commands)


def build_help_text() -> str:
    """Build canonical help text shared across channels."""
    lines = ["🐈 nanobot commands:"]
    for cmd in get_all_commands():
        command = cmd.command
        if cmd.arg_hint:
            command = f"{command} {cmd.arg_hint}"
        lines.append(f"{command} — {cmd.description}")
    return "\n".join(lines)


def get_telegram_bot_commands() -> list:
    """Build the command list for Telegram's ``set_my_commands()``."""
    from telegram import BotCommand

    result: list[BotCommand] = []
    seen: set[str] = set()
    for cmd in get_all_commands():
        tc = cmd.telegram_command
        if tc in seen:
            continue
        seen.add(tc)
        # Telegram doesn't allow leading slash
        name = tc.lstrip("/")
        result.append(BotCommand(name, cmd.description))
    return result


def build_telegram_slash_regex() -> re.Pattern:
    """Build a regex for all dispatchable (non-help, non-start) commands.

    Matches command names with optional ``@bot`` suffix and arguments.
    Excludes ``/start`` and ``/help`` which have dedicated handlers.
    """
    names: list[str] = []
    for cmd in get_all_commands():
        name = cmd.command.lstrip("/")
        if name in ("start", "help"):
            continue
        escaped = re.escape(name)
        escaped_alt = re.escape(cmd.telegram_command.lstrip("/"))
        names.append(escaped)
        if escaped_alt != escaped:
            names.append(escaped_alt)
    if not names:
        return re.compile(r"^/(?:)$")
    alternation = "|".join(sorted(set(names), key=len, reverse=True))
    return re.compile(rf"^/(?:{alternation})(?:@\w+)?(?:\s+.*)?$")


def get_command_palette() -> list[dict]:
    """Return structured command metadata for UI command palettes."""
    result: list[dict] = []
    for cmd in get_all_commands():
        result.append({
            "command": cmd.command,
            "title": cmd.title,
            "description": cmd.description,
            "icon": cmd.icon,
            "arg_hint": cmd.arg_hint,
        })
    return result
