# AGENT.md

## 当前权威文档

后续开发以 [`docs/superpowers/README.md`](docs/superpowers/README.md) 为文档入口，并遵守：

- [`docs/superpowers/PROJECT_RULES.md`](docs/superpowers/PROJECT_RULES.md)：模型执行与工程硬规则。
- [`docs/superpowers/specs/2026-07-22-wxzy-product-requirements.md`](docs/superpowers/specs/2026-07-22-wxzy-product-requirements.md)：当前 PRD。
- [`docs/superpowers/specs/2026-07-22-system-design.md`](docs/superpowers/specs/2026-07-22-system-design.md)：总体系统设计。
- [`docs/superpowers/specs/2026-07-22-document-processing-design.md`](docs/superpowers/specs/2026-07-22-document-processing-design.md)：文档处理设计。
- [`docs/superpowers/specs/2026-07-22-learning-miniprogram-design.md`](docs/superpowers/specs/2026-07-22-learning-miniprogram-design.md)：学习小程序设计。
- [`docs/superpowers/plans/2026-07-22-wxzy-implementation-plan.md`](docs/superpowers/plans/2026-07-22-wxzy-implementation-plan.md)：分阶段实施计划。

`docs/PRODUCT_PLAN.md`、`docs/IMPLEMENTATION_PLAN.md` 和 `docs/MVP_CARD_FSRS.md` 是历史基线。出现冲突时，以 `docs/superpowers/` 中 Active/Baseline 文档为准。

## 项目定位

这是一个自用的中医学习微信小程序。产品目标是帮助用户阅读自己的中医 PDF 文献、理解知识、进行主动回忆，并依据间隔复习安排巩固内容。

产品是学习工具，不是医疗诊断、处方或在线问诊系统。任何功能、文案和模型提示词都必须保持这个边界。

系统只服务一个 Owner，但必须保存用户身份、学习档案、卡片加入状态和个人复习记录。单用户不等于无用户，也不意味着建设多用户、社交或租户系统。

## 系统边界

### 文档处理控制面

`tools/` 及未来任务服务负责 PDF 清单、拆分、MinerU、清洗、结构化、候选卡、质量检查、人工审核和版本化发布。原始 PDF 和中间产物不进入小程序包。

### 学习运行面

`server/` 和 `miniprogram/` 只向用户提供已发布内容、加入学习、每日计划、主动回忆、标准 FSRS、来源和统计。小程序不得直接调用 MinerU/Qwen，也不得展示本地处理路径和密钥。

### 内容和学习状态

`approved/published` 表示卡片内容可供选择；`enrolled` 才表示该卡进入唯一用户的学习范围。导入发布内容不得自动让全量卡片当天到期。

## 模型工作协议

1. 修改前读取本文件、Superpowers 入口、适用规格和当前任务。
2. 先检查代码现状，不把目标设计当作已经实现。
3. 跨模块、数据模型、接口、认证或算法变更先更新规格/计划。
4. 一个任务只处理一个可验收主题，并执行对应质量门禁。
5. 没有测试、接口、编译或质量报告证据时，不得声称完成。

## 后端和流水线硬约束

- 新业务接口使用 `/api/v1`，错误包含稳定 code、message 和 request_id。
- 生产数据库使用迁移管理，不依赖 `create_all()`。
- 写操作必须考虑幂等；复习重复点击不能生成重复记录。
- 标准 FSRS 使用成熟库和显式算法版本，当前手写实现只作过渡。
- 原 PDF、MinerU raw 和原始 `full.md` 不可被清洗覆盖。
- 全量文档完成以 704/704 页 terminal 状态和来源映射为准，不以样本成功代替。
- 生成卡必须先 candidate/needs_review；高风险医学事实必须人工审核。

## 官方依据

后续开发以微信小程序官方开发文档为准，重点参考：

- [开发指南](https://developers.weixin.qq.com/miniprogram/dev/framework/)
- [小程序代码构成](https://developers.weixin.qq.com/miniprogram/dev/framework/quickstart/code.html)
- [逻辑层 App Service](https://developers.weixin.qq.com/miniprogram/dev/framework/app-service/)
- [视图层 View](https://developers.weixin.qq.com/miniprogram/dev/framework/view/)
- [自定义组件](https://developers.weixin.qq.com/miniprogram/dev/framework/custom-component/)
- [分包加载](https://developers.weixin.qq.com/miniprogram/dev/framework/subpackages.html)
- [低版本兼容](https://developers.weixin.qq.com/miniprogram/dev/framework/compatibility.html)
- [运行时性能](https://developers.weixin.qq.com/miniprogram/dev/framework/performance/tips.html)
- [安全指引](https://developers.weixin.qq.com/miniprogram/dev/framework/security.html)
- [用户隐私保护](https://developers.weixin.qq.com/miniprogram/dev/framework/user-privacy/)

当本文件与微信官方文档冲突时，以官方文档和当前基础库行为为准，并更新本文件。

## 小程序开发规范

### 项目结构

采用微信小程序原生结构，使用以下文件类型：

- `app.json`：全局页面、窗口、TabBar、分包和组件配置。
- `app.js`：应用注册、全局生命周期和最小化的全局状态。
- `app.wxss`：全局基础样式和兼容的通用样式类；关键样式不依赖 `:root` 或 CSS 自定义属性。
- `pages/<page>/`：页面的 `.json`、`.wxml`、`.wxss`、`.js` 文件。
- `components/<component>/`：可复用组件的 `.json`、`.wxml`、`.wxss`、`.js` 文件。
- `utils/`：无界面的纯函数、格式化和兼容性工具。
- `services/` 或 `api/`：请求封装和后端接口定义，不在页面中散落请求细节。

页面和组件目录使用小写字母、中划线或下划线。页面、组件和接口命名要表达业务含义，避免 `test`、`temp`、`common2` 等无语义名称。

### 逻辑层和视图层

- 使用 `App()`、`Page()`、`Component()` 注册应用、页面和组件。
- WXML 负责结构和数据绑定，JS 负责状态和事件处理，WXSS 负责样式。
- 不使用浏览器环境 API，例如 `window`、`document`、DOM 查询或浏览器 `localStorage`。
- 页面状态通过 `this.setData()` 更新，禁止直接修改用于渲染的 `this.data`。
- 事件处理函数使用明确的动词命名，例如 `onSubmitAnswer`、`onOpenDocument`。
- 模板中的 `wx:if`、`wx:for` 和事件绑定应保持简单；复杂计算放到 JS 中完成。
- 组件通过 properties、内部 data、methods 和事件与父页面通信，不通过隐式全局变量通信。
- 页面销毁、切换和重复进入时，必须考虑请求取消、重复提交和状态重置。

### 配置和兼容

- JSON 必须是严格 JSON：双引号、无注释、只使用合法 JSON 类型。
- 新 API、组件属性或能力使用前，优先通过 `wx.canIUse`、API 存在性或基础库版本判断兼容性。
- 版本号必须按数字段比较，不能直接进行字符串比较。
- 需要强制最低基础库版本时，先用真实用户版本分布验证影响。
- 页面级差异配置放在对应页面的 `page.json`，不要把局部配置堆进 `app.json`。

### 样式和交互

- 使用 WXSS 支持的选择器和 `rpx`，避免依赖 Web CSS 未被小程序支持的特性。
- 全局样式只放基础色、字号、间距和通用状态；业务页面样式保持局部化。
- 样式类名按页面或组件加前缀，避免无意的全局污染。
- 长文本、古籍原文、引用和模型回答必须支持换行、滚动和复制，不能固定高度截断关键信息。
- 加载中、空状态、失败、无权限和完成状态都要有明确界面。
- 需要连续点击防护的操作必须在请求期间禁用或去重。

### 数据和网络

- 小程序只调用自有 HTTPS 后端；Qwen、向量模型和 Rerank 模型的密钥不得进入小程序代码包。
- 所有请求集中在 API 层，统一处理鉴权、超时、错误码、重试和取消。
- 后端返回稳定的业务错误码和面向用户的安全提示，不把堆栈、密钥或内部路径返回给前端。
- 仅在必要时调用 `setData`，避免传输大对象、整本书全文和高频无效更新。
- PDF、OCR 结果和长篇原文放在服务端或对象存储，前端按章节或片段分页获取。
- 流式回答、长任务和导入任务必须有超时、断线恢复或可重试状态。

### 知识检索和 AI

- MVP 主路径是「MinerU 解析 → 候选卡片 → 人工审核 → 上传后端 → FSRS 复习」，不做诊疗。
- 向量检索 / RAG 问答是后续可选能力，不阻塞第一版复习闭环。
- 文档与卡片必须保留书名、章节、页码（有则写）；关键结论尽量可回溯到原文摘录。
- 模型不得伪造书名、页码、原文、剂量或方剂组成。
- 自动生成的卡片和题目先进入 candidate/needs_review，确认后（approved/published）才能进入内容目录；只有显式 enrollment 才进入个人复习计划。
- 涉及个人症状时只提供学习性解释，不能输出诊断、处方或替代医生的建议。
- 小程序不直接调用 MinerU / Qwen；密钥只存在服务端或本地解析环境。

### 安全、隐私和版权

- 互不信任：用户输入、检索参数和模型返回都必须在后端校验。
- 鉴权、权限和文档访问控制必须在后端完成，不能靠前端隐藏按钮代替。
- AppSecret、Qwen API Key、数据库凭据和内部地址只能存放在服务端配置中。
- 不在小程序代码、日志或注释中保存敏感信息；日志默认脱敏。
- 涉及个人信息时同步维护微信平台要求的用户隐私保护指引和授权流程。
- 仅处理有权使用的 PDF；不公开分享受版权保护的整本内容，引用遵循最小必要原则。

### 性能和可观测性

- 首屏优先加载必要数据，书籍列表、章节内容和复习队列按需加载。
- 大量文本、图片和模型结果不得一次性写入页面 data。
- 对导入、OCR、向量化、Rerank 和 Qwen 请求记录耗时、失败原因和可追踪 ID，但不记录敏感原文。
- 使用微信开发者工具的性能面板和体验评分检查启动、渲染、网络、内存和包体积。
- 达到体积或首屏瓶颈时使用分包和预加载，不能为了“预留”而过早拆分。

### 测试和交付检查

每个功能至少验证：

1. 正常流程、空状态、加载中、失败和重试。
2. 重复点击、快速返回、断网和接口超时。
3. 长标题、长古文、特殊字符、图片缺失和 OCR 错误。
4. 当前基础库以及产品支持的最低基础库。
5. 用户输入不会绕过后端鉴权或访问不属于自己的内容。
6. AI 答案能回溯到正确文档和页码，无法回溯时明确标注。

变更说明中应写明影响范围、验证方式和已知限制。不要为了完成局部功能顺手重构无关模块。
