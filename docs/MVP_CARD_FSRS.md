# MVP 实施冻结（卡片 + FSRS）

> 状态：Prototype baseline。本文记录已经跑通的 15 张样例卡 MVP，不再定义目标产品范围。当前基线见 `docs/superpowers/README.md`。
>
> 样本验收已通过。本文冻结的是原型范围；原 `PRODUCT_PLAN.md` / `IMPLEMENTATION_PLAN.md` 中的向量检索主路径降为后续可选项。

## 1. 目标闭环

```text
本地审核通过的卡片 JSON
  -> FastAPI 导入
  -> 小程序今日到期列表
  -> 主动回忆 + 四档评分
  -> FSRS 更新下次 due
```

## 2. 范围

### 做

- 单用户鉴权（Bearer Token）
- 书籍列表、卡片列表
- 今日待复习 / 提交评分
- 本地/ECS 导入 approved 卡片
- 微信小程序 4 页：今日、复习、书库、我的
- Docker Compose：api + postgres

### 不做（MVP）

- 向量检索 / RAG 问答
- 小程序内 PDF 阅读
- 小程序内调用 MinerU/Qwen
- 多用户权限体系
- 社交、支付、课程

## 3. 技术选型

| 层 | 选型 |
|---|---|
| 小程序 | 微信原生（见 AGENT.md） |
| 后端 | FastAPI |
| 数据库 | PostgreSQL |
| 复习算法 | FSRS（`algorithm_version` 字段可升级） |
| 部署 | Docker Compose + Nginx HTTPS（ECS） |

## 4. 已确认环境前提

- 微信小程序 AppID：已有
- ECS：已有
- 域名：已备案
- 后端：FastAPI

## 5. 验收标准

1. 可导入 ≥ 本仓库 seed 样例卡
2. 开发者工具完成「看题 → 翻答案 → 评分」
3. 再次请求 `/review/due` 时 due 状态变化
4. 密钥不在小程序包内、不进 git
5. 卡片含 book/section/source_excerpt

## 6. 本地启动（开发）

见仓库根目录 `README.md`。

## 7. 当前实现与验证

- 后端已实现书籍/卡片查询、approved 导入、到期队列、四档评分和统计接口。
- `server/app/fsrs_simple.py` 是带 `algorithm_version` 的轻量 FSRS-like MVP 调度器，保证评分结果可追踪、可升级；正式上线前应替换为经过评测的标准 FSRS 参数实现。
- 本地冒烟已验证：未授权请求返回 401；seed 导入为 15 张 approved、跳过 3 张 needs_review；评分后 due 数量变化；重复导入不重复创建复习状态。
