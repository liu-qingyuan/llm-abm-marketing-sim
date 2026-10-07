# 十话题四模型×P0–P3最终交付与验收

**结论：16条件全部完成，28,800次实际曝光、480个批次屏障及判断来源/统计复验通过。** 本轮现金费用未知；没有把失败/unknown填成判断。论文与canonical未修改或部署。

Worktree：`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim`；分支：`codex/ten-topic-full-pool-replay`。独立运行目录：`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/runs/ten-topic-four-model-20261007`。

## 口径与真实来源

最终正式数据集实际十个采集话题合并历史网络（不是平台所有话题），排除holdout视频`7328592728139353363`；4,211历史视频、50,604历史评论，39,779去重边、累计权重52,587。P95在36,400 eligible用户上复算为5，边/度数/邻居与生产输入逐项一致。

十个实际话题：绵阳锦江国际酒店、锦江之星、锦江之星品尚、锦江之星海口、锦江之星酒店、锦江都城酒店、锦江都城酒店吉安、锦江酒店、锦江酒店中国区、锦江酒店华西区。

按原规则独立重建新基准1,000人，与前阶段已验收集合一致；新旧样本重合646/1000，共同初始seed用户20人。三消息、每消息每批20人、30批，每条件1,800曝光；推荐权重0.50/0.30/0.20、饱和阈值3。排序/并列、种子优先、逐对去重、四种互斥行为和三消息完成后的反馈屏障全部从原始路径重建核对。

行为seed仅20260823，不套用参数研究的100seed。保留旧四模型的Source/User/Message SHA53-bit抽样锚点`1d31f0d24f8e77b6081a4c327b5e5653dcea071cd71100a77494901acd338b01`；与参数研究抽样规则不同，未静默迁移。输出目录、新网络身份、执行顺序不改变逐对抽样。

| 研究模型 | 新请求标识 | 实际观测标识 | 既有通道 |
|---|---|---|---|
| GPT-5.6 Sol | openai-codex/gpt-5.6-sol | gpt-5.6-sol | Pi/OpenAI OAuth订阅 |
| Kimi | kimi-k3 | kimi-k3 | 官方Moonshot |
| Gemini 3.1 Pro | gemini-3.1-pro | gemini-pro-agent | 原Antigravity网关 |
| DeepSeek V4.1 Flash | deepseek-flash | deepseek-flash | 原官方DeepSeek |

DeepSeek原V4已退役，V4.1请求更新来自用户显式授权；旧V4结果不追溯改写。Kimi统一作为一个研究模型显示，历史路由逐条保留；旧33条订阅记录因请求条件不同不直接复用。Gemini观测的是网关alias，不是原生Google模型版本证明；隐藏effective context/上游行为仍不可观测。

## 16条件新旧对照

互动率分母每条件1,800次曝光，以下均为单次实现的整数互动数/比例，不是100seed均值。

| 模型 | 模板 | 旧互动数 | 新互动数 | 旧率 | 新率 | 差值(pp) |
|---|---|---:|---:|---:|---:|---:|
| DeepSeek V4.1 Flash | P0 | 607 | 1047 | 33.722% | 58.167% | +24.444 |
| Kimi | P0 | 708 | 618 | 39.333% | 34.333% | -5.000 |
| Gemini 3.1 Pro | P0 | 916 | 848 | 50.889% | 47.111% | -3.778 |
| GPT-5.6 Sol | P0 | 1190 | 1098 | 66.111% | 61.000% | -5.111 |
| DeepSeek V4.1 Flash | P1 | 734 | 986 | 40.778% | 54.778% | +14.000 |
| Kimi | P1 | 719 | 619 | 39.944% | 34.389% | -5.556 |
| Gemini 3.1 Pro | P1 | 913 | 836 | 50.722% | 46.444% | -4.278 |
| GPT-5.6 Sol | P1 | 1171 | 1087 | 65.056% | 60.389% | -4.667 |
| DeepSeek V4.1 Flash | P2 | 652 | 1138 | 36.222% | 63.222% | +27.000 |
| Kimi | P2 | 828 | 730 | 46.000% | 40.556% | -5.444 |
| Gemini 3.1 Pro | P2 | 1093 | 984 | 60.722% | 54.667% | -6.056 |
| GPT-5.6 Sol | P2 | 1222 | 1127 | 67.889% | 62.611% | -5.278 |
| DeepSeek V4.1 Flash | P3 | 609 | 1008 | 33.833% | 56.000% | +22.167 |
| Kimi | P3 | 730 | 606 | 40.556% | 33.667% | -6.889 |
| Gemini 3.1 Pro | P3 | 949 | 872 | 52.722% | 48.444% | -4.278 |
| GPT-5.6 Sol | P3 | 1257 | 1186 | 69.833% | 65.889% | -3.944 |

逐消息、S1–S3虚拟类别、四类行为及传播曲线见`formal-report/`全部CSV/SVG。新旧差异共同包含网络、样本、补采服务时点和DeepSeek版本变化，不解释为单一网络/纯模型因果效应或普遍稳健。

共同Batch0仅20个seed用户×3消息；沿原协议500次、seed20260809用户block bootstrap做配对描述。自适应后续路径不作曝光独立重复的binomial推断。独立统计程序直接重读原始路径，核对1,664行表/曲线/旧新对照及384行配对bootstrap；未复用生产summarize/percentile函数，仅共享Python random算法与声明seed。

## 判断复用、调用与费用

实际曝光判断库28,800条：旧四模型精确匹配复用8,974条，已验收GPT/P0库复用1,800条，新增成功正式判断18,026条。合计复用10,774条。完整48,000候选库没有预先补齐，`full_candidate_bank_closed=false`不代表传播路径不完整。

物理请求18,089/29,143：正式成功18,026＋资格成功4＋已知失败42＋unknown17；无inflight。资格共5次（旧DeepSeek身份不合格1次也真实留账）。每模型/模板复用量、逻辑输入签名、物理请求、成功、已知失败、unknown与费用列在`formal-call-ledger/model-template-calls-costs.csv`及`final-bank/manifest.json`。没有把100行为seed或十话题乘入模型判断预算。

已知名义参考消耗USD19.794592，仅本任务记录的订阅参考字段；缺失名义消耗、CNY provider-fee字段、实际现金费用均未知，不能按零或用余额差额推算。用户授权无现金上限，但物理上限始终29,143；隐含网关上游调用不可观察，物理计数明确为客户端请求意图/派发。

原17条unknown状态保留，每条都链接另外真实成功的同输入采集，详见`UNKNOWN_RECOLLECTION_TRACE.json`。Gemini原三次耗尽后，新批次单独标识、每批最多三次；老请求/旧contract字段不改写，新运行采用独立contract及用户补采授权。已知无效Kimi响应不改为unknown，显式补采保留1024上限和原retryable=false。

## 修复、验收与保留

- 本轮发现14次未等待Retry-After的早期请求，记录与费用状态原样保留；已加派发前冷却门禁并独立检查2,282条新策略意图。失败未进入正式判断库。
- 显式中断后仅在PID及tool handles实际缺失、无响应字节时追加3条Kimi unknown；原journal bytes保留为prefix，另外采集成功，不因观察超时重启。
- Kimi一次真实响应decision_text为空、output_tokens=1024且usage完整；不合格响应保留。持久化无finish_reason，截断仅为推断，未提高token上限，显式同设置采集已成功。
- 新增独立完整输入/请求条件、源模型/hash、顶层网络来源与matrix检查；原成功响应18,030条重新用std JSON解析并与记录决策逐字段相等。
- fresh raw-CSV graph/sampler使用前阶段独立验收实现，而非生产graph/sampler；共享用户trait加载、cohort对照、prompt renderer/message-fit边界已在各证据明确，不把同一生产kernel重复执行称独立。
- 84项相关离线测试通过；src/tests/scripts全部py_compile通过；相关脚本Ruff F通过。全仓Ruff42项与原项目路径/代码/位置/消息完全一致，本轮新增0。
- 19个旧四模型文件、前阶段16个GPT最终对象、全部2,800条旧GPT路径及9个全样本产物hash不变；原项目main HEAD仍bdedc9f。
- 验收/重算Provider调用0；本任务实际采集请求18,089。运行读取既有本机凭证用于用户授权调用，未打印或提交秘密；raw响应/大用户JSONL及私钥不提交Git，费用原始来源快照本机mode0600。

实际命令、literal输出与exit status见`FINAL_COMMANDS.json`、`VERIFICATION_FINAL.txt`；最终绝对路径/hash见`DELIVERY_INVENTORY.json`。

## 未执行/遗留及发布判断

- 原全仓库synthetic历史recovery测试曾80分钟未结束，本轮未盲目重复；原consumer重放192秒被终止也不写成通过。采用独立一遍真实origin/receipt校验，覆盖范围明确不同，旧source formal_evidence_closed=false字段保留。
- pyright本机缺失（原exit127），未新增依赖；这是静态检查缺口，不影响已执行的路径/统计核验。
- 部分旧producer请求条件由受保护合同重建，非全部原生wire metadata；前期新调用也未存全部HTTP body。可核对客户端输入、适用合同及真实响应；不虚称隐藏网关上下文或上游原生版本已验收。
- 未做vendor invoice现金对账，费用未知；未把unknown费用归零。
- 论文与canonical发布、公网交互/下载、immutable release集成尚未执行（用户明确留待统一发布）。

**用于论文：可作为本次声明的单seed观察性16条件结果，必须保留上述模型版本/网关/服务时点、样本和source证据限制。没有未解决的数据真实性、实际路径完整性或统计计算问题。正式发布：尚未进入统一release/deployment验收，不能把本目录直接当成canonical release。**

待同步：实验方法与十话题/P95/样本说明、DeepSeek V4.1及实际观测模型/路由；16条件/消息/类别结果和曲线；复用/unknown/费用与source表；完整下载清单及独立验收证据。之后再更新拥有该知识的Module/contract并做统一发布，非手工改远端HTML。
