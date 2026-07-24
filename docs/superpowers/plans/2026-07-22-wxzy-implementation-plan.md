# wxzy 分阶段实施计划

状态：Active plan
日期：2026-07-22
关联规格：

- [`../specs/2026-07-22-wxzy-product-requirements.md`](../specs/2026-07-22-wxzy-product-requirements.md)
- [`../specs/2026-07-22-system-design.md`](../specs/2026-07-22-system-design.md)
- [`../specs/2026-07-22-document-processing-design.md`](../specs/2026-07-22-document-processing-design.md)
- [`../specs/2026-07-22-learning-miniprogram-design.md`](../specs/2026-07-22-learning-miniprogram-design.md)

## 1. 使用方式

后续模型每次只选择一个状态为 `[ ]` 且依赖已满足的任务执行。开始时改为 `[~]`，验证全部通过后改为 `[x]`；阻塞时改为 `[!]` 并记录证据。不得一次把一个阶段的所有任务同时标记完成。

状态：

- `[ ]` 未开始。
- `[~]` 进行中。
- `[x]` 已完成并验证。
- `[!]` 阻塞，必须附原因和下一条件。

每个任务的完成报告必须包含：修改文件、验证命令、关键输出、数据迁移影响、剩余风险。

## 2. 阶段总览

| 阶段 | 目标 | 主要依赖 | 退出条件 |
|---|---|---|---|
| P0 | 工程与质量基线 | 当前原型 | 测试、lint、迁移、CI 可运行 |
| P1 | 领域模型和数据分离 | P0 | User/Content/Enrollment/Review 分离 |
| P2 | 唯一 Owner 与学习档案 | P1 | 微信登录和 onboarding 闭环 |
| P3 | 文档流水线工程化 | P0 | fixture 端到端可恢复 |
| P4 | 704 页全量解析 | P3 | 704/704 terminal 状态 |
| P5 | 候选卡、审核和发布 | P3、P1 | 版本化发布包可幂等导入 |
| P6 | 个性化学习引擎 | P1、P2、P5 | 标准 FSRS 和每日计划闭环 |
| P7 | 小程序产品化 | P2、P6 | 四个 Tab 和学习会话真机可用 |
| P8 | 部署与可靠性 | P0–P7 | HTTPS/Postgres/备份/监控完成 |
| P9 | 两周个人校准 | P7、P8 | 真实数据驱动参数和内容改进 |

P3/P4 可与 P1/P2 并行推进，但 P5 的发布导入必须基于 P1 的目标数据模型。

## 3. 全局质量门禁

阶段任务完成前，按影响范围执行：

```bash
# Python（P0 建立后）
ruff check server tools
ruff format --check server tools
pytest -q

# 小程序基础检查
node --check miniprogram/app.js
node --check miniprogram/services/*.js
# 所有页面 JS 逐一 node --check；所有 JSON 严格解析

# 数据库
alembic upgrade head
alembic downgrade -1
alembic upgrade head

# 微信
微信开发者工具：清缓存并编译
人工/自动化：登录 -> 今日 -> 显示答案 -> 评分 -> 统计变化
```

全量文档阶段还必须运行 coverage 和 quality gate，不能只运行 Python 单元测试。

---

# P0 工程与质量基线

## P0-T01 建立 Superpowers 文档基线

状态：`[x]`

产物：`docs/superpowers/` 下的入口、规则、PRD、设计和计划；更新入口引用后完成。

验收：文档链接无断链，旧文档明确为历史参考。

## P0-T02 建立 Python 工程配置

状态：`[x]`

目标：统一依赖、格式、lint 和测试入口。

完成报告（2026-07-22）：

- 修改文件：新增根级 `pyproject.toml`、`server/requirements-dev.txt`、`server/tests/`、`tools/tests/` 和 `tools/__init__.py`；更新运行依赖范围、Server README、Python 缓存忽略项，并对现有 Python 文件执行 Ruff 机械格式化。
- 行为覆盖：health 公共访问、Bearer Token 缺失/错误/正确、过渡调度器四档评分/经过天数/非法评分、候选卡稳定 ID、HTML 表格解析和依赖清单一致性。
- 验证环境：使用 uv 管理的 CPython `3.12.12` 在 `/tmp/wxzy-p0-t02-py312` 创建全新虚拟环境，并从 `server/requirements-dev.txt` 完整安装依赖；现有 Python 3.14 开发环境也通过相同门禁。
- 验证命令：`ruff check server tools`、`ruff format --check server tools`、`mypy server/app tools`、`pytest -q`、`coverage run -m pytest -q && coverage report`、`pip check`、`python -m compileall -q server/app tools`、`git diff --check`。
- 关键输出：Ruff 全通过，23 个文件格式正确，Mypy 检查 20 个源文件无问题，pytest `13 passed`，coverage 分支基线 `23%`，`pip check` 无破损依赖。
- 数据迁移影响：无 schema、迁移或业务数据变更；API 测试固定使用命名共享内存 SQLite，不读取或写入 `server/wxzy.db`。
- 恢复点：P0-T02 已完成；下一个满足依赖的串行任务是 P0-T03 数据库迁移基线，文档流水线可在另一工作流从 P3-T01 开始。

依赖决策：

| 依赖 | 维护/许可证 | 体积影响 | 采用原因与替代方案 |
|---|---|---|---|
| pytest + httpx | 活跃；MIT / BSD-3-Clause | 仅开发环境，小 | FastAPI 契约测试生态成熟；标准库 unittest 需要更多夹具和传输适配 |
| Ruff | 活跃；MIT | 单个原生开发工具，中 | 同时承担 lint/import/format；替代 Black + Flake8 会增加工具和配置面 |
| coverage.py | 活跃；Apache-2.0 | 仅开发环境，小 | 直接提供分支覆盖基线；pytest-cov 只是其 pytest 包装层，暂不增加 |
| Mypy + types-requests | 活跃；MIT / Apache-2.0 | 仅开发环境，中 | Python 原生静态检查且适配现有类型标注；Pyright 需要额外 Node 工具链 |
| requests + PyMuPDF | 活跃；Apache-2.0 / AGPL-3.0 或商业许可 | 仅 `documents` 可选组，PyMuPDF 较大 | 延续现有上传和 PDF 抽页实现，不进入 Server 运行依赖；P3 需继续核对 PyMuPDF 分发许可，pypdf 是纯 Python 备选 |

剩余风险：pytest 有 3 条已知弃用告警；`on_event/create_all` 由 P0-T03 的 lifespan/迁移启动方式消除，Starlette TestClient 的 httpx 迁移在 P0-T06 固定 CI 依赖时复核。当前 23% 只是首个可量化基线，P0-T06 前不作为覆盖率阈值；文档工具全流程测试属于 P3。

计划文件：

- 新增根或 `server/pyproject.toml`，明确 Python 3.12、Ruff、pytest 配置。
- 拆分 `server/requirements.txt` 与开发依赖，或使用统一锁定方案。
- 新增 `server/tests/`、`tools/tests/`。

工作：

1. 固定运行依赖的兼容版本范围。
2. 增加 `pytest`、`httpx`、`ruff`、`coverage`；类型检查工具在本任务评估后固定。
3. 建立第一个 health/auth/review scheduler 测试。
4. 将当前代码格式化，避免混入行为重构。

验证：Ruff check/format 和 `pytest -q` 在干净环境通过。

## P0-T03 建立数据库迁移基线

状态：`[x]`

需求：SP-040。

完成报告（2026-07-22）：

- 修改文件：新增 `server/alembic.ini`、`server/migrations/` 和 migration 集成测试；更新依赖、Dockerfile、Server README、测试 schema fixture，并从 `server/app/main.py` 移除生产 `create_all()`。
- baseline：revision `20260722_0001` 精确描述 `books/cards/review_states/review_logs`、索引、唯一约束、外键和 UTC 时间列；SQLite/PostgreSQL 的 `alembic check` 均返回 `No new upgrade operations detected`。
- SQLite 验证：空库 `upgrade -> downgrade -> upgrade` 通过；合成 legacy 库 `stamp -> upgrade` 保留 `2/15/15/4`；真实 `server/wxzy.db` 副本也保留 `2/15/15/4`，revision 正确。
- PostgreSQL 验证：Docker PostgreSQL 16 独立测试库完成 `upgrade -> downgrade -> upgrade -> check`；最终包含 revision、四张业务表、13 个索引和 3 个外键。
- 应用验证：独立进程访问 `/health` 后 SQLite 文件仍不存在，证明生产启动不再隐式建表；测试环境只在 autouse fixture 中显式 `create_all/drop_all`。
- 全量命令：Python 3.12 下 Ruff、format、Mypy 22 个源文件、`pip check`、`docker compose config --quiet` 和含 PostgreSQL 的 `pytest -q` 全部通过，pytest 输出 `17 passed`。
- 存量保护：仓库原库未 stamp、未迁移，SHA-256 仍为 `843175f98cd70f09d0e0321561fafb7fdd7210d1a2adb471f851db0dca7680a5`，计数仍为 `2/15/15/4`，`due_now=11`。
- 数据与回滚：baseline 本身不改业务行；现有库采用“备份 -> stamp -> check -> upgrade”。对有数据的 baseline 库禁止用 `downgrade -1` 回滚，因为它会删除四张业务表；回滚必须恢复迁移前备份。
- 依赖决策：Alembic 活跃维护、MIT、纯 Python 且体积小（附带 Mako）；它与 SQLAlchemy 原生集成并支持双数据库 autogenerate/check，优于另加 Liquibase/JVM 或自建 SQL 版本表。
- 剩余风险：Dockerfile 已复制迁移文件且 Compose 配置有效，但 `python:3.12-slim` 因 Docker Hub 连续 EOF 未能完成镜像构建；这是外部验证缺口，P0-T06 CI 仍需重跑。pytest 只剩 Starlette TestClient/httpx 的 1 条上游弃用告警。
- 恢复点：P0-T03 已完成，专用 PostgreSQL 测试库已删除、容器已停止；下一串行任务是 P0-T04 统一错误、request ID 和脱敏日志。

计划文件：

- `server/alembic.ini`
- `server/migrations/env.py`
- `server/migrations/versions/*_baseline.py`
- `server/app/main.py`

工作：捕获当前表结构为 baseline；测试空 SQLite/PostgreSQL 升级；生产启动移除 `create_all` 依赖，测试环境可显式创建 fixture 库。

验收：全新库可 upgrade；现有 `wxzy.db` 的 schema 可 stamp/migrate；升级不删除 15 张样例卡。

## P0-T04 统一错误、请求 ID 和日志

状态：`[x]`

完成报告（2026-07-22）：

- 修改文件：新增 `server/app/core/errors.py`、`server/app/core/logging.py`、`server/app/core/__init__.py`；更新 `main.py`、auth、review/import 服务和 `ErrorOut` schema；新增错误契约测试。
- 错误契约：401/404/422/409/500 均返回 `code/message/request_id/details`，并在 `X-Request-ID` 响应头回传同一 ID；422 只返回 location/message/type，不回显 body/input。
- 业务映射：卡片不存在 -> `CARD_NOT_FOUND`/404；无效导入 -> `INVALID_IMPORT_PAYLOAD`/400；数据库唯一冲突 -> `DATABASE_CONFLICT`/409；未知异常 -> `INTERNAL_ERROR`/500。
- 日志与安全：结构化记录 `request_id/route/status/duration_ms/method`；关闭 Uvicorn query-bearing access log；递归脱敏 Authorization、Token、Secret、Password、URL query、原文摘录和异常敏感文本，500 日志只保留异常类型。
- 自动验证：Python 3.12 下 `23 passed, 1 skipped, 1 warning`；Ruff check/format、Mypy 25 个源文件、pip check、git diff check 全通过；coverage 分支基线为 `29%`。
- 运行验证：本机 `http://127.0.0.1:8000` 实测 health 200、带 request ID 的 401/404/422；结构化日志无 query、Token 或原文；书库鉴权请求仍返回 200。
- 数据迁移影响：无 schema、migration 或业务数据写入；测试继续使用独立内存 SQLite，既有 2 本书/15 张卡数据未改变。
- 剩余风险：唯一告警来自 Starlette TestClient/httpx 上游弃用，待 P0-T06 固定 CI 依赖时处理；用户 ID 尚未建立，日志暂不记录 user_id，待 P1/P2 身份任务补入。
- 恢复点：P0-T04 已完成；下一任务是 P0-T05，把新业务接口挂到 `/api/v1`，保留旧路由兼容期。

计划文件：`server/app/core/errors.py`、`server/app/core/logging.py`、`server/app/main.py`、API tests。

工作：建立 `{code,message,request_id,details}`；添加 request-id middleware；Authorization/Token/原文脱敏；把已知 ValueError 映射为稳定业务错误。

验收：401、404、422、409、500 的响应契约测试通过，日志无 Token。

## P0-T05 建立 API v1 路由骨架

状态：`[x]`

完成报告（2026-07-22）：

- 修改文件：新增 `server/app/api/`、`server/app/api/v1/router.py` 和 `server/tests/test_api_v1.py`；`main.py` 同时挂载 v1 聚合路由与 deprecated 兼容路由。
- 路由结果：`/health` 保持根路径；books/cards/review/stats/admin 同时提供 `/api/v1/...` 与原根级路径，两个版本复用同一业务函数，没有复制实现。
- OpenAPI 验证：v1 和兼容路径全部存在；v1 操作未标 deprecated，旧操作全部标记 deprecated；所有 operation ID 非空且全局唯一。
- 行为验证：v1/旧 `/books` 在同一 Token 下返回相同 2 本书/15 张卡统计；v1 无 Token 继续使用 P0-T04 四字段错误契约。
- 日志验证：实际 path 不含 query 地记录，`/api/v1/books` 与 `/books` 可在结构化日志中区分。
- 自动门禁：Python 3.12 下 `26 passed, 1 skipped, 1 warning`；Ruff、format、Mypy 28 个源文件、compileall 和 git diff check 通过；coverage 分支基线为 `30%`。
- 运行验证：本机 `http://127.0.0.1:8000/api/v1/books` 返回 200，与旧路径 payload 一致；后端已重启并保持运行。
- 数据迁移影响：无数据库或内容变更；小程序仍调用兼容路径，迁移到 v1 留给 P7 API 适配任务。
- 剩余风险：兼容路径暂不设置删除日期；领域目标路径最终会演进为 catalog/learning 结构，需在 P1/P7 规格下新增而不是静默改义。
- 恢复点：P0-T05 已完成；下一任务 P0-T06 建立单一质量脚本和无密钥 CI。

计划文件：`server/app/api/v1/router.py` 及兼容路由。

工作：保留 `/health`；把新接口统一置于 `/api/v1`；旧 `/books`、`/review/*` 在迁移期保留并标记 deprecated，不立即破坏原型。

验收：OpenAPI 同时包含 health、v1 和兼容接口；无重复 operation ID。

## P0-T06 建立一键质量门禁和 CI

状态：`[x]`

完成报告（2026-07-22）：

- 修改文件：新增 `tools/quality-gate.sh`、`tools/quality_checks.py`、检查器测试和 `.github/workflows/quality.yml`；更新依赖、coverage 阈值与根 README。
- 单一门禁：检查 Python 3.12+、Ruff lint/format、Mypy、测试存在性、pytest、coverage、6 个小程序 JS、8 个本地 JSON 和 13 份 Markdown 本地链接。
- 成功证据：全新 Python 3.12 环境执行 `PYTHON=... tools/quality-gate.sh` 返回 PASS；`30 passed, 1 skipped, 1 warning`，分支 coverage `33%`，高于固定的 20% 阈值。
- 失败证据：`/tmp` 非法 JSON 与两个空测试目录分别返回 exit code 1；单测另覆盖重复 JSON key 和 Markdown 断链，证明 gate 会正确失败。
- CI：GitHub Actions 使用 Python 3.12 + Node 20，权限仅 `contents: read`，安装公开 requirements 后运行同一个 shell 脚本；默认不启动 PostgreSQL，也不读取 PDF、data、本地数据库或任何 Key。
- 解析依赖：`markdown-it-py` 活跃维护、MIT、纯 Python 且体积小；用 AST 提取链接，替代易误判括号/转义的手写正则。
- 文档与启动：README 已改为先 Alembic 后启动，v1 示例和 Docker 迁移顺序正确，并公开唯一质量命令。
- 数据迁移影响：无数据/schema 变更；coverage、pytest、Mypy、Ruff 缓存与报告均由 `.gitignore` 排除。
- 剩余风险：workflow 文件已本地解析但尚未随本轮改动 push，因此没有远端首个 run；Docker Hub EOF 导致 P0-T03 镜像构建仍待 CI/网络恢复后复验；TestClient/httpx 保留 1 条上游告警。
- 恢复点：P0-T06 与 P0 阶段完成；下一串行任务是 P1-T01 唯一 User 与 LearningProfile。

计划文件：`tools/quality-gate.sh`、CI workflow、README。

工作：串联 Ruff、pytest、JS 语法、JSON 解析、文档链接检查；CI 不依赖私有 PDF、MinerU 或模型 Key。

验收：本地脚本和 CI 在无密钥环境通过；缺测试或解析错误时正确失败。

### P0 退出门禁

- [x] 自动测试和 lint 可在全新 Python 3.12 环境安装运行。
- [x] SQLite/PostgreSQL 数据库迁移可升级、回退和检查 drift。
- [x] 新接口有 `/api/v1`、统一错误、request ID 和脱敏日志。
- [x] 后续模型有单一 `tools/quality-gate.sh` 命令。

P0 完成检查点：T01–T06 全部完成；当前后端保持在 `http://127.0.0.1:8000` 运行，原型数据库仍为 2 本书、15 张卡、15 个 review state 和 4 条 review log。P1 开始后，任何新表或旧表变化都必须新增 Alembic revision，不能修改 baseline。

---

# P1 领域模型与数据分离

## P1-T01 建立唯一 User 和 LearningProfile

状态：`[x]`

需求：AUTH-001、PROFILE-001–004。

完成报告（2026-07-22）：

- 修改文件：新增 `server/app/identity/`、UTC SQLAlchemy 类型、`20260722_0002` migration 和身份测试；更新模型注册、迁移集成测试、Server 迁移说明与系统设计约束。
- 领域结果：建立 `User/UserSession/LearningProfile`；Owner 默认同时创建一份日常学习档案；Session 只持久化唯一 Token hash；profile 更新保留稳定 ID、创建时间、User 和 Session 历史。
- 约束与校验：SQLite/PostgreSQL 的部分唯一索引均拒绝第二个 active Owner 并允许多个 disabled Owner；IANA 时区、5–240 分钟、7 天布尔数组、0.70–0.99 留存率、0–100 新卡上限和 1–5 学科评分由 Pydantic 契约校验，核心数值另有数据库 check constraint。
- 时间语义：新身份领域的时间写入必须 timezone-aware，统一转 UTC；自定义类型恢复 SQLite 丢失的 UTC tzinfo，Owner/default profile 的 UTC round-trip 已验证。
- SQLite/migration 验证：空库 `upgrade head -> downgrade 0002 -> downgrade base -> upgrade head -> check`、legacy `stamp 20260722_0001 -> upgrade head -> check` 均通过；迁移生成的唯一 Owner 约束有独立断言。
- PostgreSQL 验证：Docker PostgreSQL 16 独立库完成相同升级/约束/两级回退/再升级/drift 流程，输出 `1 passed, 3 deselected`；测试库已删除且容器已停止。
- 全量门禁：`tools/quality-gate.sh` PASS；Ruff、format、Mypy 36 个源文件、小程序 JS/JSON 和 13 份 Markdown 链接通过；pytest `44 passed, 1 skipped, 1 warning`，分支 coverage `38%`。
- 数据迁移影响：revision 只新增三个空表，不创建或关联 legacy Owner；真实 `server/wxzy.db` 未 stamp、未 upgrade，SHA-256 仍为 `843175f98cd70f09d0e0321561fafb7fdd7210d1a2adb471f851db0dca7680a5`，计数仍为 `2/15/15/4`。
- 回滚与风险：已有原型库必须备份后执行 `stamp 20260722_0001 -> upgrade head -> check`，禁止 `stamp head`；未来 identity 表产生数据后，`downgrade 20260722_0001` 会删除身份/Session/profile 数据，只能通过备份恢复。微信换登、Session 签发和 profile HTTP/审计按范围留给 P2，legacy Owner 和学习历史归属留给 P1-T03–T05。
- 恢复点：P1-T01 已完成并验证；下一个串行任务是 P1-T02 文档和内容目录模型。

计划文件：`server/app/identity/models.py`、schemas/services、migration、tests。

工作：创建 User、UserSession、LearningProfile；数据库约束最多一个 active Owner；时区和时间预算校验；建立默认 profile factory。

范围外：不在本任务签发 Session Token、不调用微信、不新增 HTTP API，也不迁移现有复习表的用户归属；这些分别由 P2-T02、P2-T03 和 P1-T03–T05 完成。

输入输出：输入为经过 Pydantic 校验的 Owner/档案值；输出为三个新表、可直接单测的 Owner/profile 领域服务和默认档案。JSON 字段使用固定 schema，不延续无约束 JSON 字符串。

验证：模型/服务单测、第二个 active Owner 的数据库冲突、空 SQLite 迁移升级/回退/再升级、legacy 副本数据对账、Alembic drift check、UTC round-trip 和全量质量门禁。

验收：第二个 active Owner 被拒绝；档案更新不删除历史；UTC 字段一致。

## P1-T02 建立文档和内容目录模型

状态：`[x]`

需求：CAT-001–006、DOC-001。

完成报告（2026-07-22）：

- 修改文件：新增 `server/app/catalog/`、`20260722_0003_catalog.py` 和 catalog 测试；将兼容 Book/Card ORM 移入 catalog 模块；更新系统设计、任务边界与 SQLite/PostgreSQL migration 集成测试。
- 目录模型：建立 Document、DocumentVersion、Chapter、DocumentChunk、CardSource；Card 新增 `content_revision/content_hash` 和结构化 `answer_points/tags`，同时保留 legacy 主键、外键和旧字段供现有 API 过渡。
- 业务规则：`document_key` 稳定唯一，同一 Document 的 SHA256 版本登记幂等；文件名拒绝路径；章节父子与 chunk 必须属于同一 version 且页范围合法；只有 `quality_status=ready` 的 chunk 可成为发布卡来源，新目录写入不创建 ReviewState。
- 来源契约：一张 Card 可按 `citation_order` 引用多个 chunk；持久层和输出明确区分 0-based PDF index、1-based PDF number 与字符串印刷页标签；普通来源契约不含 `source_file_name/source_text/cleaned_text/processing_version/local_path`。
- 自动验证：`tools/quality-gate.sh` PASS；Ruff、format、Mypy 41 个源文件、小程序 JS/JSON 和 13 份 Markdown 链接通过；pytest `50 passed, 1 skipped, 1 warning`，分支 coverage `47%`。
- 迁移验证：空 SQLite 和 Docker PostgreSQL 16 均完成 `upgrade head -> downgrade 0003 -> downgrade base -> upgrade head -> check`；PostgreSQL 专用输出 `1 passed, 3 deselected`，测试库已删除、容器已停止。
- 真实数据迁移：停服后备份为 `server/backups/wxzy-before-20260722-0003.db`，备份 SHA-256 为 `843175f98cd70f09d0e0321561fafb7fdd7210d1a2adb471f851db0dca7680a5`；真实库已按 `stamp 0001 -> upgrade head -> check` 升至 `20260722_0003`，`PRAGMA integrity_check=ok`，业务计数仍为 `2/15/15/4`，15 张 Card 均为 revision 1，Documents/CardSources 暂为 0。
- 运行验证：最新代码重启后 health、books、cards 和 stats 均返回 200；书籍仍为 2、approved cards 15、due 11、reviewed today 4，结构化日志不含 Token。
- 回滚与风险：恢复升级前状态优先停服并还原上述备份；一旦 P1-T05/P5 写入目录数据，不得直接 downgrade 0003，因为它会删除目录表和 Card 新列。现有 15 张卡尚未回填 Document/Chunk/Source，catalog HTTP API 和 revision 冲突导入分别留给 P7/P5。
- 恢复点：P1-T02 已完成并验证；下一个串行任务是 P1-T03 Enrollment 和个人 ReviewState。

计划文件：`server/app/catalog/models.py`、migration、schemas、tests。

工作：Document、DocumentVersion、Chapter、DocumentChunk、Card、CardSource；Card 支持 content_revision；来源页字段区分 PDF 页和印刷页。

范围外：不扫描或解析 PDF、不迁移现有 2 本书/15 张卡、不新增目录 HTTP API，也不实现 publication importer；这些分别属于 P3/P4、P1-T05、P7/P5。

兼容策略：保留现有 `books/cards` 表、主键和兼容 API；将 Book/Card 模型迁入 catalog 模块，并以可空/有默认值的新列扩展 Card。Document/Version/Chapter/Chunk/CardSource 使用新表，legacy 来源字段到 P1-T05 再对账回填。

验证：同一文档 SHA 重复登记幂等；Card 可按稳定顺序引用多个 ready chunk；来源契约同时给出 0-based PDF index、1-based PDF number 和独立印刷页标签，且不包含原文全文、文件路径或处理字段；SQLite/PostgreSQL migration 升降级、legacy 对账和 drift check 通过。

验收：一张卡可引用多个块；相同文档 hash 不重复创建版本；来源契约测试通过。

## P1-T03 建立 Enrollment 和个人 ReviewState

状态：`[x]`

需求：ENROLL-001–004、REV-005。

完成报告（2026-07-22）：

- 修改文件：新增 `server/app/learning/`、`20260722_0004_enrollment_review_state.py` 和 learning 测试；更新模型注册、系统设计、任务边界与双数据库迁移测试。
- 领域结果：建立 CardEnrollment 与 CardReviewState，数据库分别保证 `(user_id, card_id)` 唯一；enrollment 支持 queued/active/suspended/retired 与 manual/chapter/plan 来源，个人状态持有 UTC due、调度参数和 algorithm_version。
- 引入语义：发布 Card 本身不创建 enrollment/state；`enroll_card` 只创建 queued enrollment；`introduce_enrollment` 才原子转 active 并创建默认 `new` 状态。重复加入和重复引入幂等，不产生第二行。
- 生命周期：仅 `active <-> suspended` 可暂停/恢复，retired 保持终态；暂停和退出都从 due 查询排除，但不删除 CardReviewState，disabled Owner 和已撤回 Card 同样不进入 due。
- 核心验收：测试发布 100 张 Card 后 enrollment/state/due 均为 0；加入前 5 张后仍为 0 due；计划首次引入 5 张后恰有 5 条个人状态和 5 due，其余 95 张无个人学习行。
- 自动验证：`tools/quality-gate.sh` PASS；Ruff、format、Mypy 46 个源文件、小程序 JS/JSON 和 13 份 Markdown 链接通过；pytest `55 passed, 1 skipped, 1 warning`，分支 coverage `49%`。
- 迁移验证：空 SQLite 与 Docker PostgreSQL 16 均完成 `upgrade head -> downgrade 0004 -> downgrade 0003 -> downgrade base -> upgrade head -> check`；PostgreSQL 专用输出 `1 passed, 3 deselected`，测试库已删除、容器已停止。
- 真实数据迁移：停服后备份 `server/backups/wxzy-before-20260722-0004.db`，SHA-256 为 `120f97ce39655ebc4172e1eea5e2bcd25539fa0ade92b194d07696e3ed7e99c7`；真实库已由 0003 升至 `20260722_0004`，`PRAGMA integrity_check=ok`，旧业务计数仍为 `2/15/15/4`，新 enrollment/state 表为 0。
- 运行验证：最新后端重启后 health、books、legacy due 和 stats 均返回 200；旧统计仍为 2 本、15 approved cards、11 due、4 reviewed today，结构化日志不含 Token。
- 回滚与风险：恢复 0003 优先停服并还原上述备份；产生个人学习数据后不得直接 downgrade 0004。兼容 `review_states/review_logs` 尚未归属 User，新 due 服务尚未接入 HTTP，标准 FSRS 和 legacy 数据迁移分别留给 P6-T01 与 P1-T05。
- 恢复点：P1-T03 已完成并验证；下一个串行任务是 P1-T04 StudySession、ReviewAttempt 和 CardIssue。

计划文件：`server/app/learning/models.py`、migration、tests。

工作：CardEnrollment、CardReviewState；唯一 `(user_id, card_id)`；发布卡不会自动创建 ReviewState；首次引入后才创建。

范围外：不删除或改写兼容期的 `review_states/review_logs`，不实现标准 FSRS adapter、StudySession 或 ReviewAttempt；旧表归属迁移由 P1-T05，算法替换由 P6-T01。

验证：新表迁移可升级/回退；加入学习只创建 queued enrollment；首次引入才创建一条带 `user_id/card_id` 的新状态；重复加入/引入幂等；暂停、恢复、退出保留状态和历史；发布卡未加入学习时 due 查询为 0。

验收：导入 100 张发布卡后 due 仍为 0；加入 5 张后只有计划引入的卡进入学习。

## P1-T04 建立 StudySession、ReviewAttempt 和 CardIssue

状态：`[x]`

完成报告（2026-07-22）：

- 修改文件：扩展 `server/app/learning/`，新增 `20260722_0005_study_review_issues.py` 与复习尝试测试；更新系统设计和双数据库迁移测试。
- 领域结果：建立 StudySession、ReviewAttempt、CardIssue；会话记录 planned/active/completed/interrupted 生命周期、时间预算和任务计数，作答固定记录用户、会话、卡片 revision、行为信号、due 与完整状态前后快照。
- 幂等与并发：数据库唯一 `(user_id, client_attempt_id)`；相同上下文重放返回首次行，不同 session/card/revision/rating 返回冲突。服务先占用唯一键再更新 CardReviewState，SQLite 以 `BEGIN IMMEDIATE` 短退避串行写入，PostgreSQL 以 `FOR UPDATE` 锁定状态。
- 输入边界：answer payload 仅允许最多 16 个标量字段、单字符串 4000 字符、总计 8192 UTF-8 字节；卡片问题覆盖事实错误、来源错误、过大、过难、表述不清、概念混淆，并保留提交时 revision。
- 核心验收：正常提交、网络重放、冲突重放、SQLite 双线程和 PostgreSQL 双连接测试均通过；并发同键只产生 1 条 Attempt、状态只推进 1 次，会话生命周期和六类 CardIssue 均有测试。
- 自动验证：`tools/quality-gate.sh` PASS；Ruff、format、Mypy 47 个源文件、小程序 JS/JSON 和 13 份 Markdown 链接通过；pytest `62 passed, 2 skipped, 1 warning`，分支 coverage `54%`。两个 skip 均为默认未配置 PostgreSQL 的显式集成测试。
- 迁移验证：空 SQLite 与 Docker PostgreSQL 16 均完成 `upgrade head -> downgrade 0005 -> downgrade 0004 -> downgrade 0003 -> downgrade base -> upgrade head -> check`；PostgreSQL 迁移和并发专项为 `2 passed`，临时测试库已删除、容器已停止。
- 真实数据迁移：停服后备份 `server/backups/wxzy-before-20260722-0005.db`，SHA-256 为 `5d897efe3adbfc3444bcf5ba74f4618166e96549a71a93f03cb5524e09fc2e51`；真实库已升至 `20260722_0005`，`PRAGMA integrity_check=ok`，旧业务计数仍为 `2/15/15/4`，三张新表均为 0。
- 运行验证：后端重启后 health、books、legacy due 和 stats 均返回 200；旧统计仍为 2 本、15 approved cards、11 due、4 reviewed today，结构化日志不含 Token。
- 回滚与风险：恢复 0004 优先停服并还原上述备份；产生 session/attempt/issue 数据后不得直接 downgrade 0005。本任务未新增 HTTP API、未实现标准 FSRS，分别留给 P6-T03 和 P6-T01。
- 恢复点：P1-T04 已完成并验证；下一个串行任务是 P1-T05 迁移现有原型数据。

需求：REV-004、REV-006、REV-007。

工作：记录 session、client_attempt_id、rating、response_ms、hint/reveal、前后状态和内容 revision；CardIssue 支持错误类别。

范围补充：复习尝试只记录调度器产出的目标状态，不在本任务实现标准 FSRS；幂等键按
`(user_id, client_attempt_id)` 唯一，重放必须返回首次结果，冲突上下文必须报错。

事务设计：在同一事务中锁定个人复习状态并插入唯一尝试，再写入目标状态；唯一键冲突回滚后
读取首次提交的尝试。SQLite 依赖单写事务，PostgreSQL 使用 `FOR UPDATE`，两者均由唯一约束
作为最终并发保障。

验收：重复 client_attempt_id 返回同一结果；并发提交只产生一条 Attempt。

## P1-T05 迁移现有原型数据

状态：`[x]`

完成报告（2026-07-23）：

- 修改文件：新增 `20260723_0006_migrate_legacy_learning.py` 和 `tools/report_legacy_migration.py`；扩展迁移集成测试与系统设计/实施计划。
- 迁移结果：检测到 legacy cards 时创建或复用唯一 active `Legacy Owner` 及默认 LearningProfile；15 张有 ReviewState 的卡建立 active enrollment 和 15 条个人 CardReviewState；保留 due、stability、difficulty、reps、lapses、state、algorithm_version 和 rating。
- 历史对账：4 条 ReviewLog 迁移为 4 条 ReviewAttempt，使用稳定 `legacy-review-log-{id}` 幂等键，归入 1 个已完成 legacy review session；legacy 四张表不删除、不改写。enrollment 来源因原型无来源字段统一保守记为 `manual`，卡片原有 chapter/section 保持不变。
- 幂等与回滚：0006 重复执行按 user/card 和稳定 attempt key 跳过已存在行；downgrade 发现任一 enrollment/state/session/attempt/issue 或 UserSession 时直接拒绝，要求停服恢复备份。
- 核心验收：合成 legacy SQLite 对账为 `2/15/15/4`，新表为 `1 owner/1 profile/15 enrollment/15 state/1 session/4 attempt`；due/reps/lapses 逐卡一致；迁移回退保护测试通过。
- 对账工具：`tools/report_legacy_migration.py` 输出 revision、Owner、legacy/new 状态差异、legacy Attempt key 缺失/多余项和孤儿计数；真实库报告 `ok=true`。
- 自动验证：`tools/quality-gate.sh` PASS；Ruff、format、Mypy 49 个源文件、小程序 JS/JSON 和 13 份 Markdown 链接通过；pytest `63 passed, 2 skipped, 1 warning`，分支 coverage `52%`。两个 skip 均为默认未配置 PostgreSQL 的显式集成测试，PostgreSQL 16 空库升级/逐级回退专项另行 `1 passed`。
- 真实数据迁移：停服后备份 `server/backups/wxzy-before-20260723-0006.db`，SHA-256 为 `6fe64ff09a0ea7c032323168997082f4021acccc42c87b5144dc6cd1f094dabc`；真实库已升至 `20260723_0006`，`PRAGMA integrity_check=ok`，对账无差异、无孤儿。
- 运行验证：后端重启后 health、books、legacy due 和 stats 均返回 200；旧兼容 API 仍可访问，当前日期变化导致 due 统计按新日期重新计算。
- 恢复点：P1-T05 已完成并验证；下一个串行任务是 P1-T06 拆分后端领域服务。

计划文件：data migration、迁移测试、迁移报告脚本。

工作：创建 legacy Owner；迁移 2 本书、15 张卡、ReviewState 和 ReviewLog；建立 enrollment；保持 due、reps、lapses 和来源。

范围补充：新增 Alembic `20260723_0006` 只写新身份/个人学习表，不删除或改写 legacy
`books/cards/review_states/review_logs`；空库不创建 Owner。迁移重复执行按稳定主键和
`legacy-review-log-{id}` 幂等，真实库执行前必须停服并备份。

回滚设计：0006 downgrade 只允许在该 Owner 没有 enrollment、review state、attempt 或
issue 时删除迁移生成的 profile/session/Owner；一旦存在个人学习数据直接拒绝 downgrade，
必须停服后恢复升级前备份。

验收：迁移前后 books/cards/due/logs 对账一致；备份可恢复；回滚策略记录。

## P1-T06 拆分后端领域服务

状态：`[x]`

目标：把原型卡片服务按 bounded context 拆成可直接单测的领域服务，同时保留根级兼容 API 的路径、响应和错误契约。

范围：`catalog` 负责目录查询和卡片输出映射；`publishing` 负责兼容期审核卡导入；`learning` 负责兼容期旧复习状态、作答和统计。routers 只处理 HTTP 参数、鉴权依赖、上传解码和响应模型，事务提交/回滚由领域服务负责。

过渡约束：兼容导入仍可创建 legacy `review_states`，以保持当前原型 API 和小程序可用，但不得创建新的用户级 `card_review_states`；真正不创建任何复习状态的 publication importer 属于 P5-T09。新导入卡的 `answer_points` 和 `tags` 必须写入 catalog 的结构化列，不再新增 `answer_points_json`/`tags_json`；目录读取对历史 JSON 列保留只读回退。来源页 JSON 仅作为尚未完成 CardSource 发布导入前的兼容字段。

输入输出：publishing service 接收已解码的候选包对象，输出现有 `ImportResult`；catalog service 输出现有 `BookOut`/`CardOut` 契约；learning service 输出现有 due、answer 和 stats 契约。所有写 service 都有单一事务边界，并对重复导入保持稳定结果。

验证：兼容 API 正常、空库、重复导入、非法 JSON、未发布卡和评分错误场景；catalog/publishing/learning service 单测；结构化字段断言；Ruff、Mypy、pytest、coverage 和 Alembic drift check。

验收：现有兼容 API 行为测试通过；领域服务可直接单测。

完成报告：

- `server/app/catalog/services.py` 新增目录列表、卡片搜索和输出映射；结构化 `answer_points/tags` 优先，历史 JSON 只读回退；CardSource 页范围转换为 1-based `source_pages`。
- 新建 `server/app/publishing/`，兼容导入使用 Pydantic 输入契约、稳定 external ID、结构化列表字段、整包事务回滚和重复导入幂等；兼容期只保留 legacy `review_states`，不创建 `card_review_states`。
- `server/app/learning/services.py` 承载 legacy due、作答和统计，评分失败与提交异常回滚；五个 routers 只保留 HTTP/鉴权/错误边界，不再依赖 `services_cards.py`。
- 新增领域服务、结构化字段、CardSource 页码、兼容路径 parity、重复/无 ID 导入、空值归一化和事务回滚测试；删除旧 `server/app/services_cards.py`。
- 验证：`server/.venv/bin/pytest -q` 为 `76 passed, 2 skipped`；coverage 全量为 `57%`；Ruff、format、Mypy、JSON、Markdown、Node JavaScript 检查通过；从 `server/` 执行 `alembic check` 报告 `20260723_0006 (head)` 且无 upgrade 操作；后端 `http://127.0.0.1:8000` health/books/due/stats 冒烟均为 200。
- 剩余风险：兼容 `/review/answer` 仍写无 `user_id` 的 legacy `ReviewLog/ReviewState`，不会同步 `ReviewAttempt/CardReviewState`；正式无状态 publication importer、revision/hash 冲突和用户级复习 API 留给 P5/P6。兼容导入的来源页暂存 legacy JSON，P5 发布时改为 CardSource。

### P1 退出门禁

- 内容、发布、加入学习和个人复习是四个独立概念。
- 原型数据安全迁移。
- 所有学习记录都归属唯一 User。

---

# P2 唯一 Owner、认证与档案

## P2-T01 认证配置和生产防误配

状态：`[x]`

目标：把开发固定 Token 与正式微信认证显式分环境，避免生产实例因默认配置静默使用 dev Token。

计划文件：`server/app/config.py`、`server/app/auth.py`、`.env.example`、`docker-compose.yml`、tests。

工作：增加 `APP_ENV`/`ENVIRONMENT`、`AUTH_MODE`、微信 AppID/AppSecret、Session TTL；`dev_token` 仅用于 development/test，production 必须使用 `wechat` 且提供完整微信凭据；固定 Token 不在 wechat 模式生效；配置校验错误不得回显 secret 值，日志不打印配置值。

范围外：不调用微信、不签发或校验 Session、不新增认证 API；这些属于 P2-T02。

输入输出：输入为环境变量或 Settings 构造参数；输出为已校验的 Settings。`require_token` 在 dev_token 模式继续校验固定 Bearer Token，在 wechat 模式统一拒绝固定 Token，等待 P2-T02 的 Session 依赖。

验证：development dev_token 默认和自定义 token、test/dev_token、wechat 完整凭据、production 默认 token/缺凭据/错误模式拒绝、secret 不出现在错误文本或配置日志；现有健康与鉴权 API 回归、Ruff/Mypy/pytest/coverage。

验收：dev_token 和 wechat 两种模式测试；prod 错配测试。

完成报告：

- `server/app/config.py` 增加 `AppEnvironment`、`AuthMode`、微信 AppID/AppSecret、Session TTL 和生产配置校验；支持 `APP_ENV`/`ENVIRONMENT` 环境别名，配置 repr/校验错误不暴露 secret。
- `server/app/auth.py` 仅在 `dev_token` 模式接受固定 Bearer Token，并使用 UTF-8 bytes 常量时间比较；`wechat` 模式为 P2-T02 的 Session 依赖预留，当前固定 Token 统一拒绝。
- 更新 `.env.example`、`docker-compose.yml`、`README.md` 和 `server/README.md`，明确 development/test 与 production 的认证配置边界；新增 `server/tests/test_config.py` 覆盖默认、环境变量、微信凭据、生产错配、启动拒绝、secret 脱敏和非 ASCII Token。
- 验证：`server/.venv/bin/pytest -q` 为 `87 passed, 2 skipped`；Ruff、format、Mypy、JSON、Markdown、Node JavaScript 检查通过；`docker compose config` 通过；生产错误配置子进程非零退出且不含 secret。
- 剩余风险：P2-T01 不调用微信、不签发或校验 Session；在 `AUTH_MODE=wechat` 下业务 API 会拒绝固定 Token，需 P2-T02 完成 Session 依赖后才可登录。

## P2-T02 微信登录和 Owner 绑定 API

状态：`[x]`

需求：AUTH-002–005。

目标：完成微信 `wx.login` code 到服务端 Session 的最小闭环，并保证单 Owner 的首次绑定、后续匹配和陌生 OpenID 拒绝。

计划文件：`server/app/identity/wechat.py`、`server/app/identity/auth.py`、`server/app/api/v1/identity.py`、`server/app/auth.py`、schemas、mock tests。

工作：实现带超时和稳定错误映射的 code2session adapter；OpenID 只保存 SHA-256；首次登录绑定已有空 hash Owner 或创建唯一 Owner/profile；签发随机 Session、只存 token hash；实现 Session 刷新轮换、幂等 logout、过期/撤销校验和 `/api/v1/me`。wechat 模式下所有业务路由使用 Session bearer，dev_token 模式保持兼容。

范围外：不保存微信 `session_key`，不返回 OpenID，不实现档案更新、导出、微信网络重试队列或多用户/重绑定界面；档案 API 属于 P2-T03。

输入输出：登录输入为 code/device_label，输出为 bearer token、过期时间和最小 Owner；refresh 使用当前 bearer，logout 返回无内容成功；外部微信错误转换为稳定业务 code，不能回显 AppSecret、session_key 或完整 OpenID。

验证：mock code2session 成功/invalid/timeout/provider-error；首次绑定、再次登录、陌生 OpenID、过期/撤销 Session、刷新轮换、重复 logout、dev_token 回归；Ruff/Mypy/pytest/coverage 和 API 错误契约。

验收：首次绑定、再次登录、陌生 OpenID、过期 code、微信超时和 logout 场景通过；OpenID/session_key 不进入响应或日志。

完成报告：

- 新增微信 `code2session` 适配器，设置超时并将无效 code、服务不可用和供应商错误映射为稳定业务错误；仅保存 OpenID 的 SHA-256 哈希，不保存或返回 `session_key`。
- 新增首次 Owner 绑定、默认学习档案创建、随机 Session 签发与哈希存储、刷新轮换、幂等 logout、过期/撤销/禁用校验和 `/api/v1/me`；`dev_token` 模式保持原固定 Token 兼容。
- 新增 `server/tests/test_wechat_auth.py` 覆盖首次绑定、重复登录、陌生 OpenID、provider 错误、刷新、过期、logout 及敏感字段不泄露。
- 验证：定向测试 `14 passed`；排除既有 SQLite/Python 3.14 并发用例后全量 `100 passed, 1 skipped`；Ruff、format、Mypy、Alembic check、JSON、Markdown 和小程序 JavaScript 检查通过；覆盖率 59%。完整 coverage 运行会在既有 `test_review_attempts.py` SQLite 并发用例触发 Python 3.14 原生段错误，普通 pytest 可通过该用例（共 `101 passed, 2 skipped`）。

## P2-T03 学习档案 API

状态：`[x]`

工作：GET/PUT `/api/v1/me/learning-profile`；校验目标日期、分钟、学习日、retention 和优先级；变更写审计。

验收：部分更新、非法值、并发更新和时区测试通过。

完成报告（2026-07-23）：

- 修改文件：新增 `learning_profile_audits` migration `20260723_0007` 与 `LearningProfileAudit` 模型；扩展 `LearningProfileUpdate`/`LearningProfileOut` 契约与 `apply_learning_profile_update` 服务；在 `GET/PUT /api/v1/me/learning-profile` 挂载鉴权路由；新增 `server/tests/test_learning_profile_api.py` 并更新 migration/identity 测试清理。
- API 结果：GET 返回完整档案及 Owner `display_name/timezone`；PUT 支持部分字段更新，要求 timezone-aware `expected_updated_at` 乐观并发；冲突返回 `LEARNING_PROFILE_CONFLICT`；校验非法分钟、学习日、retention、优先级和 IANA 时区。
- 审计：字段变更写入 append-only `learning_profile_audits`（changed_fields/before/after JSON）；全量 `update_learning_profile` 领域路径同样写审计；不删除历史档案行。
- 验证：`tools/quality-gate.sh` PASS；pytest `108 passed, 3 skipped`（含 PostgreSQL 环境跳过与 Python 3.14 共享内存 SQLite 并发段错误跳过）；Ruff/format/Mypy/Alembic check/JSON/Markdown/JS 通过；覆盖率 60%。
- 数据迁移影响：新增空审计表，不改既有 learning_profiles 数据；真实 `server/wxzy.db` 未自动 upgrade，需备份后 `upgrade head`。
- 剩余风险：未来计划重算属 P6；导出/删除个人数据属 PROFILE-004 后续；Python 3.14 下共享内存 SQLite 并发用例仍不稳定，已 skip 并由 postgres marker 覆盖。
- 恢复点：P2-T03 已完成；下一串行任务是 P2-T04 小程序认证客户端。

## P2-T04 小程序认证客户端

状态：`[x]`

计划文件：`miniprogram/services/http.js`、`auth-api.js`、`app.js`、auth tests/fixtures。

工作：启动读取 Session、`wx.login` 交换、401 刷新、logout；生产不暴露 API Token；dev 配置条件显示。

验收：Session 有效/过期/撤销/断网状态完整，页面不自行拼鉴权头。

完成报告（2026-07-23）：

- 新增 `miniprogram/services/http.js`：可注入 storage/request 的 Session 感知客户端；统一 Bearer、X-Request-Id、超时、401 刷新轮换、撤销/过期清理、断网 `offline` 状态；生产环境清除并隐藏 dev Token。
- 新增 `miniprogram/services/auth-api.js`：`wx.login` 换登、`/auth/wechat`/`refresh`/`logout`、`/me` 与 bootstrap；logout 幂等且始终清理本地 Session。
- 重构 `miniprogram/services/api.js` 与 `app.js`：页面只调 domain helpers，不拼 Authorization；`config.js` 控制 environment 与 autoWeChatLogin。
- “我的”页：登录状态、微信登录/退出；开发模式条件显示 API 地址与开发 Token；生产模式不展示 Token 输入。
- 测试：`miniprogram/tests/test_auth_client.js` + fixtures 覆盖 valid/expired/revoked/offline/refresh/login/logout/prod hide token/dev token/bootstrap/forbidden；`tools/tests/test_miniprogram_auth_client.py` 纳入 pytest；页面源码断言无 Authorization 拼装。
- 验证：Node auth suite `12 passed`；`tools/quality-gate.sh` PASS；pytest `109 passed, 3 skipped`；Ruff/format/Mypy/Alembic/JSON/Markdown/JS（11 files）通过；覆盖率 60%。
- 剩余风险：真机微信 `wx.login` 与正式 AppSecret 需联调；旧页面仍调用原型 `/books`/`/review` 路由，待 P7 全面切换 `/api/v1`；`config.autoWeChatLogin` 默认 false 以便本地 dev_token。
- 恢复点：P2-T04 已完成；下一串行任务是 P2-T05 Onboarding 和档案设置页。

## P2-T05 Onboarding 和档案设置页

状态：`[x]`

需求：PROFILE-001–003（PROFILE-004 导出/删除仍属后续）。

工作：目的、日期、分钟、学习日、科目优先级；保存期间禁用；返回后状态一致。

验收：首次用户两分钟内完成；跳过可选项；长文本和键盘无重叠。

完成报告（2026-07-23）：

- 新增 `miniprogram/utils/profile-form.js`：档案表单纯函数（默认值、校验、payload、摘要、onboarding 完成判定）。
- 新增 `miniprogram/services/profile-api.js`：`GET/PUT /api/v1/me/learning-profile`，经 `http.js` 鉴权，携带 `expected_updated_at` 乐观并发。
- 新增页面 `pages/onboarding/onboarding`（5 步引导：目的/时间/学习日/学科可选/确认）与 `pages/profile-edit/profile-edit`（完整编辑，保存中禁用控件）。
- “我的”页展示档案摘要与入口；今日页对未完成 onboarding 给出引导入口；`api.js` 暴露 profile helpers。
- 测试：`miniprogram/tests/test_profile_form.js` + `tools/tests/test_miniprogram_profile_form.py`；覆盖默认跳过、round-trip、校验失败、onboarding 标记、API bearer/并发 token、页面无 Authorization 拼装。
- 验证：Node profile suite `6 passed`；auth suite 回归 `12 passed`；`tools/quality-gate.sh` PASS；pytest `110 passed, 3 skipped`；Ruff/format/Mypy/JSON/Markdown/JS（16 files）通过；覆盖率 60%。
- 范围外/剩余：PROFILE-004 导出删除、P6 改目标后未来计划重算、真机键盘/长文本视觉验收；`config.autoWeChatLogin` 仍默认 false。
- 恢复点：P2-T05 已完成；P2 退出门禁中档案 UI 可用，下一阶段可进入 P3 或按需补 PROFILE-004。

### P2 退出门禁

- 真正的唯一 Owner 登录可用。
- 开发 Token 只存在 dev 模式。
- 学习档案可驱动后续计划。

---

# P3 文档流水线工程化

## P3-T01 把工具重构为可测试 package

状态：`[x]`

计划文件：`tools/document_pipeline/`、CLI entrypoint、`tools/tests/`。

工作：从两个大脚本提取 inventory、split、MinerU client、clean、structure、quality、generation、publish 模块；保留兼容命令。

验收：现有两份 10 页样本命令仍可用；纯函数无需外部 Key 可测试。

完成报告：
- 提交：`092a8c1`。
- 包布局：`tools/document_pipeline/{paths,env,pages,budget,http_client,split,raw,clean,structure,quality,generation,inventory,publish,cli_mineru,cli_cards}`。
- 兼容入口：`python tools/mineru_validate.py …` 与 `python tools/generate_candidate_cards.py …` 仍为薄 wrapper。
- 纯函数测试：`tools/tests/test_document_pipeline_core.py`（页范围、清洗、content_list、zip 路径安全、可注入 HTTP、预算核算、inventory 计划键）；既有 `test_generate_candidate_cards.py` 仍通过。
- MinerU 配额评估（操作员 2026-07-23）：**5000 files/day**、**1000 priority pages/day**。
  - 全库 704 页、约 28–35 个 20–30 页 split，远低于文件配额。
  - 页优先预算是真实节流：整库一通可落在约 1 个优先日内（704 ≤ 1000）；重试/重提交流留 1–2 日缓冲。
  - 实现：`MINERU_DAILY_FILE_BUDGET` / `MINERU_DAILY_PAGE_BUDGET` 环境变量 + `tools.document_pipeline.budget`；**强制扣减与 job manifest 计数放在 P3-T04**。
- 范围外：未消耗真实 MinerU 额度；未做 inventory 扫描、chapter-aware split、job 生命周期与 raw 不可变 hardening（P3-T02+）。
- 恢复点：P3-T01 完成后下一串行任务为 **P3-T02 文档 Inventory**。

## P3-T02 文档 Inventory

状态：`[x]`

需求：DOC-001。

工作：扫描 `docs/*.pdf`，输出 SHA256、页数、大小、document key、版权备注；禁止把绝对路径写入 publication。

验收：识别 7 本、704 页；重复运行输出稳定；变更文件创建新版本。

完成报告：
- 提交：`7499488`。
- 实现：`tools/document_pipeline/inventory.py` + CLI `python tools/inventory_scan.py`。
- 产出（本地 gitignore `data/`）：
  - `data/document-pipeline/inventory/documents.v1.json`（publication-safe，仅相对路径）
  - `data/document-pipeline/inventory/local_sources.v1.json`（LOCAL ONLY，可含绝对路径）
- 跟踪摘要：`tools/document_pipeline/fixtures/inventory_coverage.v1.json`（7 本 / 704 页指纹，无绝对路径）。
- Schema：`tools/document_pipeline/schemas/documents.v1.schema.json`。
- 实扫：7 documents，`page_total=704`，与设计页数一致；重复运行字节级稳定；内容变更时仅该 `document_key` 的 `version` +1。
- 测试：`tools/tests/test_document_inventory.py`（无 Key、无私有 PDF 依赖；可注入 page_counter）。
- 附带修复：内存 SQLite 使用 `StaticPool`；wechat 登录断言改用独立 Session，消除全量 coverage 下 closed database flake。
- 验证：`./tools/quality-gate.sh` PASS（125 passed, 3 skipped；coverage ~65%）。
- 恢复点：下一串行任务 **P3-T03 Chapter-aware PDF Split**。

## P3-T03 Chapter-aware PDF Split

状态：`[x]`

需求：DOC-002。

工作：优先章节边界、fallback 20–30 页；生成 split manifest 和源页映射；split 文件低于限制。

验收：所有源页恰好出现一次；合并页序与原 PDF 一致；坏范围正确失败。

完成报告：
- 提交：`660e645`。
- 实现：`tools/document_pipeline/split.py` + CLI `python tools/split_pdfs.py`（`cli_split.py`）。
- 规划：章节起点可检测/可注入；无章节时按 ~20–30 页均匀窗口；硬上限 30 + soft overflow 至 35 避免尴尬双分；覆盖 1..N 不重不漏。
- 产出（本地 gitignore `data/`）：
  - `data/document-pipeline/splits/<document_version>/split-manifest.json`
  - `data/document-pipeline/splits/<document_version>/<split_id>.pdf`
  - `data/document-pipeline/splits/split-summary.v1.json`
- 映射：`split_page_index` / `source_pdf_page_index` / `source_pdf_page_number`；`printed_page_label` 预留。
- 大小门禁：默认 `max_split_bytes=180MB`（相对 200MB 上传上限预留余量）。
- 实扫：7 本 plan-only `split_total=31`、`page_total=704`、全部 `coverage_exact=true`；`renwen` 已物化 2 个 split PDF。
- 额度评估（用户：5000 文件/日、1000 优先页/日）：31 split << 5000；704 页 ≤ 1000 → **一优先日可跑完全库**；瓶颈是页预算，不是文件数；P3-T04 起按 job 强制扣减。
- 测试：`tools/tests/test_document_split.py`（无 Key、无私有 PDF；可注入 page_text / extract / page_count）。
- 恢复点：下一串行任务 **P3-T04 MinerU Job 生命周期**。

## P3-T04 MinerU Job 生命周期

状态：`[x]`

工作：submit/poll/download 分阶段；manifest/events；安全上传；继续 poll；失败重试；外部 URL 脱敏。

验收：mock 外部 API 覆盖 waiting/running/done/failed/timeout；重复执行不重复提交成功阶段。

完成报告：
- 提交：`f68b89a`。
- 实现：`tools/document_pipeline/jobs.py` + CLI `python tools/mineru_jobs.py`（`cli_jobs.py`）。
- 阶段：`planned → submitted → uploaded → polling → done | failed | timed_out`（另有 `submit_failed` / `upload_failed`）。
- 稳定 `data_id`（自 split_id）、`manifest.json` + `events.jsonl` 于 `data/document-pipeline/jobs/<job_id>/`。
- 签名上传/下载 URL 经 `redact_url` / `redact_for_storage` 脱敏，不写入长期 manifest。
- 成功 submit 幂等：已有 `batch_id` 时跳过 re-apply，不重复扣预算。
- 超时 ≠ 失败：`timed_out` 保留 `batch_id`，后续 poll 可恢复。
- 日额度账本：`data/document-pipeline/jobs/budget-ledger.v1.json`；默认 **5000 files / 1000 priority pages**（env 可覆写）；成功上传后 reserve。
- 批次软上限：≤ 12 文件（设计偏好 4–8，`DEFAULT_BATCH_SPLIT_COUNT=6`）。
- 下载：zip + sha256 + 安全 unpack（`enforce_safe_members`）；已下载项跳过。
- 可从 split-manifest 建 job：`create-from-split`。
- 测试：`tools/tests/test_document_jobs.py`（FakeMinerU；waiting/running/done/failed/timeout；双 submit 不重复扣费；预算超限；URL 脱敏）。
- 额度再评估：31 split << 5000；704 ≤ 1000 → 一优先日可全库；瓶颈仍是页预算。
- 范围外：真实 MinerU 调用与 P3-T05 raw 不可变 hardening（clean 不改 raw mtime/hash）仍待下任务。
- 恢复点：下一串行任务 **P3-T05 安全下载与不可变 raw**。

## P3-T05 安全下载与不可变 raw

状态：`[x]`

工作：hash、zip 完整性、zip-slip 防护；raw 目录不可被 clean 覆盖；输出 input/output hash。

验收：恶意 zip fixture 被拒绝；clean 命令不修改 raw mtime/hash。

完成报告：
- 提交：`51da54b`。
- 实现：`tools/document_pipeline/raw.py` hardening + `clean.write_cleaned_markdown` 分离写出。
- Zip：`verify_zip_integrity`（testzip + BadZipFile）、默认 `enforce_safe_members=True`、逐成员解包防 zip-slip、`materialize_raw_from_zip` 写 `result.zip` + `unzipped/` + `raw_manifest.json`（zip/input/output hashes）。
- 不可变：`assert_not_raw_write_target` 拒绝写入含 `raw/` 路径段；clean 默认映射 `raw/.../unzipped/full.md` → `cleaned/.../full.cleaned.md`。
- Clean：`write_cleaned_markdown` 记录 `source_sha256` / `output_sha256` / mtime 指纹，清洗前后比对 source 未变；CLI `clean-md` 改用该路径。
- Job 下载：`download_job` 经 partial zip → materialize（校验 + 幂等复用）。
- 测试：`tools/tests/test_document_raw.py`（恶意 zip、损坏 zip、hash 不匹配、clean 不改 raw mtime/hash、拒绝 raw 写出）。
- 范围外：清洗规则 ID/页码映射 v2（P3-T06）、真实 MinerU 全量下载。
- 恢复点：下一串行任务 **P3-T06 清洗和页码映射 v2**。

## P3-T06 清洗和页码映射 v2

状态：`[x]` 完成（commit: 96fd4b5）

工作：规则 ID、替换审计、PDF 页/印刷页分离、页眉页脚过滤；已知方剂 OCR 词典；不做事实补全。

验收：现有样本固定错误修复；映射 100%；清洗幂等。

完成记录：
- `clean.v2`：`OCR_RULES` / header / page-number 规则均带稳定 `rule_id`；`replacements` 审计含 before/after/count/line_no。
- 方剂固定 OCR 词典（粳镶→粳米、咬咀→㕮咀、黎黎→漐漐等）；禁止事实补全。
- `page_mapping.py`：`source_pdf_page_index/number` 与 `printed_page_label` 分离；content_list `page_number` 归一化（含 `/ 295`）；`page_map_coverage.complete` 要求 PDF 映射 100%。
- `write_cleaned_markdown` 可选写出 `*.page_map.json` sidecar；CLI `clean-md` 自动从 content_list 建 map。
- 测试：`tools/tests/test_document_clean.py` + fixture `clean_v2_*`；幂等二次清洗无再改写。
- 范围外：章节 ContentBlock 结构化（P3-T07）、质量门禁 exit（P3-T08）、真实 MinerU 全量。
- 恢复点：下一串行任务 **P3-T07 章节与 ContentBlock 结构化**。

## P3-T07 章节与 ContentBlock 结构化

状态：`[x]` 完成（commit: 5dff9c5）

工作：标题、layout、目录和相邻页推断；保留 method/confidence；HTML table 结构；生成稳定 chunk ID。

验收：7 类代表 fixture；低置信章节不静默归类；chunk 可回 raw 页。

完成记录：
- `structure.v1`：`classify_heading` / `build_chapter_tree` / `ContentBlock` / `PageRecord`；每边界保留 `method`+`confidence`。
- 低置信边界 `needs_review`，不更新 active chapter path（不静默改章）。
- HTML table 保留 `table_rows`；`stable_chunk_id` 可重复且内容敏感。
- 7 类模板 fixture（jichu/zhenduan/zhongyao/fangji/neike/zhenjiu/renwen）+ low_confidence fixture。
- 写出 `structured/` 下 chapters.json、pages.json、content_blocks.jsonl；CLI `structure` 子命令。
- 测试：`tools/tests/test_document_structure.py`。
- 范围外：质量门禁 exit（P3-T08）、真实 MinerU 全量。
- 恢复点：下一串行任务 **P3-T08 质量报告和门禁**。

## P3-T08 质量报告和门禁

状态：`[x]` 完成（commit: 6f72862）

工作：页覆盖、空页、乱码、表格、章节、可疑词、映射和 terminal 状态；JSON + Markdown summary；nonzero exit gate。

验收：故意缺页/错表/可疑词 fixture 正确失败；summary 不含完整原文。

完成记录：
- `quality.v1`：page coverage / empty pages / garbled text / bad tables / chapters / suspicious OCR / page map coverage / terminal_status（pass|needs_review|fail）。
- Gate：issue_records 带 code+severity；`gate_ok` 与 `exit_code`；aggregate 多样本汇总。
- Summary：metrics + issue codes + 短 context；JSON/MD 均不含完整原文。
- Fixture：`quality_missing_page` / `quality_bad_table` / `quality_suspicious` 失败；`quality_pass` 通过。
- CLI `quality-report`：默认门禁 nonzero exit；`--no-gate` 仅写报告；支持 `--expected-pages` / `--source-pdf-page-start`。
- 测试：`tools/tests/test_document_quality.py`（8 passed）。
- 范围外：真实 MinerU 全量、P4 Wave 0 七类模板章节实跑。
- 恢复点：下一串行任务 **P4-T01 Wave 0：七类模板章节**。

### P3 退出门禁

- 单个代表章节可从 PDF 恢复性地处理到 ContentBlock。
- 无外部 Key 的逻辑有完整 fixture 测试。
- raw、cleaned、structured 分层不可混淆。

---

# P4 704 页全量解析

## P4-T01 Wave 0：七类模板章节

状态：`[ ]`

工作：每本书选一个结构代表章节，执行 split -> MinerU -> clean -> structure -> quality；记录时间、页成本和主要错误。

验收：7/7 章节通过或明确 needs_review；根据结果冻结全量参数。

## P4-T02 中医基础理论全量

状态：`[ ]`

目标：102/102 页 terminal；章节和概念表可用。

验证：该书 coverage report、随机页回源抽查和章节连续性。

## P4-T03 中医诊断学全量

状态：`[ ]`

目标：92/92 页 terminal；证候/症状表列不串行。

## P4-T04 中药学全量

状态：`[ ]`

目标：88/88 页 terminal；药名、剂量、毒性/禁忌风险 flags 完整。

## P4-T05 方剂学全量

状态：`[ ]`

目标：140/140 页 terminal；已知 OCR 词典、剂量、方歌和跨页方剂表抽查。

## P4-T06 中医内科学全量

状态：`[ ]`

目标：149/149 页 terminal；多教材版本和证型表不混合。

## P4-T07 针灸学全量

状态：`[ ]`

目标：94/94 页 terminal；穴位定位/操作高风险标记。

## P4-T08 人文全量

状态：`[ ]`

目标：39/39 页 terminal；法规/伦理内容的版本或日期可记录。

## P4-T09 全局覆盖闭环

状态：`[ ]`

工作：合并 7 本 coverage；处理 failed/needs_review；确认 704 页无遗漏；输出 tracked 的无原文摘要。

验收：`total=704`，每页 terminal；所有失败有 owner、原因和处置，不用“总体完成”隐藏失败页。

### P4 退出门禁

- 704/704 页有状态和源页映射。
- 7 本书有章节树和质量报告。
- 全量原始/清洗/结构化产物可恢复。

---

# P5 候选卡、审核与发布

## P5-T01 Candidate Card v2 Schema

状态：`[ ]`

工作：加入 document_version、chunk IDs、PDF/印刷页、risk_level/flags、content hash、generator/prompt 版本和审核字段；提供 v1 -> v2 converter。

验收：现有 18 张样例可转换；无来源或高风险缺 flags 时 schema/gate 失败。

## P5-T02 基础理论/诊断模板

状态：`[ ]`

工作：定义、机制、关系、对比、四诊、证候和鉴别模板；针对代表章节 golden tests。

## P5-T03 中药/方剂模板

状态：`[ ]`

工作：结构化表优先；性味归经/功效/主治/用法、组成/功用/主治/方歌/配伍；剂量毒性禁忌 high/critical。

## P5-T04 内科/针灸/人文模板

状态：`[ ]`

工作：证型-治法-代表方、多版本、穴位定位/主治/操作、法规/伦理情境；版本字段和风险规则。

## P5-T05 Qwen 全量游标生成器

状态：`[ ]`

工作：按 ContentBlock 游标，不再 `md[:max_chars]`；记录 input hash、chunk IDs、model/prompt、token/cost；失败可恢复；输出只进 candidate。

验收：输入超过 max_chars 的 fixture 每个 chunk 都被覆盖；重复运行不重复候选。

## P5-T06 自动卡片校验与去重

状态：`[ ]`

工作：schema、来源覆盖、实体新增、长度、最小知识点、近重复、多版本和风险检查。

验收：伪造剂量、无来源答案、重复问题、多版本混合 fixture 被拦截。

## P5-T07 人工审核工作流

状态：`[ ]`

初期产物：CLI/静态 review bundle；后续可增加独立管理 UI。支持逐张和章节批量，critical 不允许批量。

验收：Approve/Edit/Reject/Second review 审计完整；编辑后重新校验。

## P5-T08 Publication Exporter

状态：`[ ]`

工作：manifest、documents、chapters、chunks、cards、sources、checksums、quality summary；不含本地路径和密钥。

验收：hash 可重算；缺引用或未审核卡不能导出。

## P5-T09 Publication Import API

状态：`[ ]`

需求：PUB-004–005。

工作：validate/import/status；事务、publication idempotency、revision/conflict；不创建 ReviewState。

验收：重复导入结果一致；冲突报告；导入后目录增加但 due 不增加。

## P5-T10 首批正式发布

状态：`[ ]`

工作：每本至少一个审核章节；导入目标库；核对小程序目录来源。

验收：7 本可见；所有发布卡来源 100%；高风险审核记录 100%。

### P5 退出门禁

- 所有生成内容先 candidate。
- 发布包版本化、可校验、可幂等导入。
- 发布与学习状态彻底分离。

---

# P6 个性化学习引擎

## P6-T01 标准 FSRS Adapter

状态：`[ ]`

工作：选择维护中的 Python FSRS 库；封装 scheduler；保存版本；用公开/固定用例验证；保留 legacy 状态迁移。

验收：四档产生有效不同 due；UTC；升级 dry-run；不再新增依赖 `fsrs_simple` 的业务代码。

## P6-T02 Enrollment Service

状态：`[ ]`

工作：按书/章/卡加入；queued/active/suspended/retired；章节顺序；重复加入幂等。

验收：加入整章不立即生成全量 due；暂停后不进入计划，历史保留。

## P6-T03 幂等 ReviewAttempt

状态：`[ ]`

工作：开始会话、current state 检查、原子调度、attempt 写入；client ID 重放；并发锁/冲突。

验收：重复点击、超时重试、并发请求测试均只有一条记录。

## P6-T04 DailyPlan v1

状态：`[ ]`

需求：PLAN-001–006。

工作：分钟预算、到期优先、response 时间估算、repair、新卡引入、7 天负荷限制、reason codes；无历史冷启动。

验收：积压时 new=0；预算变化可解释；相同输入输出稳定。

## P6-T05 StudySession API

状态：`[ ]`

工作：start/next/complete/interrupted；计划项游标；一次只取当前/下一任务；实际分钟统计。

验收：中断恢复、空会话、已完成重开和跨日边界测试。

## P6-T06 Weak Topic 和 Repair Rules

状态：`[ ]`

工作：重复 Again、持续 Hard、耗时、混淆标签和 Issue 聚合；输出具体 reason/action；不自动发布 AI 修复卡。

验收：fixture 能触发/不误触发；建议指向具体来源。

## P6-T07 Insights Read Models

状态：`[ ]`

工作：summary、未来 7 天、学科趋势、薄弱点；异步/可重建聚合；区分覆盖/发布/加入/掌握。

验收：空数据、少量数据、跨时区当天统计和大数据分页。

### P6 退出门禁

- 标准 FSRS、幂等评分和 DailyPlan API 完成。
- 系统能限制新卡和解释计划。
- Repair 建议来自真实记录。

---

# P7 小程序产品化

## P7-T01 API Client v1 拆分

状态：`[ ]`

工作：`http/auth/profile/catalog/learning/insights` services；Session、request_id、业务错误、超时；页面不直接请求。

验收：API fixture 单测/手工 mock；401、超时、业务冲突文案。

## P7-T02 Onboarding UI

状态：`[ ]`

工作：目的、日期、时间、学习日、优先级；保存和恢复；首次路由。

验收：移动端键盘、长文本、错误/重试、两分钟完成。

## P7-T03 今日页 DailyPlan

状态：`[ ]`

工作：预计分钟、到期/新卡/薄弱、调整时间、overloaded/completed；最多 3–5 预览。

验收：loading/empty/error/unauthorized/completed；布局稳定；计划与 API 一致。

## P7-T04 Study Session 页面

状态：`[ ]`

工作：review/learn/repair/test；主动回忆、可选书写、答案、来源、评分；client_attempt_id；中断恢复。

验收：完整点击流、重复点击、超时重试、长答案、来源加载和返回。

## P7-T05 学科和章节

状态：`[ ]`

工作：7 本目录、章节树、发布/加入/掌握区分、加入/暂停、搜索分页。

验收：无内容、部分发布、整章加入和大列表性能。

## P7-T06 进度与周测

状态：`[ ]`

工作：分钟、积压、未来负荷、学科趋势、薄弱点和周测入口；样本不足提示。

验收：空/少量/正常数据；图表不只靠颜色；长主题不溢出。

## P7-T07 我的页

状态：`[ ]`

工作：Owner、档案、目标、Session、导出/删除；dev-only API 设置；生产不显示 Token。

验收：环境开关、保存失败、Session 撤销和隐私文案。

## P7-T08 通用状态与组件

状态：`[ ]`

工作：rating/source/loading/error/empty/progress 等真实复用组件；请求序列防迟到；减少大 setData。

验收：组件尺寸稳定、无嵌套卡片、无 CSS 变量兼容问题。

## P7-T09 微信开发者工具与真机验收

状态：`[ ]`

工作：当前和最低基础库、清缓存编译、网络、断网、长文、快速返回、性能面板；真机使用 HTTPS/LAN 正确地址。

验收：10 个 PRD 发布场景全部通过并保留结果记录。

### P7 退出门禁

- 四个 Tab 和学习会话完整。
- 小程序没有任何文档处理控制功能或生产 Token 输入。
- 真机完成登录、加入章节、学习、评分、来源和进度流程。

---

# P8 部署、备份和稳定性

## P8-T01 PostgreSQL 生产迁移

状态：`[ ]`

工作：Compose/托管库、连接池、Alembic、时区、备份；SQLite/Postgres 差异测试。

## P8-T02 HTTPS 和域名

状态：`[ ]`

工作：Nginx/网关、证书、合法业务域名、CORS、健康检查、反向代理大小限制。

## P8-T03 微信生产认证

状态：`[ ]`

工作：AppSecret 密钥管理、Owner claim 保护、Session rotation、dev_token 禁用。

## P8-T04 私有内容存储

状态：`[ ]`

工作：原 PDF/OCR/图片进入私有 OSS 或受控磁盘；短期签名或服务端代理；生命周期和容量监控。

## P8-T05 备份恢复

状态：`[ ]`

工作：数据库每日备份、publication/manifest 备份、恢复演练、RPO/RTO 记录。

验收：在独立环境恢复 Owner、目录、enrollment 和 review history；不依赖原运行容器。

## P8-T06 监控和告警

状态：`[ ]`

工作：API 错误/延迟、作答重复、任务失败、页覆盖、审核积压、磁盘、外部 API 额度；脱敏日志。

## P8-T07 安全与版权检查

状态：`[ ]`

工作：密钥扫描、日志抽查、接口权限、原文最小返回、微信隐私指引、个人使用版权备注。

### P8 退出门禁

- 域名 HTTPS 真机可访问。
- 默认 Token 不可用于生产。
- 数据和内容可恢复，关键故障可观察。

---

# P9 两周个人使用与校准

## P9-T01 建立使用基线

状态：`[ ]`

连续 14 天记录计划分钟、实际分钟、完成率、Again/Hard 分布、积压、新卡和中断原因。

## P9-T02 调整每日负荷

状态：`[ ]`

根据真实时间和未来 7 天负荷调整新卡上限、默认分钟和章节引入速度，不只根据主观感觉。

## P9-T03 评估 FSRS 参数

状态：`[ ]`

确认数据量足够后再评估 desired retention 或个性参数；不足时继续使用默认值并记录原因。

## P9-T04 修复低质量卡

状态：`[ ]`

汇总事实错误、来源错误、过大、过难和混淆 Issue；优先修复高频/高风险；内容 revision 不覆盖历史。

## P9-T05 扩大发布覆盖

状态：`[ ]`

按实际学习顺序持续审核和发布剩余候选，不以一次性发布全部卡片作为目标。

## P9-T06 产品复盘

状态：`[ ]`

对 PRD 成功指标逐项评估，决定是否进入 RAG/问答、完整章节阅读或更复杂题型；没有证据的功能继续延后。

### P9 退出门禁

- 至少 14 天真实学习数据。
- 学习负荷可持续且无长期积压。
- 高频低质量卡有闭环。
- 下一阶段决策有数据依据。

---

# 4. 首个推荐执行切片

文档批准后，建议严格按以下顺序开始，不直接全量跑 MinerU：

1. `P0-T02` Python 工程配置。
2. `P0-T03` Alembic 基线。
3. `P0-T04` 统一错误和 request ID。
4. `P1-T01` User/Profile。
5. `P1-T03` Enrollment/个人 ReviewState。
6. `P1-T05` 迁移现有 15 张卡。
7. 同时开始 `P3-T01` 到 `P3-T03`，准备七本书 Wave 0。

这个切片先把数据语义和可回滚能力建立起来，再扩大内容规模，避免 704 页处理完成后重新迁移所有卡片和来源。

# 5. 计划变更规则

- 新需求先映射到 PRD requirement ID。
- 改变阶段退出条件时同时更新对应设计文档。
- 新任务必须写在正确阶段，不能用“临时任务”绕过质量门禁。
- 外部 API 配额、版权或 Owner 决策导致阻塞时，用 `[!]` 记录，不伪造完成。
- 每完成一个阶段，更新本计划状态和一份简短验收记录。
