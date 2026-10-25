"""Worker for the frozen message-channel probe on Modal or Lambda."""
import argparse
import csv
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import validate as validate_schema

try:
    from research.endogenous_defection.response_schema import seller_schema
except ImportError:  # self-contained Lambda export
    from response_schema import seller_schema

try:
    from poseidon_compute.runtime_metadata import RUNTIME_HEADER, validate_serving_runtime
except ImportError:  # self-contained Lambda export
    from runtime_metadata import RUNTIME_HEADER, validate_serving_runtime

BASE = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/")
API_KEY = os.environ.get("LLM_API_KEY")
PROVIDER = "Modal-hosted" if os.environ.get("MODAL_SERVING_RUNTIME") else "Lambda Cloud"
MODEL = "Qwen/Qwen2.5-7B-Instruct"
REQUEST_TIMEOUT_SECONDS = 300
WORKER_TIMEOUT_SECONDS = 4 * 60 * 60


def now():
    return datetime.now(timezone.utc).isoformat()


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ask_value(response, schema):
    content = response["choices"][0]["message"]["content"]
    choice = response["choices"][0]
    if choice.get("finish_reason") != "stop":
        raise ValueError("Incomplete generation")
    parsed = json.loads(content)
    validate_schema(instance=parsed, schema=schema)
    raw = parsed["ask"]
    withdrawn = raw is None or raw == "null"
    if withdrawn:
        return parsed, None, True
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError("Ask must be numeric or the documented null withdrawal")
    return parsed, float(raw), False


def write_rows(path, rows):
    if not rows:
        return
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def wait_ready(out, deadline):
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(BASE + "/models")
            if API_KEY:
                req.add_header("Authorization", "Bearer " + API_KEY)
            response = urllib.request.urlopen(req, timeout=10)
        except OSError:
            time.sleep(5)
            continue
        with response:
            runtime = validate_serving_runtime(json.loads(response.headers[RUNTIME_HEADER]))
            models = json.load(response)
        if MODEL not in [item["id"] for item in models.get("data", [])]:
            raise RuntimeError("Served model identity differs from the pinned model")
        dump(out / "runtime.json", {"provider": PROVIDER, "runtime": runtime, "model": MODEL})
        return runtime
    raise TimeoutError("Model readiness exceeded 900 seconds")


def request(payload, index, out, timeout):
    requests = out / "requests"
    responses = out / "responses"
    requests.mkdir(exist_ok=True)
    responses.mkdir(exist_ok=True)
    dump(requests / f"{index:03d}.json", payload)
    req = urllib.request.Request(BASE + "/chat/completions", data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    if API_KEY:
        req.add_header("Authorization", "Bearer " + API_KEY)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
    path = responses / f"{index:03d}.json"
    path.write_bytes(raw)
    return json.loads(raw), path


def run(plan_path: Path, out: Path):
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("model") != MODEL or plan.get("decisions", 999) > 200:
        raise ValueError("Plan model or decision ceiling is invalid")
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    schema = seller_schema(True)
    start = time.monotonic()
    deadline = start + WORKER_TIMEOUT_SECONDS
    calls, rows, status, error_type, runtime_info = 0, [], "incomplete", None, None
    dump(out / "execution.json", {"started_at": now(), "plan_sha256": sha(plan_path),
         "maximum_requests": plan["maximum_requests"], "maximum_decisions": plan["decisions"],
         "worker_timeout_seconds": WORKER_TIMEOUT_SECONDS, "provider": PROVIDER})
    try:
        runtime_info = wait_ready(out, min(deadline, time.monotonic() + 900))
        warmup = {"model": MODEL, "messages": [{"role": "user", "content": "Return a valid seller action JSON with brief text fields and ask 85."}],
                  "temperature": plan["temperature"], "seed": 900,
                  "max_tokens": 128, "guided_json": schema}
        calls = 1
        warm_response, _ = request(warmup, calls, out, min(900, max(10, deadline - time.monotonic())))
        _, _, _ = ask_value(warm_response, schema)
        cases = []
        for state_index, state in enumerate(plan["states"]):
            conditions = list(state["conditions"])
            for sampling_seed in plan["seeds"]:
                offset = (state_index + int(sampling_seed)) % len(conditions)
                ordered = conditions[offset:] + conditions[:offset]
                for key in ordered:
                    case = state["conditions"][key]
                    cases.append((state_index, state, int(sampling_seed), key, case))
        expected = plan["decisions"]
        if len(cases) != expected:
            raise ValueError("Plan decision count differs from enumerated fixed cases")
        for decision_index, (state_index, state, sampling_seed, key, case) in enumerate(cases, start=1):
            if calls >= plan["maximum_requests"]:
                raise RuntimeError("Hard request ceiling exhausted")
            if time.monotonic() >= deadline:
                raise TimeoutError("Four-hour worker ceiling reached")
            calls += 1
            payload = {"model": MODEL, "messages": [{"role": "user", "content": case["prompt"]}],
                       "temperature": plan["temperature"], "seed": sampling_seed,
                       "max_tokens": plan["max_tokens"], "guided_json": schema}
            try:
                response, response_path = request(payload, calls, out,
                                                   min(REQUEST_TIMEOUT_SECONDS, max(10, deadline - time.monotonic())))
            except Exception as exc:
                error_type = type(exc).__name__
                row = {"decision_index": decision_index, "state_index": state_index,
                       "seed": state["seed"], "round": state["round"], "sender": state["sender"],
                       "recipient": state["recipient"], "sampling_seed": sampling_seed,
                       "visibility": case["visibility"], "message_mode": case["message_mode"],
                       "accepted": False, "error_type": error_type}
                rows.append(row)
                write_rows(out / "decisions.csv", rows)
                status = "stopped_transport_or_protocol_failure"
                break
            choice = response.get("choices", [{}])[0]
            row = {"decision_index": decision_index, "state_index": state_index,
                   "seed": state["seed"], "round": state["round"], "sender": state["sender"],
                   "recipient": state["recipient"], "sampling_seed": sampling_seed,
                   "visibility": case["visibility"], "message_mode": case["message_mode"],
                   "accepted": False, "ask": None, "withdrawal": None,
                   "finish_reason": choice.get("finish_reason"), "response_sha256": sha(response_path),
                   "usage": response.get("usage"), "returned_model": response.get("model")}
            try:
                _, ask, withdrawal = ask_value(response, schema)
                row.update(accepted=True, ask=ask, withdrawal=withdrawal)
            except Exception as exc:
                row["error_type"] = type(exc).__name__
                row["error"] = str(exc)[:240]
            rows.append(row)
            write_rows(out / "decisions.csv", rows)
            print("DECISION " + json.dumps(row, sort_keys=True), flush=True)
        if len(rows) == expected:
            status = "complete_with_rejections" if any(not r.get("accepted") for r in rows) else "complete"
    except Exception as exc:
        error_type = type(exc).__name__
        status = "stopped_technical_failure"
    finally:
        summary = {"status": status, "error_type": error_type, "requests": calls,
                   "maximum_requests": plan["maximum_requests"], "planned_decisions": plan["decisions"],
                   "attempted_decisions": len(rows), "accepted_decisions": sum(bool(r.get("accepted")) for r in rows),
                   "runtime": runtime_info, "model": MODEL,
                   "provider": PROVIDER, "scientific_interpretation": "Exploratory decision-level responses; no market was run.",
                   "finished_at": now()}
        dump(out / "summary.json", summary)
        files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "checksums.json")
        dump(out / "checksums.json", {str(p.relative_to(out)).replace("\\", "/"): sha(p) for p in files})
        print("PROBE_SUMMARY " + json.dumps(summary, sort_keys=True), flush=True)
    return 0 if status in ("complete", "complete_with_rejections") else 2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=Path("/app/plan.json"))
    parser.add_argument("--out", type=Path, default=Path("/results/probe"))
    args = parser.parse_args()
    return run(args.plan, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
