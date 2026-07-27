# P10 Android 自动化测试报告

日期：2026-07-27
应用：温习 `0.1.0`（versionCode 1）
applicationId：`xin.luoandlt.wxzy`

## 结论

当前已具备可安装的内部 debug APK，但尚不满足最终用户 release 分发门禁。自动化已覆盖 Web、真实
FastAPI E2E、Android 编译、lint、debug 签名和包内容检查；缺少 OPPO Find X7 Pro 真机安装、安全存储、
返回手势、软键盘、release 签名和覆盖升级验证。

## 已通过

| 层级 | 用例 | 结果 |
|---|---|---|
| Web 静态 | ESLint、TypeScript、Vite production build | 通过 |
| Web 单元/组件 | 激活、Session 轮换/前台复验、目录/章节、进度、档案、设备、学习会话和断网原 payload 重试 | 22 passed |
| 移动页面 E2E | 四 Tab、目录/来源、进度/薄弱点/周测、档案/设备，390x844 无横向溢出 | 1 passed |
| 真实 API E2E | 激活 -> 目录/章节/来源 -> 进度/档案/设备 -> 10 分钟 -> 暂停/恢复 -> 评分断网幂等 -> 完成 | 1 passed |
| E2E 数据 | 激活码消费、ReviewAttempt 幂等、会话游标 | used=1，attempt=1，completed/1/1 |
| Android | Gradle test、lintDebug、assembleDebug、assembleDebugAndroidTest | BUILD SUCCESSFUL，269 tasks |
| APK 契约 | 包名、版本、SDK、权限、应用名 | 通过 |
| APK 签名 | APK Signature Scheme v2 debug 签名 | 通过 |
| 安全扫描 | APK 不含测试 Token、激活码、微信密钥或私钥标记 | 无命中 |
| 生产连通 | `https://api.luoandlt.xin/health` | 200 / ok |

## 最终复验

Vitest 已显式排除 `e2e/**`；复验结果为 ESLint、TypeScript、10 个 Vitest 文件共 22 个用例和
显式生产 API Base 的 Vite build 通过。移动页面 Playwright 覆盖四 Tab 与全部任务页并保留学科、
进度、档案截图；隔离 SQLite + Alembic head + 实际 FastAPI E2E 同时验证目录来源与学习闭环。
重新执行 Capacitor sync 与 Gradle `test lintDebug assembleDebug assembleDebugAndroidTest`，269 个任务成功。

E2E 种子工具通过 Ruff format/check 与 Mypy；43 份仓库文档链接检查和 `git diff --check` 通过。
Git 忽略规则已验证覆盖 APK、Android/Gradle 构建目录、Capacitor 复制资源、`*.jks`、`*.keystore`
和 `keystore.properties`。

## Debug APK

- 文件：`mobile/artifacts/wenxi-0.1.0-debug.apk`
- 类型：Android debug 签名，仅供内部安装测试
- 大小：约 4.0 MiB
- SHA-256：`879d37c451551a4dec4c63481f16a0ac6297b3f3f957cbea1dfe94bc4800de3c`
- 证书：`C=US, O=Android, CN=Android Debug`
- 证书 SHA-256：`e920652a81bd4cf85f0fee90361266508db9caed90e913e57449be050825309e`

## 尚未通过

1. OPPO Find X7 Pro 安装、首次激活与 Android Keystore 实际持久化。
2. 实机 ColorOS/Android 状态栏、边到边布局、返回手势和中文软键盘；Xiaomi/HyperOS 后续补兼容验证。
3. 30 分钟真实 API 会话、长答案/长来源、断网恢复和 Session 撤销真机流程；instrumentation APK
   已构建但因当前无 ADB 设备尚未执行。
4. 用户自主管理的 release keystore、release APK 签名、`apksigner verify` 和覆盖升级。

因此 debug APK 可以交给受控测试用户试装，不能标记为最终发布版本。
