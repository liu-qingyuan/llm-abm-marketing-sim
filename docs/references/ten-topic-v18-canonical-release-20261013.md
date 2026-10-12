# 十话题五模型 v18 canonical 发布

口径：2026-10-13（Asia/Singapore）；实际部署时间 **2026-10-12T22:16:58Z**。

[Canonical Final Research](https://abm.q1ngyuan.top/) 已通过真实 v18 发布验收。GPT 6.0、GPT 6.1、qwen3.8-max 非思考各完成资格1、三消息smoke3及Formal7,200判断；DeepSeek官方直连与十话题GPT 5.6仅复用历史正式结果，没有新增实验。12新条件21,600曝光＋8历史条件14,400曝光＝20条件36,000曝光。

## 发布身份

- Release ID：`ten-topic-v18-20261012T214048Z`
- Report/Release implementation commit：`e4fa16be10fb93a34aab2493b4c19d4e70bde5eb`
- Public transport integrity fix commit：`667f4d5`（只增加压缩完整性协商，不改变源报告或部署结构）
- Contract SHA256：`6b93abf94007f4e27fec1e2a4f8dd9eb0537c353dea63d2d4816b830e9409ac6`
- Release identity：`7741a0c3c99335f3852561b83e7b6f48a264a8989401bbdc48d79e48a0551cdf`
- Report SHA256：`8de830b1884c80348f9b5e5e16c57c21dec0d9262c4c16b15d2d71ff0f288480`
- Manifest SHA256：`2743bacbd6945bae6bb187867f72320ab6e8fd0ae7157c90c6376511ee3e4239`

## 实际验收

313项不可变库存完整核对：214项完整正文hash（74,417,595 bytes），99项既有大文件由manifest、远端hash及公网/浏览器HEAD闭合（1,727,526,845 bytes）。公网Playwright **1 passed（2.5m）**，验证五模型20条件、消息/模板/segment筛选、曲线、双语、桌面/手机、既有历史交互及两版工作簿下载。candidate health、原子current、post-switch health和锁内最终current/container身份均实际通过。

源目录：`runs/ten-topic-v18-publication-20261013/ten-topic-v18-20261012T214048Z/`；兄弟文件为exact v18 release contract。Operational证据：`runs/ten-topic-four-model-revision-20261011-formal-01/production-accession-20261013/DEPLOYMENT_OPERATION.json`；[Operational #265](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/265)。

前三次公网正文截断均被原hash门禁拒绝并恢复v17；压缩协商使curl识别不完整传输并使用既有有限重试，解码后仍核对原始完整SHA/size。第四次正式事务成功。主机、域名、远程根目录、容器和部署结构不变，没有手改远端report.html；本次发布重建Provider调用为0。

## 研究与费用口径

原有序1,000人panel、20seed、十话题网络/holdout、三消息、P0–P3、权重0.50/0.30/0.20、阈值3、SHA53抽样锚点及behaviorseed20260823不变。实际全局判断并发峰值5、模型同时重叠峰值3；保守物理总数21,635/86,450。用户后续允许更多常规异常重试；有界ceil10、退避及原始失败/unknown记录保留，没有更换seed、模板或模型。

Max供应商两种已入账来源在完整实验范围截止时点均为 **CNY69.766308**，低于授权100；这是exact SKU/原Key/北京业务空间的已入账聚合，不是下一月最终invoice，也不是逐请求精确实付分摊。供应商7,205成功与本地7,204完整回执的差额1次/754输入/51输出仅作聚合披露，未归因具体unknown；原逐请求未知字段不改写。GPT新增现金0；DeepSeek/GPT 5.6无新增调用；没有充值或额外credits。

GPT采用原订阅来源及服务端model/response-ID追踪；两次独立SSE缺失的HTTP request-ID按用户接受保持unknown。未日期Max SKU不是不可变权重证明，未报告reasoning_tokens不填0，供应商推理等级不等同。观察后选型时点与跨时点历史复用已披露。完整Max P3 **847/1800＝47.06%**全部保留，没有新增60%门槛；互动率不是准确率。

## 测试与保留

默认离线全套启动快照：**1859 passed、7 deselected（2:48:03）**；随后两文件接纳变化由76相关tests和真实source正例闭合，HTTP传输修复由66相关tests及实际公网事务闭合，不冒称全套在最终源码另重跑。源编译和变更范围Ruff通过；规定更广Ruff的42项既有问题均来自3个与原HEAD字节相同文件，未扩大修复；pyright未安装，未声称通过。

v17完整字节、旧合同、旧结论、判断库与回退版本保留。匿名镜像及稿件不变。所有既有未提交的无关文件保留；新增公开物仅聚合统计、方法及相应下载。
