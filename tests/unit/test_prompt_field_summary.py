from __future__ import annotations

from llm_abm_sim.decision import DecisionInput
from llm_abm_sim.prompt_field_summary import (
    build_prompt_field_summary,
    capture_prompt_field_inclusion,
    profile_prompt_field_inclusion,
    summarize_prompt_fields,
)
from llm_abm_sim.schemas import (
    LatentAttributes,
    LatentProfileLabels,
    LatentValueWeights,
    PeerContext,
    PlatformContext,
    PostContent,
    UserProfile,
)


def test_prompt_field_summary_outputs_clean_chinese_profile_summary() -> None:
    profile = UserProfile.model_validate(
        {
            "user_id": "u1",
            "interest_tags": [" 锦江酒店 ", "", "环保生活", "锦江酒店", "x" * 80],
            "activity_score": 0.65,
            "global_influence_score": 0.81,
            "local_influence_score": 0.34,
            "brand_attitude": 1.0,
            "like_tendency": 1.0,
            "comment_tendency": 1.0,
            "share_tendency": 1.0,
            "latent_attributes": LatentAttributes(
                spec_id="jinjiang_user_latent_attributes_v1",
                method="latent_class_exact_quota_v1",
                seed=20260630,
                latent_class="class_2",
                environmental_consciousness_coef=1.037,
                value_weights=LatentValueWeights(
                    epistemic=0.4,
                    environmental=0.9,
                    functional=0.6,
                    health=0.7,
                    emotional=0.2,
                    social=0.1,
                ),
                profile_labels=LatentProfileLabels(
                    hotel_class="midscale",
                    travel_purpose="leisure",
                    gender="female",
                    age="age_26_35",
                    education="bachelor",
                    monthly_income="income_8001_15000",
                ),
            ),
        }
    )

    summary = summarize_prompt_fields(profile)

    assert "说明：活跃度、全平台影响力、锦江酒店社群内的局部影响力为可观测代理指标" in summary
    assert "环保意识倾向、消费价值、入住酒店类型和入住目的为虚拟实验标签" in summary
    assert "历史 hashtags 与文本主题派生的兴趣代理：锦江酒店、环保生活" in summary
    assert "不代表真实心理画像" in summary
    assert "真实 profile 兴趣标签" not in summary
    assert "活跃度：中等偏高（0.65）" in summary
    assert "全平台影响力：高（0.81）" in summary
    assert "锦江酒店社群内的局部影响力：中等偏低（0.34）" in summary
    assert "环保意识倾向：正向较强（1.04）" in summary
    assert "前三个秸秆制品相关消费价值：环保消费价值（0.90）、健康价值（0.70）、功能价值（0.60）" in summary
    assert "最近一次入住锦江旗下酒店类型：中端酒店" in summary
    assert "最近一次入住锦江旗下酒店目的：休闲旅游" in summary
    assert "class_2" not in summary
    assert "latent_class" not in summary
    assert "brand_attitude" not in summary
    assert "like_tendency" not in summary
    assert "comment_tendency" not in summary
    assert "share_tendency" not in summary
    assert "female" not in summary
    assert "age_26_35" not in summary
    assert "bachelor" not in summary
    assert "income_8001_15000" not in summary


def test_prompt_field_summary_omits_empty_optional_fields() -> None:
    summary = summarize_prompt_fields(UserProfile(user_id="u2", interest_tags=[]))

    assert "兴趣标签" not in summary
    assert "全平台影响力：" not in summary
    assert "锦江酒店社群内的局部影响力：" not in summary
    assert "秸秆制品相关消费价值" not in summary
    assert "最近一次入住" not in summary
    assert summary == ("说明：活跃度、全平台影响力、锦江酒店社群内的局部影响力为可观测代理指标；活跃度：中等（0.50）")


def test_profile_prompt_field_inclusion_uses_the_same_interest_tag_cleaning_path() -> None:
    included = profile_prompt_field_inclusion(
        UserProfile(user_id="included", interest_tags=[" 绿色旅行 ", "", "绿色旅行"])
    )
    omitted = profile_prompt_field_inclusion(UserProfile(user_id="omitted", interest_tags=[]))

    assert included["interest_tags"] == "included"
    assert omitted["interest_tags"] == "empty_omitted"


def test_prompt_field_inclusion_is_captured_only_when_summary_is_built() -> None:
    decision_input = DecisionInput(
        post=PostContent(post_id="p1", text="绿色酒店"),
        profile=UserProfile(user_id="u1", interest_tags=["绿色旅行"]),
        peer_context=PeerContext(),
        platform_context=PlatformContext(),
        time_step=0,
    )

    with capture_prompt_field_inclusion() as capture:
        assert capture.by_user == {}
        build_prompt_field_summary(decision_input)

    assert capture.by_user["u1"]["interest_tags"] == "included"


def test_prompt_field_summary_deduplicates_after_interest_tag_truncation() -> None:
    summary = summarize_prompt_fields(
        UserProfile(
            user_id="u3",
            interest_tags=[
                "a" * 30,
                "a" * 24 + "different suffix",
                "绿色营销",
            ],
        )
    )

    assert summary.count("a" * 24) == 1
    assert "绿色营销" in summary


def test_build_prompt_field_summary_converts_decision_input_context_to_chinese_summaries() -> None:
    decision_input = DecisionInput(
        post=PostContent(
            post_id="p1",
            text="锦江推出秸秆制品绿色营销活动",
            topic_tags=["锦江", "环保"],
            media_summary="短视频展示酒店客房用品",
        ),
        profile=UserProfile(user_id="u1", interest_tags=["绿色旅行"], activity_score=0.6),
        peer_context=PeerContext(
            engaged_neighbors=2,
            exposed_neighbors=4,
            influential_engaged_neighbors=1,
            visible_likes=3,
            visible_comments=1,
            visible_shares=0,
        ),
        platform_context=PlatformContext(hot_topics=["环保"], platform_mood="活动上线"),
        time_step=3,
        prompt_version="engage-provider-v1",
    )

    summary = build_prompt_field_summary(decision_input)

    assert summary == {
        "post_summary": "帖子内容：锦江推出秸秆制品绿色营销活动；主题标签：锦江、环保；媒体摘要：短视频展示酒店客房用品",
        "marketing_content_summary": "锦江推出秸秆制品绿色营销活动",
        "post_value_summary": "未提供明确价值维度",
        "observed_profile_summary": (
            "说明：活跃度、全平台影响力、锦江酒店社群内的局部影响力为可观测代理指标；"
            "活跃度：中等偏高（0.60）；历史 hashtags 与文本主题派生的兴趣代理："
            "绿色旅行（仅表示可复算的历史行为主题，不代表真实心理画像）"
        ),
        "consumption_preference_summary": "",
        "individual_preference_summary": (
            "说明：活跃度、全平台影响力、锦江酒店社群内的局部影响力为可观测代理指标；"
            "活跃度：中等偏高（0.60）；历史 hashtags 与文本主题派生的兴趣代理："
            "绿色旅行（仅表示可复算的历史行为主题，不代表真实心理画像）"
        ),
        "peer_influence_summary": "邻居曝光：4；邻居互动：2；互动比例：0.50；有影响力的已互动邻居：1；可见点赞：3；可见评论：1；可见分享：0",
        "platform_context_summary": "平台热门话题：环保；平台氛围：活动上线；Feed 排序权重：1.00；痕迹可见度：1.00",
    }
