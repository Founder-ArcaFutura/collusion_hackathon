"""vLLM/Outlines runtime contract and metadata transport for hosted inference."""

import json
from importlib.metadata import version

from packaging.version import InvalidVersion, Version

XGRAMMAR_VERSION = "0.1.13"
OUTLINES_VERSION = "0.1.11"
VLLM_BASE_VERSION = "0.6.6"
GUIDED_DECODING_BACKEND = "outlines"
RUNTIME_HEADER = "X-Poseidon-Serving-Runtime"


def collect_serving_runtime(
    package_version=version,
):
    """Fail closed unless the vLLM 0.6.6 Outlines runtime is installed."""
    vllm_version = package_version("vllm")
    xgrammar_version = package_version("xgrammar")
    outlines_version = package_version("outlines")
    try:
        vllm_base_version = Version(vllm_version).base_version
    except InvalidVersion as exc:
        raise RuntimeError(f"Invalid vLLM package version: {vllm_version}") from exc
    if vllm_base_version != VLLM_BASE_VERSION:
        raise RuntimeError(
            f"Expected vLLM {VLLM_BASE_VERSION}, found {vllm_version}"
        )
    if xgrammar_version != XGRAMMAR_VERSION:
        raise RuntimeError(
            f"Expected XGrammar {XGRAMMAR_VERSION}, found {xgrammar_version}"
        )
    if outlines_version != OUTLINES_VERSION:
        raise RuntimeError(
            f"Expected Outlines {OUTLINES_VERSION} for vLLM {VLLM_BASE_VERSION}, found {outlines_version}"
        )
    return {
        "vllm": vllm_version,
        "xgrammar": xgrammar_version,
        "outlines": outlines_version,
        "guided_decoding_backend": GUIDED_DECODING_BACKEND,
        "required_api": "vllm guided_json via outlines backend",
        "required_api_available": True,
    }


def validate_serving_runtime(metadata):
    """Validate the actual dependency report returned by the Modal server."""
    if not isinstance(metadata, dict):
        raise RuntimeError("Modal serving runtime metadata is missing or invalid")
    try:
        vllm_base_version = Version(metadata["vllm"]).base_version
    except (InvalidVersion, KeyError, TypeError) as exc:
        raise RuntimeError("Modal server did not report a valid vLLM version") from exc
    if vllm_base_version != VLLM_BASE_VERSION:
        raise RuntimeError(f"Modal server is not running vLLM {VLLM_BASE_VERSION}")
    if metadata.get("outlines") != OUTLINES_VERSION:
        raise RuntimeError(f"Modal server is not running Outlines {OUTLINES_VERSION}")
    if metadata.get("guided_decoding_backend") != GUIDED_DECODING_BACKEND:
        raise RuntimeError("Modal server guided-decoding backend is not outlines")
    if metadata.get("required_api") != "vllm guided_json via outlines backend" or not metadata.get("required_api_available"):
        raise RuntimeError("Modal server does not report the required guided_json/Outlines contract")
    return metadata


async def runtime_metadata_middleware(request, call_next):
    """Attach actual serving package versions to readiness/API responses."""
    response = await call_next(request)
    runtime = collect_serving_runtime()
    response.headers[RUNTIME_HEADER] = json.dumps(runtime, separators=(",", ":"))
    return response
