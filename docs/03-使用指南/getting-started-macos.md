# macOS 从零开始运行指南

这是在一台新 macOS 机器上运行 `llm-abm-marketing-sim` 的完整指南。它覆盖：离线 CLI demo、本地 Web 控制台、test/dev mock provider、可选 live LLM Provider、运行产物、故障排查和清理。

默认路径是离线且确定性的：**不需要 API key，不调用真实 LLM，所有运行产物写入被 git 忽略的 `runs/` 目录**。

## 1. 完成后你能运行什么

完整安装后，可以运行：

```bash
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
python -m llm_abm_sim.run --config configs/fixtures/realistic_marketing_dataset.yaml --output runs/realistic-sample
python -m llm_abm_sim.web --host 127.0.0.1 --port 8000 --artifact-root runs/web
```

然后打开：

```text
http://127.0.0.1:8000
```

## 2. macOS 前置依赖

新 Mac 先安装 Apple 命令行工具：

```bash
xcode-select --install
```

建议用 Homebrew 安装 Python 和 Node：

```bash
brew install python node
python3 --version
node --version
npm --version
```

要求：

- Python 3.10 或更新版本；
- Node.js 18 或更新版本；
- npm；
- 能在终端创建 Python 虚拟环境。

如果你使用 `pyenv`、`asdf` 或其他版本管理器也可以，只要 `python3` 指向 Python 3.10+，`node` 指向 Node 18+。

## 3. 克隆仓库

使用维护者提供的仓库地址。示例：

```bash
mkdir -p ~/work
cd ~/work
git clone <repository-url> llm-abm-marketing-sim
cd llm-abm-marketing-sim
```

下面所有命令都假设你在仓库根目录。

## 4. 创建并激活 Python 环境

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
```

安装完整本地产品/开发栈：

```bash
python -m pip install -e ".[dev,web,llm]"
```

extras 含义：

- `dev`：测试、lint、类型检查工具；
- `web`：本地 FastAPI/Uvicorn Web 控制台；
- `llm`：可选 OpenAI-compatible SDK，仅用于显式 live Provider 运行。

如果只做 CLI 开发，最小安装即可：

```bash
python -m pip install -e ".[dev]"
```

## 5. 安装浏览器测试依赖

Web 控制台和静态报告都是本地 HTML/JS 页面。浏览器自动化验证使用 Playwright：

```bash
npm ci
npx playwright install chromium
```

请优先使用 `npm ci`，确保依赖与 `package-lock.json` 一致。

## 6. 运行默认离线 CLI 仿真

```bash
. .venv/bin/activate
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
```

`runs/sample/` 下应出现：

```text
config.json
run_result.json
events.json
metrics_summary.json
step_records.csv
report.html
report_payload.json
graph_trace.json
input-builder.html
```

打开报告：

```bash
open runs/sample/report.html
open runs/sample/input-builder.html
```

报告支持中英文切换，展示帖子、种子用户、图/画像摘要、指标、决策来源证据和 Agent 输入/输出追踪。默认决策来源是确定性规则基线。

## 7. 运行真实感营销数据样例

```bash
. .venv/bin/activate
python -m llm_abm_sim.run \
  --config configs/fixtures/realistic_marketing_dataset.yaml \
  --output runs/realistic-sample
```

额外产物：

```text
runs/realistic-sample/dataset_validation.json
```

该样例使用 `tests/fixtures/datasets/` 下可提交的真实感 CSV 数据。配置中的相对数据路径会从配置文件所在目录解析，所以新克隆仓库后无需改路径。

## 8. 启动本地 Web 控制台

如果前面只安装了最小 CLI 依赖，先安装 web extra：

```bash
python -m pip install -e ".[dev,web,llm]"
```

启动本地单用户控制台：

```bash
. .venv/bin/activate
python -m llm_abm_sim.web --host 127.0.0.1 --port 8000 --artifact-root runs/web
```

或使用安装后的脚本：

```bash
llm-abm-web --host 127.0.0.1 --port 8000 --artifact-root runs/web
```

打开：

```text
http://127.0.0.1:8000
```

常用本地端点：

```text
GET  /api/health
GET  /api/provider/readiness
POST /api/datasets/validate
POST /api/runs
GET  /api/runs/{run_id}
GET  /api/runs/{run_id}/report-payload
GET  /api/runs/{run_id}/artifact/{name}
GET  /api/templates/users.csv
GET  /api/templates/edges.csv
```

### Web 控制台 mock provider demo

无网络演示流程：

1. 打开 `http://127.0.0.1:8000`。
2. 勾选 **Use mock provider for test/dev**。
3. 下载或直接使用本地模板：
   - `configs/templates/web_users.csv`
   - `configs/templates/web_edges.csv`
4. 上传 users 和 edges。
5. 点击 **Validate dataset**。
6. 点击 **Start run**。
7. 查看结果仪表盘并下载 allowlisted artifacts。

Mock provider 模式只用于测试/开发，会在 readiness、结果、metadata、payload 中明确标记为 mock，并避免网络调用和秘密暴露。

### Web 控制台 product provider 行为

如果没有勾选 **Use mock provider for test/dev**，Web 控制台会按产品模式运行：必须真实 Provider ready。缺少 live gate、凭证、可选 SDK 或 Provider metadata 时，运行会标记为 `blocked`，不会静默回退到离线规则基线。

这是预期的 fail-closed 行为，避免评审者误把离线 demo 当作真实 Provider 输出。

## 9. 可选 live LLM / Provider 模式

Live Provider 执行是手动且显式 opt-in 的。除非你确实要发起真实 Provider 调用，并且凭证已在仓库外配置好，否则不要运行本节命令。

先阅读完整 Provider 指南：

```text
docs/03-使用指南/provider-config.md
```

手动 live smoke 形态：

```bash
LLM_ABM_RUN_LIVE_LLM=1 python -m llm_abm_sim.run \
  --config configs/live/provider_smoke.yaml \
  --output runs/live-provider-smoke
```

Provider 测试也有门禁：

```bash
LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm -rs
```

凭证可以来自兼容的本地 Codex Provider 配置，或 Provider 配置指定的环境变量。秘密值必须留在 git、日志、文档、fixtures、运行产物和截图之外。

## 10. 运行验证检查

完整本地验证：

```bash
. .venv/bin/activate
ruff check .
ruff format --check .
mypy src
python -m py_compile $(find src tests -name '*.py' -print)
pytest -q
pytest -q tests/web/test_web_api.py
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
python -m llm_abm_sim.run --config configs/fixtures/realistic_marketing_dataset.yaml --output runs/realistic-sample
npx playwright test tests/playwright/web-console.spec.ts
```

默认测试离线运行。`pytest -q` 不会执行 live-provider 测试，除非显式选择 `live_llm` marker 并设置 gate。

## 11. 运行产物位置

CLI 默认运行：

```text
runs/sample/
```

真实感样例：

```text
runs/realistic-sample/
```

Web 控制台运行：

```text
runs/web/<run-id>/
```

常见产物：

```text
config.json
run_result.json
events.json
metrics_summary.json
step_records.csv
report.html
report_payload.json
graph_trace.json
input-builder.html
dataset_validation.json       # 仅数据集驱动运行
web_run_metadata.json         # 仅 Web 控制台运行
```

生成运行目录会被 git 忽略。私密/原始数据应放在本地忽略目录，例如 `data/raw/` 或 `data/processed/`，不要放入可提交 fixtures。

## 12. 故障排查

### `python3: command not found` 或 Python 版本太旧

```bash
brew install python
python3 --version
```

然后用该解释器重建 `.venv`。

### `pip install -e ".[dev,web,llm]"` 因 pip 太旧失败

```bash
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev,web,llm]"
```

### `npm ci` 因 lockfile 问题失败

仓库应包含 `package-lock.json`。干净克隆后优先使用：

```bash
npm ci
```

如果你确实修改了 Node 依赖，请在单独变更中更新 lockfile。

### Playwright 提示 Chromium 缺失

```bash
npx playwright install chromium
```

### 8000 端口被占用

换一个端口：

```bash
python -m llm_abm_sim.web --host 127.0.0.1 --port 8010 --artifact-root runs/web
```

然后打开 `http://127.0.0.1:8010`。

### Web product mode 显示 `blocked`

缺少 live Provider readiness 时这是预期行为。离线 Web demo 请勾选 **Use mock provider for test/dev**。如果要使用 live Provider，请确认：

- 启动 server 或命令的进程设置了 `LLM_ABM_RUN_LIVE_LLM=1`；
- 已安装 `llm` extra；
- Provider metadata 和 runtime credentials 在仓库外可用；
- 你没有期待 Web 控制台静默回退到离线 adapter。

### 数据集校验失败

检查：

- users 与 edges 是否使用支持的 CSV/JSON 格式；
- edge `source` / `target` 是否匹配 profile `user_id`；
- 必需列是否存在；
- 相对数据路径是否从配置文件所在目录解析。

可先从模板开始：

```text
configs/templates/web_users.csv
configs/templates/web_edges.csv
configs/templates/web_users.json
configs/templates/web_edges.json
```

### 生成报告无法打开

直接打开 HTML：

```bash
open runs/sample/report.html
```

如果路径不同，检查 CLI 的 `--output` 参数或 Web run ID。

## 13. 清理

在运行 Web server 的终端按 `Ctrl-C` 停止服务。

删除本地产物和依赖目录：

```bash
rm -rf runs test-results playwright-report blob-report
rm -rf node_modules
rm -rf .venv .ruff_cache .mypy_cache .pytest_cache
```

之后可按上文步骤重新创建环境。
