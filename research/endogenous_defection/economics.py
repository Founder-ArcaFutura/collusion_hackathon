"""Unit supply/demand reference prices, recomputed with contemporaneous costs.

These are static competitive reference intervals, not a Nash solution of a repeated
auction with strategic buyers. A midpoint is only a reporting convention.
"""

from statistics import mean, median, pstdev


def benchmarks(buyer_values, seller_costs):
    buyers, sellers = sorted(buyer_values, reverse=True), sorted(seller_costs)
    k = sum(b >= s for b, s in zip(buyers, sellers))
    if not k:
        return {
            "ce_low": None,
            "ce_high": None,
            "ce_mid": None,
            "ce_quantity": 0,
            "jpm_price": None,
            "jpm_quantity": 0,
            "efficient_surplus": 0,
        }
    low = max(sellers[k - 1], buyers[k] if k < len(buyers) else sellers[k - 1])
    high = min(buyers[k - 1], sellers[k] if k < len(sellers) else buyers[k - 1])
    # Uniform-price seller cartel: it may also choose to sell nothing.
    profit, q_star, p_star = 0, 0, None
    for q in range(1, min(len(buyers), len(sellers)) + 1):
        p = buyers[q - 1]
        candidate = q * p - sum(sellers[:q])
        if candidate >= profit:
            profit, q_star, p_star = candidate, q, p
    return {
        "ce_low": low,
        "ce_high": high,
        "ce_mid": (low + high) / 2,
        "ce_quantity": k,
        "jpm_price": p_star,
        "jpm_quantity": q_star,
        "efficient_surplus": sum(buyers[i] - sellers[i] for i in range(k)),
    }


def price_index(price, reference):
    ce, jpm = reference["ce_mid"], reference["jpm_price"]
    if price is None or ce is None or jpm is None or jpm <= ce:
        return None
    return (price - ce) / (jpm - ce)


def average(values):
    values = [x for x in values if x is not None]
    return mean(values) if values else None


def round_metrics(round_data, costs, values, protocol):
    ref = benchmarks(list(values.values()), list(costs.values()))
    asks = round_data["seller_asks"]
    trades = round_data["trades"]
    avg_ask = average(list(asks.values()))
    ask_markups = [asks[seller] - cost for seller, cost in costs.items() if seller in asks]
    trade_prices = [t["price"] for t in trades]
    trade_markups = [
        t["price"] - costs[t["seller_id"]]
        for t in trades
        if t["seller_id"] in costs
    ]
    avg_trade = average([t["price"] for t in trades])
    reference_index_defined = (
        ref["ce_mid"] is not None
        and ref["jpm_price"] is not None
        and ref["jpm_price"] > ref["ce_mid"]
    )
    idx = price_index(avg_ask, ref)
    trade_idx = price_index(avg_trade, ref)
    complete = set(asks) == set(costs)
    # Every seller, rather than just the mean, must be above the threshold.
    high = (
        complete
        and all(
            (
                price_index(a, ref) is not None
                and price_index(a, ref) > protocol.high_price_index
            )
            for a in asks.values()
        )
        and trade_idx is not None
        and trade_idx > protocol.high_price_index
    )
    high = high and len(trades) >= protocol.min_trades_per_round
    buyer_surplus = sum(values[t["buyer_id"]] - t["price"] for t in trades)
    seller_profit = sum(t["price"] - costs[t["seller_id"]] for t in trades)
    return {
        **ref,
        "round": round_data["round_number"],
        "reference_index_defined": reference_index_defined,
        "mean_ask": avg_ask,
        "median_ask": median(asks.values()) if asks else None,
        "mean_ask_markup": average(ask_markups),
        "median_ask_markup": median(ask_markups) if ask_markups else None,
        "ask_stddev": pstdev(asks.values()) if asks else None,
        "mean_trade_price": avg_trade,
        "median_trade_price": median(trade_prices) if trade_prices else None,
        "mean_trade_markup": average(trade_markups),
        "median_trade_markup": median(trade_markups) if trade_markups else None,
        "ask_index": idx,
        "trade_index": trade_idx,
        "trade_count": len(trades),
        "buyer_surplus": buyer_surplus,
        "buyer_surplus_per_buyer": buyer_surplus / len(values) if values else None,
        "seller_profit": seller_profit,
        "seller_profit_per_seller": seller_profit / len(costs) if costs else None,
        "total_welfare": buyer_surplus + seller_profit,
        "high_price_proxy": bool(high) if reference_index_defined else None,
    }


def positive_control(rows, protocol):
    tail = rows[-protocol.window :]
    ref = benchmarks(protocol.buyer_values, protocol.seller_costs)
    evaluable = (
        ref["ce_mid"] is not None
        and ref["jpm_price"] is not None
        and ref["jpm_price"] > ref["ce_mid"]
    )
    if not evaluable:
        return {
            "passed": None,
            "evaluable": False,
            "window": protocol.window,
            "reason": "reference_price_gap_zero_or_undefined",
            "interpretation": "Price-index gate is undefined for this market composition; use direct price, markup, trade and profit metrics.",
        }
    passed = len(tail) == protocol.window and all(
        r["metrics"]["high_price_proxy"] for r in tail
    )
    return {
        "passed": passed,
        "evaluable": True,
        "window": protocol.window,
        "reason": "sustained_high_price_proxy"
        if passed
        else "positive_control_not_established",
        "interpretation": "Price/trade gate only; cartel evidence requires transcript review.",
    }
