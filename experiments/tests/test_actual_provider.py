"""Planned and actual decision providers must be distinguishable."""
from experiments.core.deciding import Answer, DecideRequest, DecideResponse, FallbackClient
from experiments.tests.test_typed_controller import make_session


class Broken:
    name = "planned"
    def decide(self, request):
        raise RuntimeError("offline")


class Actual:
    name = "actual"
    def decide(self, request):
        return DecideResponse(answers={"q": Answer(kind="noul", noul=.9)}, provider=self.name)


def test_fallback_records_actual_provider_and_forces_degradation():
    response = FallbackClient([Broken(), Actual()]).decide(DecideRequest(state={}, questions={}))
    assert response.provider == "planned"
    assert response.actual_provider == "actual"
    assert response.fallback_chain == ["planned", "actual"]
    assert response.degraded is True


def test_actual_provider_survives_batch_event_and_runtime_accounting():
    session = make_session()
    session.note_batch(provider="planned", actual_provider="actual", fallback_chain=["planned", "actual"], degraded=True)
    session.record_decision(step=0, node="q", answer=".9", confidence=.9, correct=True, latency_ms=0, batch=1)
    session.finish_events()
    event = session.decision_batches()[0]
    assert event.provider == "planned"
    assert event.actual_provider == "actual"
    assert event.fallback_chain == ["planned", "actual"]
    assert session.decider_providers == ["actual"]
