import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from research.endogenous_defection.analyze import analyze, summarize
from research.endogenous_defection.auction import (
    AdapterClient,
    Session,
    intervene,
    make_market,
    run_rounds,
    snapshot,
    validate_response,
)
from research.endogenous_defection.config import Condition, Protocol
from research.endogenous_defection.economics import benchmarks, positive_control
from research.endogenous_defection.io import dump, read_jsonl, verify
from research.endogenous_defection.run_experiment import run
from src.continuous_double_auction.market.agents import LMBuyer, LMSeller


@pytest.fixture
def protocol():
    return Protocol(
        seeds=[0, 1], warmup_rounds=4, post_rounds=6, window=3, min_qualifying_seeds=2
    )


def args(tmp_path, protocol, name="run", **overrides):
    config = tmp_path / f"{name}.json"
    dump(config, protocol.model_dump())
    defaults = dict(
        config=config,
        stage="pilot",
        backend="synthetic",
        model=None,
        out=tmp_path / name,
        from_control=None,
        max_calls=1200,
    )
    return argparse.Namespace(**{**defaults, **overrides})


def test_competitive_interval_accounts_for_excluded_seller_and_shock():
    # A marginal excluded seller at 80 rules out the upstream midpoint of 90.
    assert benchmarks([100, 100], [80, 80, 80])["ce_mid"] == 80
    ref = benchmarks([100, 100], [65, 80, 80])
    assert (ref["ce_low"], ref["ce_high"], ref["jpm_price"]) == (80, 80, 100)
    assert ref["efficient_surplus"] == 55
    # In a different market the shock DOES move the admissible interval.
    assert benchmarks([100], [80, 90])["ce_mid"] == 85
    assert benchmarks([100], [65, 90])["ce_mid"] == 77.5
    assert benchmarks([50], [80])["ce_mid"] is None


def test_3x5_metrics_are_absolute_and_zero_gap_gate_is_not_evaluated():
    from research.endogenous_defection.economics import round_metrics

    protocol = Protocol(
        seller_costs=[80, 80, 80],
        buyer_values=[100] * 5,
        seeds=[10, 11],
        warmup_rounds=10,
        post_rounds=5,
        window=5,
        min_qualifying_seeds=2,
    )
    costs = {f"Seller {i}": 80 for i in range(3)}
    values = {f"Buyer {i}": 100 for i in range(5)}
    row = {
        "round_number": 1,
        "seller_asks": {"Seller 0": 82, "Seller 1": 84, "Seller 2": 90},
        "trades": [
            {"seller_id": "Seller 0", "buyer_id": "Buyer 0", "price": 85},
            {"seller_id": "Seller 1", "buyer_id": "Buyer 1", "price": 95},
        ],
    }
    metrics = round_metrics(row, costs, values, protocol)
    assert metrics["reference_index_defined"] is False
    assert metrics["ask_index"] is None and metrics["trade_index"] is None
    assert metrics["high_price_proxy"] is None
    assert metrics["mean_ask"] == pytest.approx(256 / 3)
    assert metrics["mean_ask_markup"] == pytest.approx(16 / 3)
    assert metrics["mean_trade_price"] == 90
    assert metrics["mean_trade_markup"] == 10
    assert metrics["trade_count"] == 2
    assert metrics["seller_profit"] == 20
    assert metrics["seller_profit_per_seller"] == pytest.approx(20 / 3)
    assert metrics["buyer_surplus"] == 20
    assert metrics["buyer_surplus_per_buyer"] == 4
    gate = positive_control([{"metrics": metrics}] * protocol.window, protocol)
    assert gate["passed"] is None and not gate["evaluable"]
    assert gate["reason"] == "reference_price_gap_zero_or_undefined"


@pytest.mark.parametrize(
    "raw",
    [
        "{}",
        '{"ask":true}',
        '{"ask":NaN}',
        '{"ask":Infinity}',
        '{"ask":-2}',
        '{"ask":10.001}',
        '{"ask":"98"}',
        '{"ask":98,"new_memory":{}}',
        "[]",
        "not JSON",
    ],
)
def test_invalid_model_actions_are_not_market_actions(raw):
    with pytest.raises(ValueError):
        validate_response(raw, "ask")


def test_real_harness_memory_branching_and_private_notice(tmp_path, protocol):
    session = Session(protocol, None, "synthetic", 0, tmp_path / "events.jsonl")
    market = make_market(protocol, session, 0)
    assert isinstance(market.sellers[0], LMSeller)
    assert isinstance(market.buyers[0], LMBuyer)
    rows = run_rounds(
        market,
        protocol.warmup_rounds,
        protocol,
        tmp_path / "warmup.jsonl",
        "warmup",
        "Seller 0",
    )
    assert positive_control(rows, protocol)["passed"]
    saved = snapshot(market)
    assert len(saved["agents"]["Seller 0"]["memories"]) == protocol.warmup_rounds
    branch = make_market(protocol, session, 0, "shock", saved)
    assert snapshot(branch) == saved
    intervene(
        branch, Condition(name="shock", kind="cost_shock", cost_drop=15), "Seller 0"
    )
    assert branch.sellers[0].valuation == 65
    assert branch.sellers[1].valuation == 80
    run_rounds(branch, 1, protocol, tmp_path / "post.jsonl", "shock", "Seller 0")
    assert snapshot(market) == saved  # independent source history/agents/queues
    events = [
        e for e in read_jsonl(tmp_path / "events.jsonl") if e["condition"] == "shock"
    ]
    for event in events:
        assert ("# Private operating-cost notice" in event["prompt"]) == (
            event["agent"] == "Seller 0"
        )
        assert ("$65.00" in event["prompt"]) == (event["agent"] == "Seller 0")
    post = read_jsonl(tmp_path / "post.jsonl")[0]
    assert rows[-1]["seller_costs"]["Seller 0"] == 80
    assert post["seller_costs"]["Seller 0"] == 65
    expected = sum(
        t["price"] - post["seller_costs"][t["seller_id"]]
        for t in post["market"]["trades"]
    )
    assert post["metrics"]["seller_profit"] == expected


def test_frozen_book_and_json_null_withdrawal(tmp_path, protocol, monkeypatch):
    session = Session(protocol, None, "synthetic", 0, tmp_path / "events.jsonl")
    market = make_market(protocol, session, 0)
    before_asks = list(market.seller_ask_queue)
    seen = []

    def scripted(self, messages):
        seen.append(messages[0]["content"])
        # A withdrawal must cancel a pre-existing initial order.
        return json.dumps({"ask": "null"} if self.role == "seller" else {"bid": "null"})

    monkeypatch.setattr(AdapterClient, "generate", scripted)
    market.run_round()
    assert market.seller_ask_queue == [] and market.buyer_bid_queue == []
    assert market.rounds[-1].seller_asks == {}
    for prompt in seen:
        for price, seller in before_asks:
            assert str(price) in prompt and seller in prompt


def test_no_trades_cannot_pass_high_ask_gate(tmp_path, protocol):
    session = Session(protocol, None, "synthetic", 0, tmp_path / "events.jsonl")
    market = make_market(protocol, session, 0)
    for buyer in market.buyers:
        buyer.valuation = 79
    # Use real metric computation on an explicitly empty-trade observation.
    from research.endogenous_defection.economics import round_metrics

    data = dict(
        round_number=1,
        seller_asks={"Seller 0": 98, "Seller 1": 98, "Seller 2": 98},
        trades=[],
    )
    metrics = round_metrics(
        data,
        {s.id: s.valuation for s in market.sellers},
        {b.id: b.valuation for b in market.buyers},
        protocol,
    )
    assert metrics["trade_index"] is None
    assert not metrics["high_price_proxy"]


def test_end_to_end_synthetic_and_matched_starts(tmp_path, protocol):
    invocation = args(tmp_path, protocol)
    assert run(invocation) == 0
    verify(invocation.out)
    bundle = json.loads((invocation.out / "bundle.json").read_text())
    assert bundle["actual_requests"] == 0 and bundle["synthetic"]
    assert bundle["modal_serving_runtime"] is None
    for seed in protocol.seeds:
        starts = [
            json.loads(
                (
                    invocation.out / f"seed_{seed}" / c.name / "start_state.json"
                ).read_text()
            )
            for c in protocol.conditions
        ]
        assert all(s == starts[0] for s in starts)
        checkpoint = json.loads(
            (invocation.out / f"seed_{seed}/checkpoint.json").read_text()
        )
        assert all(s == checkpoint["state"] for s in starts)
        audits = [
            json.loads(
                (
                    invocation.out / f"seed_{seed}" / c.name / "intervention.json"
                ).read_text()
            )
            for c in protocol.conditions
        ]
        assert len({a["start_state_sha256"] for a in audits}) == 1
        assert all(
            a["checkpoint_information_identical"] and a["only_declared_fields_changed"]
            for a in audits
        )
    # Peers' first post-intervention prompts are byte-identical across all four
    # continuations. Later divergences caused by observed actions are allowed.
    events = [
        e
        for e in read_jsonl(invocation.out / "events.jsonl")
        if e["round"] == protocol.warmup_rounds + 1
    ]
    for seed in protocol.seeds:
        target = next(
            e["target"]
            for e in read_jsonl(invocation.out / "manifest.jsonl")
            if e["seed"] == seed
        )
        for agent in {e["agent"] for e in events if e["seed"] == seed} - {target}:
            prompts = [
                e["prompt"] for e in events if e["seed"] == seed and e["agent"] == agent
            ]
            assert len(prompts) == 4 and len(set(prompts)) == 1
    analyze(invocation.out, tmp_path / "analysis")
    import csv

    with (tmp_path / "analysis/summary.csv").open() as handle:
        summaries = list(csv.DictReader(handle))
    shocks = [r for r in summaries if r["kind"] == "cost_shock"]
    assert all(r["price_undercut_round"] == "1" for r in shocks)
    assert all(
        r["cartel_breakdown_assessment"].startswith("UNREVIEWED") for r in summaries
    )
    assert all(r["outcome"] == "temporary_loss_then_reformation" for r in shocks)
    assert all(r["reformation_round"] == "2" for r in shocks)
    assert "SYNTHETIC VALIDATION ONLY" in (tmp_path / "analysis/README.md").read_text(
        encoding="utf-8"
    )


def test_stop_before_interventions_when_positive_control_fails(tmp_path, protocol):
    invocation = args(tmp_path, protocol.model_copy(update={"high_price_index": 0.99}))
    assert run(invocation) == 2
    records = read_jsonl(invocation.out / "manifest.jsonl")
    assert all(r["phase"] == "warmup" and not r["gate_passed"] for r in records)
    assert not list(invocation.out.glob("seed_*/control/rounds.jsonl"))


def test_continuation_matches_single_run_and_rejects_tampering(tmp_path, protocol):
    baseline = args(tmp_path, protocol, "baseline", stage="control")
    assert run(baseline) == 0
    continued = args(
        tmp_path,
        protocol,
        "continued",
        stage="interventions",
        from_control=baseline.out,
    )
    assert run(continued) == 0
    full = args(tmp_path, protocol, "full")
    assert run(full) == 0
    for seed in protocol.seeds:
        for c in protocol.conditions:
            relative = Path(f"seed_{seed}") / c.name / "rounds.jsonl"
            assert (continued.out / relative).read_bytes() == (
                full.out / relative
            ).read_bytes()
    dump(baseline.out / "seed_0/checkpoint.json", {})
    with pytest.raises(ValueError, match="checksums"):
        run(
            args(
                tmp_path,
                protocol,
                "tampered",
                stage="interventions",
                from_control=baseline.out,
            )
        )


def test_live_budget_gate_before_any_client_or_output(tmp_path, protocol):
    protocol = protocol.model_copy(update={"response_schema_version": "agent-action-json-v1"})
    invocation = args(
        tmp_path, protocol, backend="live", model="exact-model", max_calls=0
    )
    with pytest.raises(ValueError, match="cap"):
        run(invocation)
    assert not invocation.out.exists()


def mock_live(tmp_path, protocol, create):
    session = Session(protocol, None, "synthetic", 1, tmp_path / "events.jsonl")
    session.backend, session.model = "live", "exact-model"
    session.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    adapter = AdapterClient(session, 0, "Seller 0", 0, "seller", "control")
    return session, adapter


def test_invalid_live_response_retains_raw_and_does_not_retry(tmp_path, protocol):
    result = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='{"ask":NaN}'), finish_reason="stop"
            )
        ],
        model="exact-model",
        usage=None,
    )
    session, adapter = mock_live(tmp_path, protocol, lambda **_: result)
    with pytest.raises(RuntimeError, match="Invalid model response"):
        adapter.generate([{"role": "user", "content": "test"}])
    assert session.calls == 1
    assert read_jsonl(session.event_path)[-1]["raw"] == '{"ask":NaN}'
    failure = read_jsonl(session.event_path)[-1]
    assert failure["event"] == "response_validation_failed"
    assert failure["finish_reason"] == "stop"
    assert failure["validation_error"] and failure["schema_version"] == "unconstrained-v1"
    with pytest.raises(RuntimeError, match="budget"):
        adapter.generate([{"role": "user", "content": "test"}])
    assert session.calls == 1


def test_provider_errors_do_not_leak_exception_text_or_retry(tmp_path, protocol):
    def fail(**kwargs):
        raise RuntimeError("secret-header-must-not-be-written")

    session, adapter = mock_live(tmp_path, protocol, fail)
    with pytest.raises(RuntimeError, match="Inference failed"):
        adapter.generate([{"role": "user", "content": "test"}])
    assert session.calls == 1
    assert "secret-header" not in session.event_path.read_text()
    assert read_jsonl(session.event_path)[-1]["event"] == "request_failed"


def test_failed_run_is_preserved_and_stops_remaining_seeds(
    tmp_path, protocol, monkeypatch, capsys
):
    def fail(*args, **kwargs):
        raise RuntimeError(
            "Invalid model response; raw output retained; no retry or invented action"
        )

    monkeypatch.setattr(Session, "generate", fail)
    invocation = args(tmp_path, protocol)
    assert run(invocation) == 1
    verify(invocation.out)
    records = read_jsonl(invocation.out / "manifest.jsonl")
    assert len(records) == 1 and records[0]["status"] == "failed"
    assert records[0]["failure_reason"] == (
        "Invalid model response; raw output retained; no retry or invented action"
    )
    meta = json.loads((invocation.out / "bundle.json").read_text())
    assert meta["status"] == "failed" and meta["positive_control_gate_passed"] is None
    summary = json.loads((invocation.out / "final_summary.json").read_text())
    assert summary["requests"] == 0
    assert summary["completed_rounds"] == 0
    assert summary["seeds"]["attempted"] == [0]
    assert summary["seeds"]["failed"] == [0]
    assert summary["seeds"]["unattempted"] == [1]
    assert summary["gate"]["result"] == "not_evaluated"
    assert summary["failure_reason"] == records[0]["failure_reason"]
    assert "FINAL_SUMMARY " in capsys.readouterr().out


def test_protocol_rejects_unknown_fields_and_inconsistent_controls():
    with pytest.raises(ValueError):
        Protocol(typo_silent_change=True)
    with pytest.raises(ValueError):
        Protocol(conditions=[Condition(name="control", kind="cost_shock", cost_drop=5)])


def test_preexisting_cheaper_target_is_not_new_defection(tmp_path, protocol):
    session = Session(protocol, None, "synthetic", 0, tmp_path / "events.jsonl")
    market = make_market(protocol, session, 0)
    rows = run_rounds(
        market,
        protocol.warmup_rounds,
        protocol,
        tmp_path / "warmup.jsonl",
        "warmup",
        "Seller 0",
    )
    for row in rows:
        row["market"]["seller_asks"]["Seller 0"] = 96
    post = run_rounds(
        market,
        protocol.post_rounds,
        protocol,
        tmp_path / "post.jsonl",
        "control",
        "Seller 0",
    )
    for row in post:
        row["market"]["seller_asks"]["Seller 0"] = 96
    assert summarize(post, rows, "Seller 0", protocol)["price_undercut_round"] is None


def test_cost_pass_through_and_target_only_cut_are_not_cartel_breakdown(
    tmp_path, protocol
):
    from research.endogenous_defection.economics import round_metrics

    session = Session(protocol, None, "synthetic", 0, tmp_path / "events.jsonl")
    market = make_market(protocol, session, 0)
    warmup = run_rounds(
        market,
        protocol.warmup_rounds,
        protocol,
        tmp_path / "warmup.jsonl",
        "warmup",
        "Seller 0",
    )
    intervene(
        market, Condition(name="shock", kind="cost_shock", cost_drop=15), "Seller 0"
    )
    post = run_rounds(
        market,
        protocol.post_rounds,
        protocol,
        tmp_path / "post.jsonl",
        "shock",
        "Seller 0",
    )
    for row in post:
        # $98 -> $83 exactly passes through the $15 cost fall, preserving margin.
        row["market"]["seller_asks"]["Seller 0"] = 83
        row["metrics"].update(
            round_metrics(
                row["market"], row["seller_costs"], row["buyer_values"], protocol
            )
        )
    result = summarize(post, warmup, "Seller 0", protocol)
    assert result["price_undercut_round"] == 1
    assert result["excess_cost_pass_through_undercut_round"] is None
    assert result["sustained_proxy_loss_round"] == 1
    assert result["sustained_peer_price_decline_round"] is None
    assert result["cartel_breakdown_assessment"].startswith("UNREVIEWED")


def test_live_smoke_is_twenty_requests_and_cannot_shock():
    from research.endogenous_defection.config import load_protocol

    smoke = load_protocol(
        Path(__file__).resolve().parents[1] / "configs/live_smoke.json"
    )
    assert smoke.call_estimate()["control"] == 20
    assert smoke.seeds == [0]
    assert all(c.kind == "control" and c.cost_drop == 0 for c in smoke.conditions)


@pytest.mark.parametrize(
    "price,expected", [("81.00", 81.0), ("98.5", 98.5), ("0", 0.0)]
)
def test_decimal_string_representation_can_be_explicitly_enabled(price, expected):
    raw = json.dumps(_valid_agent_response("buyer", price))
    with pytest.raises(ValueError):
        validate_response(raw, "bid")
    assert validate_response(raw, "bid", allow_numeric_strings=True)["bid"] == expected


@pytest.mark.parametrize("price", ["$81.00", "81.001", "1e2", " 81 ", "NaN"])
def test_decimal_string_normalization_never_guesses_or_rounds(price):
    with pytest.raises(ValueError):
        validate_response(
            json.dumps(_valid_agent_response("buyer", price)),
            "bid",
            allow_numeric_strings=True,
        )


def test_live_decimal_normalization_preserves_raw_and_emits_audit(tmp_path, protocol):
    protocol = protocol.model_copy(update={"numeric_string_actions": True})
    raw = json.dumps(
        {
            "reflection": "observed",
            "plan_for_this_hour": "act",
            "ask": "81.00",
            "new_memory": "memory",
            "scratch_pad_update": "scratch",
            "plan_for_message": "communicate",
            "message_to_sellers": None,
        }
    )
    result = SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=raw), finish_reason="stop")
        ],
        model="exact-model",
        usage=None,
    )
    session, adapter = mock_live(tmp_path, protocol, lambda **_: result)
    response = json.loads(adapter.generate([{"role": "user", "content": "test"}]))
    events = read_jsonl(session.event_path)
    assert response["ask"] == 81.0 and session.calls == 1
    assert events[-2]["raw"] == raw
    assert events[-1]["event"] == "action_representation_normalized"
    assert events[-1]["original"] == "81.00" and events[-1]["normalized"] == 81.0


def _valid_agent_response(role="buyer", action=82.50):
    key = "ask" if role == "seller" else "bid"
    response = {
        "reflection": "observed",
        "plan_for_this_hour": "act",
        key: action,
        "new_memory": "memory",
        "scratch_pad_update": "scratch",
    }
    if role == "seller":
        response.update(plan_for_message="communicate", message_to_sellers=None)
    return response


def test_every_archived_rejected_raw_response_is_replayed_as_malformed_json(tmp_path):
    fixture_dir = Path(__file__).parent / "fixtures"
    fixtures = sorted(fixture_dir.glob("rejected_baseline_A_*.json"))
    assert len(fixtures) == 2
    sources = {
        ("baseline_A_v1", 12),
        ("baseline_A_v2_diagnostic", 13),
    }
    for path in fixtures:
        fixture = json.loads(path.read_text(encoding="utf-8"))
        bundle = Path(__file__).resolve().parents[1] / "results" / fixture["source_bundle"]
        source_event = next(
            event
            for event in read_jsonl(bundle / "events.jsonl")
            if event.get("event") == "response" and event.get("call") == fixture["call"]
        )
        assert (fixture["source_bundle"], fixture["call"]) in sources
        assert fixture["raw"] == source_event["raw"]
        assert fixture["finish_reason"] == source_event["finish_reason"]
        sources.remove((fixture["source_bundle"], fixture["call"]))
        assert fixture["finish_reason"] == "stop"
        with pytest.raises(ValueError, match="Malformed JSON") as exc:
            validate_response(
                fixture["raw"],
                "ask" if fixture["role"] == "seller" else "bid",
                role=fixture["role"],
                comms_enabled=fixture["role"] == "seller",
            )
        assert getattr(exc.value, "category") == "malformed_json"

        protocol = Protocol(
            numeric_string_actions=True,
            response_schema_version="agent-action-json-v1",
        )
        result = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=fixture["raw"]),
                    finish_reason=fixture["finish_reason"],
                )
            ],
            model="exact-model",
            usage=None,
        )
        event_dir = tmp_path / path.stem
        event_dir.mkdir()
        session, adapter = mock_live(event_dir, protocol, lambda **_: result)
        adapter.role = fixture["role"]
        adapter.agent_id = "Contract Buyer" if fixture["role"] == "buyer" else "Contract Seller"
        with pytest.raises(RuntimeError, match="Invalid model response"):
            adapter.generate([{"role": "user", "content": "replay"}])
        diagnostic = read_jsonl(session.event_path)[-1]
        assert diagnostic["raw"] == fixture["raw"]
        assert diagnostic["finish_reason"] == fixture["finish_reason"]
        assert diagnostic["validation_error"].startswith("Malformed JSON:")
        assert diagnostic["schema_version"] == "agent-action-json-v1"
        assert diagnostic["error_category"] == "malformed_json"
    assert not sources


def test_semantic_validator_requires_fields_and_rejects_bad_actions_and_extra_fields():
    with pytest.raises(ValueError, match="Missing required"):
        validate_response('{"bid":82}', "bid")
    response = _valid_agent_response("buyer", "82.00")
    with pytest.raises(ValueError, match="number or null"):
        validate_response(json.dumps(response), "bid")
    assert validate_response(
        json.dumps(response), "bid", allow_numeric_strings=True
    )["bid"] == 82.0
    for action in (None, "null"):
        response = _valid_agent_response("buyer", action)
        assert validate_response(json.dumps(response), "bid")["bid"] == action
    response = _valid_agent_response("seller")
    response["message_to_sellers"] = 7
    with pytest.raises(ValueError, match="message_to_sellers"):
        validate_response(json.dumps(response), "ask", role="seller", comms_enabled=True)
    response = _valid_agent_response("buyer")
    response["unmodeled"] = "value"
    with pytest.raises(ValueError, match="Unexpected fields"):
        validate_response(json.dumps(response), "bid")


@pytest.mark.parametrize("action", [True, -0.01, 10.001, float("nan"), float("inf")])
def test_complete_agent_schema_still_rejects_semantically_invalid_prices(action):
    response = _valid_agent_response("seller", action)
    with pytest.raises(ValueError) as exc:
        validate_response(
            json.dumps(response, allow_nan=True),
            "ask",
            role="seller",
            comms_enabled=True,
        )
    assert exc.value.category == "semantically_invalid_action"


def test_truncated_generation_records_raw_finish_reason_and_schema(tmp_path, protocol):
    protocol = protocol.model_copy(update={"response_schema_version": "agent-action-json-v1"})
    result = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"bid":'), finish_reason="length")],
        model="exact-model",
        usage=None,
    )
    session, adapter = mock_live(tmp_path, protocol, lambda **_: result)
    with pytest.raises(RuntimeError, match="Invalid model response"):
        adapter.generate([{"role": "user", "content": "test"}])
    failure = read_jsonl(session.event_path)[-1]
    assert failure["event"] == "response_validation_failed"
    assert failure["raw"] == '{"bid":' and failure["finish_reason"] == "length"
    assert failure["schema_version"] == "agent-action-json-v1"
    assert failure["error_category"] == "incomplete_generation"


def test_live_request_carries_vllm_guided_json_and_validates_response(tmp_path, protocol):
    from research.endogenous_defection.response_schema import SCHEMA_VERSION, schema_for

    protocol = protocol.model_copy(update={"response_schema_version": SCHEMA_VERSION})
    result = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(_valid_agent_response("seller"))),
                finish_reason="stop",
            )
        ],
        model="exact-model",
        usage=None,
    )
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return result

    session, adapter = mock_live(tmp_path, protocol, create)
    response = json.loads(adapter.generate([{"role": "user", "content": "test"}]))
    assert response["ask"] == 82.5
    assert captured["extra_body"]["guided_json"] == schema_for("seller", protocol)
    assert set(captured["extra_body"]["guided_json"]["required"]) == {
        "reflection", "plan_for_this_hour", "ask", "new_memory",
        "scratch_pad_update", "plan_for_message", "message_to_sellers",
    }


def test_bounded_text_v2_replays_runaway_scratchpad_and_bounds_generation(tmp_path):
    from jsonschema import Draft202012Validator, ValidationError

    from research.endogenous_defection.config import load_protocol
    from research.endogenous_defection.response_schema import (
        BOUNDED_TEXT_LIMITS,
        BOUNDED_TEXT_SCHEMA_VERSION,
        schema_for,
    )

    root = Path(__file__).resolve().parents[1]
    failed = root / "results/factorial_3x5_comms_off_v1/events.jsonl"
    event = next(
        record
        for record in read_jsonl(failed)
        if record.get("event") == "response_validation_failed"
        and record.get("call") == 7
    )
    assert event["agent"] == "Seller Theo"
    assert event["round"] == 1 and event["finish_reason"] == "length"
    assert event["error_category"] == "incomplete_generation"
    raw = event["raw"]
    scratch_start = raw.index('"scratch_pad_update":')
    runaway_scratch = raw[scratch_start:]
    assert raw.count(r"\\(\\)") > 100
    assert len(runaway_scratch) > BOUNDED_TEXT_LIMITS["scratch_pad_update"]
    assert BOUNDED_TEXT_SCHEMA_VERSION == "agent-action-json-v2-bounded-text"

    config = root / "configs/factorial_3x5_comms_off_v2_bounded_text.json"
    bounded = load_protocol(config)
    previous = load_protocol(root / "configs/factorial_3x5_comms_off_v1.json")
    assert bounded.response_schema_version == BOUNDED_TEXT_SCHEMA_VERSION
    assert bounded.max_tokens == 2048
    assert bounded.seller_costs == previous.seller_costs
    assert bounded.buyer_values == previous.buyer_values
    assert bounded.seeds == previous.seeds
    assert bounded.temperature == previous.temperature
    assert bounded.seller_comms_enabled == previous.seller_comms_enabled is False
    assert bounded.buyer_comms_enabled == previous.buyer_comms_enabled is False
    allowed_changes = {"protocol_version", "response_schema_version", "max_tokens"}
    assert all(
        bounded.model_dump()[key] == previous.model_dump()[key]
        for key in bounded.model_dump()
        if key not in allowed_changes
    )
    from research.endogenous_defection.run_experiment import validate_live_request

    preflight = argparse.Namespace(
        backend="live",
        stage="preflight",
        model=bounded.model_id,
        max_calls=160,
        out=tmp_path / "fresh-v2-output",
    )
    assert validate_live_request(preflight, bounded) == 160
    assert not preflight.out.exists()
    preflight.max_calls = 159
    with pytest.raises(ValueError, match="Plan needs up to 160 requests"):
        validate_live_request(preflight, bounded)

    seller_schema = schema_for("seller", bounded)
    Draft202012Validator.check_schema(seller_schema)
    assert "message_to_sellers" not in seller_schema["properties"]
    assert seller_schema["properties"]["scratch_pad_update"]["maxLength"] == 1200
    valid = _valid_agent_response("seller")
    valid.pop("plan_for_message")
    valid.pop("message_to_sellers")
    Draft202012Validator(seller_schema).validate(valid)
    too_long = {**valid, "scratch_pad_update": "x" * 1201}
    with pytest.raises(ValidationError, match="maxLength"):
        Draft202012Validator(seller_schema).validate(too_long)
    with pytest.raises(ValueError, match="exceeds 1200 characters") as exc:
        validate_response(
            json.dumps(too_long),
            "ask",
            role="seller",
            comms_enabled=False,
            max_text_lengths=BOUNDED_TEXT_LIMITS,
        )
    assert exc.value.category == "schema_violation"

    result = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(valid)), finish_reason="stop"
            )
        ],
        model="exact-model",
        usage=None,
    )
    captured = {}
    session, adapter = mock_live(
        tmp_path,
        bounded,
        lambda **kwargs: (captured.update(kwargs) or result),
    )
    assert json.loads(adapter.generate([{"role": "user", "content": "test"}]))["ask"] == 82.5
    assert captured["max_tokens"] == 2048
    assert captured["extra_body"]["guided_json"] == seller_schema
    assert session.calls == 1


def test_v3_schema_bounds_only_the_runaway_scratchpad(tmp_path):
    from jsonschema import Draft202012Validator, ValidationError

    from research.endogenous_defection.config import load_protocol
    from research.endogenous_defection.response_schema import (
        BOUNDED_SCRATCHPAD_LIMITS,
        BOUNDED_SCRATCHPAD_SCHEMA_VERSION,
        schema_for,
    )

    root = Path(__file__).resolve().parents[1]
    protocol = load_protocol(
        root / "configs/factorial_3x5_comms_off_v3_bounded_scratchpad.json"
    )
    prior = load_protocol(
        root / "configs/factorial_3x5_comms_off_v2_bounded_text.json"
    )
    assert protocol.response_schema_version == BOUNDED_SCRATCHPAD_SCHEMA_VERSION
    assert protocol.max_tokens == prior.max_tokens == 2048
    assert protocol.seller_costs == prior.seller_costs
    assert protocol.buyer_values == prior.buyer_values
    assert protocol.seeds == prior.seeds and protocol.temperature == prior.temperature
    assert protocol.seller_comms_enabled is False
    assert protocol.buyer_comms_enabled is False
    allowed = {"protocol_version", "response_schema_version"}
    assert all(
        protocol.model_dump()[key] == prior.model_dump()[key]
        for key in protocol.model_dump()
        if key not in allowed
    )

    schema = schema_for("buyer", protocol)
    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["scratch_pad_update"]["maxLength"] == 1000
    assert all(
        "maxLength" not in definition
        for key, definition in schema["properties"].items()
        if key != "scratch_pad_update"
    )
    valid = _valid_agent_response("buyer")
    valid["reflection"] = "x" * 1500
    Draft202012Validator(schema).validate(valid)
    too_long = {**valid, "scratch_pad_update": "x" * 1001}
    with pytest.raises(ValidationError, match="maxLength"):
        Draft202012Validator(schema).validate(too_long)
    with pytest.raises(ValueError, match="exceeds 1000 characters") as exc:
        validate_response(
            json.dumps(too_long),
            "bid",
            role="buyer",
            comms_enabled=False,
            max_text_lengths=BOUNDED_SCRATCHPAD_LIMITS,
        )
    assert exc.value.category == "schema_violation"

    result = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(valid)), finish_reason="stop"
            )
        ],
        model="exact-model",
        usage=None,
    )
    captured = {}
    session, adapter = mock_live(
        tmp_path,
        protocol,
        lambda **kwargs: (captured.update(kwargs) or result),
    )
    adapter.role = "buyer"
    adapter.agent_id = "Contract Buyer"
    assert json.loads(adapter.generate([{"role": "user", "content": "test"}]))["bid"] == 82.5
    assert captured["extra_body"]["guided_json"] == schema
    assert session.calls == 1


def test_v4_reuses_known_guided_schema_with_longer_token_ceiling(tmp_path):
    from jsonschema import Draft202012Validator

    from research.endogenous_defection.config import load_protocol
    from research.endogenous_defection.response_schema import SCHEMA_VERSION, schema_for

    root = Path(__file__).resolve().parents[1]
    protocol = load_protocol(
        root / "configs/factorial_3x5_comms_off_v4_guided_2048.json"
    )
    original = load_protocol(root / "configs/factorial_3x5_comms_off_v1.json")
    assert protocol.response_schema_version == SCHEMA_VERSION
    assert protocol.max_tokens == 2048
    allowed = {"protocol_version", "max_tokens"}
    assert all(
        protocol.model_dump()[key] == original.model_dump()[key]
        for key in protocol.model_dump()
        if key not in allowed
    )

    schema = schema_for("buyer", protocol)
    Draft202012Validator.check_schema(schema)
    assert all("maxLength" not in value for value in schema["properties"].values())
    valid = _valid_agent_response("buyer")
    Draft202012Validator(schema).validate(valid)
    too_long = {**valid, "scratch_pad_update": "word " * 251}
    with pytest.raises(ValueError, match="maximum is 250 words"):
        validate_response(json.dumps(too_long), "bid", role="buyer")

    result = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(valid)), finish_reason="stop"
            )
        ],
        model="exact-model",
        usage=None,
    )
    captured = {}
    session, adapter = mock_live(
        tmp_path,
        protocol,
        lambda **kwargs: (captured.update(kwargs) or result),
    )
    adapter.role = "buyer"
    assert json.loads(adapter.generate([{"role": "user", "content": "test"}]))["bid"] == 82.5
    assert captured["max_tokens"] == 2048
    assert captured["extra_body"]["guided_json"] == schema
    assert session.calls == 1


def test_final_summary_preserves_request_failure_diagnostic(tmp_path):
    from research.endogenous_defection.run_experiment import build_final_summary

    out = tmp_path / "failed-request"
    out.mkdir()
    manifest = {
        "seed": 10,
        "phase": "warmup",
        "status": "failed",
        "failure_reason": "RuntimeError",
    }
    events = [
        {
            "event": "request_started",
            "seed": 10,
            "agent": "Buyer Ana",
            "round": 1,
            "call": 1,
        },
        {
            "event": "request_failed",
            "seed": 10,
            "agent": "Buyer Ana",
            "round": 1,
            "call": 1,
            "error_type": "APITimeoutError",
            "request_timeout_seconds": 90,
            "schema_version": "agent-action-json-v3-bounded-scratchpad",
        },
    ]
    (out / "manifest.jsonl").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    (out / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )
    protocol = Protocol(seeds=[10, 11])
    summary = build_final_summary(
        out,
        {
            "status": "failed",
            "planned_max_requests": 160,
            "max_calls": 160,
            "positive_control_gate_passed": None,
        },
        protocol,
        session_calls=1,
    )
    assert summary["failure_reason"] == "Inference request failed (APITimeoutError)"
    detail = summary["failure_reasons"][0]
    assert detail["error_type"] == "APITimeoutError"
    assert detail["request_timeout_seconds"] == 90
    assert detail["error_category"] == "inference_request_failed"
    assert detail["call"] == 1 and detail["agent"] == "Buyer Ana"
    assert summary["gate"]["result"] == "not_evaluated"


def test_role_schemas_are_valid_json_schema_and_distinct():
    from jsonschema import Draft202012Validator, ValidationError
    from research.endogenous_defection.response_schema import schema_for

    protocol = Protocol(response_schema_version="agent-action-json-v1")
    buyer = schema_for("buyer", protocol)
    seller = schema_for("seller", protocol)
    Draft202012Validator.check_schema(buyer)
    Draft202012Validator.check_schema(seller)
    Draft202012Validator(buyer).validate(_valid_agent_response("buyer"))
    Draft202012Validator(seller).validate(_valid_agent_response("seller"))
    with pytest.raises(ValidationError):
        Draft202012Validator(buyer).validate(_valid_agent_response("buyer", "82.50"))
    assert "ask" in seller["required"] and "ask" not in buyer["required"]
    assert "bid" in buyer["required"] and "bid" not in seller["required"]


def test_guided_protocol_has_versioned_a_only_approval(tmp_path):
    import hashlib

    from research.endogenous_defection.config import load_protocol

    root = Path(__file__).resolve().parents[1]
    old = load_protocol(root / "configs/baseline_A_qwen_v1.json")
    new = load_protocol(root / "configs/baseline_A_qwen_v2_guided.json")
    assert new.protocol_version != old.protocol_version
    assert new.response_schema_version == "agent-action-json-v1"
    assert new.execution_enabled
    budget = json.loads((root / "BASELINE_BUDGET_ESTIMATES.json").read_text())
    approval = budget["A_guided_v2"]
    assert approval["execution_enabled"] and approval["calls"] == 200
    assert hashlib.sha256(
        (root / "configs/baseline_A_qwen_v2_guided.json").read_bytes()
    ).hexdigest() == approval["approved_config_sha256"]
    assert approval["approval_record"]["approved_config_sha256"] == approval[
        "approved_config_sha256"
    ]
    assert not budget["B"]["execution_enabled"]
    for name in (
        "seeds", "seller_costs", "buyer_values", "warmup_rounds", "post_rounds",
        "window", "min_qualifying_seeds", "high_price_index", "min_trades_per_round",
        "temperature", "max_tokens", "provider_seed", "numeric_string_actions",
        "seller_comms_enabled", "buyer_comms_enabled", "hide_num_rounds",
        "announced_rounds", "identity_mode", "initial_seller_ask_range",
        "initial_buyer_bid_range", "conditions",
    ):
        assert getattr(new, name) == getattr(old, name)
    args = argparse.Namespace(
        config=root / "configs/baseline_A_qwen_v2_guided.json", stage="preflight",
        backend="live", model=new.model_id, out=tmp_path / "none", from_control=None,
        max_calls=200,
    )
    assert run(args) == 0
    assert not args.out.exists()
