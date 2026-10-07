# 十话题成果并入 main 与持久来源

十话题研究分支的全部提交已快进合入原项目 main。原项目的未提交周报保留；研究统计、模型、协议、论文及 canonical 部署均未修改。

正式本地产物现保存于原项目 `/Users/liuqingyuan/work/llm-abm-marketing-sim/runs/` 下的以下完整目录，不覆盖既有旧结果：

- `ten-topic-full-pool-20261006/`
- `ten-topic-gpt-studies-20261006/`
- `ten-topic-gpt-final-acceptance-20261007/`
- `ten-topic-four-model-20261007/`
- `ten-topic-v17-publication-20261007/`

历史 contract、账本、验收与 release 的原始字节及研究身份不改写。它们记录的旧 worktree 绝对路径是历史定位；当前读取须使用独立的持久位置映射。不能通过修改历史 contract 的路径来伪装为原生产 validator 已验证的新身份。此次仅做迁移、原库存与 hash 复核，不重建 release、不重新计算或运行研究、不部署。

映射及完整逐文件迁移清单保存于：

`/Users/liuqingyuan/work/llm-abm-marketing-sim/runs/ten-topic-main-integration-20261008/PRESERVATION_MAPPING.json`

`/Users/liuqingyuan/work/llm-abm-marketing-sim/runs/ten-topic-main-integration-20261008/COPY_MANIFEST.json`

原项目的旧判断库、数据集和旧四模型 outputs 仍原地保留。worktree 中其他无法由 Git 恢复的证据另存同一 integration 目录的 `support-untracked/`；源码由 main 及其完整 Git 历史保留。可再生的索引/字节码缓存不作为研究输入；环境依赖链接的目标仍在原项目或既有 bundled runtime。

可复验持久副本：

```bash
cd /Users/liuqingyuan/work/llm-abm-marketing-sim
.venv/bin/python scripts/verify_ten_topic_preservation.py \
  --mapping runs/ten-topic-main-integration-20261008/PRESERVATION_MAPPING.json
```

也可添加 `--resolve <历史文件绝对路径>`，返回已验证的持久路径/hash。此命令只读取保存的字节和原库存，无 Provider、实验、写历史结果或部署能力。

最终合并、推送、清理和未执行检查见 [本轮交付报告](../../runs/ten-topic-main-integration-20261008/REPORT.md)。此前发布证据仍见 [v17 canonical 发布](ten-topic-v17-canonical-release-20261007.md)。
