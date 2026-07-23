# ADR 0002: 使用目标投放排序替代概率曝光抽签

Status: Accepted

锦江 Final Research 只研究一条真实目标视频，核心问题是评论网络和内容相关性是否会改变用户获得该视频的顺序与互动结果。固定分批后的概率抽签会让随机数掩盖排序信号，且原 1,000 人样本切断了 seed users 与直接评论网络邻居。项目因此采用 Network-Augmented Research Sample 和逐轮全局 Top20 Target Delivery Ranking：网络信号只影响平台投放，真实 LLM 只决定曝光后的动作，每个用户最多曝光一次。

该设计牺牲了对随机平台流量的模拟，换取可解释、可复现且能直接验证网络信号实际排名作用的基础研究路径。权重属于预先声明的研究假设，不声称来自真实抖音曝光日志；报告必须提供无网络配对排名和最小权重敏感性检查。

Decision Adapter 接收的 `PeerContext` 保持中性：`engaged_neighbors`、`exposed_neighbors`、`influential_engaged_neighbors`、`visible_likes`、`visible_comments` 和 `visible_shares` 均为 0。Ranking 中观测到的 `engaged_neighbor_count` 只影响投放顺序，不是 Prompt input。Final Research v6 会分别持久化两种 context 的聚合证据，用于验证隔离边界；它不会把 Ranking signal 重新解释为用户真实看见的同伴行为。
