# 温习 Android APP 设计

状态：Active v1
日期：2026-07-27
关联 PRD：[`2026-07-22-wxzy-product-requirements.md`](2026-07-22-wxzy-product-requirements.md)
关联系统设计：[`2026-07-22-system-design.md`](2026-07-22-system-design.md)

## 1. 决策与目标

在保持微信体验版可用的同时，为唯一 Learner 提供可私有安装的 Android APP“温习”。
APP 复用现有 FastAPI、PostgreSQL、已发布内容、Owner、学习档案、计划、FSRS 和历史记录，
不建立第二套后端或第二个用户体系。

已确认的交付配置：

| 项目 | 值 |
|---|---|
| APP 名称 | 温习 |
| Android applicationId | `xin.luoandlt.wxzy` |
| 首个测试版本 | `0.1.0` / versionCode `1` |
| 首个目标设备 | OPPO Find X7 Pro |
| 目标系统 | 以真机连接后读取的 ColorOS / Android 版本为准 |
| 分发方式 | 私有 HTTPS 下载的签名 APK |
| 数据模式 | 联网优先；服务端为学习数据真相 |

## 2. 仓库与边界

Android 客户端放在当前仓库根目录的独立 `mobile/`，不放进 `miniprogram/`，也不新建仓库。
这样可以让移动认证、API 契约和客户端在同一变更中验证，同时避免微信开发者工具扫描 Android
源码和构建产物。

```text
wxzy/
  server/                  # 共用 API、认证、计划、FSRS 和 PostgreSQL
  miniprogram/             # 保留微信体验版
  mobile/                  # React/TypeScript/Capacitor Android 客户端
    src/
      app/                 # 路由、启动和全局边界
      components/          # 稳定复用的展示与交互组件
      features/            # auth/today/study/catalog/insights/profile
      services/            # HTTP、Session、API 契约
      platform/            # secure storage、Android lifecycle、back button
    android/               # 可复现的 Capacitor 原生工程
  deploy/
  tools/
```

首阶段不建立跨客户端 `shared/` 包。小程序客户端仍绑定 `wx.*` 和 CommonJS；Android 客户端使用
浏览器/Capacitor 适配层和 TypeScript。只有实际出现稳定、无平台依赖的重复逻辑时才提取共享包。

## 3. 技术栈

- React + TypeScript + Vite：移动端界面和开发构建。
- Capacitor：把同一 Web 产物封装为 Android APP。
- 小型 hash route adapter：四个一级入口和任务页面导航；避免引入当前命中高危审计公告且未使用的 SSR/RSC 路由能力。
- TanStack Query：只管理服务端查询缓存、失效和请求状态；不保存学习领域真相。
- Android Keystore 支持的安全存储插件：保存 Session Token；不得用普通 localStorage。
- Vitest + Testing Library：领域适配器和页面状态测试。
- Playwright：移动 viewport 的浏览器闭环。
- Gradle/Android SDK：生成签名 APK。

依赖使用实施时的稳定版本并锁定 lockfile。新增依赖必须通过许可证、维护状态、Android 16
兼容性和包体积检查。

## 4. 产品边界

APP 提供与学习小程序一致的学习运行面：

- 设备激活、自动登录、学习档案和设备会话。
- 今日计划和 10/20/30 分钟调整。
- 学科、章节、发布卡和加入学习。
- 主动回忆、可选书写、答案要点、来源和四档评分。
- 进度、未来负荷、薄弱点和周测。
- 数据导出、会话撤销和本地退出。

APP 不提供 PDF 导入、MinerU/Qwen 控制、候选审核、数据库管理、生产密钥配置或医疗建议。
第一版不承诺完整离线学习、后台推送和应用内自动更新。

## 5. 身份与设备激活

### 5.1 不变量

- 数据库最多一个 active Owner。
- 当前微信 Owner 和 Android Learner 是同一个 User 行。
- APP 不调用微信接口，不包含 AppID/AppSecret。
- Session Token 只在签发时返回，数据库只存哈希。
- 激活码只存哈希、单次使用、短期有效、可撤销。

### 5.2 OwnerActivationCode

新增 `owner_activation_codes`：

| 字段 | 约束 |
|---|---|
| id | 整数主键 |
| user_id | 指向唯一 active Owner，删除 Owner 时级联删除 |
| code_hash | SHA-256，唯一，不保存明文 |
| expires_at | timezone-aware UTC，默认短期有效 |
| used_at | 成功激活时原子写入；不可重复使用 |
| revoked_at | 管理员可提前撤销 |
| created_at | UTC |

服务端 CLI 生成高熵激活码并只显示一次。CLI 不把码写入日志、shell history 或仓库；Operator
通过线下或受控渠道交给 Learner。第一版支持粘贴，不要求手输短 PIN。

### 5.3 激活流程

1. Operator 在服务器为现有 Owner 签发一次性激活码。
2. Learner 在 APP 首屏粘贴激活码，并填写可识别的设备标签。
3. `POST /api/v1/auth/mobile/activate` 校验哈希、有效期、撤销和使用状态。
4. 同一事务中标记激活码已用并签发普通 `UserSession`。
5. APP 把 Token 写入 Android 安全存储，随后调用 `/api/v1/me`。
6. 重复使用返回稳定的通用无效错误，不泄露码是否存在或对应用户。

现有 `/api/v1/auth/refresh`、`/logout`、`/me/sessions` 和撤销接口继续用于 Android。
生产 `AUTH_MODE=wechat` 目前实际表示“Session Bearer + 微信登录提供方”；P10 先兼容该配置，
不为移动端另建一套 Token。是否改名为 provider-independent `session` 在完成双端回归后决定。

## 6. API 增量

| Method | Path | 用途 |
|---|---|---|
| POST | `/api/v1/auth/mobile/activate` | 一次性激活并签发 Owner Session |
| POST | `/api/v1/auth/refresh` | 轮换当前 Session |
| POST | `/api/v1/auth/logout` | 撤销当前 Session |
| GET | `/api/v1/me/sessions` | 查看微信/Android 设备会话 |
| DELETE | `/api/v1/me/sessions/{id}` | 撤销指定设备会话 |

激活接口输入只包含 `activation_code` 和最小 `device_label`，输出复用 `SessionTokenOut`。
所有失败使用稳定 `code/message/request_id`；日志不得包含激活码、Token、OpenID 或完整请求体。

## 7. 客户端架构

### 7.1 一级导航

沿用“今日、学科、进度、我的”四个一级入口。任务页面包括激活、引导、学习会话、章节、
卡片详情、来源、薄弱点、周测和档案编辑。

### 7.2 状态所有权

- 安全存储：Session Token 和到期时间。
- 运行时认证状态：booting/activating/ready/expired/offline/forbidden。
- Query cache：档案、今日计划、目录和统计的短期副本。
- 页面本地状态：回答草稿、答案是否显示、要点核对和提交锁。
- 服务端真相：Owner、enrollment、计划、会话、ReviewAttempt 和 FSRS。

评分仍携带稳定 `client_attempt_id`。超时重试必须复用原 ID 和 payload，服务端成功后才进入下一张。

### 7.3 Android 平台适配

- 使用 Android 安全存储，不把 Token 放进 localStorage、URL 或日志。
- 系统返回手势先关闭抽屉/对话框，再返回上一任务；学习会话离开前确认中断。
- 状态栏、导航栏和软键盘不遮挡固定操作区。
- 不申请通讯录、位置、相机、麦克风、存储等与学习无关权限。
- 网络切换和 WebView 恢复后重新校验 Session，不重复提交评分。
- OPPO/ColorOS 重点验收边到边布局、返回手势、中文输入、安装来源提示和后台恢复；
  Xiaomi/HyperOS 保留为后续兼容性验证，不阻塞首个私有发布。

## 8. 视觉与交互

延续当前安静、工作型学习界面，不做营销首页。今日任务是启动后的主体验；触控目标至少适合
单手操作，文字不只靠颜色表达状态。来源长文本允许换行和复制，评分区保持固定尺寸，软键盘
弹出后书写区和提交按钮不能互相遮挡。

## 9. 实施顺序与门禁

### A1 文档和工程基线

- 落盘本设计、PRD/系统设计增量和 P10 计划。
- 建立 `mobile/`、依赖锁、lint/typecheck/test/build。
- 验收：浏览器显示真实应用壳，不是营销页；质量命令可重复执行。

### A2 移动设备认证

- migration、激活领域服务、CLI、API、安全存储和恢复登录。
- 验收：正常、过期、撤销、重放、并发双击、无 Owner 和日志脱敏全部测试通过。

### A3 最小学习闭环

- 激活 -> 今日 -> 开始会话 -> 回忆 -> 答案/要点 -> 评分 -> 下一张 -> 完成。
- 验收：真实 API、Session 刷新、断网恢复和评分幂等通过。

### A4 功能迁移

- 档案、学科/章节、加入学习、卡片详情/来源、进度、薄弱点、周测和设备管理。
- 验收：对应小程序 11 个页面的核心能力均有移动端落点和状态矩阵。

### A5 Android 构建与私有分发

- 生成/提交 Android 工程，建立 release signing 配置模板和 APK 校验脚本。
- 私钥、keystore、密码、APK 和临时下载签名不进入 Git。
- 验收：release APK 可安装、签名可验证、SHA-256 可复算、升级保留数据。

### A6 OPPO 真机验收

- OPPO Find X7 Pro 完成激活、10/30 分钟计划、章节加入、完整复习、来源、进度、退出重进、
  断网/恢复和版本升级。
- 验收证据包括 APP 版本、设备/系统版本、服务端 request_id、数据库计数和脱敏结果记录。

## 10. 发布与恢复

APK 通过私有 HTTPS 或阿里云 OSS 短期签名地址交付，同时提供文件名、versionCode、SHA-256
和签名证书指纹。更新使用相同 applicationId 和签名密钥覆盖安装。签名 keystore 至少保留一份
离线加密备份；丢失后无法对现有安装做可信升级。

学习数据继续由 PostgreSQL 每日备份。卸载 APP 会删除本地 Session，但不会删除服务端学习记录；
重新安装需要新激活码。账户删除仍是显式危险操作。

## 11. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 自动转换 WXML 造成行为偏差 | 按 API 契约重写页面，先做纵向学习闭环 |
| 激活码泄露 | 高熵、短期、单次、只存哈希、可撤销、通用错误 |
| WebView Token 泄露 | Android 安全存储、CSP、无第三方脚本、日志脱敏 |
| OPPO 安装拦截 | 签名 APK、校验值、受控下载、真机记录安装步骤 |
| HyperOS 行为差异 | 后续取得 Xiaomi 设备时补做兼容性验收，不把 OPPO 结果外推为全厂商结论 |
| Android 16 布局/返回变化 | 真实设备检查边到边、手势、软键盘和生命周期 |
| 两个客户端逻辑漂移 | 服务端作为领域真相，共享 API 契约和端到端验收 |
| 私有分发更新困难 | 固定包名/签名、版本清单和可重复 release 命令 |

## 12. 范围外与后续决策

- 第一版不进入应用商店，不建设支付、公开注册或多用户。
- 第一版不承诺后台通知、完整离线卡库或应用内差分更新。
- 是否停用小程序由 Android 连续使用数据决定，不在迁移前删除。
- 中国大陆 APP 备案和应用市场规则在决定公开分发前单独核验；私有测试不被描述为公开合规结论。
