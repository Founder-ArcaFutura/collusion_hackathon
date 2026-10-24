"""Two-request live API contract probe; it does not create market rounds."""

import argparse
import json
from pathlib import Path

from .auction import AdapterClient, Session
from .config import load_protocol
from .io import dump, serving_runtime_metadata, utc_now
from .response_schema import SCHEMA_VERSION, schema_for


def run_contract(config, model, out):
    protocol = load_protocol(config)
    if not protocol.execution_enabled:
        raise ValueError("Review-only configuration: user approval is required before live execution")
    if protocol.response_schema_version != SCHEMA_VERSION:
        raise ValueError("Contract probe requires the versioned guided JSON response protocol")
    if not model or model != protocol.model_id:
        raise ValueError("--model must exactly match the protocol model_id")
    out = Path(out)
    if out.exists():
        raise FileExistsError(f"Output directory already exists: {out}")
    out.mkdir(parents=True)
    events = out / "events.jsonl"
    session = None
    failure = None
    checked = []
    status = "failed"
    try:
        session = Session(protocol, model, "live", max_calls=2, event_path=events)
        for index, role in enumerate(("buyer", "seller")):
            action = "bid" if role == "buyer" else "ask"
            schema = schema_for(role, protocol)
            prompt = (
                "API contract probe only; return one minimal JSON response satisfying "
                f"the following role schema. Use a numeric {action} and null for the optional message.\n"
                + json.dumps(schema, sort_keys=True)
            )
            adapter = AdapterClient(
                session, 0, f"Contract {role.title()}", index, role, "contract"
            )
            parsed = json.loads(adapter.generate([{"role": "user", "content": prompt}]))
            checked.append(role)
            del parsed
        status = "passed"
    except Exception as exc:
        failure = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
    finally:
        summary = {
            "status": status,
            "requests": session.calls if session else 0,
            "request_ceiling": 2,
            "roles_checked": checked,
            "schema_version": protocol.response_schema_version,
            "serving_runtime": serving_runtime_metadata(),
            "gate_result": "passed" if status == "passed" else "failed",
            "failure_reason": failure,
            "finished_at": utc_now(),
            "scientific_run": False,
        }
        dump(out / "contract_summary.json", summary)
        print("CONTRACT_SUMMARY " + json.dumps(summary, sort_keys=True), flush=True)
    return 0 if status == "passed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        return run_contract(args.config, args.model, args.out)
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        print(f"Stopped before inference: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
