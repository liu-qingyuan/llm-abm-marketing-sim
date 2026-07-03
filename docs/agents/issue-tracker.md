# Issue Tracker：GitHub

本仓库使用 GitHub Issues 跟踪 issue 和 PRD。所有 issue 操作默认使用 `gh` CLI。

仓库：`https://github.com/liu-qingyuan/llm-abm-marketing-sim`

## 约定

- 创建 issue：`gh issue create --title "..." --body "..."`
- 读取 issue：`gh issue view <number> --comments`
- 列出 issue：`gh issue list --state open --json number,title,body,labels,comments`
- 评论 issue：`gh issue comment <number> --body "..."`
- 添加/移除标签：`gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- 关闭 issue：`gh issue close <number> --comment "..."`

在仓库内运行 `gh` 时，GitHub 仓库会从 `git remote -v` 自动推断。

## PR 作为 triage 请求入口

外部 PR 也作为 `/triage-lqy` 的请求输入。

triage PR 时，使用与 issue 相同的标签和状态，并使用对应的 `gh pr` 命令：

- 读取 PR：`gh pr view <number> --comments` 和 `gh pr diff <number>`
- 列出打开的 PR：`gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments`
- 当 `authorAssociation` 是 `CONTRIBUTOR`、`FIRST_TIME_CONTRIBUTOR` 或 `NONE` 时，把该 PR 视为外部请求候选
- 默认不要把 `OWNER`、`MEMBER` 或 `COLLABORATOR` 的 PR 拉入请求 triage 队列

GitHub 的 issue 和 PR 共享编号空间。因此裸 `#42` 可能是 issue，也可能是 PR；先尝试 `gh pr view 42`，再回退到 `gh issue view 42`。

## 当 skill 说“发布到 issue tracker”

创建 GitHub issue。

## 当 skill 说“获取相关 ticket”

如果 ticket 是 issue，运行 `gh issue view <number> --comments`。

如果 ticket 是 PR，运行 `gh pr view <number> --comments`。
