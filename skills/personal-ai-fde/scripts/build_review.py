#!/usr/bin/env python3
"""
personal-ai-fde v1.0.0 · 腾讯风格回顾报告（思维导图版）。

  python3 build_review.py --scan scan.json --analysis analysis.json --out review.html

结构（6 节）：
01 数据回顾（Wrapped 大数字）
02 工作全景：思维导图 = 习惯画像 + 四大层级（可深度自动化/协作加深/稳步推进/判断密集）× 板块 × SOP 落点
03-06 建议 1-4：大标题带序号；每条建议 = 流程图（现在→优化后）+ 验收 + 启动指令（即 SOP 本体）
SOP 频率榜：按使用频率披露前 5，更多渐进展开；点击芯片直达对应建议页的启动指令。
纯标准库、自包含 HTML；大标题用本机腾讯体 W7。
"""
import argparse, html, json, sys
from collections import Counter

esc = lambda s: html.escape(str(s if s is not None else ""), quote=True)

TX, TX_D, TX_L = "#0052D9", "#003BA3", "#E6EEFB"
CY, OR, INK, MUT, LINE = "#00A9CE", "#FF7D00", "#0B0B0F", "#6E6E76", "#E4E4EA"
ACT = {"AI": (TX_L, TX), "协作": ("#E3F6FB", CY), "人": ("#FFF3E6", OR)}
NEUT = ("#F2F3F5", "#C4C9D2")

ADVICE = {
    1: {"flows": [("W1", "伙伴邮件：从事实到可发送草稿"), ("W2", "伙伴材料：从文件堆到对照表")],
        "title": "先对齐，再起草", "lead": "伙伴邮件与准入材料：事实、披露、编号在出稿前钉死，你只审业务意图"},
    2: {"flows": [("W3", "活动物料：一份事实表驱动多份产物")],
        "title": "一份事实源，多份产物", "lead": "议程、主持稿、展示页共用同一份已确认事实，改动一次、全量检查"},
    3: {"flows": [("W4", "调研：证据先行，判断归人"), ("W5", "纪要与汇报：先记录，再成稿")],
        "title": "把资料变成判断", "lead": "研究、纪要、汇报先成证据与状态，再成文案；判断和归属由你拍板"},
    4: {"flows": [("W6", "工具与流程改造：讨论、试作、上线分开")],
        "title": "边界即纪律", "lead": "每条工作流改造都先过价值检验；阶段授权 + 人工验收 + 两周试运行"},
}
SOP_FAMILY = {"SOP-01": "邮件与消息沟通", "SOP-02": "调研与分析", "SOP-03": "会议与活动筹备",
              "SOP-04": "调研与分析", "SOP-05": "文档与汇报写作", "SOP-06": "AI 工作流与 Skill 搭建"}
SOP_PAGE = {"SOP-01": "pp-a1", "SOP-02": "pp-a1", "SOP-03": "pp-a2", "SOP-04": "pp-a3", "SOP-05": "pp-a3", "SOP-06": "pp-a4"}
SOP_LOGIC = {
    "SOP-01": "先把人和事摆清楚再动笔，训练「先对齐后起草」：事实不清就让 AI 写，它只能编。",
    "SOP-02": "让 AI 编号对表、你只批例外，把找材料的体力活交出去——查得全，不等于能放行。",
    "SOP-03": "一份事实源喂所有物料，改一处全同步，养成单点维护的习惯，告别逐份改到 V5。",
    "SOP-04": "先写问题再搜资料，防止 AI 拿搜索摘要糊弄你；取舍和判断永远留在你手里。",
    "SOP-05": "先让 AI 把「谁做了什么」摆成证据，你再定重点和归属——话说过，不等于事做完。",
    "SOP-06": "讨论时不许动手、动手前先说范围：给 AI 立规矩——阶段不清，执行就是越权。",
}


def cjk_units(s):
    return sum(1 if ord(c) > 127 else 0.55 for c in s)


def cut(s, n):
    s = str(s or "")
    return s if len(s) <= n else s[: n - 1] + "…"


def wrap_caption(cap, width=14):
    """按显示宽度折行：短说明完整显示，超长说明第二行末尾加省略号。"""
    cap = str(cap or "")
    chunks, cur, units = [], "", 0.0
    for ch in cap:
        u = 1 if ord(ch) > 127 else 0.55
        if units + u > width and cur:
            chunks.append(cur)
            cur, units = ch, u
        else:
            cur += ch
            units += u
    if cur:
        chunks.append(cur)
    if len(chunks) <= 2:
        return chunks
    return [chunks[0], chunks[1][:-1] + "…"]


def flow_svg(steps, colored):
    H, RH = 78, 56
    items, x = [], 0
    for name, cap, actor, warn in steps:
        cap_lines = wrap_caption(cap, 14)
        units = max(cjk_units(name), max(cjk_units(l) for l in cap_lines) * 0.78)
        w = int(max(96, min(240, units * 14.5 + 30)))
        items.append((x, w, name, cap_lines, actor, warn))
        x += w + 34
    total = max(x - 34, 120)
    parts = [f'<svg viewBox="0 0 {total} {H}" class="flow" role="img">']
    for i, (nx, w, name, cap_lines, actor, warn) in enumerate(items):
        fill, stroke = ACT.get(actor, NEUT) if colored else NEUT
        parts.append(f'<rect x="{nx}" y="6" width="{w}" height="{RH}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>')
        if warn:
            parts.append(f'<circle cx="{nx + w - 10}" cy="16" r="7" fill="#D54941"/><text x="{nx + w - 10}" y="19.6" text-anchor="middle" font-size="10" fill="#fff" font-weight="800">!</text>')
        parts.append(f'<text x="{nx + w / 2}" y="25" text-anchor="middle" font-size="13" font-weight="700" fill="{INK}">{esc(name)}</text>')
        ccolor = "#D54941" if warn else MUT
        for li, line in enumerate(cap_lines):
            parts.append(f'<text x="{nx + w / 2}" y="{41 + li * 13}" text-anchor="middle" font-size="10.5" fill="{ccolor}">{esc(line)}</text>')
        if i < len(items) - 1:
            ax = nx + w + 7
            parts.append(f'<line x1="{ax}" y1="34" x2="{ax + 16}" y2="34" stroke="#B9C4D6" stroke-width="1.6"/>')
            parts.append(f'<path d="M{ax + 16} 29 L{ax + 24} 34 L{ax + 16} 39 Z" fill="#B9C4D6"/>')
    parts.append("</svg>")
    return f'<div class="flowwrap">{"".join(parts)}</div>'


# ---------------------------------------------------------------- 思维导图
TIERS = [
    ("可深度自动化", OR, "AI 接手的空间最大：规则稳定、重复性高"),
    ("协作加深", TX, "已在协作，补上出稿前对齐与验收可再进一步"),
    ("稳步推进", "#8A93A6", "流程已顺，沉淀模板、维持现状"),
    ("判断密集 · 保留人审", INK, "对外占比高：AI 做外围，判断和授权归人"),
]


def mindmap(work_fams, fam_sops, sop_rank, total_work):
    def depth_key(f):
        if f.get("external_share", 0) >= 60:
            return 3
        if f.get("skill_share", 0) < 45:
            return 0
        if f.get("correction_rate", 0) >= 8:
            return 1
        return 2

    groups = [[], [], [], []]
    for f in work_fams:
        groups[depth_key(f)].append(f)

    SEG_W, SEG_H, SEG_GAP = 320, 46, 14
    GX, G_W = 270, 176
    SX = 560
    ggeo, y = [], 44
    for segs in groups:
        gh = max(len(segs), 1) * SEG_H + max(len(segs) - 1, 0) * SEG_GAP
        ggeo.append((y, gh))
        y += gh + 38
    H = y + 6
    root_cy = H / 2

    parts = [f'<svg viewBox="0 0 1160 {int(H)}" class="mmap" role="img">']
    parts.append(f'<rect x="24" y="{root_cy - 30}" width="180" height="60" rx="14" fill="{INK}"/>')
    parts.append(f'<text x="114" y="{root_cy - 3}" text-anchor="middle" font-size="17" font-weight="800" fill="#fff">我的工作</text>')
    parts.append(f'<text x="114" y="{root_cy + 16}" text-anchor="middle" font-size="10.5" fill="#B9C4D6">{len(work_fams)} 大板块 · {total_work} 任务</text>')

    for gi, segs in enumerate(groups):
        tname, tcolor, _ = TIERS[gi]
        gy, gh = ggeo[gi]
        gcy = gy + gh / 2
        parts.append(f'<path d="M204 {root_cy} C 240 {root_cy}, 240 {gcy}, {GX} {gcy}" fill="none" stroke="{tcolor}" stroke-width="2" opacity="0.55"/>')
        parts.append(f'<rect x="{GX}" y="{gcy - 22}" width="{G_W}" height="44" rx="22" fill="{tcolor}"/>')
        parts.append(f'<text x="{GX + G_W / 2}" y="{gcy + 4}" text-anchor="middle" font-size="13.5" font-weight="800" fill="#fff">{esc(tname)}</text>')
        parts.append(f'<text x="{GX + G_W / 2}" y="{gcy + 32}" text-anchor="middle" font-size="10" fill="{MUT}">{len(segs)} 个板块</text>')
        for si, f in enumerate(segs):
            sy = gy + si * (SEG_H + SEG_GAP)
            scy = sy + SEG_H / 2
            parts.append(f'<path d="M{GX + G_W} {gcy} C {SX - 30} {gcy}, {SX - 30} {scy}, {SX} {scy}" fill="none" stroke="{tcolor}" stroke-width="1.5" opacity="0.35"/>')
            fill = "#FFFDF8" if gi == 0 else ("#FBFCFF" if gi in (1, 2) else "#F7F7F9")
            parts.append(f'<rect x="{SX}" y="{sy}" width="{SEG_W}" height="{SEG_H}" rx="10" fill="{fill}" stroke="{tcolor}" stroke-width="1.4"/>')
            parts.append(f'<text x="{SX + 12}" y="{sy + 19}" font-size="13" font-weight="700" fill="{INK}">{esc(f["family"])}</text>')
            parts.append(f'<text x="{SX + 12}" y="{sy + 36}" font-size="10" fill="{MUT}">纠错候选 {f["correction_rate"]}% · Skill 覆盖 {f["skill_share"]}% · 对外 {f["external_share"]}%</text>')
            parts.append(f'<text x="{SX + SEG_W - 12}" y="{sy + 19}" text-anchor="end" font-size="12" font-weight="800" fill="{TX_D}">{f["sessions"]} 任务</text>')
            sids = sorted(fam_sops.get(f["family"], []), key=lambda x: sop_rank.get(x, 99))
            if sids:
                parts.append(f'<text x="{SX + SEG_W - 12}" y="{sy + 36}" text-anchor="end" font-size="10.5" font-weight="800" fill="{INK}">{esc(" ".join(sids))}</text>')
            else:
                parts.append(f'<text x="{SX + SEG_W - 12}" y="{sy + 36}" text-anchor="end" font-size="10" fill="#9B9BA3">可沉淀模板</text>')
    parts.append("</svg>")
    legend = "".join(
        f'<span><i class="lg" style="background:{c}"></i>{esc(n)}<em>{esc(d)}</em></span>' for n, c, d in TIERS)
    return f'<div class="mmapwrap">{"".join(parts)}</div><div class="mlegend">{legend}</div>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", required=True)
    ap.add_argument("--analysis", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    scan = json.load(open(a.scan, encoding="utf-8"))
    ana = json.load(open(a.analysis, encoding="utf-8"))
    if ana.get("scan_run_id") != scan.get("run_id"):
        sys.exit("scan_run_id 不匹配，拒绝渲染")
    m = scan.get("metrics", {})
    fams = scan.get("families", [])
    sessions = scan.get("sessions", [])
    evidence = scan.get("evidence", [])
    wfs = {w["id"]: w for w in ana.get("workflows", [])}
    sops = {s["id"]: s for s in ana.get("sops", [])}
    ev = {e["ref"]: e for e in evidence}

    ai_acts, skill_use = Counter(), Counter()
    for f in fams:
        ai_acts.update(f.get("ai_actions", {}))
        skill_use.update(f.get("skills", {}))
    work_fams = [f for f in fams if f["family"] not in ("个人事务", "定时任务与资讯", "其他")]
    fam_total = sum(f["sessions"] for f in work_fams) or 1
    day = Counter(s["date"] for s in sessions)
    busiest = day.most_common(1)[0] if day else ("—", 0)
    longest = max(sessions, key=lambda s: s.get("turns", 0), default=None)
    top_fam = max(work_fams, key=lambda f: f["sessions"], default=None)
    judgments = sum(1 for e in evidence if e.get("judgment"))

    fam_sessions = {f["family"]: f["sessions"] for f in fams}
    sop_freq = {sid: fam_sessions.get(SOP_FAMILY.get(sid, ""), 0) for sid in sops}
    pri = {"先做": 0, "下一批": 1, "观察": 2}
    sop_rank = {sid: i + 1 for i, sid in enumerate(sorted(
        sops, key=lambda s: (-sop_freq.get(s, 0),
                             pri.get(next((o.get("priority") for o in ana.get("opportunities", []) if o.get("sop_id") == s), "观察"), 3),
                             s)))}
    ranked = sorted(sop_rank, key=lambda x: sop_rank[x])
    top5, rest = ranked[:5], ranked[5:]
    fam_sops = {}
    for sid, fn in SOP_FAMILY.items():
        if sid in sops:
            fam_sops.setdefault(fn, []).append(sid)

    # ---------------- 01 数据回顾
    def stat(num, unit, label, note=""):
        return (f'<div class="stat"><div class="num">{esc(num)}<small>{esc(unit)}</small></div>'
                f'<div class="slab">{esc(label)}</div><div class="snote">{esc(note)}</div></div>')

    share = "".join(
        f'<div class="shrow"><div class="shname">{esc(f["family"])}</div>'
        f'<div class="shbar"><div class="shfill" style="width:{100 * f["sessions"] / fam_total:.1f}%"></div></div>'
        f'<div class="shval">{f["sessions"]}</div></div>' for f in sorted(work_fams, key=lambda x: -x["sessions"])[:7])

    p1 = f'''
<section class="pg" id="pg1">
 <div class="pmeta"><span>PERSONAL FDE × WORKBUDDY RECAP</span><span>01 / 06</span></div>
 <h1 class="bigtitle">你的 AI 协作<br>半年回顾<span class="chev">&gt;</span></h1>
 <p class="lead">{esc(scan.get("scope", {}).get("from"))} → {esc(scan.get("scope", {}).get("to"))}　·　全部工作区　·　本机日志只读统计</p>
 <div class="statgrid">
  {stat(m.get("work_sessions"), " 个任务", "交给工作搭子的任务", f"覆盖 {m.get('workspaces')} 个工作区")}
  {stat(m.get("user_turns"), " 轮", "人机对话轮次", f"AI 活动约 {m.get('ai_hours')} h（非工时口径）")}
  {stat(ai_acts.get("生成产出", 0), " 次", "AI 生成产出", f"检索调研 {ai_acts.get('检索调研', 0)} 次")}
  {stat(m.get("automation_sessions"), " 次运行", "定时任务自动跑", "资讯与周报类")}
 </div>
 <div class="cols2">
  <div><div class="slab2">时间花在哪</div>{share}
   <p class="fun">头号场景：<b>{esc(top_fam["family"]) if top_fam else "—"}</b>（{top_fam["sessions"] if top_fam else 0} 个任务）</p></div>
  <div><div class="slab2">值得记住的数字</div>
   <ul class="facts">
    <li><b>{judgments}</b> 次关键判断由你拍板——口径、关系、承诺，AI 替不了</li>
    <li><b>{len(scan.get('corrections', []))}</b> 次返工候选，集中在事实对齐与格式口径</li>
    <li><b>{m.get('sessions_compacted')}</b> 个长会话被压缩过，长任务记得收尾交接</li>
    <li>最忙一天：<b>{esc(busiest[0])}</b>（{busiest[1]} 个任务）</li>
    <li>最长单任务：<b>{longest["turns"] if longest else 0} 轮</b>{esc("｜" + longest["title"][:16] if longest else "")}</li>
    <li>最常用入口：<b>{esc(skill_use.most_common(1)[0][0])}</b>（{skill_use.most_common(1)[0][1]} 次）</li>
   </ul>
   <p class="fine">口径：分类与纠错为规则候选；间隔时长≠工时；后续无纠错≠验收通过。个人事务明细已隐藏。</p>
  </div>
 </div>
</section>'''

    # ---------------- 02 工作全景（思维导图）
    habits = [
        (m.get("first_goal"), "%", "开场说清目标", "四分之一的任务一开始就讲清要什么"),
        (m.get("first_context"), "%", "开场带上下文", "过半任务给了材料或参考，习惯好"),
        (m.get("first_constraint"), "%", "开场带验收约束", "还偏低——标准前置能省最多返工"),
        (judgments, " 次", "你拍板的判断", "口径、关系、承诺，最该保留的时间"),
        (m.get("sessions_compacted"), " 个", "被压缩的长会话", "长任务收尾交接，下轮不用重讲"),
    ]
    habit_html = "".join(
        f'<div class="hchip"><div class="hnum">{esc(v)}<small>{esc(u)}</small></div>'
        f'<div class="hlab">{esc(k)}</div><div class="hnote">{esc(note)}</div></div>'
        for v, u, k, note in habits)

    ladder = "".join(
        f'<button class="lchip" onclick="jumpPrompt(\'{esc(SOP_PAGE[sid])}\')">'
        f'<span class="lnum">{sop_rank[sid]}</span>{esc(sid)}'
        f'<em>{esc(cut(sops[sid].get("title"), 12))} · {sop_freq[sid]} 任务</em></button>'
        for sid in top5)
    ladder_more = "".join(
        f'<button class="lchip" onclick="jumpPrompt(\'{esc(SOP_PAGE[sid])}\')">'
        f'<span class="lnum alt">+</span>{esc(sid)}<em>{esc(cut(sops[sid].get("title"), 12))} · {sop_freq[sid]} 任务</em></button>'
        for sid in rest)

    p2 = f'''
<section class="pg" id="pg2">
 <div class="pmeta"><span>你的工作全景 · 习惯 × 板块 × 深化路径</span><span>02 / 06</span></div>
 <h2 class="ptitle"><span class="chev">&gt;</span>你的工作全景</h2>
 <p class="lead">一张图看清：你的工作分哪几个板块、各板块走到哪一步、SOP 该落在哪。</p>
 <div class="slab2">使用习惯画像</div>
 <div class="habitgrid">{habit_html}</div>
 <div class="slab2" style="margin-top:22px">板块脉络图</div>
 {mindmap(work_fams, fam_sops, sop_rank, m.get("work_sessions"))}
 <div class="slab2" style="margin-top:20px">SOP 频率榜（按使用频率，先给前 5）</div>
 <div class="ladder">{ladder}
  {f'<details class="more"><summary>+{len(rest)} 个频率较低，展开</summary><div class="ladder in">{ladder_more}</div></details>' if rest else ''}
 </div>
 <p class="fine">层级为启发判断：对外占比≥60% → 判断密集；Skill 覆盖&lt;45% → 可深度自动化；纠错候选率≥8% → 协作加深；其余稳步推进。</p>
</section>'''

    # ---------------- 03-06 建议 1-4
    def flow_block(wf_id, label):
        w = wfs[wf_id]
        cur = [(s["step"], s.get("friction") or s.get("observed") or "", "", bool(s.get("friction"))) for s in w.get("current_steps", [])]
        opt = [(s["step"], s.get("output") or "", s.get("owner", "协作"), False) for s in w.get("optimized_steps", [])]
        refs = list(dict.fromkeys(r for s in w.get("current_steps", []) for r in s.get("evidence_refs", [])))[:3]
        chips = "".join(
            f'<span class="evchip"><b>{esc(r)}</b>{esc(cut(ev[r]["quote"], 34))}</span>' for r in refs if r in ev)
        opp_acc = {o.get("id"): o.get("acceptance", []) for o in ana.get("opportunities", [])}
        acc = list(dict.fromkeys(x for s in w.get("optimized_steps", [])
                                 for o in s.get("opportunity_ids", [])
                                 for x in opp_acc.get(o, [])))[:3]
        return f'''
  <div class="flowcard">
   <div class="flowname">{esc(label)}</div>
   <div class="flowlabel">现在怎么跑</div>{flow_svg(cur, colored=False)}
   <div class="flowlabel to">优化后这么走</div>{flow_svg(opt, colored=True)}
   <div class="flowfoot">
     <div class="chips">{chips}</div>
     <div class="accs">{"".join(f"<span class=acc>✓ {esc(x)}</span>" for x in acc)}</div>
   </div>
  </div>'''

    def advice_page(num):
        cfg = ADVICE[num]
        pgid = f"pg{num + 2}"
        blocks = "".join(flow_block(wid, lab) for wid, lab in cfg["flows"])
        wf_ids = [x[0] for x in cfg["flows"]]
        firsts = [o for o in ana.get("opportunities", [])
                  if o.get("priority") == "先做" and o.get("workflow_id") in wf_ids]
        sop_ids = list(dict.fromkeys(o["sop_id"] for o in ana.get("opportunities", []) if o.get("workflow_id") in wf_ids))
        prompts = "\n\n".join(f"【{sid}】{sops[sid].get('copy_prompt')}" for sid in sop_ids if sid in sops)
        why = "".join(
            f'<p class="whyline"><b>{esc(sid)}</b>　{esc(SOP_LOGIC.get(sid, ""))}</p>'
            for sid in sop_ids if sid in SOP_LOGIC)
        return f'''
<section class="pg" id="{pgid}">
 <div class="pmeta"><span>建议 {num} / 4 · 本条即 SOP</span><span>0{num + 2} / 06</span></div>
 <h2 class="ptitle"><span class="pnum">{num}</span>{esc(cfg["title"])}</h2>
 <p class="lead">{esc(cfg["lead"])}</p>
 <div class="legend"><span><i class="lg lg-ai"></i>AI 执行</span><span><i class="lg lg-co"></i>人机协作</span><span><i class="lg lg-hu"></i>人工判断</span><span class="lg-note">灰=现在的跑法，红色 ! = 卡过壳的地方</span></div>
 {blocks}
 <div class="dobar"><b>本周就做：</b>{esc(firsts[0].get("first_action") if firsts else "按启动指令试跑一个真实任务")}</div>
 <div class="promptbox" id="pp-a{num}"><span class="lbl">启动指令（填好材料即可粘贴）</span>
   <pre>{esc(prompts)}</pre><button class="cp" onclick="copyPre(this)">复制</button>
   <div class="why"><span class="lbl">背后的逻辑 · 它在培养什么习惯</span>{why}</div></div>
</section>'''

    pages = [p1, p2] + [advice_page(i) for i in (1, 2, 3, 4)]

    # 建议 4 附加边界速查 + 试运行
    bmap = {b.get("mode"): b for b in ana.get("boundary_rules", [])}
    def blist(mode):
        return "；".join(bmap.get(mode, {}).get("conditions", []))
    pages[5] = pages[5].replace(
        "</section>",
        f'''<div class="cols2" style="margin-top:24px">
 <div><div class="slab2">人机边界速查</div>
  <div class="brow"><b class="t-ai">AI</b><p>{esc(blist("AI"))}</p></div>
  <div class="brow"><b class="t-co">协作</b><p>{esc(blist("协作"))}</p></div>
  <div class="brow"><b class="t-hu">人</b><p>{esc(blist("人"))}</p></div>
 </div>
 <div><div class="slab2">两周试运行</div>
  <ul class="facts">
   <li><b>第 1 周</b>：邮件准备包、材料对照各跑 3 个真实任务，记录补信息次数与返工</li>
   <li><b>第 2 周</b>：活动事实表跑 1 场多物料，验证改动一次、全量同步</li>
   <li>出现未授权外发或错改正式文件，立即停止并修规则</li>
  </ul>
  <div class="hardsm">AI 产出未经人验收，不得外发。</div>
 </div>
</div></section>''')

    open(a.out, "w", encoding="utf-8").write(wrap(pages, scan))
    print(f"REVIEW_OK\t{a.out}")


CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--tx:#0052D9;--txd:#003BA3;--txl:#E6EEFB;--ink:#0B0B0F;--mut:#6E6E76;--line:#E4E4EA;--cy:#00A9CE;--or:#FF7D00}
html{scroll-behavior:smooth}
body{background:#fff;color:var(--ink);font-family:"Helvetica Neue",Helvetica,-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;-webkit-font-smoothing:antialiased}
.pg{min-height:100vh;padding:6vh 6.5vw 8vh;border-bottom:1px solid var(--line);display:flex;flex-direction:column}
.pmeta{display:flex;justify-content:space-between;font-size:12px;letter-spacing:.22em;color:var(--mut);text-transform:uppercase;margin-bottom:5vh}
.bigtitle,.ptitle{font-family:"腾讯体 W7","TencentSansW7","Helvetica Neue",Helvetica,"PingFang SC",sans-serif}
.bigtitle{font-size:clamp(44px,7vw,92px);line-height:1.04;font-weight:800;letter-spacing:.01em}
.ptitle{font-size:clamp(30px,4.4vw,56px);font-weight:800;line-height:1.1;display:flex;align-items:baseline;gap:18px}
.pnum{font-size:clamp(48px,5.6vw,80px);font-weight:800;color:var(--tx);line-height:1;flex:none}
.chev{color:var(--tx)}
.lead{margin-top:14px;font-size:16.5px;color:var(--mut);max-width:64ch}
.statgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:2vw;margin:5vh 0}
.stat .num{font-size:clamp(38px,4.4vw,68px);font-weight:800;letter-spacing:-.02em;line-height:1;
 background:linear-gradient(120deg,var(--ink) 25%,var(--tx));-webkit-background-clip:text;background-clip:text;color:transparent}
.stat .num small{font-size:.32em;font-weight:700;color:var(--mut);-webkit-text-fill-color:var(--mut)}
.slab{font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:var(--tx);font-weight:700;margin-top:10px}
.slab2{font-size:12px;letter-spacing:.18em;text-transform:uppercase;font-weight:800;border-bottom:2px solid var(--ink);display:inline-block;padding-bottom:5px;margin-bottom:14px}
.snote{font-size:12.5px;color:var(--mut);margin-top:5px}
.cols2{display:grid;grid-template-columns:1.12fr 1fr;gap:4vw}
.shrow{display:grid;grid-template-columns:118px 1fr 38px;align-items:center;gap:12px;padding:7px 0;border-bottom:1px solid var(--line)}
.shname{font-size:14px;font-weight:600}
.shbar{height:8px;background:#F0F2F6;border-radius:99px;overflow:hidden}
.shfill{height:100%;background:linear-gradient(90deg,var(--tx),#3D7BE8);border-radius:99px}
.shval{font-weight:800;font-size:15px;text-align:right}
.facts{list-style:none}
.facts li{padding:9px 0;border-bottom:1px solid var(--line);font-size:15px}
.facts li b{font-size:19px;color:var(--txd)}
.fun{margin-top:14px;font-size:14px;color:var(--mut)}
.fine{margin-top:12px;font-size:11.5px;color:#9B9BA3;max-width:70ch}
.habitgrid{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}
.hchip{border:1px solid var(--line);border-radius:12px;padding:12px 14px;background:#FCFCFE}
.hnum{font-size:30px;font-weight:800;color:var(--txd)}
.hnum small{font-size:13px;color:var(--mut);font-weight:700}
.hlab{font-size:12px;font-weight:800;letter-spacing:.08em;margin-top:2px}
.hnote{font-size:11.5px;color:var(--mut);margin-top:5px;line-height:1.5}
.mmapwrap{overflow-x:auto;border:1px solid var(--line);border-radius:14px;padding:18px 10px;background:linear-gradient(180deg,#FCFDFF,#FAFBFD)}
.mmap{display:block;min-width:980px;width:100%}
.mlegend{display:flex;flex-wrap:wrap;gap:10px 22px;margin-top:10px;font-size:12.5px;color:var(--ink)}
.mlegend .lg{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.mlegend em{font-style:normal;color:var(--mut);margin-left:6px;font-size:11.5px}
.ladder{display:flex;flex-wrap:wrap;gap:10px}
.ladder.in{margin-top:10px}
.lchip{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--line);background:#fff;border-radius:10px;padding:8px 14px;cursor:pointer;font-size:13px}
.lchip:hover{border-color:var(--tx)}
.lnum{width:22px;height:22px;border-radius:7px;background:var(--tx);color:#fff;font-weight:800;font-size:12.5px;display:inline-flex;align-items:center;justify-content:center}
.lnum.alt{background:#B9C4D6}
.lchip em{font-style:normal;color:var(--mut);font-size:12px}
.more{flex-basis:100%}
.more summary{cursor:pointer;font-weight:700;font-size:13px;color:var(--txd)}
.legend{display:flex;gap:18px;align-items:center;margin:12px 0 6px;font-size:12.5px;color:var(--mut)}
.lg{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.lg-ai{background:var(--tx)}.lg-co{background:var(--cy)}.lg-hu{background:var(--or)}
.lg-note{margin-left:auto;font-size:11.5px}
.flowcard{border:1px solid var(--line);border-radius:14px;padding:16px 20px;margin:14px 0}
.flowname{font-weight:800;font-size:15.5px;margin-bottom:10px}
.flowlabel{font-size:11px;letter-spacing:.16em;color:var(--mut);font-weight:700;margin:10px 0 6px}
.flowlabel.to{color:var(--tx)}
.flowwrap{overflow-x:auto;padding-bottom:2px}
.flow{display:block;min-width:560px}
.flowfoot{display:flex;gap:16px;align-items:flex-start;margin-top:10px;flex-wrap:wrap}
.chips{display:flex;gap:8px;flex-wrap:wrap;flex:1}
.evchip{border:1px solid var(--line);border-left:3px solid var(--tx);border-radius:7px;padding:5px 10px;font-size:12px;color:#33333B;background:#FBFCFE}
.evchip b{color:var(--txd);margin-right:6px}
.accs{display:flex;flex-direction:column;gap:4px;min-width:230px}
.acc{font-size:12.5px;color:var(--txd);font-weight:700}
.dobar{margin:16px 0 10px;background:var(--txl);border-radius:10px;padding:12px 16px;font-size:14px}
.promptbox{background:var(--ink);border-radius:12px;padding:14px 16px;position:relative}
.promptbox .lbl{color:#9DB6E4;font-size:11px;letter-spacing:.16em;text-transform:uppercase}
.promptbox pre{white-space:pre-wrap;color:#EDEDF2;font-size:12.5px;margin-top:8px;padding-right:64px;line-height:1.6;font-family:inherit}
.cp{position:absolute;right:12px;top:12px;border:0;background:var(--tx);color:#fff;border-radius:6px;padding:5px 12px;font-size:12px;cursor:pointer}
.why{margin-top:12px;border-top:1px dashed #3A4A63;padding-top:10px}
.why .lbl{color:#9DB6E4}
.whyline{font-size:12.5px;color:#C9D4E6;margin-top:6px;line-height:1.6}
.whyline b{color:#fff;background:#1D3A6B;border-radius:5px;padding:1px 7px;margin-right:4px}
.brow{display:flex;gap:14px;padding:8px 0;border-bottom:1px solid var(--line);align-items:baseline}
.brow b{min-width:52px;font-size:13px}
.brow p{font-size:13.5px;color:#33333B}
.t-ai{color:var(--tx)}.t-co{color:var(--cy)}.t-hu{color:var(--or)}
.hardsm{margin-top:14px;display:inline-block;background:var(--ink);color:#fff;font-weight:800;padding:8px 16px;border-radius:8px;font-size:14px}
.navdots{position:fixed;right:18px;top:50%;transform:translateY(-50%);display:flex;flex-direction:column;gap:10px;z-index:9}
.navdots a{width:9px;height:9px;border-radius:99px;background:#CFCFD6;display:block}
.navdots a.on{background:var(--tx)}
footer{padding:26px 6.5vw;font-size:11px;color:#9B9BA3;border-top:1px solid var(--line)}
@media(max-width:960px){.statgrid{grid-template-columns:1fr 1fr}.cols2{grid-template-columns:1fr}.habitgrid{grid-template-columns:1fr 1fr}.ptitle{gap:10px}}
@media print{.navdots{display:none}.pg{page-break-after:always;min-height:auto}.promptbox pre{white-space:pre-wrap}}
"""

JS = """
document.querySelectorAll('.navdots a').forEach(function(a){a.addEventListener('click',function(e){e.preventDefault();var t=document.querySelector(a.getAttribute('href'));if(t)t.scrollIntoView({behavior:'smooth'});});});
var secs=[].slice.call(document.querySelectorAll('.pg'));var dots=[].slice.call(document.querySelectorAll('.navdots a'));
window.addEventListener('scroll',function(){var y=window.scrollY+window.innerHeight/3,k=0;secs.forEach(function(s,i){if(s.offsetTop<=y)k=i;});dots.forEach(function(d,i){d.className=i===k?'on':'';});});
function jumpPrompt(id){var el=document.getElementById(id);if(!el)return;var d=el.closest('details');if(d)d.open=true;setTimeout(function(){el.scrollIntoView({behavior:'smooth',block:'center'});el.style.boxShadow='0 0 0 3px #0052D9';setTimeout(function(){el.style.boxShadow='';},1600);},80);}
function copyPre(b){var t=b.parentNode.querySelector('pre').innerText;function done(){b.innerText='已复制';setTimeout(function(){b.innerText='复制';},1500);}function fb(){var n=document.createElement('textarea');n.value=t;document.body.appendChild(n);n.select();document.execCommand('copy');document.body.removeChild(n);done();}if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(done,fb);}else fb();}
"""


def wrap(pages, scan):
    dots = "".join(f'<a href="#pg{i+1}" class="{"on" if i == 0 else ""}"></a>' for i in range(len(pages)))
    return (f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>AI 协作回顾与行动建议｜{esc(scan.get("run_id", ""))}</title><style>{CSS}</style></head><body>'
            f'<nav class="navdots">{dots}</nav>' + "".join(pages) +
            f'<footer>PERSONAL FDE × WORKBUDDY · run {esc(scan.get("run_id", ""))} · 数据只读本机日志 · 分类与纠错为规则候选 · 建议与启动指令均为草案·未试运行</footer>'
            f'<script>{JS}</script></body></html>')


if __name__ == "__main__":
    main()
