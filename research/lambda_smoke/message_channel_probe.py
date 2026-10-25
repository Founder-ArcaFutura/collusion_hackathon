"""Prepare and validate the saved-state message × quote visibility probe.

Local stages (plan, validate, mock, package) make no inference calls. The live
worker can use the existing Modal host wrapper or be exported for Lambda.
"""
from __future__ import annotations

import argparse
import ast
import csv
import contextlib
import hashlib
import io
import json
import re
import shutil
import tarfile
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from research.endogenous_defection.io import read_jsonl, verify

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PUBLICATION = ROOT / "research/endogenous_defection/publication/sprint_20261024"
SOURCES = (
    ROOT / "output/information_study_20261024_095806_35d3842f",
    ROOT / "output/information_study_20261024_122407_31b6457e",
)
MODEL = "Qwen/Qwen2.5-7B-Instruct"
SAMPLING_SEEDS = (901, 902)
VISIBILITIES = ("hidden", "restored")
MESSAGE_MODES = ("original", "redacted", "up10", "down10", "absent")
EXPECTED_SOURCE_RUNTIME = {
    "vllm": "0.6.6", "xgrammar": "0.1.13", "outlines": "0.1.11",
    "guided_decoding_backend": "outlines",
    "required_api": "vllm guided_json via outlines backend",
    "required_api_available": True,
}
ASK_QUEUE = re.compile(r"(## Current Status of Ask Queue\s*\n)(\[[^\n]*\])")
HISTORY = re.compile(r"(## Asks/Bids Placed in the Last 5 Hours\s*\n)(.*?)(?=\n## Past Trades)", re.S)
MESSAGE_HEADER = "# Messages Received from Other Sellers (Previous Hour)"
PRICE = re.compile(r"(?P<currency>\$\s*)(?P<amount>\d+(?:\.\d{1,2})?)")
SELF_ASK = re.compile(
    r"\bmy\s+(?:current\s+|new\s+)?ask\b.{0,45}\$\s*(\d+(?:\.\d{1,2})?)"
    r"|\bI\s+(?:have\s+|\u2019ve\s+|'ve\s+)?(?:set|placed|entered|adjusted|lowered|raised)"
    r"\s+(?:my\s+)?ask\b.{0,45}\$\s*(\d+(?:\.\d{1,2})?)",
    re.I,
)


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def load_jsonl(path: Path):
    return read_jsonl(path)


def money_equal(left, right):
    try:
        return round(float(left), 2) == round(float(right), 2)
    except (TypeError, ValueError):
        return False


def _read_csv(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _bundle_index():
    result = {}
    for study in SOURCES:
        if not study.is_dir():
            continue
        for bundle in sorted((study / "cells").glob("seed_*_partial_on")):
            result[bundle.name] = bundle
    return result


def _market_rounds(bundle: Path, seed: int):
    path = bundle / f"seed_{seed}" / "warmup.jsonl"
    return {int(row["metrics"]["round"]): row for row in load_jsonl(path)}


def _response_prompts(bundle: Path):
    return {
        (int(row["seed"]), int(row["round"]), row["agent"]): row
        for row in load_jsonl(bundle / "events.jsonl")
        if row.get("event") == "response" and isinstance(row.get("prompt"), str)
    }


def _mask_row(obs, owner, price, quote_round, key):
    return next((row for row in obs.get(key, [])
                 if row.get("owner") == owner
                 and int(row.get("quote_round", -1)) == quote_round
                 and money_equal(row.get("price"), price)), None)


def _owner_price_assertion_exists(text, owner, price):
    """Find the same seller-price claim in another prompt line."""
    for line in text.splitlines():
        if owner.casefold() not in line.casefold() or not re.search(r"\b(?:ask|asked|quote|quoted)\b", line, re.I):
            continue
        if any(money_equal(m.group("amount"), price) for m in PRICE.finditer(line)):
            return True
    return False


def _candidate_states(limit=10, unique_pairs=True):
    bundles = _bundle_index()
    candidates_path = PUBLICATION / "recipient_hidden_price_candidates.csv"
    if not candidates_path.is_file():
        raise FileNotFoundError(f"Missing frozen candidate index: {candidates_path}")
    candidates = _read_csv(candidates_path)
    observations = {}
    rounds = {}
    prompts = {}
    seals = {}
    output = []
    for row in candidates:
        if row.get("cell") != "partial_on":
            continue
        if not (row.get("matches_sender_own_quote") == "True"
                and row.get("directly_masked_in_history") == "True"
                and row.get("current_quote_also_hidden") == "True"
                and row.get("sender") == row.get("quote_owner")):
            continue
        seed = int(row["seed"])
        sent_round = int(row["sent_round"])
        received_round = int(row["received_round"])
        if received_round > 6:
            continue
        bundle_name = f"seed_{seed}_partial_on"
        bundle = bundles.get(bundle_name)
        if bundle is None:
            continue
        if bundle not in seals:
            verify(bundle)
            meta = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
            if meta.get("status") != "complete" or meta.get("backend") != "live":
                continue
            if meta.get("model") != MODEL or meta.get("modal_serving_runtime") != EXPECTED_SOURCE_RUNTIME:
                raise ValueError(f"Source model/runtime differs from the frozen probe contract: {bundle}")
            seals[bundle] = sha_file(bundle / "checksums.json")
            observations[bundle] = {
                (int(o["seed"]), int(o["round"]), o["observer"]): o
                for o in load_jsonl(bundle / "observations.jsonl")
                if o.get("role") == "seller"
            }
            rounds[bundle] = _market_rounds(bundle, seed)
            prompts[bundle] = _response_prompts(bundle)
        obs = observations[bundle].get((seed, received_round, row["recipient"]))
        if obs is None:
            continue
        quote = next((q for q in obs.get("true_observation", {}).get("ask_queue", [])
                      if q[1] == row["quote_owner"] and money_equal(q[0], row["quote_price"])), None)
        if quote is None:
            continue
        current_mask = _mask_row(obs, row["quote_owner"], row["quote_price"], sent_round, "current_quote_masks")
        history_mask = _mask_row(obs, row["quote_owner"], row["quote_price"], sent_round, "historical_quote_masks")
        if not current_mask or current_mask.get("visible") is not False:
            continue
        if not history_mask or history_mask.get("visible") is not False:
            continue
        round_record = rounds[bundle].get(sent_round)
        if round_record is None:
            continue
        market = round_record.get("market", {})
        sent_text = market.get("seller_messages", {}).get(row["sender"])
        if not isinstance(sent_text, str) or sent_text != row["message"]:
            continue
        actual_ask = market.get("seller_asks", {}).get(row["sender"])
        if not money_equal(actual_ask, row["quote_price"]):
            continue
        claims = [m for m in SELF_ASK.finditer(sent_text)]
        claimed = [next((x for x in m.groups() if x is not None), None) for m in claims]
        reported_prices = [m.group("amount") for m in PRICE.finditer(sent_text)]
        if len(claims) != 1 or not claimed[0] or not money_equal(claimed[0], actual_ask):
            continue
        # A single factual number is required so the intervention changes only
        # the reported quote, never a recommendation or a second numeric claim.
        if len(reported_prices) != 1 or not money_equal(reported_prices[0], actual_ask):
            continue
        event = prompts[bundle].get((seed, received_round, row["recipient"]))
        if event is None:
            continue
        prompt = event["prompt"]
        message_line = f"- From {row['sender']}: {sent_text}"
        if prompt.count(message_line) != 1:
            continue
        # Exclude cases where the exact reported fact is already disclosed
        # elsewhere in the recipient's prompt, including another message.
        without_message = prompt.replace(message_line, "", 1)
        quoted_fact = PRICE.search(sent_text)
        fact_text = quoted_fact.group(0) if quoted_fact else ""
        if not fact_text:
            continue
        # Prevent the fabricated ±$10 report from coinciding with a separate
        # number already present in the hidden prompt.
        shifted = (float(actual_ask) + 10, float(actual_ask) - 10)
        if _owner_price_assertion_exists(without_message, row["quote_owner"], actual_ask):
            continue
        if any(_owner_price_assertion_exists(without_message, row["quote_owner"], value) for value in shifted):
            continue
        if not ASK_QUEUE.search(prompt) or not HISTORY.search(prompt):
            continue
        if any(row["quote_owner"] == owner and money_equal(price, row["quote_price"])
               for price, owner in ast.literal_eval(ASK_QUEUE.search(prompt).group(2))):
            continue
        hist_true = obs.get("true_observation", {}).get("past_bids_and_asks", "")
        historical_quote_line = _historical_quote_line(hist_true, sent_round, row["quote_owner"], row["quote_price"])
        if historical_quote_line and historical_quote_line in HISTORY.search(prompt).group(2):
            continue
        output.append({
            "seed": seed, "cell": "partial_on", "round": received_round,
            "sent_round": sent_round, "recipient": row["recipient"], "sender": row["sender"],
            "quote_owner": row["quote_owner"], "quote_price": float(row["quote_price"]),
            "message": sent_text, "message_line": message_line,
            "quote_current_at_decision": True,
            "quote_historical_at_decision": bool(historical_quote_line),
            "historical_quote_line": historical_quote_line,
            "prompt": prompt, "prompt_sha256": sha_bytes(prompt.encode("utf-8")),
            "source_bundle": str(bundle.relative_to(ROOT)).replace("\\", "/"),
            "source_cell_seal_sha256": seals[bundle],
            "source_event_call": event.get("call"),
            "source_event_schema_version": event.get("schema_version"),
            "source_observation": obs,
            "selection_reason": "Verified sender self-ask; matching live quote hidden from current and historical direct displays; matching fact absent elsewhere in the recipient prompt.",
        })
    # Deterministic round-robin across seeds first, then early rounds and roles.
    output.sort(key=lambda s: (s["round"], s["seed"], s["sender"], s["recipient"]))
    by_seed = {seed: [s for s in output if s["seed"] == seed]
               for seed in sorted({s["seed"] for s in output})}
    selected = []
    seen_pairs = set()
    # Round-robin one candidate per market in each pass, preferring new sender /
    # recipient combinations. This prevents the cap from being filled by a
    # single large seed when candidates exist elsewhere.
    while any(by_seed.values()) and len(selected) < limit:
        progressed = False
        for seed in by_seed:
            while by_seed[seed]:
                state = by_seed[seed].pop(0)
                pair = (state["sender"], state["recipient"])
                if unique_pairs and pair in seen_pairs:
                    continue
                selected.append(state)
                seen_pairs.add(pair)
                progressed = True
                break
            if len(selected) >= limit:
                break
        if not progressed:
            break
    return selected[:limit]


def _historical_quote_line(history: str, quote_round: int, owner: str, price):
    blocks = re.split(r"(?=^Hour \d+:)", history, flags=re.M)
    for block in blocks:
        if not block.startswith(f"Hour {quote_round}:"):
            continue
        for line in block.splitlines():
            match = re.match(r"\s*" + re.escape(owner) + r" ask \$\s*(\d+(?:\.\d{1,2})?)\s*$", line)
            if match and money_equal(match.group(1), price):
                return line
    return None


def _replace_history_block(history_text: str, quote_round: int, line: str):
    if line in history_text:
        return history_text
    blocks = re.split(r"(?=^Hour \d+:)", history_text, flags=re.M)
    target = f"Hour {quote_round}:"
    changed = False
    for i, block in enumerate(blocks):
        if not block.startswith(target):
            continue
        rows = block.splitlines(keepends=True)
        insert = next((j for j, row in enumerate(rows) if re.match(r"\s+Buyer ", row)), len(rows))
        rows.insert(insert, line + "\n")
        blocks[i] = "".join(rows)
        changed = True
        break
    if not changed:
        raise ValueError(f"Could not find historical Hour {quote_round} block")
    return "".join(blocks)


def _restore_quote(prompt: str, state):
    obs = state["source_observation"]["true_observation"]
    match = ASK_QUEUE.search(prompt)
    if not match:
        raise ValueError("Current ask queue is missing")
    shown = ast.literal_eval(match.group(2))
    true_queue = obs["ask_queue"]
    owner, price = state["quote_owner"], state["quote_price"]
    target = next((q for q in true_queue if q[1] == owner and money_equal(q[0], price)), None)
    if target is None:
        raise ValueError("Quote is not present in the saved true current book")
    if not any(q[1] == owner and money_equal(q[0], price) for q in shown):
        if any(q[1] == owner for q in shown):
            raise ValueError("Current queue already contains another standing quote for target seller")
        shown.append(target)
        true_order = { (q[1], round(float(q[0]), 2)): i for i, q in enumerate(true_queue) }
        shown.sort(key=lambda q: true_order.get((q[1], round(float(q[0]), 2)), len(true_order)))
        prompt = prompt[:match.start(2)] + repr(shown) + prompt[match.end(2):]
    hist_line = state.get("historical_quote_line")
    if hist_line:
        hist = HISTORY.search(prompt)
        if not hist:
            raise ValueError("Historical quote block is missing")
        merged = _replace_history_block(hist.group(2), state["sent_round"], hist_line)
        prompt = prompt[:hist.start(2)] + merged + prompt[hist.end(2):]
    return prompt


def _message_transform(prompt: str, state, mode: str):
    line = state["message_line"]
    if prompt.count(line) != 1:
        raise ValueError("Selected incoming message is not present exactly once")
    amount = PRICE.search(state["message"])
    if amount is None:
        raise ValueError("Selected message has no factual price token")
    value = float(amount.group("amount"))
    if mode == "original":
        return prompt
    if mode == "absent":
        return prompt.replace(line + "\n", "", 1)
    if mode == "redacted":
        replacement_text = PRICE.sub("[price withheld]", state["message"], count=1)
    elif mode in ("up10", "down10"):
        changed = value + (10 if mode == "up10" else -10)
        if changed < 0:
            raise ValueError("Distorted price would be negative")
        decimals = len(amount.group("amount").split(".")[1]) if "." in amount.group("amount") else 0
        replacement = f"${changed:.{decimals}f}"
        replacement_text = PRICE.sub(lambda m: replacement, state["message"], count=1)
    else:
        raise ValueError(f"Unknown message condition {mode}")
    new_line = f"- From {state['sender']}: {replacement_text}"
    return prompt.replace(line, new_line, 1)


def build_prompts(state):
    result = {}
    for visibility in VISIBILITIES:
        base = state["prompt"] if visibility == "hidden" else _restore_quote(state["prompt"], state)
        for message_mode in MESSAGE_MODES:
            prompt = _message_transform(base, state, message_mode)
            key = f"{visibility}_{message_mode}"
            result[key] = {"visibility": visibility, "message_mode": message_mode,
                           "prompt": prompt, "prompt_sha256": sha_bytes(prompt.encode("utf-8"))}
    return result


def make_plan():
    states = _candidate_states()
    if not states:
        raise RuntimeError("No clean eligible recipient decision states passed the frozen-source checks")
    for state in states:
        state["conditions"] = build_prompts(state)
    decisions = len(states) * len(VISIBILITIES) * len(MESSAGE_MODES) * len(SAMPLING_SEEDS)
    return {
        "version": "message-content-public-quote-factorial-v1",
        "scientific_question": "Does the immediate influence of factual seller-to-seller communication depend on whether the recipient can independently observe the reported quote?",
        "interpretation": "Exploratory decision-level probe; no complete-market mediation or mechanistic claim.",
        "model": MODEL,
        "seeds": list(SAMPLING_SEEDS),
        "visibilities": list(VISIBILITIES),
        "message_conditions": list(MESSAGE_MODES),
        "states": states,
        "selected_state_count": len(states),
        "source_market_count": len({s["seed"] for s in states}),
        "unique_source_message_count": len({(s["seed"], s["sent_round"], s["sender"]) for s in states}),
        "decisions": decisions,
        "warmup_requests": 1,
        "maximum_requests": decisions + 1,
        "max_tokens": 1200,
        "temperature": 0.7,
        "schema_version": "agent-action-json-v1",
        "serving_stack": {"vllm": "0.6.6", "xgrammar": "0.1.13", "outlines": "0.1.11", "guided_decoding_backend": "outlines"},
        "selection_rule": "Completed partial-visibility communication-ON source cells, rounds 2-6; conservative explicit self-ask wording and exactly one numeric price match the sender's actual standing ask; quote is absent from recipient current and historical direct displays; message fact has no exact price-token duplicate elsewhere in that recipient prompt; deterministic round-robin across markets, up to ten states.",
        "order_rule": "For each state × sampling seed, rotate the ten conditions by a deterministic offset; same sampling seed is reused across all ten treatments. No retries.",
        "request_cost_note": "One seller schema warmup plus one request per planned decision; max requests equals decisions plus one warmup. Lambda instance time is billed separately.",
    }


def validate_plan(plan, max_states=10, max_decisions=200):
    assert plan["maximum_requests"] == plan["decisions"] + plan["warmup_requests"]
    assert plan["decisions"] <= max_decisions
    assert len(plan["states"]) <= max_states
    assert len({(s["seed"], s["round"], s["sender"], s["recipient"]) for s in plan["states"]}) == len(plan["states"])
    for state in plan["states"]:
        conditions = state["conditions"]
        original_hidden = conditions["hidden_original"]["prompt"]
        if original_hidden != state["prompt"]:
            raise ValueError("ORIGINAL/HIDDEN does not reconstruct the saved prompt byte-for-byte")
        if conditions["restored_original"]["prompt"] == original_hidden:
            raise ValueError("RESTORED quote condition did not alter the prompt")
        actual = state["quote_price"]
        for visibility in VISIBILITIES:
            base = conditions[f"{visibility}_original"]["prompt"]
            for mode in MESSAGE_MODES:
                item = conditions[f"{visibility}_{mode}"]
                if item["visibility"] != visibility or item["message_mode"] != mode:
                    raise ValueError("Condition labels do not match condition key")
                changed_line = next((line for line in item["prompt"].splitlines()
                                     if line.startswith(f"- From {state['sender']}:")), None)
                if mode == "absent":
                    if changed_line == state["message_line"]:
                        raise ValueError("ABSENT condition retained target message")
                elif mode == "redacted":
                    if "[price withheld]" not in (changed_line or ""):
                        raise ValueError("REDACTED condition did not replace factual price")
                elif mode in ("up10", "down10"):
                    shift = 10 if mode == "up10" else -10
                    expected = f"${actual + shift:.2f}"
                    if expected not in (changed_line or ""):
                        raise ValueError(f"{mode} condition lacks the intended price transformation")
                elif changed_line != state["message_line"]:
                    raise ValueError("ORIGINAL message was changed")
            if visibility == "hidden":
                queue_match = ASK_QUEUE.search(base)
                queue = ast.literal_eval(queue_match.group(2))
                if any(owner == state["quote_owner"] and money_equal(price, actual) for price, owner in queue):
                    raise ValueError("HIDDEN condition exposes target quote in current queue")
                hist = HISTORY.search(base).group(2)
                if state["historical_quote_line"] and state["historical_quote_line"] in hist:
                    raise ValueError("HIDDEN condition exposes target quote in historical display")
            else:
                queue = ast.literal_eval(ASK_QUEUE.search(base).group(2))
                quote_visible = any(owner == state["quote_owner"] and money_equal(price, actual) for price, owner in queue)
                history_visible = bool(state["historical_quote_line"] and state["historical_quote_line"] in HISTORY.search(base).group(2))
                if not quote_visible and not history_visible:
                    raise ValueError("RESTORED condition fails to expose truthful target quote")
    return {"valid": True, "states": len(plan["states"]), "decisions": plan["decisions"],
            "maximum_requests": plan["maximum_requests"], "checks": ["source seals", "byte-exact original prompt", "single-target message edits", "hidden/restored quote visibility", "treatment count ceiling"]}


def _manifest(root: Path):
    files = sorted(path for path in root.rglob("*") if path.is_file() and path.name != "source_sha256.json")
    return {str(path.relative_to(root)).replace("\\", "/"): sha_file(path) for path in files}


def package(plan_path: Path, out: Path):
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    summary = validate_plan(plan)
    if out.exists():
        raise FileExistsError(f"Output already exists: {out}")
    files = {
        "message_channel_worker.py": HERE / "message_channel_worker.py",
        "Dockerfile": HERE / "message_channel_probe_v1/Dockerfile",
        "run_message_channel.sh": HERE / "message_channel_probe_v1/run_message_channel.sh",
        "README.md": HERE / "message_channel_probe_v1/README.md",
    }
    for source in files.values():
        if not source.is_file():
            raise FileNotFoundError(f"Missing package source: {source}")
    out.mkdir(parents=True)
    shutil.copyfile(plan_path, out / "plan.json")
    for name, source in files.items():
        shutil.copyfile(source, out / name)
    shutil.copyfile(ROOT / "util/poseidon_compute/runtime_metadata.py", out / "runtime_metadata.py")
    shutil.copyfile(ROOT / "research/endogenous_defection/response_schema.py", out / "response_schema.py")
    (out / "validation.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    hashes = _manifest(out)
    (out / "source_sha256.json").write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    archive = out.with_suffix(".tar.gz")
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(out, arcname=out.name)
    return archive


def mock_worker(plan_path: Path, out: Path):
    """Run the packaged worker against an in-process fake OpenAI endpoint."""
    import sys
    import urllib.request
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(ROOT / "research/endogenous_defection"))
    sys.path.insert(0, str(ROOT / "util/poseidon_compute"))
    import message_channel_worker as worker
    from runtime_metadata import RUNTIME_HEADER

    runtime = {"vllm": "0.6.6", "xgrammar": "0.1.13", "outlines": "0.1.11",
               "guided_decoding_backend": "outlines",
               "required_api": "vllm guided_json via outlines backend", "required_api_available": True}
    attempts = {"warmup": 0, "decisions": 0}
    original_config = worker.BASE, worker.API_KEY, worker.PROVIDER
    worker.BASE = "https://modal.test/v1"
    worker.API_KEY = "mock-modal-token"
    worker.PROVIDER = "Modal-hosted"

    class FakeResponse:
        def __init__(self, payload, headers=None):
            self._payload = payload
            self.headers = headers or {}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return self._payload

    def fake_urlopen(request, timeout=0):
        url = request if isinstance(request, str) else request.full_url
        if isinstance(request, urllib.request.Request):
            if request.get_header("Authorization") != "Bearer mock-modal-token":
                raise AssertionError("Worker did not authenticate its Modal endpoint request")
        if url.endswith("/models"):
            return FakeResponse(json.dumps({"data": [{"id": MODEL}]}).encode("utf-8"),
                                {RUNTIME_HEADER: json.dumps(runtime)})
        if url.endswith("/chat/completions"):
            payload = json.loads(request.data.decode("utf-8"))
            if payload["model"] != MODEL:
                raise AssertionError("Worker tried a different model")
            if payload["max_tokens"] == 128:
                attempts["warmup"] += 1
                ask = 85.0
            else:
                attempts["decisions"] += 1
                ask = "null" if attempts["decisions"] % 13 == 0 else 84.25
            content = {"reflection": "mock", "plan_for_this_hour": "mock", "ask": ask,
                       "new_memory": "mock", "plan_for_message": "mock",
                       "message_to_sellers": None, "scratch_pad_update": "mock"}
            response = {"model": MODEL, "choices": [{"finish_reason": "stop",
                        "message": {"content": json.dumps(content)}}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
            return FakeResponse(json.dumps(response).encode("utf-8"))
        raise AssertionError("Unexpected worker endpoint: " + url)

    original = worker.urllib.request.urlopen
    worker.urllib.request.urlopen = fake_urlopen
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            worker.run(plan_path, out)
    finally:
        worker.urllib.request.urlopen = original
        worker.BASE, worker.API_KEY, worker.PROVIDER = original_config
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    expected = json.loads(plan_path.read_text(encoding="utf-8"))["decisions"]
    if (attempts["warmup"] != 1 or attempts["decisions"] != expected
            or summary["requests"] != expected + 1 or summary["status"] != "complete"
            or summary["provider"] != "Modal-hosted"):
        raise ValueError("Mock endpoint did not exercise the complete fixed worker request set")
    for relative, expected_hash in json.loads((out / "checksums.json").read_text(encoding="utf-8")).items():
        if sha_file(out / relative) != expected_hash:
            raise ValueError(f"Mock worker result checksum mismatch: {relative}")
    return {"warmup_requests": attempts["warmup"], "decision_requests": attempts["decisions"],
            "total_requests": summary["requests"], "status": summary["status"],
            "paid_inference_requests": 0, "interpretation": "Fake local HTTP endpoint only; no model evidence."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("plan", "validate", "mock", "package"), required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "output/message_channel_probe_v1")
    parser.add_argument("--plan", type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    if args.stage == "plan":
        plan = make_plan()
        validate_plan(plan)
        if out.exists():
            raise FileExistsError(f"Output already exists: {out}")
        out.mkdir(parents=True)
        (out / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in plan.items() if k != "states"}, indent=2))
        print(f"PLAN {out / 'plan.json'}")
        return 0
    plan_path = args.plan.resolve() if args.plan else out / "plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if args.stage == "validate":
        if plan != make_plan():
            raise ValueError("Plan differs from freshly reverified source evidence or deterministic selector")
        print(json.dumps(validate_plan(plan), indent=2))
        return 0
    if args.stage == "mock":
        result = validate_plan(plan)
        # Exercise the bounded response parser contract with deterministic fixtures.
        fixtures = [
            {"reflection": "mock", "plan_for_this_hour": "mock", "ask": 85.0,
             "new_memory": "mock", "plan_for_message": "mock", "message_to_sellers": "mock",
             "scratch_pad_update": "mock"},
            {"reflection": "mock", "plan_for_this_hour": "mock", "ask": "null",
             "new_memory": "mock", "plan_for_message": "mock", "message_to_sellers": None,
             "scratch_pad_update": "mock"},
        ]
        schema_path = ROOT / "research/endogenous_defection/response_schema.py"
        # This offline smoke builds the full fixed request matrix and validates
        # mock numerical and withdrawal outputs against the saved seller contract.
        from research.endogenous_defection.response_schema import seller_schema
        try:
            from jsonschema import validate as validate_schema
        except ImportError as exc:
            raise RuntimeError("Install project dependencies before mocked validation") from exc
        schema = seller_schema(True)
        mock_rows = 0
        mock_decisions = []
        for state_index, state in enumerate(plan["states"]):
            for seed in plan["seeds"]:
                for mode_index, (key, condition) in enumerate(state["conditions"].items()):
                    payload = {"model": plan["model"], "messages": [{"role": "user", "content": condition["prompt"]}],
                               "temperature": plan["temperature"], "seed": seed,
                               "max_tokens": plan["max_tokens"], "guided_json": schema}
                    if payload["model"] != MODEL or payload["seed"] != seed or not payload["messages"][0]["content"]:
                        raise ValueError("Mock request does not preserve the pinned model/prompt/sampling seed")
                    fixture = fixtures[mock_rows % len(fixtures)]
                    validate_schema(instance=fixture, schema=schema)
                    if len(key.split("_", 1)) != 2 or condition["prompt_sha256"] != sha_bytes(condition["prompt"].encode("utf-8")):
                        raise ValueError("Mock condition metadata or prompt hash is invalid")
                    withdrawn = (mock_rows % 11 == 0)
                    mock_decisions.append({
                        "decision_index": mock_rows + 1, "state_index": state_index,
                        "seed": state["seed"], "round": state["round"], "sender": state["sender"],
                        "recipient": state["recipient"], "sampling_seed": seed,
                        "visibility": condition["visibility"], "message_mode": condition["message_mode"],
                        "accepted": True, "ask": "" if withdrawn else str(80 + ((state_index + int(seed) + mode_index) % 8)),
                        "withdrawal": str(withdrawn), "finish_reason": "stop",
                    })
                    mock_rows += 1
        mock_root = out / "mock_results"
        if mock_root.exists() or (out / "mock_analysis").exists() or (out / "mock_validation.json").exists():
            raise FileExistsError("Mock output already exists; use a fresh --out directory")
        mock_root.mkdir(parents=True)
        with (mock_root / "decisions.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(mock_decisions[0]))
            writer.writeheader()
            writer.writerows(mock_decisions)
        (mock_root / "checksums.json").write_text(json.dumps({
            "decisions.csv": sha_file(mock_root / "decisions.csv")
        }, indent=2) + "\n", encoding="utf-8")
        from research.lambda_smoke.analyze_message_channel import analyze
        analyze(mock_root, plan_path, out / "mock_analysis")
        worker_result = mock_worker(plan_path, out / "mock_worker_results")
        result["mocked_fixture_responses"] = len(fixtures)
        result["mocked_request_rows"] = mock_rows
        result["mock_worker_validation"] = worker_result
        result["paid_inference_requests"] = 0
        result["mock_analysis_rows"] = len(mock_decisions)
        result["interpretation"] = "Mock plumbing validation only; no model behavior evidence."
        destination = out / "mock_validation.json"
        if destination.exists():
            raise FileExistsError(destination)
        out.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
        return 0
    if args.stage == "package":
        if plan != make_plan():
            raise ValueError("Refusing to package a plan that differs from freshly reverified source evidence")
        archive = package(plan_path, out)
        print(f"BUNDLE {out}")
        print(f"ARCHIVE {archive}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
