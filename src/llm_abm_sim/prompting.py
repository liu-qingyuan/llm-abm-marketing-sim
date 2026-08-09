from __future__ import annotations

from .decision import DecisionInput
from .prompt_contracts import CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY, CONCURRENT_ROBUSTNESS_PROMPT_TOKENS
from .prompt_field_summary import (
    CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
    JINJIANG_PROMPT_V3,
    JINJIANG_PROMPT_V3_TOKENS,
    build_prompt_field_summary,
)

PROMPT_VERSION = JINJIANG_PROMPT_V3


def build_engagement_prompt(decision_input: DecisionInput) -> list[dict[str, str]]:
    """Build the configured provider prompt with schema-safe context."""

    prompt_version = decision_input.prompt_version
    if prompt_version in JINJIANG_PROMPT_V3_TOKENS:
        return _build_jinjiang_prompt_v3(decision_input)
    if prompt_version in CONCURRENT_ROBUSTNESS_PROMPT_TOKENS:
        return _build_concurrent_primary_prompt(decision_input)
    if prompt_version == CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION:
        return _build_concurrent_shadow_prompt(decision_input)
    raise ValueError(f"unsupported prompt_version: {prompt_version}")


def _build_jinjiang_prompt_v3(decision_input: DecisionInput) -> list[dict[str, str]]:
    summaries = build_prompt_field_summary(decision_input)
    preference_summary = summaries["consumption_preference_summary"] or "未提供可用消费偏好摘要"
    return [
        {
            "role": "system",
            "content": (
                "你是 agent-based marketing diffusion simulator 中的结构化决策函数。"
                "请模拟一名抖音用户无意间刷到锦江酒店集团使用秸秆制品、推进环保举措的绿色营销内容，"
                "结合营销文案、用户可观测特征、用户消费偏好和其他用户行为，判断该用户是否互动以及最可能的互动动作。"
                "只返回一个 JSON 对象，不要输出 Markdown、解释性段落、headers、secrets 或额外 commentary。"
            ),
        },
        {
            "role": "user",
            "content": "\n\n".join(
                [
                    "【营销内容】\n" f"{summaries['marketing_content_summary']}",
                    "【内容主要强调的价值】\n" f"{summaries['post_value_summary']}",
                    "【用户可观测特征】\n" f"{summaries['observed_profile_summary']}",
                    "【用户消费偏好】\n" f"{preference_summary}",
                    "【其他用户行为】\n"
                    f"{summaries['peer_influence_summary']}\n"
                    f"平台上下文：{summaries['platform_context_summary']}",
                    "【输出 schema】\n"
                    "必须返回字段：engage（boolean）、probability（0.0 到 1.0）、"
                    "reason（简短非敏感理由）、confidence（0.0 到 1.0）、"
                    "action（ignore/like/comment/share）。"
                    "engage=false 时 action 必须为 ignore；"
                    "engage=true 时 action 必须为 like、comment 或 share 之一。",
                ]
            ),
        },
    ]


def _build_concurrent_primary_prompt(decision_input: DecisionInput) -> list[dict[str, str]]:
    summaries = build_prompt_field_summary(decision_input)
    return CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.render(decision_input.prompt_version, summaries)


def _build_concurrent_shadow_prompt(decision_input: DecisionInput) -> list[dict[str, str]]:
    summaries = build_prompt_field_summary(decision_input)
    return [
        {
            "role": "system",
            "content": (
                "你是 concurrent-message validation runtime 中的结构化决策函数。"
                "你只可以使用当前 message 原文、可观测代理指标、受控 Synthetic Experiment Labels 和中性 PeerContext。"
                "其中额外人口学标签只用于受控对照，不得据此推断人格、价值高低、消费能力优劣或行为必然性。"
                "不要推断或补写未提供的人口学身份、Class、昵称、简介、签名、粉丝原始字段、历史标签、平台上下文或其他 message 历史。"
                "只返回一个 JSON 对象，不要输出 Markdown、解释性段落、headers、secrets 或额外 commentary。"
            ),
        },
        {
            "role": "user",
            "content": "\n\n".join(
                [
                    "【当前 message 原文】\n" f"{summaries['marketing_content_summary']}",
                    "【内容主要强调的价值】\n" f"{summaries['post_value_summary']}",
                    "【用户可观测代理指标】\n" f"{summaries['observed_profile_summary']}",
                    "【Synthetic Experiment Labels】\n" f"{summaries['consumption_preference_summary']}",
                    "【Synthetic Experiment Labels（额外人口学对照）】\n"
                    f"{summaries['synthetic_demographic_summary']}",
                    "【中性 PeerContext】\n" f"{summaries['peer_influence_summary']}",
                    "【输出 schema】\n"
                    "必须返回字段：engage（boolean）、probability（0.0 到 1.0）、"
                    "reason（简短非敏感理由）、confidence（0.0 到 1.0）、"
                    "action（ignore/like/comment/share）。"
                    "engage=false 时 action 必须为 ignore；"
                    "engage=true 时 action 必须为 like、comment 或 share 之一。",
                ]
            ),
        },
    ]
