# Changelog · personal-ai-fde

所有可感知的变更记录在此文件。格式参照 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循语义化。

## [1.0.0] - 2026-09-30

首个开源发布版（方法论沿袭内部 v3 迭代）。

### 新增
- 会话扫描器 `parse_sessions.py`：只读扫描 WorkBuddy / CodeBuddy / Claude Code 主会话日志；mtime 增量缓存（90 天 TTL）、两层脱敏（数据层 PII 留原文供审计 / 展示层改写安全拦截原文防宿主误判）、`--share-safe` 对外分享模式、`goldset` 分类器一致率标定、`purge` 缓存清理。
- 工作拆解层 `worklens.py`：工作类型启发分类（可 `--taxonomy` 覆盖）、九类工作环节拆解、人机分工信号、重复任务簇、周度快照与同口径对比护栏（同 scope_key + ≥20h 间隔 + metric_version 一致才可比）。
- 报告渲染器 `build_report.py`：五页分析报告（结论与行动 / 真实工作流 / 人机分工 / SOP 手册 / 证据与历史）+ 完整采集记录 HTML；渲染前强制校验 run_id 绑定、evidence_refs 存在、每个优化项有完整 SOP。
- 腾讯风格回顾报告 `build_review.py`：六节思维导图版（Wrapped 大数字 / 工作全景四层级 / 建议 1-4 流程图 + 启动指令）。
- 方法论 references 七篇：诊断准则（rubric）、反模式清单（antipatterns）、人机边界（boundary）、SOP 最低标准（sop-template）、报告契约（report-spec）、数据框架与采集规范（data-spec）、方法背景（fde-methodology）。
- 回归测试 20 例：脱敏、HTML 转义、渲染校验、可比性护栏、纠错误判。

### 安全
- 纯标准库、零依赖、零网络请求；只读日志、写入仅限显式输出目录；个人事务默认隐藏；引文与标题自动脱敏。

### 说明
- 内部迭代沿革：v1（诊断版）→ v2（增加工作流还原）→ v3（八项检查 + 不打总分 + SOP 当场生成）；对外发布版本号从 v1.0.0 重新起算。
- Demo 截图为二进制资产，随发布包分发，不入 git 库。

[1.0.0]: https://github.com/Martinciao/workbuddy-skills/releases/tag/personal-ai-fde-v1.0.0
