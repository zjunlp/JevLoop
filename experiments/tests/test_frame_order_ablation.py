"""A6 reorders only the longest pickInput field; budgets stay fixed."""
from experiments.core.frame import NODE_FRAMES, AgentCtx, compile_frame


def test_action_table_is_last():
    """A6 的顺序结论不变；预算那一半在 2026-10-05 被整体删掉了。"""
    spec = NODE_FRAMES["pickInput"]
    assert spec.fields[-1].name == "action_table"
    assert [f.name for f in spec.fields] == [
        "task", "action_rules", "history", "last_result", "redirect_note", "action_table"]
    assert all(f.budget is None for f in spec.fields), "逐字段预算应当已经全部删掉"
    frame = compile_frame(spec, AgentCtx(task="task", action_table="[1] act",
                                        action_rules="rules", last_result="observation"))
    body = "\n".join(frame.lines)
    assert body.index("task:") < body.index("how_this_world_works:") < body.index("actions_on_the_table:")
