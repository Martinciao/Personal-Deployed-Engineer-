# Personal Deployed Engineer

Martin 的 Agent Skills 库，遵循 [WorkBuddy](https://www.workbuddy.cn) / Claude Code / CodeBuddy 通用的 `SKILL.md` 规范。每个 skill 独立目录、自带 CHANGELOG，按标准 skills 仓库形式组织。

## 🚀 一键安装（复制这段话给任何 AI Agent 即可）

> 请帮我安装这个 Agent Skill：仓库地址 https://github.com/Martinciao/Personal-Deployed-Engineer- ，安装 `skills/personal-ai-fde` 这个 skill——把该目录下的 SKILL.md、references/、scripts/、tests/ 完整下载，放入技能目录（WorkBuddy 用户级为 ~/.workbuddy/skills/personal-ai-fde/；Claude Code 为 ~/.claude/skills/personal-ai-fde/；CodeBuddy 为 ~/.codebuddy/skills/personal-ai-fde/），然后读取 SKILL.md 确认安装成功，并告诉我怎么触发它。

## Skills

| Skill | 版本 | 状态 | 说明 |
|---|---|---|---|
| [personal-ai-fde](skills/personal-ai-fde/) | v1.0.0 | 稳定 | 个人 FDE 工作流诊断：只读扫描 AI 会话日志，还原工作流、区分人机分工、当场生成可试跑 SOP |

## 目录结构

```
Personal-Deployed-Engineer-/
├── README.md                 # 本文件：库索引 + 版本管理约定
├── LICENSE
└── skills/
    └── <skill-name>/         # 每个 skill 一个目录
        ├── SKILL.md          # 入口（name / description frontmatter）
        ├── README.md         # 快速开始、架构、安全说明
        ├── CHANGELOG.md      # 版本迭代记录
        ├── references/       # 方法论 / 规范 / 模板（按需加载）
        ├── scripts/          # 可执行脚本
        └── tests/            # 回归测试
```

## 版本管理约定

- **main 分支**：始终为最新稳定版；迭代直接走 commit，重大改动走分支 + PR。
- **CHANGELOG.md**：每个 skill 目录内维护，人工可读的版本演进记录（新增 / 修复 / 破坏性变更）。
- **版本快照**：每个发布版本打 `release/<skill-name>-v<版本号>` 分支（如 `release/personal-ai-fde-v1.0.0`），在 GitHub 分支列表可随时回看任一历史版本全貌。
- **提交规范**：`feat(<skill>): ...` / `fix(<skill>): ...` / `docs(<skill>): ...` / `test(<skill>): ...`，一个功能点一个 commit，保证 `git log` 可读。
- **版本号**：语义化（major.minor.patch）。改 SKILL.md 行为约定 = major 或 minor；修 bug / 补文档 = patch。

## 手动安装某个 skill

```bash
git clone https://github.com/Martinciao/Personal-Deployed-Engineer-.git

# 用户级
cp -r Personal-Deployed-Engineer-/skills/personal-ai-fde ~/.workbuddy/skills/personal-ai-fde
# 或项目级
cp -r Personal-Deployed-Engineer-/skills/personal-ai-fde <workspace>/.workbuddy/skills/personal-ai-fde
```

## License

MIT © 2026 Martin Zhe，见 [LICENSE](LICENSE)。
