"""Plugin management functions shared by CLI and slash commands."""

from __future__ import annotations

import importlib
import json
import shutil
import sys
from pathlib import Path

from nanobot.config.paths import get_plugins_dir, get_plugins_manifest_path


def install_plugin(path: str, name: str | None = None) -> tuple[bool, str]:
    """Install a plugin from a local directory into ~/.nanobot/plugins/.

    Returns (success, message).
    """
    src = Path(path).expanduser().resolve()
    if not src.is_dir():
        return False, f"'{path}' is not a directory"

    pkg_dir = src
    if not (pkg_dir / "__init__.py").exists() and (src / "pyproject.toml").exists():
        import tomllib
        try:
            pyproject = src / "pyproject.toml"
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            pkg_name = data.get("project", {}).get("name", "").replace("-", "_")
            candidate = src / pkg_name
            if candidate.is_dir() and (candidate / "__init__.py").exists():
                pkg_dir = candidate
            else:
                for sub in sorted(src.iterdir()):
                    if sub.is_dir() and (sub / "__init__.py").exists():
                        pkg_dir = sub
                        break
        except Exception:
            for sub in sorted(src.iterdir()):
                if sub.is_dir() and (sub / "__init__.py").exists():
                    pkg_dir = sub
                    break

    if not (pkg_dir / "__init__.py").exists():
        return False, f"'{path}' is not a Python package (missing __init__.py)"

    install_name = name or pkg_dir.name
    plugins_dir = get_plugins_dir()
    dest = plugins_dir / install_name

    if dest.exists():
        shutil.rmtree(dest)

    shutil.copytree(pkg_dir, dest)

    manifest_path = get_plugins_manifest_path()
    manifest: dict = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plugins_list: list = manifest.setdefault("plugins", [])
    if install_name not in plugins_list:
        plugins_list.append(install_name)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return True, f"Installed plugin '{install_name}' from {pkg_dir}\nRestart the gateway to load the plugin."


def uninstall_plugin(name: str) -> tuple[bool, str]:
    """Remove a previously installed plugin.

    Returns (success, message).
    """
    plugins_dir = get_plugins_dir()
    dest = plugins_dir / name
    if not dest.exists():
        return False, f"Plugin '{name}' is not installed."

    shutil.rmtree(dest)

    manifest_path = get_plugins_manifest_path()
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        plugins_list: list = manifest.get("plugins", [])
        if name in plugins_list:
            plugins_list.remove(name)
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return True, f"Uninstalled plugin '{name}'."


def list_plugins() -> str:
    """Return a formatted string listing all registered commands and installed plugins."""
    from nanobot.command.builtin import register_builtin_commands
    from nanobot.command.plugin import (
        _builtin_commands,
        discover_plugin_commands,
        get_all_commands,
    )
    from nanobot.command.router import CommandRouter

    manifest_path = get_plugins_manifest_path()
    loose_names: set[str] = set()
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        loose_names = set(manifest.get("plugins", []))

    if not _builtin_commands:
        register_builtin_commands(CommandRouter())
    discover_plugin_commands()
    all_cmds = get_all_commands()

    lines = ["## Command Plugins", ""]
    lines.append(f"{'Command':<24} {'Source':<12} Description")
    lines.append(f"{'─' * 24} {'─' * 12} {'─' * 40}")

    for cmd in all_cmds:
        source = "builtin" if cmd in _builtin_commands else "plugin"
        lines.append(f"{cmd.command:<24} {source:<12} {cmd.description}")

    lines.append("")
    if loose_names:
        lines.append(f"Installed loose plugins: {', '.join(sorted(loose_names))}")
    lines.append(f"Plugins directory: {get_plugins_dir()}")

    return "\n".join(lines)


def reload_plugins(router=None) -> tuple[bool, str]:
    """Reload loose plugin modules and re-discover plugin commands.

    If *router* is provided, newly discovered plugin commands are registered.
    Returns (success, message).
    """
    from nanobot.command.plugin import _plugin_commands, discover_plugin_commands

    plugins_dir = get_plugins_dir()

    # Reload any already-imported loose plugin modules
    reloaded: list[str] = []
    failed: list[str] = []
    plugins_path_str = str(plugins_dir)
    for mod_name, mod in list(sys.modules.items()):
        if mod is None:
            continue
        mod_file = getattr(mod, "__file__", None)
        if mod_file and mod_file.startswith(plugins_path_str):
            try:
                importlib.reload(mod)
                reloaded.append(mod_name)
            except Exception:
                failed.append(mod_name)

    # Re-discover commands
    discover_plugin_commands()

    # Re-register with router if provided
    new_count = 0
    if router is not None:
        from nanobot.command.plugin import get_all_commands
        for cmd in get_all_commands():
            if not router.has_command(cmd.command):
                router.register_plugin(cmd)
                new_count += 1

    parts: list[str] = []
    if reloaded:
        parts.append(f"Reloaded {len(reloaded)} module(s): {', '.join(reloaded)}")
    if failed:
        parts.append(f"Failed to reload {len(failed)} module(s): {', '.join(failed)}")
    parts.append(f"Discovered {len(_plugin_commands)} plugin command(s).")
    if new_count > 0:
        parts.append(f"Registered {new_count} new command(s) with the router.")

    return True, " ".join(parts)
