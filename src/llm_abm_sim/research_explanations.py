from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Protocol


class LineageEntry(Protocol):
    @property
    def field_name(self) -> str: ...

    @property
    def provenance(self) -> str: ...

    @property
    def usage_stages(self) -> Sequence[str]: ...


@dataclass(frozen=True)
class _ExplanationSpec:
    chinese_name: str
    meaning: str
    source: str
    calculation: str
    value_range: str
    interpretation: str
    limitation: str


@dataclass(frozen=True)
class FieldExplanation:
    field_name: str
    chinese_name: str
    meaning: str
    source: str
    calculation: str
    value_range: str
    usage: str
    interpretation: str
    limitation: str


_PROVENANCE = {
    "Direct Observed Profile Field": (
        "Direct Observed Profile Field（直接观测画像字段）",
        "来自 processed 数据中可直接观察或定位的记录。",
    ),
    "Historical Behavioral Evidence": (
        "Historical Behavioral Evidence（历史行为证据）",
        "由 Historical Set（历史集合）的评论、回复、视频或来源记录形成。",
    ),
    "Derived Proxy Metric": (
        "Derived Proxy Metric（派生代理指标）",
        "由可观测字段按项目声明的方法复算，不是平台官方指标。",
    ),
    "Synthetic Experiment Label": (
        "Synthetic Experiment Label（合成实验标签）",
        "由固定规格和随机种子生成，只用于仿真实验。",
    ),
    "Runtime Simulation Result": (
        "Runtime Simulation Result（仿真运行结果）",
        "由本次 Target Delivery Ranking runtime 或报告构建过程记录。",
    ),
}

_USAGE_STAGE = {
    "Sampling": "Sampling（抽样）：形成 Base Sample（基础样本）或 Final Sample（最终样本）",
    "Seed Selection": "Seed Selection（种子选择）：识别首批固定投放用户",
    "Ranking": "Ranking（排序）：形成逐轮候选证据、名次或投放结果",
    "LLM Prompt": "LLM Prompt（大模型提示）：作为曝光后 action 决策输入",
    "Report Only": "Report Only（仅报告）：只用于审计、解释或下载",
}


def _text(
    chinese_name: str,
    meaning: str,
    source: str,
    *,
    limitation: str = "文本只表达记录内容；空值表示未观测到，不能推断真实情况。",
) -> _ExplanationSpec:
    return _ExplanationSpec(
        chinese_name,
        meaning,
        source,
        "不适用：该字段是记录值，不通过数值公式计算。",
        "文本或空值。",
        "不适用：文本字段没有高低方向，应结合字段语义阅读。",
        limitation,
    )


def _category(
    chinese_name: str,
    meaning: str,
    source: str,
    *,
    values: str = "有限类别或空值。",
    limitation: str = "类别只适用于本项目声明的研究口径，不能外推为真实身份或平台分类。",
) -> _ExplanationSpec:
    return _ExplanationSpec(
        chinese_name,
        meaning,
        source,
        "不适用：按已声明规则选择或记录类别，不进行连续数值计算。",
        values,
        "不适用：类别没有统一的高低顺序。",
        limitation,
    )


def _count(
    chinese_name: str,
    meaning: str,
    source: str,
    *,
    calculation: str = "对满足字段条件的记录计数。",
    limitation: str = "计数受本次数据覆盖与研究口径限制，不代表平台全量事实。",
) -> _ExplanationSpec:
    return _ExplanationSpec(
        chinese_name,
        meaning,
        source,
        calculation,
        "0 及以上的整数。",
        "数值越高表示该口径下记录数量越多；0 表示本次未记录到。",
        limitation,
    )


def _score(
    chinese_name: str,
    meaning: str,
    source: str,
    calculation: str,
    *,
    limitation: str = "该值是研究代理或相对排序信号，不是平台官方指数，也不能用于因果或心理推断。",
) -> _ExplanationSpec:
    return _ExplanationSpec(
        chinese_name,
        meaning,
        source,
        calculation,
        "0..1 的归一化数值。",
        "越接近 1 表示该字段限定的信号越强，越接近 0 表示越弱或未观测到。",
        limitation,
    )


def _boolean(chinese_name: str, meaning: str, source: str, *, limitation: str) -> _ExplanationSpec:
    return _ExplanationSpec(
        chinese_name,
        meaning,
        source,
        "按字段声明的条件判定 true 或 false。",
        "true / false。",
        "true 表示条件成立，false 表示条件不成立；二者不是强弱分数。",
        limitation,
    )


def _path(chinese_name: str, meaning: str, source: str) -> _ExplanationSpec:
    return _ExplanationSpec(
        chinese_name,
        meaning,
        source,
        "不适用：由 writer 使用固定 artifact 名称写入。",
        "run 目录内的相对路径。",
        "不适用：路径没有高低方向。",
        "路径只定位允许公开的 processed/runtime artifact，不代表 artifact 内容本身。",
    )


_USER_FIELD_SPECS = {
    "user_id": _text(
        "用户标识",
        "在 processed 数据和 runtime 中关联同一 Research User（研究用户）的稳定标识。",
        "processed 用户记录。",
    ),
    "nickname": _text("昵称", "用户记录中的公开昵称。", "processed profile 字段。"),
    "bio": _text("简介", "用户记录中的清洗后简介文本。", "processed profile 字段。"),
    "signature": _text("个性签名", "用户记录中的清洗后签名文本。", "processed profile 字段。"),
    "interest_tags": _text(
        "兴趣标签",
        "从允许字段整理的用户兴趣标签列表。",
        "processed 用户画像。",
        limitation="标签是清洗后的可观测描述，不等同于真实稳定偏好或心理特征。",
    ),
    "historical_tags": _text(
        "历史互动标签",
        "用户在 Historical Set（历史集合）中互动视频的标签集合。",
        "历史评论与视频标签关联。",
        limitation="只反映已采集历史互动，未出现的标签不表示用户不感兴趣。",
    ),
    "follower_count": _count(
        "粉丝数",
        "采集时点观测到的 follower 数量。",
        "processed profile 字段。",
        calculation="直接记录采集时点的非负计数。",
        limitation="时点值可能变化，也不等同于真实触达或影响效果。",
    ),
    "following_count": _count(
        "关注数",
        "采集时点观测到的 following 数量。",
        "processed profile 字段。",
        calculation="直接记录采集时点的非负计数。",
    ),
    "video_count": _count(
        "作品数",
        "采集时点观测到的公开视频数量。",
        "processed profile 字段。",
        calculation="直接记录采集时点的非负计数。",
    ),
    "activity_score": _score(
        "活跃度代理",
        "综合历史视频、评论和回复活跃度的可观测代理。",
        "processed 历史活动计数。",
        "由 video、comment、reply 三项归一化分量按项目方法组合。",
    ),
    "activity_video_score": _score(
        "视频活跃分量",
        "activity_score（活跃度代理）中的历史作品分量。",
        "processed video_count。",
        "按数据集 reference 对作品数归一化。",
    ),
    "activity_comment_score": _score(
        "评论活跃分量",
        "activity_score（活跃度代理）中的一级评论分量。",
        "Historical Set 一级评论记录。",
        "按数据集 reference 对历史评论数归一化。",
    ),
    "activity_reply_score": _score(
        "回复活跃分量",
        "activity_score（活跃度代理）中的回复分量。",
        "Historical Set 二级回复记录。",
        "按数据集 reference 对历史回复数归一化。",
    ),
    "global_influence_score": _score(
        "全局影响力代理",
        "以 follower evidence 为主的全平台影响力代理。",
        "processed profile 与派生 reference。",
        "按项目 influence 方法归一化 follower 等可观测证据。",
    ),
    "local_influence_score": _score(
        "局部影响力代理",
        "在 Historical Set 评论网络中的位置与评论获赞认可组合代理。",
        "历史评论网络与评论获赞记录。",
        "组合 local_network_score 与 local_recognition_score。",
    ),
    "local_network_score": _score(
        "局部网络分量",
        "local_influence_score（局部影响力代理）的评论网络位置分量。",
        "Historical Set 评论派生网络。",
        "按项目网络 reference 对局部连接证据归一化。",
    ),
    "local_recognition_score": _score(
        "局部认可分量",
        "local_influence_score（局部影响力代理）的评论获赞认可分量。",
        "Historical Set 评论获赞记录。",
        "按项目 recognition reference 对评论获赞证据归一化。",
    ),
    "latent_attribute_spec_id": _text(
        "合成属性规格标识",
        "生成本组 latent attributes（合成属性）的规格版本。",
        "项目内固定 latent attribute specification。",
        limitation="它只标识实验生成规则，不证明用户真实属性。",
    ),
    "latent_attribute_method": _text(
        "合成属性方法",
        "生成 latent attributes（合成属性）所用的方法名称。",
        "项目内合成实验配置。",
        limitation="方法用于可复现仿真，不是个人画像识别方法。",
    ),
    "latent_attribute_seed": _count(
        "合成属性随机种子",
        "复现该用户合成标签的确定性随机种子。",
        "项目配置与 user_id 派生。",
        calculation="由全局实验 seed 和稳定用户标识确定性派生。",
        limitation="数值只控制复现，大小没有研究含义。",
    ),
    "latent_class": _category("合成实验类别", "为仿真实验生成的用户类别标签。", "latent attribute generator。"),
    "latent_environmental_consciousness_coef": _score(
        "合成环保意识系数",
        "实验中使用的合成环保倾向系数。",
        "latent attribute generator。",
        "按固定规格和随机种子生成。",
        limitation="纯合成实验变量，不能描述用户真实环保意识或心理。",
    ),
    "latent_epistemic_value_weight": _score(
        "合成认知价值权重",
        "实验决策中的合成认知价值权重。",
        "latent attribute generator。",
        "按固定规格生成并归一化。",
        limitation="纯合成实验变量，不能用于个人心理推断。",
    ),
    "latent_environmental_value_weight": _score(
        "合成环境价值权重",
        "实验决策中的合成环境价值权重。",
        "latent attribute generator。",
        "按固定规格生成并归一化。",
        limitation="纯合成实验变量，不能用于个人心理推断。",
    ),
    "latent_functional_value_weight": _score(
        "合成功能价值权重",
        "实验决策中的合成功能价值权重。",
        "latent attribute generator。",
        "按固定规格生成并归一化。",
        limitation="纯合成实验变量，不能用于个人心理推断。",
    ),
    "latent_health_value_weight": _score(
        "合成健康价值权重",
        "实验决策中的合成健康价值权重。",
        "latent attribute generator。",
        "按固定规格生成并归一化。",
        limitation="纯合成实验变量，不能用于个人心理推断。",
    ),
    "latent_emotional_value_weight": _score(
        "合成情绪价值权重",
        "实验决策中的合成情绪价值权重。",
        "latent attribute generator。",
        "按固定规格生成并归一化。",
        limitation="纯合成实验变量，不能用于个人心理推断。",
    ),
    "latent_social_value_weight": _score(
        "合成社会价值权重",
        "实验决策中的合成社会价值权重。",
        "latent attribute generator。",
        "按固定规格生成并归一化。",
        limitation="纯合成实验变量，不能用于个人心理推断。",
    ),
    "latent_hotel_class": _category("合成酒店偏好类别", "实验用酒店类别标签。", "latent attribute generator。"),
    "latent_travel_purpose": _category("合成出行目的", "实验用出行目的标签。", "latent attribute generator。"),
    "latent_gender": _category("合成性别标签", "实验用性别标签，不是观测身份。", "latent attribute generator。"),
    "latent_age": _category("合成年龄段", "实验用年龄段标签，不是观测年龄。", "latent attribute generator。"),
    "latent_education": _category("合成教育标签", "实验用教育程度标签，不是观测学历。", "latent attribute generator。"),
    "latent_monthly_income": _category(
        "合成月收入标签", "实验用月收入区间，不是观测收入。", "latent attribute generator。"
    ),
    "sample_source_scope": _category(
        "采集来源分组",
        "Video Source Scope（视频来源分组），表示采集入口而非视频语义类别。",
        "processed video 的 source_challenge_name 与抽样关联。",
        limitation="scope 只说明采集来源，不能解释为内容主题或用户偏好类别。",
    ),
    "in_base_sample": _boolean(
        "是否属于基础样本",
        "用户是否在 network augmentation 前的初始 Base Sample（基础样本）中。",
        "network sample audit。",
        limitation="false 可能表示用户通过网络补入 Final Sample，不代表质量更低。",
    ),
    "is_seed": _boolean(
        "是否为种子用户",
        "用户是否属于 Batch 0 固定曝光的 Seed Users（种子用户）。",
        "Base Sample 的 seed union 选择结果。",
        limitation="seed 是研究调度角色，不代表真实平台关键意见领袖。",
    ),
    "is_network_cohort": _boolean(
        "是否为网络传播识别组",
        "用户是否为 seeds 在 Historical Set 评论网络中的直接邻居。",
        "Historical Set 评论派生网络与 sample audit。",
        limitation="该 cohort 是真实 processed 用户的传播识别组，不是好友关系、合成用户或代表性随机样本。",
    ),
    "sample_role": _category(
        "样本角色",
        "用户在 Final Sample 中的 seed、network_cohort 或 ordinary 角色。",
        "network sample audit。",
        values="seed / network_cohort / ordinary。",
        limitation="角色用于研究抽样与比较，不代表用户的固定社会身份。",
    ),
    "historical_comment_network_weighted_degree": _count(
        "历史评论网络加权度",
        "用户在 Historical Set 评论派生网络中的加权连接总量。",
        "一级评论、回复和 @ mention 派生边。",
        calculation="汇总与用户相连历史互动边的权重。",
        limitation="它不是好友数或关注数，且受采集评论网络覆盖限制。",
    ),
    "latest_ranking_time_step": _count(
        "最近排序批次",
        "用户最后一次进入 ranking candidate evidence 的 Batch 编号。",
        "ranking_runtime_candidates.csv。",
        calculation="取该用户持久化 candidate evidence 的最大 time_step。",
        limitation="编号表示仿真顺序，不是现实时间。",
    ),
    "latest_ranking_position": _count(
        "最近排序名次",
        "用户最近一批全局候选排序中的名次。",
        "ranking_runtime_candidates.csv。",
        calculation="按 recommendation_score 降序、user_id 稳定破同分后得到。",
        limitation="名次只在同一批 eligible users 内可比较。",
    ),
    "selected_for_exposure": _boolean(
        "是否获得曝光",
        "用户是否在某批进入 Delivery Capacity（投放容量）并获得目标视频曝光。",
        "ranking runtime outcome。",
        limitation="false 可能是低于容量，不表示用户看到视频后忽略。",
    ),
    "base_network_relevance": _score(
        "基础网络相关性",
        "用户在 Historical Set 评论网络中的静态相关性信号。",
        "历史评论网络 weighted degree 与 P95 reference。",
        "min(1, log1p(weighted_degree) / log1p(P95_degree))。",
    ),
    "engaged_neighbor_count": _count(
        "已互动直接邻居数",
        "此前批次已对目标视频产生 like/comment/share 的 Historical Set 直接邻居数量。",
        "冻结到批首的 runtime action 与评论网络。",
        calculation="只计数此前批次成功互动的直接邻居；ignore 与 provider_failed 不计入。",
        limitation="它是仿真中的网络 evidence，不证明用户真实看见邻居行为。",
    ),
    "engaged_neighbor_signal": _score(
        "已互动邻居信号",
        "把已互动直接邻居数转换为动态排序信号。",
        "engaged_neighbor_count。",
        "min(1, engaged_neighbor_count / 3)。",
        limitation="只影响后续批次 ranking，不进入 LLM Prompt，也不证明真实社交影响。",
    ),
    "historical_tag_affinity": _score(
        "历史标签亲和度",
        "用户历史互动标签与 Target Video（目标视频）标签的匹配信号。",
        "Historical Set 用户标签与 target_video.hashtags。",
        "按项目声明的标签交集方法归一化。",
        limitation="只反映已观测标签重合，不等同于稳定兴趣或真实点击概率。",
    ),
    "recommendation_score": _score(
        "推荐排序分数",
        "决定同批 eligible users 相对排序的综合分数。",
        "三项冻结 ranking evidence。",
        "0.50 * base_network_relevance + 0.30 * engaged_neighbor_signal + 0.20 * historical_tag_affinity。",
        limitation="这是相对排序分数，不是曝光概率、互动概率或真实平台参数。",
    ),
    "exposure_time_step": _count(
        "曝光批次",
        "用户实际获得 Target Video 曝光的 Batch；未曝光时为空。",
        "ranking runtime outcome。",
        calculation="记录 selected_for_exposure 首次为 true 的 time_step。",
        limitation="编号表示仿真批次，不是现实发布时间。",
    ),
    "result_status": _category(
        "最终结果状态",
        "用户的 like/comment/share/ignore/provider_failed 或 below_delivery_capacity 结果。",
        "ranking runtime outcome 与 provider task。",
        values="like / comment / share / ignore / provider_failed / below_delivery_capacity。",
        limitation="below_delivery_capacity 表示未曝光；ignore 表示已曝光后不互动，两者不能混同。",
    ),
    "provider_status": _category(
        "Provider 状态",
        "Decision Adapter 是否未调用、成功或重试耗尽。",
        "runtime provider task。",
        values="not_called / succeeded / provider_failed。",
        limitation="状态只说明本次调用结果，不代表 provider 永久可用性。",
    ),
    "action": _category(
        "互动动作",
        "曝光后结构化 decision 的单一最可能 action。",
        "Decision Adapter 结构化输出。",
        values="like / comment / share / ignore / 空值。",
        limitation="这是仿真决策，不是观测到的真实用户动作。",
    ),
    "engage": _boolean(
        "是否互动",
        "结构化 decision 是否选择非 ignore 互动。",
        "Decision Adapter 结构化输出。",
        limitation="这是条件于已曝光的仿真结果，不是平台真实互动率。",
    ),
    "probability": _score(
        "互动倾向",
        "假设用户已获得 Recommendation Opportunity 后的模拟互动倾向。",
        "Decision Adapter 结构化输出。",
        "由已启用 Decision Adapter 根据允许输入生成。",
        limitation="它不是由真实曝光分母计算的点击率或互动率。",
    ),
    "reason": _text(
        "决策简短理由",
        "Decision Adapter 返回的安全简短理由。",
        "持久化结构化 decision。",
        limitation="理由是模型生成解释，不是用户真实陈述，也不包含 raw Prompt。",
    ),
    "confidence": _score(
        "决策置信度",
        "Decision Adapter 对本次结构化 action 的自报置信度。",
        "Decision Adapter 结构化输出。",
        "由 Decision Adapter 在 0..1 范围内返回。",
        limitation="自报置信度未经真实结果校准，不能解释为准确率。",
    ),
    "decision_source": _text(
        "决策来源",
        "标识产生结构化 decision 的 Adapter 来源。",
        "runtime decision metadata。",
        limitation="只记录允许的安全来源 token，不暴露 raw provider payload。",
    ),
    "provider_failure_type": _category(
        "Provider 失败类型",
        "重试耗尽时记录的安全失败类别。",
        "runtime provider failure allowlist。",
        limitation="只保留错误类别，不包含异常消息、凭证或 raw provider payload。",
    ),
    "report_path": _path("报告路径", "回到本次 report.html 的相对路径。", "FinalResearchReportWriter。"),
    "payload_path": _path("Payload 路径", "本次 payload v3 JSON 的相对路径。", "FinalResearchReportWriter。"),
    "json_path": _path("用户 JSON 路径", "完整允许字段用户 JSON 的相对路径。", "FinalResearchReportWriter。"),
    "manifest_path": _path("Manifest 路径", "artifact manifest 的相对路径。", "FinalResearchReportWriter。"),
}

_TARGET_VIDEO_SPECS = {
    "video_id": _text("目标视频标识", "唯一 Target Video（目标视频）的稳定标识。", "processed videos.csv。"),
    "source_challenge_name": _category(
        "目标视频来源分组",
        "目标视频的 Video Source Scope（视频来源分组）。",
        "processed videos.csv。",
        limitation="来源分组不是视频语义类别。",
    ),
    "source_challenge_rank": _count(
        "来源内次序",
        "目标视频在采集来源记录中的 rank。",
        "processed videos.csv。",
        calculation="直接记录 processed source rank。",
        limitation="rank 只表示采集记录次序，不是推荐质量或内容质量。",
    ),
    "caption": _text("目标视频文案", "Target Video 的清洗后 caption。", "processed videos.csv。"),
    "hashtags": _text(
        "目标视频标签",
        "Target Video 的清洗后 hashtags。",
        "processed videos.csv。",
        limitation="标签用于历史亲和度与 Prompt，不完整代表视频全部语义。",
    ),
    "creator_user_id": _text("创作者标识", "Target Video 的 creator user id。", "processed videos.csv。"),
    "video_url": _text(
        "目标视频链接",
        "指向真实采集 Target Video 的 URL。",
        "processed videos.csv。",
        limitation="链接可能受平台可用性影响；报告不会抓取或嵌入 raw 页面。",
    ),
}

_RUN_SPECS = {
    "sample_size": _count(
        "最终样本量",
        "真正进入正式 runtime 的 Final Sample 用户总数。",
        "ranking runtime summary。",
        calculation="统计 Final Sample 唯一 user_id。",
    ),
    "horizon": _count(
        "批次数",
        "Target Delivery Ranking runtime 的总 Batch 数。",
        "研究配置。",
        calculation="直接读取预声明 horizon。",
        limitation="批次数是仿真设计，不对应真实平台自然周期。",
    ),
    "random_seed": _count(
        "运行随机种子",
        "保证抽样和合成实验标签可复现的 seed。",
        "研究配置。",
        calculation="直接读取预声明 random_seed。",
        limitation="大小没有业务含义，只用于复现。",
    ),
    "delivery_capacity": _count(
        "每批投放容量",
        "Batch 1..29 每批最多投放 Target Video 的用户数。",
        "研究配置与 ranking runtime summary。",
        calculation="预声明为 Top K 容量。",
        limitation="容量不是互动概率或 action 配额。",
    ),
    "maximum_target_exposures": _count(
        "最大目标曝光数",
        "全部批次理论上最多产生的 Target Video 曝光数。",
        "horizon、seed batch 与 delivery capacity。",
        calculation="Batch 0 seeds 加后续批次各自 capacity 的理论上限。",
        limitation="理论上限不保证每批都有足够 eligible users。",
    ),
    "ranking_formula": _text(
        "排序公式",
        "逐轮计算 recommendation_score 的预声明 50/30/20 公式。",
        "ranking runtime summary。",
        limitation="公式权重是研究假设，不是从真实平台曝光日志训练得到。",
    ),
    "engaged_neighbor_formula": _text(
        "邻居信号公式",
        "把 engaged_neighbor_count 转成 0..1 动态信号的公式。",
        "ranking runtime summary。",
        limitation="公式描述仿真信号，不证明真实社交传播机制。",
    ),
}

_SAMPLE_SPECS = {
    "base_sample_count": _count(
        "基础样本量",
        "network augmentation 前按 source scope 形成的初始样本人数。",
        "network sample audit。",
        calculation="统计 Base Sample 唯一 user_id。",
    ),
    "final_sample_count": _count(
        "最终样本量",
        "真正进入正式 runtime 的最终样本人数。",
        "network sample audit。",
        calculation="统计 Final Sample 唯一 user_id。",
    ),
    "seed_count": _count(
        "种子用户数",
        "Batch 0 固定曝光的 Seed Users 数量。",
        "network sample audit。",
        calculation="统计 Final Sample 中 is_seed=true 的用户。",
    ),
    "network_cohort_count": _count(
        "网络传播识别组人数",
        "Final Sample 中 Historical Set 直接网络邻居的总人数。",
        "network sample audit。",
        calculation="统计 is_network_cohort=true 的用户。",
    ),
    "network_cohort_added_count": _count(
        "新增网络传播识别组人数",
        "不在 Base Sample、通过 network augmentation 补入的 Network Cohort 人数。",
        "network sample audit。",
        calculation="统计 is_network_cohort=true 且 in_base_sample=false 的用户。",
    ),
    "replacement_count": _count(
        "普通用户替换数",
        "为补入网络用户而从 Base Sample 等量移出的 Ordinary Users 数量。",
        "network sample audit。",
        calculation="与新增 cohort 等量替换，以保持 Final Sample 总量不变。",
        limitation="替换是研究设计，不表示被替换用户质量更低。",
    ),
    "base_source_scope_counts": _count(
        "基础样本来源构成",
        "Base Sample 按 Video Source Scope 分组的人数。",
        "network sample audit。",
        calculation="按 sample_source_scope 分组统计 Base Sample。",
    ),
    "final_source_scope_counts": _count(
        "最终样本来源构成",
        "Final Sample 按 Video Source Scope 分组的人数。",
        "network sample audit。",
        calculation="按 sample_source_scope 分组统计 Final Sample。",
    ),
}

_ROUND_SPECS = {
    "time_step": _count(
        "批次",
        "该组 ranking evidence 所属的 Batch 编号。",
        "ranking_runtime_steps.csv。",
        calculation="由 runtime scheduler 依次记录。",
        limitation="编号是仿真顺序，不是现实时间。",
    ),
    "eligible_count": _count(
        "候选资格人数",
        "批首尚未曝光、可参与本轮全局排序的用户数。",
        "ranking runtime state。",
        calculation="统计尚未处理的 eligible users。",
    ),
    "delivery_capacity": _count(
        "本批投放容量",
        "本批最多可选择的用户数。",
        "ranking runtime step。",
        calculation="取预声明 Top K 与本批 eligible 数的适用容量。",
        limitation="容量不是互动概率或动作配额。",
    ),
    "selected_count": _count(
        "本批选择人数",
        "本批进入 Delivery Capacity 的用户数。",
        "ranking runtime step。",
        calculation="统计 candidate selected=true。",
    ),
    "selected_user_ids": _text(
        "本批选择用户",
        "本批获得 Target Video 曝光的稳定 user_id 列表。",
        "ranking runtime candidates。",
        limitation="列表表示仿真投放，不是现实平台曝光日志。",
    ),
    "target_exposures": _count(
        "本批目标曝光数",
        "本批实际产生的 Target Video 曝光数量。",
        "ranking runtime outcomes。",
        calculation="统计本批 selected users 的目标曝光。",
    ),
    "decisions": _count(
        "本批成功决策数",
        "本批 Decision Adapter 成功返回结构化 decision 的任务数。",
        "runtime decisions。",
        calculation="统计 provider_status=succeeded。",
    ),
    "engagements": _count(
        "本批互动数",
        "本批 like/comment/share 的 action 数。",
        "runtime actions。",
        calculation="统计 action 属于 like、comment、share。",
        limitation="这是仿真 action，不是观测到的真实互动。",
    ),
    "ignored": _count(
        "本批忽略数",
        "已曝光后选择 ignore 的用户数。",
        "runtime actions。",
        calculation="统计 action=ignore。",
        limitation="ignore 与未曝光的 below_delivery_capacity 不同。",
    ),
    "provider_failed": _count(
        "本批 Provider 失败数",
        "本批重试耗尽的 provider task 数。",
        "runtime provider failures。",
        calculation="统计 provider_status=provider_failed。",
        limitation="0 只表示本批未记录失败，不代表 provider 永不失败。",
    ),
    "below_delivery_capacity": _count(
        "本批容量线下人数",
        "本批参与排序但未进入 Top K 的 candidate 数。",
        "ranking runtime candidates。",
        calculation="eligible_count - selected_count。",
        limitation="表示本批未曝光，不等同于已曝光后的 ignore。",
    ),
    "candidates_with_positive_engaged_neighbor_signal": _count(
        "正向邻居信号候选数",
        "本批 engaged_neighbor_signal 大于 0 的 candidate evidence 行数。",
        "ranking runtime candidates。",
        calculation="统计 engaged_neighbor_signal > 0 的 candidates。",
        limitation="统计的是 evidence rows，不是 selected users 或 actions。",
    ),
    "selected_with_positive_engaged_neighbor_signal": _count(
        "正向邻居信号入选数",
        "本批 selected 且 engaged_neighbor_signal 大于 0 的用户数。",
        "ranking runtime candidates。",
        calculation="统计 selected=true 且 engaged_neighbor_signal > 0。",
    ),
    "maximum_engaged_neighbor_signal": _score(
        "本批最大邻居信号",
        "本批 candidates 中最高的 engaged_neighbor_signal。",
        "ranking runtime candidates。",
        "取本批 engaged_neighbor_signal 最大值。",
    ),
}

_CANDIDATE_SPECS = {
    "ranking_position": _count(
        "候选排序名次",
        "该用户在本批全局 eligible candidates 中的名次。",
        "ranking runtime candidate evidence。",
        calculation="按 recommendation_score 降序、user_id 稳定破同分。",
        limitation="只在同一批候选集合中可比较。",
    ),
    "user_id": _text(
        "候选用户标识", "关联 candidate evidence 与 Research User 的稳定标识。", "ranking runtime candidate evidence。"
    ),
    "is_seed": _boolean(
        "候选是否为种子",
        "该 candidate 是否属于 Batch 0 Seed Users。",
        "network sample audit 与 runtime candidate evidence。",
        limitation="seed 是研究角色，不代表真实平台意见领袖。",
    ),
    "selected": _boolean(
        "候选是否入选",
        "该 candidate 是否进入本批 Delivery Capacity 并获得曝光。",
        "ranking runtime candidate evidence。",
        limitation="false 表示本批未入选，不表示已曝光后 ignore。",
    ),
    "base_network_relevance": _USER_FIELD_SPECS["base_network_relevance"],
    "engaged_neighbor_count": _USER_FIELD_SPECS["engaged_neighbor_count"],
    "engaged_neighbor_signal": _USER_FIELD_SPECS["engaged_neighbor_signal"],
    "historical_tag_affinity": _USER_FIELD_SPECS["historical_tag_affinity"],
    "recommendation_score": _USER_FIELD_SPECS["recommendation_score"],
}

_DIAGNOSTIC_SPECS = {
    "paired_ablation": _text(
        "成对排序消融",
        "同批冻结 evidence 下比较 full 与 no-network Top K 的诊断。",
        "ranking_diagnostics.json。",
        limitation="它不推进第二条完整 trajectory，也不是现实平台因果实验。",
    ),
    "weight_sensitivity": _text(
        "权重敏感性",
        "主方案、网络较弱和无网络三组权重的 Top K 稳健性对照。",
        "ranking_diagnostics.json。",
        limitation="只检查预声明的三组方案，不是参数优化或生产准确率评估。",
    ),
    "historical_top20_diagnostic": _text(
        "历史 Top20 诊断",
        "Holdout-safe ranking 与历史目标互动证据的稀疏对照。",
        "ranking_diagnostics.json。",
        limitation="缺少真实曝光分母，不构成生产推荐准确率。",
    ),
    "summary": _text(
        "排序诊断摘要",
        "Recommendation Signal Inclusion 与 Observed Effect 等同源汇总。",
        "ranking_diagnostics_summary.json。",
        limitation="摘要只描述本次持久化诊断结果，不证明真实平台因果效应。",
    ),
}


def _prefixed(prefix: str, specs: Mapping[str, _ExplanationSpec]) -> dict[str, _ExplanationSpec]:
    return {f"{prefix}.{field_name}": spec for field_name, spec in specs.items()}


_FIELD_SPECS: dict[str, _ExplanationSpec] = {
    **_USER_FIELD_SPECS,
    **_prefixed("target_video", _TARGET_VIDEO_SPECS),
    **_prefixed("run", _RUN_SPECS),
    **_prefixed("sample_comparison", _SAMPLE_SPECS),
    **_prefixed("ranking_rounds", _ROUND_SPECS),
    **_prefixed("ranking_rounds.candidates", _CANDIDATE_SPECS),
    **_prefixed("ranking_diagnostics", _DIAGNOSTIC_SPECS),
}


class ResearchExplanationCatalog(Mapping[str, FieldExplanation]):
    def __init__(self, explanations: Mapping[str, FieldExplanation]) -> None:
        self._explanations = dict(explanations)

    @classmethod
    def from_lineage(cls, lineage: Sequence[LineageEntry]) -> ResearchExplanationCatalog:
        declared = [entry.field_name for entry in lineage]
        duplicates = sorted({field_name for field_name in declared if declared.count(field_name) > 1})
        if duplicates:
            raise ValueError(f"lineage contains duplicate fields: {duplicates}")

        declared_fields = set(declared)
        supported_fields = set(_FIELD_SPECS)
        missing = sorted(declared_fields - supported_fields)
        unknown = sorted(supported_fields - declared_fields)
        if missing or unknown:
            raise ValueError(f"explanation catalog does not match lineage; missing={missing}, unknown={unknown}")

        explanations: dict[str, FieldExplanation] = {}
        for entry in lineage:
            spec = _FIELD_SPECS[entry.field_name]
            provenance_label, provenance_definition = _PROVENANCE[entry.provenance]
            usage = "；".join(_USAGE_STAGE[stage] for stage in entry.usage_stages)
            explanations[entry.field_name] = FieldExplanation(
                field_name=entry.field_name,
                chinese_name=spec.chinese_name,
                meaning=spec.meaning,
                source=f"{provenance_label}：{provenance_definition}{spec.source}",
                calculation=spec.calculation,
                value_range=spec.value_range,
                usage=usage,
                interpretation=spec.interpretation,
                limitation=spec.limitation,
            )
        return cls(explanations)

    def __getitem__(self, field_name: str) -> FieldExplanation:
        return self._explanations[field_name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._explanations)

    def __len__(self) -> int:
        return len(self._explanations)

    def as_records(self) -> list[dict[str, str]]:
        return [asdict(explanation) for explanation in self._explanations.values()]
