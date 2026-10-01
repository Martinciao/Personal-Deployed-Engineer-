#!/usr/bin/env python3
"""
personal-ai-fde v1.0.0 会话扫描器（WorkBuddy 优先，兼容 CodeBuddy / Claude Code）。

只读扫描本机全部工作区的会话日志，输出给模型阅读的 Markdown 摘要，并把客观指标写入
scan.json 供 build_report.py 渲染 HTML 报告。不联网、不改动任何日志文件。

脱敏分两层（v1.0.0 语义）：
  redact()     数据层（scan.json / 缓存）：只做 PII 脱敏，保留安全拦截原文，供审计追溯
  redact_out() 展示层（stdout / Markdown 文档）：在 PII 脱敏之上把安全拦截原文改写为
               「[系统拦截]」，避免宿主把工具输出误判为本命令被拦截；改写次数记入 coverage.warnings

用法:
  python3 parse_sessions.py scan [--days 30 | --all] [--workspace 关键词] [--exclude-current]
                                 [--share-safe]        # 原话与标题置空，仅保留结构化指标，适合外发
  python3 parse_sessions.py list [--days 14]
  python3 parse_sessions.py session <sessionId前缀|路径> [--full]
  python3 parse_sessions.py file <导出的 .jsonl/.txt/.md>
  python3 parse_sessions.py goldset <标注.tsv> [--taxonomy x.json]   # 分类器一致率标定（≥30 样本）
  python3 parse_sessions.py purge [--yes]               # 清空解析缓存（不动原日志）

通用参数:
  --root <目录>      追加/替换日志根目录（可重复）；默认 ~/.workbuddy/projects 等
  --cache-dir <目录> 缓存与 scan.json 的位置；默认 ~/.workbuddy/ai-fde，不可写时回落到 ./.ai-fde
"""
import argparse, glob, json, os, re, sys, time, random
from collections import Counter, defaultdict
from datetime import datetime

VERSION = "1.1.0"
CACHE_V = "1.0.0"  # 解析逻辑或脱敏规则变化时递增，使旧缓存失效
CACHE_TTL_DAYS = 90  # 缓存条目最长保留天数，超期自动重解析（派生数据不做无限期留存）
HOME = os.path.expanduser("~")
WB_HOME = os.path.join(HOME, ".workbuddy")
DEFAULT_ROOTS = [
    os.path.join(WB_HOME, "projects"),
    os.path.join(HOME, ".codebuddy", "projects"),
    os.path.join(HOME, ".claude", "projects"),
]
ACTIVE_GAP_MS = 30 * 60 * 1000  # 两条记录间隔超过 30 分钟不计入活跃时长

# ---------------------------------------------------------------- 文本清洗
QUERY_RE = re.compile(r"<user_query>([\s\S]*?)</user_query>")
BLOCK_TAGS = ("system-reminder", "system_reminder", "additional_data", "user_info", "current_time",
              "memory_and_skills_reminder", "project_context", "identity_context", "product_identity",
              "tone_and_style", "connector-status", "craft_mode", "ask_mode", "automation_system_reminder",
              "manually_attached_skills", "expert_prompt", "file_handling_rules", "tencent_docs_editor_context",
              "active_document", "tencent_docs_selection", "user_special_instructions", "omitted",
              "previous_tool_call", "previous_assistant_message", "previous_user_message", "result")
BLOCK_RE = re.compile(r"<(%s)[^>]*>[\s\S]*?</\1>" % "|".join(re.escape(t) for t in BLOCK_TAGS), re.I)
TAG_RE = re.compile(r"</?[a-zA-Z_\-]+(?:\s[^>]{0,200})?>")
NON_USER_PREFIX = ("<task-notification", "<teammate-message", "<conversation_history_summary", "<cb_summary",
                   "Please continue with the conversation", "<local-command-stdout", "<command-message")
CONTINUE_RE = re.compile(r"^(请继续(完成)?(未完成的任务)?[。.!！]?|继续[。.!！]?|continue\.?|go on\.?)$", re.I)

# ---------------------------------------------------------------- 语义线索（只做召回，由模型复核）
CORR_CATS = [  # 前四类为强信号，计入纠错率；「约束」为弱信号，单独统计
    ("方向", re.compile(r"(不是我要的|我说的是|我的意思是|我在(和你)?(讨论|说)的是|我问的是|我要的是|理解错|理解偏|跑偏|不是这个意思|其实我是想|你没理解|答非所问|^不是[，,])", re.I)),
    ("事实", re.compile(r"(错了|不对|写错|搞错|不准确|有误|数据不对|不是.{0,8}而是|\bwrong\b|incorrect)", re.I)),
    ("格式语气", re.compile(r"(太长|太短|太啰嗦|啰嗦|ai ?味|AI ?味|de-?ai|破折号|太正式|太口语|语气|排版|格式不|虚词|套话|很丑|重叠)", re.I)),
    ("返工", re.compile(r"(重新(做|写|来|生成|改|给)|重做|再改|再做一[次版]|还是(很|太|有|不|没)|又错|怎么又|跟你说过|说了多少次|说过了|撤回|回滚|\bredo\b|\brevert\b|\bundo\b)", re.I)),
    ("约束", re.compile(r"(不要|别再|不能这样|不用这样|不需要|别用|\bdon'?t\b|\bnot what\b)", re.I)),
]
STRONG_CATS = {"方向", "事实", "格式语气", "返工"}
REMEMBER_RE = re.compile(r"(记住|记下来|记一下|写进记忆|存进记忆|以后(都|所有|每次)|下次(都|也)|形成(规范|规则)|\bremember\b)", re.I)
QUESTION_RE = re.compile(r"([?？]\s*$|吗[?？]?\s*$|呢[?？]?\s*$|是不是|要不要|能不能|可不可以|怎么样[?？])")
POSITIVE_RE = re.compile(r"(很好|完美|不错|可以了|就这样|太棒|满意|没问题|很棒|\bperfect\b|\bgreat\b|\bnice\b|looks good)", re.I)
GOAL_RE = re.compile(r"(目标|目的|为了|用于|用来|以便|给.{0,8}(看|用|发)|面向|受众|验收|标准|交付|输出成|最终|要做一|做一[个份张页]|写一[封份篇个]|成功的标志|done when)", re.I)
CONTEXT_RE = re.compile(r"(参考|照着|按照|模板|示例|例如|比如|背景|附件|这份|这个文件|原文|资料|链接)", re.I)
CONSTRAINT_RE = re.compile(r"(不超过|以内|不要|必须|只要|控制在|字以内|\d+ ?页|一页|格式|口径|版本|英文|中文|表格|bullet|语气|篇幅)", re.I)
PLAN_RE = re.compile(r"(先.{0,12}(再|然后)|计划|方案|步骤|拆解|先别动手|先分析|先调研|\bplan\b)", re.I)
VERIFY_RE = re.compile(r"(验证|测试|跑一下|截图|证据|落盘|检查一下|确认一下|核对|出处|fact.?check|double confirm|对一下|\bverify\b|\btest\b)", re.I)
EMAIL_MARK = re.compile(r"^(dear|hi|hello|morning|best,|best regards|regards|thanks|发件人|收件人|主题[:：]|抄送|from:|to:|subject:|cc:|sent:)", re.I)
REF_RE = re.compile(r"(@\"[^\"]+\"|@/[^\s]+|@skill:[\w\-]+|https?://\S+|^[^\s/]{1,80}\.(pdf|docx?|pptx?|xlsx?|csv|md|png|jpe?g|txt)\b)", re.I | re.M)
ATTACH_TAG_RE = re.compile(r"<(attached_files|local_files|user_references|image_local_path|file|media)\b", re.I)
AUTOMATION_RE = re.compile(r"automations/([0-9a-f\-]{8,})/memory\.md")
MODE_RE = re.compile(r"You are now in (\w+) mode", re.I)
SLASH_RE = re.compile(r"<command-name>\s*/?([\w:\-]+)")

# ---------------------------------------------------------------- 工作环节识别（v3）
VISUAL_RE = re.compile(r"(排版|字体|字号|配色|颜色|很丑|好看|美观|艺术|重叠|对齐|间距|布局|图例|样式|版式|logo|留白|溢出)", re.I)
TRANSLATE_RE = re.compile(r"(翻译|translate|译成|英文版|中文版|中英|用英文|换成英文|改成英文|改成中文|in english)", re.I)
DELIVER_RE = re.compile(r"(保存|存到|存一下|存成|发给|上传|导出|转成|转换成|另存|下载|打包|发布|分享链接|放到资料库|归档)", re.I)
# 用户在对话里注入业务判断：口径、关系、承诺、授权、对外分寸
JUDGE_RE = re.compile(r"(不要.{0,8}(联系|透露|写|提|抢|说|暴露|承诺)|不能(透露|说|写|承诺|commit)|口径|立场|站在.{0,12}(角度|视角|立场)|对外|内部信息|敏感|抢功|轻描淡写|\bcommit\b|\bconfirm\b|承诺|报价|价格|预算|合同|法务|合规|授权|审批|领导|老板|上级|客户关系|分寸|姿态|得罪|拍板|给.{0,6}面子)", re.I)
EXTERNAL_RE = re.compile(r"(邮件|email|回信|发给|客户|伙伴|partner|对外|官网|PR稿|新闻稿|致辞|主持|报价|合同|协议|老板|领导|汇报|上级|嘉宾)", re.I)
RESEARCH_TOOLS = {"WebSearch", "WebFetch", "domain_search", "conversation_search", "RAG_search", "web_search", "web_fetch"}
READ_TOOLS = {"Read", "Glob", "Grep", "list_dir", "read_me", "read_file", "LS"}
PRODUCE_TOOLS = {"Write", "Edit", "MultiEdit", "write_file", "create_file", "edit_file", "save_file", "ImageGen", "VideoGen",
                 "show_widget", "NotebookEdit", "replace_in_file"}
DELIVER_TOOLS = {"present_files", "deliver_attachments", "open_result_view", "preview_url", "automation_update"}
PRODUCE_BASH = re.compile(r"(create_doc|submit_doc_edit|html_to_docx|python-docx|python-pptx|pptx|docx|openpyxl|xlsx|reportlab|\.html\b|\.md\b|\.csv\b|>\s*\S+\.\w{2,4})", re.I)
DELIVER_BASH = re.compile(r"(upload_drive_file|upload_page|publish_page|wecom-cli\s+message|message\s+send|lexiang.*(create|upload))", re.I)
RESEARCH_BASH = re.compile(r"(\bcurl\b|\bwget\b|search-nodes|rag_search|get_doc_reviews|get_download_link)", re.I)
EXT_RE = re.compile(r"\.(docx?|pptx?|xlsx?|csv|html?|md|pdf|png|jpe?g|svg|mp4|mp3|skill|zip)\b", re.I)


def action_category(name, args):
    """把一次工具调用归到 AI 动作：research / read / produce / deliver / run / ask / plan / delegate / skill。"""
    if name in RESEARCH_TOOLS or (name.startswith("mcp__") and re.search(r"search|fetch|query|list|get", name, re.I)):
        return "research"
    if name == "DeferExecuteTool":
        tn = str(args.get("toolName") or "")
        if re.search(r"search|fetch|query|list|get|read", tn, re.I):
            return "research"
        return "produce" if re.search(r"create|write|update|add|set|import|gen", tn, re.I) else "run"
    if name in READ_TOOLS:
        return "read"
    if name in PRODUCE_TOOLS:
        return "produce"
    if name in DELIVER_TOOLS:
        return "deliver"
    if name == "Bash":
        cmd = str(args.get("command") or "")
        if DELIVER_BASH.search(cmd):
            return "deliver"
        if RESEARCH_BASH.search(cmd):
            return "research"
        if PRODUCE_BASH.search(cmd):
            return "produce"
        return "run"
    if name == "AskUserQuestion":
        return "ask"
    if name in ("TaskCreate", "TaskUpdate", "todo_write", "plan_create", "plan_update", "ExitPlanMode", "TaskList"):
        return "plan"
    if name in ("Agent", "TeamCreate", "task", "SendMessage"):
        return "delegate"
    if name == "Skill":
        return "skill"
    return "run"


def file_exts(name, args):
    vals = []
    for k in ("file_path", "path", "target_file"):
        if args.get(k):
            vals.append(str(args[k]))
    if name == "present_files":
        vals += [str(x) for x in (args.get("files") or [])]
    return [m.lower().replace("jpeg", "jpg").replace("htm", "html").replace("htmll", "html")
            for v in vals for m in EXT_RE.findall(v)[-1:]]


def turn_phase(i, t):
    """用户这一轮在工作流里的位置。只做启发式，由模型复核。"""
    own = t["own"]
    if i == 0:
        return "布置任务"
    if set(t["corr"]) & STRONG_CATS:
        return "排版返工" if VISUAL_RE.search(own) else "内容返工"
    if VERIFY_RE.search(own):
        return "核对校验"
    if TRANSLATE_RE.search(own):
        return "翻译润色"
    if DELIVER_RE.search(own) and len(own) < 120:
        return "交付存档"
    if QUESTION_RE.search(own) and not t["acts"].get("produce"):
        return "讨论追问"
    if t["refs"]:
        return "补充材料"
    return "追加需求"

# ---------------------------------------------------------------- 脱敏
EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")
PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
IDCARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
BANK_RE = re.compile(r"(?<!\d)\d{16,19}(?!\d)")  # 连续 16-19 位数字按卡号处理（身份证已被 IDCARD_RE 先行拦截）
BANK_SP_RE = re.compile(r"(?<!\d)(?:\d{4}[ -]){3}\d{4}(?!\d)")  # 4-4-4-4 分组卡号
URLQ_RE = re.compile(r"(https?://[^\s?#\"'<>]+)[?#][^\s\"'<>]*")
TOKEN_RE = re.compile(r"(?<![\w/])[A-Za-z0-9_\-]{20,}(?![\w/])")  # ≥20 位随机串按密钥处理
# 这些原文若出现在脚本输出里，WorkBuddy 会误判为「本条命令被沙箱拦截」。仅展示层（stdout/Markdown）替换；
# 数据层（scan.json/缓存）保留原文，改写次数记入 coverage.warnings，保证安全事件可审计追溯
HARNESS_RE = re.compile(r"SANDBOX PERMISSION DENIED|Operation not permitted|安全策略拦截", re.I)
AUTO_BLOCK_RE = re.compile(r"<automation_system_reminder[^>]*>[\s\S]*?</automation_system_reminder>", re.I)


def redact(s):
    """数据层脱敏：只处理 PII，不改写安全拦截原文。"""
    s = EMAIL_RE.sub("[邮箱]", s or "")
    s = PHONE_RE.sub("[手机号]", s)
    s = IDCARD_RE.sub("[证件号]", s)
    s = BANK_SP_RE.sub("[卡号]", s)
    s = BANK_RE.sub("[卡号]", s)
    s = URLQ_RE.sub(r"\1?…", s)
    s = TOKEN_RE.sub("[长串]", s)
    return s


def redact_out(s):
    """展示层脱敏：PII + 安全拦截原文改写（防宿主误判）。所有 stdout/Markdown 输出必须走这里。"""
    return HARNESS_RE.sub("[系统拦截]", redact(s))


def extract_user_text(raw):
    """优先取 <user_query>，先剥掉会在正文里提到 <user_query> 字样的系统块，避免误截。"""
    stripped = BLOCK_RE.sub("", raw)
    qs = QUERY_RE.findall(stripped) or QUERY_RE.findall(AUTO_BLOCK_RE.sub("", raw))
    qs = [q for q in qs if not q.lstrip().startswith(". You MUST")]
    if qs:
        return "\n".join(qs).strip()
    return TAG_RE.sub("", stripped).strip()


def oneline(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------------------------------------------------------------- 基础工具
def content_text(content):
    if isinstance(content, str):
        return content, 0
    out, imgs = [], 0
    for c in content or []:
        if isinstance(c, dict):
            if c.get("type") in ("input_text", "output_text", "text"):
                out.append(c.get("text", ""))
            elif c.get("type") in ("input_image", "image"):
                imgs += 1
    return "\n".join(out), imgs


def result_text(output):
    if isinstance(output, dict):
        return output.get("text") or json.dumps(output, ensure_ascii=False)[:4000]
    if isinstance(output, list):
        return "\n".join(result_text(o) for o in output)
    return str(output or "")


def parse_args_field(a):
    if isinstance(a, dict):
        return a
    try:
        return json.loads(a) if a else {}
    except Exception:
        return {}


AUTO_DIR_RE = re.compile(r"\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}|\d{14}|default_project")


def display_workspace(cwd, names, project_dir=""):
    if cwd and cwd in names:
        return names[cwd]
    if cwd:
        base = os.path.basename(cwd.rstrip("/"))
        if cwd.rstrip("/") == HOME:
            return "临时任务（自动目录）"
    else:
        # 旧版日志没有 cwd 字段：从项目目录名（路径中的 / 被替换为 -）还原最后一段
        user = os.path.basename(HOME)
        base = re.sub(r"^Users-%s-?" % re.escape(user), "", project_dir or "")
        if base.startswith(".workbuddy-skills-"):
            return "Skill 目录：" + base[len(".workbuddy-skills-"):]
        base = re.sub(r"^(WorkBuddy|Desktop|Documents|Downloads|\.workbuddy-workspace)-", "", base) or "临时任务（自动目录）"
    if base.startswith("automation-"):
        return "定时任务（自动目录）"
    if AUTO_DIR_RE.fullmatch(base):
        return "临时任务（自动目录）"
    return base


def load_workspace_names():
    p = os.path.join(WB_HOME, "workspace-display-names.json")
    try:
        ws = json.load(open(p, encoding="utf-8")).get("workspaces", {})
        return {k: v.get("displayName") or os.path.basename(k) for k, v in ws.items()}
    except Exception:
        return {}


def load_legacy_titles():
    p = os.path.join(WB_HOME, "sessions.json")
    try:
        return {s["id"]: s.get("title", "") for s in json.load(open(p, encoding="utf-8")).get("sessions", [])}
    except Exception:
        return {}


def pick_cache_dir(explicit=None):
    cands = [explicit] if explicit else [os.path.join(WB_HOME, "ai-fde"), os.path.join(os.getcwd(), ".ai-fde")]
    for d in cands:
        try:
            os.makedirs(d, exist_ok=True)
            probe = os.path.join(d, ".probe")
            open(probe, "w").write("ok")
            os.remove(probe)
            return d
        except Exception:
            continue
    return None


def all_session_files(roots):
    files = []
    for r in roots:
        files += glob.glob(os.path.join(r, "*", "*.jsonl"))  # 只取主会话，不含 subagents/
    return files


def project_dir_of(cwd):
    return cwd.strip("/").replace("/", "-")


# ---------------------------------------------------------------- 用户消息拆分
def split_own_pasted(text):
    """把一条用户消息拆成「自己写的话」和「粘贴的材料」。只做启发式，最终以模型语义判断为准。"""
    if len(text) <= 400:
        return text.strip(), 0
    own, pasted, in_mail = [], 0, False
    for p in re.split(r"\n+", text):
        ps = p.strip()
        if not ps:
            continue
        if EMAIL_MARK.search(ps):
            in_mail = True
        if in_mail or len(ps) > 220:
            pasted += len(ps)
        else:
            own.append(ps)
    own_txt = "\n".join(own).strip()
    if not own_txt:
        own_txt = (text[:150] + " … " + text[-150:]).strip()
    return own_txt[:800], pasted


def classify_correction(own):
    cats = [name for name, pat in CORR_CATS if pat.search(own)]
    if not cats:
        return []
    if QUESTION_RE.search(own) and set(cats) <= {"返工", "约束"}:
        return []  # “还是重新再发一封呢？”这类是提问，不是纠错
    return cats



def postprocess_turns(s):
    """纠错归类、环节归类与人机时长切分；缓存命中的会话也要补跑（旧缓存无 phase 字段）。"""
    prev_last = None
    for i, tn in enumerate(s["turns"]):
        tn["corr"] = classify_correction(tn["own"]) if i > 0 else []
        tn.setdefault("acts", {})
        tn.setdefault("skills", [])
        tn.setdefault("phase", turn_phase(i, tn))
        if "ai_s" not in tn:
            tn["ai_s"] = int(min(max((tn.get("last_ts") or tn["ts"] or 0) - (tn["ts"] or 0), 0), 3600 * 1000) / 1000) if tn["ts"] else 0
            gap = (tn["ts"] - prev_last) if (tn["ts"] and prev_last) else None
            tn["human_s"] = int(gap / 1000) if gap is not None and 0 <= gap <= ACTIVE_GAP_MS else 0
        prev_last = tn.get("last_ts") or tn["ts"]
        tn.pop("last_ts", None)


# ---------------------------------------------------------------- 单会话分析
def analyze_file(path, names=None, legacy_titles=None):
    names = names or {}
    legacy_titles = legacy_titles or {}
    sid = os.path.basename(path)[:-6]
    s = {
        "id": sid, "file": path, "cwd": "", "title": "", "ai_title": "", "custom_title": "",
        "start": None, "end": None, "active_min": 0.0, "kind": "interactive", "automation_id": "",
        "turns": [], "n_user": 0, "compactions": 0, "teammate_msgs": 0, "task_notifs": 0, "continues": 0,
        "n_calls": 0, "n_fail": 0, "max_fail_streak": 0, "sandbox": 0, "rejected": 0,
        "tools": Counter(), "skills": Counter(), "connectors": Counter(), "modes": Counter(), "slash": Counter(),
        "deliverables": 0, "memory_writes": 0, "memory_curated": 0, "automation_ops": 0, "subagents": 0,
        "ask_user": 0, "plan_tools": 0, "manual_skill": 0, "expert": 0, "images": 0, "remember_asks": 0,
        "exts": Counter(),
    }
    ts_all, streak = [], 0
    try:
        fh = open(path, encoding="utf-8", errors="ignore")
    except Exception:
        return None
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                load_sessions.invalid_lines = getattr(load_sessions, "invalid_lines", 0) + 1
                continue
            ts = r.get("timestamp")
            if isinstance(ts, (int, float)):
                ts_all.append(ts)
                if s["turns"] and r.get("type") != "message" or (s["turns"] and r.get("role") == "assistant"):
                    s["turns"][-1]["last_ts"] = max(s["turns"][-1].get("last_ts") or 0, ts)
            if not s["cwd"] and r.get("cwd"):
                s["cwd"] = r["cwd"]
            t = r.get("type")
            if t == "ai-title":
                s["ai_title"] = r.get("aiTitle", "") or s["ai_title"]
            elif t == "custom-title":
                s["custom_title"] = r.get("customTitle", "") or s["custom_title"]
            elif t == "message" and r.get("role") == "user":
                raw, imgs = content_text(r.get("content"))
                pd = r.get("providerData") or {}
                if pd.get("agent") == "compact" or "<conversation_history_summary" in raw or "<cb_summary" in raw:
                    s["compactions"] += 1
                    continue
                head = raw.lstrip()
                if head.startswith("<teammate-message"):
                    s["teammate_msgs"] += 1
                    continue
                if head.startswith("<task-notification"):
                    s["task_notifs"] += 1
                    continue
                if head.startswith(NON_USER_PREFIX):
                    continue
                if "<automation_system_reminder" in raw:
                    s["kind"] = "automation"
                    m = AUTOMATION_RE.search(raw)
                    if m:
                        s["automation_id"] = m.group(1)
                for m in MODE_RE.findall(raw):
                    s["modes"][m.capitalize()] += 1
                if "Ask mode is active" in raw:
                    s["modes"]["Ask"] += 1
                if "<manually_attached_skills" in raw:
                    s["manual_skill"] += 1
                if "<expert_prompt" in raw:
                    s["expert"] += 1
                for m in SLASH_RE.findall(raw):
                    s["slash"][m] += 1
                text = extract_user_text(raw)
                if not text:
                    continue
                if CONTINUE_RE.match(text):
                    s["continues"] += 1
                    continue
                own, pasted = split_own_pasted(text)
                if REMEMBER_RE.search(own):
                    s["remember_asks"] += 1
                refs = len(REF_RE.findall(text)) + len(ATTACH_TAG_RE.findall(raw)) + imgs
                s["images"] += imgs
                s["turns"].append({
                    "ts": ts, "last_ts": ts, "own": own, "len": len(text), "pasted": pasted, "refs": refs,
                    "corr": [], "positive": bool(POSITIVE_RE.search(own[:200])),
                    "acts": {}, "skills": [], "judge": bool(JUDGE_RE.search(own)),
                })
            elif t == "function_call":
                name = r.get("name") or "?"
                s["n_calls"] += 1
                s["tools"][name] += 1
                a = parse_args_field(r.get("arguments"))
                if s["turns"]:
                    cur = s["turns"][-1]
                    cat = action_category(name, a)
                    cur["acts"][cat] = cur["acts"].get(cat, 0) + 1
                    for e in file_exts(name, a):
                        s["exts"][e] += 1
                if name == "Skill":
                    sk = a.get("skill") or a.get("command") or "?"
                    s["skills"][sk] += 1
                    if s["turns"]:
                        s["turns"][-1]["skills"].append(sk)
                elif name == "DeferExecuteTool":
                    tn = a.get("toolName") or ""
                    if tn.startswith("mcp__"):
                        s["connectors"][tn.split("__")[1]] += 1
                elif name.startswith("mcp__"):
                    s["connectors"][name.split("__")[1]] += 1
                elif name in ("present_files", "deliver_attachments", "open_result_view"):
                    s["deliverables"] += 1
                elif name in ("Edit", "Write", "write_file", "update_memory"):
                    fp = str(a.get("file_path") or a.get("path") or "")
                    if name == "update_memory" or "/.workbuddy/memory/" in fp or fp.endswith("MEMORY.md"):
                        s["memory_writes"] += 1
                        if name == "update_memory" or fp.endswith("MEMORY.md"):
                            s["memory_curated"] += 1  # 长期规则；日期日志属于系统自动记录
                elif name == "automation_update" and str(a.get("mode")) in ("create", "update"):
                    s["automation_ops"] += 1
                elif name in ("Agent", "TeamCreate", "task"):
                    s["subagents"] += 1
                elif name == "AskUserQuestion":
                    s["ask_user"] += 1
                elif name in ("plan_create", "plan_update", "ExitPlanMode"):
                    s["plan_tools"] += 1
            elif t == "function_call_result":
                txt = result_text(r.get("output"))[:4000]
                failed = r.get("status") not in (None, "completed")
                codes = re.findall(r"Exit Code:\s*(\d+)", txt)
                if codes and codes[-1] != "0":
                    failed = True
                if "<tool_use_error>" in txt or "InputValidationError" in txt or re.match(r"\s*\{\"error\"", txt):
                    failed = True
                if HARNESS_RE.search(txt):
                    s["sandbox"] += 1
                    failed = True
                if "User rejected" in txt:
                    s["rejected"] += 1
                    failed = True
                elif '"status": "cancelled"' in txt:
                    failed = True  # 多为工具名不存在等调用错误，不算用户拒绝
                if failed:
                    s["n_fail"] += 1
                    streak += 1
                    s["max_fail_streak"] = max(s["max_fail_streak"], streak)
                else:
                    streak = 0

    if ts_all:
        ts_all.sort()
        s["start"], s["end"] = ts_all[0], ts_all[-1]
        act = sum(min(b - a, ACTIVE_GAP_MS) if b - a <= ACTIVE_GAP_MS else 0 for a, b in zip(ts_all, ts_all[1:]))
        s["active_min"] = round(act / 60000, 1)
    s["n_user"] = len(s["turns"])
    if s["n_user"] == 0 and s["teammate_msgs"]:
        s["kind"] = "team"
    postprocess_turns(s)
    s["workspace"] = display_workspace(s["cwd"], names, os.path.basename(os.path.dirname(path)))
    first = s["turns"][0]["own"] if s["turns"] else ""
    if s["kind"] == "automation":
        s["title"] = "[定时] " + (oneline(first, 30) or s["ai_title"] or "(无标题)")
    else:
        s["title"] = s["custom_title"] or s["ai_title"] or legacy_titles.get(sid, "") or oneline(first, 30) or "(无标题)"
    return s


COUNTER_KEYS = ("tools", "skills", "connectors", "modes", "slash", "exts")


def to_cacheable(s):
    d = dict(s)
    for k in COUNTER_KEYS:
        d[k] = dict(s.get(k) or {})
    d["turns"] = [dict(t, own=redact(t["own"])[:400]) for t in s["turns"]]
    d["cached_at"] = time.time()  # 供 TTL 判断；缓存为 PII 脱敏后的派生数据，超期或 --purge 清除
    return d


def from_cache(d):
    for k in COUNTER_KEYS:
        d[k] = Counter(d.get(k) or {})
    return d


def load_sessions(roots, cache_dir, verbose=True):
    names, legacy = load_workspace_names(), load_legacy_titles()
    cache_path = os.path.join(cache_dir, "sessions-cache.json") if cache_dir else None
    cache = {}
    if cache_path and os.path.exists(cache_path):
        try:
            cache = json.load(open(cache_path, encoding="utf-8"))
            if cache.get("_v") != CACHE_V:
                cache = {}
        except Exception:
            cache = {}
    ttl_s = CACHE_TTL_DAYS * 86400
    out, new_cache, hits = [], {"_v": CACHE_V}, 0
    for f in all_session_files(roots):
        try:
            st = os.stat(f)
        except Exception:
            continue
        key = "%s|%d|%d" % (f, int(st.st_mtime), st.st_size)
        ent = cache.get(key)
        if ent and time.time() - (ent.get("cached_at") or 0) <= ttl_s:
            s = from_cache(ent)
            postprocess_turns(s)
            hits += 1
        else:
            s = analyze_file(f, names, legacy)
            if s is None:
                continue
            s = from_cache(to_cacheable(s))
        s["mtime"] = st.st_mtime
        new_cache[key] = to_cacheable(s)
        out.append(s)
    if cache_path:
        try:
            json.dump(new_cache, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass
    if verbose:
        print(f"<!-- 读取会话文件 {len(out)} 个，缓存命中 {hits} 个 -->", file=sys.stderr)
    return out


# ---------------------------------------------------------------- 聚合
def pct(a, b):
    return round(100.0 * a / b, 1) if b else 0.0


def strong(t):
    return bool(set(t["corr"]) & STRONG_CATS)


def n_strong(s):
    return sum(1 for t in s["turns"] if strong(t))


def n_weak(s):
    return sum(1 for t in s["turns"] if t["corr"] and not strong(t))


def select(sessions, days=None, workspace=None, exclude_ids=(), include_auto=True):
    now_ms = time.time() * 1000
    res = []
    for s in sessions:
        if s["id"] in exclude_ids or not s["end"]:
            continue
        if days and s["end"] < now_ms - days * 86400000:
            continue
        if workspace and workspace.lower() not in (s["workspace"] + " " + s["cwd"]).lower():
            continue
        if s["n_user"] == 0 and s["kind"] != "team":
            continue
        if not include_auto and s["kind"] == "automation":
            continue
        res.append(s)
    return res


def week_key(ms):
    d = datetime.fromtimestamp(ms / 1000)
    y, w, _ = d.isocalendar()
    monday = datetime.fromisocalendar(y, w, 1)
    return monday.strftime("%m-%d")


def aggregate(sel):
    inter = [s for s in sel if s["kind"] == "interactive"]
    auto = [s for s in sel if s["kind"] == "automation"]
    turns = sum(s["n_user"] for s in inter)
    follow = sum(max(s["n_user"] - 1, 0) for s in inter)
    corr = sum(n_strong(s) for s in inter)
    weak = sum(n_weak(s) for s in inter)
    cat = Counter(c for s in inter for t in s["turns"] for c in t["corr"])
    firsts = [s["turns"][0] for s in inter if s["turns"]]
    calls = sum(s["n_calls"] for s in sel)
    fails = sum(s["n_fail"] for s in sel)
    agg = {
        "sessions": len(sel), "interactive": len(inter), "automation_sessions": len(auto),
        "team_sessions": sum(1 for s in sel if s["kind"] == "team"),
        "workspaces": len({s["workspace"] for s in sel}),
        "user_turns": turns, "active_hours": round(sum(s["active_min"] for s in sel) / 60, 1),
        "avg_turns": round(turns / len(inter), 1) if inter else 0,
        "correction_turns": corr, "correction_rate": pct(corr, follow), "correction_cats": dict(cat),
        "weak_constraint_turns": weak, "correction_rate_incl_weak": pct(corr + weak, follow),
        "remember_asks": sum(s["remember_asks"] for s in inter),
        "memory_curated_sessions": sum(1 for s in sel if s["memory_curated"]),
        "continue_nudges": sum(s["continues"] for s in inter),
        "positive_turns": sum(1 for s in inter for t in s["turns"] if t["positive"]),
        "tool_calls": calls, "tool_fails": fails, "tool_fail_rate": pct(fails, calls),
        "sandbox_blocks": sum(s["sandbox"] for s in sel), "user_rejections": sum(s["rejected"] for s in sel),
        "sessions_with_sandbox": sum(1 for s in sel if s["sandbox"]),
        "compactions": sum(s["compactions"] for s in sel), "sessions_compacted": sum(1 for s in sel if s["compactions"]),
        "long_fail_streaks": sum(1 for s in sel if s["max_fail_streak"] >= 3),
        "first_goal": pct(sum(1 for t in firsts if GOAL_RE.search(t["own"])), len(firsts)),
        "first_context": pct(sum(1 for t in firsts if t["refs"] or CONTEXT_RE.search(t["own"])), len(firsts)),
        "first_constraint": pct(sum(1 for t in firsts if CONSTRAINT_RE.search(t["own"])), len(firsts)),
        "first_plan": pct(sum(1 for t in firsts if PLAN_RE.search(t["own"])), len(firsts)),
        "turns_with_refs": pct(sum(1 for s in inter for t in s["turns"] if t["refs"]), turns),
        "turns_pasted_heavy": pct(sum(1 for s in inter for t in s["turns"] if t["pasted"] > 1500), turns),
        "verify_asks": sum(1 for s in inter for t in s["turns"] if VERIFY_RE.search(t["own"])),
        "skills": dict(sum((s["skills"] for s in sel), Counter()).most_common(12)),
        "sessions_with_skill": sum(1 for s in sel if s["skills"] or s["manual_skill"]),
        "connectors": dict(sum((s["connectors"] for s in sel), Counter()).most_common(8)),
        "modes": dict(sum((s["modes"] for s in sel), Counter())),
        "plan_sessions": sum(1 for s in sel if s["plan_tools"]),
        "ask_user_calls": sum(s["ask_user"] for s in sel),
        "subagent_sessions": sum(1 for s in sel if s["subagents"]),
        "expert_sessions": sum(1 for s in sel if s["expert"]),
        "deliverable_sessions": sum(1 for s in sel if s["deliverables"]),
        "memory_write_sessions": sum(1 for s in sel if s["memory_writes"]),
        "automation_ops": sum(s["automation_ops"] for s in sel),
        "automation_ids": len({s["automation_id"] for s in auto if s["automation_id"]}),
        "automation_fail_rate": pct(sum(s["n_fail"] for s in auto), sum(s["n_calls"] for s in auto)),
    }
    return agg


def per_workspace(sel):
    g = defaultdict(list)
    for s in sel:
        g[s["workspace"]].append(s)
    rows = []
    for w, ss in g.items():
        inter = [s for s in ss if s["kind"] == "interactive"]
        follow = sum(max(s["n_user"] - 1, 0) for s in inter)
        corr = sum(n_strong(s) for s in inter)
        calls, fails = sum(s["n_calls"] for s in ss), sum(s["n_fail"] for s in ss)
        rows.append({"workspace": w, "sessions": len(ss), "turns": sum(s["n_user"] for s in ss),
                     "hours": round(sum(s["active_min"] for s in ss) / 60, 1),
                     "correction_rate": pct(corr, follow), "fail_rate": pct(fails, calls),
                     "automation": sum(1 for s in ss if s["kind"] == "automation")})
    rows.sort(key=lambda r: (-r["sessions"], -r["turns"]))
    return rows


def weekly(sel, weeks=10):
    g = defaultdict(list)
    for s in sel:
        g[week_key(s["end"])].append((s["end"], s))
    keys = sorted(g, key=lambda k: max(e for e, _ in g[k]))[-weeks:]
    out = []
    for k in keys:
        ss = [s for _, s in g[k]]
        inter = [s for s in ss if s["kind"] == "interactive"]
        follow = sum(max(s["n_user"] - 1, 0) for s in inter)
        corr = sum(n_strong(s) for s in inter)
        out.append({"week": k, "sessions": len(ss), "turns": sum(s["n_user"] for s in ss),
                    "correction_rate": pct(corr, follow)})
    return out


def friction_score(s):
    return n_strong(s) * 3 + n_weak(s) + s["n_fail"] + s["compactions"] * 2 + s["sandbox"] * 2 \
        + (5 if s["max_fail_streak"] >= 3 else 0)


def assets_inventory():
    inv = {"user_skills": [], "agent_created_skills": 0, "user_memory_chars": 0, "user_memory_updated": "",
           "workspace_memories": 0}
    sk = os.path.join(WB_HOME, "skills")
    if os.path.isdir(sk):
        inv["user_skills"] = sorted(d for d in os.listdir(sk) if os.path.isfile(os.path.join(sk, d, "SKILL.md")))
    try:
        inv["agent_created_skills"] = len(json.load(open(os.path.join(WB_HOME, "agent-created-skills.json"))))
    except Exception:
        pass
    mems = glob.glob(os.path.join(WB_HOME, "user-*", "MEMORY.md")) or [os.path.join(WB_HOME, "MEMORY.md")]
    for m in mems:
        if os.path.isfile(m):
            inv["user_memory_path"] = m
            inv["user_memory_chars"] = len(open(m, encoding="utf-8", errors="ignore").read())
            inv["user_memory_updated"] = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(m)))
            break
    return inv


def workspace_memory_count(sel):
    """只看其他工作区是否存在记忆文件（stat），不读取内容。"""
    n = 0
    for cwd in {s["cwd"] for s in sel if s["cwd"]}:
        if os.path.isfile(os.path.join(cwd, ".workbuddy", "memory", "MEMORY.md")):
            n += 1
    return n


# ---------------------------------------------------------------- 输出：scan
def cmd_scan(a, roots):
    import worklens
    cache_dir = pick_cache_dir(a.cache_dir)
    all_files = all_session_files(roots)
    sessions = load_sessions(roots, cache_dir)
    exclude = set(a.exclude_session or [])
    if a.exclude_current:
        cwd = a.cwd or os.getcwd()
        pdir = project_dir_of(cwd)
        mine = [s for s in sessions if os.path.basename(os.path.dirname(s["file"])) == pdir]
        # 当前会话正在写入，mtime 最新；工作区匹配不到时退回全局最新文件
        pool = mine or sessions
        if pool:
            exclude.add(max(pool, key=lambda s: s["mtime"])["id"])
    days = None if a.all else a.days
    sel = select(sessions, days, a.workspace, exclude)
    skipped = [{"id": os.path.basename(f)[:12], "reason": "读取失败"} for f in all_files
               if not any(s["file"] == f for s in sessions)]
    coverage = {"discovered_files": len(all_files), "read_files": len(sessions),
                "in_scope_sessions": len(sel), "excluded_current": len(exclude),
                "skipped_files": skipped, "invalid_lines": getattr(load_sessions, "invalid_lines", 0),
                "roots": [r for r in roots if os.path.isdir(r)],
                "warnings": ["只读取主会话日志，不含子代理、云端任务与其他设备；时间过滤按逐条事件时间戳"]}
    # 数据层保留了安全拦截原文；展示层（stdout/Markdown）会改写为「[系统拦截]」，这里留痕改写规模
    harness_n = sum(len(HARNESS_RE.findall((s.get("title") or "") + " " + " ".join(t["own"] for t in s["turns"])))
                    for s in sel)
    if harness_n:
        coverage["warnings"].append(
            f"展示层改写安全拦截原文 {harness_n} 处为「[系统拦截]」；scan.json 数据层保留原文以便审计追溯")
    if not sel:
        print("## 扫描结果为空\n范围内没有可分析的会话。可改用 --all 或放宽 --workspace。")
        return
    agg = aggregate(sel)
    inter = [s for s in sel if s["kind"] == "interactive"]
    span = (min(s["start"] or s["end"] for s in sel), max(s["end"] for s in sel))
    if days:
        span = (max(span[0], time.time() * 1000 - days * 86400000), span[1])
    scope = {"days": days, "workspace": a.workspace or "全部工作区", "excluded": sorted(exclude),
             "from": time.strftime("%Y-%m-%d", time.localtime(span[0] / 1000)),
             "to": time.strftime("%Y-%m-%d", time.localtime(span[1] / 1000)),
             "generated": time.strftime("%Y-%m-%d %H:%M"),
             "source": "本机 WorkBuddy 主会话日志（只读）",
             "_from_ms": span[0], "_to_ms": span[1]}
    out_dir = os.path.abspath(a.out_dir) if a.out_dir else os.path.join(os.getcwd(), "outputs")
    history_dir = os.path.abspath(a.history_dir) if a.history_dir else out_dir
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(history_dir, exist_ok=True)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    legacy = None
    if a.legacy_history and os.path.exists(a.legacy_history):
        try:
            rows = [json.loads(l) for l in open(a.legacy_history, encoding="utf-8") if l.strip()]
            rows = [r for r in rows if r.get("scope_key") == f"{scope['workspace']}|{days}"] or rows
            if rows:
                legacy = rows[-1]
        except Exception:
            legacy = None
    scan = worklens.build_scan(sel, sessions, scope, agg, history_dir, taxonomy=a.taxonomy,
                               show_personal=a.include_personal, legacy=legacy, coverage=coverage, run_id=run_id)
    if getattr(a, "share_safe", False):
        # 对外分享模式：置空所有原话与标题，仅保留结构化指标、ref 与计数，防止引文外泄
        scan["scope"]["share_safe"] = True
        for e in scan.get("evidence", []):
            e["quote"] = "（share-safe 已省略原话）"
        for s in scan.get("sessions", []):
            s["title"] = "（已省略）"
        for f in scan.get("families", []):
            f["correction_examples"] = []
            f["judgment_examples"] = []
        for c in scan.get("clusters", []):
            c["examples"] = []
        coverage["warnings"].append("share-safe：原话、标题与示例已置空，仅保留结构化指标与引用编号，适合对外分享")
    json_path = os.path.join(out_dir, f"scan-{run_id}.json")
    md_path = os.path.join(out_dir, f"scan-{run_id}.md")
    json.dump(scan, open(json_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    worklens.write_record_md(scan, md_path)
    worklens.save_snapshot(scan, history_dir)
    worklens.print_digest(scan, md_path, json_path)


def frequent_terms(titles, top=15):
    df = Counter()
    for t in titles:
        t = re.sub(r"^\[定时\]\s*", "", t or "")
        grams = set()
        for seg in re.findall(r"[\u4e00-\u9fa5]{2,}", t):
            for n in (2, 3, 4):
                for i in range(len(seg) - n + 1):
                    grams.add(seg[i:i + n])
        grams |= {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", t)}
        df.update(grams)
    stop = {"一个", "帮我", "生成", "分析", "进行", "以及", "相关", "关于", "如何", "什么", "the", "and", "for"}
    cands = [(w, c) for w, c in df.items() if c >= 3 and w not in stop]
    cands.sort(key=lambda x: (-x[1], -len(x[0])))
    kept = []
    for w, c in cands:
        if any(w in k and c <= kc for k, kc in kept):
            continue
        kept.append((w, c))
        if len(kept) >= top:
            break
    return kept


def last_baseline(cache_dir, scope):
    if not cache_dir:
        return None
    p = os.path.join(cache_dir, "history.jsonl")
    if not os.path.exists(p):
        return None
    rows = []
    for line in open(p, encoding="utf-8"):
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    rows = [r for r in rows if r.get("scope_key") == scope_key(scope)] or rows
    return rows[-1] if rows else None


def scope_key(scope):
    return f"{scope.get('workspace')}|{scope.get('days')}"


# ---------------------------------------------------------------- 输出：list / session / file
def cmd_list(a, roots):
    sessions = load_sessions(roots, pick_cache_dir(a.cache_dir))
    sel = select(sessions, a.days, a.workspace)
    sel.sort(key=lambda s: -s["end"])
    print("| # | 会话ID | 更新 | 工作区 | 标题 | 轮次 | 类型 |\n|---|---|---|---|---|---|---|")
    for i, s in enumerate(sel[:60]):
        print(f"| {i} | {s['id'][:8]} | {time.strftime('%m-%d %H:%M', time.localtime(s['end'] / 1000))} | {s['workspace']} | "
              f"{oneline(redact_out(s['title']), 34)} | {s['n_user']} | {s['kind']} |")


def find_session_file(arg, roots):
    if os.path.isfile(arg):
        return arg
    for r in roots:
        hits = glob.glob(os.path.join(r, "*", f"{arg}*.jsonl"))
        if hits:
            return hits[0]
    sys.exit(f"找不到会话：{arg}（先用 list 查看会话 ID）")


def render_transcript(path, full=False, tools=False, ai_chars=240, max_turns=0, focus=False):
    """默认精简：用户原话完整、AI 回复截断、工具调用按段折叠成计数；--tools 逐条列出，--full 全部展开。
    focus=True 只保留前 3 轮、每个纠错候选轮及其前一轮（含触发纠错的 AI 回复），适合长会话深挖。"""
    text = _render_transcript(path, full, tools, ai_chars, max_turns)
    if not focus:
        return text
    parts = text.split("\n\n**[USER #")
    head, blocks = parts[0], parts[1:]
    keep = set(range(min(3, len(blocks))))
    for i, b in enumerate(blocks):
        if "⚑纠错候选" in b.split("\n", 1)[0]:
            keep |= {i - 1, i}
    out, last = [head], -1
    for i in sorted(k for k in keep if k >= 0):
        if i - last > 1:
            out.append(f"\n…（省略 {i - last - 1} 轮）")
        out.append("\n**[USER #" + blocks[i])
        last = i
    if len(blocks) - 1 > last:
        out.append(f"\n…（其后省略 {len(blocks) - 1 - last} 轮）")
    return "\n".join(out)


def _render_transcript(path, full=False, tools=False, ai_chars=240, max_turns=0):
    names = load_workspace_names()
    s = analyze_file(path, names, load_legacy_titles())
    if not s:
        return "无法读取该会话。"
    lim = 100000 if full else ai_chars
    tools = tools or full
    corr = n_strong(s)
    out = [f"## 会话 {s['id'][:8]}｜{redact_out(s['title'])}",
           f"工作区 {s['workspace']}｜类型 {s['kind']}｜用户轮次 {s['n_user']}｜纠错候选 {corr}｜活跃 {s['active_min']} min"
           f"｜工具 {s['n_calls']}/失败 {s['n_fail']}（最长连续 {s['max_fail_streak']}）｜沙箱拦截 {s['sandbox']}｜拒绝 {s['rejected']}"
           f"｜压缩 {s['compactions']}｜Skill {dict(s['skills']) or '无'}｜模式 {dict(s['modes']) or '无'}", "", "### Transcript（已清洗、脱敏）"]
    turn_i, pending, last_ai = 0, Counter(), ""

    def flush():
        if pending:
            out.append("  - 🔧 " + " ".join(f"{k}×{v}" for k, v in pending.most_common(6)))
            pending.clear()

    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            t = r.get("type")
            if t == "message" and r.get("role") == "user":
                raw, _ = content_text(r.get("content"))
                pd = r.get("providerData") or {}
                if pd.get("agent") == "compact" or "<conversation_history_summary" in raw:
                    flush()
                    out.append("  - [上下文压缩]")
                    continue
                if raw.lstrip().startswith(NON_USER_PREFIX):
                    continue
                text = extract_user_text(raw)
                if not text or CONTINUE_RE.match(text):
                    continue
                flush()
                if last_ai and not full:
                    out.append(f"**[AI 最终回复]** {oneline(redact_out(last_ai), lim)}")
                last_ai = ""
                own, pasted = split_own_pasted(text)
                tag = ""
                if turn_i < len(s["turns"]) and s["turns"][turn_i]["corr"]:
                    tag = " ⚑纠错候选[" + "/".join(s["turns"][turn_i]["corr"]) + "]"
                turn_i += 1
                if max_turns and turn_i > max_turns:
                    out.append(f"\n…（其余 {s['n_user'] - max_turns} 轮已省略，可用 --max-turns 0 查看全部）")
                    return "\n".join(out)
                note = f"（另有粘贴材料约 {pasted} 字已折叠）" if pasted else ""
                out.append(f"\n**[USER #{turn_i}]**{tag} {redact_out(own)[:1500]}{note}")
            elif t == "message" and r.get("role") == "assistant":
                txt, _ = content_text(r.get("content"))
                if "<conversation_history_summary" in txt:
                    continue
                if txt.strip():
                    if full:
                        flush()
                        out.append(f"**[AI]** {oneline(redact_out(txt), lim)}")
                    else:
                        last_ai = txt  # 精简模式只保留每轮最后一条 AI 回复
            elif t == "function_call":
                if tools:
                    args = r.get("arguments")
                    args = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
                    out.append(f"  - 🔧 {r.get('name')} {oneline(redact_out(args), 140)}")
                else:
                    pending[r.get("name") or "?"] += 1
            elif t == "function_call_result":
                txt = result_text(r.get("output"))[:4000]
                codes = re.findall(r"Exit Code:\s*(\d+)", txt)
                bad = r.get("status") not in (None, "completed") or (codes and codes[-1] != "0") \
                    or HARNESS_RE.search(txt) or "User rejected" in txt or "<tool_use_error>" in txt \
                    or re.match(r"\s*\{\"error\"", txt)
                if bad:
                    flush()
                    out.append(f"  - ❌ {r.get('name')} {oneline(redact_out(txt), 160)}")
    flush()
    if last_ai and not full:
        out.append(f"**[AI 最终回复]** {oneline(redact_out(last_ai), lim)}")
    return "\n".join(out)


def parse_plain(path):
    txt = open(path, encoding="utf-8", errors="ignore").read()
    recs = []
    for block in re.split(r"\n(?=(?:用户|我|User|Human|AI|助手|Assistant|WorkBuddy)\s*[:：])", txt):
        m = re.match(r"(用户|我|User|Human|AI|助手|Assistant|WorkBuddy)\s*[:：]\s*([\s\S]*)", block.strip())
        if m:
            recs.append(("user" if m.group(1) in ("用户", "我", "User", "Human") else "assistant", m.group(2)))
    return recs


def cmd_file(a):
    if a.path.endswith(".jsonl"):
        print(render_transcript(a.path, a.full))
        return
    recs = parse_plain(a.path)
    users = [t for r, t in recs if r == "user"]
    print(f"## 导入记录｜用户消息 {len(users)} 条")
    for i, u in enumerate(users, 1):
        own, pasted = split_own_pasted(u)
        cats = classify_correction(own) if i > 1 else []
        print(f"- #{i}{' ⚑' + '/'.join(cats) if cats else ''} {oneline(redact_out(own), 200)}{'（粘贴约 %d 字）' % pasted if pasted else ''}")


def cmd_purge(a):
    """清空解析缓存（PII 脱敏后的派生数据）。只动缓存目录内容，不碰任何原始会话日志。"""
    d = os.path.abspath(a.cache_dir) if a.cache_dir else os.path.join(WB_HOME, "ai-fde")
    if not os.path.isdir(d):
        print(f"缓存目录不存在：{d}（无需清理）")
        return
    if not a.yes:
        print(f"将删除缓存目录内全部文件：{d}\n原会话日志不受影响。确认请加 --yes 重新执行。")
        return
    n = 0
    for f in glob.glob(os.path.join(d, "*")):
        if os.path.isfile(f):
            try:
                os.remove(f)
                n += 1
            except Exception:
                print(f"- 跳过无法删除的文件：{f}")
    print(f"已清空缓存：{d}（删除 {n} 个文件）。下次扫描将全量重解析。")


def cmd_goldset(a, roots):
    """分类器一致率标定：读 TSV（每行「会话ID<TAB>人工标注板块」，# 开头为注释），
    用现有启发式重分类并输出一致率与混淆矩阵。建议 ≥30 个标注样本。"""
    import worklens
    sessions = load_sessions(roots, pick_cache_dir(a.cache_dir), verbose=False)
    by_id = {}
    for s in sessions:
        by_id[s["id"]] = s
        by_id[s["id"][:8]] = s
    tax, overrides = worklens.load_taxonomy(a.taxonomy)
    total = hit = 0
    conf = defaultdict(Counter)
    missing = []
    for line in open(a.tsv, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        sid, label = parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")
        s = by_id.get(sid)
        if not s:
            missing.append(sid)
            continue
        pred = worklens.classify_family(s, tax, {})
        total += 1
        conf[label][pred] += 1
        if pred == label:
            hit += 1
    if not total:
        print("没有可用标注样本。格式：每行「会话ID<TAB>板块名」，# 开头为注释。")
        return
    print(f"# 分类器标定结果（v{VERSION}）")
    print(f"- 有效样本 {total}｜命中 {hit}｜一致率 {pct(hit, total)}%")
    if missing:
        print(f"- 未找到会话 {len(missing)} 个：{', '.join(missing[:5])}{'…' if len(missing) > 5 else ''}（可先跑 list 核对 ID）")
    labels = sorted(conf)
    preds = sorted({p for row in conf.values() for p in row})
    print("\n混淆矩阵（行=人工标注，列=模型分类）：")
    print("| 标注＼预测 | " + " | ".join(preds) + " |")
    print("|---" * (len(preds) + 1) + "|")
    for lb in labels:
        print(f"| {lb} | " + " | ".join(str(conf[lb].get(p, 0)) for p in preds) + " |")
    if total < 30:
        print(f"\n- ⚠ 样本 {total} < 30：一致率仅供方向参考，不建议据此调整正则")
    print("\n口径提醒：一致率衡量的是启发式召回质量；分歧样本应人工复核后，再决定是改正则还是加 taxonomy override。")


def main():
    ap = argparse.ArgumentParser(description="personal-ai-fde 会话扫描器")
    ap.add_argument("--root", action="append", help="日志根目录，可重复；指定后替换默认值")
    ap.add_argument("--cache-dir")
    sub = ap.add_subparsers(dest="cmd")
    sp = sub.add_parser("scan")
    sp.add_argument("--days", type=int, default=30)
    sp.add_argument("--all", action="store_true")
    sp.add_argument("--workspace")
    sp.add_argument("--exclude-current", action="store_true")
    sp.add_argument("--exclude-session", action="append")
    sp.add_argument("--cwd")
    sp.add_argument("--top", type=int, default=10)
    sp.add_argument("--corr-limit", type=int, default=40)
    sp.add_argument("--title-limit", type=int, default=120)
    sp.add_argument("--out-dir", help="扫描文档输出目录；默认 <当前目录>/outputs")
    sp.add_argument("--history-dir", help="历史快照目录；默认与输出目录相同")
    sp.add_argument("--legacy-history", help="旧版诊断历史 JSONL 路径（仅作参考，不做指标环比）")
    sp.add_argument("--include-personal", action="store_true", help="展示个人事务标题与原话（默认隐藏）")
    sp.add_argument("--taxonomy", help="工作类型覆盖 JSON（families/override）")
    sp.add_argument("--share-safe", dest="share_safe", action="store_true",
                    help="对外分享模式：置空原话、标题与示例，仅保留结构化指标与引用编号")
    lp = sub.add_parser("list")
    lp.add_argument("--days", type=int, default=14)
    lp.add_argument("--workspace")
    ss = sub.add_parser("session")
    ss.add_argument("id")
    ss.add_argument("--full", action="store_true", help="全部展开（AI 回复与工具调用逐条）")
    ss.add_argument("--tools", action="store_true", help="逐条列出工具调用")
    ss.add_argument("--ai-chars", type=int, default=240)
    ss.add_argument("--max-turns", type=int, default=0)
    ss.add_argument("--focus", action="store_true", help="只看前 3 轮与纠错候选前后，适合长会话")
    fp = sub.add_parser("file")
    fp.add_argument("path")
    fp.add_argument("--full", action="store_true")
    gp = sub.add_parser("goldset", help="分类器一致率标定：TSV 每行「会话ID<TAB>人工标注板块」")
    gp.add_argument("tsv")
    gp.add_argument("--taxonomy")
    pp2 = sub.add_parser("purge", help="清空解析缓存（默认 ~/.workbuddy/ai-fde；不动原始日志）")
    pp2.add_argument("--yes", action="store_true", help="跳过确认直接执行")
    a = ap.parse_args()
    roots = a.root or DEFAULT_ROOTS
    if a.cmd == "scan":
        cmd_scan(a, roots)
    elif a.cmd == "list":
        cmd_list(a, roots)
    elif a.cmd == "session":
        print(render_transcript(find_session_file(a.id, roots), a.full, a.tools, a.ai_chars, a.max_turns, a.focus))
    elif a.cmd == "file":
        cmd_file(a)
    elif a.cmd == "goldset":
        cmd_goldset(a, roots)
    elif a.cmd == "purge":
        cmd_purge(a)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
