# v17第二阶段：正式聚合展示接入

## 已执行

- Report Module公开Interface新增render_ten_topic_research，旧v16 renderer/合同仍原样可用；旧内容、脚本、下载标识保留在显式历史区，四个新研究anchor作为默认当前入口。
- Release Module统计投影读取已接纳的正式CSV，校验分母/互斥计数/100seed均值/16条件矩阵，再把无用户ID的聚合事实交给renderer；没有运行仿真或Provider。
- 全样本实际比例来自109200曝光计数；参数21行、指标7行及四模型16行动态呈现。普通df99区间来自绑定估计；原同时区间将随对应下载保留，100seed不是100模型判断。
- 参数范围由正式mean数据计算；Local p99重建重合23从受保护样本引用重新求交集，不直接套旧108。
- 新四模型类别曲线由显式验收reference指定的16个normalized源生成，只输出aggregate；4320个点的144个终点与正式segment统计逐项一致，不扫描latest。
- 第一版浏览器发现没有ignore估计字段引发TypeError；已修为1−实际互动均值。实际新浏览器console0错误。四个table/四个curve可见；Message2/P2/S1四行筛选、English标题和390px无横向溢出通过。最新包含4320类别点、样本重合23的JSON已重开核对。
- 51项相关测试通过（3.13s），Ruff/py_compile通过。TDD Report Interface baseline缺行为，GREEN后新增Facade dispatch；scratch-only rollback恢复原无Interface状态，工作区修改保留，精确命令/输出/exit与四路径见VERIFICATION.txt。

## 当前未完成

此目录candidate-preview仅开发预览，不是Formal release。新下载links/CSV/JSON/XLSX/SVG统一文件、可重复重建Release contract、v17 Deployment exact dispatch及公网验收均待完成。最终发布前还需双轴review、GitNexus刷新、完整适用测试、fresh rollback/candidate/atomic/public gates。不得据本地预览声称线上新版本已发布。

Provider0。原域名/主机/根目录/容器/端口不变；本轮未写远端/切换current/改论文。历史模型实际渠道/DeepSeek V4.1版本与旧V4差异已在新阅读区说明；模型intent不与实际行为混淆。
