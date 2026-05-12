"""Tests for Long Task Tool: HandoffTool, CompleteTool, LongTaskTool."""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.tools.long_task import (
    HandoffState,
    HandoffTool,
    CompleteTool,
    LongTaskTool,
    LongTaskEvent,
    _build_system_prompt,
    _build_user_message,
    _extract_file_changes,
    _extract_handoff_from_messages,
)


# ---------------------------------------------------------------------------
# Signal tool tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handoff_tool_stores_structured_signal():
    store = HandoffState()
    tool = HandoffTool(store)
    result = await tool.execute(
        message="Processed items 1-8. Results in out.md.",
        files_created=["out.md", "report.md"],
        files_modified=["main.py"],
        next_step_hint="Continue with item 9.",
        verification="Tests passed",
    )
    assert result == "Progress recorded. The next step will continue from here."
    assert store.message == "Processed items 1-8. Results in out.md."
    assert store.files_created == ["out.md", "report.md"]
    assert store.files_modified == ["main.py"]
    assert store.next_step_hint == "Continue with item 9."
    assert store.verification == "Tests passed"


@pytest.mark.asyncio
async def test_handoff_tool_defaults_optional_fields():
    store = HandoffState()
    tool = HandoffTool(store)
    await tool.execute(message="Done.")
    assert store.files_created == []
    assert store.files_modified == []
    assert store.next_step_hint == ""
    assert store.verification == ""


@pytest.mark.asyncio
async def test_complete_tool_stores_signal():
    store = HandoffState()
    tool = CompleteTool(store)
    result = await tool.execute(summary="All 100 items processed. Summary in report.md")
    assert result == "Task marked as complete. Awaiting validation."
    assert store.message == "All 100 items processed. Summary in report.md"


@pytest.mark.asyncio
async def test_signal_tools_overwrite_on_multiple_calls():
    """Last call wins — the orchestrator only reads the final signal."""
    store = HandoffState()
    handoff = HandoffTool(store)
    complete = CompleteTool(store)
    await handoff.execute(message="first progress")
    assert store.message == "first progress"
    await complete.execute(summary="done early")
    assert store.message == "done early"


# ---------------------------------------------------------------------------
# Helper: minimal SubagentManager stub
# ---------------------------------------------------------------------------


def _make_manager_stub():
    """Create a minimal SubagentManager stub with a mockable run_step."""
    mgr = MagicMock()
    mgr.run_step = AsyncMock()
    return mgr


def _step_result(**overrides):
    """Create a minimal AgentRunResult-like namespace."""
    defaults = dict(
        final_content="step done",
        messages=[],
        tool_events=[],
        stop_reason="completed",
        tools_used=[],
        usage={},
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# LongTaskTool orchestrator tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_long_task_completes_in_one_step():
    """Subagent calls complete() immediately, validation passes."""
    mgr = _make_manager_stub()
    call_count = 0

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="All done. Report in summary.md")
            return _step_result(
                final_content="All done.",
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )
        else:
            # Validation round
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="Validated")
            return _step_result(
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    result = await tool.execute(goal="Audit all issues.")
    assert result == "All done. Report in summary.md"
    assert call_count == 2  # main step + validation


@pytest.mark.asyncio
async def test_long_task_completes_after_multiple_handoffs():
    """Subagent calls handoff() twice then complete(), validation passes."""
    mgr = _make_manager_stub()
    call_count = 0

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            for t in extra_tools:
                if t.name == "handoff":
                    await t.execute(message="Processed 1-8.")
            return _step_result(
                tools_used=["handoff"],
                tool_events=[{"name": "handoff", "status": "ok", "detail": ""}],
            )
        elif call_count == 2:
            assert "Processed 1-8." in user_message
            assert "Step 2" in user_message or "Step 2 of" in user_message
            for t in extra_tools:
                if t.name == "handoff":
                    await t.execute(message="Processed 9-16.")
            return _step_result(
                tools_used=["handoff"],
                tool_events=[{"name": "handoff", "status": "ok", "detail": ""}],
            )
        elif call_count == 3:
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="All 16 items audited.")
            return _step_result(
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )
        else:
            # Validation round
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="Validated")
            return _step_result(
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    result = await tool.execute(goal="Audit 16 issues.")
    assert result == "All 16 items audited."
    assert call_count == 4  # 3 main steps + validation


@pytest.mark.asyncio
async def test_long_task_validation_falls_back_to_handoff():
    """Subagent claims complete but validation fails — task continues."""
    mgr = _make_manager_stub()
    call_count = 0

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First step claims complete
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="Done.")
            return _step_result(
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )
        elif call_count == 2:
            # Validation round fails (handoff called)
            for t in extra_tools:
                if t.name == "handoff":
                    await t.execute(message="Not actually done. Need more work.")
            return _step_result(
                tools_used=["handoff"],
                tool_events=[{"name": "handoff", "status": "ok", "detail": ""}],
            )
        elif call_count == 3:
            # Continue and complete for real
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="Really done.")
            return _step_result(
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )
        else:
            # Second validation passes
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="Validated")
            return _step_result(
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    result = await tool.execute(goal="Do something.", max_steps=5)
    assert "Really done." == result
    assert call_count == 4


@pytest.mark.asyncio
async def test_long_task_fallback_when_no_signal_called():
    """Subagent doesn't call handoff/complete — extract progress from messages."""
    mgr = _make_manager_stub()

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        return _step_result(
            final_content="Tool budget exhausted.",
            messages=[
                {"role": "system", "content": "..."},
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "I processed items 1-5. Results in out.md."},
                {"role": "tool", "content": "ok"},
                {"role": "assistant", "content": "Tool budget exhausted. Call handoff() earlier next time."},
            ],
            stop_reason="max_iterations",
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    result = await tool.execute(goal="Do something.", max_steps=2)
    # Should reach max_steps and return the fallback extracted from messages
    assert "max steps (2)" in result
    assert "I processed items 1-5" in result


@pytest.mark.asyncio
async def test_long_task_auto_extracts_on_natural_end():
    """Subagent finishes naturally (stop_reason=completed) without calling signal."""
    mgr = _make_manager_stub()
    call_count = 0

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _step_result(
                final_content="I processed items 1-5. Results in out.md.",
                stop_reason="completed",
            )
        elif call_count == 2:
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="All done.")
            return _step_result(
                final_content="All done.",
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )
        else:
            # Validation
            for t in extra_tools:
                if t.name == "complete":
                    await t.execute(summary="Validated")
            return _step_result(
                tools_used=["complete"],
                tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
            )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    result = await tool.execute(goal="Process items.", max_steps=5)
    assert "All done." == result
    assert call_count == 3


@pytest.mark.asyncio
async def test_long_task_retries_on_crash():
    """A step that crashes once should be retried."""
    mgr = _make_manager_stub()
    call_count = 0

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Simulated crash")
        for t in extra_tools:
            if t.name == "complete":
                await t.execute(summary="Recovered.")
        return _step_result(
            tools_used=["complete"],
            tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    result = await tool.execute(goal="Test retry.")
    assert "Recovered." == result
    assert call_count == 3  # main step + retry + validation


@pytest.mark.asyncio
async def test_long_task_fails_after_two_crashes():
    """A step that crashes twice should terminate the task."""
    mgr = _make_manager_stub()

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        raise RuntimeError("Persistent crash")

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    result = await tool.execute(goal="Test failure.", max_steps=3)
    assert "failed at step 1/3" in result
    assert tool.status == "error"


@pytest.mark.asyncio
async def test_long_task_uses_dynamic_budget():
    """Final steps should use lower max_iterations."""
    mgr = _make_manager_stub()
    captured_budgets = []

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        captured_budgets.append(max_iterations)
        for t in extra_tools:
            if t.name == "complete":
                await t.execute(summary="Done.")
        return _step_result(
            tools_used=["complete"],
            tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    await tool.execute(goal="Test budget.", max_steps=5)
    # Step 0-2 should use 8, step 3+ should use 4
    # But we complete on step 0, so only one budget captured
    assert captured_budgets[0] == 8


# ---------------------------------------------------------------------------
# Hook and observability tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hooks_receive_events():
    """Registered hooks should be called during execution."""
    mgr = _make_manager_stub()
    events = []

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        for t in extra_tools:
            if t.name == "complete":
                await t.execute(summary="Done.")
        return _step_result(
            tools_used=["complete"],
            tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    tool.set_hooks({
        "on_task_start": lambda **kw: events.append(("task_start", kw)),
        "on_step_start": lambda **kw: events.append(("step_start", kw)),
        "on_step_complete": lambda **kw: events.append(("step_complete", kw)),
        "on_validation_started": lambda **kw: events.append(("validation_started", kw)),
        "on_task_complete": lambda **kw: events.append(("task_complete", kw)),
    })
    await tool.execute(goal="Test hooks.")

    assert any(e[0] == "task_start" for e in events)
    assert any(e[0] == "step_start" for e in events)
    assert any(e[0] == "step_complete" for e in events)
    assert any(e[0] == "validation_started" for e in events)
    assert any(e[0] == "task_complete" for e in events)


@pytest.mark.asyncio
async def test_catch_all_hook_receives_events():
    """The on_event catch-all hook should receive all events."""
    mgr = _make_manager_stub()
    events = []

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        for t in extra_tools:
            if t.name == "complete":
                await t.execute(summary="Done.")
        return _step_result(
            tools_used=["complete"],
            tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    tool.set_hooks({
        "on_event": lambda ev: events.append(ev.type),
    })
    await tool.execute(goal="Test catch-all.")

    assert "task_start" in events
    assert "step_start" in events
    assert "task_complete" in events


@pytest.mark.asyncio
async def test_state_exposure():
    """Properties should reflect current execution state."""
    mgr = _make_manager_stub()

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        for t in extra_tools:
            if t.name == "handoff":
                await t.execute(message="Progress.")
        return _step_result(
            tools_used=["handoff"],
            tool_events=[{"name": "handoff", "status": "ok", "detail": ""}],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    assert tool.status == "idle"

    # Start execution in background so we can inspect mid-run
    import asyncio
    task = asyncio.create_task(tool.execute(goal="Test state.", max_steps=3))
    # Give it a moment to start
    await asyncio.sleep(0.01)
    # Task should have finished by now since mocks are instant
    await task

    assert tool.goal == "Test state."
    assert tool.total_steps == 3
    assert tool.status == "error"  # max_steps reached
    assert tool.last_handoff.message == "Progress."


@pytest.mark.asyncio
async def test_inject_correction():
    """User correction should appear in the next step's user message."""
    mgr = _make_manager_stub()
    captured_messages = []

    async def fake_run_step(*, system_prompt, user_message, extra_tools, max_iterations=None):
        captured_messages.append(user_message)
        for t in extra_tools:
            if t.name == "complete":
                await t.execute(summary="Done.")
        return _step_result(
            tools_used=["complete"],
            tool_events=[{"name": "complete", "status": "ok", "detail": ""}],
        )

    mgr.run_step.side_effect = fake_run_step
    tool = LongTaskTool(manager=mgr)
    tool.inject_correction("Focus on error handling.")
    await tool.execute(goal="Refactor code.")

    assert any("Focus on error handling" in msg for msg in captured_messages)


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


def test_build_system_prompt():
    prompt = _build_system_prompt(budget=8)
    assert "handoff()" in prompt
    assert "complete()" in prompt
    assert "8 tool calls" in prompt


def test_build_user_message_step_0():
    msg = _build_user_message("Audit all issues.", step=0, max_steps=20, handoff=HandoffState())
    assert "Audit all issues." in msg
    assert "Step 1 of 20" in msg
    assert "8 tool calls" in msg
    assert "Previous Progress" not in msg


def test_build_user_message_later_step():
    handoff = HandoffState(message="Did 1-10.", files_created=["a.py"], next_step_hint="Do Y")
    msg = _build_user_message("Audit all issues.", step=3, max_steps=20, handoff=handoff)
    assert "Audit all issues." in msg
    assert "Previous Progress" in msg
    assert "Did 1-10." in msg
    assert "a.py" in msg
    assert "Do Y" in msg
    assert "Step 4 of 20" in msg


def test_build_user_message_final_step():
    handoff = HandoffState(message="Almost done.")
    msg = _build_user_message("Audit all issues.", step=18, max_steps=20, handoff=handoff)
    assert "FINAL Step" in msg
    assert "4 tool calls" in msg  # final steps use lower budget


def test_build_user_message_with_correction():
    msg = _build_user_message(
        "Audit.", step=0, max_steps=20, handoff=HandoffState(), correction="Skip file A"
    )
    assert "User Correction" in msg
    assert "Skip file A" in msg


def test_extract_handoff_from_messages():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "do it"},
        {"role": "assistant", "content": ""},
        {"role": "tool", "content": "result"},
        {"role": "assistant", "content": "I processed items 1-3."},
    ]
    assert _extract_handoff_from_messages(messages) == "I processed items 1-3."


def test_extract_handoff_skips_budget_message():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "do it"},
        {"role": "assistant", "content": "I processed items 1-3."},
        {"role": "tool", "content": "result"},
        {"role": "assistant", "content": "Tool budget exhausted. Call handoff() earlier."},
    ]
    # Should skip the budget message and find the actual progress
    assert _extract_handoff_from_messages(messages) == "I processed items 1-3."


def test_extract_handoff_from_empty_messages():
    assert _extract_handoff_from_messages([]) == ""
    assert _extract_handoff_from_messages([{"role": "system", "content": "sys"}]) == ""


def test_extract_file_changes_from_tool_events():
    events = [
        {"name": "write_file", "status": "ok", "detail": "Wrote /workspace/a.py: done"},
        {"name": "edit_file", "status": "ok", "detail": "Edited /workspace/b.py: patched"},
        {"name": "read_file", "status": "ok", "detail": "Read /workspace/c.py"},
        {"name": "write_file", "status": "error", "detail": "Failed"},
    ]
    created, modified = _extract_file_changes(events)
    assert created == ["/workspace/a.py"]
    assert modified == ["/workspace/b.py"]


def test_extract_file_changes_empty():
    assert _extract_file_changes([]) == ([], [])


# ---------------------------------------------------------------------------
# Integration: verify LongTaskTool is wired into the main agent loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_long_task_registered_in_tool_registry(tmp_path):
    """Verify LongTaskTool appears in the main agent's tool registry."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
    tool = loop.tools.get("long_task")
    assert tool is not None
    assert tool.name == "long_task"
