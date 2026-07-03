# 锦江用户数据结构简图

## 核心理解

后续用户数据可以简单分成两部分：

| 部分 | 含义 | 来源 | 用途 |
|---|---|---|---|
| 真实观测数据 | 用户在 Douyin 数据中真实出现过的行为和网络指标 | 现有 final dataset | 表示用户是否活跃、是否有影响力、处在什么互动位置 |
| 虚拟实验标签 | 为仿真实验生成的 latent class、价值偏好和画像标签 | 用户潜在属性研究表格 | 表示用户在实验中被设定为何种消费价值偏好类型 |

也就是说，新版本不是替换真实数据，而是在真实用户对象上增加一层“虚拟实验标签”。

## 图一：当前版本

当前版本只有真实观测数据。

```mermaid
graph TB
    real["真实观测数据<br/>Douyin final dataset"]

    subgraph realFields["用户已有字段"]
        identity["用户 ID<br/>sec_user_id"]
        behavior["互动行为<br/>comment_count<br/>reply_count"]
        network["网络位置<br/>in_degree<br/>out_degree<br/>edge_degree"]
        scores["观测代理指标<br/>activity_score<br/>global_influence_score<br/>local_influence_score"]
    end

    user["ABM UserProfile<br/>当前用户对象"]
    decision["ABM / LLM 决策<br/>只能基于真实观测画像"]

    real --> identity
    real --> behavior
    real --> network
    real --> scores
    identity --> user
    behavior --> user
    network --> user
    scores --> user
    user --> decision

    classDef realStyle fill:#e7f5ff,stroke:#1971c2,color:#0b3d66
    classDef fieldStyle fill:#d3f9d8,stroke:#2f9e44,color:#154d24
    classDef runStyle fill:#c5f6fa,stroke:#0c8599,color:#0b4f5c

    class real realStyle
    class identity,behavior,network,scores fieldStyle
    class user,decision runStyle
```

当前问题：

- 能知道用户在 Douyin 里是否活跃、是否中心、是否有覆盖力。
- 不能知道用户对锦江秸秆产品的价值偏好。
- LLM 只能看到“平台行为画像”，缺少“消费价值偏好画像”。

## 图二：修改后的目标版本

目标版本把用户数据分为两部分：真实观测数据 + 虚拟实验标签。

```mermaid
graph TB
    subgraph userData["新版用户数据"]
        subgraph realPart["A.真实观测部分"]
            realBehavior["互动行为<br/>comment_count<br/>reply_count"]
            realNetwork["网络位置<br/>in_degree<br/>out_degree<br/>edge_degree"]
            realScores["观测代理指标<br/>activity_score<br/>global_influence_score<br/>local_influence_score"]
        end

        subgraph virtualPart["B.虚拟实验标签部分"]
            latentClass["latent_class<br/>Class 1 / Class 2 / Class 3"]
            valueWeights["价值偏好权重<br/>认知<br/>环境<br/>功能<br/>健康<br/>情感<br/>社会"]
            profileLabels["Table 11 画像标签<br/>最近入住酒店档次<br/>旅行目的<br/>性别<br/>年龄<br/>教育<br/>收入"]
        end
    end

    profile["新版 ABM UserProfile<br/>真实观测字段 + latent_attributes"]

    subgraph llmView["LLM 可见用户信息"]
        llmReal["LLM 可获取的真实观测信息<br/>活跃度<br/>影响力<br/>互动位置"]
        llmVirtual["LLM 需要新增的实验标签解释<br/>用户属于哪类<br/>更重视哪些价值<br/>标签不代表真实身份"]
    end

    decision["ABM / LLM 决策<br/>同时考虑平台行为和价值偏好"]

    realBehavior --> profile
    realNetwork --> profile
    realScores --> profile
    latentClass --> profile
    valueWeights --> profile
    profileLabels --> profile
    profile --> llmReal
    profile --> llmVirtual
    llmReal --> decision
    llmVirtual --> decision

    classDef realStyle fill:#e7f5ff,stroke:#1971c2,color:#0b3d66
    classDef virtualStyle fill:#fff4e6,stroke:#e67700,color:#5f370e
    classDef userStyle fill:#d3f9d8,stroke:#2f9e44,color:#154d24
    classDef llmStyle fill:#c5f6fa,stroke:#0c8599,color:#0b4f5c
    classDef decisionStyle fill:#ffe8cc,stroke:#d9480f,color:#6f2508

    class realBehavior,realNetwork,realScores realStyle
    class latentClass,valueWeights,profileLabels virtualStyle
    class profile userStyle
    class llmReal,llmVirtual llmStyle
    class decision decisionStyle
```

## LLM 版本怎么理解

LLM 版本和用户数据结构是一致的，也分成两部分：

| LLM 看到的部分 | 内容 | 注意 |
|---|---|---|
| 真实观测信息 | 用户活跃度、互动网络位置、影响力代理指标 | 来自 Douyin 数据，可以说是观测到的行为 |
| 新增实验标签解释 | latent class、价值偏好摘要、最近入住锦江酒店类型等 | 是仿真实验设定，不能说成真实用户身份 |

示例：

```text
真实观测信息：
该用户在锦江相关评论数据中有一定互动记录，activity_score 较高，处在一定互动网络位置。

新增实验标签解释：
该用户在本次仿真实验中属于 Class 1。
在锦江酒店秸秆产品语境下，该类用户相对更重视环境价值和健康价值。
这些标签是实验设定，不代表真实 Douyin 用户画像。
```

## 最终要改成什么样

```text
当前：
UserProfile = 真实观测数据

目标：
UserProfile = 真实观测数据 + 虚拟实验标签
```

更具体地说：

```text
真实观测数据：
- comment_count
- reply_count
- in_degree
- out_degree
- edge_degree
- activity_score
- global_influence_score
- local_influence_score

虚拟实验标签：
- latent_class
- six value weights
- latent_hotel_class
- latent_travel_purpose
- latent_gender
- latent_age
- latent_education
- latent_monthly_income
```

其中：

- 真实观测数据用于说明用户在 Douyin 平台上的行为状态。
- 虚拟实验标签用于说明用户在 ABM 实验中的消费价值偏好设定。
- LLM 决策时也按这两部分读取：一部分是真实观测画像，一部分是实验标签解释。
- Table 11 的画像标签第一版主要用于分组分析和解释，不直接当成真实人口属性。
