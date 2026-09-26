from jarvis.security.policy import Policy, ScriptMeta, TurnState, Verdict
from jarvis.tools.registry import Tool, ToolContext


async def _noop(args, ctx):
    return None


def tool(risk):
    return Tool("t", "", {}, [], _noop, risk=risk)


def test_read_always_allowed():
    assert Policy().check(tool("read"), ToolContext(), TurnState(tainted=True)) == Verdict.ALLOW


def test_critical_needs_confirmation():
    assert Policy().check(tool("critical"), ToolContext(), TurnState()) == Verdict.CONFIRM


def test_taint_forces_confirmation_for_write():
    assert Policy().check(tool("write"), ToolContext(), TurnState(tainted=True)) == Verdict.CONFIRM
    assert Policy().check(tool("write"), ToolContext(), TurnState()) == Verdict.ALLOW


def test_cloud_cannot_run_critical():
    assert Policy().check(tool("critical"), ToolContext(provider="cloud"), TurnState()) == Verdict.DENY


def test_car_blocks_script():
    ctx = ToolContext(in_car=True)
    assert Policy().check(tool("critical"), ctx, TurnState(), ScriptMeta(confirm=True, car_allowed=False)) == Verdict.DENY


def test_script_without_confirm():
    assert Policy().check(tool("critical"), ToolContext(), TurnState(), ScriptMeta(confirm=False)) == Verdict.ALLOW
