# wxzy 文档处理与卡片生产设计

状态：Baseline v1
日期：2026-07-22
边界：离线/服务端控制面，不属于微信小程序运行时

## 1. 设计目的

把 `docs/` 中 7 本、704 页、约 1.58 GB 的 PDF 全量转换为可追溯的结构化内容和候选卡，并通过质量门禁和人工审核生成版本化发布包。

本设计只负责“内容如何可靠地产生和发布”。用户登录、每日计划、复习和统计由学习系统负责。

## 2. 硬边界

### 控制面负责

- 原始 PDF 清单和版本。
- 文件拆分、MinerU 上传/轮询/下载。
- OCR 清洗、页码和章节映射。
- 内容块结构化和质量报告。
- 候选卡生成、审核、冲突处理和发布包。

### 小程序不负责

- 上传大 PDF。
- 显示 MinerU batch、上传 URL、OSS 签名或本地路径。
- 运行 OCR、Qwen 或清洗脚本。
- 修改原始解析产物。
- 把候选卡直接加入复习。

小程序只能消费后端已经导入的发布目录和短来源摘录。

## 3. 输入清单

| document_key | 文件 | 页数 | 大小约 | 风险提示 |
|---|---|---:|---:|---|
| neike | 学霸笔记—中医内科学(1).pdf | 149 | 345.1 MB | 多教材版本、证型表 |
| jichu | 学霸笔记—中医基础理论(1).pdf | 102 | 237.1 MB | 概念关系和古文 |
| zhenduan | 学霸笔记—中医诊断学(1).pdf | 92 | 206.0 MB | 证候、诊断要点和表格 |
| zhongyao | 学霸笔记—中药学(1).pdf | 88 | 190.1 MB | 剂量、毒性、禁忌、相似药物 |
| renwen | 学霸笔记—人文(1).pdf | 39 | 102.3 MB | 法规、伦理、版本时效 |
| fangji | 学霸笔记—方剂学(1).pdf | 140 | 327.9 MB | 组成、剂量、方歌、主治 |
| zhenjiu | 学霸笔记—针灸学(1).pdf | 94 | 210.2 MB | 穴位定位、深度、操作禁忌 |

现有上传工具拒绝超过 200 MB 的单文件，因此 5 本必须物理拆分；另外两本也建议统一走可恢复的小批次。

## 4. 完成定义

“7 本书处理完成”必须同时满足：

1. 原始文件 SHA256、页数和版本已登记。
2. 704 个 PDF 页都有唯一映射和 terminal 状态。
3. 每页 terminal 状态是 `ready`、`needs_review` 或 `failed`，不存在失联页。
4. 章节树和内容块可以回到原 PDF 页。
5. 自动质检报告覆盖每本书和每个物理批次。
6. 未通过质量门禁的内容没有进入发布包。
7. 已发布卡片均有审核状态、来源块和内容 revision。

完成全量解析不要求所有候选卡立即发布，也不要求所有发布卡立即加入用户学习。

## 5. 处理流水线

```text
inventory
  -> split
  -> submit/poll/download
  -> preserve raw
  -> deterministic clean
  -> page/chapter structure
  -> quality gate
  -> semantic chunk
  -> candidate generation
  -> automated card validation
  -> human review
  -> versioned publication
```

每个箭头都是独立、可重跑、可观察的阶段，不使用一个脚本从头跑到底后只留下最终 JSON。

## 6. 产物目录

`data/` 默认被 gitignore，建议使用：

```text
data/document-pipeline/
  inventory/
    documents.v1.json
  sources/
    <document_key>/<sha256>/              # 可指向 docs 原文件，不复制也可
  splits/
    <document_version>/<split_id>.pdf
    <document_version>/split-manifest.json
  runs/
    <job_id>/manifest.json
    <job_id>/events.jsonl
  raw/
    <document_version>/<split_id>/         # MinerU 原始解包，只读
  cleaned/
    <document_version>/<pipeline_version>/
  structured/
    <document_version>/<pipeline_version>/
  candidates/
    <document_version>/<generation_version>/
  reviews/
    <review_batch_id>/
  publications/
    <publication_id>/manifest.json
```

tracked 仓库只保存 schema、规则、模板、测试 fixture 和不含原文的覆盖摘要；完整 OCR 和 PDF 不提交。

## 7. Inventory 契约

每个文档版本至少记录：

```json
{
  "schema_version": 1,
  "document_key": "fangji",
  "title": "学霸笔记—方剂学",
  "source_file_name": "学霸笔记—方剂学(1).pdf",
  "source_sha256": "...",
  "page_count": 140,
  "size_bytes": 343816000,
  "copyright_scope": "personal-use",
  "registered_at": "2026-07-22T00:00:00Z"
}
```

绝对路径仅存在于本地运行 manifest，不进入 publication 和 API。

## 8. PDF 拆分

### 8.1 拆分规则

1. 优先通过目录页或标题检测确定章节边界。
2. 每块目标 20–30 页；章节过长时按页切分。
3. 每个物理块必须小于外部服务限制，并预留大小波动空间。
4. PDF 页不重复、不遗漏；语义 chunk 可以有少量上下文重叠。
5. 每块生成稳定 `split_id = document_version + page_start + page_end`。

### 8.2 映射字段

- `split_page_index`：拆分 PDF 内 0-based。
- `source_pdf_page_index`：原 PDF 内 0-based，系统主键字段。
- `source_pdf_page_number`：面向人类的 1-based。
- `printed_page_label`：OCR 提取的印刷页码，可空或为字符串。
- `mapping_confidence`：页码映射置信度。

不得把印刷页码和 PDF 文件页混为一个整数。

## 9. MinerU 集成

### 9.1 提交

- 每次提交使用稳定 data_id，不依赖文件名偶然值。
- 记录 model_version、OCR 开关、language、table/formula 开关。
- 上传 URL 和签名 query 必须脱敏，不写入长期日志。
- 单批文件数保持保守，先以 4–8 个 split 为一批，再按实测调整。

### 9.2 轮询

- 状态变化和页进度写入 events。
- 超时不等于任务失败；保留 batch_id 供后续继续 poll。
- 外部 `failed` 保存原始错误码和脱敏摘要。

### 9.3 下载

- 原始 zip、`full.md`、content list、layout 和 images 版本化保存。
- 下载完成校验 zip 可打开、预期入口存在和 hash 一致。
- 解包路径防止 zip-slip，不信任外部文件名。

## 10. 原始产物保护

以下内容不可被清洗命令覆盖：

- 原 PDF。
- 物理拆分 PDF。
- MinerU 原始 zip。
- 原始 `full.md`。
- 原始 content list/layout JSON。

所有清洗产物写新目录，并记录 `input_hash`、规则版本、输出 hash 和时间。

## 11. 确定性清洗

### 允许自动执行

- 删除明确识别的重复页眉、页脚和独立页码行。
- 规范空白、换行和已人工确认的固定 OCR 词典。
- 保留 HTML table 结构并规范无语义属性。
- 统一可逆的标点和 Unicode 形式。

### 禁止自动执行

- 根据常识补齐缺失药名、剂量、方名或穴位。
- 把多个教材版本合并成一个答案。
- 对古文、方歌和组成做无来源的改写。
- 删除无法识别但可能是正文的内容。

每条替换记录 rule_id、before/after、页号和计数，可从 cleaned 回到 raw 证据。

## 12. 结构化内容模型

### PageRecord

```json
{
  "document_version_id": "...",
  "source_pdf_page_index": 19,
  "source_pdf_page_number": 20,
  "printed_page_label": "294",
  "status": "ready",
  "quality_flags": [],
  "content_block_ids": ["..."]
}
```

### ContentBlock

```json
{
  "id": "stable-hash",
  "document_version_id": "...",
  "chapter_path": ["第四部分 方剂学", "第九章 解表剂"],
  "source_pdf_pages": [20],
  "printed_page_labels": ["294"],
  "block_type": "table",
  "raw_text_ref": "...",
  "cleaned_text": "...",
  "quality_status": "ready",
  "quality_flags": [],
  "pipeline_version": "..."
}
```

结构化阶段保留原文顺序和 table 单元格，不提前转换成问答。

## 13. 章节识别

章节树来自以下信号的组合：

- Markdown 标题。
- 页内大字号/layout 信息。
- 目录页。
- 页眉中的学科/章信息。
- 相邻页连续性。

识别结果保留 `method` 和 `confidence`。低置信边界进入人工复核，不把后续所有页错误归入同一章。

## 14. 语义分块

- 方剂表以一张完整方剂或一个明确字段组为边界。
- 中药条目以单味药及其字段为边界。
- 内科以疾病、证型或版本小节为边界。
- 基础理论以定义、机制、关系和对比表为边界。
- 诊断以诊法、症状、证候和鉴别条目为边界。
- 针灸以经络、穴位或操作主题为边界。
- 人文以法规条款、伦理原则或情境题知识点为边界。

Chunk 要足够包含答案依据，但不把整章交给一个模型请求。

## 15. 卡片模板

### 中医基础理论

- 概念定义。
- 生理功能和病理机制。
- 五行、脏腑、气血津液之间的关系。
- 易混概念对比。

### 中医诊断学

- 四诊要点。
- 症状/舌脉与证候映射。
- 证候定义、辨证要点和鉴别。
- 有明确来源的情境判断题。

### 中药学

- 性味归经、功效、主治。
- 配伍、相似药物对比。
- 用法用量、毒性和禁忌。
- 高风险字段全部单独标记。

### 方剂学

- 组成、功用、主治、方歌。
- 配伍意义和关键用法。
- 相似方剂对比。
- 剂量和古文原句为高风险。

### 中医内科学

- 疾病概念、病因病机和治则。
- 一证一张的证型-治法-代表方。
- 症状要点和鉴别。
- 多版本教材分别建卡并明确版本。

### 针灸学

- 经络循行和主治概要。
- 穴位定位、归经、主治。
- 操作方法和注意事项。
- 定位、针刺深度/方向和禁忌为高风险。

### 人文

- 法规和伦理原则。
- 人物/历史事实。
- 场景化判断依据。
- 有时效性的法规记录版本或日期。

## 16. 候选生成

### 16.1 确定性提取优先

结构明确的表格字段先由 parser 提取，减少模型自由改写。模型适合：

- 把长段拆成最小知识点。
- 生成对比题和结构化 answer_points。
- 对低风险定义做忠实问答转换。

### 16.2 全量遍历

生成器按 ContentBlock/Chapter 游标处理，不能使用 `md[:max_chars]` 代表全书。每个请求记录：

- 输入 chunk IDs。
- 输入 hash。
- 模型和 prompt 版本。
- 输出候选 IDs。
- token/成本和错误。

### 16.3 卡片最小信息原则

- 一卡一个明确召回目标。
- 答案过长时拆卡，原文完整内容留在来源。
- 问题不依赖未展示的选项或上下文。
- 需要版本、病名、方名或药名限定时写进问题。
- 不因追求数量生成低价值同义重复卡。

## 17. 风险分级

| 等级 | 示例 | 发布要求 |
|---|---|---|
| low | 简短概念、明确标题事实 | 自动校验后可进入批量人工确认 |
| medium | 病机总结、主治要点、对比 | 人工查看问题/答案/来源 |
| high | 剂量、方歌、证型代表方、法规 | 逐张人工审核 |
| critical | 毒性禁忌、针刺深度方向、多版本冲突 | 原 PDF 对照、逐张审核、禁止批量通过 |

置信度与风险是两个字段；高置信模型输出仍可能是 high/critical。

## 18. 自动质量门禁

### 文档级

- 页数和页覆盖一致。
- split 不重不漏。
- 所有 zip/JSON 可解析。
- 章节边界异常和空白页有报告。

### 页面/内容块级

- page mapping 完整。
- OCR 可疑词、乱码和极低文本量。
- table 行列异常、跨页断裂和标题噪声。
- source excerpt 可以从 cleaned/raw 找到。

### 卡片级

- JSON Schema 通过。
- question/answer 非空且长度合理。
- 稳定 ID 和内容 hash 可重复。
- 每个答案要点有来源覆盖。
- 重复/近重复检测。
- 多版本标签和风险字段完整。
- 模型新增但来源不存在的实体进入拒绝或复核。

## 19. 人工审核

### 审核视图最小信息

- 问题、答案和 answer_points。
- 书籍、章节、PDF 页和印刷页。
- 清洗后摘录及一键查看 raw 对照。
- 风险 flags、模型/规则版本和自动校验结果。
- Approve/Edit/Reject/Needs second review。

### 审核策略

- 每本书先审一个代表章节，校准模板后再扩量。
- low-risk 可按章节抽样并批量确认，但必须留下人为批准记录。
- high/critical 逐张确认。
- 编辑后的答案再次执行来源覆盖和 schema 校验。
- 审核完成不自动加入用户学习。

## 20. Publication 契约

发布包目录：

```text
publication/
  manifest.json
  documents.json
  chapters.json
  chunks.jsonl
  cards.jsonl
  card_sources.jsonl
  checksums.json
  quality-summary.json
```

`manifest.json` 必须包含 schema_version、publication_id、pipeline/generation/review 版本、文档版本、记录数量和 hash。

发布包不得包含：模型 Key、OpenID、用户学习数据、本地绝对路径、上传签名 URL 和无必要的整本原文。

## 21. 幂等与恢复

- 阶段唯一键：`document_version + stage + stage_version + input_hash`。
- 已成功阶段默认复用；`--force` 创建新版本，不覆盖旧版本。
- 外部 batch_id 可重新 poll/download。
- 每个 split 独立失败，不让整本书从零重跑。
- 候选生成可从最后成功 chunk 游标恢复。
- publication 导入根据 publication_id 和 hash 幂等。

## 22. 全量执行波次

### Wave 0：模板校准

每本书选一个代表章节，完成 parse -> structure -> candidate -> review -> publication。验收 7 种书籍模板和风险规则。

### Wave 1：全量解析

拆分并解析全部 704 页，先追求页 terminal 状态和来源完整，不急于生成全部卡片。

### Wave 2：全量结构化

完成章节树、PageRecord、ContentBlock 和每本质量报告；修复系统性 OCR/表格问题。

### Wave 3：按学习顺序生成

基础理论、诊断学、中药/方剂、内科学、针灸、人文依次生成候选；不阻塞用户先学习已发布章节。

### Wave 4：风险分层审核发布

持续发布通过审核的批次，并在后端目录中可见。发布速度与学习负荷解耦。

## 23. 质量报告

每本书报告至少包含：

- 总页、ready/needs_review/failed 页数。
- split 和 MinerU job 状态。
- 字符数、表格数、图片数和章节数。
- OCR 可疑词与影响页。
- 页码映射覆盖率。
- 候选数量、风险分布、审核通过率和拒绝原因。
- publication 数量和 hash。

仓库可跟踪不含完整原文的 summary，完整报告保存在 `data/` 或私有存储。

## 24. 测试

- PDF 拆分不重不漏。
- 源页和印刷页映射。
- zip-slip 防护和坏 zip。
- 清洗规则可重复、可追踪、不会覆盖 raw。
- HTML table rowspan/colspan fixture。
- 7 类书籍模板 fixture。
- 全量游标不会只处理首段。
- 稳定 ID、去重和版本升级。
- 高风险卡不能批量自动发布。
- publication schema、hash 和重复导入。

## 25. 运行安全

- 只处理确认有权个人使用的 PDF。
- API Key 来自环境或密钥服务，不输出值。
- OSS 和 MinerU 签名 URL 不进入长期 manifest。
- 清理临时文件前确认 raw/manifest 已持久化。
- 处理成本和外部配额在全量运行前做 Wave 0 估算。
