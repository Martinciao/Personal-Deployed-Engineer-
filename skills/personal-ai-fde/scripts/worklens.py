#!/usr/bin/env python3
"""
personal-ai-fde v1.0.0 工作拆解层：把会话归到工作类型，拆出工作环节，统计人机分工信号，
对比历史扫描，并生成完整扫描文档（Markdown + JSON）与给模型读的分析摘要。

由 parse_sessions.py scan 调用；也可单独 import。只读日志，不联网。
"""
import glob, json, os, re, time
from collections import Counter, defaultdict
from datetime import datetime

import parse_sessions as P

SCAN_SCHEMA = "3.1"
METRIC_VERSION = "3.0"
PERSONAL = "个人事务"
AUTOMATION = "定时任务与资讯"
OTHER = "其他"

# ---------------------------------------------------------------- 工作类型（通用知识工作，可用 --taxonomy 覆盖）
TAXONOMY = [
    {"name": "会议与活动筹备",
     "strong": r"会议|议程|agenda|纪要|谈参|主持|致辞|接待|研讨会|workshop|座位|日程单|参会|来访|沙龙|峰会|黑客松|hackathon|demo ?day|晚宴|开场白",
     "weak": r"活动|meeting|brief|日程|嘉宾|会谈|会面|共创营",
     "skills": r"meeting|brief|hosting|agenda|event|活动"},
    {"name": "邮件与消息沟通",
     "strong": r"邮件|email|e-mail|回信|回邮件|thread|抄送|发件|收件|跟进信",
     "weak": r"回复|跟进|话术|消息|发给|draft|催",
     "skills": r"email|mail"},
    {"name": "演示文稿",
     "strong": r"\bppt\b|pptx|slides?|幻灯片|\bdeck\b|一客一档|演示文稿",
     "weak": r"演示|讲稿|演讲|ppt",
     "skills": r"ppt|slide|deck|partner-profile", "exts": r"pptx"},
    {"name": "翻译与润色",
     "strong": r"翻译|translate|英文版|中文版|润色|polish|de-?ai|去 ?ai ?味",
     "weak": r"改写|用英文|中英",
     "skills": r"translat"},
    {"name": "数据与表格",
     "strong": r"excel|xlsx|csv|表格|台账|数据清洗|透视|名单",
     "weak": r"数据|统计|填写|表单",
     "skills": r"xlsx|excel|sheet", "exts": r"xlsx|csv"},
    {"name": "网页与工具搭建",
     "strong": r"网页|html|看板|dashboard|工作台|小游戏|网站|小程序|海报|视频|web ?app",
     "weak": r"游戏|应用|页面|工具|图片|logo|动画",
     "skills": r"web|frontend|dashboard|game|page|video|image"},
    {"name": PERSONAL,
     "strong": r"个税|社保|公积金|强积金|\bmpf\b|薪酬|租房|买房|旅行|旅游|酒店|机票|里程|miles|八字|命盘|情感|恋爱|女友|男友|异地恋|聊天记录|简历|\bcv\b|求职|理财|股票|基金|纳指|\bqqq\b|签证|小账本|打工人|周末|体检",
     "weak": r"个人|生活|家人|入职|福利",
     "skills": r"relationship|resume"},
    {"name": "AI 工作流与 Skill 搭建",
     "strong": r"\bskills?\b|技能|工作流|\bsop\b|定时任务|自动化|智能体|\bmcp\b|连接器|提示词|prompt|workbuddy.{0,8}(设置|配置|权限|怎么用|功能)",
     "weak": r"agent|记忆|规则|模板化",
     "skills": r"skill-creator|find-skills|skill-manage|skills-sec|expert-manager"},
    {"name": "文档与汇报写作",
     "strong": r"周报|月报|汇报|复盘报告|述职|答辩|docx|\bword\b|协议|合同|文案|pr稿|新闻稿|备忘录|白皮书",
     "weak": r"总结|文档|方案|报告|撰写|起草|简介|说明",
     "skills": r"docx|word|weekly|report", "exts": r"docx"},
    {"name": "调研与分析",
     "strong": r"调研|竞品|研究|调查|landscape|research",
     "weak": r"分析|对比|梳理|了解|评估|盘点|扫描|趋势|格局|介绍|背景|是什么|哪些|怎么样",
     "skills": r"search|research|finance|neodata|westock"},
]
SKILL_TAG_RE = re.compile(r"@skill:[\w\-]+|@\"[^\"]+\"|@/\S+|https?://\S+", re.I)

PHASES = ["布置任务", "补充材料", "追加需求", "讨论追问", "内容返工", "排版返工", "核对校验", "翻译润色", "交付存档"]
PHASE_SHORT = {"布置任务": "布置", "补充材料": "补充", "追加需求": "追加", "讨论追问": "讨论", "内容返工": "返工",
               "排版返工": "排版返工", "核对校验": "核对", "翻译润色": "翻译", "交付存档": "交付"}
REWORK = {"内容返工", "排版返工"}
ACT_LABEL = {"research": "检索调研", "read": "读取材料", "produce": "生成产出", "deliver": "交付/发布", "run": "运行命令",
             "skill": "调用 Skill", "plan": "任务规划", "delegate": "子代理", "ask": "向人提问"}


def load_taxonomy(path=None):
    tax = [dict(t) for t in TAXONOMY]
    overrides = {}
    if path and os.path.exists(path):
        cfg = json.load(open(path, encoding="utf-8"))
        if cfg.get("families"):
            tax = cfg["families"] + [t for t in tax if t["name"] not in {f["name"] for f in cfg["families"]}]
        overrides = cfg.get("override", {})
    for t in tax:
        for k in ("strong", "weak", "skills", "exts"):
            t[k + "_re"] = re.compile(t[k], re.I) if t.get(k) else None
    return tax, overrides


def classify_family(s, tax, overrides):
    for k, v in overrides.items():
        if s["id"].startswith(k):
            return v
    if s["kind"] == "automation":
        return AUTOMATION
    title = SKILL_TAG_RE.sub(" ", s.get("title") or "")
    first = " ".join(SKILL_TAG_RE.sub(" ", t["own"]) for t in s["turns"][:1])
    rest = " ".join(SKILL_TAG_RE.sub(" ", t["own"]) for t in s["turns"][1:4])
    best, best_score = OTHER, 0
    for t in tax:
        sc = 0
        for text, w in ((title, 3), (first, 2), (rest, 0.5)):
            if t["strong_re"]:
                sc += w * 1.0 * min(len(t["strong_re"].findall(text)), 2)
            if t["weak_re"]:
                sc += w * 0.35 * min(len(t["weak_re"].findall(text)), 2)
        if t["skills_re"]:
            sc += 2.5 * sum(1 for k in s["skills"] if t["skills_re"].search(k))
        if t.get("exts_re"):
            sc += 1.5 * sum(1 for e in s["exts"] if t["exts_re"].fullmatch(e))
        if sc > best_score:
            best, best_score = t["name"], sc
    return best if best_score >= 1.2 else OTHER


def session_path(s):
    toks = []
    for t in s["turns"]:
        toks.append(PHASE_SHORT[t["phase"]])
        a = t["acts"]
        if a.get("research", 0) >= 2:
            toks.append("调研")
        if a.get("produce", 0) >= 1:
            toks.append("生成")
        if a.get("deliver", 0) >= 1:
            toks.append("交付")
    merged = []
    for x in toks:
        if not merged or merged[-1] != x:
            merged.append(x)
    loops = sum(1 for t in s["turns"] if t["phase"] in REWORK)
    skel = []
    for x in merged:
        if x not in skel:
            skel.append(x)
    return "→".join(skel) + (f"（返工 {loops} 轮）" if loops else ""), merged


def first_pass(s):
    """首稿是否一次通过：第一次出现生成产出之后，本会话再无强纠错。"""
    idx = next((i for i, t in enumerate(s["turns"]) if t["acts"].get("produce")), None)
    if idx is None:
        return None
    return not any(P.strong(t) for t in s["turns"][idx + 1:])


def masked_title(s, show_personal=False):
    if s["family"] == PERSONAL and not show_personal:
        return "（个人事务，标题已隐藏）"
    return P.oneline(P.redact(s["title"]), 40)


# ---------------------------------------------------------------- 资产盘点（只列名称）
def inventory(sel):
    skills_dir = os.path.join(P.WB_HOME, "skills")
    skills = sorted(d for d in os.listdir(skills_dir) if os.path.isfile(os.path.join(skills_dir, d, "SKILL.md"))) \
        if os.path.isdir(skills_dir) else []
    sops = []
    for f in glob.glob(os.path.join(P.WB_HOME, "*sop*.md")) + glob.glob(os.path.join(P.WB_HOME, "*SOP*.md")):
        sops.append({"name": os.path.basename(f), "where": "用户级"})
    for cwd in sorted({s["cwd"] for s in sel if s["cwd"] and os.path.isdir(s["cwd"])}):
        try:
            for f in os.listdir(cwd):
                if re.match(r"sop", f, re.I) and f.lower().endswith(".md"):
                    sops.append({"name": f, "where": os.path.basename(cwd)})
            sd = os.path.join(cwd, "sop")
            if os.path.isdir(sd):
                for f in os.listdir(sd):
                    if f.lower().endswith(".md"):
                        sops.append({"name": f, "where": os.path.basename(cwd) + "/sop"})
        except Exception:
            continue
    seen, uniq = set(), []
    for x in sops:
        if x["name"] not in seen:
            seen.add(x["name"]); uniq.append(x)
    autos = defaultdict(lambda: {"runs": 0, "last": 0, "title": ""})
    for s in sel:
        if s["kind"] == "automation":
            k = s["automation_id"] or s["title"][:20]
            a = autos[k]
            a["runs"] += 1
            if s["end"] > a["last"]:
                a["last"], a["title"] = s["end"], P.oneline(P.redact(s["title"].replace("[定时] ", "")), 40)
    autos = [{"title": v["title"], "runs": v["runs"], "last": time.strftime("%Y-%m-%d", time.localtime(v["last"] / 1000))}
             for v in sorted(autos.values(), key=lambda v: -v["runs"])]
    mem = glob.glob(os.path.join(P.WB_HOME, "user-*", "MEMORY.md"))
    return {"skills": skills, "sops": uniq, "automations": autos,
            "user_memory": mem[0] if mem else "", "user_memory_chars": len(open(mem[0], encoding="utf-8", errors="ignore").read()) if mem else 0}


def match_assets(fam, inv, tax):
    t = next((x for x in tax if x["name"] == fam), None)
    if not t:
        return {"skills": [], "sops": []}
    pats = [r for r in (t.get("strong_re"), t.get("skills_re")) if r]
    extra = {"邮件与消息沟通": r"邮件|email|mail", "会议与活动筹备": r"会议|纪要|活动|meeting|brief|hosting|agenda",
             "演示文稿": r"ppt|slide|deck|profile", "文档与汇报写作": r"周报|汇报|report|docx|word|de-ai|humanizer",
             "调研与分析": r"研究|调研|research|radar|雷达|fit|brief|analy", "数据与表格": r"xlsx|excel|sheet|名单",
             "网页与工具搭建": r"dashboard|web|html|page|看板", "翻译与润色": r"de-ai|humanizer|translat"}.get(fam)
    if extra:
        pats.append(re.compile(extra, re.I))
    hit = lambda name: any(p.search(name) for p in pats)
    return {"skills": [k for k in inv["skills"] if hit(k)][:8], "sops": [x["name"] for x in inv["sops"] if hit(x["name"])]}


# ---------------------------------------------------------------- 聚合
def family_stats(sessions, weeks, now_ms, tax, inv):
    by = defaultdict(list)
    for s in sessions:
        by[s["family"]].append(s)
    total_turns = sum(s["n_user"] for s in sessions) or 1
    total_human = sum(t["human_s"] for s in sessions for t in s["turns"]) or 1
    rows = []
    for fam, ss in by.items():
        turns = [t for s in ss for t in s["turns"]]
        follow = sum(max(s["n_user"] - 1, 0) for s in ss)
        strong_n = sum(P.n_strong(s) for s in ss)
        cats = Counter(c for t in turns for c in t["corr"] if c in P.STRONG_CATS)
        ph = {}
        for p in PHASES:
            pt = [t for t in turns if t["phase"] == p]
            if pt:
                ph[p] = {"turns": len(pt), "sessions": len({id(s) for s in ss for t in s["turns"] if t["phase"] == p}),
                         "human_min": round(sum(t["human_s"] for t in pt) / 60, 1),
                         "ai_min": round(sum(t["ai_s"] for t in pt) / 60, 1)}
        acts = Counter()
        for t in turns:
            acts.update(t["acts"])
        fps = [first_pass(s) for s in ss]
        fps = [x for x in fps if x is not None]
        paths = Counter(session_path(s)[0].split("（")[0] for s in ss)
        judge = [t for t in turns if t["judge"]]
        ext = sum(1 for s in ss if P.EXTERNAL_RE.search((s["title"] or "") + " " + (s["turns"][0]["own"] if s["turns"] else "")))
        recent = sum(1 for s in ss if s["end"] >= now_ms - 30 * 86400000)
        prior = sum(1 for s in ss if now_ms - 60 * 86400000 <= s["end"] < now_ms - 30 * 86400000)
        months = Counter(time.strftime("%Y-%m", time.localtime(s["end"] / 1000)) for s in ss)
        human_min = sum(t["human_s"] for t in turns) / 60
        ai_min = sum(t["ai_s"] for t in turns) / 60
        rows.append({
            "family": fam, "sessions": len(ss), "turns": len(turns), "turn_share": P.pct(len(turns), total_turns),
            "human_hours": round(human_min / 60, 1), "ai_hours": round(ai_min / 60, 1),
            "human_share": P.pct(human_min * 60, total_human),
            "per_week": round(len(ss) / weeks, 1), "avg_turns": round(len(turns) / len(ss), 1) if ss else 0,
            "recent30": recent, "prior30": prior, "months": dict(sorted(months.items())[-6:]),
            "last_active": time.strftime("%Y-%m-%d", time.localtime(max(s["end"] for s in ss) / 1000)),
            "correction_rate": P.pct(strong_n, follow), "corrections": strong_n, "correction_cats": dict(cats.most_common()),
            "first_pass_rate": P.pct(sum(fps), len(fps)) if fps else None, "first_pass_n": len(fps),
            "rework_turns_per_session": round(sum(1 for t in turns if t["phase"] in REWORK) / len(ss), 2),
            "judgment_turns": len(judge), "external_share": P.pct(ext, len(ss)),
            "rejections": sum(s["rejected"] for s in ss), "verify_asks": sum(1 for t in turns if t["phase"] == "核对校验"),
            "skill_share": P.pct(sum(1 for s in ss if s["skills"]), len(ss)),
            "skills": dict(sum((s["skills"] for s in ss), Counter()).most_common(6)),
            "exts": dict(sum((s["exts"] for s in ss), Counter()).most_common(5)),
            "phases": ph, "ai_actions": {ACT_LABEL.get(k, k): v for k, v in acts.most_common(6)},
            "paths": [{"path": k, "n": v} for k, v in paths.most_common(3)],
            "assets": match_assets(fam, inv, tax),
            "_sessions": ss,
        })
    rows.sort(key=lambda r: (r["family"] in (PERSONAL, AUTOMATION, OTHER), -r["human_hours"], -r["sessions"]))
    return rows


def title_clusters(sessions, min_n=3):
    """按标题关键片段聚出重复任务（如「一客一档」×6），供 Skill 化 / 定时化判断。"""
    grams = defaultdict(set)
    for s in sessions:
        if s["family"] in (PERSONAL,) or s["kind"] == "automation":
            continue
        t = SKILL_TAG_RE.sub(" ", s["title"] or "")
        for seg in re.findall(r"[\u4e00-\u9fa5A-Za-z]{2,}", t):
            seg = seg.lower()
            for n in (2, 3, 4, 5):
                for i in range(len(seg) - n + 1):
                    grams[seg[i:i + n]].add(s["id"])
    stop = set("帮我 生成 分析 进行 以及 相关 关于 如何 什么 一个 一份 整理 梳理 查看 了解 询问 调研 制作 撰写 优化 设计 搭建 评估 研究 对比 总结 介绍 读取 文档 内容 方案 问题 情况 合作 腾讯 腾讯云 the and for".split())
    cands = [(g, ids) for g, ids in grams.items() if len(ids) >= min_n and g not in stop and not g.isdigit()]
    cands.sort(key=lambda x: (-len(x[1]), -len(x[0])))
    kept = []
    for g, ids in cands:
        if any(g in k and ids <= kid for k, kid in kept):
            continue
        if any(k in g and len(ids) >= len(kid) * 0.8 for k, kid in kept):
            kept = [(k, kid) for k, kid in kept if not (k in g)]
        kept.append((g, ids))
        if len(kept) >= 14:
            break
    idx = {s["id"]: s for s in sessions}
    out = []
    for g, ids in kept:
        ss = sorted((idx[i] for i in ids), key=lambda s: -s["end"])
        out.append({"key": g, "n": len(ids), "families": dict(Counter(s["family"] for s in ss).most_common(2)),
                    "examples": [P.oneline(P.redact(s["title"]), 28) for s in ss[:3]],
                    "last": time.strftime("%Y-%m-%d", time.localtime(ss[0]["end"] / 1000))})
    return out


# ---------------------------------------------------------------- 历史
def snapshot_dir(cache_dir):
    d = os.path.join(cache_dir, "scans") if cache_dir else None
    if d:
        os.makedirs(d, exist_ok=True)
    return d


def load_previous(cache_dir, scope_key, now_s, min_gap_h=20, legacy=None):
    """上一次同口径扫描：优先 v3 快照（至少间隔 min_gap_h 小时）；legacy 传入的旧版记录只作参考，不做环比。"""
    best = None
    d = snapshot_dir(cache_dir)
    for f in sorted(glob.glob(os.path.join(d, "scan-*.json"))) if d else []:
        try:
            x = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if x.get("scope_key") == scope_key and now_s - x.get("ts", 0) >= min_gap_h * 3600:
            best = x
    if best:
        return best
    if legacy:
        return {"date": legacy.get("date", ""), "ts": 0, "metrics": legacy.get("metrics", {}),
                "families": {}, "source": "v2", "reference_only": True}
    return None


def all_snapshots(cache_dir, scope_key):
    d = snapshot_dir(cache_dir)
    rows = []
    for f in sorted(glob.glob(os.path.join(d, "scan-*.json"))) if d else []:
        try:
            x = json.load(open(f, encoding="utf-8"))
            if x.get("scope_key") == scope_key:
                rows.append({"date": x["date"], "sessions": x["metrics"].get("sessions"),
                             "correction_rate": x["metrics"].get("correction_rate"),
                             "human_hours": x["metrics"].get("human_hours")})
        except Exception:
            continue
    return rows[-8:]


# ---------------------------------------------------------------- 主流程
def build_scan(sel, all_sessions, scope, agg, cache_dir, taxonomy=None, show_personal=False,
               legacy=None, coverage=None, run_id=""):
    tax, overrides = load_taxonomy(taxonomy)
    for s in sel:
        s["family"] = classify_family(s, tax, overrides)
        s["path"], _ = session_path(s)
    now_ms = time.time() * 1000
    span_days = max((scope["_to_ms"] - scope["_from_ms"]) / 86400000, 7)
    weeks = span_days / 7
    inv = inventory(sel)
    fams = family_stats(sel, weeks, now_ms, tax, inv)
    work = [s for s in sel if s["family"] not in (PERSONAL, AUTOMATION)]
    agg = dict(agg)
    agg["human_hours"] = round(sum(t["human_s"] for s in sel for t in s["turns"]) / 3600, 1)
    agg["ai_hours"] = round(sum(t["ai_s"] for s in sel for t in s["turns"]) / 3600, 1)
    fps = [x for x in (first_pass(s) for s in work) if x is not None]
    agg["first_pass_rate"] = P.pct(sum(fps), len(fps)) if fps else None
    agg["work_sessions"] = len(work)
    agg["personal_sessions"] = sum(1 for s in sel if s["family"] == PERSONAL)
    agg["judgment_turns"] = sum(1 for s in work for t in s["turns"] if t["judge"])
    scope_key = f"{scope.get('workspace')}|{scope.get('days')}"
    prev = load_previous(cache_dir, scope_key, time.time(), legacy=legacy)
    history = all_snapshots(cache_dir, scope_key)

    corrections, judgments, evidence = [], [], []
    seen_ref = set()
    for s in sel:
        if s["family"] == PERSONAL and not show_personal:
            continue
        for i, t in enumerate(s["turns"]):
            sid8 = s["id"][:8]
            is_corr = P.strong(t)
            is_judge = bool(t["judge"]) and s["family"] != AUTOMATION
            if not (is_corr or is_judge):
                continue
            ref = f"{sid8}#{i + 1}"
            if ref in seen_ref:
                continue
            seen_ref.add(ref)
            entry = {"ref": ref, "session_id": sid8, "date": time.strftime("%Y-%m-%d", time.localtime((t["ts"] or s["end"]) / 1000)),
                     "family": s["family"], "phase": t["phase"], "quote": P.oneline(P.redact(t["own"]), 200),
                     "judgment": is_judge,
                     "correction_categories": [c for c in t["corr"] if c in P.STRONG_CATS] if is_corr else []}
            evidence.append(entry)
            if is_corr:
                corrections.append(entry)
            if is_judge:
                judgments.append(entry)
    corrections.sort(key=lambda x: x["date"], reverse=True)

    sess_rows = []
    for s in sorted(sel, key=lambda s: -s["end"]):
        fp = first_pass(s)
        sess_rows.append({
            "id": s["id"][:8], "date": time.strftime("%Y-%m-%d", time.localtime(s["end"] / 1000)), "workspace": s["workspace"],
            "family": s["family"], "kind": s["kind"], "title": masked_title(s, show_personal), "turns": s["n_user"],
            "corrections": P.n_strong(s), "human_min": round(sum(t["human_s"] for t in s["turns"]) / 60, 1),
            "ai_min": round(sum(t["ai_s"] for t in s["turns"]) / 60, 1), "compactions": s["compactions"],
            "first_pass": fp, "skills": list(s["skills"].keys())[:4], "exts": list(s["exts"].keys())[:3],
            "path": s["path"] if (s["family"] != PERSONAL or show_personal) else "",
        })

    fam_out = []
    for r in fams:
        ss = r.pop("_sessions")
        deep = sorted((s for s in ss if s["kind"] == "interactive"), key=P.friction_score, reverse=True)
        typical = sorted((s for s in ss if s["kind"] == "interactive" and 3 <= s["n_user"] <= 25), key=lambda s: -s["end"])
        r["deep_dive"] = [s["id"][:8] for s in deep[:2]] + [s["id"][:8] for s in typical[:2] if s not in deep[:2]][:1]
        r["classification"] = "heuristic"
        r["judgment_examples"] = [j["quote"] for j in judgments if j["family"] == r["family"]][:4]
        r["correction_examples"] = [f"[{c['phase']}/{'/'.join(c['correction_categories'])}] {c['quote']}" for c in corrections if c["family"] == r["family"]][:4]
        pf = (prev or {}).get("families", {}).get(r["family"])
        r["prev"] = {k: pf.get(k) for k in ("sessions", "correction_rate", "first_pass_rate", "human_hours")} if pf else None
        fam_out.append(r)

    scan = {
        "schema": SCAN_SCHEMA, "version": P.VERSION, "metric_version": METRIC_VERSION,
        "run_id": run_id,
        "scope": {k: v for k, v in scope.items() if not k.startswith("_")}, "scope_key": scope_key,
        "coverage": coverage or {},
        "metrics": agg, "families": fam_out, "clusters": title_clusters(sel),
        "assets": {"skills_count": len(inv["skills"]), "sops": inv["sops"], "automations": inv["automations"],
                   "user_memory_chars": inv["user_memory_chars"], "user_memory_path": inv["user_memory"]},
        "workspaces": P.per_workspace(sel)[:20], "weekly": P.weekly(sel, 12),
        "evidence": evidence, "corrections": corrections, "judgments": judgments,
        "sessions": sess_rows,
        "previous": {"date": prev.get("date"), "metrics": prev.get("metrics", {}), "source": prev.get("source", "v3"),
                     "reference_only": bool(prev.get("reference_only"))} if prev else None,
        "history": history,
        "changes": build_changes(prev, agg, fam_out, now_ms),
        "notes": {"show_personal": show_personal,
                  "phase_rules": "布置=首轮；返工=强纠错（含排版字眼记为排版返工）；核对=要求验证/出处；翻译=翻译/中英；交付=保存/上传/发送；讨论=提问且无产出；补充=带附件或链接；其余为追加需求。所有归类为规则启发候选，仅供检索",
                  "time_rules": "AI 活动时长=本轮消息到本轮最后一条记录（非实际工时）；人侧间隔=上一轮 AI 活动结束到本轮消息，间隔超过 30 分钟视为离开不计。间隔时长不能当作工时或效率证据",
                  "first_pass_rule": "「末次产出后无强纠错」只表示之后没有再纠错，不代表验收通过",
                  "honesty": "纠错/判断均为正则候选，需语义复核；分类按标题与首轮文本启发，长会话可能含多个任务"},
    }
    return scan


def save_snapshot(scan, cache_dir):
    d = snapshot_dir(cache_dir)
    if not d:
        return None
    m = scan["metrics"]
    snap = {"date": time.strftime("%Y-%m-%d"), "ts": time.time(), "scope_key": scan["scope_key"],
            "metric_version": METRIC_VERSION,
            "metrics": {k: m.get(k) for k in ("sessions", "work_sessions", "user_turns", "human_hours", "ai_hours",
                                              "correction_rate", "first_pass_rate", "tool_fail_rate", "first_goal",
                                              "first_context", "sessions_compacted", "judgment_turns")},
            "families": {f["family"]: {k: f.get(k) for k in ("sessions", "correction_rate", "first_pass_rate", "human_hours", "per_week")}
                         for f in scan["families"]}}
    p = os.path.join(d, time.strftime("scan-%Y%m%d-%H%M%S.json"))
    json.dump(snap, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    return p



def build_changes(prev, agg, fams, now_ms):
    """与上次同口径快照的增量；可比性护栏：v3 快照 + 间隔>=20h + 同 metric_version。"""
    if not prev:
        return {"status": "首次扫描", "comparable": False, "notes": ["本次结果将作为基线"]}
    if prev.get("source") == "v2" or prev.get("reference_only"):
        return {"status": "历史为旧版参考", "comparable": False,
                "prev_date": prev.get("date"),
                "notes": ["旧版指标口径不同，仅作背景，不用于进步判定"]}
    gap_ok = (time.time() - (prev.get("ts") or 0)) >= 20 * 3600
    mv_ok = prev.get("metric_version", METRIC_VERSION) == METRIC_VERSION
    base = {"status": "同口径对比", "prev_date": prev.get("date"), "comparable": bool(gap_ok and mv_ok)}
    if not gap_ok:
        base["notes"] = ["距上次扫描不足 20 小时：视为同数据复跑/报告方法重跑，不判定进步"]
        return base
    if not mv_ok:
        base["notes"] = ["指标版本已变化，不能直接环比"]
        return base
    pm = prev.get("metrics", {})
    keys = ("work_sessions", "user_turns", "correction_rate", "first_goal", "first_context",
            "first_constraint", "judgment_turns", "tool_fail_rate", "sessions_compacted")
    base["deltas"] = {k: (round(agg.get(k, 0) - pm.get(k, 0), 1) if isinstance(agg.get(k), (int, float)) else None)
                      for k in keys if isinstance(agg.get(k), (int, float)) or isinstance(pm.get(k), (int, float))}
    pf = (prev.get("families") or {})
    base["family_deltas"] = [
        {"family": f["family"],
         "sessions": round(f["sessions"] - (pf.get(f["family"], {}) or {}).get("sessions", f["sessions"]), 1),
         "correction_rate": round(f["correction_rate"] - (pf.get(f["family"], {}) or {}).get("correction_rate", f["correction_rate"]), 1)}
        for f in fams if f["family"] in pf]
    base["notes"] = ["同口径增量才可视为进步；样本窗口不同（如 7 天 vs 30 天）不可比"]
    return base

# ---------------------------------------------------------------- 输出：完整扫描文档（Markdown）
def fmt_delta(cur, prev, unit=""):
    if prev is None or cur is None:
        return ""
    d = round(cur - prev, 1)
    return "（持平）" if d == 0 else f"（{'+' if d > 0 else ''}{d}{unit}）"


def write_record_md(scan, path):
    m, sc = scan["metrics"], scan["scope"]
    prev = scan.get("previous") or {}
    pm = prev.get("metrics", {})
    L = []
    A = L.append
    A(f"# 工作扫描记录｜{sc.get('workspace')}｜{sc.get('from')} → {sc.get('to')}")
    A("")
    A(f"> 生成于 {sc.get('generated')}｜personal-ai-fde v{scan['version']}｜数据源：本机 WorkBuddy 会话日志（只读）｜"
      f"引文已脱敏；个人事务{'已展示' if scan['notes']['show_personal'] else '只计数、不展示标题与原话'}")
    A("")
    A("## 0. 口径说明")
    A(f"- 工作环节：{scan['notes']['phase_rules']}")
    A(f"- 时长：{scan['notes']['time_rules']}")
    A("- 纠错候选率 = 强纠错候选轮次 ÷ 交互会话第 2 轮起的轮次；「末次产出后无强纠错」不代表验收通过")
    A("- 人工判断介入：用户在对话中给出口径、关系、承诺、授权、对外分寸等内容的候选轮次，需语义复核")
    A("- 人侧间隔与 AI 活动时长由消息时间差推算，不是实际工时，不得用于效率或收益结论")
    A("")
    A("## 1. 总览")
    rows = [("会话", m["sessions"], pm.get("sessions"), ""), ("其中工作会话", m.get("work_sessions"), pm.get("work_sessions"), ""),
            ("定时任务运行", m["automation_sessions"], None, ""), ("个人事务", m.get("personal_sessions"), None, ""),
            ("工作区", m["workspaces"], None, ""), ("用户轮次", m["user_turns"], pm.get("user_turns"), ""),
            ("人侧间隔 h（非工时）", m.get("human_hours"), pm.get("human_hours"), " h"), ("AI 活动时长 h", m.get("ai_hours"), pm.get("ai_hours"), " h"),
            ("纠错候选率 %", m["correction_rate"], pm.get("correction_rate"), " 个百分点"), ("末次产出后无强纠错占比 %（≠验收）", m.get("first_pass_rate"), pm.get("first_pass_rate"), " 个百分点"),
            ("工具失败率 %", m["tool_fail_rate"], pm.get("tool_fail_rate"), " 个百分点"), ("首条含目标 %", m["first_goal"], pm.get("first_goal"), " 个百分点"),
            ("被压缩的会话", m["sessions_compacted"], pm.get("sessions_compacted"), ""), ("人工判断介入轮次", m.get("judgment_turns"), pm.get("judgment_turns"), ""),
            ("沙箱拦截 / 用户拒绝", f"{m['sandbox_blocks']} / {m['user_rejections']}", None, "")]
    A("| 指标 | 本次 | 与上次对比 |\n|---|---|---|")
    for k, v, p, u in rows:
        A(f"| {k} | {v} | {fmt_delta(v, p, u) if isinstance(v, (int, float)) else ''} |")
    A("")
    A("## 2. 历史扫描记录")
    if prev:
        A(f"- 上次同口径扫描：{prev.get('date')}（来源 {prev.get('source')}）")
    else:
        A("- 首次扫描，本次结果将作为基线。")
    if scan["history"]:
        A("\n| 日期 | 会话 | 纠错率 | 人处理时长 h |\n|---|---|---|---|")
        for h in scan["history"]:
            A(f"| {h['date']} | {h['sessions']} | {h['correction_rate']} | {h['human_hours']} |")
    A("\n周趋势：" + "｜".join(f"{w['week']} {w['sessions']}会话/纠错{w['correction_rate']}%" for w in scan["weekly"]))
    A("")
    A("## 3. 工作类型分布（分类为启发候选）")
    A("| 工作类型 | 会话 | 每周 | 近30天/前30天 | 轮次占比 | 人侧间隔 h | AI 活动时长 h | 纠错候选率 | 无强纠错占比（≠验收） | 判断候选 | 对外占比 | Skill 覆盖 |\n|---|---|---|---|---|---|---|---|---|---|---|---|")
    for f in scan["families"]:
        fpr = "—" if f["first_pass_rate"] is None else f"{f['first_pass_rate']}%"
        A(f"| {f['family']} | {f['sessions']}{fmt_delta(f['sessions'], (f['prev'] or {}).get('sessions'))} | {f['per_week']} | {f['recent30']}/{f['prior30']} | "
          f"{f['turn_share']}% | {f['human_hours']} | {f['ai_hours']} | {f['correction_rate']}% | {fpr} | {f['judgment_turns']} | {f['external_share']}% | {f['skill_share']}% |")
    A("")
    A("## 4. 各工作类型的环节拆解")
    for f in scan["families"]:
        A(f"\n### {f['family']}（{f['sessions']} 个会话，最近 {f['last_active']}）")
        A("- 典型路径：" + "；".join(f"{p['path']} ×{p['n']}" for p in f["paths"]))
        A("- AI 动作：" + "、".join(f"{k} {v}" for k, v in f["ai_actions"].items()))
        A(f"- 返工：平均每会话 {f['rework_turns_per_session']} 轮；类别 {f['correction_cats'] or '无'}")
        A(f"- 常用 Skill：{', '.join(f['skills']) or '无'}｜产出类型：{', '.join(f['exts']) or '无'}｜月度会话 {f['months']}")
        A(f"- 已有资产：Skill {', '.join(f['assets']['skills']) or '无'}；SOP {', '.join(f['assets']['sops']) or '无'}")
        if f["phases"]:
            A("\n| 环节 | 轮次 | 涉及会话 | 人处理 min | AI 执行 min |\n|---|---|---|---|---|")
            for p in PHASES:
                x = f["phases"].get(p)
                if x:
                    A(f"| {p} | {x['turns']} | {x['sessions']} | {x['human_min']} | {x['ai_min']} |")
        if f["judgment_examples"]:
            A("\n人工判断介入示例：")
            for q in f["judgment_examples"]:
                A(f"- {q}")
        if f["correction_examples"]:
            A("\n返工示例：")
            for q in f["correction_examples"]:
                A(f"- {q}")
    A("")
    A("## 5. 重复任务簇（标题片段 × 会话数）")
    A("| 片段 | 会话数 | 所属类型 | 示例 | 最近 |\n|---|---|---|---|---|")
    for c in scan["clusters"]:
        A(f"| {c['key']} | {c['n']} | {', '.join(c['families'])} | {'；'.join(c['examples'])} | {c['last']} |")
    A("")
    A("## 6. 已有资产")
    A(f"- 用户级 Skill {scan['assets']['skills_count']} 个；用户级记忆 {scan['assets']['user_memory_chars']} 字")
    A("- SOP 文件：" + ("；".join(f"{x['name']}（{x['where']}）" for x in scan["assets"]["sops"]) or "无"))
    A("- 定时任务：" + ("；".join(f"{x['title']}（运行 {x['runs']} 次，最近 {x['last']}）" for x in scan["assets"]["automations"]) or "无"))
    A("")
    A(f"## 7. 纠错候选明细（{len(scan['corrections'])} 条）")
    A("| 引用 | 日期 | 类型 | 环节 | 类别 | 原话 |\n|---|---|---|---|---|---|")
    for c in scan["corrections"]:
        A(f"| {c['ref']} | {c['date']} | {c['family']} | {c['phase']} | {'/'.join(c['correction_categories'])} | {c['quote'].replace('|', '/')} |")
    A("")
    A(f"## 8. 人工判断候选明细（{len(scan['judgments'])} 条）")
    for j in scan["judgments"]:
        A(f"- {j['ref']}｜{j['family']}｜{j['phase']}｜{j['quote']}")
    A("")
    A("## 9. 工作区")
    A("| 工作区 | 会话 | 轮次 | 时长 h | 纠错率 | 工具失败率 | 定时 |\n|---|---|---|---|---|---|---|")
    for w in scan["workspaces"]:
        A(f"| {w['workspace']} | {w['sessions']} | {w['turns']} | {w['hours']} | {w['correction_rate']}% | {w['fail_rate']}% | {w['automation']} |")
    A("")
    A(f"## 10. 会话清单（{len(scan['sessions'])} 个）")
    A("| 日期 | 会话 | 工作区 | 类型 | 标题 | 轮次 | 纠错候选 | 人侧间隔 min | AI 活动 min | 后续无强纠错（≠验收） | 路径 |\n|---|---|---|---|---|---|---|---|---|---|---|")
    for s in scan["sessions"]:
        fp = "—" if s["first_pass"] is None else ("✔" if s["first_pass"] else "✘")
        A(f"| {s['date']} | {s['id']} | {s['workspace']} | {s['family']} | {s['title'].replace('|', '/')} | {s['turns']} | {s['corrections']} | "
          f"{s['human_min']} | {s['ai_min']} | {fp} | {s['path']} |")
    open(path, "w", encoding="utf-8").write(
        P.HARNESS_RE.sub("[系统拦截]", "\n".join(L)) + "\n")  # 展示层落盘：改写安全拦截原文防宿主误判


# ---------------------------------------------------------------- 输出：给模型的分析摘要
def print_digest(scan, record_path, json_path):
    m, sc = scan["metrics"], scan["scope"]
    prev = scan.get("previous")
    P_ = lambda line="": print(P.HARNESS_RE.sub("[系统拦截]", line))  # stdout 展示层：防宿主误判拦截原文
    P_(f"# 工作扫描摘要（personal-ai-fde v{scan['version']}｜run {scan['run_id']}）")
    P_(f"范围：{sc.get('workspace')}｜{sc.get('from')} → {sc.get('to')}｜会话 {m['sessions']}（工作 {m['work_sessions']}｜定时 {m['automation_sessions']}"
       f"｜个人 {m['personal_sessions']}）｜人侧间隔 {m['human_hours']} h（非工时）｜AI 活动 {m['ai_hours']} h｜纠错候选率 {m['correction_rate']}%"
       f"｜后续无强纠错占比 {m['first_pass_rate']}%（≠验收）｜判断候选 {m['judgment_turns']} 轮")
    P_(f"历史：{'上次 ' + str(prev['date']) + '（' + prev['source'] + '）' if prev else '首次扫描，作为基线'}\n")
    P_("## A. 工作类型（启发分类，按人侧间隔排序；个人/定时/其他置后）")
    P_("| 类型 | 会话 | 每周 | 近30/前30 | 间隔h | AI活动h | 纠错候选率 | 无强纠错（≠验收） | 判断候选 | 对外 | Skill覆盖 | 上次对比 |\n|---|---|---|---|---|---|---|---|---|---|---|---|")
    for f in scan["families"]:
        pv = f["prev"]
        cmp_ = f"会话{fmt_delta(f['sessions'], pv.get('sessions'))} 纠错{fmt_delta(f['correction_rate'], pv.get('correction_rate'))}" if pv else ""
        fpr = "—" if f["first_pass_rate"] is None else f"{f['first_pass_rate']}%"
        P_(f"| {f['family']} | {f['sessions']} | {f['per_week']} | {f['recent30']}/{f['prior30']} | {f['human_hours']} | {f['ai_hours']} | "
           f"{f['correction_rate']}% | {fpr} | {f['judgment_turns']} | {f['external_share']}% | {f['skill_share']}% | {cmp_} |")
    P_("")
    P_("## B. 环节拆解与分工信号（工作类，逐类）")
    for f in scan["families"]:
        if f["family"] in (PERSONAL, OTHER) or f["sessions"] < 2:
            continue
        P_(f"\n### {f['family']}｜{f['sessions']} 会话｜每周 {f['per_week']}｜人侧间隔 {f['human_hours']} h / AI 活动 {f['ai_hours']} h")
        P_("- 路径：" + "；".join(f"{p['path']} ×{p['n']}" for p in f["paths"]))
        ph = "；".join(f"{p} {x['turns']}轮/间隔{x['human_min']}m/AI{x['ai_min']}m" for p, x in
                      sorted(f["phases"].items(), key=lambda kv: -kv[1]["human_min"])[:6])
        P_(f"- 环节（按人侧间隔）：{ph}")
        P_(f"- AI 动作：{f['ai_actions']}｜返工类别 {f['correction_cats'] or '无'}｜后续无强纠错 {f['first_pass_rate']}%（n={f['first_pass_n']}，≠验收）"
           f"｜拒绝执行 {f['rejections']}｜Skill {list(f['skills'].keys())[:4]}")
        P_(f"- 已有资产：Skill {f['assets']['skills'][:5] or '无'}｜SOP {f['assets']['sops'] or '无'}")
        for q in f["judgment_examples"][:3]:
            P_(f"  - 判断介入：{q}")
        for q in f["correction_examples"][:3]:
            P_(f"  - 返工：{q}")
        P_(f"- 深挖候选：{', '.join(f['deep_dive'])}")
    ch = scan.get("changes") or {}
    P_("\n## C. 与上次对比（进步判定用）")
    if not ch:
        P_("- 首次扫描，作为基线")
    else:
        P_(f"- 状态：{ch.get('status')}｜上次 {ch.get('prev_date', '—')}｜可比：{'是' if ch.get('comparable') else '否'}")
        for n in ch.get("notes", []):
            P_(f"- {n}")
        if ch.get("comparable"):
            d = ch.get("deltas", {})
            P_("- 指标增量：" + "；".join(f"{k} {v:+}" for k, v in d.items() if v is not None))
            fd = [f"{x['family']} 会话{x['sessions']:+}/纠错{x['correction_rate']:+.1f}点" for x in ch.get("family_deltas", []) if x["sessions"] or x["correction_rate"]]
            if fd:
                P_("- 板块增量：" + "；".join(fd[:8]))
    P_("\n## D. 重复任务簇")
    P_("；".join(f"{c['key']}×{c['n']}（{'/'.join(c['families'])}；例：{c['examples'][0]}）" for c in scan["clusters"][:12]))
    P_("\n## E. 已有资产")
    P_("- SOP：" + ("；".join(f"{x['name']}（{x['where']}）" for x in scan["assets"]["sops"]) or "无"))
    P_("- 定时任务：" + ("；".join(f"{x['title']}（{x['runs']} 次，最近 {x['last']}）" for x in scan["assets"]["automations"][:6]) or "无"))
    P_(f"\n完整扫描文档：{record_path}")
    P_(f"结构化数据：{json_path}（build_report.py --scan 使用）")
    P_("口径提醒：间隔≠工时；候选≠结论；无后续纠错≠验收通过。")
