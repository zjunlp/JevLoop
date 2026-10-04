"""A1a changes the response type, not frame, ranking target or escape bar."""
import pytest

from experiments.core.deciding import Answer, DecideResponse
from experiments.jloop.typed import TypedController
from experiments.tests.test_typed_controller import ScriptedClient, make_session, _view


class AdmissionClient(ScriptedClient):
    def __init__(self, probability):
        super().__init__(noul={"needsTool": 0.9, "needs_auth": 0.1})
        self.probability = probability

    def decide(self, request):
        response = super().decide(request)
        for node, question in request.questions.items():
            if node.startswith("pickInput::"):
                p = self.probability
                if question["type"] == "choice":
                    # A confident 'false' must not be mistaken for P(true).
                    response.answers[node] = Answer(
                        kind="choice", choice="true" if p >= 0.5 else "false",
                        probabilities={"true": p, "false": 1-p, "unclear": 0.0})
                else:
                    response.answers[node] = Answer(kind="noul", noul=p)
        return response


def run(kind, p, form="relational"):
    client = AdmissionClient(p)
    session = make_session()
    ctl = TypedController(client, pick_input_shape="admission", admission_answer_kind=kind,
                         admission_question_form=form)
    decision = ctl.decide(session, _view(session))
    requests = [r for r in client.requests if any(n.startswith("pickInput::") for n in r.questions)]
    assert requests
    return decision, requests[0], ctl


def test_only_answer_type_changes_frame_and_prompt_stay_equal():
    _, boolean, _ = run("noul", 0.9)
    decision, choice, _ = run("choice", 0.9)
    assert boolean.state == choice.state
    assert list(boolean.questions) == list(choice.questions)
    for node, q in choice.questions.items():
        control = boolean.questions[node]
        assert q["instructions"] == control["instructions"]
        assert q["type"] == "choice"
        assert set(q["criteria"]) == {"true", "false", "unclear"}
        for label in ("true", "false"):
            assert q["criteria"][label] == control["criteria"][label]
    assert decision.kind == "tool"


def test_high_false_probability_is_not_positive_admission():
    decision, _, ctl = run("choice", 0.05)
    assert decision.kind != "tool"
    ranked = [r for r in ctl.trace if r.get("answer") == "none_cleared_the_bar"]
    assert ranked and ranked[0]["top"] == 0.05


def test_only_question_form_changes_prompt():
    _, relational, _ = run("noul", 0.9, "relational")
    _, suffices, _ = run("noul", 0.9, "suffices")
    for node in relational.questions:
        assert relational.questions[node]["type"] == suffices.questions[node]["type"] == "noul"
        assert relational.questions[node]["criteria"] == suffices.questions[node]["criteria"]
        assert relational.questions[node]["instructions"] != suffices.questions[node]["instructions"]


def test_unknown_answer_kind_raises():
    with pytest.raises(ValueError, match="Unknown admission answer kind"):
        run("typo", 0.9)
