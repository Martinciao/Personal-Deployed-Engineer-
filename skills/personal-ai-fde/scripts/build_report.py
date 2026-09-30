#!/usr/bin/env python3
"""
personal-ai-fde v1.0.0 报告渲染器。

  # 分析报告（5 个导航页）+ SOP 草案 + 分析文档
  python3 build_report.py --scan scan.json --analysis analysis.json \
      --out report.html --sop-out sop-drafts.md --analysis-out analysis.md

  # 仅把完整扫描记录转成易读 HTML
  python3 build_report.py --scan scan.json --record-out record.html

规则：所有数据 html 转义后展示；引用必须能在 scan.evidence 找到；缺 SOP 即报错；
渲染器不联网、不执行日志内容、不伪造未验证收益。
"""
import argparse, html, json, os, sys, time

esc = lambda s: html.escape(str(s if s is not None else ""), quote=True)
ERRORS, WARN = [], []


def fail(msg):
    ERRORS.append(msg)


def warn(msg):
    WARN.append(msg)


# ---------------------------------------------------------------- 校验
def validate(scan, analysis):
    if scan.get("schema") != "3.1":
        warn(f"scan schema={scan.get('schema')}，按 3.1 渲染，缺失字段留空")
    if analysis.get("schema") != "3.1":
        fail("analysis schema 必须是 3.1")
    if analysis.get("scan_run_id") != scan.get("run_id"):
        fail(f"scan_run_id 不匹配：analysis={analysis.get('scan_run_id')} scan={scan.get('run_id')}")
    refs = {e.get("ref") for e in scan.get("evidence", [])}
    opp_ids = {o.get("id") for o in analysis.get("opportunities", [])}
    for w in analysis.get("workflows", []):
        for r in w.get("evidence_refs", []):
            if r not in refs:
                fail(f"{w.get('id')} 引用不存在：{r}")
        for st in w.get("current_steps", []) + w.get("optimized_steps", []):
            for r in st.get("evidence_refs", []):
                if r not in refs:
                    fail(f"{w.get('id')}/{st.get('step')} 引用不存在：{r}")
    for f in analysis.get("findings", []):
        for r in f.get("evidence_refs", []):
            if r not in refs:
                fail(f"{f.get('id')} 引用不存在：{r}")
    for o in analysis.get("opportunities", []):
        for r in o.get("evidence_refs", []):
            if r not in refs:
                fail(f"{o.get('id')} 引用不存在：{r}")
        if not o.get("sop_id"):
            fail(f"{o.get('id')} 缺 SOP")
        elif o["sop_id"] not in {s.get("id") for s in analysis.get("sops", [])}:
            fail(f"{o.get('id')} 的 {o['sop_id']} 不存在")
    for s in analysis.get("sops", []):
        if not s.get("steps"):
            fail(f"{s.get('id')} 缺步骤表")
        for key in ("trigger", "inputs", "human_gates", "exception_rules", "acceptance", "trial", "rollback", "copy_prompt"):
            if not s.get(key):
                fail(f"{s.get('id')} 缺 {key}")
        if not set(s.get("opportunity_ids", [])) & opp_ids:
            warn(f"{s.get('id')} 未对应任何优化项")


# ---------------------------------------------------------------- 通用片段
def ref_chip(r):
    return f'<button class="refchip" onclick="gotoRef(this)" data-ref="{esc(r)}">{esc(r)}</button>'


def refs_html(refs):
    return "".join(ref_chip(r) for r in (refs or [])) or '<span class="muted">—</span>'


def owner_badge(owner):
    m = {"AI": "b-ai", "人": "b-human", "协作": "b-both"}
    return f'<span class="badge {m.get(owner, "b-both")}">{esc(owner or "协作")}</span>'


def pri_badge(p):
    m = {"先做": "b-hot", "下一批": "b-next", "观察": "b-watch"}
    return f'<span class="badge {m.get(p, "b-watch")}">{esc(p or "观察")}</span>'


def page_head(title, sub=""):
    return f'<header class="phead"><h1>{esc(title)}</h1><div class="psub">{esc(sub)}</div></header>'


def sop_section(sop):
    rows = "".join(
        f'<tr><td class="c-ord">{s.get("order", i + 1)}</td><td>{owner_badge(s.get("owner"))}</td>'
        f'<td>{esc(s.get("action"))}</td><td>{esc(s.get("output"))}</td><td class="c-check">{esc(s.get("check"))}</td></tr>'
        for i, s in enumerate(sop.get("steps", [])))
    trial = sop.get("trial", {})
    return f'''
<article class="sop" id="{esc(sop.get("id"))}">
  <div class="sop-h"><span class="sop-id">{esc(sop.get("id"))}</span><h3>{esc(sop.get("title"))}</h3>
    <span class="badge b-draft">{esc(sop.get("status", "草案·未试运行"))}</span>
    <button class="cp" onclick="copyEl(this,'{esc(sop.get("id"))}-full')">复制全文</button></div>
  <div class="sop-grid">
    <div><span class="lbl">触发</span><p>{esc(sop.get("trigger"))}</p></div>
    <div><span class="lbl">输入</span><ul>{"".join(f"<li>{esc(x)}</li>" for x in sop.get("inputs", []))}</ul></div>
  </div>
  <table class="tbl"><thead><tr><th>#</th><th>执行者</th><th>动作</th><th>产出</th><th>检查点</th></tr></thead><tbody>{rows}</tbody></table>
  <div class="sop-grid3">
    <div><span class="lbl">人工确认点</span><ul>{"".join(f"<li>{esc(x)}</li>" for x in sop.get("human_gates", []))}</ul></div>
    <div><span class="lbl">异常处置</span><ul>{"".join(f"<li>{esc(x)}</li>" for x in sop.get("exception_rules", []))}</ul></div>
    <div><span class="lbl">验收与回退</span><ul>{"".join(f"<li>{esc(x)}</li>" for x in sop.get("acceptance", []))}</ul>
      <p class="sm muted">回退：{esc(sop.get("rollback"))}</p></div>
  </div>
  <div class="sop-grid3">
    <div><span class="lbl">试跑样本</span><p>{esc(trial.get("sample"))}</p></div>
    <div><span class="lbl">记录指标</span><ul>{"".join(f"<li>{esc(x)}</li>" for x in trial.get("metrics", []))}</ul></div>
    <div><span class="lbl">通过 / 停止</span><p>{esc(trial.get("pass_condition"))}</p><p>{esc(trial.get("stop_condition"))}</p></div>
  </div>
  <div class="promptbox"><span class="lbl">启动指令（填好材料即可粘贴）</span>
    <pre id="{esc(sop.get("id"))}-full">{esc(sop.get("copy_prompt"))}</pre>
    <button class="cp" onclick="copyPre(this)">复制</button></div>
</article>'''


# ---------------------------------------------------------------- 报告 5 页
def build_report(scan, ana):
    scope = scan.get("scope", {})
    scope_label = f'{scope.get("workspace", "")}｜{scope.get("from", "")} → {scope.get("to", "")}'
    es = ana.get("executive_summary", {})
    hist = ana.get("history_review", {})
    wfs = {w["id"]: w for w in ana.get("workflows", [])}

    # ---- P1 结论与行动
    finds = "".join(
        f'<div class="fcard"><div class="fhead"><span class="fid">{esc(f["id"])}</span><b>{esc(str(f.get("inference", ""))[:48])}</b>'
        f'<span class="conf">置信度 {esc(f.get("confidence", ""))}</span></div>'
        f'<p>{esc(f.get("observation"))}</p><p class="alt">另一种可能：{esc(f.get("alternative_explanation"))}</p>'
        f'<div class="refs">{refs_html(f.get("evidence_refs"))}</div></div>'
        for f in ana.get("findings", []))
    acts = sorted(ana.get("opportunities", []),
                  key=lambda o: ({"先做": 0, "下一批": 1, "观察": 2}.get(o.get("priority"), 3)))
    act_rows = "".join(
        f'<tr><td>{pri_badge(o.get("priority"))}</td><td><b>{esc(o.get("stage"))}</b>'
        f'<div class="sm muted">{esc(wfs.get(o.get("workflow_id"), {}).get("name", ""))}</div></td>'
        f'<td>{esc(o.get("change"))}</td><td>{owner_badge(o.get("owner"))}</td><td class="sm">{esc(o.get("first_action"))}</td>'
        f'<td><a class="jump" href="#{esc(o.get("sop_id"))}" onclick="showTabById(this.hash)">{esc(o.get("sop_id"))}</a></td></tr>'
        for o in acts)
    firsts = [o for o in acts if o.get("priority") == "先做"][:3]
    todo = "".join(
        f'<li><b>{esc(o.get("first_action"))}</b>　<span class="sm muted">验收：{esc("；".join(o.get("acceptance", [])[:2]))}</span></li>'
        for o in firsts)
    nr = "".join(f"<li>{esc(x)}</li>" for x in es.get("not_recommended", []))
    p1 = page_head("结论与行动", scope_label) + f'''
<div class="hero"><div class="hl-main"><span class="tag">核心结论</span>{esc(es.get("headline"))}</div>
<p class="concl">{esc(es.get("conclusion"))}</p>
<div class="firstbox"><b>看完先做这一件事</b><p>{esc(es.get("first_action"))}</p></div></div>
<div class="cols2"><div><h3>主要发现</h3>{finds}</div>
<div><h3>行动清单（按优先级）</h3><table class="tbl"><thead><tr><th>优先级</th><th>环节</th><th>改法</th><th>执行</th><th>下一步</th><th>SOP</th></tr></thead><tbody>{act_rows}</tbody></table>
<div class="notrec"><b>本次不建议直接做</b><ul>{nr}</ul></div></div></div>
<div class="todobox"><b>本周先跑这 {len(firsts)} 项</b><ol>{todo}</ol>
<div class="hardsm">硬规则：AI 产出未经人验收，不得外发。</div></div>'''

    # ---- P2 工作流
    wf_html = []
    for w in ana.get("workflows", []):
        cur = "".join(
            f'<tr><td><b>{esc(s.get("step"))}</b></td><td>{owner_badge(s.get("actor"))}</td><td>{esc(s.get("observed"))}</td>'
            f'<td>{esc(s.get("friction"))}</td><td>{refs_html(s.get("evidence_refs"))}</td></tr>'
            for s in w.get("current_steps", []))
        opt = "".join(
            f'<tr><td><b>{esc(s.get("step"))}</b></td><td>{owner_badge(s.get("owner"))}</td><td>{esc(s.get("action"))}</td>'
            f'<td>{esc(s.get("output"))}</td><td class="sm">{esc(s.get("gate"))}</td><td class="sm muted">{esc(s.get("basis"))}</td>'
            f'<td>{" ".join(chr(60) + f"a class=jump href=#{esc(x)}" + chr(62) + esc(x) + "</a>" for x in s.get("opportunity_ids", []))}</td></tr>'
            for s in w.get("optimized_steps", []))
        un = "".join(f"<li>{esc(x)}</li>" for x in w.get("unknowns", []))
        wf_html.append(f'''
<section class="wf"><div class="wf-h"><span class="fid">{esc(w["id"])}</span><h3>{esc(w.get("name"))}</h3>
<p class="sm muted">目标：{esc(w.get("goal"))}</p><div class="refs">{refs_html(w.get("evidence_refs"))}</div></div>
<div class="cols2"><div><h4>当前怎么跑</h4><table class="tbl"><thead><tr><th>步骤</th><th>现在</th><th>实际观察</th><th>卡点 / 正常协作</th><th>证据</th></tr></thead><tbody>{cur}</tbody></table></div>
<div><h4>改造后</h4><table class="tbl"><thead><tr><th>步骤</th><th>归属</th><th>动作</th><th>产出</th><th>何时停</th><th>依据</th><th>优化项</th></tr></thead><tbody>{opt}</tbody></table>
<p class="sm"><b>分工依据：</b>{esc(w.get("boundary_reason"))}</p>
<div class="unk"><b>日志覆盖不到</b><ul>{un}</ul></div></div></div>
<p class="sm root"><b>根因假设：</b>{esc(w.get("root_cause"))}</p></section>''')
    p2 = page_head("真实工作流", "按业务成果还原；长会话可能跨多个任务，类型分类仅供检索") + "".join(wf_html)

    # ---- P3 人机边界
    br = "".join(
        f'<div class="bcard b-{esc(str(r.get("mode", "")).lower())}"><h3>{esc(r.get("mode"))}</h3>'
        f'<div class="bcol"><span class="lbl">适用条件</span><ul>{"".join(f"<li>{esc(x)}</li>" for x in r.get("conditions", []))}</ul></div>'
        f'<div class="bcol"><span class="lbl">例子</span><ul>{"".join(f"<li>{esc(x)}</li>" for x in r.get("examples", []))}</ul></div>'
        f'<div class="bcol"><span class="lbl">何时升级 / 停</span><ul>{"".join(f"<li>{esc(x)}</li>" for x in r.get("escalate_when", []))}</ul></div></div>'
        for r in ana.get("boundary_rules", []))
    by = {"AI": [], "协作": [], "人": []}
    for w in ana.get("workflows", []):
        for s in w.get("optimized_steps", []):
            by.setdefault(s.get("owner", "协作"), []).append((w.get("name"), s.get("step"), s.get("basis")))
    lists = "".join(
        f'<div class="bsum"><h4>{esc(k)}（{len(v)} 步）</h4><ul>' +
        "".join(f'<li><b>{esc(st)}</b><span class="sm muted">　{esc(wf)}｜{esc(bs)}</span></li>' for wf, st, bs in v) + "</ul></div>"
        for k, v in by.items() if v)
    p3 = page_head("人机分工", "AI 执行、协作对齐、人拍板；每一步的判定依据可查") + f'''
<div class="bgrid">{br}</div>
<div class="cols3">{lists}</div>
<div class="notebox">分工单位是具体步骤，不是整个岗位。AI 产出未经人验收不得外发；工具失败或权限拒绝属于系统阻塞，应先补条件而不是反复提示。</div>'''

    # ---- P4 SOP
    sop_html = "".join(sop_section(s) for s in ana.get("sops", []))
    p4 = page_head("SOP 工作手册", "全部为草案·未试运行；先按试跑样本小范围验证，通过后再固化") + sop_html

    # ---- P5 证据与历史
    prev = scan.get("previous")
    if prev:
        hist_html = (f'<div class="hcard"><b>历史参考：{esc(prev.get("date"))}（来源 {esc(prev.get("source"))}'
                     f'{"，仅参考" if prev.get("reference_only") else ""}）</b>'
                     f'<p class="sm">{esc(hist.get("comparability", ""))}</p>'
                     f'<p class="sm">能确认的变化：{esc(hist.get("what_changed", ""))}</p>'
                     f'<p class="sm">不能据此证明：{esc(hist.get("what_not_proven", ""))}</p>'
                     f'<p class="sm">下次复盘：{esc(hist.get("next_review", ""))}</p></div>')
    else:
        hist_html = f'<div class="hcard"><b>首次扫描</b><p class="sm">{esc(hist.get("finding", ""))}</p></div>'
    cov = scan.get("coverage", {})
    cov_html = "".join(f"<li>{esc(k)}：{esc(v)}</li>" for k, v in cov.items() if k != "skipped_files")
    skip_html = "".join(f"<li>{esc(x.get('id'))}（{esc(x.get('reason'))}）</li>" for x in cov.get("skipped_files", [])) or "<li>无</li>"
    ev_rows = "".join(
        f'<tr><td>{ref_chip(e["ref"])}</td><td>{esc(e.get("date"))}</td><td>{esc(e.get("family"))}</td><td>{esc(e.get("phase"))}</td>'
        f'<td>{"/".join(e.get("correction_categories", [])) or ("判断候选" if e.get("judgment") else "")}</td>'
        f'<td class="q">{esc(e.get("quote"))}</td></tr>' for e in scan.get("evidence", []))
    lim = "".join(f"<li>{esc(x)}</li>" for x in ana.get("coverage_review", {}).get("limitations", []))
    covrev = "".join(f"<li>{esc(x)}</li>" for x in ana.get("coverage_review", {}).get("excluded", []))
    p5 = page_head("证据与历史", "全部候选来自规则召回；语义结论以分析页为准") + f'''
<div class="cols2"><div><h3>覆盖与口径</h3><ul class="sm">{cov_html}</ul>
<h4>未纳入</h4><ul class="sm">{skip_html}</ul>
<h4>分析限制</h4><ul class="sm">{lim}</ul><h4>已排除</h4><ul class="sm">{covrev}</ul></div>
<div><h3>历史与对比口径</h3>{hist_html}</div></div>
<h3>工作证据索引（{len(scan.get("evidence", []))} 条）</h3>
<input id="evq" class="search" placeholder="输入类型 / 环节 / 原话关键词过滤…" oninput="filterTable('evq','evtbl')">
<table class="tbl" id="evtbl"><thead><tr><th>引用</th><th>日期</th><th>类型</th><th>环节</th><th>类别</th><th>原话（已脱敏）</th></tr></thead><tbody>{ev_rows}</tbody></table>'''
    return [p1, p2, p3, p4, p5]


# ---------------------------------------------------------------- 完整记录 HTML
def build_record(scan):
    m = scan.get("metrics", {})
    sec = []
    sc = scan.get("scope", {})
    sec.append(page_head("工作扫描记录（采集稿）",
                         f'{sc.get("workspace")}｜{sc.get("from")} → {sc.get("to")}｜run {scan.get("run_id")}'))
    sec.append('<div class="notebox">本文件是完整采集记录，不是流程分析。候选分类与纠错为规则召回，需语义复核；人侧间隔不是工时。</div>')
    cov = scan.get("coverage", {})
    sec.append('<h3>覆盖情况</h3><ul class="sm">' + "".join(f"<li>{esc(k)}：{esc(v)}</li>" for k, v in cov.items()) + "</ul>")
    sec.append('<h3>总览指标</h3><div class="kpirow">' + "".join(
        f'<div class="kpi"><div class="k-l">{esc(k)}</div><div class="k-v">{esc(v)}</div></div>'
        for k, v in m.items() if isinstance(v, (int, float))) + "</div>")
    sec.append("<h3>工作类型（启发分类）</h3><table class='tbl'><thead><tr><th>类型</th><th>会话</th><th>轮次</th><th>纠错候选率</th><th>判断候选</th><th>对外占比</th><th>Skill覆盖</th><th>已有Skill线索</th></tr></thead><tbody>"
               + "".join(f"<tr><td><b>{esc(f['family'])}</b></td><td>{f['sessions']}</td><td>{f['turns']}</td><td>{f['correction_rate']}%</td><td>{f['judgment_turns']}</td><td>{f['external_share']}%</td><td>{f['skill_share']}%</td><td class='sm'>{esc(', '.join(f['assets']['skills'][:5]))}</td></tr>" for f in scan.get("families", []))
               + "</tbody></table>")
    for f in scan.get("families", []):
        ph = "".join(f"<tr><td>{esc(p)}</td><td>{x['turns']}</td><td>{x['sessions']}</td><td>{x['human_min']}</td><td>{x['ai_min']}</td></tr>"
                     for p, x in f.get("phases", {}).items())
        sec.append(f"<details><summary><b>{esc(f['family'])}</b>｜{f['sessions']} 会话｜路径 {esc('；'.join(p['path'] for p in f.get('paths', [])))}</summary>"
                   + (f"<table class='tbl'><thead><tr><th>环节</th><th>轮次</th><th>涉及会话</th><th>人侧间隔 min</th><th>AI 活动 min</th></tr></thead><tbody>{ph}</tbody></table>" if ph else "")
                   + f"<p class='sm'>返工示例：{esc('；'.join(f.get('correction_examples', [])))}</p></details>")
    sec.append("<h3>重复任务簇</h3><table class='tbl'><thead><tr><th>片段</th><th>会话数</th><th>类型</th><th>示例</th></tr></thead><tbody>"
               + "".join(f"<tr><td><b>{esc(c['key'])}</b></td><td>{c['n']}</td><td>{esc('/'.join(c['families']))}</td><td class='sm'>{esc('；'.join(c['examples']))}</td></tr>" for c in scan.get("clusters", []))
               + "</tbody></table>")
    a = scan.get("assets", {})
    autos = "；".join(x["title"] + "（运行 " + str(x["runs"]) + " 次）" for x in a.get("automations", [])[:8]) or "无"
    sec.append("<h3>已有资产线索</h3><ul class='sm'>"
               + "<li>SOP 文件：" + esc("；".join(x["name"] + "（" + x["where"] + "）" for x in a.get("sops", [])) or "未见") + "</li>"
               + "<li>定时任务运行：" + esc(autos) + "</li>"
               + f"<li>用户级 Skill {a.get('skills_count')} 个（名称见 scan.json）｜用户级记忆 {a.get('user_memory_chars')} 字</li></ul>")
    sec.append(f"<h3>工作证据（{len(scan.get('evidence', []))} 条）</h3><input id='evq' class='search' placeholder='过滤…' oninput=\"filterTable('evq','evtbl')\">"
               "<table class='tbl' id='evtbl'><thead><tr><th>引用</th><th>日期</th><th>类型</th><th>环节</th><th>类别</th><th>原话</th></tr></thead><tbody>"
               + "".join(f"<tr><td>{esc(e['ref'])}</td><td>{esc(e['date'])}</td><td>{esc(e['family'])}</td><td>{esc(e['phase'])}</td><td>{'/'.join(e.get('correction_categories', [])) or ('判断候选' if e.get('judgment') else '')}</td><td class='q'>{esc(e['quote'])}</td></tr>" for e in scan.get("evidence", []))
               + "</tbody></table>")
    sec.append("<h3>工作区</h3><table class='tbl'><thead><tr><th>工作区</th><th>会话</th><th>轮次</th><th>纠错候选率</th><th>工具失败率</th></tr></thead><tbody>"
               + "".join(f"<tr><td>{esc(w['workspace'])}</td><td>{w['sessions']}</td><td>{w['turns']}</td><td>{w['correction_rate']}%</td><td>{w['fail_rate']}%</td></tr>" for w in scan.get("workspaces", []))
               + "</tbody></table>")
    sec.append(f"<h3>会话清单（{len(scan.get('sessions', []))} 个）</h3><input id='sq' class='search' placeholder='过滤工作区/类型/标题…' oninput=\"filterTable('sq','stbl')\">"
               "<table class='tbl' id='stbl'><thead><tr><th>日期</th><th>会话</th><th>工作区</th><th>类型</th><th>标题</th><th>轮次</th><th>纠错候选</th><th>路径</th></tr></thead><tbody>"
               + "".join(f"<tr><td>{esc(s['date'])}</td><td>{esc(s['id'])}</td><td>{esc(s['workspace'])}</td><td>{esc(s['family'])}</td><td>{esc(s['title'])}</td><td>{s['turns']}</td><td>{s['corrections']}</td><td class='sm'>{esc(s['path'])}</td></tr>" for s in scan.get("sessions", []))
               + "</tbody></table>")
    return sec


# ---------------------------------------------------------------- SOP / 分析 Markdown
def sop_markdown(ana):
    out = ["# SOP 草案（personal-ai-fde v3）", "",
           f"> 生成 {time.strftime('%Y-%m-%d %H:%M')}｜全部为草案·未试运行；先小范围试跑，通过后再固化。", ""]
    for s in ana.get("sops", []):
        out += [f"## {s['id']} {s.get('title')}", "", f"- 状态：{s.get('status')}", f"- 触发：{s.get('trigger')}",
                "- 输入：" + "；".join(s.get("inputs", [])), "", "| # | 执行者 | 动作 | 产出 | 检查 |", "|---|---|---|---|---|"]
        out += [f"| {x.get('order', i + 1)} | {x.get('owner')} | {x.get('action')} | {x.get('output')} | {x.get('check')} |"
                for i, x in enumerate(s.get("steps", []))]
        out += ["", "**人工确认点**：" + "；".join(s.get("human_gates", [])), "", "**异常处置**："]
        out += [f"- {x}" for x in s.get("exception_rules", [])]
        out += ["", "**验收**："] + [f"- {x}" for x in s.get("acceptance", [])]
        trial = s.get("trial", {})
        out += ["", f"**回退**：{s.get('rollback')}", "",
                f"**试跑**：{trial.get('sample')}｜指标：{'；'.join(trial.get('metrics', []))}",
                f"通过条件：{trial.get('pass_condition')}｜停止条件：{trial.get('stop_condition')}", "",
                "**启动指令（填好材料后粘贴）**：", "", "```", s.get("copy_prompt", ""), "```", ""]
    return "\n".join(out)


def analysis_markdown(ana):
    es = ana.get("executive_summary", {})
    L = [f"# {ana.get('title')}", "",
         f"> scan run {ana.get('scan_run_id')}｜生成 {time.strftime('%Y-%m-%d %H:%M')}｜所有 SOP 为草案·未试运行", "",
         "## 结论", f"- {es.get('headline')}", f"- {es.get('conclusion')}", f"- 先做：{es.get('first_action')}"]
    for x in es.get("not_recommended", []):
        L.append(f"- 不建议：{x}")
    L += ["", "## 发现"]
    for f in ana.get("findings", []):
        L.append(f"- **{f['id']}** {f.get('observation')} → 推断：{f.get('inference')}"
                 f"（{f.get('confidence')}；另一种可能：{f.get('alternative_explanation')}；证据 {'、'.join(f.get('evidence_refs', []))}）")
    L += ["", "## 工作流与分工"]
    for w in ana.get("workflows", []):
        L.append(f"### {w['id']} {w.get('name')}")
        for s in w.get("current_steps", []):
            L.append(f"- 现在｜{s.get('step')}（{s.get('actor')}）：{s.get('observed')}"
                     f"｜{'卡点：' + s.get('friction') if s.get('friction') else ''}（{'、'.join(s.get('evidence_refs', []))}）")
        for s in w.get("optimized_steps", []):
            L.append(f"- 改为｜{s.get('step')}（{s.get('owner')}）：{s.get('action')} → {s.get('output')}"
                     f"｜停下条件：{s.get('gate')}｜依据：{s.get('basis')}")
        L.append(f"- 分工依据：{w.get('boundary_reason')}｜未知：{'；'.join(w.get('unknowns', []))}")
    L += ["", "## 优化项与 SOP"]
    for o in ana.get("opportunities", []):
        L.append(f"- **{o['id']} {o.get('stage')}**（{o.get('priority')}）{o.get('diagnosis')} → {o.get('change')}"
                 f"（{o.get('owner')}）｜先做：{o.get('first_action')}｜验收：{'；'.join(o.get('acceptance', []))}｜{o.get('sop_id')}"
                 f"｜收益待试跑验证：{o.get('expected_benefit')}")
    h = ana.get("history_review", {})
    L += ["", "## 历史口径", f"- {h.get('finding')}", f"- 可比性：{h.get('comparability')}",
          f"- 能确认：{h.get('what_changed')}", f"- 不能证明：{h.get('what_not_proven')}",
          f"- 下次复盘：{h.get('next_review')}"]
    return "\n".join(L)


# ---------------------------------------------------------------- 样式与脚本
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{background:#EEF2F7;color:#1F2937;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;font-size:15px;line-height:1.65}
.topbar{position:sticky;top:0;z-index:20;background:#0F2547;color:#fff;display:flex;gap:4px;align-items:center;padding:10px 18px;flex-wrap:wrap}
.topbar .brand{font-weight:800;margin-right:14px;letter-spacing:.5px}.topbar .brand i{display:inline-block;width:9px;height:9px;border-radius:50%;background:#5B9BFF;margin-right:8px;box-shadow:14px 0 0 #F59E42}
.topbar a{color:#C9D8F2;text-decoration:none;padding:6px 13px;border-radius:8px;font-size:14px;cursor:pointer}
.topbar a:hover,.topbar a.on{background:#1D3A6B;color:#fff}
.wrap{max-width:1160px;margin:0 auto;padding:22px 20px 60px}
.page{background:#fff;border-radius:16px;box-shadow:0 6px 24px rgba(15,35,70,.08);padding:30px 34px;margin-bottom:22px}
h1{font-size:27px;color:#0F172A}.psub{color:#64748B;font-size:14px;margin-top:4px}
.phead{border-bottom:2px solid #E6ECF3;padding-bottom:12px;margin-bottom:20px}
h3{font-size:18px;margin:18px 0 10px;color:#0F172A}h4{font-size:15px;margin:12px 0 8px;color:#334155}
.hero{background:linear-gradient(135deg,#F4F8FF,#fff);border:1px solid #D9E6FB;border-left:5px solid #1D6FE8;border-radius:12px;padding:18px 20px;margin-bottom:18px}
.hl-main{font-size:21px;font-weight:800;color:#0F2F66;margin-bottom:8px}
.concl{color:#334155}
.firstbox{margin-top:14px;background:#FFF7EF;border:1px solid #FDE2C8;border-radius:10px;padding:12px 14px}.firstbox b{color:#C2560A}
.cols2{display:grid;grid-template-columns:1fr 1fr;gap:20px}.cols3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px}
.fcard{border:1px solid #E6ECF3;border-radius:12px;padding:12px 14px;margin-bottom:10px;background:#FBFCFE}
.fhead{display:flex;gap:8px;align-items:center}.fid{background:#1D6FE8;color:#fff;border-radius:6px;padding:1px 8px;font-size:12px;font-weight:800}
.conf{margin-left:auto;font-size:12px;color:#64748B}.alt{color:#94A3B8;font-size:13px;margin-top:4px}
.tbl{width:100%;border-collapse:collapse;font-size:14px;margin:8px 0}
.tbl th{text-align:left;color:#64748B;font-weight:600;padding:7px 8px;border-bottom:2px solid #E6ECF3;background:#F8FAFD}
.tbl td{padding:8px;border-bottom:1px solid #EEF2F7;vertical-align:top}
.c-ord{width:34px;color:#1D6FE8;font-weight:800}.c-check{color:#475569;font-size:13px}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap}
.b-ai{background:#E8F0FE;color:#1D4ED8}.b-human{background:#FFF1E4;color:#C2560A}.b-both{background:#EDE9FE;color:#6D28D9}
.b-hot{background:#F2790D;color:#fff}.b-next{background:#E8F0FE;color:#1D4ED8}.b-watch{background:#EEF2F7;color:#64748B}
.b-draft{background:#FDECEC;color:#B42318}
.refs{margin-top:6px}.refchip{border:1px solid #C9D8F2;background:#F4F8FF;color:#1D4ED8;border-radius:6px;font-size:12px;padding:1px 8px;margin:0 4px 4px 0;cursor:pointer}
.refchip:hover{background:#E8F0FE}
.jump{color:#1D6FE8;font-weight:700;text-decoration:none;margin-right:6px;cursor:pointer}
.wf{border:1px solid #E6ECF3;border-radius:14px;padding:18px 20px;margin-bottom:18px}
.wf-h{margin-bottom:8px}.root{background:#F7F9FC;border-radius:10px;padding:10px 14px}
.unk{background:#FFFBEF;border:1px dashed #FDE2C8;border-radius:10px;padding:10px 14px;margin-top:10px}
.bgrid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:18px}
.bcard{border-radius:14px;padding:16px 18px;border:1px solid #E6ECF3}
.bcard h3{margin-top:0}.bcard.b-ai{background:#F4F8FF}.bcard.b-human{background:#FFF8F1}.bcard.b-both{background:#FAF7FF}
.bcol{margin-top:8px}.lbl{display:inline-block;font-size:12px;font-weight:800;color:#94A3B8;letter-spacing:1px;margin-bottom:4px}
ul{padding-left:18px}.sm{font-size:13px}.muted{color:#94A3B8}
.sop{border:1px solid #E6ECF3;border-radius:14px;padding:18px 20px;margin-bottom:20px}
.sop-h{display:flex;align-items:center;gap:10px;margin-bottom:10px}.sop-id{background:#0F2547;color:#fff;border-radius:6px;padding:2px 10px;font-size:13px;font-weight:800}
.sop-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:10px}
.sop-grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin:10px 0}
.promptbox{background:#0F2547;border-radius:12px;padding:14px 16px;margin-top:8px;position:relative}
.promptbox .lbl{color:#9DB6E4}.promptbox pre{white-space:pre-wrap;color:#E8F0FE;font-family:inherit;font-size:14px;margin-top:6px;padding-right:70px}
.cp{position:absolute;right:12px;top:12px;border:0;background:#1D6FE8;color:#fff;border-radius:6px;padding:5px 12px;font-size:12px;cursor:pointer}
.sop-h .cp{position:static;margin-left:auto}
.notrec{background:#FDF4F4;border:1px solid #F5C6C6;border-radius:10px;padding:10px 14px;margin-top:12px}.notrec b{color:#B42318}
.todobox{background:#F4F8FF;border:1px solid #D9E6FB;border-radius:12px;padding:14px 18px;margin-top:16px}
.todobox ol{padding-left:20px}.hardsm{margin-top:10px;background:#0F2547;color:#fff;display:inline-block;border-radius:8px;padding:6px 14px;font-weight:700;font-size:14px}
.notebox{background:#FFFBEF;border:1px solid #FDE2C8;border-radius:10px;padding:12px 16px;margin:14px 0}
.search{width:100%;padding:9px 14px;border:1px solid #C9D8F2;border-radius:10px;margin:8px 0 10px;font-size:14px}
.hcard{border:1px solid #E6ECF3;border-radius:12px;padding:14px 16px;background:#FBFCFE}
.q{color:#334155;max-width:520px}
.kpirow{display:flex;flex-wrap:wrap;gap:10px}.kpi{border:1px solid #E6ECF3;border-radius:10px;padding:8px 14px;background:#fff}.k-l{font-size:12px;color:#64748B}.k-v{font-size:20px;font-weight:800;color:#1D6FE8}
details{border:1px solid #E6ECF3;border-radius:10px;padding:10px 14px;margin:8px 0}summary{cursor:pointer;font-weight:600}
footer.f{color:#94A3B8;font-size:12px;text-align:center;padding:10px 0 30px}
@media(max-width:900px){.cols2,.cols3,.bgrid,.sop-grid,.sop-grid3{grid-template-columns:1fr}}
@media print{.topbar{display:none}body{background:#fff}.page{box-shadow:none;border-radius:0;page-break-after:always;max-width:none}details>summary{display:none}.search{display:none}.cp{display:none}}
"""

JS = """
function show(id){document.querySelectorAll('.page').forEach(function(p){p.style.display=p.id===id?'block':'none';});document.querySelectorAll('.topbar a[data-tab]').forEach(function(a){a.className=a.getAttribute('data-tab')===id?'on':'';});window.scrollTo(0,0);}
function showTabById(hash){show('tab3');var el=document.querySelector(hash);if(el)el.scrollIntoView({behavior:'smooth',block:'start'});}
document.querySelectorAll('.topbar a[data-tab]').forEach(function(a){a.addEventListener('click',function(e){e.preventDefault();show(a.getAttribute('data-tab'));});});
if(document.querySelector('.topbar a[data-tab]'))show(document.querySelector('.topbar a[data-tab]').getAttribute('data-tab'));
function filterTable(inputId,tableId){var q=document.getElementById(inputId).value.toLowerCase();document.querySelectorAll('#'+tableId+' tbody tr').forEach(function(tr){tr.style.display=tr.innerText.toLowerCase().indexOf(q)>=0?'':'none';});}
function copyText(t,b){function done(){b.innerText='已复制';setTimeout(function(){b.innerText='复制';},1500);}function fallback(){var n=document.createElement('textarea');n.value=t;document.body.appendChild(n);n.select();document.execCommand('copy');document.body.removeChild(n);done();}if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(done,fallback);}else fallback();}
function copyPre(b){copyText(b.parentNode.querySelector('pre').innerText,b);}
function copyEl(b,id){copyText(document.getElementById(id).innerText,b);}
function gotoRef(btn){var r=btn.getAttribute('data-ref');var sid=r.split('#')[0];var rec=document.getElementById('tab-record');if(rec){show('tab-record');var input=document.getElementById('sq');if(input){input.value=sid;filterTable('sq','stbl');}}var rows=document.querySelectorAll('#evtbl tbody tr');for(var i=0;i<rows.length;i++){if(rows[i].innerText.indexOf(r)>=0){rows[i].style.background='#FFF3D6';rows[i].scrollIntoView({behavior:'smooth',block:'center'});(function(row){setTimeout(function(){row.style.background='';},2500);})(rows[i]);break;}}}
"""


def wrap_html(title, pages, tab_names, brand, ids=None):
    ids = ids or [f"tab{i}" for i in range(len(pages))]
    nav = "".join(f'<a href="#" data-tab="{ids[i]}" class="{"on" if i == 0 else ""}">{esc(n)}</a>' for i, n in enumerate(tab_names))
    body = "".join(f'<div class="page" id="{ids[i] if i < len(ids) else "tab" + str(i)}">{p}</div>' for i, p in enumerate(pages))
    return (f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)}</title><style>{CSS}</style></head><body>'
            f'<nav class="topbar"><span class="brand"><i></i>{esc(brand)}</span>{nav}</nav>'
            f'<div class="wrap">{body}</div><footer class="f">本机生成 · 只读分析 · SOP 均为草案，试跑通过前不代表已实施或已产生收益</footer>'
            f'<script>{JS}</script></body></html>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", required=True)
    ap.add_argument("--analysis")
    ap.add_argument("--out")
    ap.add_argument("--sop-out")
    ap.add_argument("--analysis-out")
    ap.add_argument("--record-out")
    a = ap.parse_args()
    scan = json.load(open(a.scan, encoding="utf-8"))
    ana = None
    if a.analysis:
        ana = json.load(open(a.analysis, encoding="utf-8"))
        validate(scan, ana)
        if ERRORS:
            for e in ERRORS:
                print("ERROR", e, file=sys.stderr)
            sys.exit(2)
    stamp = time.strftime("%Y%m%d")
    if a.record_out:
        open(a.record_out, "w", encoding="utf-8").write(
            wrap_html(f"工作扫描记录｜{scan.get('run_id', '')}", build_record(scan),
                      ["采集记录"], "工作扫描记录 · Personal FDE", ids=["tab-record"]))
        print(f"RECORD_OK\t{a.record_out}")
    if a.out:
        if not ana:
            sys.exit("生成分析报告需要 --analysis；只转记录请用 --record-out")
        pages = build_report(scan, ana)
        open(a.out, "w", encoding="utf-8").write(
            wrap_html(f"工作流程诊断与行动方案｜{stamp}", pages,
                      ["结论与行动", "真实工作流", "人机分工", "SOP 手册", "证据与历史"],
                      "AI 工作搭子 · Personal FDE v3"))
        print(f"REPORT_OK\t{a.out}")
    if a.sop_out:
        if not ana:
            sys.exit("--sop-out 需要 --analysis")
        open(a.sop_out, "w", encoding="utf-8").write(sop_markdown(ana))
        print(f"SOP_OK\t{a.sop_out}\t{len(ana.get('sops', []))} 个草案")
    if a.analysis_out:
        if not ana:
            sys.exit("--analysis-out 需要 --analysis")
        open(a.analysis_out, "w", encoding="utf-8").write(analysis_markdown(ana))
        print(f"ANALYSIS_MD_OK\t{a.analysis_out}")
    for w in WARN:
        print("WARN", w, file=sys.stderr)


if __name__ == "__main__":
    main()
