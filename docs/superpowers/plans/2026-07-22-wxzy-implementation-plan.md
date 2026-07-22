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

状态：`[ ]`

目标：统一依赖、格式、lint 和测试入口。

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

状态：`[ ]`

需求：SP-040。

计划文件：

- `server/alembic.ini`
- `server/migrations/env.py`
- `server/migrations/versions/*_baseline.py`
- `server/app/main.py`

工作：捕获当前表结构为 baseline；测试空 SQLite/PostgreSQL 升级；生产启动移除 `create_all` 依赖，测试环境可显式创建 fixture 库。

验收：全新库可 upgrade；现有 `wxzy.db` 的 schema 可 stamp/migrate；升级不删除 15 张样例卡。

## P0-T04 统一错误、请求 ID 和日志

状态：`[ ]`

计划文件：`server/app/core/errors.py`、`server/app/core/logging.py`、`server/app/main.py`、API tests。

工作：建立 `{code,message,request_id,details}`；添加 request-id middleware；Authorization/Token/原文脱敏；把已知 ValueError 映射为稳定业务错误。

验收：401、404、422、409、500 的响应契约测试通过，日志无 Token。

## P0-T05 建立 API v1 路由骨架

状态：`[ ]`

计划文件：`server/app/api/v1/router.py` 及兼容路由。

工作：保留 `/health`；把新接口统一置于 `/api/v1`；旧 `/books`、`/review/*` 在迁移期保留并标记 deprecated，不立即破坏原型。

验收：OpenAPI 同时包含 health、v1 和兼容接口；无重复 operation ID。

## P0-T06 建立一键质量门禁和 CI

状态：`[ ]`

计划文件：`tools/quality-gate.sh`、CI workflow、README。

工作：串联 Ruff、pytest、JS 语法、JSON 解析、文档链接检查；CI 不依赖私有 PDF、MinerU 或模型 Key。

验收：本地脚本和 CI 在无密钥环境通过；缺测试或解析错误时正确失败。

### P0 退出门禁

- 自动测试和 lint 可在新环境安装运行。
- 数据库迁移可升级和回退。
- 新接口有版本化和统一错误。
- 后续模型有单一质量命令。

---

# P1 领域模型与数据分离

## P1-T01 建立唯一 User 和 LearningProfile

状态：`[ ]`

需求：AUTH-001、PROFILE-001–004。

计划文件：`server/app/identity/models.py`、schemas/services、migration、tests。

工作：创建 User、UserSession、LearningProfile；数据库约束最多一个 active Owner；时区和时间预算校验；建立默认 profile factory。

验收：第二个 active Owner 被拒绝；档案更新不删除历史；UTC 字段一致。

## P1-T02 建立文档和内容目录模型

状态：`[ ]`

需求：CAT-001–006、DOC-001。

计划文件：`server/app/catalog/models.py`、migration、schemas、tests。

工作：Document、DocumentVersion、Chapter、DocumentChunk、Card、CardSource；Card 支持 content_revision；来源页字段区分 PDF 页和印刷页。

验收：一张卡可引用多个块；相同文档 hash 不重复创建版本；来源契约测试通过。

## P1-T03 建立 Enrollment 和个人 ReviewState

状态：`[ ]`

需求：ENROLL-001–004、REV-005。

计划文件：`server/app/learning/models.py`、migration、tests。

工作：CardEnrollment、CardReviewState；唯一 `(user_id, card_id)`；发布卡不会自动创建 ReviewState；首次引入后才创建。

验收：导入 100 张发布卡后 due 仍为 0；加入 5 张后只有计划引入的卡进入学习。

## P1-T04 建立 StudySession、ReviewAttempt 和 CardIssue

状态：`[ ]`

需求：REV-004、REV-006、REV-007。

工作：记录 session、client_attempt_id、rating、response_ms、hint/reveal、前后状态和内容 revision；CardIssue 支持错误类别。

验收：重复 client_attempt_id 返回同一结果；并发提交只产生一条 Attempt。

## P1-T05 迁移现有原型数据

状态：`[ ]`

计划文件：data migration、迁移测试、迁移报告脚本。

工作：创建 legacy Owner；迁移 2 本书、15 张卡、ReviewState 和 ReviewLog；建立 enrollment；保持 due、reps、lapses 和来源。

验收：迁移前后 books/cards/due/logs 对账一致；备份可恢复；回滚策略记录。

## P1-T06 拆分后端领域服务

状态：`[ ]`

工作：将 `services_cards.py` 按 catalog、publishing、learning 拆分；routers 只做 HTTP；事务边界在 service；移除 JSON 字符串列表的新增使用，目标库用结构化字段。

验收：现有兼容 API 行为测试通过；领域服务可直接单测。

### P1 退出门禁

- 内容、发布、加入学习和个人复习是四个独立概念。
- 原型数据安全迁移。
- 所有学习记录都归属唯一 User。

---

# P2 唯一 Owner、认证与档案

## P2-T01 认证配置和生产防误配

状态：`[ ]`

计划文件：`server/app/config.py`、`.env.example`、tests。

工作：增加 `AUTH_MODE`、微信 AppID/AppSecret、Session TTL；生产环境默认 Token 或缺 AppSecret 时拒绝启动；配置日志不打印值。

验收：dev_token 和 wechat 两种模式测试；prod 错配测试。

## P2-T02 微信登录和 Owner 绑定 API

状态：`[ ]`

需求：AUTH-002–005。

计划文件：identity WeChat client、auth service、v1 routes、mock tests。

工作：code2session adapter、首次 claim、OpenID 匹配、Session hash/刷新/撤销；外部调用有超时和错误码。

验收：首次绑定、再次登录、陌生 OpenID、过期 code、微信超时和 logout 场景通过。

## P2-T03 学习档案 API

状态：`[ ]`

工作：GET/PUT `/api/v1/me/learning-profile`；校验目标日期、分钟、学习日、retention 和优先级；变更写审计。

验收：部分更新、非法值、并发更新和时区测试通过。

## P2-T04 小程序认证客户端

状态：`[ ]`

计划文件：`miniprogram/services/http.js`、`auth-api.js`、`app.js`、auth tests/fixtures。

工作：启动读取 Session、`wx.login` 交换、401 刷新、logout；生产不暴露 API Token；dev 配置条件显示。

验收：Session 有效/过期/撤销/断网状态完整，页面不自行拼鉴权头。

## P2-T05 Onboarding 和档案设置页

状态：`[ ]`

需求：PROFILE-001–004。

工作：目的、日期、分钟、学习日、科目优先级；保存期间禁用；返回后状态一致。

验收：首次用户两分钟内完成；跳过可选项；长文本和键盘无重叠。

### P2 退出门禁

- 真正的唯一 Owner 登录可用。
- 开发 Token 只存在 dev 模式。
- 学习档案可驱动后续计划。

---

# P3 文档流水线工程化

## P3-T01 把工具重构为可测试 package

状态：`[ ]`

计划文件：`tools/document_pipeline/`、CLI entrypoint、`tools/tests/`。

工作：从两个大脚本提取 inventory、split、MinerU client、clean、structure、quality、generation、publish 模块；保留兼容命令。

验收：现有两份 10 页样本命令仍可用；纯函数无需外部 Key 可测试。

## P3-T02 文档 Inventory

状态：`[ ]`

需求：DOC-001。

工作：扫描 `docs/*.pdf`，输出 SHA256、页数、大小、document key、版权备注；禁止把绝对路径写入 publication。

验收：识别 7 本、704 页；重复运行输出稳定；变更文件创建新版本。

## P3-T03 Chapter-aware PDF Split

状态：`[ ]`

需求：DOC-002。

工作：优先章节边界、fallback 20–30 页；生成 split manifest 和源页映射；split 文件低于限制。

验收：所有源页恰好出现一次；合并页序与原 PDF 一致；坏范围正确失败。

## P3-T04 MinerU Job 生命周期

状态：`[ ]`

工作：submit/poll/download 分阶段；manifest/events；安全上传；继续 poll；失败重试；外部 URL 脱敏。

验收：mock 外部 API 覆盖 waiting/running/done/failed/timeout；重复执行不重复提交成功阶段。

## P3-T05 安全下载与不可变 raw

状态：`[ ]`

工作：hash、zip 完整性、zip-slip 防护；raw 目录不可被 clean 覆盖；输出 input/output hash。

验收：恶意 zip fixture 被拒绝；clean 命令不修改 raw mtime/hash。

## P3-T06 清洗和页码映射 v2

状态：`[ ]`

工作：规则 ID、替换审计、PDF 页/印刷页分离、页眉页脚过滤；已知方剂 OCR 词典；不做事实补全。

验收：现有样本固定错误修复；映射 100%；清洗幂等。

## P3-T07 章节与 ContentBlock 结构化

状态：`[ ]`

工作：标题、layout、目录和相邻页推断；保留 method/confidence；HTML table 结构；生成稳定 chunk ID。

验收：7 类代表 fixture；低置信章节不静默归类；chunk 可回 raw 页。

## P3-T08 质量报告和门禁

状态：`[ ]`

工作：页覆盖、空页、乱码、表格、章节、可疑词、映射和 terminal 状态；JSON + Markdown summary；nonzero exit gate。

验收：故意缺页/错表/可疑词 fixture 正确失败；summary 不含完整原文。

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
