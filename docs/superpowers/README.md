# wxzy Superpowers 文档基线

状态：Active baseline
版本：v1
更新时间：2026-07-22

## 这组文档解决什么问题

这组文档是 wxzy 后续开发的唯一工作基线。它把产品需求、离线文档处理、学习小程序、后端系统和实施任务分开描述，避免把“PDF 已解析”误认为“用户已经可以学习”，也避免把离线处理工具塞进小程序运行时。

## 权威顺序

当多个文件出现冲突时，按以下顺序解释：

1. 当前用户和系统指令。
2. [`AGENT.md`](../../AGENT.md) 中的项目硬约束。
3. [`PROJECT_RULES.md`](PROJECT_RULES.md) 中的工程规则。
4. 当前标记为 Active 的规格和设计文档。
5. 当前实施计划中已批准的任务。
6. `docs/PRODUCT_PLAN.md`、`docs/IMPLEMENTATION_PLAN.md` 和 `docs/MVP_CARD_FSRS.md` 等旧文档。

旧文档保留作历史依据，不得单独驱动新功能；若要恢复其中的内容，必须在新的规格或实施任务中明确写出。

## 文档地图

| 文档 | 用途 | 状态 |
|---|---|---|
| [`PROJECT_RULES.md`](PROJECT_RULES.md) | 模型执行规则、代码工程规范、质量门禁 | Active |
| [`specs/2026-07-22-wxzy-product-requirements.md`](specs/2026-07-22-wxzy-product-requirements.md) | 产品 PRD、范围、用户故事、验收指标 | Baseline |
| [`specs/2026-07-22-system-design.md`](specs/2026-07-22-system-design.md) | 服务边界、数据模型、API、状态机、安全 | Baseline |
| [`specs/2026-07-22-document-processing-design.md`](specs/2026-07-22-document-processing-design.md) | 7 本 PDF 的全量处理和卡片生产线 | Baseline |
| [`specs/2026-07-22-learning-miniprogram-design.md`](specs/2026-07-22-learning-miniprogram-design.md) | 小程序信息架构、学习方法、个性化体验 | Baseline |
| [`plans/2026-07-22-wxzy-implementation-plan.md`](plans/2026-07-22-wxzy-implementation-plan.md) | 分阶段、分任务、依赖、验证和交付顺序 | Active plan |

## 两条业务边界

### 文档处理控制面

运行在本地工作站或服务端任务环境，负责 PDF 清单、拆分、MinerU、清洗、页码映射、质量检查、候选卡生成和人工审核。它可以使用 Python、MinerU、Qwen、OSS 和批处理脚本，但不进入小程序包。

### 学习产品运行面

小程序只读取已发布的文档目录、卡片、来源和用户学习状态，负责学习计划、主动回忆、作答、反馈、统计和设置。它不能直接访问 MinerU、Qwen、数据库或原始 PDF 私有路径。

## 模型执行入口

接到新任务时，模型必须按以下顺序工作：

1. 读取本文件、`AGENT.md` 和适用的规格文档。
2. 在代码中确认现状，不把设计目标当成已实现能力。
3. 把任务拆成可验证的小任务，写入实施计划或任务说明。
4. 先修改边界内的最小文件集合，再运行对应质量门禁。
5. 在结果中报告改动、验证、未完成项和风险。

## 术语

- **文档**：原始 PDF 的逻辑实体。
- **文档版本**：同一本书的一个不可变文件版本。
- **内容块**：带源页、章节和原文的可检索片段。
- **候选卡**：尚未完成事实审核的生成结果。
- **发布卡**：已通过内容审核、可供学习计划选择的卡片。
- **加入学习**：把发布卡纳入某个用户的学习范围；不等于发布。
- **复习状态**：某个用户对某张卡的 FSRS 状态。
- **学习会话**：一次有开始、结束、计划和结果的学习活动。

## 更新规则

- 需求变化先更新 PRD，再更新设计和实施任务。
- 数据模型、接口或状态机变化必须同时更新系统设计和迁移任务。
- 处理质量规则变化必须更新文档处理设计和质量报告格式。
- 规则变化必须在变更说明中写出影响范围和验证方式。
- 不把生成的 PDF、OCR 压缩包、数据库和含密钥的本地配置提交到 git。
