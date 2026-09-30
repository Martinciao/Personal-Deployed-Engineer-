# Personal FDE v1.0.0 · 数据框架与采集规范（data-spec）

> 配套：`scripts/parse_sessions.py`（采集）→ `scripts/worklens.py`（聚合/对比）→ `analysis.json`（判断）→ `scripts/build_review.py`（渲染，HTML 结构已定稿不再改动）。
> 本文档是数据契约：每个字段的含义、来源、谁消费、对应 HTML 哪一节、以及采集时的质量与 token 策略。改数据或改采集逻辑前先改这里。

## 0. 数据流总览

```
WorkBuddy 会话日志(~/.workbuddy/projects/*/*.jsonl, 只读)
  │  parse_sessions.py scan   ← 8s 全量 / <1s 缓存增量
  ▼
scan.json (schema 3.1, 采集层: 全量证据+指标+覆盖, run_id 唯一)
  │  模型读 digest + session --focus 深挖若干代表会话 → 写 analysis.json
  ▼
analysis.json (schema 3.1, 判断层: 工作流/分工/SOP, 绑定 scan_run_id)
  │  build_review.py --scan --analysis
  ▼
review.html (6 节, 结构定稿)   +  快照 scan-*.json → 周度 changes 对比
```

三条铁律：①数字一律脚本计算，模型不手填；②analysis 引用必须能在 scan.evidence 找到（渲染器强制校验）；③可比才环比，口径不同只作参考。

## 1. scan.json 字段表（采集层，机器生成）

| 字段 | 含义 | 来源/算法 | 消费者（HTML 节） |
|---|---|---|---|
| `schema`/`version`/`metric_version` | 契约版本；`metric_version` 变化则历史不可直接环比 | 常量 | changes 护栏 |
| `run_id` | 本次扫描唯一 ID（YYYYMMDD-HHMMSS） | 运行时 | analysis 绑定；渲染校验 |
| `scope{workspace,from,to,days,excluded,source}` | 口径：范围/起止/排除的当前会话/数据源声明 | CLI 参数 | 01 回顾 lead 行；可比性判断 |
| `coverage{discovered_files,read_files,in_scope_sessions,excluded_current,skipped_files[],invalid_lines,roots,warnings}` | 覆盖诚实性：发现/读取/跳过及原因；warnings 含展示层安全拦截原文改写次数、share-safe 声明 | 扫描过程计数 | 报告口径脚注 |
| `metrics` | 全局指标（见 1.1） | 逐事件聚合 | 01 回顾、02 习惯画像、changes |
| `families[]` | 板块启发分类（见 1.2） | 标题+首轮+技能名加权打分 | 02 思维导图、SOP 频率 |
| `evidence[]` | 统一证据池（见 1.3） | 强纠错轮+判断候选轮 | 03-06 流程图证据 chip |
| `sessions[]` | 全量会话清单（见 1.4） | 每会话一条 | 底稿/回溯；01 趣事实 |
| `clusters[]` | 重复任务簇（标题片段×会话数） | 标题 n-gram 去重 | 底稿；Skill 化候选 |
| `assets{sops[],automations[],skills_count,user_memory_chars}` | 已有资产线索（只列名称，未读取内容） | 文件名/日志计数 | 02/底稿 |
| `previous`/`history[]`/`changes` | 上次同口径快照/历次列表/增量（见第 5 节） | 快照目录对比 | 周度进步判定 |

### 1.1 metrics 关键字段（01 回顾与习惯画像的数据源）

| 字段 | 含义 | HTML 消费点 |
|---|---|---|
| `work_sessions` | 排除定时/个人后的工作会话数 | 01 大数字"交给工作搭子的任务" |
| `workspaces` | 覆盖工作区数 | 01 同卡脚注 |
| `user_turns` | 用户轮次总数 | 01"人机对话轮次" |
| `ai_hours`/`human_hours` | AI 活动时长/人侧间隔（**非工时**） | 01 脚注；禁止用于效率收益 |
| `automation_sessions` | 定时任务运行次数 | 01"定时任务自动跑" |
| `ai_actions` 汇总（生成产出/检索调研） | 各 family.ai_actions 求和 | 01"AI 生成产出 N 次" |
| `first_goal`/`first_context`/`first_constraint` % | 首条指令含目标/上下文/约束 | 02 习惯画像前三卡 |
| `judgment_turns` | 判断候选轮数（evidence 里 judgment=true 计数） | 02 习惯画像/01 趣事实 |
| `sessions_compacted` | 发生过上下文压缩的会话数 | 01/02 |
| `correction_rate` | 强纠错候选率（**需语义复核**） | 底稿/板块卡；不作奖惩 |

### 1.2 families[] 字段（思维导图的数据源）

`family, sessions, turns, correction_rate, skill_share(用 Skill 会话占比), external_share(对外信号占比), judgment_turns, phases{环节→轮次/时长}, ai_actions, skills{名→次数}, paths, correction_examples, judgment_examples, deep_dive[会话id], prev`。
渲染实际使用：`family / sessions / correction_rate / skill_share / external_share`（思维导图节点）；`skills`（01 最常用入口=全局 sum）；`deep_dive`（人工深挖入口）。层级归属由渲染器按规则现算：`external≥60%→判断密集；skill<45%→可深度自动化；纠错≥8%→协作加深；其余→稳步推进`。

### 1.3 evidence[] 字段（判断层的锚点）

`ref(会话8位#轮次) / session_id / date / family / phase(环节) / quote(清洗脱敏后的用户原话,≤200字) / judgment / correction_categories`。
质量规则：来自 `<user_query>` 提取（先剥系统块）；粘贴材料拆出； teammate/通知/压缩摘要剔除；邮箱/手机号/证件/长串密钥/链接参数已脱敏；个人事务默认不进 evidence（`--include-personal` 才放）。

### 1.4 sessions[] 字段（底稿）

`id(8位) / date / workspace / family / kind / title(个人事务隐藏) / turns / corrections / human_min / ai_min / first_pass(≠验收) / skills / exts / path(环节串)`。

## 2. analysis.json 字段表（判断层，模型产出）

| 字段 | 含义 | 渲染消费点 |
|---|---|---|
| `schema`/`scan_run_id` | 契约+溯源（不匹配即拒渲） | 渲染校验 |
| `executive_summary{headline,conclusion,first_action,not_recommended[]}` | 总结论（模型判断） | 报告叙事基线（建议页 lead 与之保持一致） |
| `history_review{...}` | 历史口径声明 | 周度汇报措辞 |
| `findings[]{observation,inference,evidence_refs,confidence,alternative_explanation}` | 证据化发现 | 03-06 流程图"为什么改" |
| `workflows[]{current_steps[step/actor/observed/friction/evidence_refs], optimized_steps[step/owner/action/output/gate/basis/opportunity_ids], boundary_reason, root_cause, unknowns}` | 工作流现状与优化 | 03-06 上下两条流程图 |
| `opportunities[]{id,workflow_id,stage,priority,first_action,acceptance[],sop_id}` | 优化项 | 流程图验收 ✓、"本周就做" |
| `boundary_rules[]{mode,conditions,examples,escalate_when}` | 人机边界 | 建议4"边界速查"；02 层级定义参照 |
| `sops[]{id,title,copy_prompt,steps[],human_gates,exception_rules,acceptance,trial,...}` | SOP 本体 | 启动指令框（pre） |
| `coverage_review{reviewed_evidence_refs,excluded,limitations}` | 覆盖声明 | 口径诚实性 |

### 2.1 渲染器常量（随脚本维护，属于"展示层数据"）

`ADVICE(页→flows/标题/lead)`、`SOP_FAMILY(SOP→主战场板块,用于频率)`、`SOP_PAGE(SOP→建议页锚点)`、`SOP_LOGIC(每条一句话教习惯)`、`TIERS(四层定义)`、`ACT(蓝/青/橙)`。这些不是扫描数据，是产品文案与映射，改文案改这里。

## 3. HTML 模块 ↔ 字段映射矩阵

| HTML 节 | 组件 | 所需字段（来源） |
|---|---|---|
| 01 回顾 | statgrid 四卡 | metrics.work_sessions/workspaces/user_turns/ai_hours/automation_sessions + Σfamilies.ai_actions |
| 01 回顾 | 份额条 | families.family/sessions（排序取7） |
| 01 回顾 | 趣事实 | Σjudgments、len(corrections)、sessions_compacted、Counter(sessions.date).max、max(sessions.turns+title)、Σskills.max |
| 02 全景 | 习惯画像 5 卡 | metrics.first_goal/first_context/first_constraint/judgment 计数/sessions_compacted |
| 02 全景 | 思维导图 | families（名称/会话/三指标）+ 层级规则 + fam_sops（SOP_FAMILY 反查，按 sop_rank 排序） |
| 02 全景 | SOP 频率榜 | sop_freq（SOP_FAMILY→板块 sessions）+ sop_rank + sops.title |
| 03-06 建议 | 流程图-现在 | workflows.current_steps（step/friction/observed/evidence_refs→evidence.quote） |
| 03-06 建议 | 流程图-优化 | workflows.optimized_steps（step/owner/output） |
| 03-06 建议 | ✓ 验收 | opportunities.acceptance（经 optimized_steps.opportunity_ids 反查） |
| 03-06 建议 | 本周就做 | opportunities.first_action（priority=先做） |
| 03-06 建议 | 启动指令+背后的逻辑 | sops.copy_prompt + SOP_LOGIC 常量 |
| 建议 4 | 边界速查/试运行 | boundary_rules + 固定文案 |

## 4. WorkBuddy 采集指南（fetch 怎么跑、token 怎么省）

**启动即全量采集（快）：**
```bash
PY=~/.workbuddy/binaries/python/versions/3.13.12/bin/python3
$PY scripts/parse_sessions.py scan --days 7 --exclude-current --cwd <工作区> \
    --out-dir <工作区>/outputs --history-dir <工作区>/.workbuddy/fde-history
```
全量 382 会话约 8s（401MB 日志逐事件解析），之后 sessions-cache（~/.workbuddy/ai-fde/）按 mtime 增量，重扫 <1s。

**Token 平衡点（三层漏斗）：**
1. 脚本算尽一切数字 → 模型只读 digest（≤8KB）+ 结构化的 scan.json，绝不读原始日志全文。
2. 深挖只看焦点：`session <id> --focus`（前 3 轮+纠错前后，~20KB/会话）；每板块挑 1 正常+1 摩擦；>150 会话可用子代理并行，每个只回结构化观察。
3. 引文即证据：evidence.quote 已截断 200 字并脱敏，判断引用 ref 而非贴全文；analysis 不复述大段原文。

**质量规则：** 真实用户话只认 `<user_query>`；`automation_system_reminder` 先剥离（内文含 user_query 字样会误截）；teammate/task-notification/压缩摘要不算用户输入；时间窗按逐事件时间戳过滤（不按会话结束时间）；拒绝/失败分开计；含 error 字样的正常文档不算失败。**两层脱敏（v1.0.0）：** 数据层（scan.json/缓存）`redact()` 只做 PII（邮箱/手机/证件/银行卡/URL参数/≥20位随机串），保留安全拦截原文供审计；展示层（stdout/scan-*.md/digest）`redact_out()` 额外把拦截原文改写为"系统拦截"防宿主误判，改写次数写进 coverage.warnings。

**分类器标定（goldset）：** `parse_sessions.py goldset <标注.tsv>`（每行「会话ID<TAB>板块名」，# 为注释），输出一致率+混淆矩阵；≥30 样本才有参考价值，一致率低先复核分歧样本，再决定改正则或加 taxonomy override。

**缓存与分享：** 缓存条目带 `cached_at`，TTL 90 天自动过期重解析，`purge --yes` 手动清空（只动 `~/.workbuddy/ai-fde`，不碰原始日志）；`scan --share-safe` 置空 evidence.quote、sessions[].title、family examples 与 clusters examples，供对外分享，scope.share_safe=true 标记。

**权限边界：** 只读 `~/.workbuddy/projects/*/*.jsonl` 主会话；不碰其他工作区业务文件/记忆/凭证/设置/自动化库；写入仅限 `--out-dir`/`--history-dir`。

## 5. 周度 recurring 与进步追踪（changes 层）

**快照机制：** 每次 scan 在 history-dir 存 `scan-<run_id>.json` 精简快照（metrics 子集+板块子集+metric_version）。**可比性护栏**（build_changes）：同 `scope_key`（范围+天数）+ v3 快照 + 间隔≥20h + metric_version 一致 → `comparable=true` 才输出 deltas；同日重跑=同数据复跑，不判定进步；v2 旧历史仅参考。

**changes 输出：** `status / prev_date / comparable / deltas{9 项指标增量} / family_deltas[]{板块会话数与纠错率增量} / notes`。周运行 SOP：
```bash
$PY scripts/parse_sessions.py scan --days 7 ...   # 同口径窗口
# digest 自动打印"## C. 与上次对比"；汇报时引用 changes 块
```
进步判定建议看：`correction_rate`（↓好）、`first_constraint`（↑好）、`judgment_turns` 结构、family_deltas 里重点板块；**SOP 试跑结果（人工记录：补信息次数/返工/验收）不入 scan，由使用者在周报里口述**，两者结合才算真实进步。HTML 结构定稿，周度变化不进 HTML，进对话汇报+快照序列；要可视化趋势时另开小工具读 history[]，勿改主 HTML。

## 6. 落地检查清单

- [ ] run_id 绑定：analysis.scan_run_id == scan.run_id（渲染器强制）
- [ ] evidence_refs 全部存在于 scan.evidence（渲染器强制）
- [ ] 每个 opportunity 有 sop_id 且 SOP 字段齐全（渲染器强制）
- [ ] 输出目录与历史目录显式指定，未写其他工作区
- [ ] 个人事务默认隐藏；引文已脱敏；对外分享用 --share-safe 且 scope.share_safe=true
- [ ] 展示层拦截原文改写次数已记入 coverage.warnings（>0 时）
- [ ] 周度：scope_key 与上次一致；comparable=false 时在汇报里说明原因
