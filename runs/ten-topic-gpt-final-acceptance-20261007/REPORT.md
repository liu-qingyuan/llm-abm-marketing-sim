# 十话题 GPT/P0 两项研究：最终独立验收

## 结论

**正式判断库、全部2,800条路径及所列统计结果验收通过，无影响真实性、路径完整性或统计正确性的未解决问题。** 本轮实际Provider调用 **0**，未执行新模型判断或新实验，未修改原始账本、判断、路径或报告。验收goal的完成指验收工作完成，不把未执行的全仓库/发布检查写成通过。

当前接手HEAD为4769dee7823b13d498f8d387cec421ef5285ee72，分支codex/ten-topic-full-pool-replay；开始时无tracked工作区改动，仅既存.venv链接。验收源代码另存本目录，不追溯改写正式成果。旧结果、原main和前阶段全样本保护hash一致。

## 通过项及证据

| 范围 | 独立计算结果 |
|---|---|
| 判断库 | 17,520个唯一(user,message,完整请求条件)；原两库逐条匹配复用10,308；真实新成功7,212；旧判断内容和来源不改写 |
| 账本 | 5段原始hash链、intent/settlement、实际gpt-5.6-sol/usage和256 ceiling、资格、来源和并发逐条校验；物理请求7,219 |
| unknown | 三条原unknown与三条用户明确授权的新成功响应分离；每精确输入仅新发一次；unknown账本/未知消耗保留，未把旧请求写成成功 |
| 费用 | 序列化浮点转Decimal小计47.0218439999999999842 USD，报告六位数47.021844 USD一致，差1.58e-17来自浮点序列化；3次未知消耗与现金账单均不当零 |
| 网络 | 从原videos/all_comments独立建无向comment→creator、reply→parent、mentions边，空ID/自环排除、权重累计，独立核查唯一comment_id与holdout；39,779边、52,587总边权；eligible分母36,400含零度，P95=5；图identity与正式十话题lineage相符 |
| 用户及样本 | 原始历史信号重算Activity/Local阈值/权重；Global逐CSV核对保持不变；独立种子Top10并集、邻居边强度并列/排序、话题配额及原shuffle seed重构全部7臂 |
| 路径 | 原21参数×100seed=2,100，原7臂×100seed=700；每路径1,800曝光/30完整屏障；共5,040,000曝光/84,000屏障 |
| 路径规则 | 自行计算每批eligible全集排序、user_id tie、种子优先、每消息600唯一曝光、原first53抽样/互斥行为和三消息全批反馈；未调用生产Kernel/ranking/selector/verifier |
| 2,700接纳来源 | 全部原ready-scope路径hash、payload和身份逐字段匹配；各scope实际3,000输入及判断hash与最终库精确一致；完整路径trace重新推导，而非只凭文件数/通过标记 |
| 最后100 | local_p99_rebuilt最后100路径没有旧scope复用标记；从完整库与实际三条新响应再独立推导全部终态和屏障 |
| 统计 | 从逐seed终态复算表、原始/均值累计曲线、配对seed、MCSE/95% CI；另写regularized beta连续分式计算Student-t分位数，不使用生产统计函数；df99、参数家族123、指标家族120与原协议一致 |
| 重复性 | Local weights fixed/rebuilt100条payload相同；两研究共享baseline100条相同。它们不是额外独立重复证据 |
| 样本重叠 | 新旧基准646/1000；Local p99 rebuilt与新基准23/1000；报告同时单列样本组成，不把网络/样本/指标/服务时点混合差异称为纯指标因果效应 |

基准67.196%→62.278%为**100行为seed下每路径1,800曝光互动率的均值**，互动=like+comment+share，ignore计入曝光分母。独立精确值0.6719611111111111→0.6227777777777778。新参数终点均值范围0.6227777777777778–0.6584777777777778，即62.278%–65.848%。每消息分母600；“all”分母1,800；不是将100个seed当100次模型判断。

## 共用部分与独立性边界

共用：冻结原数据/cohort读取与类型、原profile→P0客户端渲染器（协议拥有者）；数据和renderer字节/输入指纹核对，原消息向量及latent维度作为数据读取。未把这些共用读取器称为独立实现；客户端condition SHA由本验收按协议自行计算。

独立重写：原CSV建边、历史计数/likes、percentile及代理分数、七臂权重/归一化、种子/邻居/配额采样、ledger hash/状态/响应来源、Decimal费用、fit cosine、eligible排序、seed-first选择、draw/action/barrier、终态统计和区间。未调用fast_paths.Campaign.verify、生产run_research/report_research、bank_union.validate（其会写closure），也未重新生成传播实验。此前同一个fast_paths verifier用于执行阶段和报告阶段的两次调用，本轮没有把它们当独立验收。

响应证据边界：未保留raw Provider wire payload（项目规则）；真实性依现有正式规范化observed-model/usage与hash-linked settlement来源验证，不等同服务端第三方签名认证。本轮未访问远端响应历史/发票、未发起任何额外Provider请求。

## 实际命令与结果

工作目录为既有worktree，命令全部关live gate，读取历史模块时禁写bytecode。

- `LLM_ABM_RUN_LIVE_LLM=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python runs/ten-topic-gpt-final-acceptance-20261007/audit.py`：exit0，全部2,800独立路径计算通过；日志audit-accepted.log，机器证据evidence-accepted.json。
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python runs/ten-topic-gpt-final-acceptance-20261007/metadata_audit.py`：exit0，三条一次授权、2,700真实执行来源、最后100和保护hash通过；metadata-evidence.json。
- 新验收测试：3 passed；本轮相关研究/Core回归：62 passed in74.54s，exit0。具体命令与日志见VERIFICATION.txt。
- src/tests/scripts及验收代码py_compile：exit0；验收代码Ruff：exit0。
- 仓库规定范围Ruff：exit1、42个错误；原项目同范围复跑同42个，原有问题，未扩改。
- 文档导航：worktree4 failed/6 passed；原项目3 failed/7 passed。三个共同失败为既存导航/周报入口合同；另一个为独立worktree缺少被忽略的旧run本地链接，不通过复制/改写旧结果消除它。均不影响本轮研究产物。
- pyright可执行文件未安装：exit127，环境缺失；未增装依赖。

## 旧约80分钟扫描的具体原因

定位到 `tests/integration/test_concurrent_recovery_parallel.py::test_parallel_acceptance_is_hash_bound_idempotent_and_zero_provider`（前次收集序号102），是旧四模型恢复的**纯mock**并行接纳/幂等性集成测试，不是本轮真实调用。

前次中断后保留的合成campaign包含86,767事件。一次只读CampaignJournal.read测量15.0468秒，checksum函数调用86,767次，全部记录加载成功。读函数每次从序号1校验整个事件链；旧流程通过_context/合法历史重构反复全链读取，累计历史变大导致累计扫描工作放大。前次采样CPU热点在JSON编码/SHA256，与此一致。量化证据 diagnostics/legacy-slow-test.json。未重跑长集成测试/模型比较，不因该原有性能问题扩大研究实现修复；选择本轮62项相关回归和2,800正式产物全覆盖验收。

## 修复与遗留

正式数据/运行/统计未发现需修复问题，未改账本或删失败记录。验收程序自身的初版严格Decimal等号在1.58e-17浮点残差处误报，改为1e-9 USD比对容差并重新全量运行；矩阵断言强化为独立锁定七权重点×1/3/6而非仅检查21个名字；新程序变量/导入格式问题经Ruff修正。历史初版证据/失败日志保留在first-pass/及decimal-tolerance-probe.log，仅evidence-accepted.json为最终。

遗留：旧恢复全链扫描性能、既有42 Ruff问题、文档导航问题、缺失pyright。未执行：整个1768测试全仓库扫描、旧四模型恢复慢集成测试重跑、pyright、现金发票/远端认证、论文修改、canonical部署与公网交互/下载验收。已执行检查不产生任何真实Provider调用；mock测试不算正式模型判断。

## 最终可用成果与发布判断

正式判断库、路径和统计表的绝对路径/sha256完整列于final-artifact-inventory.json。

- 判断库：现有成果目录final-bank/closed-bank.jsonl，SHA256 cea5316de20aa361b40cb9c02ed2f9bb0e2db54e9e92df67fdaed654bf188fb0。
- 路径清单：formal-paths/manifest.json，SHA256 d01006705b1ef826193b86d94c41741669f96b4626b6fd605ee7d505a0a123fa；2,800个逐路径hash由该清单拥有。
- 统计总表：formal-report/arm-parameter-estimates.csv，SHA256 f43a6216fac2e48e5f11f4dbe231635586a1c7edf2500b367d5428d5b10168a8。

**可作为论文中这两个有界研究的结果使用**，必须保留样本/网络/模型服务时点、Monte Carlo条件区间、observed代理与合成标签等限制。论文正文本轮未修改。

**可作为后续正式发布的输入候选，不等同已可直接部署。** 现有成果production_deploy_eligible=false；发布仍需接纳新schema、生成immutable release、呈现/下载同源检查及用户授权下的部署/公网验收。canonical本轮未更改。
