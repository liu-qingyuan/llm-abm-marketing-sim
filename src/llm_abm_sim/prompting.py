from __future__ import annotations

import json

from .decision import DecisionInput

PROMPT_VERSION = "engage-provider-v1"


def build_engagement_prompt(decision_input: DecisionInput) -> list[dict[str, str]]:
    """Build a provider prompt with only schema-safe simulation context."""

    payload = {
        "post_content": decision_input.post.model_dump(mode="json"),
        "individual_preference": decision_input.profile.model_dump(mode="json"),
        "peer_influence": decision_input.peer_context.model_dump(mode="json"),
        "platform_context": decision_input.platform_context.model_dump(mode="json"),
        "time_step": decision_input.time_step,
        "required_output_schema": {
            "engage": "boolean",
            "probability": "float between 0.0 and 1.0",
            "reason": "short non-sensitive explanation",
            "confidence": "float between 0.0 and 1.0",
            "action": "one of ignore, like, comment, share",
        },
    }
    return [
        {
            "role": "system",
            "content": (
                "You are a decision function inside an agent-based marketing diffusion simulator. "
                "Return only one JSON object that validates the required output schema. "
                "Do not include secrets, headers, markdown, or extra commentary."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
        },
    ]
