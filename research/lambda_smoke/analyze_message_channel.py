"""Analyze state-paired Lambda message-channel probe decisions; no model calls."""
import argparse
import csv
import difflib
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def read_csv(path):
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def verify_checksums(root):
    manifest_path = root / "checksums.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors = []
    for relative, expected in manifest.items():
        path = root / relative
        if not path.is_file():
            errors.append(f"missing: {relative}")
        else:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                errors.append(f"mismatch: {relative}")
    if errors:
        raise ValueError("Evidence checksum failure: " + "; ".join(errors))


def as_bool(value):
    if value in (True, "True", "true", "1"):
        return True
    if value in (False, "False", "false", "0"):
        return False
    return None


def as_float(value):
    if value in (None, "", "None"):
        return None
    return float(value)


def write_csv(path, rows):
    if not rows:
        Path(path).write_text("", encoding="utf-8")
        return
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def analyze(results: Path, plan_path: Path, out: Path):
    verify_checksums(results)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    rows = read_csv(results / "decisions.csv")
    by_key = {}
    for row in rows:
        row["state_index"] = int(row["state_index"])
        row["sampling_seed"] = int(row["sampling_seed"])
        row["ask"] = as_float(row.get("ask"))
        row["withdrawal"] = as_bool(row.get("withdrawal"))
        row["accepted"] = as_bool(row.get("accepted"))
        by_key[(row["state_index"], row["sampling_seed"], row["visibility"], row["message_mode"])] = row

    contrasts = []
    did_rows = []
    aggregate = defaultdict(list)
    modes = plan["message_conditions"]
    for state_index, state in enumerate(plan["states"]):
        for seed in plan["seeds"]:
            for mode in modes:
                if mode == "original":
                    continue
                h = by_key.get((state_index, int(seed), "hidden", mode))
                ho = by_key.get((state_index, int(seed), "hidden", "original"))
                r = by_key.get((state_index, int(seed), "restored", mode))
                ro = by_key.get((state_index, int(seed), "restored", "original"))
                for visibility, treatment, baseline in (("hidden", h, ho), ("restored", r, ro)):
                    ta = treatment.get("ask") if treatment and treatment.get("accepted") else None
                    ba = baseline.get("ask") if baseline and baseline.get("accepted") else None
                    tw = treatment.get("withdrawal") if treatment and treatment.get("accepted") else None
                    bw = baseline.get("withdrawal") if baseline and baseline.get("accepted") else None
                    delta = ta - ba if ta is not None and ba is not None else None
                    withdrawal_change = (tw, bw) if tw is not None and bw is not None else None
                    record = {
                        "state_index": state_index, "market_seed": state["seed"],
                        "round": state["round"], "sender": state["sender"], "recipient": state["recipient"],
                        "sampling_seed": seed, "visibility": visibility, "message_mode": mode,
                        "treatment_accepted": treatment.get("accepted") if treatment else None,
                        "baseline_accepted": baseline.get("accepted") if baseline else None,
                        "treatment_ask": ta, "original_ask": ba,
                        "ask_delta_treatment_minus_original": delta,
                        "treatment_withdrawal": tw, "original_withdrawal": bw,
                        "withdrawal_changed": (tw != bw) if withdrawal_change else None,
                        "pair_complete": bool(treatment and baseline and treatment.get("accepted") and baseline.get("accepted")),
                    }
                    contrasts.append(record)
                    aggregate[(visibility, mode)].append(record)
                ask_did = None
                h_effect = (h.get("ask") - ho.get("ask")) if h and ho and h.get("accepted") and ho.get("accepted") and h.get("ask") is not None and ho.get("ask") is not None else None
                r_effect = (r.get("ask") - ro.get("ask")) if r and ro and r.get("accepted") and ro.get("accepted") and r.get("ask") is not None and ro.get("ask") is not None else None
                if h_effect is not None and r_effect is not None:
                    ask_did = r_effect - h_effect
                h_withdraw = (int(h.get("withdrawal")) - int(ho.get("withdrawal"))) if h and ho and h.get("accepted") and ho.get("accepted") else None
                r_withdraw = (int(r.get("withdrawal")) - int(ro.get("withdrawal"))) if r and ro and r.get("accepted") and ro.get("accepted") else None
                did_rows.append({
                    "state_index": state_index, "market_seed": state["seed"], "round": state["round"],
                    "sender": state["sender"], "recipient": state["recipient"], "sampling_seed": seed,
                    "message_mode_vs_original": mode, "hidden_ask_effect": h_effect,
                    "restored_ask_effect": r_effect,
                    "restored_minus_hidden_ask_effect": ask_did,
                    "hidden_withdrawal_effect_treatment_minus_original": h_withdraw,
                    "restored_withdrawal_effect_treatment_minus_original": r_withdraw,
                    "restored_minus_hidden_withdrawal_effect": (r_withdraw - h_withdraw) if h_withdraw is not None and r_withdraw is not None else None,
                })

    summary_rows = []
    for (visibility, mode), group in sorted(aggregate.items()):
        deltas = [r["ask_delta_treatment_minus_original"] for r in group if r["ask_delta_treatment_minus_original"] is not None]
        complete = [r for r in group if r["pair_complete"]]
        wd_changes = [r["withdrawal_changed"] for r in complete if r["withdrawal_changed"] is not None]
        to_withdrawal = sum(r["treatment_withdrawal"] is True and r["original_withdrawal"] is False for r in complete)
        to_ask = sum(r["treatment_withdrawal"] is False and r["original_withdrawal"] is True for r in complete)
        summary_rows.append({
            "visibility": visibility, "message_mode_vs_original": mode,
            "paired_state_seed_rows": len(group), "complete_pairs": len(complete),
            "numeric_ask_pairs": len(deltas),
            "mean_ask_delta_when_both_numeric": (sum(deltas) / len(deltas)) if deltas else None,
            "withdrawal_changed_pairs": sum(wd_changes), "withdrawal_unchanged_pairs": len(wd_changes) - sum(wd_changes),
            "changed_to_withdrawal": to_withdrawal, "changed_to_numeric_ask": to_ask,
            "note": "Descriptive only; repeated decisions share saved states and messages.",
        })

    out.mkdir(parents=True, exist_ok=False)
    write_csv(out / "state_paired_contrasts.csv", contrasts)
    write_csv(out / "visibility_interaction_contrasts.csv", did_rows)
    write_csv(out / "descriptive_summary.csv", summary_rows)
    _write_prompt_diffs(out / "representative_prompt_diffs.md", plan)
    (out / "ANALYSIS.md").write_text(
        "# Message × public-quote decision probe analysis\n\n"
        f"States in frozen plan: {len(plan['states'])}. Planned decisions: {plan['decisions']}. "
        f"Observed decision rows: {len(rows)}.\n\n"
        "Contrasts are paired within saved state and sampling seed. Numeric ask deltas exclude withdrawals; "
        "withdrawals are tabulated separately. Missing, rejected, or transport-failed pairs remain missing and "
        "are never imputed as zero. The visibility interaction is a descriptive difference in paired message "
        "effects between restored and hidden quote conditions. Repeated decisions share the same small set of "
        "messages and market states, so these rows are not independent market replications. No p-values, "
        "equivalence claims, monotonic-response assumptions, or market-level mediation claims are made.\n\n"
        "See `state_paired_contrasts.csv`, `visibility_interaction_contrasts.csv`, and `representative_prompt_diffs.md`.\n",
        encoding="utf-8")
    return out


def _write_prompt_diffs(path, plan):
    state = plan["states"][0]
    conditions = state["conditions"]
    sections = ["# Representative prompt diffs\n\n"
                "These show the first frozen state only; the complete prompts and hashes are in the plan and request files.\n"]
    baseline = conditions["hidden_original"]["prompt"].splitlines(keepends=True)
    for key in ("hidden_redacted", "hidden_up10", "hidden_down10", "hidden_absent", "restored_original", "restored_up10"):
        candidate = conditions[key]["prompt"].splitlines(keepends=True)
        diff = "".join(difflib.unified_diff(baseline, candidate,
                    fromfile="hidden_original", tofile=key, n=2))
        sections.append(f"## {key}\n\n```diff\n{diff}```\n")
    Path(path).write_text("\n".join(sections), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    analyze(args.results.resolve(), args.plan.resolve(), args.out.resolve())
    print(f"ANALYSIS {args.out.resolve()}")


if __name__ == "__main__":
    main()
