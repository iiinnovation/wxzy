# P10 Android 自动化测试报告

日期：2026-07-27
应用：温习 `0.1.0`（versionCode 1）
applicationId：`xin.luoandlt.wxzy`

## 结论

当前已具备可安装的内部 debug APK，但尚不满足最终用户 release 分发门禁。自动化已覆盖 Web、真实
FastAPI E2E、Android 编译、lint、debug 签名和包内容检查；OPPO Find X7 Ultra 已通过安装和安全存储
及基础 UI 冒烟测试；按本轮范围不在 OPPO 上激活，仍缺少 Xiaomi 17 Pro 完整闭环、release 签名和
覆盖升级验证。

## 已通过

| 层级 | 用例 | 结果 |
|---|---|---|
| Web 静态 | ESLint、TypeScript、Vite production build | 通过 |
| Web 单元/组件 | 激活、Session 轮换/前台复验、目录/章节、进度、档案、设备、学习会话和断网原 payload 重试 | 22 passed |
| 移动页面 E2E | 四 Tab、目录/来源、进度/薄弱点/周测、档案/设备，390x844 无横向溢出 | 1 passed |
| 真实 API E2E | 激活 -> 目录/章节/来源 -> 进度/档案/设备 -> 10 分钟 -> 暂停/恢复 -> 评分断网幂等 -> 完成 | 1 passed |
| E2E 数据 | 激活码消费、ReviewAttempt 幂等、会话游标 | used=1，attempt=1，completed/1/1 |
| Android | Gradle test、lintDebug、assembleDebug、assembleDebugAndroidTest | BUILD SUCCESSFUL，269 tasks |
| Android 真机 | OPPO Find X7 Ultra（PHY110），Android 16 / API 36，ColorOS V16.1.0 | 安装、Keystore instrumentation、系统栏、中文键盘缩放和返回手势通过 |
| APK 契约 | 包名、版本、SDK、权限、应用名 | 通过 |
| APK 签名 | APK Signature Scheme v2 debug 签名 | 通过 |
| 安全扫描 | APK 不含测试 Token、激活码、微信密钥或私钥标记 | 无命中 |
| 生产连通 | `https://api.luoandlt.xin/health` | 200 / ok |

## 最终复验

Vitest 已显式排除 `e2e/**`；复验结果为 ESLint、TypeScript、10 个 Vitest 文件共 22 个用例和
显式生产 API Base 的 Vite build 通过。移动页面 Playwright 覆盖四 Tab 与全部任务页并保留学科、
进度、档案截图；隔离 SQLite + Alembic head + 实际 FastAPI E2E 同时验证目录来源与学习闭环。
重新执行 Capacitor sync 与 Gradle `test lintDebug assembleDebug assembleDebugAndroidTest`，269 个任务成功。
OPPO 真机发现并修复了深色系统模式下浅色页面状态栏图标对比度不足，以及缺少生产 API Base 时
APK 可构建但启动白屏的问题；Vite 现会在构建期直接拒绝缺少 `VITE_API_BASE_URL` 的生产构建。

E2E 种子工具通过 Ruff format/check 与 Mypy；43 份仓库文档链接检查和 `git diff --check` 通过。
Git 忽略规则已验证覆盖 APK、Android/Gradle 构建目录、Capacitor 复制资源、`*.jks`、`*.keystore`
和 `keystore.properties`。

## Debug APK

- 文件：`mobile/artifacts/wenxi-0.1.0-debug.apk`
- 类型：Android debug 签名，仅供内部安装测试
- 大小：约 4.0 MiB
- SHA-256：`b92d8bb2065822b7495269eb98008edec265bdb818f17811ca4002dae831dd7d`
- 证书：`C=US, O=Android, CN=Android Debug`
- 证书 SHA-256：`e920652a81bd4cf85f0fee90361266508db9caed90e913e57449be050825309e`

## 尚未通过

1. Xiaomi 17 Pro 使用真实激活码完成首次激活、重启恢复和最小学习闭环。
2. Xiaomi/HyperOS 状态栏、边到边布局、返回手势、中文软键盘、长答案/长来源和断网恢复。
3. 30 分钟真实 API 会话、Session 撤销和同签名覆盖升级流程。
4. 用户自主管理的 release keystore、release APK 签名和 `apksigner verify`。

OPPO 基础冒烟结束后已卸载主应用与测试组件，并清除手机端临时截图；未签发或消费真实激活码。

因此 debug APK 可以交给受控测试用户试装，不能标记为最终发布版本。
