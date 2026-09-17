# GPT-P0 千人动态参数研究：最终证据（2026-09-17）

关联 #256、#258–#262；main，原审计1856752。代码增量4b160a5、e6f4002、f8ce522、f61636f、7805fe5。

## 结论

**终点消息差异在所测矩阵内保持，但传播时间过程有变化。** 这不是“推荐参数普遍不敏感”的证据。

| 消息 | 基准平均 realized 互动率 | 普通95%均值区间 |
|---|---:|---:|
| message_1 | 65.4433% | [65.1454, 65.7413]% |
| message_2 | 65.0883% | [64.7172, 65.4594]% |
| message_3 | 71.0567% | [70.7012, 71.4121]% |

| 终点消息对比 | 均值差/pp | 123均值校正区间/pp | 判据 |
|---|---:|---:|---|
| message_1-message_2 | 0.3550 | [-0.5248, 1.2348] | near_zero |
| message_1-message_3 | -5.6133 | [-6.4868, -4.7399] | negative |
| message_2-message_3 | -5.9683 | [-6.9124, -5.0243] | negative |

- 2,100路径全部闭合：63,000 barriers、3,780,000 exposures。每消息600曝光，每路径1,800；3,000是判断库容量。
- 2,000个同seed非基准配对：最终曝光集合全部相同；1,597条曝光顺序变化，1,494条跨批分配变化。固定判断与CRN相同draw因此使同seed终值严格一致，所有Δ=0。不是冻结反馈重排序。
- message_1−message_2平均时间曲线最大相对基准偏移+7.94pp（w6-h6，第5批）。这是描述性最大偏移，不是全时程显著性检验。
- 本矩阵所有曝光均引用旧1,800判断，补采判断曝光数0；完整库仍按预声明补齐，不把未曝光数据伪称参与终点估计。
- 42/63条主要对比满足普通区间半宽≤0.5pp；message_2−message_3对应21条为0.5118pp，明确精度不足。保留预声明100种子，未根据结果扩样。

## 冻结设计与接纳

用户先接受完整客户端重建证据并复用旧1,800条；随后明确“后续不需要我确认…直到最终完成”，接纳[方案](gpt-p0-dynamic-parameter-plan-20260917.md)的有界执行。用户后续明确把并发改为最多5路，其他请求/费用上限未扩大。

仅GPT-5.6 Sol/P0、原1,000用户/三消息/图；固定P95、Top20、30批、同批冻结/全批提交。7权重点各交叉h=1/3/6：

| 权重点 | 网络 | 邻居反馈 | 内容 |
|---|---:|---:|---:|
| w0 | .50 | .30 | .20 |
| w1 | .65 | .15 | .20 |
| w2 | .35 | .45 | .20 |
| w3 | .65 | .30 | .05 |
| w4 | .35 | .30 | .35 |
| w5 | .50 | .45 | .05 |
| w6 | .50 | .15 | .35 |

基准w0-h3；100种子2026091700..2026091799。ε=2pp，123均值Bonferroni t区间、df99；时间带是点态模拟分位数。独立路径状态由Study/私有kernel推进，Evidence另行重算曝光/动作/反馈，Report从同一闭合Evidence产生。

新增接纳政策`client-reconstruction-accepted-20260917-v1`保存于独立bank准备产物；旧审计undetermined与原证据不改。1800历史完整请求逐条匹配，3000×30=90000客户端渲染检查通过。实际Pi OAuth订阅路由、gpt-5.6-sol、low reasoning、timeout30、application completion ceiling256、sampling参数省略均核对；新响应模型与usage逐条校验。

旧判断采于2026-09-11 17:52:17–20:37:35 UTC；新判断采于2026-09-17 06:31:31.794856–07:46:53.554472 UTC。隐藏服务端版本不可观测，客户端重建一致不证明隐藏上下文相同。

## 调用与费用

| 项目 | 本次补采 |
|---|---:|
| 新增合格判断 | 1200 |
| 物理请求（上限1262） | 1201 |
| 资格 / 重试 / 失败 | 1 / 0 / 0 |
| 在途峰值 / 最终授权上限 | 5 / 5 |
| input / output / total tokens | 1179967 / 156984 / 1336951 |
| cached input tokens / 缺失usage attempts | 0 / 0 |
| 已知订阅名义参考USD | 10.609355 |
| 实际额外扣款 | null，未提供独立账单证据 |
| 离线动态阶段Provider调用 | 0 |

历史另有1800判断/1804物理请求、已知名义参考$15.593085；4个历史失败的缺失cost仍未知。两段共3005物理请求，历史消费未在本次重复发生。未充值、购买额度、兑换reset或换路由。

在685新增成功+1资格后，冻结串行进程并核验0在途再交接；原前缀2020532字节的hash保持不变。并发独立授权hash绑定每条新intent，共享预算先预留后派发、统一结算，成功pair不重发。

## 可追溯产物

以下路径相对仓库根目录；HTML为可直接打开的独立报告，不是canonical部署。

- bank：`runs/gpt-p0-bank-topup-20260917-authorized-01/`，含preparation、accepted-bank、missing-pairs、client-identities、closed-bank及collection账本/closure/授权/串行交接与实现身份。
- paths/report：`runs/gpt-p0-dynamic-parameters-20260917-formal-01/`，含2100独立路径、study/path manifests。
- 最终入口：`runs/gpt-p0-dynamic-parameters-20260917-formal-01/report/report.html`，27张SVG、5张CSV（2100路径摘要、63参数率、63消息对比、3780时程、2100路径诊断）及evidence.json。
- 初版报告保留为同run的`report-initial-20260917/`；补齐解释/累计人数曲线未改变路径字节。
- 实现与验证：`runs/gpt-p0-parameter-implementation-20260917/VERIFICATION.txt`，包含完整命令、输出、退出状态、修改副本/差分/回滚记录。

| 内容 | SHA256 |
|---|---|
| bank | `0e4e72283b1ffc94364a2d13b2f4516213c1c01aca145769bf15ae30bc1f0e0e` |
| attempt ledger | `8fa1ab4ff8bdcb22a64f50d64e14bd5658d62a4553513f23167c2325be2356ae` |
| study | `2512c8613ee4474b4790c1cfc537fa49165eadee1525657ba480fd0ab7c6bac8` |
| report Evidence | `576b94a0ba8226c0a978d01d4ec74a6df0a77e5097d29f429b36812a4c3ed063` |
| report artifact manifest | `87a3eb404c2e378b69347b67172fce684bf597b8bbc439e265c9d67411e7b0a4` |

## 验证与限制

- 聚焦及相关旧合同回归114 passed in 50.42s；参数模块/测试Ruff、Pyright通过，src/tests/scripts编译通过。两轴review无未闭合阻塞。
- 新kernel逐条复现历史1800曝光/动作/draw与30barriers；2100路径resume后全部字节不变。最终35文件重新读取/hash核对，HTTP下载逐文件200且hash一致；报告及曲线经浏览器视觉检查。
- 全仓pytest尝试约一小时后终止（exit143），未获得完整结果；不声称全仓绿色。既有全仓Ruff/type问题没有借此宣称解决。
- 仅固定样本/图/判断库下的realization随机性；自适应曝光不是IID用户配对。结果不覆盖LLM重采样、样本/图不确定性、服务漂移、其他模型/Prompt或真实平台因果有效性。
- [Burke (2002)](https://link.springer.com/article/10.1023/A:1021240730564)解释组合推荐背景；[Pazzani & Billsus (2007)](https://doi.org/10.1007/978-3-540-72079-9_10)解释内容匹配；[Bakshy et al. (2012)](https://arxiv.org/abs/1206.4327)区分社交定向与展示线索影响；[Saltelli et al. (2019)](https://arxiv.org/abs/1711.11359)支持联合扰动与声明覆盖范围。它们不估计本项目权重、P95、Top20、h或2pp界值；这些均是研究者设定。
- 无新增依赖、无Ralph、无canonical部署；未手工读取/打印/写入秘密，认证由既有Pi transport内部处理。

复核提示词：
```text
仅沿本记录列出的bank、study与report manifest复核；保留历史证据，不扫描latest，不调用Provider。区分终点集合同一造成的机械Δ=0与逐批时间过程变化，并保留21项MC精度不足和费用null语义。
```
