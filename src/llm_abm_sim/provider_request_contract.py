from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

from .prompt_contracts import (
    CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY,
    CONCURRENT_ROBUSTNESS_PROMPT_TOKENS,
    DECISION_OUTPUT_SCHEMA,
)
from .provider_accounting import ProviderAccounting
from .schemas import ProviderLLMConfig

ReasoningEffortValue = Literal["low", "medium", "high"]


def engage_decision_json_schema() -> dict[str, Any]:
    """Return a fresh JSON-schema request object for the shared Decision contract."""

    return {
        "type": "json_schema",
        "name": "engage_decision",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": DECISION_OUTPUT_SCHEMA.additional_properties,
            "required": list(DECISION_OUTPUT_SCHEMA.required_fields),
            "properties": {
                "engage": {"type": "boolean"},
                "probability": {
                    "type": "number",
                    "minimum": DECISION_OUTPUT_SCHEMA.probability_range[0],
                    "maximum": DECISION_OUTPUT_SCHEMA.probability_range[1],
                },
                "reason": {"type": "string"},
                "confidence": {
                    "type": "number",
                    "minimum": DECISION_OUTPUT_SCHEMA.confidence_range[0],
                    "maximum": DECISION_OUTPUT_SCHEMA.confidence_range[1],
                },
                "action": {"type": "string", "enum": list(DECISION_OUTPUT_SCHEMA.action_values)},
            },
        },
    }


def _structured_output_schema_hash() -> str:
    encoded = json.dumps(
        engage_decision_json_schema(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


STRUCTURED_OUTPUT_SCHEMA_HASH = "sha256:baa4b5ac3950d8834bd296b184b8544c707633d5e668e1ee23cb8570e0e46654"
if _structured_output_schema_hash() != STRUCTURED_OUTPUT_SCHEMA_HASH:
    raise ValueError("Decision JSON schema changed without a new structured-output schema version")
OMITTED_SAMPLING_PARAMETERS: tuple[str, ...] = ("temperature", "top_p", "seed")


@dataclass(frozen=True)
class ProviderRequestContract:
    """Safe, immutable facts that fully identify one Provider request policy."""

    schema_version: Literal["provider-request-contract-v1"]
    requested_model: str
    prompt_version: str
    prompt_canonical_hash: str | None
    wire_api: str
    reasoning_effort: ReasoningEffortValue | None
    output_token_ceiling: int | None
    timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float
    structured_output_schema_version: Literal["engage-decision-output-v1"]
    structured_output_schema_hash: str
    omitted_parameters: tuple[str, ...]

    def audit_record(self) -> dict[str, object]:
        """Return allowlisted request facts without messages, payloads, responses, or credentials."""

        return asdict(self)


@dataclass(frozen=True)
class ProviderRequestAccounting:
    """Typed request identity plus returned-response accounting for one Adapter."""

    schema_version: Literal["provider-request-accounting-v1"]
    requested_model: str
    request_contract: ProviderRequestContract
    response_accounting: ProviderAccounting

    def audit_record(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "requested_model": self.requested_model,
            "request_contract": self.request_contract.audit_record(),
            "response_accounting": self.response_accounting.model_dump(mode="json"),
        }


def build_provider_request_contract(
    config: ProviderLLMConfig,
    *,
    requested_model: str,
) -> ProviderRequestContract:
    try:
        prompt_hash = CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(config.prompt_version).canonical_hash
    except ValueError:
        prompt_hash = None
    reasoning_effort: ReasoningEffortValue | None = None
    if config.reasoning_effort is not None:
        reasoning_effort = config.reasoning_effort.value
    return ProviderRequestContract(
        schema_version="provider-request-contract-v1",
        requested_model=requested_model,
        prompt_version=config.prompt_version,
        prompt_canonical_hash=prompt_hash,
        wire_api=config.wire_api,
        reasoning_effort=reasoning_effort,
        output_token_ceiling=config.max_output_tokens,
        timeout_seconds=config.timeout_seconds,
        max_retries=config.max_retries,
        retry_backoff_seconds=config.retry_backoff_seconds,
        structured_output_schema_version=DECISION_OUTPUT_SCHEMA.schema_version,
        structured_output_schema_hash=STRUCTURED_OUTPUT_SCHEMA_HASH,
        omitted_parameters=OMITTED_SAMPLING_PARAMETERS,
    )


def validate_robustness_request_contract(contract: ProviderRequestContract) -> None:
    """Fail closed unless a request matches the Prompt–Model robustness policy."""

    if contract.prompt_version not in CONCURRENT_ROBUSTNESS_PROMPT_TOKENS:
        raise ValueError("robustness request requires a declared P0-P3 Prompt token")
    prompt_contract = CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(contract.prompt_version)
    if contract.prompt_canonical_hash != prompt_contract.canonical_hash:
        raise ValueError("robustness request Prompt hash does not match its stable token")
    if contract.wire_api != "responses":
        raise ValueError("robustness request requires the Responses wire")
    if contract.reasoning_effort != "low":
        raise ValueError("robustness request requires explicit reasoning_effort=low")
    if contract.output_token_ceiling is None:
        raise ValueError("robustness request requires an explicit output-token ceiling")
    if contract.structured_output_schema_version != DECISION_OUTPUT_SCHEMA.schema_version:
        raise ValueError("robustness request Decision schema version mismatch")
    if contract.structured_output_schema_hash != STRUCTURED_OUTPUT_SCHEMA_HASH:
        raise ValueError("robustness request Decision schema hash mismatch")
    if contract.omitted_parameters != OMITTED_SAMPLING_PARAMETERS:
        raise ValueError("robustness request must omit temperature, top_p, and seed")
