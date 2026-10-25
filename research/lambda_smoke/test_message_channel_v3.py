"""Source-admission and pre-compute guard regressions; no inference."""
import copy
import json
from pathlib import Path

import pytest

from research.lambda_smoke import message_channel_probe as p
from research.lambda_smoke import message_channel_v3 as v3
from research.lambda_smoke import message_channel_replication_analysis as analysis


@pytest.fixture(scope="module")
def audited():
    return v3.audit_sources()


def identity(s):
    return (s["seed"], s["round"], s["sender"], s["recipient"])


def test_raw_audit_preserves_frozen_eligibility_and_counts(audited):
    previous = v3.runner.read(p.ROOT / "output/message_channel_modal_v2_recovered/plan.json")
    assert {identity(s) for s in audited["states"]} == {identity(s) for s in previous["states"]}
    assert len(audited["audit_rows"]) == 688
    assert {item["market_seed"] for item in audited["inventory"]} == {20, 21, 22, 23}
    assert len(audited["states"]) == len({identity(s) for s in audited["states"]}) == 10
    for s in audited["states"]:
        source = p._response_prompts(p.ROOT / s["source_bundle"])[(s["seed"], s["round"], s["recipient"])]
        assert s["conditions"]["hidden_original"]["prompt"].encode() == source["prompt"].encode()


def test_late_scope_amendment_not_silently_admitted(audited):
    late = [r for r in audited["audit_rows"] if r["first_exclusion"] == "outside_frozen_rounds_2_to_6"
            and r["late_round_other_rules_result"] == "eligible"]
    assert len(late) == 1 and late[0]["seed"] == 21 and late[0]["round"] == 8
    assert all(s["round"] <= 6 for s in audited["states"])


def test_visible_or_false_reports_stay_out(audited):
    s = audited["states"][0]
    assert v3.assess(s, s["source_observation"], s["prompt"], s["quote_price"] + 1) == "report_does_not_match_submitted_ask"
    obs = copy.deepcopy(s["source_observation"])
    for row in obs["current_quote_masks"]:
        if row["owner"] == s["sender"]:
            row["visible"] = True
    assert v3.assess(s, obs, s["prompt"], s["quote_price"]) == "current_quote_not_hidden"
    prompt = s["prompt"] + f"\n{s['sender']} ask ${s['quote_price']:.2f}\n"
    assert v3.assess(s, s["source_observation"], prompt, s["quote_price"]) == "fact_asserted_elsewhere_in_prompt"


def test_held_plan_queue_budget_and_no_paid_launch(tmp_path, monkeypatch):
    root = tmp_path / "held"
    summary = v3.prepare(root)
    assert summary["proposed_decisions"] == 300 and summary["maximum_requests"] == 303
    assert summary["new_states_vs_v2"] == 0 and summary["status"] == "HELD_NOT_LAUNCHED"
    manifest = v3.runner.load(root)
    assert len({row["key"] for row in manifest["queue"]}) == 300
    assert manifest["plan"]["seeds"] == [1001, 1002, 1003]
    assert manifest["plan"]["schema_warmup"]["max_tokens"] == 512
    assert not manifest["plan"]["execution_enabled"]
    assert summary["budget"]["conditional_maximum_resource_cost_with_20_percent_reserve_usd"] <= 10
    monkeypatch.setattr(v3.runner.subprocess, "run", lambda *a, **kw: pytest.fail("No compute may start"))
    with pytest.raises(RuntimeError, match="held before any compute"):
        v3.batch(root)
    assert not list((root / "sessions").iterdir())


def test_analysis_rejects_duplicate_keys(tmp_path, monkeypatch):
    plan = v3.runner.read(p.ROOT / "output/message_channel_modal_v2_recovered/plan.json")
    rows = analysis.base.read_csv(p.ROOT / "output/message_channel_modal_v2_recovered/decisions.csv")
    monkeypatch.setattr(analysis.base, "verify_checksums", lambda _: None)
    monkeypatch.setattr(analysis.base, "read_csv", lambda _: [dict(rows[0]), dict(rows[0])])
    with pytest.raises(ValueError, match="Duplicate decision key"):
        analysis.identify_rows(tmp_path, plan)
