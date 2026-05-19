"""Slash command routing and built-in handlers."""

from nanobot.command.builtin import register_builtin_commands
from nanobot.command.plugin import (
    PluginCommand,
    build_help_text,
    build_telegram_slash_regex,
    discover_plugin_commands,
    get_command_palette,
    get_telegram_bot_commands,
)
from nanobot.command.router import CommandContext, CommandRouter

__all__ = [
    "CommandContext",
    "CommandRouter",
    "PluginCommand",
    "register_builtin_commands",
    "discover_plugin_commands",
    "build_help_text",
    "get_telegram_bot_commands",
    "build_telegram_slash_regex",
    "get_command_palette",
]
