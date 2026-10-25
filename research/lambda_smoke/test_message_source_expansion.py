"""Validate the wired source-market stack and pre-inference execution gates."""
import copy
import json
from pathlib import Path

import pytest

from research.lambda_smoke import message_source_expansion as source
from research.lambda_smoke import message_channel_overnight as io
from research.lambda_smoke import message_channel_probe as p


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    root = tmp_path_factory.mktemp("source") / "synthetic"
    source.prepare(root, backend="synthetic")
    return root


def test_source_plan_preserves_scientific_protocol(prepared):
    plan = source.load(prepared)
    original = io.read(p._bundle_index()["seed_20_partial_on"] / "protocol.json")
    for job in plan["jobs"]:
        config = dict(job["protocol"], seeds=original["seeds"])
        assert config == original
        assert job["maximum_market_requests"] == 200
        assert job["market_decisions"] == 100
    assert plan["market_seeds"] == [40,41,42,43]
    assert plan["maximum_requests"] == 808
    assert plan["source_phase_full_reservation_usd"] < 10
    assert plan["total_phase_allocations_usd"] == 20 < plan["balance_user_reported_usd"]


def test_real_market_stack_synthetic_run_and_seal(prepared):
    job = "seed_40_partial_on"
    assert source.source_worker(prepared, job, "synthetic") == 0
    bundle = prepared / "cells" / job
    p.verify(bundle)
    meta = io.read(bundle / "bundle.json")
    assert meta["backend"] == "synthetic" and meta["status"] == "complete"
    assert meta["actual_requests"] == 0  # synthetic backend performs no HTTP inference
    assert io.read(bundle / "final_summary.json")["accepted_actions"] == 100
    rounds = p._market_rounds(bundle,40)
    assert len(rounds) == 10
    observations = p.load_jsonl(bundle / "observations.jsonl")
    assert len(observations) == 100
    assert sum(o["role"] == "seller" for o in observations) == 50
    assert all(o["rendered_observation"] == o["true_observation"] for o in observations if o["role"] == "buyer")
    assert all(o["mode"] == "partial" for o in observations)
    assert all(o["true_observation"] and o["rendered_observation"] for o in observations)
    before = p.sha_file(bundle / "checksums.json")
    with pytest.raises(FileExistsError):
        source.source_worker(prepared, job, "synthetic")
    assert p.sha_file(bundle / "checksums.json") == before


def test_synthetic_cannot_start_paid_host_or_supply_research_states(prepared, monkeypatch):
    monkeypatch.setattr(source, "execute_host", lambda *args: pytest.fail("Paid host called"))
    with pytest.raises(RuntimeError, match="paid host requires live"):
        source.batch(prepared)
    bundle = prepared / "cells/seed_40_partial_on"
    if bundle.exists():
        with pytest.raises(ValueError, match="complete live"):
            source.collect_candidates([bundle])


def test_source_selection_matches_original_audit():
    states, audit, inventory = source.collect_candidates(list(p._bundle_index().values()))
    old = io.read(p.ROOT / "output/message_channel_modal_v2_recovered/plan.json")
    identity = lambda s: (s["seed"],s["round"],s["sender"],s["recipient"])
    assert {identity(s) for s in states} == {identity(s) for s in old["states"]}
    assert len(audit) == 688 and len(inventory) == 4
    for state in states:
        assert state["conditions"]["hidden_original"]["prompt"] == state["prompt"]


def test_source_status_detects_failed_or_active_session(tmp_path):
    root = tmp_path / "live"
    source.prepare(root)
    session = root / "sessions/seed_40_partial_on"
    session.mkdir()
    io.save(session/"started.json", {"phase":"sources"})
    status = source.phase_status(root,"sources")
    assert status["sessions_started"] == 1 and status["failed_or_active"]
    assert status["charged_time_reservations_usd"] == source.RESERVATION
    with pytest.raises(RuntimeError, match="previous failure"):
        source.batch(root)


def test_budget_refuses_insufficient_reservation(tmp_path, monkeypatch):
    root = tmp_path / "live"
    source.prepare(root)
    status = source.phase_status(root,"sources")
    status["budget_remaining_usd"] = 0
    monkeypatch.setattr(source,"phase_status",lambda *args:status)
    monkeypatch.setattr(source,"execute_host",lambda *args:pytest.fail("Host called after budget exhaustion"))
    with pytest.raises(RuntimeError, match="Insufficient resource budget"):
        source.batch(root)
    assert not list((root/"sessions").iterdir())


def test_resource_capped_host_definition_is_accepted_by_installed_sdk():
    from poseidon_compute import message_source_host as host
    assert host.RESOURCE_SPEC["cpu_limit"] == 4
    assert host.RESOURCE_SPEC["memory_limit_mib"] == 32768
    assert host.RESOURCE_SPEC["container_watchdog_seconds"] == source.RESOURCE_SECONDS
    assert host.app is not None and host.serve is not None


def test_three_way_sampler_does_not_duplicate_selected_states():
    states,_,_ = source.collect_candidates(list(p._bundle_index().values()))
    selected = source.select_diverse(states)
    assert len(selected) == len({(s['seed'],s['round'],s['sender'],s['recipient']) for s in selected}) == 10


def test_integer_price_reports_keep_their_precision_in_new_plan():
    states,_,_ = source.collect_candidates(list(p._bundle_index().values()))
    state = copy.deepcopy(states[0])
    original = state["message_line"]
    token = p.PRICE.search(state["message"])
    state["message"] = state["message"].replace(token.group(0), f"${state['quote_price']:.0f}", 1)
    state["message_line"] = f"- From {state['sender']}: {state['message']}"
    state["prompt"] = state["prompt"].replace(original,state["message_line"],1)
    state["conditions"] = p.build_prompts(state)
    plan = dict(states=[state],seeds=[1001,1002,1003],decisions=30,maximum_requests=31,warmup_requests=1)
    assert source.validate_probe(plan)
    assert f"${state['quote_price']+10:.0f}" in state["conditions"]["hidden_up10"]["prompt"]


def test_timeout_closes_host_context_and_stops_child(monkeypatch):
    from contextlib import contextmanager
    from poseidon_compute import message_source_host as host
    events = []
    @contextmanager
    def fake_host():
        events.append("open")
        try:
            yield
        finally:
            events.append("closed")
    class Process:
        count = 0
        def wait(self,timeout=None):
            self.count += 1
            if self.count == 1:
                raise host.subprocess.TimeoutExpired("worker",timeout)
            return 0
        def poll(self): return None
        def send_signal(self,signal): events.append("interrupted")
    monkeypatch.setattr(host,"hosted",fake_host)
    monkeypatch.setattr(host.subprocess,"Popen",lambda *a,**kw:Process())
    with pytest.raises(host.subprocess.TimeoutExpired):
        host.run_command(["worker"])
    assert events == ["open","interrupted","closed"]
