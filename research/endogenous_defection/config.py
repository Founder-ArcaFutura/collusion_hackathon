"""Validated, serializable protocol. No provider calls at import or during planning."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    kind: Literal["control", "cost_shock", "scripted_defector"]
    cost_drop: float = Field(default=0, ge=0, allow_inf_nan=False)


class Protocol(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_version: str = "pilot-v1"
    seeds: list[int] = [0, 1, 2]
    seller_costs: list[float] = [80, 80, 80]
    buyer_values: list[float] = [100, 100]
    warmup_rounds: int = Field(default=15, ge=1)
    post_rounds: int = Field(default=15, ge=1)
    window: int = Field(default=5, ge=2)
    min_qualifying_seeds: int = Field(default=2, ge=1)
    high_price_index: float = Field(default=0.5, gt=0, lt=1)
    min_trades_per_round: int = Field(default=1, ge=1)
    undercut_cents: int = Field(default=1, ge=1)
    temperature: float = Field(default=0.7, ge=0, allow_inf_nan=False)
    max_tokens: int = Field(default=1200, ge=64)
    provider_seed: bool = False
    max_action_attempts: int = Field(default=1, ge=1, le=2)
    numeric_string_actions: bool = False
    response_schema_version: Literal[
        "unconstrained-v1",
        "agent-action-json-v1",
        "agent-action-json-v2-bounded-text",
        "agent-action-json-v3-bounded-scratchpad",
    ] = "unconstrained-v1"
    buyer_comms_enabled: bool = False
    execution_enabled: bool = True
    model_id: str | None = None
    allow_continuations: bool = True
    hide_num_rounds: bool = True
    announced_rounds: int | None = Field(default=None, ge=1)
    identity_mode: Literal["numbered", "upstream_seeded"] = "numbered"
    initialization_seller_slots: int | None = Field(default=None, ge=2)
    initial_seller_ask_range: tuple[float, float] = (96.25, 98.75)
    initial_buyer_bid_range: tuple[float, float] = (81.25, 83.75)
    seller_comms_enabled: bool = True
    conditions: list[Condition] = [
        Condition(name="control", kind="control"),
        Condition(name="cost_drop_5", kind="cost_shock", cost_drop=5),
        Condition(name="cost_drop_15", kind="cost_shock", cost_drop=15),
        Condition(name="scripted_drop_15", kind="scripted_defector", cost_drop=15),
    ]

    @model_validator(mode="after")
    def check_design(self):
        import math

        if len(self.seller_costs) < 2 or not self.buyer_values:
            raise ValueError("Need at least two sellers and one buyer")
        if (
            self.initialization_seller_slots is not None
            and self.initialization_seller_slots < len(self.seller_costs)
        ):
            raise ValueError("Initialization seller slots cannot be fewer than sellers")
        for low, high in (self.initial_seller_ask_range, self.initial_buyer_bid_range):
            if (
                not math.isfinite(low)
                or not math.isfinite(high)
                or low < 0
                or low > high
            ):
                raise ValueError(
                    "Initial order ranges must be finite, nonnegative and ordered"
                )
        if not self.allow_continuations and any(
            c.kind != "control" for c in self.conditions
        ):
            raise ValueError(
                "Control-only protocols cannot contain intervention conditions"
            )
        if self.announced_rounds is not None and self.announced_rounds != (
            self.warmup_rounds + self.post_rounds
            if self.allow_continuations
            else self.warmup_rounds
        ):
            raise ValueError(
                "Announced horizon must match the planned control/continuation horizon"
            )
        if any(
            not math.isfinite(x) or x < 0 for x in self.seller_costs + self.buyer_values
        ):
            raise ValueError("Valuations must be finite and nonnegative")
        if not self.seeds or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("Seeds must be nonempty and unique")
        if self.window > min(self.warmup_rounds, self.post_rounds):
            raise ValueError("Window must fit both phases")
        if self.min_qualifying_seeds > len(self.seeds):
            raise ValueError("Too few planned seeds for the positive-control gate")
        names = [c.name for c in self.conditions]
        if len(set(names)) != len(names) or names.count("control") != 1:
            raise ValueError("Unique conditions including 'control' are required")
        if sum(c.kind == "control" for c in self.conditions) != 1:
            raise ValueError("Exactly one control is required")
        for c in self.conditions:
            if (c.name == "control") != (c.kind == "control"):
                raise ValueError("The control must be named 'control'")
            if c.kind == "control" and c.cost_drop != 0:
                raise ValueError("Control must preserve costs")
            if c.kind != "control" and c.cost_drop <= 0:
                raise ValueError("Interventions need a positive cost drop")
            if c.cost_drop > min(self.seller_costs):
                raise ValueError("Cost shock could create a negative cost")
        return self

    def call_estimate(self):
        agents = len(self.seller_costs) + len(self.buyer_values)
        warmup = len(self.seeds) * self.warmup_rounds * agents * self.max_action_attempts
        branches = (
            len(self.seeds)
            * self.post_rounds
            * sum(agents - int(c.kind == "scripted_defector") for c in self.conditions)
            * self.max_action_attempts
        )
        if not self.allow_continuations:
            branches = 0
        return {
            "control": warmup,
            "interventions_max": branches,
            "pilot_max": warmup + branches,
        }


def load_protocol(path: Path) -> Protocol:
    return Protocol.model_validate(json.loads(path.read_text(encoding="utf-8")))
