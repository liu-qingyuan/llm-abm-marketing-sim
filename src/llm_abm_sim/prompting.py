from __future__ import annotations

from .decision import DecisionInput
from .prompt_field_summary import build_prompt_field_summary

PROMPT_VERSION = "jinjiang-green-marketing-prompt-v3"


def build_engagement_prompt(decision_input: DecisionInput) -> list[dict[str, str]]:
    """Build the Jinjiang Prompt v3 provider prompt with schema-safe context."""

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
