"""Provider-labelled, state-paired analysis of completed message probes; offline."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
from statistics import mean

from research.lambda_smoke import message_channel_overnight as io
from research.lambda_smoke import message_channel_probe as probe
from research.lambda_smoke import analyze_message_channel as base


def average(values):
    return mean(values) if values else None


def state_id(state):
    return (state["seed"], state["round"], state["sender"], state["recipient"])


def identify_rows(root, plan):
    base.verify_checksums(root)
    rows = base.read_csv(root / "decisions.csv")
    seen = set()
    for row in rows:
        for key in ("state_index", "sampling_seed"):
            row[key] = int(row[key])
        row["accepted"] = base.as_bool(row["accepted"])
        row["withdrawal"] = base.as_bool(row["withdrawal"])
        row["ask"] = base.as_float(row["ask"])
        key = (row["state_index"], row["sampling_seed"], row["visibility"], row["message_mode"])
        if key in seen:
            raise ValueError("Duplicate decision key; cannot silently overwrite evidence")
        seen.add(key)
        state = plan["states"][row["state_index"]]
        condition = state["conditions"][row["visibility"] + "_" + row["message_mode"]]
        if row["sampling_seed"] not in plan["seeds"] or condition["prompt_sha256"] != probe.sha_bytes(condition["prompt"].encode()):
            raise ValueError("Decision does not belong to the frozen plan")
        if row["accepted"] and (row["withdrawal"] is None or ((row["ask"] is None) != row["withdrawal"])):
            raise ValueError("Participation and numeric ask disagree")
    expected = len(plan["states"]) * len(plan["seeds"]) * 10
    if len(rows) != expected or expected != plan["decisions"]:
        raise ValueError("Analysis requires the complete planned factorial")
    return rows


def summarize(root, plan, out):
    rows = identify_rows(root, plan)
    base.analyze(root, root / "plan.json" if (root / "plan.json").exists() else PLAN_V1, out)
    accepted = [r for r in rows if r["accepted"]]
    by_key = {(r["state_index"], r["sampling_seed"], r["visibility"], r["message_mode"]): r for r in accepted}
    factorial, per_state, visibility, interaction = [], [], [], []
    for v in probe.VISIBILITIES:
        for m in probe.MESSAGE_MODES:
            group = [r for r in accepted if (r["visibility"], r["message_mode"]) == (v, m)]
            asks = [r["ask"] for r in group if r["ask"] is not None]
            factorial.append(dict(visibility=v, message_mode=m, accepted=len(group),
                                  withdrawals=sum(r["withdrawal"] for r in group),
                                  withdrawal_rate=average([int(r["withdrawal"]) for r in group]),
                                  numeric_n=len(asks), numeric_mean=average(asks),
                                  numeric_min=min(asks) if asks else None, numeric_max=max(asks) if asks else None))
    for i, state in enumerate(plan["states"]):
        identity = dict(state_index=i, market_seed=state["seed"], round=state["round"],
                        sender=state["sender"], recipient=state["recipient"],
                        message_id=f"{state['seed']}-h{state['sent_round']}-{state['sender']}")
        for v in probe.VISIBILITIES:
            for m in probe.MESSAGE_MODES:
                group = [r for r in accepted if (r["state_index"], r["visibility"], r["message_mode"]) == (i, v, m)]
                asks = [r["ask"] for r in group if r["ask"] is not None]
                per_state.append({**identity, "visibility": v, "message_mode": m, "n": len(group),
                                  "withdrawals": sum(r["withdrawal"] for r in group),
                                  "numeric_n": len(asks), "numeric_mean": average(asks),
                                  "asks_by_sampling_seed": json.dumps({r["sampling_seed"]: r["ask"] for r in group})})
        for seed in plan["seeds"]:
            for mode in probe.MESSAGE_MODES:
                h, r = (by_key.get((i, seed, v, mode)) for v in probe.VISIBILITIES)
                visibility.append({**identity, "sampling_seed": seed, "message_mode": mode,
                    "restored_minus_hidden_withdrawal": int(r["withdrawal"]) - int(h["withdrawal"]) if r and h else None,
                    "restored_minus_hidden_ask_both_numeric": r["ask"] - h["ask"] if r and h and r["ask"] is not None and h["ask"] is not None else None})
    interactions = base.read_csv(out / "visibility_interaction_contrasts.csv")
    for mode in probe.MESSAGE_MODES[1:]:
        group = [r for r in interactions if r["message_mode_vs_original"] == mode]
        asks = [float(r["restored_minus_hidden_ask_effect"]) for r in group if r["restored_minus_hidden_ask_effect"] != ""]
        wd = [float(r["restored_minus_hidden_withdrawal_effect"]) for r in group if r["restored_minus_hidden_withdrawal_effect"] != ""]
        interaction.append(dict(message_mode=mode, complete_numeric_quartets=len(asks),
                                mean_ask_interaction=average(asks), complete_participation_quartets=len(wd),
                                mean_withdrawal_interaction=average(wd)))
    for name, data in (("factorial_cells", factorial), ("every_state_by_condition", per_state),
                       ("public_visibility_pairs", visibility), ("interaction_summary", interaction)):
        base.write_csv(out / (name + ".csv"), data)
    return {"rows": rows, "factorial": factorial, "per_state": per_state, "interaction": interaction,
            "counts": {"states": len(plan["states"]), "markets": len({s["seed"] for s in plan["states"]}),
                       "messages": len({(s["seed"], s["sent_round"], s["sender"]) for s in plan["states"]}),
                       "valid_decisions": len(accepted)}}


PLAN_V1 = probe.ROOT / "output/message_channel_probe_v1_approved4/plan.json"


def run(out):
    v2root = probe.ROOT / "output/message_channel_modal_v2_recovered"
    v1root = probe.ROOT / "output/modal_message_probe_20261024_001"
    v1plan, v2plan = io.read(PLAN_V1), io.read(v2root / "plan.json")
    v1meta = io.read(v1root / "summary.json")
    if probe.sha_file(PLAN_V1) != io.read(v1root / "execution.json")["plan_sha256"]:
        raise ValueError("Earlier run is not bound to this plan")
    out.mkdir(parents=True, exist_ok=False)
    v2 = summarize(v2root, v2plan, out / "v2")
    v1 = summarize(v1root, v1plan, out / "earlier_probe")
    map1 = {state_id(s): i for i, s in enumerate(v1plan["states"])}
    earlier = {(r["state_index"], r["sampling_seed"], r["visibility"], r["message_mode"]): r for r in v1["rows"]}
    comparisons = []
    for row in v2["rows"]:
        state = v2plan["states"][row["state_index"]]
        previous_index = map1.get(state_id(state))
        if previous_index is None:
            continue
        condition = row["visibility"] + "_" + row["message_mode"]
        if v1plan["states"][previous_index]["conditions"][condition]["prompt"] != state["conditions"][condition]["prompt"]:
            raise ValueError("Cross-run source identity has different prompts")
        prior = earlier.get((previous_index, row["sampling_seed"], row["visibility"], row["message_mode"]))
        if not prior or not prior["accepted"] or not row["accepted"]:
            continue
        comparisons.append(dict(state_index=row["state_index"], sampling_seed=row["sampling_seed"],
            visibility=row["visibility"], message_mode=row["message_mode"],
            earlier_withdrawal=prior["withdrawal"], v2_withdrawal=row["withdrawal"],
            withdrawal_agrees=prior["withdrawal"] == row["withdrawal"],
            earlier_ask=prior["ask"], v2_ask=row["ask"],
            ask_delta_v2_minus_earlier_when_both_numeric=row["ask"] - prior["ask"] if row["ask"] is not None and prior["ask"] is not None else None))
    base.write_csv(out / "cross_run_matched_responses.csv", comparisons)
    overview = dict(v2_counts=v2["counts"], earlier_counts=v1["counts"],
                    earlier_provider=v1meta["provider"], v2_provider=v2plan["provider"],
                    matched_responses=len(comparisons),
                    withdrawal_disagreements=sum(not r["withdrawal_agrees"] for r in comparisons),
                    matched_numeric_pairs=sum(r["ask_delta_v2_minus_earlier_when_both_numeric"] is not None for r in comparisons),
                    exact_numeric_agreements=sum(r["ask_delta_v2_minus_earlier_when_both_numeric"] == 0 for r in comparisons),
                    maximum_absolute_numeric_difference=max((abs(r["ask_delta_v2_minus_earlier_when_both_numeric"]) for r in comparisons
                                                             if r["ask_delta_v2_minus_earlier_when_both_numeric"] is not None), default=None),
                    source_run_checksums={str(root.relative_to(probe.ROOT)): probe.sha_file(root / "checksums.json") for root in (v1root, v2root)},
                    interpretation="Two separate Modal-hosted runs over shared source states. No verified live Lambda message-factorial result was found; Lambda-labelled mock results are not provider evidence. No pooling or independence claim.")
    io.save(out / "comparison_summary.json", overview)
    lines = ["# Completed Modal v2 evidence and earlier-run comparison", "",
             f"V2: {v2['counts']}. Earlier: {v1['counts']}. Both recorded providers are Modal-hosted.", "",
             "The earlier directory name/export instructions mention Lambda, but its live summary and runtime record Modal. No live Lambda factorial was located; fake endpoint fixtures labelled Lambda are excluded.", "",
             "All contrasts pair the same saved state and sampling seed. Numeric ask comparisons exclude withdrawals and show their own denominators. Participation is a separate outcome. Interaction = (restored treatment − restored original) − (hidden treatment − hidden original). These small correlated samples support descriptive patterns, not significance or market-level conclusions.", "",
             "## Factorial outcomes", "", "|Visibility|Message|Withdrawals / n|Numeric mean|Numeric n|", "|---|---|---:|---:|---:|"]
    for row in v2["factorial"]:
        value = f"{row['numeric_mean']:.3f}" if row["numeric_mean"] is not None else "—"
        lines.append(f"|{row['visibility']}|{row['message_mode']}|{row['withdrawals']}/{row['accepted']}|{value}|{row['numeric_n']}|")
    lines += ["", "## Paired interaction", "", "|Treatment vs original|Mean ask interaction|Numeric quartets|Mean withdrawal interaction|", "|---|---:|---:|---:|"]
    for row in v2["interaction"]:
        value = f"{row['mean_ask_interaction']:.3f}" if row["mean_ask_interaction"] is not None else "—"
        lines.append(f"|{row['message_mode']}|{value}|{row['complete_numeric_quartets']}|{row['mean_withdrawal_interaction']:.3f}|")
    lines += ["", "## Every source state", "",
              "Each table entry lists numeric asks by sampling seed; null means withdrawal. The two draws are repeated responses, not independent messages."]
    for i, state in enumerate(v2plan["states"]):
        lines += ["", f"### State {i}: market {state['seed']}, hour {state['round']}, {state['sender']} → {state['recipient']}", "",
                  f"Source message (hour {state['sent_round']}): {state['message']}", "", "|Visibility|Message|Asks by sampling seed|", "|---|---|---|"]
        for row in v2["per_state"]:
            if row["state_index"] == i:
                lines.append(f"|{row['visibility']}|{row['message_mode']}|{row['asks_by_sampling_seed']}|")
    lines += ["", "## Replication limits", "",
              f"Matched responses across runs: {len(comparisons)}. Withdrawal disagreements: {overview['withdrawal_disagreements']}. Of {overview['matched_numeric_pairs']} matched numeric pairs, {overview['exact_numeric_agreements']} agree exactly; largest absolute difference is ${overview['maximum_absolute_numeric_difference']:.2f}. Exact matching prompts and seeds do not guarantee identical generation across sessions. See separate earlier_probe/ and v2/ contrast tables; no outputs have been pooled.", "",
              "The observed aggregate numeric shifts are small; participation changes occur in selected state/seed pairs. Apparent information-resistant or information-sensitive regimes remain hypotheses: two draws and four shared messages cannot establish stable behavioral classes. More independent source environments take priority over extra sampling seeds."]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    io.save(out / "checksums.json", {f.relative_to(out).as_posix(): probe.sha_file(f) for f in out.rglob("*") if f.is_file()})
    print(json.dumps(overview, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    run(parser.parse_args().out.resolve())
