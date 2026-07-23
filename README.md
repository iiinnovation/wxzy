# wxzy — 个人中医学习系统

自用学习工具，由两个严格分离的部分组成：

- 文档处理控制面：PDF -> MinerU -> 清洗/结构化 -> 候选卡 -> 审核 -> 发布。
- 学习运行面：唯一 Owner -> 学习档案 -> 每日计划 -> 主动回忆 -> FSRS -> 薄弱点。

当前代码是已打通的卡片复习原型，目标产品和实施任务以 Superpowers 文档为准。

## 当前文档基线

| 入口 | 说明 |
|---|---|
| [`docs/superpowers/README.md`](docs/superpowers/README.md) | 文档地图和权威顺序 |
| [`docs/superpowers/PROJECT_RULES.md`](docs/superpowers/PROJECT_RULES.md) | 工程与模型执行规则 |
| [`docs/superpowers/specs/2026-07-22-wxzy-product-requirements.md`](docs/superpowers/specs/2026-07-22-wxzy-product-requirements.md) | PRD |
| [`docs/superpowers/specs/2026-07-22-system-design.md`](docs/superpowers/specs/2026-07-22-system-design.md) | 总体系统设计 |
| [`docs/superpowers/plans/2026-07-22-wxzy-implementation-plan.md`](docs/superpowers/plans/2026-07-22-wxzy-implementation-plan.md) | 分阶段任务计划 |

原型闭环：

```text
审核通过的卡片 JSON → FastAPI 导入 → 小程序今日到期 → 四档评分 → FSRS 更新 due
```

旧 MVP 冻结范围见 [docs/MVP_CARD_FSRS.md](docs/MVP_CARD_FSRS.md)，仅作原型历史依据。

## 目录

| 路径 | 说明 |
|---|---|
| `miniprogram/` | 微信原生小程序（今日 / 复习 / 书库 / 我的） |
| `server/` | FastAPI 后端 |
| `tools/` | MinerU 校验、候选卡片生成（本地） |
| `docs/superpowers/` | 当前产品、设计、规则与实施文档 |
| `docs/*.pdf` | 7 本本地源 PDF（gitignore，仅个人使用） |
| `data/` | 本地解析产物（gitignore） |

## 本地后端（推荐 SQLite 快速启动）

```bash
cd server
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export API_TOKEN=dev-token-change-me
# 默认 sqlite+pysqlite:///./wxzy.db
alembic -c alembic.ini upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

已有原型 SQLite 数据库需要先按 [Server 迁移说明](server/README.md)备份并 stamp baseline，
不能直接在有表、无 `alembic_version` 的库上执行首次 upgrade。

另开终端导入 seed（15 张 approved 样例卡）：

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/admin/cards/import-seed" \
  -H "Authorization: Bearer dev-token-change-me"
```

健康检查：

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/api/v1/stats/summary -H "Authorization: Bearer dev-token-change-me"
```

以上命令也可作为最小冒烟流程：导入后访问 `/api/v1/review/due`，调用
`/api/v1/review/answer`（`rating` 为 1 到 4），再次访问 due 和 stats，确认复习统计发生变化。
根级旧路径仍兼容但已在 OpenAPI 标为 deprecated。当前 `fsrs-v1` 为可升级的轻量 MVP
调度器，生产环境上线前需用标准 FSRS 参数实现替换并重新评测。

## Docker Compose（Postgres）

```bash
export API_TOKEN=dev-token-change-me
docker compose build api
docker compose up -d db
docker compose run --rm api alembic -c alembic.ini upgrade head
docker compose up -d api
curl -s -X POST "http://127.0.0.1:8000/api/v1/admin/cards/import-seed" \
  -H "Authorization: Bearer $API_TOKEN"
```

## 小程序

1. 用微信开发者工具打开目录 `miniprogram/`
2. 项目已配置当前 AppID；更换自己的小程序时只修改 `miniprogram/project.config.json`
3. 开发阶段可关闭「校验合法域名」
4. 在「我的」页设置：
   - API Base：本机 `http://127.0.0.1:8000`；真机改为电脑局域网 IP 或已备案 HTTPS 域名
   - Token：与服务端 `API_TOKEN` 一致

小程序包不含 API Token。首次打开或切换环境时，必须在「我的」页保存服务端地址和 Token；配置仅保存在当前设备。

不要把仓库根目录作为微信小程序项目打开；根目录的历史 `project.config.json` 不是正确项目配置。目标认证完成后，生产小程序将使用微信登录而不是手填 Token。

## 导入自己的审核卡片

JSON 格式同 `server/seed_data/candidates_offline_v1.json`（`cards` 数组）。
仅 `status=approved` 会进入正式复习库。

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/admin/cards/import" \
  -H "Authorization: Bearer dev-token-change-me" \
  -F "file=@/path/to/approved_cards.json"
```

## 质量门禁

开发环境安装完成后，在仓库根目录运行唯一质量命令：

```bash
pip install -r server/requirements-dev.txt
PYTHON=server/.venv/bin/python tools/quality-gate.sh
```

它检查 Python 3.12、Ruff、Mypy、pytest/coverage、小程序 JavaScript/JSON 和 Markdown
本地链接。GitHub Actions 运行同一个脚本，不需要 PDF、数据库、MinerU/Qwen Key 或其他密钥。

## 安全

- 不要把 `AppSecret`、数据库密码、`API_TOKEN`、MinerU/Qwen Key 写进小程序代码或 git
- 开发环境显式使用 `AUTH_MODE=dev_token`；生产环境必须使用 `APP_ENV=production`、`AUTH_MODE=wechat` 及服务端微信 AppID/AppSecret，并走 HTTPS 合法域名

## 明确不做

多用户产品、社交/排行榜、公开牌组、支付、诊疗、小程序直连 MinerU/Qwen。向量检索和完整 PDF 阅读是否增加，待卡片与个人学习闭环稳定后决定。
