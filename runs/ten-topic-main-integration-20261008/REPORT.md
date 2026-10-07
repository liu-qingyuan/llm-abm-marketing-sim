# 十话题 main 合并与成果持久保存

当前阶段：main 已快进合入研究分支972c64f的全部35个新增提交；正式产物持久保存与main复验通过。推送和worktree清理的最终状态将在完成后追加。

- 原main：bdedc9fbd17b5d77bbd49baba0b49bc9b3d3a856；研究分支：972c64ff125924421b52be3439e508bf23724ae9。
- 五个完整正式目录位于 `/Users/liuqingyuan/work/llm-abm-marketing-sim/runs/`，不覆盖原项目已有结果。
- 7,588对象（7,585普通文件及3环境依赖链接），14,898,050,086 bytes。所有源/目标文件SHA一致；20个其他untracked文件及两个root运行时别名另存support-untracked。
- COPY_MANIFEST.json SHA：7da93b2522ebb944cffe6c8fb705afe4d5bf93f07466f50cd939117c8106fd3d。
- PRESERVATION_MAPPING.json SHA：4cf6730bf842e489be378b4f3dae0e14d0d543a404e8c5d3253f0b7dcb912a66。
- 使用独立映射读取原contract，原字节、身份及SHA不改写。9绑定来源、2,800条GPT路径、四模型80交付文件、v17 264文件及旧v16 215文件均再次核验；结果READY_FOR_CLEANUP.json。
- 正式源的其他依赖留在原项目数据集/旧判断库/outputs，worktree data只有6个Git README/gitkeep；外部runtime与凭证配置仍在原位置，凭证未读取/复制。扫描3,490条绝对路径；除4个过去测试scratch文件及1条截断叙事外，旧定位有迁移映射或原项目持久位置。堆栈行号/JSON Unicode转义已规范化。当前Formal hash绑定不存在缺失。
- main相关测试：105 passed in68.27s；初次PYTHONPATH=src缺少tests模块的调用失败保留，修正为src:.后通过。全src/tests/scripts py_compile、bash -n与新脚本/测试Ruff通过。
- 全域Ruff实际运行42个既有错误；pyright执行文件缺失。未重复旧约80分钟的mock并行恢复集成全仓扫描，未声称全仓全部通过。未重跑正式实验/统计，不调用模型，不部署网页、不修改论文。
- canonical及服务器读取的report/manifest SHA仍为82012e17b4176284d21443cf07ba9a05336730864a27208cc7093da493186251 / e16f591b3cf18f2717137a4a21a726a299badaa208949d20e0cebe0c7574d479，current为ten-topic-v17-20261007T113429Z，healthy。仅只读检查。
- 原main的3份未提交周报SHA未改变，未被纳入本次提交。无关9个分支不自动清理。

持久读取：

```bash
cd /Users/liuqingyuan/work/llm-abm-marketing-sim
.venv/bin/python scripts/verify_ten_topic_preservation.py --mapping runs/ten-topic-main-integration-20261008/PRESERVATION_MAPPING.json
```

增加`--resolve <历史绝对路径>`可获得通过SHA验证的新路径。历史发布validator的绝对位置合同没有被绕过；此处是独立的保存/读取验证，不是新研究或可重新部署的contract。

## 新增/调整文件

- scripts/verify_ten_topic_preservation.py：独立位置解析与完整迁移/hash核验。
- tests/unit/test_ten_topic_preservation.py：不存在旧root仍可读取、篡改拒绝、原contract字节不改写与越界拒绝。
- docs/index.md、docs/references/ten-topic-main-preservation-20261008.md：新main物理入口及历史身份区别。
- 本integration目录：迁移、工作区、Git、main复验及清理证据；COPY_MANIFEST与绝对路径扫描为本地保留文件，不将响应银行、raw payload或凭证加入Git。

## 分支/HEAD记录的可回滚复验

MERGED_HEAD.json保存真实合并后的main_head字段，DIFF_FILE.patch显示前后差异；VERIFICATION.txt记录精确BASELINE/MODIFIED/ROLLBACK命令、输入、输出和退出码。ROLLBACK.sh仅恢复scratch-head.json，恢复旧祖先检查状态；没有回退实际main、丢弃任何周报或覆盖正式结果。
