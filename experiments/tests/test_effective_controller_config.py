"""Runtime metadata must distinguish effective ablation settings."""
from experiments.core.runner import _controller_config, _controller_config_digest
from experiments.scripts.run import resolve_agent
from experiments.tests.test_typed_controller import ScriptedClient


def test_actual_admission_variants_have_distinct_effective_configs():
    configs = {}
    for name in ("react-typed", "react-typed-admission", "react-typed-admission-choice",
                 "react-typed-admission-suffices"):
        agent = resolve_agent(name, ScriptedClient())()
        config = _controller_config(agent)
        assert "client" not in config and "trace" not in config and "redirects" not in config
        configs[name] = config
    assert configs["react-typed-admission"]["admission_answer_kind"] == "noul"
    assert configs["react-typed-admission-choice"]["admission_answer_kind"] == "choice"
    assert configs["react-typed-admission-suffices"]["admission_question_form"] == "suffices"
    assert len({_controller_config_digest(c) for c in configs.values()}) == 4


def test_runtime_mutation_does_not_change_effective_configuration():
    agent = resolve_agent("react-typed", ScriptedClient())()
    before = _controller_config(agent)
    agent.config.controller.redirects = 9
    agent.config.controller.trace.append({"runtime": True})
    assert _controller_config(agent) == before


def test_dictionary_order_does_not_change_config_digest():
    assert _controller_config_digest({"a": 1, "b": 2}) == _controller_config_digest({"b": 2, "a": 1})
