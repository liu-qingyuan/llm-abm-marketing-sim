from __future__ import annotations

import argparse
import json
from pathlib import Path

from llm_abm_sim import ConcurrentMessageExperimentConfig, ConcurrentMessageExperimentRunner
from llm_abm_sim.concurrent_message_experiment import (
    CONCURRENT_MESSAGE_FORMAL_MAX_RETRIES,
    CONCURRENT_MESSAGE_FORMAL_OBSERVED_MODEL,
    CONCURRENT_MESSAGE_FORMAL_REQUESTED_MODEL,
    CONCURRENT_MESSAGE_FORMAL_TIMEOUT_SECONDS,
)
from llm_abm_sim.prompt_field_summary import (
    CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
    CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
)
from llm_abm_sim.provider_accounting import ProviderResponseEnvelope
from llm_abm_sim.providers.openai_compatible import OpenAICompatibleDecisionAdapter
from llm_abm_sim.schemas import ProviderLLMConfig, ReportConfig

DEFAULT_REQUESTED_MODEL = CONCURRENT_MESSAGE_FORMAL_REQUESTED_MODEL
DEFAULT_OBSERVED_MODEL = CONCURRENT_MESSAGE_FORMAL_OBSERVED_MODEL
DEFAULT_PRIMARY_INPUT_TOKENS = 9
DEFAULT_PRIMARY_OUTPUT_TOKENS = 4
DEFAULT_SHADOW_INPUT_TOKENS = 8
DEFAULT_SHADOW_OUTPUT_TOKENS = 3
DEFAULT_TITLE = "Concurrent Message Experiment Validation"


class _FixedEnvelopeClient:
    def __init__(self, envelope: ProviderResponseEnvelope, *, expected_model: str) -> None:
        self._envelope = envelope
        self._expected_model = expected_model

    def create_response(self, messages: list[dict[str, str]], model: str) -> ProviderResponseEnvelope:
        del messages
        if model != self._expected_model:
            raise ValueError(f"unexpected requested model: {model}")
        return self._envelope


def _response_envelope(
    *,
    reason: str,
    observed_model: str,
    input_tokens: int,
    output_tokens: int,
) -> ProviderResponseEnvelope:
    return ProviderResponseEnvelope(
        decision_text=json.dumps(
            {
                "engage": False,
                "probability": 0.1,
                "reason": reason,
                "confidence": 0.9,
                "action": "ignore",
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        observed_model=observed_model,
        observed_model_status="reported",
        usage_status="complete",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
    )


def _build_adapter(
    *,
    prompt_version: str,
    requested_model: str,
    observed_model: str,
    timeout_seconds: float,
    max_retries: int,
    reason: str,
    input_tokens: int,
    output_tokens: int,
) -> OpenAICompatibleDecisionAdapter:
    return OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(
            enabled=True,
            provider="openai_compatible",
            model=requested_model,
            require_live_env=False,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            prompt_version=prompt_version,
        ),
        client=_FixedEnvelopeClient(
            _response_envelope(
                reason=reason,
                observed_model=observed_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
            expected_model=requested_model,
        ),
        sleep=lambda _delay: None,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the 1,000-user concurrent-message validation artifact with a mocked OpenAI-compatible provider"
    )
    parser.add_argument(
        "--dataset-dir", required=True, help="Processed dataset directory containing the latent-v1 CSV inputs"
    )
    parser.add_argument("--output-dir", required=True, help="Fresh output directory for the validation run")
    parser.add_argument("--title", default=DEFAULT_TITLE, help="Report title written into the persisted artifact")
    parser.add_argument(
        "--requested-model", default=DEFAULT_REQUESTED_MODEL, help="Requested model recorded in provider metadata"
    )
    parser.add_argument(
        "--observed-model", default=DEFAULT_OBSERVED_MODEL, help="Observed model recorded in mocked response envelopes"
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=CONCURRENT_MESSAGE_FORMAL_TIMEOUT_SECONDS,
        help="Provider timeout metadata recorded in the artifact",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=CONCURRENT_MESSAGE_FORMAL_MAX_RETRIES,
        help="Adapter retry count recorded in provider metadata",
    )
    parser.add_argument("--primary-input-tokens", type=int, default=DEFAULT_PRIMARY_INPUT_TOKENS)
    parser.add_argument("--primary-output-tokens", type=int, default=DEFAULT_PRIMARY_OUTPUT_TOKENS)
    parser.add_argument("--shadow-input-tokens", type=int, default=DEFAULT_SHADOW_INPUT_TOKENS)
    parser.add_argument("--shadow-output-tokens", type=int, default=DEFAULT_SHADOW_OUTPUT_TOKENS)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=Path(args.dataset_dir),
        report=ReportConfig(title=args.title),
    )
    primary_adapter = _build_adapter(
        prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        requested_model=args.requested_model,
        observed_model=args.observed_model,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        reason="mocked concurrent primary validation decision",
        input_tokens=args.primary_input_tokens,
        output_tokens=args.primary_output_tokens,
    )
    shadow_adapter = _build_adapter(
        prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
        requested_model=args.requested_model,
        observed_model=args.observed_model,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        reason="mocked concurrent shadow validation decision",
        input_tokens=args.shadow_input_tokens,
        output_tokens=args.shadow_output_tokens,
    )
    output_dir = ConcurrentMessageExperimentRunner(config, primary_adapter, shadow_adapter).run_and_write(
        args.output_dir
    )

    validation = json.loads((output_dir / "concurrent_validation.json").read_text(encoding="utf-8"))
    counts = validation["counts"]
    accounting = validation["variant_provider_accounting"]
    summary = {
        "output_dir": str(output_dir),
        "requested_model": args.requested_model,
        "observed_model": args.observed_model,
        "sample_users": counts["sample_users"],
        "eligible_user_message_pairs": counts["eligible_user_message_pairs"],
        "actual_exposures": counts["actual_exposures"],
        "primary": {
            "attempted": counts["primary_attempted"],
            "succeeded": counts["primary_successes"],
            "failed": counts["primary_failures"],
            "provider_invocations": accounting["primary"]["invocations"],
            "provider_responses": accounting["primary"]["responses"],
            "total_usage": accounting["primary"]["total_usage"],
        },
        "shadow": {
            "attempted": counts["shadow_attempted"],
            "succeeded": counts["shadow_successes"],
            "failed": counts["shadow_failures"],
            "provider_invocations": accounting["shadow"]["invocations"],
            "provider_responses": accounting["shadow"]["responses"],
            "total_usage": accounting["shadow"]["total_usage"],
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
