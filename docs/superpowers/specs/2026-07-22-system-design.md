# wxzy 总体系统设计

状态：Baseline v1
日期：2026-07-22
关联 PRD：[`2026-07-22-wxzy-product-requirements.md`](2026-07-22-wxzy-product-requirements.md)

## 1. 设计目标

本设计把当前卡片原型演进为可维护的个人学习系统，重点解决：

- 唯一用户身份和个人学习状态。
- 文档内容与学习状态的边界。
- 704 页文档处理的可恢复和可追溯。
- 内容发布与用户加入学习的分离。
- 标准 FSRS、幂等作答和可解释每日计划。
- 微信小程序、FastAPI 和离线任务各自独立演进。

## 2. 现状约束

当前代码可保留作为行为原型，但不是目标架构：

- `ReviewState` 与 `Card` 一对一，尚无 `user_id`。
- 导入 approved 卡时立即创建到期状态。
- `ReviewLog` 只记录 rating，缺少幂等键、耗时、会话和提示信息。
- 使用固定 Bearer Token，无微信登录和 Session。
- 服务启动时 `create_all()`，没有迁移版本。
- API 未版本化，错误响应使用 FastAPI 默认 `detail`。
- `tools/generate_candidate_cards.py` API 模式只处理输入前段。
- 文档任务有初步 manifest，但没有完整任务状态机和内容持久化模型。

## 3. 逻辑上下文

系统按五个 bounded context 组织：

1. **Identity & Profile**：唯一 Owner、Session、目标和偏好。
2. **Document Processing**：PDF、任务、页、清洗、结构化和质量。
3. **Content Catalog**：书籍、章节、发布卡和来源。
4. **Learning & Scheduling**：enrollment、每日计划、FSRS、作答和薄弱点。
5. **Mini Program Presentation**：页面、交互、API 客户端和本地会话缓存。

Document Processing 是控制面；其余后端模块和小程序构成学习运行面。

## 4. 总体架构

```text
                     文档处理控制面

  docs/*.pdf
      |
      v
  inventory -> split -> MinerU -> clean -> structure -> generate
      |                                                   |
      +---- manifest / quality report / immutable data ---+
                                                          |
                                                    candidate review
                                                          |
                                                    versioned publish bundle
                                                          |
                                                          v
微信小程序 <---- HTTPS /api/v1 ---- FastAPI ---- PostgreSQL
    |                                  |             |
    |                                  |             +-- identity/profile
    |                                  |             +-- content catalog
    |                                  |             +-- learning/reviews
    |                                  |
    +-- pages/services                 +-- admin publish importer

私有原始文件和中间产物可迁移到 OSS；小程序只接收必要的分页数据和短来源摘录。
```

## 5. 运行与部署单元

### 5.1 Mini Program

- 微信原生小程序。
- 只依赖 HTTPS API。
- 本地仅缓存 Session、非敏感设置和短期页面状态。
- 不保存模型 Key、AppSecret、数据库凭据和完整 PDF。

### 5.2 API Service

- FastAPI + Pydantic + SQLAlchemy。
- 提供身份、档案、目录、计划、复习、统计和发布导入 API。
- 承担鉴权、事务、幂等、领域规则和审计。

### 5.3 Document Worker/CLI

- 初期为本地 Python CLI，后续可演进为异步任务 Worker。
- 调用 MinerU/Qwen，写版本化 manifest 和数据产物。
- 不作为 API 进程启动依赖，文档处理失败不能让学习 API 不可用。

### 5.4 Data Stores

- PostgreSQL：关系数据、学习状态、发布目录和审计。
- SQLite：仅本地开发和 focused test。
- 本地 `data/` 或私有 OSS：PDF、中间产物、图片和发布包。
- Redis：仅在确有任务队列、锁或缓存需求时引入，不作为第一阶段前置条件。

## 6. 目标目录结构

当前目录可以渐进迁移，目标结构如下：

```text
miniprogram/
  pages/
  components/
  services/
  utils/

server/
  app/
    api/v1/
    core/
    identity/
    catalog/
    learning/
    publishing/
  migrations/
  tests/

tools/
  document_pipeline/
    inventory/
    parsing/
    cleaning/
    structuring/
    generation/
    quality/
    publishing/
  tests/

docs/superpowers/
data/                       # ignored, generated artifacts
```

不要求一次性搬迁现有文件；每个实施任务按模块逐步迁入，避免大爆炸重构。

## 7. 领域数据模型

### 7.1 Identity & Profile

#### User

| 字段 | 说明 |
|---|---|
| id | 内部稳定 UUID/整数 ID |
| wechat_openid_hash | OpenID 的安全存储或加密值；不向普通接口返回 |
| status | active/disabled |
| display_name | 可选昵称 |
| timezone | 默认 Asia/Shanghai |
| created_at/updated_at | UTC |

约束：最多一个 active User。保留 `user_id` 是为了数据归属和多设备，不开放多用户产品能力。

#### UserSession

| 字段 | 说明 |
|---|---|
| id | Session ID |
| user_id | Owner |
| token_hash | 只存哈希 |
| expires_at | 过期时间 |
| revoked_at | 可撤销 |
| device_label | 可选设备说明 |

#### LearningProfile

| 字段 | 说明 |
|---|---|
| user_id | 唯一 Owner |
| goal_type | 日常学习/考试/专项 |
| target_date | 可空 |
| daily_minutes | 默认 20 |
| study_days | 周一至周日布尔集合 |
| desired_retention | 初始 0.90 |
| new_card_ceiling | 默认 5–10 |
| subject_priorities | 结构化权重 |
| onboarding_completed_at | 冷启动状态 |

### 7.2 Document Processing

#### Document

逻辑书籍，包含标准名、学科、版本说明和版权备注；不等于一次具体上传。

#### DocumentVersion

| 字段 | 说明 |
|---|---|
| id | 内容版本 ID |
| document_id | 所属文档 |
| source_sha256 | 原文件指纹 |
| source_file_name | 文件名，不暴露本地绝对路径给小程序 |
| page_count | PDF 页数 |
| size_bytes | 大小 |
| processing_version | 流水线版本 |
| status | 状态机字段 |

#### DocumentPage

记录 `pdf_page_index`、可选 `printed_page_label`、OCR 状态、质量分和图像引用。

#### DocumentChunk

记录章节路径、起止 PDF 页、原文、清洗文本、内容类型、质量状态和内容 hash。Chunk 是卡片来源的主要锚点。

#### ProcessingJob

记录阶段、批次、输入输出版本、状态、重试、外部 trace、耗时、错误码和成本信息。

### 7.3 Content Catalog

#### Book/Chapter

Book 是对 Document 的学习目录投影；Chapter 具有父子层级、排序、来源页范围和发布版本。

#### CandidateCard

| 字段 | 说明 |
|---|---|
| id | 稳定 ID |
| content_version | 生成所基于的内容版本 |
| card_type | 类型 |
| question/answer | 候选问答 |
| answer_points | 结构化要点 |
| risk_level | low/medium/high/critical |
| status | generated/needs_review/approved/rejected |
| generator/model/prompt_version | 生成追踪 |
| review_notes/reviewer/reviewed_at | 审核追踪 |

#### Card

发布目录中的不可变或版本化卡片。修改事实内容时创建新 `content_revision`，不直接改写历史作答对应的版本。

#### CardSource

Card 到 DocumentChunk 的多对多来源，记录引用顺序、原文摘录、PDF 页和印刷页。一个答案包含多个事实时可以有多个来源块。

### 7.4 Learning & Scheduling

#### CardEnrollment

| 字段 | 说明 |
|---|---|
| id | enrollment ID |
| user_id/card_id | 唯一组合 |
| status | queued/active/suspended/retired |
| priority | 用户或计划权重 |
| introduced_at | 首次进入新卡队列时间 |
| source | manual/chapter/plan |

只有 active 或 queued enrollment 才可能进入用户学习计划。

#### CardReviewState

| 字段 | 说明 |
|---|---|
| user_id/card_id | 唯一组合 |
| fsrs_state | 标准 FSRS 序列化状态 |
| due_at | UTC |
| stability/difficulty | FSRS 参数 |
| reps/lapses | 次数 |
| last_reviewed_at | UTC |
| algorithm_version | 算法版本 |

#### StudySession

记录计划类型、开始/结束、预计/实际分钟、计划任务数、完成数和中断原因。

#### ReviewAttempt

| 字段 | 说明 |
|---|---|
| id | 作答 ID |
| idempotency_key | 用户范围内唯一 |
| session_id/user_id/card_id/card_revision | 上下文 |
| rating | 1–4 |
| response_ms | 作答耗时 |
| reveal_count/hint_used | 行为信号 |
| answer_payload | 可选、受限长度的结构化作答 |
| due_before/due_after | 审计 |
| state_before/state_after | 审计 |
| algorithm_version | 审计 |

#### DailyPlan

记录日期、用户时间预算、生成版本、预测负荷、任务项和生成原因。计划项引用 enrollment/card，而不是复制卡片内容。

#### CardIssue

用户反馈：事实错误、来源错误、过大、过难、表述不清、概念混淆。Issue 可触发内容审核或学习修复。

#### TopicMastery

由 ReviewAttempt 和标签聚合得到的读模型，可重建。不得把单一自评分直接当成永久“已掌握”。

## 8. 关键关系

```text
User 1---1 LearningProfile
User 1---N UserSession
Document 1---N DocumentVersion 1---N DocumentPage/DocumentChunk
CandidateCard N---N DocumentChunk
Card N---N DocumentChunk through CardSource
User N---N Card through CardEnrollment
CardEnrollment 1---0..1 CardReviewState
StudySession 1---N ReviewAttempt
User/Card 1---N ReviewAttempt
DailyPlan 1---N DailyPlanItem
```

## 9. 状态机

### 9.1 DocumentVersion

```text
registered -> split -> parsing -> parsed -> cleaning -> structured
    -> quality_review -> ready_for_generation -> published

任一处理中状态 -> failed -> retrying -> 原阶段
quality_review -> needs_review -> quality_review
```

每页也有 terminal 状态：`ready`、`needs_review` 或 `failed`，用于计算 704 页覆盖。

### 9.2 CandidateCard

```text
generated -> needs_review -> approved -> published
                  |             |
                  +-> rejected  +-> superseded
```

模型置信度不能直接把状态变成 approved。

### 9.3 CardEnrollment

```text
queued -> active -> suspended -> active
                  -> retired
queued -> retired
```

Card 发布状态变化不会自动删除 enrollment；若卡被撤回，计划生成器排除并产生维护提示。

### 9.4 StudySession

```text
planned -> active -> completed
                  -> interrupted
planned -> cancelled
```

## 10. 认证设计

### 10.1 正式环境

1. 小程序调用 `wx.login()` 获取短期 code。
2. `POST /api/v1/auth/wechat` 把 code 发给后端。
3. 后端使用 AppID/AppSecret 调用微信 `jscode2session`。
4. 若未绑定 Owner，执行一次性 owner claim；若已绑定且 OpenID 不匹配则拒绝。
5. 后端签发随机 Session Token，只保存哈希。
6. 小程序把 Session 存入 `wx` storage，请求通过 Bearer Session 鉴权。

### 10.2 开发环境

通过显式配置 `AUTH_MODE=dev_token` 启用固定 Token。生产配置启动时若仍使用默认 Token 必须失败，而不是静默运行。

## 11. API 设计

### 11.1 通用约定

- 业务接口前缀 `/api/v1`。
- 时间使用 ISO 8601 UTC，展示层转本地时区。
- 列表接口使用 cursor 或稳定 offset 分页。
- 写接口接收 `Idempotency-Key` 或请求体 `client_attempt_id`。
- 错误格式：

```json
{
  "code": "REVIEW_ALREADY_SUBMITTED",
  "message": "本次评分已经提交",
  "request_id": "req_...",
  "details": null
}
```

### 11.2 Identity/Profile

| Method | Path | 用途 |
|---|---|---|
| POST | `/api/v1/auth/wechat` | 微信登录/绑定 |
| POST | `/api/v1/auth/refresh` | 刷新 Session |
| POST | `/api/v1/auth/logout` | 撤销 Session |
| GET | `/api/v1/me` | 当前 Owner |
| GET/PUT | `/api/v1/me/learning-profile` | 学习档案 |
| POST | `/api/v1/me/export` | 数据导出任务 |

### 11.3 Catalog

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/v1/catalog/books` | 学科/书籍目录 |
| GET | `/api/v1/catalog/books/{id}/chapters` | 章节树 |
| GET | `/api/v1/catalog/cards` | 发布卡搜索/分页 |
| GET | `/api/v1/catalog/cards/{id}` | 卡片和来源 |
| GET | `/api/v1/catalog/sources/{id}` | 必要来源详情 |

### 11.4 Learning

| Method | Path | 用途 |
|---|---|---|
| POST | `/api/v1/enrollments` | 加入书籍/章节/卡片 |
| PATCH | `/api/v1/enrollments/{id}` | 暂停/恢复/退出 |
| GET | `/api/v1/learning/today` | 今日计划摘要 |
| POST | `/api/v1/study-sessions` | 开始会话 |
| GET | `/api/v1/study-sessions/{id}/next` | 下一任务 |
| POST | `/api/v1/review-attempts` | 幂等提交评分 |
| POST | `/api/v1/cards/{id}/issues` | 卡片反馈 |
| GET | `/api/v1/insights/summary` | 学习概览 |
| GET | `/api/v1/insights/workload` | 未来负荷 |
| GET | `/api/v1/insights/weak-topics` | 薄弱主题 |

### 11.5 Publishing/Admin

| Method | Path | 用途 |
|---|---|---|
| POST | `/api/v1/admin/publications/validate` | 校验发布包 |
| POST | `/api/v1/admin/publications/import` | 幂等导入 |
| GET | `/api/v1/admin/publications/{id}` | 导入统计/冲突 |

Admin 接口不暴露给普通小程序页面；初期由 CLI 调用。

## 12. 每日计划算法

计划生成使用确定性规则和标准 FSRS 信号：

1. 读取用户当天分钟预算和学习日设置。
2. 获取已到期卡，按逾期风险、目标权重和卡片状态排序。
3. 用历史 response_ms 估算任务时长；数据不足时使用保守默认值。
4. 先填充到期卡，再填充 repair/weak-topic 任务。
5. 计算未来 7 天预测负荷；若超过预算，新增卡为 0。
6. 若仍有预算，从 queued enrollment 按章节顺序和优先级引入新卡。
7. 每周插入一次跨章节混合测试。
8. 为每个计划项记录 reason code，例如 `DUE`、`OVERDUE`、`WEAK_TOPIC`、`NEW_FROM_PRIORITY_CHAPTER`。

计划生成版本必须记录在 DailyPlan 中，确保后续可以解释为什么出现某张卡。

## 13. FSRS 设计

- 使用标准、维护中的 Python FSRS 库，不继续扩展手写 `fsrs_simple.py`。
- 评分仍为 Again/Hard/Good/Easy。
- 初始 desired retention 为 0.90。
- 学习/重学步骤、参数和调度版本显式配置。
- 有足够历史前使用默认参数；不得用 15 张样例卡拟合个人参数。
- 每次 ReviewAttempt 保存前后状态和算法版本。
- 算法升级提供 dry-run 报告和可回滚迁移，不静默重排全部 due。

## 14. 发布和版本一致性

发布包包含：

- `schema_version`。
- `publication_id` 和生成时间。
- 文档/文档版本清单。
- 章节和内容块引用。
- 卡片及其 `content_revision`。
- 来源映射。
- 审核记录摘要。
- 文件级 SHA256。

导入事务规则：

1. 先做 schema、引用和 hash 校验。
2. 同 publication_id 重复导入返回原结果。
3. 稳定卡片 ID 相同但内容 hash 不同时创建 revision 或报告冲突。
4. 整个发布包在单个数据库事务中提交。
5. 导入发布卡不自动创建 CardReviewState。

## 15. 并发和幂等

- `ReviewAttempt.idempotency_key` 在 `user_id` 范围唯一。
- 提交时锁定或原子更新对应 CardReviewState。
- 重复请求返回首次提交结果。
- enrollment 创建使用 `(user_id, card_id)` 唯一约束。
- 文档任务使用 `(document_version_id, stage, pipeline_version, input_hash)` 唯一约束。
- 发布使用 publication_id 和 manifest hash 双重检查。

## 16. 安全与隐私

- OpenID、Session Token、AppSecret 和模型 Key 使用不同配置项。
- Session Token 只存哈希，支持撤销。
- 原 PDF 和 OCR 图片默认私有；小程序来源接口只返回最小必要摘录。
- 管理 API 需要 Owner Session 之外的 admin capability 或本地管理凭据。
- 日志脱敏 Authorization、上传 URL query、OpenID、完整原文和模型上下文。
- 不保存与学习无关的健康信息。

## 17. 可观测性

所有 API 请求记录 request_id、route、status、duration_ms 和 user_id 的非可逆内部标识。

文档任务记录：

- document_version、stage、batch_id。
- 页数进度、重试次数和耗时。
- MinerU/Qwen model version、token/cost（若可获得）。
- 错误 code 和脱敏摘要。
- 输入/输出 hash。

核心指标：API 错误率、作答重复率、计划生成耗时、文档页覆盖、候选审核积压、发布冲突和未来复习负荷。

## 18. 测试架构

### Unit

- FSRS adapter、计划排序、负荷限制、状态机、稳定 ID、页码映射、OCR 清洗。

### Integration

- 认证交换、publication import、enrollment、幂等 review、SQLite/PostgreSQL migration。

### Contract

- Pydantic/OpenAPI schema、发布包 JSON Schema、小程序 API fixture。

### End-to-end

- Owner 登录 -> 设置档案 -> 加入章节 -> 获取今日计划 -> 评分 -> 统计变化。
- PDF fixture -> parse fixture -> clean -> candidate -> review -> publication -> catalog。

## 19. 原型数据迁移

迁移顺序：

1. 建立 Alembic 基线，捕获现有表结构。
2. 创建唯一 Owner 和默认 LearningProfile。
3. 把现有 Book/Card 转为 Content Catalog。
4. 为现有 15 张有 ReviewState 的卡创建 CardEnrollment。
5. 把 ReviewState 迁移为带 user_id 的 CardReviewState。
6. 把 ReviewLog 迁移为 ReviewAttempt，生成 legacy idempotency key。
7. 校验迁移前后卡数、due 数和 review 数。
8. 保留回滚备份，删除 `create_all` 生产依赖。

## 20. 关键设计决策

| ID | 决策 | 原因 |
|---|---|---|
| ADR-001 | 保留 User 实体但限制一个 active Owner | 正确归属学习状态，不引入多用户产品 |
| ADR-002 | 文档处理控制面与学习运行面分离 | 大文件、密钥和长任务不适合小程序 |
| ADR-003 | 发布与 enrollment 分离 | 避免全量内容造成当天复习爆炸 |
| ADR-004 | 标准 FSRS 替换手写近似实现 | 算法已有成熟实现，需要可审计版本 |
| ADR-005 | PostgreSQL 为生产真相，SQLite 为开发辅助 | 支持事务、迁移和未来 JSON/检索能力 |
| ADR-006 | 先规则化个性学习，再使用 AI 建议 | 可解释、可测试，避免模型随意调度 |
| ADR-007 | 内容 revision 不覆盖历史事实版本 | 保持作答和来源审计一致 |

## 21. 延后决策

- 是否增加 pgvector/RAG，不阻塞全量卡片和学习闭环。
- 是否使用 Redis/独立 Worker，待本地批处理不足时决定。
- 是否在小程序内加入完整章节阅读，先以来源摘录和跳转定位为主。
- 是否自动拟合个人 FSRS 参数，待累积足够真实复习数据后评估。
