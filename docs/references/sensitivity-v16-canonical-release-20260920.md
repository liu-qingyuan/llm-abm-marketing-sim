# Parameter 与指标敏感性研究：v16 canonical 追加发布

## 实际发布

- [统一网页](https://abm.q1ngyuan.top/)；[Parameter 章节](https://abm.q1ngyuan.top/#parameter-study)；[Activity / Local Influence 章节](https://abm.q1ngyuan.top/#index-sensitivity-study)。
- 时间：2026-09-20T11:44:00Z；release：`sensitivity-v16-20260920T113800Z`；实现 commit：`43555ea6f06b08f06ec9c7d700cd352e2f7494d2`。
- Contract：`runs/sensitivity-v16-ticket-263-20260920/sensitivity-v16-20260920T113800Z-release-contract.json`；SHA-256 `6ef1f9baf777d29223fa1e9fab8d3cd1c86b368162f4f9f7491d86e83db63ef0`。
- Immutable source：`runs/sensitivity-v16-ticket-263-20260920/sensitivity-v16-20260920T113800Z/`。
- Release identity：`001dda6a1ed260eb3ecb33dad636c647a49757929b2843db4c901731b0d12ce0`。
- Report SHA-256：`e7c9cc0bffb8a148376fed4b49b58d8574784540a6b2dbaf0f8845a2d0cff659`。
- Manifest SHA-256：`52e65d1bba4f75114fa3acadb56fe74684c6415aedfa078f9b0f11e01aaf8774`。
- [Operational #263](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/263)。

## 最小改动与证据 ownership

Report Module 追加导航及两个独立报告阅读区；复用原报告/相对下载，不重写统计 renderer。Release Module 新增固定证据 accession 合同；Deployment 复用原事务，仅增加 v16 schema 分派。未新增依赖、通用框架或部署结构。

159 个旧内容/下载文件 bytes 保留；原 report/manifest 仍在 v15 回退 release。新报告及聚合结果按源 hash 安装，另从指标原 inline SVG 导出独立图表（只添加 XML namespace）。总发布文件 215 个。

原 run、判断库、调用账本、lineage 与 `production_deploy_eligible=false` 均不改写。v16 单独表达对明确最终证据的接纳资格；这是固定已审计证据的发布验证，不是重新执行实验，也不声称本轮重新重放全部 2,800 条路径。统计口径和各研究入口只在 [统一研究入口](../index.md) 汇总，单项结果仍由原 evidence/report 拥有。

## 已执行验收

- 155 项相关离线测试通过（75.92s），范围为 Report、Release、Deployment、公开下载及新增敏感性呈现/合同。
- 修改前 42 项基线测试通过；独立副本逆向应用代码 patch 后 42 项通过，工作区修改保留。
- 固定来源 manifest/audit 全部 hash、旧 v15 161 文件、两项研究路径矩阵、整数动作、100-seed 均值及100条基线复现检查通过。
- 27 张 Parameter SVG 从其 CSV 重建后 bytes 相同；指标 SVG 的7条曲线/210个点与下载 CSV 一致。
- Local snapshot/preflight、fresh rollback 身份、候选 inventory/health、Nginx、原子 current、正式容器健康、最终锁内 current/container 回读全部通过。
- 公网215个文件可达；117个完整 body hash（51,464,359 bytes）通过；98个大型旧产物按既有 manifest + remote hash + public HEAD 合同闭合，不伪称全部完整 body 重下载。
- 公网 Playwright 通过（2.2min）：1440、1600、390三种宽度，旧语言/图表/下载、新导航与阅读区，无页面错误或横向溢出。
- 补充浏览器核对两项报告的13个数据/evidence链接完整 body hash；实际点击下载指标 SVG 并对齐合同 hash；保留网页截图。
- 编译、修改范围 lint、shell syntax、git diff whitespace 通过；GitNexus 按实际仓库路径刷新。

## 回退、清理与未覆盖风险

生产回退点：`revised-four-model-v15-20260912T105000Z`；report `085a572c55bc88f5a8956f87ac731802e6866a9e3c81456266757402147de44e`，manifest `5f78009bc3ab80fd80299dcb0dfe366ecef8e615bd4e3704bf692124f36d5cb0`。生产未触发回退；副本原子切换/恢复与共享部署失败矩阵已验证，不把副本测试写成生产恢复演练。

只清理本轮生成、已验证完毕的临时副本；不删除历史研究、下载、证据或远端回退版本。原两份未提交周报的内容保留。

未跑全仓完整 pytest；全仓指定范围 Ruff 有42项既有问题，三个涉及文件与基线 bytes 相同；pyright未安装（exit127）。Nginx既有 `listen ... http2` 弃用警告未在本任务改动。上述项均不宣称通过。

本轮 `provider_calls=0`，未重跑实验，未读取/打印/写入秘密。

## 本地操作证据

`outputs/research-navigation-publication-20260920/`：`VERIFICATION.txt`、`production-operation.json`、`production-deploy.log`、`all-related-tests.log`、`rollback-code-tests.log`、`chart-parity-result.txt`、`public-download-check.json`、`public-navigation.png`、`public-index-section.png`。正式 operation facts 位于 release 之外，不回写 immutable source。
