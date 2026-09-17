# GPT-P0 千人动态参数研究：接纳依据与待确认方案

日期：2026-09-17。来源：[父 Spec #256](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/256)、[审计 #258](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/258)、[方案 #259](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/259)。

状态：**旧判断接纳政策已由用户确认；下面的实验矩阵、新合同与 live 预算仍待确认。** 本文完成 #259 的决策材料，不宣称完成动态参数研究。基线 main `1856752d068d048ad439320fa8378776745e160c`；开始时工作区干净。本轮实验 Provider 调用 0、实际新增实验费用 0，无 Ralph、部署、新依赖、生产代码或持久化格式变更；未读取、打印或写入秘密。Canonical 网页不受本次独立方案影响。

## 1. 新接纳依据：保留原证据，改变研究接纳政策

用户在 2026-09-17 本任务明确决定：复用旧 1,800 条 GPT-P0 判断；接受冻结输入及历史实现重建客户端请求的证据，披露采集时间差异和不可观测服务端版本；不再要求证明隐藏服务端上下文完全相同，也不授权全量重采。

因此旧 1,800 条在**历史重建客户端条件下获准复用**，每消息 600 条，拒绝/重复/冲突均为 0。物理缺口每消息 400 条，共 1,200；完整库目标是 3,000 unique pairs。未来补采的客户端相容性与当前模型资格仍须核验，这不撤回旧判断接纳。旧审计 `accepted=0 / undetermined=1800` 是当时政策的历史结果，不是数据作废。原审计及所有清单保持原 bytes，不回填、更名或修改旧 disposition；新库未来逐条引用旧 judgment_id、origin 和本接纳依据。

显式证据链（仓库根目录 `/Users/liuqingyuan/work/llm-abm-marketing-sim`）：

| 对象 | 仓库内路径 | SHA-256 |
|---|---|---|
| Evidence | `outputs/01a08bb3-1446-7f51-8933-cd49b50e9ccb/four-model-final-20260912-verified/Evidence.json` | `a7407bf355d6049af8667a69b540fe2b29591d7f8e7ef71d6cb08d01fee72b17` |
| Plan | `runs/concurrent-robustness-recovery-formal-20260909T213305Z/plan.json` | `2d64026ce755a5a5c3e8dd42f6c74add7dc1435b42adef3cbc47dac030da9b16` |
| 逐条重建清单 | `runs/gpt-p0-judgment-reuse-audit-ticket-258-20260917-direct/judgment_evidence_checklist.jsonl` | `4135ccb474cbfa0fbc8a8c214afcfcbd156186faf8a753dc536725ba6ba1f814` |
| 覆盖清单 | 同目录 `pair_coverage_checklist.csv` | `8253b64c99871b9011c00f1927dce0bd47833859fe231d16c962a5e5895a4abe` |

完整 source/control/bundle、sample/graph/message 哈希继续以[原审计](gpt-p0-judgment-reuse-audit-20260916.md)与其 audit.json 为准。本次只沿该显式 lineage 聚合预算，不重复扩大审计。历史采集窗口为 `2026-09-11T17:52:17Z`—`2026-09-11T20:37:35Z`；未来补采另存时间、模型观测身份与 client condition，服务漂移作为限制而非可证明消除的变量。最终记录每条路径旧/新判断来源比例，帮助识别时间混杂，但不把来源差异解释为因果时间效应。

### 补采前核验清单

- 同一 1,000-user sample、effective graph、3-message snapshot、P0 模板与 structured schema；逐 pair 核对全部 client messages（角色、顺序、内容）及其他发往服务端的字段，而非仅模板 hash。
- 请求 `openai-codex/gpt-5.6-sol`，wire/response 模型均精确为 `gpt-5.6-sol`；route=`pi_openai_oauth_subscription`、wire=`pi_model_runtime`。任何真实差异先报告，不悄悄换路由或模型。
- reasoning=`low`，thinking mode/budget=null；completion ceiling=256，历史为 application-fail-closed，不把它说成可保证的服务端计费上限。`temperature/top_p/seed` 继续省略；timeout=30s、max_retries=2、backoff=0.5s，每 pair 最多 3 attempts；新的全局预算仅收紧停止，不改变单次请求内容。
- 当前仓库相关实现仍与审计绑定实现一致，可离线比较；当前安装的 Pi runtime/实际 entitlement/response 身份须在授权后资格验证。不得把历史资格等同当前已通过。
- **重要键区别：** `DecisionInput.cache_key()` 包含 `time_step`，不是跨时间步判断库的复用键。保留完整 DecisionInput hash 作审计来源；拟用完整 LLM 可见 client messages + schema/model/route/wire/request settings 的 canonical hash 作资格键。P0 当前 renderer 使用静态 profile/message 和中性 peer/platform context，时间步不直接进入 P0 文本；曝光分数/反馈只驱动排序。实施验收仍须覆盖 3,000 pairs、不同批次及反馈状态的完整渲染不变性；一旦 LLM 可见输入改变，停止固定库路径，不能忽略字段强行命中。此键与格式目前仅提案，未实现。

## 2. 简短推荐：21 配置 × 100 realization seeds

当前实现核对：`concurrent_message_experiment.py::_rank_message_candidates` 为
`score = wN * base_network_relevance + wF * min(1, engaged_neighbors / h) + wM * normalized_message_user_fit`，基准 `(0.50,0.30,0.20), h=3`。`concurrent_robustness_study.py` 固定 holdout-safe log1p/P95、shared seed launch、full-precision score 与 user_id tie-break。

建议以下 7 个单纯形点，**每个均交叉 h∈{1,3,6}**，共 21 配置；基准是 B/h3。权重顺序是网络/反馈/内容匹配。

| 点 | wN | wF | wM | 含义 |
|---|---:|---:|---:|---|
| B | 0.50 | 0.30 | 0.20 | 原基准 |
| N+ F− | 0.65 | 0.15 | 0.20 | 反馈向网络转移 0.15 |
| N− F+ | 0.35 | 0.45 | 0.20 | 网络向反馈转移 0.15 |
| N+ M− | 0.65 | 0.30 | 0.05 | 内容向网络转移 0.15 |
| N− M+ | 0.35 | 0.30 | 0.35 | 网络向内容转移 0.15 |
| F+ M− | 0.50 | 0.45 | 0.05 | 内容向反馈转移 0.15 |
| F− M+ | 0.50 | 0.15 | 0.35 | 反馈向内容转移 0.15 |

所有权重非负且和为 1。此为受约束、局部但较宽的联合扰动，阈值交叉可观察交互；不声称覆盖整个单纯形、全部非线性或全局 Sobol 指数。h=1 是快速饱和，h=6 是较缓反馈；0.15、1/3/6 都是研究者预声明设定，不来自平台估计。未纳入纯单信号极点或关闭反馈，若结论需扩展范围另行确认。

固定其他条件：仅 GPT/P0；原 1,000 用户、图、消息、P95 normalization、Batch0 同一 20 shared seed users、每消息 Top20、30 batches、single exposure；campaign-positive 集合按 distinct user 去重。每消息 600 exposures，每路径 1,800，不将 3,000 bank size 当曝光分母，也不把 campaign 去重误解为每用户最多看一条消息。

建议 seeds 为整数闭区间 **2026091700..2026091799**（100 个，结果前声明）。每配置从 Batch0 初始化独立状态，同批反馈冻结，全批 barrier 后只提交 realized-positive users，下一批生效。每路径自己排序→曝光→bank 判断→realization→commit；禁止继承其他路径候选/反馈或做冻结反馈重排序。Provider ignore 不抽签；正向只实现其选择的动作。

共同随机数拟定义为 `u = first53bits(SHA256(canonical_json([rule_version, frozen_bank_identity, seed, user_id, message_id]))) / 2**53`。rule_version 显式新版本；bank identity 是内容身份，独立于磁盘路径/配置/批次/访问顺序。重复 seed/pair 的 draw 在不同配置相同，不同 seed 改变 draw；不能以更换 source 路径冒充 seed。旧固定 `20260823` 与旧 realization/manifest 合同不放宽。可额外保留旧路径审计复现，不能把它混入 100-seed 样本。

总量：2,100 条离线路径，63,000 个 barriers，3,780,000 个 exposure 实现；补库后新增 Provider 请求为 0。这是逻辑计算量，不是实测运行时间或已批准实验。

## 3. 分析和判据提案

主要比较预声明为 **message_1−message_2、message_1−message_3、message_2−message_3**，不看结果后挑“最佳消息”。令每完整路径消息互动率 `r_m = realized_positive_m / 600`；`D_c,s,ij = r_i−r_j`，同 seed 配置效应 `Δ_c,s,ij = D_c,s,ij−D_B3,s,ij`。

- 建议实际意义界值 **ε=0.02（2 个百分点）**：以每消息 600 曝光计，对应单个率约 12 次互动的尺度，是研究者判断，不继承 v15 的统计合同或文学证明。
- 每配置报告 D 的均值、seed SD、MCSE=`SD/√100`、模拟分位数、正/负/近零比例；对 Δ 使用同 seed 完整路径配对。比例只是模拟描述，避免以 95/100 次同号当作充分推断。
- 方向：D 的区间完全高于 +ε 或低于 −ε 才称有实际方向；完全位于 [−ε,+ε] 称近零；其他称未定。与基准比较逐消息对，基准未定时不宣称“方向保持”。
- 幅度：所有非基准配置 Δ 的区间均包含于 [−ε,+ε] 才支持该消息对在**所测配置内**幅度等效；明确反向或超界报告敏感；区间交界报告证据不足。“不显著”不等于“不敏感”。方向与幅度分开给结论。
- 固定 100 seeds，不根据结果自动增加或挑选种子。建议 Monte Carlo 精度目标：主要估计点的普通 95% 均值区间半宽 ≤0.005（0.5pp）；未达标如实报告精度不足，增加种子须另行确认。100 是起始工程预算，不保证达到目标。
- 推断单位是**完整 seed 路径向量**。同时检查 63 个 D 与 60 个非基准 Δ，建议以 123 个均值的 Bonferroni 校正双侧 t 区间作保守的整体判据，df=99，临界值 `t_(1−0.05/(2×123),99)`；同时列普通区间与 MCSE。近似 t 区间依赖独立 seed 的均值近似，不能声称有限样本严格保证。曲线带为点态模拟分位数，不作全时程显著性判断。
- 曲线展示 30 批每消息累计 realized rate（分母每批累计 20×批数）、累计数量和三组消息差值；另列各配置终值、Δ、方向状态、旧/新判断曝光占比、campaign distinct-positive-users。CSV、曲线与报告须由同一闭合 Evidence 计算，不抄写数据。

自适应曝光不是独立配对用户样本；共同随机数只配对完整运行，不能把两配置选出的用户直接拼成 IID 配对。区间仅覆盖所模拟 realization 随机性，不涵盖 LLM 重采样、服务漂移、样本/图抽样、心理测量误差或真实平台因果效应。固定 LLM 判断可能低估总体不确定性；本研究检验条件稳健性，不预设“不敏感”。

## 4. 补 1,200 条的预算草案（尚未授权）

**日期依据 2026-09-17；只沿已有审计 origin 聚合 1,804 个 settled attempts。** 旧账本不是新授权，也不是当前余额查询。

| 历史 GPT-P0 项 | 值 |
|---|---:|
| 成功 judgments / 物理 attempts / 已结算 retryable failures | 1,800 / 1,804 / 4 |
| 有 response / usage complete | 1,800 / 1,800 |
| input / output / total tokens（已报告 responses） | 1,769,793 / 224,804 / 1,994,597 |
| cached input tokens | 0 |
| 成功 response 单次 input / output 范围 | 967–995 / 93–228 |
| subscription nominal USD 合计 | 15.593085 |
| 单次 nominal USD 范围 | 0.007740–0.011785 |
| provider_fee_cny | 全部 null（不是已证明零扣款） |

四个无 response 的失败各无 token/cost 值；以上是已知 response 小计，不将未知成本填 0。账本语义为 `subscription_quota_with_nominal_usd_reference`。旧成功样本线性外推补采 1,200 条：input≈1,179,862、output≈149,869、total≈1,329,731 tokens；名义费用参考 **$10.395390**，按历史单次最小/最大乘 1,200 的情景范围 **$9.288–$14.142**。这不是预测置信区间、报价或实际充值额；缺失组合与旧曝光组合不一定同分布。

建议可执行授权边界：

| 项目 | 推荐上限/动作 |
|---|---|
| 模型/路由 | 上节同一 GPT-5.6 Sol / Pi OpenAI OAuth subscription；拒绝替换路由 |
| 新增合格成功 | 1,200 个缺失 pair，已成功不重发；旧 1,800 不重复采集 |
| 资格验证 | 最多 2 次物理请求，计入总账但不充当 bank 判断；失败即停，不隐式重试 |
| 补采请求 | 1,200 次首发＋最多 60 次重试，共最多 1,260 |
| 总 physical cap | **1,262**，资格/失败/重试全计；调用前检查剩余 budget |
| 单 pair 重试 | 最多 2 次（含首发最多 3 attempts），同时受全局 60 重试限制 |
| 并发 | 1，避免在停止信号后继续放大 in-flight |
| 失败规则 | 仅已结算且明确 retryable 的失败可重试；unknown/usage不闭合/模型漂移/quota exhausted 立即停止；不自动重发 unknown |
| 金钱边界 | 仅现有订阅包含额度，**额外充值/购买额度/付费 API 支出授权上限为 0**；先确认实际账户已关闭额外付费消费或存在可验证硬限额，再运行；额度不足停机，不自动充值或兑换重置 |
| 独立输出目录 | `/Users/liuqingyuan/work/llm-abm-marketing-sim/runs/gpt-p0-bank-topup-20260917-authorized-01/`（预留，尚未创建/执行） |

按历史单次 nominal 参考估计，1,262 请求的同分布均值情景约 **$10.932485**，最小/最大情景 **$9.767880–$14.872670**；建议名义成本预警线 $15，但它不是硬美元支出保证。256 completion ceiling 是应用层拒绝超限策略，不能保证已经发生的服务端生成或扣款上限。

[OpenAI Codex 官方价格与额度说明](https://chatgpt.com/codex/pricing/)（2026-09-17 读取）说明订阅额度共享且 credit 消耗依模型/任务变化，页面列 GPT-5.6 Sol 计划范围；这些产品消息范围不能换算成 Pi 的保证请求余额。当前具体订阅档位、余量、credit 单价/付费开关与实际账单未查询，故实际额外费用和可完成请求数未知。建议授权选择“仅现有包含额度、额外付费0、触顶即停”，而不是保证 $15 可买到这批结果；如用户希望付费继续，先另行获取该账户可核验计费依据并确认硬上限。

## 5. 待确认的最小工程合同（不在本 Ticket 实现）

沿父 Spec 的 Study→私有 Runtime Kernel→Realization→Evidence→Report 接缝，不新建调度器，不发布 per-batch API。建议批准一个 Study 拥有的独立参数研究高层入口及版本化研究合同，明确与旧 fresh/no-cache Formal 路径隔离；确切签名/字段在实施设计审查时冻结。

拟议持久化采用现有 JSON manifest＋JSONL judgment/attempt/path events＋CSV summaries 的格式族（均为新研究版本，**尚未批准**）：

- manifest 绑定 sample/graph/messages、输入条件、新接纳依据、固定库内容 hash、矩阵、种子、指标/预算及显式 source lineage；不靠“最新目录”。
- bank 每条绑定 pair、全 client request identity、decision、观测模型、origin、采集时间、旧/新来源；缺失/重复/冲突 fail closed。旧 origin 指针复用已有 judgment，避免重写旧 evidence；新 attempt 账本独立保存请求状态和 usage/nominal/实际费用的 nullable 值。
- 版本化 draw 身份使用固定 bank content identity；每路径保存曝光/判断引用/实现/反馈/barriers，让 Evidence 可独立重算，Report 只消费已闭合 Evidence。
- budget/resume/unknown stop、完整输入相等、独立动态反馈和旧合同不变，均从 Study 高层入口测试。既有固定 seed 合同不能被直接松绑。

本阶段 Mermaid Gate：不需要新图，纯研究方案与预算文档；引用 #256 已有 8 张提案图。未来实施涉及新合同，必须先完成其具体设计 Gate。无新依赖；无删除；无部署授权推定。

### 一次集中确认

1. 是否批准上面的 **21 配置、100 seeds、三组消息对比、2pp 界值与 0.5pp MC 精度目标、123 均值校正区间规则**？
2. 是否批准上述 **Study 独立高层入口/版本化 manifest＋bank/attempt/path 格式和新 seed 身份方向**，进入具体签名/字段冻结后实施（不放宽旧 Formal 合同）？
3. 是否授权同模型/路由补 **1,200 成功、总 cap 1,262、资格 cap 2、重试 cap 60、单 pair retries≤2、并发1、仅现有包含额度且额外付费0**，使用指定独立目录；付费开关/硬限额未核实时保持停机？可单独批准离线设计而不批准 live。

后续顺序：确认合同→离线实现及高层验证→授权后资格与客户端一致性核验→缺口补采和账本闭合→固定库 2,100 动态路径→表格/曲线/限制与独立报告。Canonical 集成与部署仍须另行明确确认。

## 6. 原始文献与解释边界

- [Burke (2002), Hybrid Recommender Systems: Survey and Experiments](https://link.springer.com/article/10.1023/A:1021240730564)：原文摘要讨论混合推荐的组合思路；为组合信号提供背景，不证明本项目线性公式或 0.50/0.30/0.20。
- [Pazzani & Billsus (2007), Content-Based Recommendation Systems](https://doi.org/10.1007/978-3-540-72079-9_10)：内容特征与用户偏好匹配提供理论背景，不验证六维合成标签、余弦变换或心理真实性。
- [Bakshy et al. (2012), Social Influence in Social Advertising: Evidence from Field Experiments](https://arxiv.org/abs/1206.4327)：现场实验区分社交定向关联与展示社交线索的影响。本项目历史评论图不是好友图，P0 不展示动态邻居线索，故这里是推荐排序反馈假设，不是对论文社交影响机制的复现，更不证明饱和阈值 3。
- [Saltelli et al. (2019), Why so many published sensitivity analyses are false](https://doi.org/10.1016/j.envsoft.2019.01.012)，[作者预印本](https://arxiv.org/abs/1711.11359)：强调合理探索输入空间；支持对受约束权重联合扰动及阈值交叉的动机，但不使有限 21 点成为全局敏感性保证。

以上已核对出版社摘要/作者摘要；未声称全文逐页复核。P95、Top20、30 批、阈值与权重均为当前模型的简化操作化，不是抖音算法参数。结论条件于固定样本、图、消息、GPT/P0及接纳的固定判断库，不推广到其他模型/Prompt或 36,400 用户。

## 7. 本轮验证与复现

本轮只完成文档、显式 ledger-origin 预算聚合及聚焦回归；原审计 14 项测试的具体命令与本轮结果见独立 `runs/gpt-p0-parameter-plan-ticket-259-20260917/VERIFICATION.txt`。全仓测试未重跑，全仓既有 Ruff/类型检查问题未处理，不声称全仓绿色。真实补采、动态矩阵路径与曲线尚未执行。

可复用离线续接提示：

```text
从 main 和 #256/#259 接续；先读本接纳方案及明确确认评论。保持旧审计 bytes 不变。
仅对已批准矩阵/seed/合同实现 Study 高层路径；完整客户端输入不等则停止。
没有独立 live 授权不调用 Provider；缺失判断不替换为 ignore/mock。
用固定判断库使每路径曝光、实现和反馈独立推进；报告真实账本和模拟随机性范围。
```
