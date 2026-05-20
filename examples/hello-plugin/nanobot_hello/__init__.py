"""A minimal nanobot plugin that registers a /hello command.

Install with ``pip install -e .`` from this directory, then restart nanobot.
"""

from nanobot.command.plugin import PluginCommand


async def _hello_handler(ctx):
    """Reply 'world' to /hello."""
    from nanobot.bus.events import OutboundMessage

    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="world",
    )


def get_commands() -> list[PluginCommand]:
    return [
        PluginCommand(
            command="/hello",
            description="Say hello to the bot",
            handler=_hello_handler,
            title="Hello",
            icon="hand",
        )
    ]
