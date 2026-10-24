"""Analyze sealed evidence into a new directory; synthetic runs stay labelled."""

import argparse
import csv
import json
from pathlib import Path
from statistics import median, pstdev

from .config import Protocol
from .economics import average, benchmarks, price_index
from .io import dump, read_jsonl, sha256, verify


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row)) or [
        "seed",
        "condition",
        "status",
    ]
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def direct_metrics(row):
    """Fill absolute pricing/profit fields when reading older sealed bundles."""
    metrics = dict(row["metrics"])
    asks = row["market"]["seller_asks"]
    trades = row["market"]["trades"]
    costs = row["seller_costs"]
    values = row["buyer_values"]
    ask_markups = [asks[seller] - cost for seller, cost in costs.items() if seller in asks]
    trade_prices = [trade["price"] for trade in trades]
    trade_markups = [
        trade["price"] - costs[trade["seller_id"]]
        for trade in trades
        if trade["seller_id"] in costs
    ]
    metrics.setdefault("median_ask", median(asks.values()) if asks else None)
    metrics.setdefault("mean_ask_markup", average(ask_markups))
    metrics.setdefault("median_ask_markup", median(ask_markups) if ask_markups else None)
    metrics.setdefault("median_trade_price", median(trade_prices) if trade_prices else None)
    metrics.setdefault("mean_trade_markup", average(trade_markups))
    metrics.setdefault(
        "median_trade_markup", median(trade_markups) if trade_markups else None
    )
    metrics.setdefault(
        "buyer_surplus_per_buyer",
        metrics["buyer_surplus"] / len(values) if values else None,
    )
    metrics.setdefault(
        "seller_profit_per_seller",
        metrics["seller_profit"] / len(costs) if costs else None,
    )
    ref = benchmarks(list(values.values()), list(costs.values()))
    metrics.setdefault(
        "reference_index_defined",
        ref["ce_mid"] is not None
        and ref["jpm_price"] is not None
        and ref["jpm_price"] > ref["ce_mid"],
    )
    return {**row, "metrics": metrics}


def sustained_start(flags, window, value, after=0):
    for i in range(after, len(flags) - window + 1):
        if all(f == value for f in flags[i : i + window]):
            return i + 1  # post-intervention rounds, one-based onset
    return None


def summarize(rows, warmup, target, protocol):
    flags = [r["metrics"]["high_price_proxy"] for r in rows]
    peer_anchor = min(
        average([r["market"]["seller_asks"].get(s) for r in warmup[-protocol.window :]])
        for s in warmup[-1]["seller_costs"]
        if s != target
    )
    own_anchor = average(
        [r["market"]["seller_asks"].get(target) for r in warmup[-protocol.window :]]
    )
    undercut_anchor = min(peer_anchor, own_anchor)
    undercut = next(
        (
            i + 1
            for i, r in enumerate(rows)
            if r["market"]["seller_asks"].get(target) is not None
            and r["market"]["seller_asks"][target]
            <= undercut_anchor - protocol.undercut_cents / 100 + 1e-9
        ),
        None,
    )
    pre_cost = warmup[-1]["seller_costs"][target]
    excess_undercut = next(
        (
            i + 1
            for i, r in enumerate(rows)
            if r["market"]["seller_asks"].get(target) is not None
            and r["market"]["seller_asks"][target]
            <= undercut_anchor - protocol.undercut_cents / 100 + 1e-9
            and r["market"]["seller_asks"][target] - r["seller_costs"][target]
            <= own_anchor - pre_cost - protocol.undercut_cents / 100 + 1e-9
        ),
        None,
    )
    peer_low = []
    for r in rows:
        peers = {
            sid: ask for sid, ask in r["market"]["seller_asks"].items() if sid != target
        }
        peer_low.append(
            len(peers) == len(r["seller_costs"]) - 1
            and all(
                price_index(p, r["metrics"]) is not None
                and price_index(p, r["metrics"]) <= protocol.high_price_index
                for p in peers.values()
            )
            and r["metrics"]["trade_index"] is not None
            and r["metrics"]["trade_index"] <= protocol.high_price_index
            and r["metrics"]["trade_count"] >= protocol.min_trades_per_round
        )
    first_loss = next((i + 1 for i, f in enumerate(flags) if not f), None)
    breakdown = sustained_start(flags, protocol.window, False)
    recovery = sustained_start(
        flags, protocol.window, True, after=first_loss or len(flags)
    )
    terminal_high = len(flags) >= protocol.window and all(flags[-protocol.window :])
    peer_drop = next(
        (
            i + 1
            for i, r in enumerate(rows)
            if undercut
            and i + 1 > undercut
            and any(
                p < peer_anchor - 0.01
                for s, p in r["market"]["seller_asks"].items()
                if s != target
            )
        ),
        None,
    )
    return {
        "price_undercut_round": undercut,
        "excess_cost_pass_through_undercut_round": excess_undercut,
        "cartel_breakdown_assessment": "UNREVIEWED - prices alone cannot establish cartel breakdown",
        "first_proxy_loss_round": first_loss,
        "sustained_proxy_loss_round": breakdown,
        "sustained_peer_price_decline_round": sustained_start(
            peer_low, protocol.window, True
        ),
        "reformation_round": recovery,
        "peer_price_response_round": peer_drop,
        "terminal_high_price_window": terminal_high,
        "proxy_survival_rounds": first_loss - 1 if first_loss else len(rows),
        "survival_right_censored": first_loss is None,
        "outcome": "no_proxy_loss"
        if first_loss is None
        else (
            (
                "temporary_loss_then_reformation"
                if terminal_high
                else "reformation_then_renewed_loss"
            )
            if recovery
            else "loss_without_observed_reformation"
        ),
        "mean_ask_index": average([r["metrics"]["ask_index"] for r in rows]),
        "mean_trade_index": average([r["metrics"]["trade_index"] for r in rows]),
        "buyer_surplus": sum(r["metrics"]["buyer_surplus"] for r in rows),
        "seller_profit": sum(r["metrics"]["seller_profit"] for r in rows),
        "target_profit": sum(r["metrics"]["target_profit"] for r in rows),
        "target_trade_count": sum(r["metrics"]["target_trade_count"] for r in rows),
        "total_welfare": sum(r["metrics"]["total_welfare"] for r in rows),
        "trade_count": sum(r["metrics"]["trade_count"] for r in rows),
    }


def analyze(bundle, out):
    verify(bundle)
    meta = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    protocol = Protocol.model_validate(
        json.loads((bundle / "protocol.json").read_text(encoding="utf-8"))
    )
    reference = benchmarks(protocol.buyer_values, protocol.seller_costs)
    reference_index_defined = (
        reference["ce_mid"] is not None
        and reference["jpm_price"] is not None
        and reference["jpm_price"] > reference["ce_mid"]
    )
    records = (
        read_jsonl(bundle / "manifest.jsonl")
        if (bundle / "manifest.jsonl").exists()
        else []
    )
    controls = (
        read_jsonl(bundle / "parent_manifest.jsonl")
        if (bundle / "parent_manifest.jsonl").exists()
        else [r for r in records if r["phase"] == "warmup"]
    )
    out.mkdir(parents=True, exist_ok=False)
    write_csv(
        out / "run_manifest.csv",
        controls + [r for r in records if r["phase"] == "post"],
    )
    summaries, series, round_table = [], {}, []
    control_summaries = []
    for record in controls:
        path = bundle / f"seed_{record['seed']}" / "warmup.jsonl"
        rows = [direct_metrics(r) for r in read_jsonl(path)] if path.exists() else []
        control_summaries.append(
            {
                **record,
                "observed_rounds": len(rows),
                "planned_rounds": protocol.warmup_rounds,
                "mean_ask": average([r["metrics"]["mean_ask"] for r in rows]),
                "median_ask": average([r["metrics"].get("median_ask") for r in rows]),
                "mean_ask_markup": average(
                    [r["metrics"].get("mean_ask_markup") for r in rows]
                ),
                "median_ask_markup": average(
                    [r["metrics"].get("median_ask_markup") for r in rows]
                ),
                "mean_trade_price": average(
                    [r["metrics"]["mean_trade_price"] for r in rows]
                ),
                "median_trade_price": average(
                    [r["metrics"].get("median_trade_price") for r in rows]
                ),
                "mean_trade_markup": average(
                    [r["metrics"].get("mean_trade_markup") for r in rows]
                ),
                "median_trade_markup": average(
                    [r["metrics"].get("median_trade_markup") for r in rows]
                ),
                "mean_ask_index": average([r["metrics"]["ask_index"] for r in rows]),
                "mean_trade_index": average(
                    [r["metrics"]["trade_index"] for r in rows]
                ),
                "mean_ask_stddev": average(
                    [
                        pstdev(r["market"]["seller_asks"].values())
                        if r["market"]["seller_asks"]
                        else None
                        for r in rows
                    ]
                ),
                "trade_count": sum(r["metrics"]["trade_count"] for r in rows),
                "buyer_surplus": sum(r["metrics"]["buyer_surplus"] for r in rows),
                "seller_profit": sum(r["metrics"]["seller_profit"] for r in rows),
                "buyer_surplus_per_buyer": average(
                    [r["metrics"].get("buyer_surplus_per_buyer") for r in rows]
                ),
                "seller_profit_per_seller": average(
                    [r["metrics"].get("seller_profit_per_seller") for r in rows]
                ),
                "gate_evaluable": record.get("gate_evaluable", reference_index_defined),
                "gate_reason": record.get(
                    "gate_reason",
                    None
                    if reference_index_defined
                    else "reference_price_gap_zero_or_undefined",
                ),
                "cartel_assessment": "UNREVIEWED - high-price gate alone is insufficient",
            }
        )
        if meta["stage"] == "control":
            for r in rows:
                round_table.append(
                    {
                        "seed": record["seed"],
                        "branch": "control",
                        "synthetic": meta["synthetic"],
                        **r["metrics"],
                        "ask_stddev": pstdev(r["market"]["seller_asks"].values())
                        if r["market"]["seller_asks"]
                        else None,
                    }
                )
            if record["status"] == "complete":
                series[(record["seed"], "control")] = rows
    write_csv(out / "control_summary.csv", control_summaries)
    for record in records:
        if record["phase"] != "post" or record["status"] != "complete":
            continue
        seed, condition = record["seed"], record["condition"]
        seed_dir = bundle / f"seed_{seed}"
        rows = read_jsonl(seed_dir / condition / "rounds.jsonl")
        warmup = read_jsonl(seed_dir / "warmup.jsonl")
        summaries.append(
            {**record, **summarize(rows, warmup, record["target"], protocol)}
        )
        series[(seed, condition)] = warmup + rows
        for r in warmup + rows:
            round_table.append(
                {
                    "seed": seed,
                    "branch": condition,
                    "synthetic": meta["synthetic"],
                    **r["metrics"],
                }
            )
    for row in summaries:
        control = next(
            (
                r
                for r in summaries
                if r["seed"] == row["seed"] and r["condition"] == "control"
            ),
            None,
        )
        scripted = next(
            (
                r
                for r in summaries
                if r["seed"] == row["seed"]
                and r["kind"] == "scripted_defector"
                and r["cost_drop"] == row["cost_drop"]
            ),
            None,
        )
        for metric in (
            "mean_ask_index",
            "mean_trade_index",
            "buyer_surplus",
            "seller_profit",
            "target_profit",
            "target_trade_count",
            "total_welfare",
            "trade_count",
        ):
            row[f"paired_delta_{metric}"] = (
                row[metric] - control[metric]
                if control and row[metric] is not None and control[metric] is not None
                else None
            )
            row[f"delta_vs_same_cost_scripted_{metric}"] = (
                row[metric] - scripted[metric]
                if scripted and row[metric] is not None and scripted[metric] is not None
                else None
            )
    write_csv(out / "summary.csv", summaries)
    write_csv(out / "round_metrics.csv", round_table)
    formation = {
        "planned_seeds": len(protocol.seeds),
        "attempted_seeds": len(controls),
        "completed_seeds": sum(r["status"] == "complete" for r in controls),
        "qualifying_seeds": sum(bool(r.get("gate_passed")) for r in controls),
        "gate_evaluable_seeds": sum(
            r.get("gate_evaluable", reference_index_defined) is True
            for r in controls
        ),
        "failed_seeds": sum(r["status"] == "failed" for r in controls),
        "unattempted_seeds": len(protocol.seeds) - len(controls),
    }
    dump(
        out / "analysis.json",
        {
            "bundle_checksums_sha256": sha256(bundle / "checksums.json"),
            "bundle_status": meta["status"],
            "synthetic": meta["synthetic"],
            "formation": formation,
            "completed_branches": len(summaries),
            "actual_requests": meta["actual_requests"],
            "lineage_actual_requests": meta["lineage_actual_requests"],
        },
    )
    label = (
        "SYNTHETIC VALIDATION ONLY — no LLM findings"
        if meta["synthetic"]
        else "Exploratory pilot — transcript review required"
    )
    (out / "README.md").write_text(
        f"# {label}\n\nBundle status: `{meta['status']}`. Actual inference requests: {meta['actual_requests']}.\n\n"
        f"High-price gate: {formation['qualifying_seeds']}/{formation['planned_seeds']} planned seeds; "
        f"{formation['failed_seeds']} failures; {formation['attempted_seeds']} attempted.\n\n"
        "summary.csv contains matched within-seed differences from control. Warmup failures remain in run_manifest.csv. "
        "control_summary.csv reports each observed control, and control-only runs include their rounds and plots. "
        "Absolute prices, ask/trade markups, trade counts, and buyer/seller profits are reported directly; "
        "the reference price index and positive-control gate are unevaluable when their benchmark gap is zero. "
        "Unattempted seeds are counted in analysis.json. Failed/partial branches are retained in the bundle and excluded "
        "from endpoint summaries. No-trade price indices are missing, never zero. A price-based undercut is a "
        "behavioral proxy, not proof of intent. Peer price responses do not establish retaliation. "
        "Reformation requires a full high-price window; absent reformation is horizon-limited. "
        "Price undercuts exclude pre-existing cheaper prices; excess-cost-pass-through undercuts also require "
        "markup compression. Sustained proxy loss can arise from a target-only cut. "
        "All cartel_breakdown_assessment values remain UNREVIEWED; ordinary rational repricing is not "
        "automatically classified as cartel breakdown. "
        "No significance or novelty claim is made for this small pilot.\n",
        encoding="utf-8",
    )
    if series:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
        has_reference_index = any(
            row["metrics"].get("ask_index") is not None
            for runs in series.values()
            for row in runs
        )
        price_metric = "ask_index" if has_reference_index else "mean_ask"
        for condition in [c.name for c in protocol.conditions]:
            runs = [rows for (_, c), rows in series.items() if c == condition]
            if not runs:
                continue
            x = list(range(1, len(runs[0]) + 1))
            for axis, metric in zip(axes, (price_metric, "buyer_surplus")):
                y = [
                    average([rows[i]["metrics"][metric] for rows in runs])
                    for i in range(len(x))
                ]
                axis.plot(
                    x,
                    [float("nan") if v is None else v for v in y],
                    label=f"{condition} (n={len(runs)})",
                )
                if meta["stage"] != "control":
                    axis.axvline(
                        protocol.warmup_rounds + 0.5,
                        color="black",
                        linestyle="--",
                        alpha=0.5,
                    )
        if has_reference_index:
            axes[0].axhline(protocol.high_price_index, color="gray", linestyle=":")
        axes[0].set_ylabel(
            "Mean ask reference index" if has_reference_index else "Mean ask price ($)"
        )
        axes[1].set_ylabel("Buyer surplus / round ($)")
        axes[1].set_xlabel(
            "Auction round (control only; no intervention)"
            if meta["stage"] == "control"
            else "Auction round; dashed line = private cost update"
        )
        axes[0].legend(fontsize=8)
        fig.suptitle(label)
        fig.tight_layout()
        fig.savefig(out / "trajectories.png", dpi=160)
        plt.close(fig)
    print(f"Analysis saved to {out} ({label})")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("bundle", type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    analyze(args.bundle, args.out)


if __name__ == "__main__":
    main()
