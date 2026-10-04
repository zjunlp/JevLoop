"""A6 reorders only the longest pickInput field; budgets stay fixed."""
from experiments.core.frame import NODE_FRAMES, AgentCtx, compile_frame


def test_action_table_is_last_with_unchanged_budget():
    spec = NODE_FRAMES["pickInput"]
    assert spec.fields[-1].name == "action_table"
    assert spec.fields[-1].budget == 6000
    budgets = {f.name: f.budget for f in spec.fields}
    assert budgets == {"task": 2000, "action_table": 6000, "action_rules": 2500,
                       "history": 4000, "last_result": 4000, "redirect_note": 1500}
    frame = compile_frame(spec, AgentCtx(task="task", action_table="[1] act",
                                        action_rules="rules", last_result="observation"))
    body = "\n".join(frame.lines)
    assert body.index("task:") < body.index("how_this_world_works:") < body.index("actions_on_the_table:")
