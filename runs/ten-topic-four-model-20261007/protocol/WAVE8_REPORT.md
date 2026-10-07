# 第八阶段：完整矩阵继续执行与验收加严

前一goal turn属于进展：充值核实、Gemini显式批次授权、新增真实响应及回归证据均已落地。本轮实查六个条件工作进程存活（Gemini P1–P3、Kimi P1–P3）；原已完成十条件不重跑。Kimi P2/P3起初的短命launcher在生成journal或调用意图前退出，原绑定记录保留为未执行；已改由两个可追踪tool session运行。每条件内部仍顺序曝光/批次屏障，条件间邻居反馈分离；样本/请求/seed/抽样锚点不变。

独立验收此前没有显式比较完整请求条件、旧来源模型/输入及部分顶层来源标识。本轮只加强验收，不改变正式数据或研究设定：

- 每条件完整1800条（实际整数1800），唯一合法模型×模板；网络source manifest绑定已核实合同。
- 复用旧记录模型、观测模型、来源path/hash、P0–P3规范、原画像渲染输入以及有效请求条件逐项匹配。
- 新判断请求与真实成功资格记录的条件精确一致；后期有adapter wire记录时额外核对模型/控制参数。早期无wire记录，不虚称重新获取HTTP body；Gemini gateway隐藏上下文仍不可观测。
- GPT/P0绑定已验收判断库的完整文件hash、来源path和request contract。

本轮加严后十个已完成条件共18,000曝光、300屏障仍通过；当前不是16条件完成。局部报告重新生成并从原始路径复算：1,040行表/曲线、新旧对照，240行共同Batch0用户block bootstrap。统计/验收过程新增Provider=0；真实采集继续单独计账。51项相关离线测试通过，Ruff F与py_compile通过。原有全仓库扫描/pyright环境缺失仍按此前说明未重复，不伪称已执行。

精确baseline/modified/rollback命令、输出及退出码见VERIFICATION_WAVE8.txt；rollback仅测试scratch副本。原判断库、结果和先前全样本/GPT研究未修改；论文与canonical未修改/部署。完整16条件及最终收尾报告/费用/来源清单仍待执行完毕后交付，goal保持active。
