"""List-count and character truncation remain separately observable."""
from experiments.core.frame import AgentCtx, FrameField, FrameSpec, compile_frame, MAX_LISTED_CANDIDATES


def test_count_and_character_truncation_do_not_overwrite_each_other():
    spec = FrameSpec("t", (FrameField("history", 40, "history", clip="head"),))
    values = ["candidate-" + str(i) + ("x" * 30) for i in range(MAX_LISTED_CANDIDATES + 5)]
    frame = compile_frame(spec, AgentCtx(history=values))
    assert frame.count_truncations["history"] == (MAX_LISTED_CANDIDATES + 5, MAX_LISTED_CANDIDATES)
    assert frame.truncations["history"][0] > frame.truncations["history"][1]
    rendered = frame.render()
    assert "items 25→20" in rendered
    assert "chars" in rendered
