"""Offline baseline budget/benchmark scenarios; never constructs an inference client."""

import argparse
import json
from pathlib import Path

from .config import load_protocol
from .economics import benchmarks

HERE = Path(__file__).resolve().parent


def plans():
    a = load_protocol(HERE / "configs/baseline_A_qwen_v1.json")
    b = load_protocol(HERE / "configs/baseline_B_reference_v1.json")
    calls_a, calls_b = a.call_estimate()["control"], b.call_estimate()["control"]
    # Published rates fetched 2026-10-23. CPU/RAM are explicit assumed allocations,
    # not measured account usage. Dollar envelopes are proposals, not enforced caps.
    gpu, cpu, ram = 0.000306, 0.0000131, 0.00000222
    a_scenarios = []
    for label, seconds_per_call, startup_seconds in (
        ("lower", 12, 120),
        ("higher", 25, 600),
    ):
        seconds = calls_a * seconds_per_call + startup_seconds
        a_scenarios.append(
            {
                "scenario": label,
                "seconds_per_call": seconds_per_call,
                "startup_seconds": startup_seconds,
                "billed_seconds_assumed": seconds,
                "gpu_usd": round(seconds * gpu, 4),
                "cpu_1_core_ram_16_gib_usd": round(seconds * (cpu + 16 * ram), 4),
                "total_usd_assuming_1_core_16_gib": round(
                    seconds * (gpu + cpu + 16 * ram), 4
                ),
            }
        )
    b_scenarios = []
    for label, input_tokens, output_tokens in (
        ("lower", 2000, 300),
        ("higher", 8000, 600),
        ("stress", 12000, b.max_tokens),
    ):
        b_scenarios.append(
            {
                "scenario": label,
                "mean_input_tokens": input_tokens,
                "mean_output_tokens": output_tokens,
                "usd_at_openai_standard_rates": round(
                    calls_b * (input_tokens * 2 + output_tokens * 8) / 1e6, 4
                ),
            }
        )
    return {
        "prepared_date": "2026-10-23",
        "currency": "USD",
        "paid_execution_performed": False,
        "approval_required": True,
        "rate_sources": {
            "modal": "https://modal.com/pricing",
            "gpt41": "https://developers.openai.com/api/docs/models/gpt-4.1",
        },
        "rate_assumptions": {
            "a10_gpu_per_second": gpu,
            "cpu_core_per_second": cpu,
            "ram_gib_per_second": ram,
            "gpt41_input_per_million": 2,
            "gpt41_output_per_million": 8,
            "cached_input_discount_assumed": False,
        },
        "A": {
            "config": "configs/baseline_A_qwen_v1.json",
            "model": a.model_id,
            "calls": calls_a,
            "max_generated_tokens": calls_a * a.max_tokens,
            "benchmark": benchmarks(a.buyer_values, a.seller_costs),
            "scenarios": a_scenarios,
            "proposed_planning_envelope_usd": 3,
            "execution_enabled": a.execution_enabled,
        },
        "B": {
            "config": "configs/baseline_B_reference_v1.json",
            "model": b.model_id,
            "calls": calls_b,
            "max_generated_tokens": calls_b * b.max_tokens,
            "benchmark": benchmarks(b.buyer_values, b.seller_costs),
            "scenarios": b_scenarios,
            "proposed_planning_envelope_usd": 60,
            "execution_enabled": b.execution_enabled,
            "model_status": "Official page marks model deprecated; exact snapshot availability unverified",
            "local_gpu_cost_usd": 0,
        },
        "limits": [
            "Scenarios are estimates, not charges or dollar caps.",
            "Request and output caps are enforceable; cumulative input/dollar caps are not implemented.",
            "CPU/RAM, region, startup, networking and actual provider quotes can change cost.",
            "Input histories can exceed assumptions; stop and review before exceeding the proposed envelope.",
            "Modal credit balance and API credit balance are unknown and separate.",
            "Reserve at least 50 percent of verified remaining Modal credit for replication/contingency.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    rendered = json.dumps(plans(), indent=2, allow_nan=False) + "\n"
    if args.out:
        with args.out.open("x", encoding="utf-8") as handle:
            handle.write(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
