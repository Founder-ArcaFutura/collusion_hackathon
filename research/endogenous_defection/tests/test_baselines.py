import argparse
import json
from pathlib import Path

import pytest

from research.endogenous_defection.auction import AdapterClient, Session, make_market, run_rounds
from research.endogenous_defection.baseline_plan import plans
from research.endogenous_defection.config import Protocol, load_protocol
from research.endogenous_defection.economics import benchmarks, price_index
from research.endogenous_defection.io import read_jsonl
from research.endogenous_defection.launch_baseline import (
    launch,
    validate_approved_config_digest,
)
from research.endogenous_defection.run_experiment import run

HERE = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "filename,calls,horizon",
    [("baseline_A_qwen_v1.json", 200, 10), ("baseline_B_reference_v1.json", 900, 30)],
)
def test_review_configs_bound_baselines_and_block_live_execution(
    tmp_path, filename, calls, horizon
):
    path = HERE / "configs" / filename
    protocol = load_protocol(path)
    assert len(protocol.seller_costs) == len(protocol.buyer_values) == 5
    assert protocol.call_estimate() == {
        "control": calls,
        "interventions_max": 0,
        "pilot_max": calls,
    }
    assert not protocol.hide_num_rounds and protocol.announced_rounds == horizon
    assert protocol.high_price_index == 0.5 and protocol.window == 5
    args = argparse.Namespace(
        config=path,
        stage="control",
        backend="live",
        model=protocol.model_id,
        out=tmp_path / "must_not_exist",
        from_control=None,
        max_calls=calls,
    )
    if filename == "baseline_A_qwen_v1.json":
        args.stage = "preflight"
        with pytest.raises(ValueError, match="guided JSON"):
            run(args)
        assert not args.out.exists()
    else:
        with pytest.raises(ValueError, match="user approval"):
            run(args)
        assert not args.out.exists()
    args.backend, args.stage = "synthetic", "pilot"
    with pytest.raises(ValueError, match="control-only"):
        run(args)


def test_archived_reference_composition_and_initial_spreads():
    root = HERE.parents[1]
    paths = list((root / "llm-agent-collusion/data").glob("*/experiment_metadata.json"))
    assert len(paths) == 75
    for path in paths:
        config = json.loads(path.read_text(encoding="utf-8"))["auction_config"]
        assert len(config["seller_valuations"]) == len(config["buyer_valuations"]) == 5
        assert config["rounds"] == 30
    config = json.loads(
        (
            root
            / "llm-agent-collusion/data/20250516_213920_base-seller_comms-2/experiment_metadata.json"
        ).read_text()
    )["auction_config"]
    b = load_protocol(HERE / "configs/baseline_B_reference_v1.json")
    assert b.initial_seller_ask_range == (
        config["initial_seller_ask_center"] - config["initial_seller_ask_spread"] / 2,
        config["initial_seller_ask_center"] + config["initial_seller_ask_spread"] / 2,
    )
    assert config["temperature"] == b.temperature and not config["hide_num_rounds"]


def test_seeded_identities_and_actual_disclosed_horizon_are_reproducible(tmp_path):
    p = load_protocol(HERE / "configs/baseline_A_qwen_v1.json")
    session = Session(p, None, "synthetic", 0, tmp_path / "events.jsonl")
    a, b = make_market(p, session, 10), make_market(p, session, 10)
    assert [(x.id, x.company) for x in a.sellers + a.buyers] == [
        (x.id, x.company) for x in b.sellers + b.buyers
    ]
    assert a.seller_ask_queue == b.seller_ask_queue
    assert all(96.25 <= price <= 98.75 for price, _ in a.seller_ask_queue)
    assert all(81.25 <= price <= 83.75 for price, _ in a.buyer_bid_queue)
    run_rounds(a, 1, p, tmp_path / "rounds.jsonl", "warmup", a.sellers[0].id)
    for event in read_jsonl(tmp_path / "events.jsonl"):
        assert "Hour #1 out of 10 hours" in event["prompt"]
        assert "out of 15" not in event["prompt"]
        assert "Message from the CEO" not in event["prompt"]
        assert "implemented a new oversight system" not in event["prompt"]


def test_market_composition_changes_static_reference_and_degeneracy():
    balanced = benchmarks([100] * 5, [80] * 5)
    assert (balanced["ce_low"], balanced["ce_high"], balanced["ce_mid"]) == (
        80,
        100,
        90,
    )
    assert balanced["jpm_price"] == 100
    excess_buyers = benchmarks([100] * 6, [80] * 5)
    assert excess_buyers["ce_mid"] == 100
    assert price_index(97, excess_buyers) is None
    assert benchmarks([100] * 2, [80] * 3)["ce_mid"] == 80


def test_factorial_configs_change_only_market_composition_and_seller_channel(tmp_path):
    root = HERE / "configs"
    archived = load_protocol(root / "baseline_A_qwen_v2_guided.json")
    variants = {
        "5x5_off": load_protocol(root / "factorial_5x5_comms_off_v1.json"),
        "3x5_on": load_protocol(root / "factorial_3x5_comms_on_v1.json"),
        "3x5_off": load_protocol(root / "factorial_3x5_comms_off_v1.json"),
    }
    baseline = archived.model_dump()
    for name, protocol in variants.items():
        assert protocol.seeds == [10, 11]
        assert protocol.buyer_values == archived.buyer_values
        assert protocol.warmup_rounds == archived.warmup_rounds == 10
        assert protocol.temperature == archived.temperature
        assert protocol.max_tokens == archived.max_tokens
        assert protocol.response_schema_version == archived.response_schema_version
        assert protocol.provider_seed == archived.provider_seed
        assert protocol.numeric_string_actions == archived.numeric_string_actions
        assert protocol.initial_seller_ask_range == archived.initial_seller_ask_range
        assert protocol.initial_buyer_bid_range == archived.initial_buyer_bid_range
        assert protocol.identity_mode == archived.identity_mode
        assert protocol.call_estimate()["pilot_max"] == (
            200 if name == "5x5_off" else 160
        )
        planned = protocol.call_estimate()["control"]
        from research.endogenous_defection.run_experiment import validate_live_request

        local_preflight = argparse.Namespace(
            backend="live",
            stage="preflight",
            model=protocol.model_id,
            max_calls=planned,
            out=tmp_path / f"preflight_{name}",
        )
        assert validate_live_request(local_preflight, protocol) == planned
        local_preflight.max_calls = planned - 1
        with pytest.raises(ValueError, match="Plan needs up to"):
            validate_live_request(local_preflight, protocol)
        actual = protocol.model_dump()
        allowed = {
            "protocol_version", "seller_costs", "seller_comms_enabled",
            "initialization_seller_slots",
        }
        assert all(actual[k] == v for k, v in baseline.items() if k not in allowed)
        assert protocol.seller_comms_enabled == (name == "3x5_on")
        assert not protocol.buyer_comms_enabled
        assert protocol.initialization_seller_slots == (5 if name.startswith("3x5") else None)

    on5 = archived
    off5 = variants["5x5_off"]
    for seed in (10, 11):
        markets = []
        for protocol in (
            on5,
            off5,
            variants["3x5_on"],
            variants["3x5_off"],
        ):
            session = Session(protocol, None, "synthetic", 0, tmp_path / "events.jsonl")
            markets.append(make_market(protocol, session, seed))
        market5_on, market5_off, market3_on, market3_off = markets
        assert [(a.id, a.company) for a in market5_on.sellers + market5_on.buyers] == [
            (a.id, a.company) for a in market5_off.sellers + market5_off.buyers
        ]
        assert market5_on.seller_ask_queue == market5_off.seller_ask_queue
        assert market5_on.buyer_bid_queue == market5_off.buyer_bid_queue
        assert [(a.id, a.company) for a in market3_on.sellers + market3_on.buyers] == [
            (a.id, a.company) for a in market3_off.sellers + market3_off.buyers
        ]
        assert market3_on.seller_ask_queue == market3_off.seller_ask_queue
        assert market3_on.buyer_bid_queue == market3_off.buyer_bid_queue
        asks5 = dict((seller, price) for price, seller in market5_on.seller_ask_queue)
        asks3 = dict((seller, price) for price, seller in market3_on.seller_ask_queue)
        bids5 = dict((buyer, price) for price, buyer in market5_on.buyer_bid_queue)
        bids3 = dict((buyer, price) for price, buyer in market3_on.buyer_bid_queue)
        assert [asks5[s.id] for s in market5_on.sellers[:3]] == [
            asks3[s.id] for s in market3_on.sellers
        ]
        assert [bids5[b.id] for b in market5_on.buyers] == [
            bids3[b.id] for b in market3_on.buyers
        ]


def test_comms_off_removes_prompt_fields_and_prevents_message_delivery(tmp_path, monkeypatch):
    protocol = load_protocol(
        HERE / "configs/factorial_5x5_comms_off_v1.json"
    )
    session = Session(protocol, None, "synthetic", 0, tmp_path / "events.jsonl")
    market = make_market(protocol, session, 10)
    prompts = []

    def no_comms(self, messages):
        prompts.append((self.role, messages[0]["content"]))
        return json.dumps(
            {
                "ask": 98
            }
            if self.role == "seller"
            else {"bid": 99}
        )

    monkeypatch.setattr(AdapterClient, "generate", no_comms)
    market.run_round()
    assert not market.rounds[-1].seller_messages
    market.rounds[-1].seller_messages[market.sellers[0].id] = "MUST_NOT_BE_DELIVERED"
    market.run_round()
    seller_prompts = [prompt for role, prompt in prompts if role == "seller"]
    assert len(seller_prompts) == 10
    for prompt in seller_prompts:
        assert "MUST_NOT_BE_DELIVERED" not in prompt
        assert "Messages Received from Other Sellers" not in prompt
        assert "maximum length limit" not in prompt
        assert "plan_for_message" not in prompt
        assert "message_to_sellers" not in prompt
    from research.endogenous_defection.response_schema import schema_for

    schema = schema_for("seller", protocol)
    assert "message_to_sellers" not in schema["properties"]
    assert "plan_for_message" not in schema["properties"]


def test_3x5_control_bundle_reports_direct_metrics_and_unevaluable_gate(tmp_path):
    import csv

    from research.endogenous_defection.analyze import analyze

    config = HERE / "configs/factorial_3x5_comms_off_v1.json"
    protocol = load_protocol(config)
    bundle = tmp_path / "three_by_five"
    invocation = argparse.Namespace(
        config=config,
        stage="control",
        backend="synthetic",
        model=None,
        out=bundle,
        from_control=None,
        max_calls=0,
    )
    assert run(invocation) == 0
    summary = json.loads((bundle / "final_summary.json").read_text())
    assert summary["status"] == "complete"
    assert summary["requests"] == 0
    assert summary["gate"]["result"] == "not_evaluated"
    assert summary["gate"]["passed"] is None
    out = tmp_path / "analysis"
    analyze(bundle, out)
    with (out / "control_summary.csv").open(encoding="utf-8") as handle:
        controls = list(csv.DictReader(handle))
    with (out / "round_metrics.csv").open(encoding="utf-8") as handle:
        rounds = list(csv.DictReader(handle))
    assert len(controls) == len(protocol.seeds)
    assert controls[0]["gate_evaluable"] == "False"
    assert controls[0]["mean_ask_markup"] != ""
    assert rounds[0]["ask_index"] == ""
    assert rounds[0]["mean_ask_markup"] != ""
    assert rounds[0]["trade_count"] != ""
    assert (out / "trajectories.png").exists()


def test_budget_scenarios_are_planning_only_and_keep_separate_funding():
    p = plans()
    assert p["approval_required"] and not p["paid_execution_performed"]
    assert p["A"]["calls"] == 200 and p["B"]["calls"] == 900
    assert p["B"]["scenarios"][-1]["usd_at_openai_standard_rates"] == 50.4
    assert p["A"]["execution_enabled"] and not p["B"]["execution_enabled"]


def _baseline_launch_args(tmp_path, **overrides):
    args = {
        "config": HERE / "configs/baseline_A_qwen_v2_guided.json",
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "max_calls": 200,
        "out": tmp_path / "baseline_A",
        "region_multiplier": 1.15,
        "verified_remaining_modal_credits_usd": 10.0,
        "ready_timeout": 900,
        "run_timeout": 7200,
    }
    args.update(overrides)
    return argparse.Namespace(**args)


def test_unconstrained_approved_a_is_stopped_before_host_invocation(tmp_path):
    args = _baseline_launch_args(
        tmp_path, config=HERE / "configs/baseline_A_qwen_v1.json"
    )
    started = []

    with pytest.raises(ValueError, match="guided JSON"):
        launch(args, host_runner=lambda command, **kwargs: started.append(command))
    assert started == []
    assert not args.out.exists()


def test_guided_a_approval_passes_all_local_preflight_before_host_invocation(tmp_path):
    args = _baseline_launch_args(tmp_path)
    started = []

    class Result:
        returncode = 0

    assert launch(
        args,
        host_runner=lambda command, **kwargs: started.append(command) or Result(),
    ) == 0
    assert len(started) == 1
    assert "research.endogenous_defection.run_experiment" in started[0]
    assert "200" in started[0]
    assert not args.out.exists()


def test_live_contract_preflight_authorizes_only_the_two_call_contract_probe(tmp_path):
    from research.endogenous_defection.launch_contract import launch as launch_contract

    args = _baseline_launch_args(tmp_path, out=tmp_path / "contract-probe", run_timeout=300)
    started = []

    class Result:
        returncode = 0

    assert launch_contract(
        args,
        host_runner=lambda command, **kwargs: started.append(command) or Result(),
    ) == 0
    assert len(started) == 1
    assert "research.endogenous_defection.contract_test" in started[0]
    assert "300" in started[0]
    assert not args.out.exists()


def test_contract_host_command_runs_only_after_preflight(tmp_path, monkeypatch):
    from research.endogenous_defection import launch_contract

    args = _baseline_launch_args(tmp_path, run_timeout=300)
    monkeypatch.setattr(launch_contract, "preflight", lambda _: {"preflight": "passed"})

    class Result:
        returncode = 0

    started = []
    assert launch_contract.launch(
        args, host_runner=lambda command, **kwargs: started.append(command) or Result()
    ) == 0
    assert len(started) == 1
    assert "--run-timeout" in started[0] and "300" in started[0]
    assert "research.endogenous_defection.contract_test" in started[0]
    assert "--out" in started[0] and str(args.out) in started[0]


def test_baseline_b_is_blocked_before_modal_start(tmp_path):
    args = _baseline_launch_args(
        tmp_path,
        config=HERE / "configs/baseline_B_reference_v1.json",
        model="gpt-4.1-2025-04-14",
        max_calls=900,
    )
    started = []
    with pytest.raises(ValueError, match="restricted to versioned baseline A"):
        launch(args, host_runner=lambda *a, **k: started.append(a))
    assert started == []


def test_scientific_config_change_invalidates_versioned_approval(tmp_path):
    config_copy = tmp_path / "baseline_A_modified.json"
    config_copy.write_text(
        (HERE / "configs/baseline_A_qwen_v1.json")
        .read_text(encoding="utf-8")
        .replace('"temperature": 0.7', '"temperature": 0.8'),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="differs from the versioned approved file"):
        validate_approved_config_digest(
            config_copy,
            "f7bd94f3dcfef02406a7034b7db70f303f590ea0e44b22fadbc13a5c76511a92",
        )


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"max_calls": 199}, "Plan needs up to 200 requests"),
        ({"region_multiplier": 1.75}, "exceeds A's"),
        ({"verified_remaining_modal_credits_usd": 4.0}, "more than half"),
        ({"model": "Qwen/other"}, "exactly match"),
    ],
)
def test_invalid_live_preflights_fail_before_modal_start(tmp_path, overrides, message, monkeypatch):
    args = _baseline_launch_args(tmp_path, **overrides)
    from research.endogenous_defection import launch_baseline

    real_load_protocol = launch_baseline.load_protocol
    monkeypatch.setattr(
        launch_baseline,
        "load_protocol",
        lambda path: real_load_protocol(path).model_copy(update={"execution_enabled": True}),
    )
    started = []
    with pytest.raises((ValueError, FileExistsError), match=message):
        launch(args, host_runner=lambda *a, **k: started.append(a))
    assert started == []
    assert not args.out.exists()


def test_announced_horizon_and_ranges_cannot_silently_misrepresent_run():
    with pytest.raises(ValueError, match="horizon"):
        Protocol(announced_rounds=31)
    with pytest.raises(ValueError, match="ranges"):
        Protocol(initial_seller_ask_range=(100, 90))


def test_control_only_baseline_has_round_and_control_analysis(tmp_path):
    import csv
    from research.endogenous_defection.analyze import analyze

    config = HERE / "configs/baseline_A_qwen_v1.json"
    bundle = tmp_path / "synthetic_control"
    args = argparse.Namespace(
        config=config,
        stage="control",
        backend="synthetic",
        model=None,
        out=bundle,
        from_control=None,
        max_calls=0,
    )
    assert run(args) == 0
    out = tmp_path / "analysis"
    analyze(bundle, out)
    with (out / "control_summary.csv").open() as handle:
        summary = list(csv.DictReader(handle))
    with (out / "round_metrics.csv").open() as handle:
        rounds = list(csv.DictReader(handle))
    assert len(summary) == 2 and all(r["observed_rounds"] == "10" for r in summary)
    assert len(rounds) == 20 and "ask_stddev" in rounds[0]
    assert (out / "trajectories.png").exists()
    assert json.loads((out / "analysis.json").read_text())["actual_requests"] == 0
