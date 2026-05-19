"""Tests for plugin command registration, discovery, and integration."""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest

from nanobot.command.builtin import register_builtin_commands
from nanobot.command.plugin import (
    PluginCommand,
    build_help_text,
    build_telegram_slash_regex,
    discover_plugin_commands,
    get_all_commands,
    get_command_palette,
    get_telegram_bot_commands,
    register_builtin,
)
from nanobot.command.router import CommandContext, CommandRouter


# Ensure built-in commands are registered before any test that reads the
# global registry.  We use a module-scoped fixture that runs once.
@pytest.fixture(scope="module")
def _ensure_builtins() -> None:
    register_builtin_commands(CommandRouter())


# ---------------------------------------------------------------------------
# PluginCommand dataclass
# ---------------------------------------------------------------------------

class TestPluginCommand:
    def test_defaults(self) -> None:
        async def noop(ctx: CommandContext) -> None:
            return None

        cmd = PluginCommand("/deploy", "Trigger a deployment", noop)
        assert cmd.command == "/deploy"
        assert cmd.description == "Trigger a deployment"
        assert cmd.title == "/deploy"
        assert cmd.icon == "zap"
        assert cmd.arg_hint == ""
        assert cmd.telegram_command == "deploy"
        assert cmd.priority is False

    def test_telegram_command_hyphen_replacement(self) -> None:
        async def noop(ctx: CommandContext) -> None:
            return None

        cmd = PluginCommand("/my-command", "desc", noop)
        assert cmd.telegram_command == "my_command"

    def test_explicit_telegram_command_preserved(self) -> None:
        async def noop(ctx: CommandContext) -> None:
            return None

        cmd = PluginCommand("/my-command", "desc", noop, telegram_command="custom_alias")
        assert cmd.telegram_command == "custom_alias"

    def test_explicit_title_preserved(self) -> None:
        async def noop(ctx: CommandContext) -> None:
            return None

        cmd = PluginCommand("/cmd", "desc", noop, title="My Title")
        assert cmd.title == "My Title"

    def test_priority_flag(self) -> None:
        async def noop(ctx: CommandContext) -> None:
            return None

        cmd = PluginCommand("/urgent", "desc", noop, priority=True)
        assert cmd.priority is True


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_get_all_commands_builtins_before_plugins(
        self, _ensure_builtins,
    ) -> None:
        all_cmds = get_all_commands()
        builtin_names = [c.command for c in all_cmds]
        assert "/stop" in builtin_names

    def test_get_command_palette_returns_dicts(self, _ensure_builtins) -> None:
        palette = get_command_palette()
        assert isinstance(palette, list)
        assert len(palette) > 0
        entry = palette[0]
        assert "command" in entry
        assert "title" in entry
        assert "description" in entry
        assert "icon" in entry
        assert "arg_hint" in entry


# ---------------------------------------------------------------------------
# build_help_text
# ---------------------------------------------------------------------------

class TestBuildHelpText:
    def test_includes_builtin_commands(self, _ensure_builtins) -> None:
        text = build_help_text()
        assert "🐈 nanobot commands:" in text
        assert "/stop" in text
        assert "/new" in text
        assert "/help" in text

    def test_includes_arg_hints(self, _ensure_builtins) -> None:
        text = build_help_text()
        assert "[preset]" in text or "<goal>" in text or "[n]" in text


# ---------------------------------------------------------------------------
# build_telegram_slash_regex
# ---------------------------------------------------------------------------

class TestBuildTelegramSlashRegex:
    def test_matches_builtin_commands(self, _ensure_builtins) -> None:
        pat = build_telegram_slash_regex()
        assert pat.match("/new")
        assert pat.match("/stop")
        assert pat.match("/status")
        assert pat.match("/model")
        assert pat.match("/dream")

    def test_matches_with_bot_suffix(self, _ensure_builtins) -> None:
        pat = build_telegram_slash_regex()
        assert pat.match("/new@my_bot")
        assert pat.match("/stop@bot")

    def test_matches_with_args(self, _ensure_builtins) -> None:
        pat = build_telegram_slash_regex()
        assert pat.match("/model gpt-5")
        assert pat.match("/goal do something long")
        assert pat.match("/pairing list")

    def test_excludes_start_and_help(self, _ensure_builtins) -> None:
        pat = build_telegram_slash_regex()
        assert not pat.match("/start")
        assert not pat.match("/start@bot")
        assert not pat.match("/help")
        assert not pat.match("/help@bot")

    def test_matches_telegram_aliases(self, _ensure_builtins) -> None:
        pat = build_telegram_slash_regex()
        assert pat.match("/dream_log")
        assert pat.match("/dream_restore")

    def test_does_not_match_unknown_commands(self, _ensure_builtins) -> None:
        pat = build_telegram_slash_regex()
        assert not pat.match("/unknown")
        assert not pat.match("/foo")

    def test_does_not_match_non_commands(self, _ensure_builtins) -> None:
        pat = build_telegram_slash_regex()
        assert not pat.match("hello world")
        assert not pat.match("what is /new")


# ---------------------------------------------------------------------------
# get_telegram_bot_commands
# ---------------------------------------------------------------------------

class TestGetTelegramBotCommands:
    def test_returns_bot_commands(self, _ensure_builtins) -> None:
        from telegram import BotCommand

        cmds = get_telegram_bot_commands()
        assert len(cmds) > 0
        assert all(isinstance(c, BotCommand) for c in cmds)

    def test_commands_have_no_leading_slash(self, _ensure_builtins) -> None:
        cmds = get_telegram_bot_commands()
        for c in cmds:
            assert not c.command.startswith("/")

    def test_known_commands_present(self, _ensure_builtins) -> None:
        cmds = get_telegram_bot_commands()
        names = {c.command for c in cmds}
        assert "new" in names
        assert "stop" in names
        assert "help" in names
        assert "dream_log" in names

    def test_no_duplicates(self, _ensure_builtins) -> None:
        cmds = get_telegram_bot_commands()
        names = [c.command for c in cmds]
        assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# CommandRouter.register_plugin / has_command
# ---------------------------------------------------------------------------

class TestRouterRegisterPlugin:
    @pytest.fixture()
    def router(self) -> CommandRouter:
        return CommandRouter()

    async def test_register_exact_command(self, router: CommandRouter) -> None:
        called = False

        async def handler(ctx: CommandContext) -> None:
            nonlocal called
            called = True
            return None

        cmd = PluginCommand("/deploy", "desc", handler)
        router.register_plugin(cmd)
        assert router.has_command("/deploy")
        assert not router.has_command("/unknown")

        ctx = CommandContext(
            msg=MagicMock(channel="test", chat_id="c1", metadata={}),
            session=None, key="test:c1", raw="/deploy", loop=MagicMock(),
        )
        await router.dispatch(ctx)
        assert called

    async def test_register_prefix_command(self, router: CommandRouter) -> None:
        captured_args: list[str] = []

        async def handler(ctx: CommandContext) -> None:
            captured_args.append(ctx.args)
            return None

        cmd = PluginCommand("/deploy", "desc", handler, arg_hint="<env>")
        router.register_plugin(cmd)
        assert router.has_command("/deploy")

        ctx = CommandContext(
            msg=MagicMock(channel="test", chat_id="c1", metadata={}),
            session=None, key="test:c1", raw="/deploy production", loop=MagicMock(),
        )
        await router.dispatch(ctx)
        assert captured_args == ["production"]

    async def test_register_priority_command(self, router: CommandRouter) -> None:
        async def handler(ctx: CommandContext) -> None:
            return None

        cmd = PluginCommand("/urgent", "desc", handler, priority=True)
        router.register_plugin(cmd)
        assert router.has_command("/urgent")
        assert router.is_priority("/urgent")

    async def test_register_priority_with_arg_hint(self, router: CommandRouter) -> None:
        captured_args: list[str] = []

        async def handler(ctx: CommandContext) -> None:
            captured_args.append(ctx.args)
            return None

        cmd = PluginCommand("/deploy", "desc", handler, priority=True, arg_hint="<env>")
        router.register_plugin(cmd)
        assert router.is_priority("/deploy")

        ctx = CommandContext(
            msg=MagicMock(channel="test", chat_id="c1", metadata={}),
            session=None, key="test:c1", raw="/deploy staging", loop=MagicMock(),
        )
        await router.dispatch(ctx)
        assert captured_args == ["staging"]

    def test_has_command_case_insensitive(self, router: CommandRouter) -> None:
        async def handler(ctx: CommandContext) -> None:
            return None

        cmd = PluginCommand("/Deploy", "desc", handler)
        router.register_plugin(cmd)
        assert router.has_command("/deploy")
        assert router.has_command("/DEPLOY")
        assert router.has_command("  /deploy  ")

    def test_register_non_plugincommand_raises(self, router: CommandRouter) -> None:
        with pytest.raises(TypeError, match="Expected PluginCommand"):
            router.register_plugin("not a PluginCommand")  # type: ignore[arg-type]

    def test_has_command_false_for_unregistered(self, router: CommandRouter) -> None:
        assert not router.has_command("/nonexistent")


# ---------------------------------------------------------------------------
# discover_plugin_commands
# ---------------------------------------------------------------------------

class TestDiscoverPluginCommands:
    def test_no_plugins_installed(self) -> None:
        import nanobot.command.plugin as mod

        old_plugins = list(mod._plugin_commands)
        try:
            mod._plugin_commands.clear()
            discover_plugin_commands()
            assert mod._plugin_commands == []
        finally:
            mod._plugin_commands[:] = old_plugins

    def test_discovers_entry_points(self) -> None:
        async def my_handler(ctx: CommandContext) -> None:
            return None

        my_cmd = PluginCommand("/my-plugin-cmd", "My plugin command", my_handler)

        mock_ep = MagicMock()
        mock_ep.name = "my_plugin"
        mock_ep.load.return_value = lambda: [my_cmd]

        with patch(
            "importlib.metadata.entry_points",
            return_value=[mock_ep],
        ):
            discover_plugin_commands()

        all_cmds = get_all_commands()
        assert my_cmd in all_cmds

    def test_failing_entry_point_is_skipped(self) -> None:
        mock_ep_bad = MagicMock()
        mock_ep_bad.name = "bad_plugin"
        mock_ep_bad.load.side_effect = ImportError("no module")

        async def handler(ctx: CommandContext) -> None:
            return None

        good_cmd = PluginCommand("/good", "good cmd", handler)

        mock_ep_good = MagicMock()
        mock_ep_good.name = "good_plugin"
        mock_ep_good.load.return_value = lambda: [good_cmd]

        with patch(
            "importlib.metadata.entry_points",
            return_value=[mock_ep_bad, mock_ep_good],
        ):
            discover_plugin_commands()

        all_cmds = get_all_commands()
        assert good_cmd in all_cmds

    def test_factory_raising_is_skipped(self) -> None:
        mock_ep = MagicMock()
        mock_ep.name = "crashy"

        def crashing_factory():
            raise RuntimeError("boom")

        mock_ep.load.return_value = crashing_factory

        with patch(
            "importlib.metadata.entry_points",
            return_value=[mock_ep],
        ):
            discover_plugin_commands()

    def test_factory_returning_non_list_is_skipped(self) -> None:
        mock_ep = MagicMock()
        mock_ep.name = "bad_return"
        mock_ep.load.return_value = lambda: "not a list"

        import nanobot.command.plugin as mod

        old_plugins = list(mod._plugin_commands)
        try:
            mod._plugin_commands.clear()
            with patch(
                "importlib.metadata.entry_points",
                return_value=[mock_ep],
            ):
                discover_plugin_commands()
            assert mod._plugin_commands == []
        finally:
            mod._plugin_commands[:] = old_plugins

    def test_non_plugincommand_items_skipped(self) -> None:
        mock_ep = MagicMock()
        mock_ep.name = "mixed"
        mock_ep.load.return_value = lambda: ["not a PluginCommand", 42]

        import nanobot.command.plugin as mod

        old_plugins = list(mod._plugin_commands)
        try:
            mod._plugin_commands.clear()
            with patch(
                "importlib.metadata.entry_points",
                return_value=[mock_ep],
            ):
                discover_plugin_commands()
            assert mod._plugin_commands == []
        finally:
            mod._plugin_commands[:] = old_plugins


# ---------------------------------------------------------------------------
# Integration: plugin command flows through router
# ---------------------------------------------------------------------------

class TestPluginCommandIntegration:
    @pytest.fixture()
    def router(self) -> CommandRouter:
        return CommandRouter()

    async def test_plugin_command_dispatches_and_returns_outbound(
        self, router: CommandRouter,
    ) -> None:
        from nanobot.bus.events import OutboundMessage

        async def plugin_handler(ctx: CommandContext) -> OutboundMessage:
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content=f"Deployed to {ctx.args.strip() or 'default'}",
            )

        cmd = PluginCommand("/deploy", "Trigger deploy", plugin_handler, arg_hint="<env>")
        router.register_plugin(cmd)

        ctx = CommandContext(
            msg=MagicMock(channel="test", chat_id="c1", metadata={}),
            session=None, key="test:c1", raw="/deploy production", loop=MagicMock(),
        )
        result = await router.dispatch(ctx)
        assert result is not None
        assert "Deployed to production" in result.content

    async def test_plugin_help_includes_plugin_command(
        self, router: CommandRouter, _ensure_builtins,
    ) -> None:
        async def plugin_handler(ctx: CommandContext) -> None:
            return None

        cmd = PluginCommand("/deploy", "Trigger a deployment", plugin_handler, arg_hint="<env>")
        register_builtin(cmd)
        router.register_plugin(cmd)

        text = build_help_text()
        assert "/deploy" in text
        assert "Trigger a deployment" in text


# ---------------------------------------------------------------------------
# Regex edge cases
# ---------------------------------------------------------------------------

class TestRegexEdgeCases:
    def test_empty_registry_produces_noop_pattern(self) -> None:
        import nanobot.command.plugin as mod

        old_builtins = list(mod._builtin_commands)
        old_plugins = list(mod._plugin_commands)
        try:
            mod._builtin_commands.clear()
            mod._plugin_commands.clear()
            pat = build_telegram_slash_regex()
            assert not pat.match("/anything")
            assert not pat.match("/new")
        finally:
            mod._builtin_commands[:] = old_builtins
            mod._plugin_commands[:] = old_plugins

    def test_pattern_is_compiled(self, _ensure_builtins) -> None:
        pat = build_telegram_slash_regex()
        assert isinstance(pat, re.Pattern)
