# 第十阶段：十一条件接纳与已知无效响应显式补采

Kimi/P1已完成并从原始路径独立验收；累计十一条件、19,800曝光、330屏障接纳通过。局部表/曲线/新旧对照重新生成，从原始路径复算1,144行表/曲线/对照及264行共同Batch0用户block bootstrap；没有增加Provider调用来验证。仍非完整16条件成果，论文/canonical未改动或部署。

Kimi/P2在第21批收到真实官方kimi-k3响应，usage完整：971输入token、1024输出token、合计1995；输出达到原1024上限，结构化判断不合格。持久化响应没有finish_reason字段，不能把“截断”当作直接观测事实；此前口头表述已在本报告更正为推断。原失败retryable=false、原真实响应及usage保留，既不改写为unknown，也不接纳为成功。依据用户“类似问题继续补，不需逐条确认”的已有授权，Study另外记录显式同输入补采；Core Adapter的retryable分类和生成设定不变。仍遵守每输入合计最多3次和全任务29,143次限制，不提高token上限、不改变模型、通道或模板。只允许实际响应型号/usage/上限合格但结构化内容不合格的官方Kimi情形；身份、usage、quota/auth等故障不由此绕过。

补采意图单独标识explicit_known_invalid_new_collection，链接原已知失败和独立授权；独立账本验收逐条核对实际父响应、完整输入/条件及预算。75项相关离线回归测试通过，Ruff F及py_compile通过；metadata-only测试不包含合成正式判断。精确baseline/modified/rollback及结果见VERIFICATION_WAVE10.txt，rollback仅对scratch。原判断与历史结果保持不变；原Adapter异常分类文件没有改动。

Gemini原冷却期结束后确实继续发出真实请求并获得部分新响应，随后服务给出新的07:44:55 UTC（新加坡15:44:55）冷却期限。三个进程继续按新期限等待，不切换原通道/模型，不提前发出意图。Kimi/P3继续执行，Kimi/P2已在相同检查点恢复。全部16条件及最后统计/完整性验收仍待收尾，goal保持active。现金费用仍未知，不推定为零；全仓库长扫描和环境缺失pyright未重复，原有检查范围说明保持。
