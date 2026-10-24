"""Adapter around the starter's real agents, prompts, memory and trade clearing.

Only research-specific round scheduling, response validation and interventions live
here. The upstream Market/LMSeller/LMBuyer files are deliberately unchanged.
"""

import copy
import json
import math
import random
import re
from pathlib import Path

from src.continuous_double_auction.cda_types import ExperimentParams, MarketRound, Trade
from src.continuous_double_auction.market.agents import LMBuyer, LMSeller
from src.continuous_double_auction.market.market import Market
from src.resources.model_wrappers import ModelWrapper

from .economics import round_metrics
from .io import append, utc_now
from .response_schema import (
    BOUNDED_SCRATCHPAD_LIMITS,
    BOUNDED_SCRATCHPAD_SCHEMA_VERSION,
    BOUNDED_TEXT_LIMITS,
    BOUNDED_TEXT_SCHEMA_VERSION,
    SCHEMA_VERSION,
    schema_for,
)

INFERENCE_REQUEST_TIMEOUT_SECONDS = 90


class ResearchMarket(Market):
    def observation_for(self, agent, common):
        """Default full-information view; study subclasses may change observations only."""
        return copy.deepcopy(common)

    def run_round(self):
        # Freeze all public inputs before collecting any actions. Model latency cannot
        # decide who sees a rival's current-round order. Apply in stable agent-ID order.
        prev = self.rounds[-1] if self.rounds else None
        common = dict(
            round_num=self.current_round.round_number,
            bid_queue=copy.deepcopy(self.buyer_bid_queue),
            ask_queue=copy.deepcopy(self.seller_ask_queue),
            past_bids_and_asks=self.formatted_past_bids_and_asks,
            past_trades=self.formatted_past_trades,
        )
        decisions = []
        for agent in sorted([*self.sellers, *self.buyers], key=lambda a: a.id):
            seller = agent.id.startswith("Seller ")
            agent.client.round_num = self.current_round.round_number
            agent.client.cost = agent.valuation
            agent.client.peer_asks = [
                p
                for sid, p in (prev.seller_asks.items() if prev else [])
                if sid != agent.id
            ]
            agent.client.previous_ask = prev.seller_asks.get(agent.id) if prev else None
            response = agent.generate_bid_response(
                **self.observation_for(agent, common),
                # Communication-off runs have no inbound channel either. This is
                # enforced even if a malformed/restored prior round contains messages.
                seller_messages=(
                    copy.deepcopy(prev.seller_messages)
                    if prev and agent.expt_params.seller_comms_enabled
                    else {}
                ),
                buyer_messages=copy.deepcopy(prev.buyer_messages) if prev else {},
                is_gag_order_active=False,
                agent_successful_trades=self.get_agent_successful_trades(agent.id),
            )
            decisions.append((agent, seller, response))
        for agent, seller, response in decisions:
            action = response["ask" if seller else "bid"]
            if action == "null":
                (self.remove_seller_ask if seller else self.remove_buyer_bid)(agent)
            else:
                # Match the checkpoint schema's float prices before storing them;
                # JSON 98 and 98.0 must not change history text after restoration.
                (self.add_seller_ask if seller else self.add_buyer_bid)(
                    agent, float(action)
                )
            message = response.get(
                "message_to_sellers" if seller else "message_to_buyers"
            )
            if seller and agent.expt_params.seller_comms_enabled and message:
                self.current_round.seller_messages[agent.id] = message[
                    : agent.expt_params.max_message_length
                ]
        self.resolve_trades_if_any()
        self.start_new_round()


class Session:
    def __init__(self, protocol, model, backend, max_calls, event_path):
        self.protocol, self.model, self.backend = protocol, model, backend
        self.max_calls, self.calls = max_calls, 0
        self.event_path = Path(event_path)
        self.client = None
        self.provider = "synthetic"
        self.route = "synthetic"
        if backend == "live":
            from urllib.parse import urlsplit
            from poseidon_compute import base_url, make_client, resolve_model

            # No silent retired-version upgrades or environment model substitutions.
            resolved = resolve_model(model, translate_openrouter=False)
            if resolved != model:
                raise ValueError(
                    "Resolved model differs from --model; choose an exact current identifier"
                )
            self.client = make_client(
                max_retries=0, timeout=INFERENCE_REQUEST_TIMEOUT_SECONDS
            )
            url = urlsplit(base_url())
            self.provider = (
                f"{url.scheme}://{url.hostname}{url.path}"  # no bearer/query/userinfo
            )
            # Modal's ephemeral host can change between control and continuation.
            self.route = (
                "modal-hosted"
                if (url.hostname or "").endswith(".modal.run")
                else self.provider
            )

    def generate(self, adapter, messages):
        for attempt in range(1, self.protocol.max_action_attempts + 1):
            try:
                result = self._generate_once(adapter, messages, attempt)
                if self.protocol.max_action_attempts > 1:
                    append(self.event_path, {
                        "event": "action_accepted", "call": self.calls,
                        "generation_attempt": attempt, "seed": adapter.seed,
                        "round": adapter.round_num, "agent": adapter.agent_id,
                        "condition": adapter.condition,
                    })
                return result
            except RejectedGeneration as exc:
                if (not exc.retryable or attempt >= self.protocol.max_action_attempts
                        or self.calls >= self.max_calls):
                    if self.protocol.max_action_attempts > 1:
                        raise RuntimeError("Invalid model response; bounded format recovery exhausted") from None
                    raise
                append(self.event_path, {
                    "event": "format_recovery_scheduled", "after_call": self.calls,
                    "next_attempt": attempt + 1, "seed": adapter.seed,
                    "round": adapter.round_num, "agent": adapter.agent_id,
                    "condition": adapter.condition, "error_category": exc.category,
                })
                print(f"Format recovery: {adapter.agent_id}, round {adapter.round_num}, attempt {attempt + 1}", flush=True)

    def _generate_once(self, adapter, messages, attempt):
        key = "ask" if adapter.role == "seller" else "bid"
        prompt = messages[0]["content"]
        if adapter.notice:
            prompt += "\n\n# Private operating-cost notice\n" + adapter.notice
        info = {
            "created_at": utc_now(),
            "seed": adapter.seed,
            "condition": adapter.condition,
            "agent": adapter.agent_id,
            "round": adapter.round_num,
            "backend": self.backend,
            "scripted": adapter.scripted,
            "prompt": prompt,
            "generation_attempt": attempt,
        }
        if adapter.scripted or self.backend == "synthetic":
            if adapter.scripted:
                peer = (
                    min(adapter.peer_asks) if adapter.peer_asks else adapter.cost + 0.01
                )
                price = max(
                    adapter.cost + 0.01, peer - self.protocol.undercut_cents / 100
                )
            elif adapter.role == "buyer":
                price = 99
            else:
                # Deliberately programmed fixture, never an LLM finding. After a shock
                # the fixture undercuts once, then resumes high pricing (reformation).
                price = (
                    88
                    if adapter.cost < 80
                    and adapter.round_num == self.protocol.warmup_rounds + 1
                    else 98
                )
            response = {
                key: round(price, 2),
                "new_memory": f"Synthetic/scripted action {price:.2f}.",
                "scratch_pad_update": "Fixture state",
            }
            if adapter.role == "seller" and self.protocol.seller_comms_enabled:
                response["message_to_sellers"] = None
            append(
                self.event_path,
                {
                    **info,
                    "event": "response",
                    "response": response,
                    "model": "scripted"
                    if adapter.scripted
                    else "SYNTHETIC-NO-INFERENCE",
                },
            )
            return json.dumps(response)
        if self.calls >= self.max_calls:
            raise RuntimeError("Inference request budget exhausted")
        self.calls += 1
        request_seed = (
            adapter.seed * 1000003 + adapter.round_num * 1009 + adapter.agent_index
            + (attempt - 1) * 104729
        ) % (2**31)
        extra = {"seed": request_seed} if self.protocol.provider_seed or attempt > 1 else {}
        schema_version = self.protocol.response_schema_version
        guided = schema_version in (
            SCHEMA_VERSION,
            BOUNDED_TEXT_SCHEMA_VERSION,
            BOUNDED_SCRATCHPAD_SCHEMA_VERSION,
        )
        if schema_version not in (
            "unconstrained-v1",
            SCHEMA_VERSION,
            BOUNDED_TEXT_SCHEMA_VERSION,
            BOUNDED_SCRATCHPAD_SCHEMA_VERSION,
        ):
            raise RuntimeError(f"Unsupported response schema version: {schema_version}")
        request_options = {"extra_body": {"guided_json": schema_for(adapter.role, self.protocol)}} if guided else {}
        append(
            self.event_path,
            {
                **info,
                "event": "request_started",
                "call": self.calls,
                "model": self.model,
                "request_seed": extra.get("seed"),
                "schema_version": schema_version,
            },
        )
        try:
            result = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.protocol.temperature,
                max_tokens=self.protocol.max_tokens,
                **request_options,
                **extra,
            )
        except Exception as exc:
            # Provider exceptions can contain headers/URLs. Preserve safe error metadata.
            append(
                self.event_path,
                {
                    **info,
                    "event": "request_failed",
                    "call": self.calls,
                    "error_type": type(exc).__name__,
                    "status_code": getattr(exc, "status_code", None),
                    "schema_version": schema_version,
                    "request_timeout_seconds": INFERENCE_REQUEST_TIMEOUT_SECONDS,
                },
            )
            raise RuntimeError(
                f"Inference failed ({type(exc).__name__}); see recorded safe metadata"
            ) from None
        raw = result.choices[0].message.content or ""
        append(
            self.event_path,
            {
                **info,
                "event": "response",
                "call": self.calls,
                "raw": raw,
                    "schema_version": schema_version,
                "requested_model": self.model,
                "returned_model": result.model,
                "finish_reason": result.choices[0].finish_reason,
                "usage": result.usage.model_dump() if result.usage else None,
                "system_fingerprint": getattr(result, "system_fingerprint", None),
            },
        )
        finish_reason = result.choices[0].finish_reason
        if finish_reason != "stop":
            error = ResponseValidationError(
                "incomplete_generation",
                f"Generation ended with finish_reason={finish_reason!r}",
            )
            self._record_validation_failure(info, raw, finish_reason, schema_version, error)
            raise RejectedGeneration(error.category, finish_reason == "length")
        try:
            response = validate_response(
                raw,
                key,
                allow_numeric_strings=self.protocol.numeric_string_actions,
                role=adapter.role,
                comms_enabled=(
                    self.protocol.seller_comms_enabled
                    if adapter.role == "seller"
                    else self.protocol.buyer_comms_enabled
                ),
                max_text_lengths=(
                    BOUNDED_TEXT_LIMITS
                    if schema_version == BOUNDED_TEXT_SCHEMA_VERSION
                    else BOUNDED_SCRATCHPAD_LIMITS
                    if schema_version == BOUNDED_SCRATCHPAD_SCHEMA_VERSION
                    else None
                ),
            )
        except ResponseValidationError as error:
            self._record_validation_failure(info, raw, finish_reason, schema_version, error)
            raise RejectedGeneration(error.category, error.category == "malformed_json") from None
        original_action = json.loads(raw)[key]
        if isinstance(original_action, str) and original_action != "null":
            append(
                self.event_path,
                {
                    **info,
                    "event": "action_representation_normalized",
                    "call": self.calls,
                    "field": key,
                    "original": original_action,
                    "normalized": response[key],
                    "rule": "exact nonnegative decimal string with at most two decimal places",
                },
            )
        # The upstream agents parse JSON again. Convert withdrawals explicitly to its
        # supported string representation (JSON null otherwise leaves a stale order).
        if response[key] is None:
            response[key] = "null"
        return json.dumps(response)

    def _record_validation_failure(self, info, raw, finish_reason, schema_version, error):
        append(
            self.event_path,
            {
                **info,
                "event": "response_validation_failed",
                "call": self.calls,
                "raw": raw,
                "finish_reason": finish_reason,
                "validation_error": str(error),
                "error_category": error.category,
                "schema_version": schema_version,
            },
        )


class RejectedGeneration(RuntimeError):
    def __init__(self, category, retryable):
        super().__init__("Invalid model response; raw output retained; no retry or invented action")
        self.category, self.retryable = category, retryable


class ResponseValidationError(ValueError):
    def __init__(self, category, message):
        super().__init__(message)
        self.category = category


def validate_response(
    raw,
    key,
    allow_numeric_strings=False,
    role=None,
    comms_enabled=False,
    max_text_lengths=None,
):
    try:
        response = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ResponseValidationError("malformed_json", f"Malformed JSON: {exc}") from exc
    if not isinstance(response, dict):
        raise ResponseValidationError("schema_violation", "Expected a JSON object")
    if role is None:
        role = "seller" if key == "ask" else "buyer" if key == "bid" else None
    if role not in ("seller", "buyer") or key != ("ask" if role == "seller" else "bid"):
        raise ResponseValidationError("schema_violation", "Action key does not match agent role")
    required = {
        "reflection",
        "plan_for_this_hour",
        key,
        "new_memory",
        "scratch_pad_update",
    }
    if comms_enabled:
        required.update(
            {"plan_for_message", "message_to_sellers" if role == "seller" else "message_to_buyers"}
        )
    if not required.issubset(response):
        missing = sorted(required - set(response))
        category = "missing_required_field" if key in response else "missing_action"
        raise ResponseValidationError(category, f"Missing required fields: {', '.join(missing)}")
    allowed = required
    if set(response) - allowed:
        raise ResponseValidationError(
            "schema_violation", f"Unexpected fields: {', '.join(sorted(set(response) - allowed))}"
        )
    for field in required - {key, "message_to_sellers", "message_to_buyers"}:
        if not isinstance(response[field], str):
            raise ResponseValidationError("schema_violation", f"Invalid {field}: expected string")
    for field in required - {key, "message_to_sellers", "message_to_buyers"}:
        if max_text_lengths and field in max_text_lengths:
            if len(response[field]) > max_text_lengths[field]:
                raise ResponseValidationError(
                    "schema_violation",
                    f"Invalid {field}: exceeds {max_text_lengths[field]} characters",
                )
    if len(response["scratch_pad_update"].split()) > 250:
        raise ResponseValidationError(
            "schema_violation", "Invalid scratch_pad_update: maximum is 250 words"
        )
    for field in ("message_to_sellers", "message_to_buyers"):
        if field in response and response[field] is not None and not isinstance(response[field], str):
            raise ResponseValidationError("schema_violation", f"Invalid {field}: expected string or null")
        if (
            field in response
            and isinstance(response[field], str)
            and max_text_lengths
            and field in max_text_lengths
            and len(response[field]) > max_text_lengths[field]
        ):
            raise ResponseValidationError(
                "schema_violation",
                f"Invalid {field}: exceeds {max_text_lengths[field]} characters",
            )
    action = response[key]
    if allow_numeric_strings and isinstance(action, str) and action != "null":
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", action):
            raise ResponseValidationError("semantically_invalid_action", "Expected an exact nonnegative decimal price string")
        action = float(action)
        response[key] = action
    if action is not None and action != "null":
        if isinstance(action, bool) or not isinstance(action, (float, int)):
            raise ResponseValidationError("semantically_invalid_action", "Action must be a number or null")
        if (
            not math.isfinite(action)
            or action < 0
            or abs(action * 100 - round(action * 100)) > 1e-6
        ):
            raise ResponseValidationError(
                "semantically_invalid_action", "Action must be finite, nonnegative and whole cents"
            )
    return response


class AdapterClient(ModelWrapper):
    def __init__(self, session, seed, agent_id, index, role, condition):
        super().__init__(session.model or "synthetic")
        self.session, self.seed, self.agent_id = session, seed, agent_id
        self.agent_index, self.role, self.condition = index, role, condition
        self.notice, self.scripted, self.round_num = "", False, 0
        self.cost, self.peer_asks, self.previous_ask = 0, [], None

    def generate(self, messages):
        return self.session.generate(self, messages)


def make_market(protocol, session, seed, condition="warmup", state=None, market_class=None):
    params = ExperimentParams(
        seller_valuations=protocol.seller_costs,
        buyer_valuations=protocol.buyer_values,
        seller_models=[session.model or "synthetic"] * len(protocol.seller_costs),
        buyer_models=[session.model or "synthetic"] * len(protocol.buyer_values),
        rounds=protocol.announced_rounds
        or (protocol.warmup_rounds + protocol.post_rounds),
        hide_num_rounds=protocol.hide_num_rounds,
        seller_comms_enabled=protocol.seller_comms_enabled,
        buyer_comms_enabled=protocol.buyer_comms_enabled,
        seed=seed,
    )
    sellers, buyers = [], []
    identities = {}
    if protocol.identity_mode == "upstream_seeded":
        from src.continuous_double_auction.identities import (
            get_random_agent_names,
            get_random_buyer_company_names,
            get_random_seller_company_names,
        )

        rng_state = random.getstate()
        try:
            random.seed(seed)
            nb, ns = len(protocol.buyer_values), len(protocol.seller_costs)
            names = get_random_agent_names(nb + ns)
            identities["buyer"] = list(
                zip(names[:nb], get_random_buyer_company_names(nb))
            )
            identities["seller"] = list(
                zip(names[nb:], get_random_seller_company_names(ns))
            )
        finally:
            random.setstate(rng_state)
    for role, valuations, cls, collection in (
        ("seller", protocol.seller_costs, LMSeller, sellers),
        ("buyer", protocol.buyer_values, LMBuyer, buyers),
    ):
        for i, valuation in enumerate(valuations):
            name, company = (
                identities[role][i]
                if identities
                else (str(i), f"{role.title()} Company {i}")
            )
            agent_id = f"{role.title()} {name}"
            agent = cls(
                id=agent_id,
                company=company,
                valuation=valuation,
                expt_params=params.model_copy(deep=True),
                client=AdapterClient(
                    session,
                    seed,
                    agent_id,
                    i + (100 if role == "buyer" else 0),
                    role,
                    condition,
                ),
            )
            if state:
                saved = state["agents"][agent_id]
                agent.company = saved["company"]
                agent.expt_params = ExperimentParams.model_validate(
                    saved["experiment_params"]
                )
                agent.valuation = saved["valuation"]
                agent.memory_manager.memories = {
                    int(k): v for k, v in saved["memories"].items()
                }
                agent.scratch_pad = saved["scratch_pad"]
                agent.client.notice = saved["private_notice"]
                agent.client.scripted = saved["scripted_policy"]
            collection.append(agent)
    market = (market_class or ResearchMarket)(sellers=sellers, buyers=buyers)
    if state:
        market.rounds = [MarketRound.model_validate(r) for r in state["rounds"]]
        market.current_round = MarketRound.model_validate(state["current_round"])
        market.past_trades = [Trade.model_validate(t) for t in state["past_trades"]]
        market.seller_ask_queue = [tuple(x) for x in state["seller_ask_queue"]]
        market.buyer_bid_queue = [tuple(x) for x in state["buyer_bid_queue"]]
    else:
        rng = random.Random(seed)
        seller_slots = protocol.initialization_seller_slots or len(sellers)
        initial_seller_prices = [
            round(rng.uniform(*protocol.initial_seller_ask_range), 2)
            for _ in range(seller_slots)
        ]
        market.set_initial_orders(
            [
                (price, seller.id)
                for seller, price in zip(sellers, initial_seller_prices)
            ],
            [
                (round(rng.uniform(*protocol.initial_buyer_bid_range), 2), b.id)
                for b in buyers
            ],
        )
        # Initial orders are public context, not decisions made by the agents in round 1.
        market.current_round = MarketRound(round_number=1)
    return market


def snapshot(market):
    return {
        "agents": {
            a.id: {
                "company": a.company,
                "valuation": a.valuation,
                "memories": dict(a.memory_manager.memories),
                "scratch_pad": a.scratch_pad,
                "experiment_params": a.expt_params.model_dump(),
                "private_notice": a.client.notice,
                "scripted_policy": a.client.scripted,
            }
            for a in [*market.sellers, *market.buyers]
        },
        "rounds": [r.model_dump() for r in market.rounds],
        "current_round": market.current_round.model_dump(),
        "past_trades": [t.model_dump() for t in market.past_trades],
        "seller_ask_queue": copy.deepcopy(market.seller_ask_queue),
        "buyer_bid_queue": copy.deepcopy(market.buyer_bid_queue),
    }


def run_rounds(market, count, protocol, path, condition, target):
    rows = []
    for _ in range(count):
        market.run_round()
        data = market.rounds[-1].model_dump()
        costs = {a.id: a.valuation for a in market.sellers}
        values = {a.id: a.valuation for a in market.buyers}
        metrics = round_metrics(data, costs, values, protocol)
        target_trades = [t for t in data["trades"] if t["seller_id"] == target]
        metrics.update(
            target_profit=sum(t["price"] - costs[target] for t in target_trades),
            target_trade_count=len(target_trades),
        )
        row = {
            "seed": market.sellers[0].client.seed,
            "condition": condition,
            "target": target,
            "market": data,
            "seller_costs": costs,
            "buyer_values": values,
            "metrics": metrics,
        }
        append(path, row)
        rows.append(row)
    return rows


def intervene(market, condition, target):
    agent = next(a for a in market.sellers if a.id == target)
    original = agent.valuation
    agent.valuation = round(original - condition.cost_drop, 2)
    # Keep old memories, original cost history, other agents' private data and channels.
    # No instruction to undercut is given in endogenous conditions.
    agent.client.notice = (
        f"Effective this hour and for the remaining market, your company's unit operating cost is "
        f"${agent.valuation:.2f} (previously ${original:.2f}). This update is private to your company. "
        "Your objective and market rules remain the same."
    )
    agent.client.scripted = condition.kind == "scripted_defector"
    return {
        "kind": condition.kind,
        "target": target,
        "effective_round": market.current_round.round_number,
        "cost_before": original,
        "cost_after": agent.valuation,
        "cost_drop": condition.cost_drop,
        "cost_units": "simulated auction dollars per lot; not API/compute spend",
        "private_notice": agent.client.notice,
        "scripted_policy": agent.client.scripted,
        "scripted_rule": "max(cost + 0.01, min(previous_peer_asks) - undercut_cents/100)"
        if agent.client.scripted
        else None,
        "peers_informed_by_experiment": False,
    }
