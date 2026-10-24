"""Role-specific vLLM 0.6.6 guided JSON contracts for agent outputs."""

from copy import deepcopy

SCHEMA_VERSION = "agent-action-json-v1"
BOUNDED_TEXT_SCHEMA_VERSION = "agent-action-json-v2-bounded-text"
BOUNDED_SCRATCHPAD_SCHEMA_VERSION = "agent-action-json-v3-bounded-scratchpad"
BOUNDED_SCRATCHPAD_LIMITS = {"scratch_pad_update": 1000}

# Limits leave headroom over the longest successful text fields in the archived
# Qwen runs while preventing scratchpad repetition from consuming the generation
# budget. These are serialization limits, not changes to agent incentives.
BOUNDED_TEXT_LIMITS = {
    "reflection": 600,
    "plan_for_this_hour": 400,
    "new_memory": 500,
    "scratch_pad_update": 1200,
    "plan_for_message": 300,
    "message_to_sellers": 500,
    "message_to_buyers": 500,
}


def _action_schema():
    # Prompt templates historically spell withdrawal as the JSON string "null".
    # Preserve that contract alongside JSON null for compatible strict parsing.
    return {
        "anyOf": [
            {"type": "number"},
            {"type": "string", "enum": ["null"]},
        ]
    }


def _base(action_key, comms_key=None):
    properties = {
        "reflection": {"type": "string"},
        "plan_for_this_hour": {"type": "string"},
        action_key: _action_schema(),
        "new_memory": {"type": "string"},
        "scratch_pad_update": {"type": "string"},
    }
    required = list(properties)
    if comms_key:
        properties["plan_for_message"] = {"type": "string"}
        properties[comms_key] = {
            "anyOf": [{"type": "string"}, {"type": "null"}]
        }
        required.extend(("plan_for_message", comms_key))
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def buyer_schema(buyer_comms_enabled=False):
    schema = _base("bid", "message_to_buyers" if buyer_comms_enabled else None)
    return deepcopy(schema)


def seller_schema(seller_comms_enabled=True):
    schema = _base("ask", "message_to_sellers" if seller_comms_enabled else None)
    return deepcopy(schema)


def _bounded_text_schema(action_key, comms_key=None):
    schema = _base(action_key, comms_key)
    for field in schema["properties"]:
        if field == action_key:
            continue
        spec = schema["properties"][field]
        if spec.get("type") == "string":
            spec["maxLength"] = BOUNDED_TEXT_LIMITS[field]
        elif "anyOf" in spec:
            for option in spec["anyOf"]:
                if option.get("type") == "string":
                    option["maxLength"] = BOUNDED_TEXT_LIMITS[field]
    return deepcopy(schema)


def bounded_buyer_schema(buyer_comms_enabled=False):
    return _bounded_text_schema(
        "bid", "message_to_buyers" if buyer_comms_enabled else None
    )


def bounded_seller_schema(seller_comms_enabled=True):
    return _bounded_text_schema(
        "ask", "message_to_sellers" if seller_comms_enabled else None
    )


def _bounded_scratchpad_schema(action_key, comms_key=None):
    schema = _base(action_key, comms_key)
    schema["properties"]["scratch_pad_update"]["maxLength"] = (
        BOUNDED_SCRATCHPAD_LIMITS["scratch_pad_update"]
    )
    return deepcopy(schema)


def bounded_scratchpad_buyer_schema(buyer_comms_enabled=False):
    return _bounded_scratchpad_schema(
        "bid", "message_to_buyers" if buyer_comms_enabled else None
    )


def bounded_scratchpad_seller_schema(seller_comms_enabled=True):
    return _bounded_scratchpad_schema(
        "ask", "message_to_sellers" if seller_comms_enabled else None
    )


def schema_for(role, protocol):
    if protocol.response_schema_version == BOUNDED_SCRATCHPAD_SCHEMA_VERSION:
        if role == "buyer":
            return bounded_scratchpad_buyer_schema(protocol.buyer_comms_enabled)
        if role == "seller":
            return bounded_scratchpad_seller_schema(protocol.seller_comms_enabled)
        raise ValueError(f"Unknown agent role: {role}")
    if protocol.response_schema_version == BOUNDED_TEXT_SCHEMA_VERSION:
        if role == "buyer":
            return bounded_buyer_schema(protocol.buyer_comms_enabled)
        if role == "seller":
            return bounded_seller_schema(protocol.seller_comms_enabled)
        raise ValueError(f"Unknown agent role: {role}")
    if role == "buyer":
        return buyer_schema(protocol.buyer_comms_enabled)
    if role == "seller":
        return seller_schema(protocol.seller_comms_enabled)
    raise ValueError(f"Unknown agent role: {role}")
