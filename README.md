# Personal Deployed Engineer

**Don't count AI usage. Diagnose the workflow.**
**把 AI 当工作搭子，而不是只统计使用次数。**

`personal-ai-fde` 是一个开源 Agent Skill（兼容 WorkBuddy / Claude Code / CodeBuddy 通用的 `SKILL.md` 规范）：**只读扫描你本机的 AI 会话日志，把半年的 AI 协作还原成一张看得懂的工作流全景图**——AI 已经在做哪一步、你还在亲自补哪一步、哪里在反复返工——并当场为每个可优化环节生成一份可以马上试跑的 SOP。

![回顾总览](skills/personal-ai-fde/docs/screenshots/01-review-dashboard.png)

## 它回答三个问题

**1. 我的工作里，哪些可以交给 AI？**
按「业务成果」而不是文件格式聚类，还原每条工作流的完整步骤，逐步骤标注：AI 执行 / 人机协作 / 人工判断。对外占比、Skill 覆盖率、纠错率一目了然。

**2. 为什么现在的人机协作总是不顺？**
纠错候选、判断介入、返工环节全部计数，每条结论都挂证据编号，可以点回当时会话的原话。归因分四面：模型执行问题、流程输入问题、环境阻塞、正常共创——不把锅全甩给你的提示词。

**3. 下一步具体怎么改？**
每个可优化环节当场落成一条可试跑的 SOP：触发条件、输入清单、步骤分工、人工关口、异常路径、验收标准、回退方式、可复制的启动指令，全带。输出草案 ≠ 已部署，试跑验收才算数。

## 它不是什么

- **不是使用量统计**：不打总分、不排工具榜，评价对象是你的工作系统，不是你的提示词水平。
- **不是监控工具**：只读本机会话日志，零联网、零第三方依赖（纯 Python 标准库），写入仅限你显式指定的目录；个人事务默认隐藏、引文自动脱敏，还有 `--share-safe` 对外分享模式。

## 🚀 一键安装（复制这段话给任何 AI Agent 即可）

> 请帮我安装这个 Agent Skill：仓库地址 https://github.com/Martinciao/Personal-Deployed-Engineer- ，安装 `skills/personal-ai-fde` 这个 skill——把该目录下的 SKILL.md、references/、scripts/、tests/ 完整下载，放入技能目录（WorkBuddy 用户级为 ~/.workbuddy/skills/personal-ai-fde/；Claude Code 为 ~/.claude/skills/personal-ai-fde/；CodeBuddy 为 ~/.codebuddy/skills/personal-ai-fde/），然后读取 SKILL.md 确认安装成功，并告诉我怎么触发它。

也可以直接下载 [最新 Release 安装包](https://github.com/Martinciao/Personal-Deployed-Engineer-/releases/latest)（`personal-ai-fde-vX.Y.Z.skill`，解压即用）。

## Skills 清单

| Skill | 版本 | 状态 | 说明 |
|---|---|---|---|
| [personal-ai-fde](skills/personal-ai-fde/) | v1.0.0 | 稳定 | 个人 FDE 工作流诊断：工作流还原、人机分工、SOP 当场生成 |

## 📸 更多截图

| 工作全景（四层分层脑图） | SOP 手册 |
|---|---|
| ![工作全景](skills/personal-ai-fde/docs/screenshots/02-workflow-landscape.png) | ![SOP 手册](skills/personal-ai-fde/docs/screenshots/05-sop-manual.png) |

## 目录结构

```
Personal-Deployed-Engineer-/
├── README.md                 # 本文件：库索引 + 版本管理约定
├── LICENSE
└── skills/
    └── personal-ai-fde/      # 每个 skill 一个目录
        ├── SKILL.md          # 入口（name / description frontmatter）
        ├── README.md         # 快速开始、架构、安全说明
        ├── CHANGELOG.md      # 版本迭代记录
        ├── references/       # 方法论 / 规范 / 模板（按需加载）
        ├── scripts/          # 可执行脚本（纯标准库）
        ├── tests/            # 回归测试
        └── docs/screenshots/ # 脱敏 Demo 截图
```

## 版本管理约定

- **main 分支**：始终为最新稳定版；迭代直接走 commit，重大改动走分支 + PR。
- **CHANGELOG.md**：每个 skill 目录内维护，人工可读的版本演进记录（新增 / 修复 / 破坏性变更）。
- **版本发布**：打 annotated tag（如 `personal-ai-fde-v1.0.0`）+ GitHub Release，`.skill` 安装包挂为 Release 资产。
- **提交规范**：`feat(<skill>): ...` / `fix(<skill>): ...` / `docs(<skill>): ...` / `test(<skill>): ...`，一个功能点一个 commit，保证 `git log` 可读。
- **版本号**：语义化（major.minor.patch）。改 SKILL.md 行为约定 = major 或 minor；修 bug / 补文档 = patch。

## License

MIT © 2026 Martin Zhe，见 [LICENSE](LICENSE)。
