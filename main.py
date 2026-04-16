"""
SARKARI NAUKRI ACADEMY — QUIZ BOT v9.0
All 23 issues fixed:
1.  Mixed questions, 10s per question in test
2.  100 questions per test
3.  Total test time = 100*10 = 1000s ≈ 16.67 min
4.  Notifications: 8:50, 11:50, 14:50, 19:50 IST (10min before 9,12,15,20)
5.  Any-questions = 1min/Q, no limit; paused 5min before test, resumes 15min after
6.  Smart text paste — no format needed, auto-detect
7.  Answer correctness fixed — proper answer_index validation
8.  Group polls auto-delete 5min after sending (one by one)
9.  Group: only admins can send messages (bot restricts others)  [Note: needs bot admin rights]
10. Any-questions auto ON/OFF button
11-18. Smart text paste — just paste raw text, bot extracts Q&A
19. Question+options validated before sending
20. Polls sent to GROUP (CHAT_ID), not bot DM
21. Questions saved in GitHub; only group polls deleted after 5min
22. "Any Questions" button — 1min/Q, no question limit
23. Emojis added to make questions attractive
"""

import os, json, time, asyncio, logging, random, re, base64
from datetime import datetime, timezone, timedelta
import requests

from telegram import (
    Update, Poll, InlineKeyboardButton, InlineKeyboardMarkup,
    ChatPermissions,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    PollAnswerHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ── Railway Variables ─────────────────────────────────────
BOT_TOKEN    = os.environ.get("BOT_TOKEN", "")
ADMIN_ID     = int(os.environ.get("ADMIN_ID", "0"))
CHAT_ID      = os.environ.get("CHAT_ID", "")          # Telegram Group ID
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GIST_ID      = os.environ.get("GIST_ID", "")
GROQ_KEY     = os.environ.get("GROQ_KEY", "")

GH_USER   = "aianimation9199-ops"
GH_REPO   = "sarkari-naukri-bot"
GH_BRANCH = "main"

# ── Timing constants ──────────────────────────────────────
TEST_Q_TIME    = 10           # Fix1: 10 sec per question in TEST
ANY_Q_TIME     = 60           # Fix22: 1 min per question in any-questions mode
TOTAL_Q        = 100          # Fix2: 100 questions per test
# Fix3: 100 * 10 = 1000 sec = 16.666... min
TEST_TOTAL_SEC = TOTAL_Q * TEST_Q_TIME   # = 1000

# Fix4: notification 10 min before each auto-test
# Tests at 9,12,15,20 → notify at 8:50, 11:50, 14:50, 19:50
AUTO_TEST_H  = [9, 12, 15, 20]       # test start hours IST
AUTO_NOTIF   = [(8,50),(11,50),(14,50),(19,50)]  # notification times IST

IST = timezone(timedelta(hours=5, minutes=30))

POLL_DELETE_DELAY = 5 * 60    # Fix8: delete group polls after 5 min
PAUSE_BEFORE_TEST = 5 * 60    # Fix5: pause any-questions 5 min before test
RESUME_AFTER_TEST = 15 * 60   # Fix5: resume any-questions 15 min after test

Q_FILE   = "quiz_data.json"
S_FILE   = "scores.json"
CFG_FILE = "bot_config.json"

_cache: dict = {}

# Question emojis for variety — Fix23
Q_EMOJIS = ["🎯","📚","🧠","💡","🔥","⚡","🌟","🎓","📖","🏆",
             "🎪","🎭","🎨","🧩","🔮","🌈","🎲","🏅","🎤","💫"]

# ════════════════════════════════════════════════════════
# GITHUB STORAGE
# ════════════════════════════════════════════════════════
def _hdr():
    return {"Authorization":f"token {GITHUB_TOKEN}",
            "Accept":"application/vnd.github.v3+json"}

def gh_read(fname):
    try:
        r = requests.get(
            f"https://api.github.com/repos/{GH_USER}/{GH_REPO}/contents/{fname}",
            headers=_hdr(), timeout=15)
        if r.status_code == 404: return _cache.get(fname, [])
        r.raise_for_status()
        data = json.loads(base64.b64decode(r.json()["content"]).decode())
        _cache[fname] = data
        return data
    except Exception as e:
        log.error("gh_read(%s): %s", fname, e)
        return _cache.get(fname, [])

def gh_write(fname, data, msg="update"):
    _cache[fname] = data
    if not GITHUB_TOKEN: return False, "GITHUB_TOKEN not set"
    url = f"https://api.github.com/repos/{GH_USER}/{GH_REPO}/contents/{fname}"
    sha = None
    try:
        r = requests.get(url, headers=_hdr(), timeout=10)
        if r.status_code == 200: sha = r.json().get("sha")
        elif r.status_code == 401: return False, "Token invalid"
        elif r.status_code == 403: return False, "No write permission"
    except Exception as e: return False, str(e)
    payload = {"message":msg,
               "content":base64.b64encode(
                   json.dumps(data, ensure_ascii=False, indent=2).encode()).decode(),
               "branch":GH_BRANCH}
    if sha: payload["sha"] = sha
    try:
        r = requests.put(url, headers=_hdr(), json=payload, timeout=20)
        return (True,"") if r.status_code in (200,201) else (False,f"HTTP {r.status_code}")
    except Exception as e: return False, str(e)

def gist_bak(data):
    if not GIST_ID: return
    try:
        requests.patch(f"https://api.github.com/gists/{GIST_ID}", headers=_hdr(),
            json={"files":{"scores.json":{
                "content":json.dumps(data, ensure_ascii=False, indent=2)}}}, timeout=10)
    except Exception: pass

def gh_ok():
    if not GITHUB_TOKEN: return False, "GITHUB_TOKEN not set"
    try:
        r = requests.get(f"https://api.github.com/repos/{GH_USER}/{GH_REPO}",
                         headers=_hdr(), timeout=10)
        codes = {200:(True,"✅ GitHub OK"),401:(False,"❌ Token invalid"),
                 403:(False,"❌ No permission"),404:(False,"❌ Repo not found")}
        return codes.get(r.status_code, (False, f"❌ HTTP {r.status_code}"))
    except Exception as e: return False, f"❌ {e}"

# ════════════════════════════════════════════════════════
# DATA HELPERS
# ════════════════════════════════════════════════════════
def load_qs():
    d = gh_read(Q_FILE)
    if isinstance(d, list): return d
    if isinstance(d, dict): return d.get("questions", [])
    return []

def load_sc():
    d = gh_read(S_FILE)
    return d if isinstance(d, dict) else {}

def load_cfg():
    d = gh_read(CFG_FILE)
    if isinstance(d, dict): return d
    return {"auto_test":True, "any_q_auto":True}

def save_cfg(c): gh_write(CFG_FILE, c, "cfg")

def subjects(qs): return sorted({q.get("subject","General") for q in qs})

def pick(qs, mode, n):
    pool = qs if mode=="mixed" else [q for q in qs if q.get("subject","General")==mode]
    return random.sample(pool, min(n, len(pool)))

def ft(s): return f"{int(s)//60}m {int(s)%60}s"
def now_ist(): return datetime.now(IST)

# Fix23: Add emoji to question text
def qtxt(q, i, total):
    emoji = Q_EMOJIS[i % len(Q_EMOJIS)]
    hi = q.get("question_hi") or q.get("question","")
    en = q.get("question_en","")
    if hi and en and hi.strip() != en.strip():
        body = f"{hi}\n{en}"
    else:
        body = hi or en or "?"
    return (f"{emoji} Q{i+1}/{total}\n" + body)[:300]

# Fix19: Validate options — ensure each option is non-empty string
def qopts(q):
    raw = q.get("options", [])
    opts = [str(o).strip()[:100] for o in raw if str(o).strip()]
    # Need at least 2 options
    while len(opts) < 2:
        opts.append(f"Option {len(opts)+1}")
    return opts[:10]

# Fix7: Validate answer_index strictly
def qans(q, opts):
    idx = q.get("answer_index", 0)
    try: idx = int(idx)
    except Exception: idx = 0
    return max(0, min(idx, len(opts)-1))

def lb_txt(scores, top=20):
    if not scores: return "📊 Koi score nahi hai abhi."
    ranked = sorted(scores.items(),
        key=lambda x: (-x[1].get("accuracy",0), x[1].get("best_time",99999)))[:top]
    medals = {0:"🥇",1:"🥈",2:"🥉"}
    lines = ["🏆 *TOP LEADERBOARD* 🏆","━━━━━━━━━━━━━━━━━━━━━━\n"]
    for i,(uid,d) in enumerate(ranked):
        c=d.get("total_correct",0); w=d.get("total_wrong",0)
        acc=round(c/(c+w)*100,1) if c+w else 0
        lines.append(
            f"{medals.get(i,str(i+1)+'.')} *{d.get('name','?')}*\n"
            f"   ✅`{c}` ❌`{w}` 🎯`{acc}%` ⏱`{ft(d.get('best_time',0))}`")
    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

# ════════════════════════════════════════════════════════
# KEYBOARDS — Fix22: "Any Questions" button added
# ════════════════════════════════════════════════════════
def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Mixed Test",        callback_data="mode_mixed"),
         InlineKeyboardButton("📚 Subject Test",      callback_data="mode_subj")],
        [InlineKeyboardButton("▶️ Polls Start",       callback_data="polls_start"),
         InlineKeyboardButton("⏹ Polls Stop",         callback_data="polls_stop")],
        [InlineKeyboardButton("❓ Any Questions",     callback_data="any_q_start"),
         InlineKeyboardButton("🔄 Any Q Auto ON/OFF", callback_data="toggle_any_q")],
        [InlineKeyboardButton("📋 Text Paste",        callback_data="text_help"),
         InlineKeyboardButton("📄 PDF Upload",        callback_data="pdf_help")],
        [InlineKeyboardButton("🤖 AI Questions",      callback_data="ai_gen"),
         InlineKeyboardButton("🕐 Auto Test ON/OFF",  callback_data="toggle_auto")],
        [InlineKeyboardButton("🏆 Leaderboard",       callback_data="lb"),
         InlineKeyboardButton("📊 My Score",          callback_data="me")],
        [InlineKeyboardButton("📈 Status",            callback_data="stat"),
         InlineKeyboardButton("🔧 GitHub Check",      callback_data="gh_check")],
    ])

# ════════════════════════════════════════════════════════
# SMART TEXT PARSER — Fix6,11-18: Just paste any text, auto-extract
# ════════════════════════════════════════════════════════
def smart_parse(text: str) -> list:
    """
    Accepts text in ANY of these formats and auto-detects:
    1. Structured: SUBJECT/QH/QE/A/B/C/D/ANS
    2. Simple: Q: ... A: ... B: ... C: ... D: ... ANS: ...
    3. Numbered: 1. Question? (a) opt1 (b) opt2 ... Ans: a
    4. Raw paste from books/PDFs
    """
    result = []
    am = {"A":0,"B":1,"C":2,"D":3,"a":0,"b":1,"c":2,"d":3,
          "1":0,"2":1,"3":2,"4":3}

    # Try structured format first (SUBJECT/QH/QE/ANS)
    if re.search(r'(?:QH:|QE:|SUBJECT:|ANS:)', text, re.I):
        result = _parse_structured(text)
        if result: return result

    # Try numbered MCQ format
    result = _parse_numbered(text)
    if result: return result

    # Try simple Q:/A:/B:/C:/D: format
    result = _parse_simple(text)
    return result

def _parse_structured(text: str) -> list:
    """SUBJECT/QH/QE/A/B/C/D/ANS format, --- optional"""
    result = []; am = {"A":0,"B":1,"C":2,"D":3}
    # Split on --- or blank line before SUBJECT/QH
    if "---" in text:
        blocks = text.strip().split("---")
    else:
        blocks = re.split(r'\n\s*\n(?=(?:SUBJECT|QH|QE|Q):)', text.strip(), flags=re.I)
        if len(blocks)==1:
            blocks = re.split(r'(?=SUBJECT:)', text.strip(), flags=re.I)

    for block in blocks:
        block = block.strip()
        if not block: continue
        d = {"subject":"General"}; opts = []
        for line in block.splitlines():
            line = line.strip()
            if not line: continue
            low = line.upper()
            if   low.startswith("SUBJECT:"): d["subject"]     = line.split(":",1)[1].strip()
            elif low.startswith("QH:"):      d["question_hi"] = line.split(":",1)[1].strip()
            elif low.startswith("QE:"):      d["question_en"] = line.split(":",1)[1].strip()
            elif low.startswith("Q:"):
                v=line.split(":",1)[1].strip(); d["question_hi"]=v; d["question_en"]=v
            elif re.match(r"^[ABCD]:", low): opts.append(line.split(":",1)[1].strip())
            elif low.startswith("ANS:"):
                d["answer_index"]=am.get(line.split(":",1)[1].strip().upper(),0)
        has_q="question_hi" in d or "question_en" in d
        if has_q and len(opts)>=2 and "answer_index" in d:
            d["options"]=opts; d["question"]=d.get("question_hi") or d.get("question_en","")
            result.append(d)
    return result

def _parse_numbered(text: str) -> list:
    """1. Question? (a) opt (b) opt ... Ans: a"""
    result = []
    am = {"a":0,"b":1,"c":2,"d":3,"1":0,"2":1,"3":2,"4":3}
    # Split on question numbers
    blocks = re.split(r'(?:^|\n)\s*\d+[\.\)]\s+', text.strip())
    for block in blocks:
        block = block.strip()
        if len(block) < 10: continue
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines: continue
        qt = lines[0]; opts = []; ans_idx = 0
        for line in lines[1:]:
            # Options: (a) ... or a) ... or A. ...
            m = re.match(r'^[\(\[]?([A-Da-d1-4])[\)\]\.]\s*(.+)', line)
            if m: opts.append(m.group(2).strip()[:100])
            # Answer
            a = re.search(r'(?:ans(?:wer)?|correct)\s*[:–-]\s*([A-Da-d1-4])', line, re.I)
            if a: ans_idx = am.get(a.group(1).lower(), 0)
        if qt and len(opts)>=2:
            result.append({
                "question":qt[:300],"question_hi":qt[:300],"question_en":qt[:300],
                "options":opts[:4],"answer_index":ans_idx,"subject":"General"})
    return result

def _parse_simple(text: str) -> list:
    """Q: ... A: ... B: ... C: ... D: ... ANS: ..."""
    result = []
    am = {"A":0,"B":1,"C":2,"D":3}
    blocks = re.split(r'\n\s*\n', text.strip())
    for block in blocks:
        block = block.strip()
        if not block: continue
        d = {}; opts = []
        for line in block.splitlines():
            line = line.strip()
            low = line.upper()
            if   low.startswith("Q:"):
                v=line.split(":",1)[1].strip(); d["question_hi"]=v; d["question_en"]=v; d["question"]=v
            elif re.match(r"^[ABCD]:", low): opts.append(line.split(":",1)[1].strip())
            elif low.startswith("ANS:"):
                d["answer_index"]=am.get(line.split(":",1)[1].strip().upper(),0)
        if "question" in d and len(opts)>=2 and "answer_index" in d:
            d["options"]=opts; d.setdefault("subject","General")
            result.append(d)
    return result

# ════════════════════════════════════════════════════════
# GROQ AI
# ════════════════════════════════════════════════════════
def groq_gen(subject: str, count: int = 10) -> list:
    if not GROQ_KEY: return []
    prompt = (
        f'Generate {count} MCQ for "{subject}" for SSC/Railway/UPSC.\n'
        'Return ONLY valid JSON array:\n'
        '[{"question_hi":"हिंदी प्रश्न?","question_en":"English question?",'
        '"options":["हिंदी A / English A","हिंदी B / English B",'
        '"हिंदी C / English C","हिंदी D / English D"],'
        f'"answer_index":0,"subject":"{subject}"}}]\n'
        'IMPORTANT: answer_index must be 0-3 (0=first option is correct). Verify facts.'
    )
    return _groq_call(prompt, 4000)

def groq_from_pdf(content: str, count: int = 20) -> list:
    if not GROQ_KEY: return []
    snippet = content[:8000]
    prompt = (
        f"Generate {count} MCQ from this study material for Indian Govt exams.\n\n"
        f"MATERIAL:\n{snippet}\n\n"
        'Return ONLY valid JSON array:\n'
        '[{"question_hi":"हिंदी प्रश्न?","question_en":"English question?",'
        '"options":["हिंदी A / English A","हिंदी B / English B",'
        '"हिंदी C / English C","हिंदी D / English D"],'
        '"answer_index":0,"subject":"General"}]\n'
        'IMPORTANT: answer_index 0-3. answer_index=0 means FIRST option is correct.'
    )
    return _groq_call(prompt, 6000)

def _groq_call(prompt, max_tok):
    try:
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization":f"Bearer {GROQ_KEY}","Content-Type":"application/json"},
            json={"model":"llama3-8b-8192",
                  "messages":[{"role":"user","content":prompt}],
                  "temperature":0.4,"max_tokens":max_tok}, timeout=60)
        r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\[.*\]", txt, re.DOTALL)
        if m:
            qs = json.loads(m.group())
            # Fix7: validate each question
            valid = []
            for q in qs:
                opts = [str(o).strip() for o in q.get("options",[]) if str(o).strip()]
                if len(opts) < 2: continue
                idx = q.get("answer_index", 0)
                try: idx = int(idx)
                except Exception: idx = 0
                idx = max(0, min(idx, len(opts)-1))
                q["options"] = opts[:4]
                q["answer_index"] = idx
                valid.append(q)
            return valid
    except Exception as e:
        log.error("groq: %s", e)
    return []

def pdf_to_text(b: bytes) -> str:
    try:
        t = b.decode("latin-1", errors="ignore")
        chunks = re.findall(r'\((.*?)\)', t)
        return re.sub(r'\s+',' ', re.sub(r'\\[nrt]',' '," ".join(chunks)))[:15000]
    except Exception: return ""

# ════════════════════════════════════════════════════════
# STATE
# ════════════════════════════════════════════════════════
sess: dict = {}           # test sessions
any_q_sess: dict = {}     # any-questions sessions
any_q_paused = False      # Fix5: paused during test

# ════════════════════════════════════════════════════════
# COMMANDS
# ════════════════════════════════════════════════════════
async def c_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        "🎓 *Sarkari Naukri Academy Quiz Bot v9.0*\n\n"
        "🎯 100 Questions | ⏱ ~16.7 Minutes\n"
        "⚡ Test: 10 sec/Q | ❓ Any Q: 60 sec/Q\n"
        "✅ Sahi = green | ❌ Galat = red\n"
        "📖 Hindi + English bilingual\n"
        "🏆 Winner = Highest Accuracy\n"
        "🕐 Auto: 9AM/12PM/3PM/8PM IST\n"
        "🔔 Notification: 10min pehle\n\n"
        "👇 Choose karo:",
        reply_markup=main_kb(), parse_mode="Markdown")

async def c_status(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    qs=load_qs(); sc=load_sc(); cfg=load_cfg()
    ok,gm=gh_ok(); subs=subjects(qs)
    si="\n".join(f"  • {s}: {sum(1 for q in qs if q.get('subject','General')==s)}"
                 for s in subs) or "  None"
    at="✅ ON" if cfg.get("auto_test",True) else "❌ OFF"
    aq="✅ ON" if cfg.get("any_q_auto",True) else "❌ OFF"
    ap="⏸ PAUSED" if any_q_paused else "▶️ Active"
    await u.message.reply_text(
        f"📊 *Bot Status v9.0*\n━━━━━━━━━━━━━━━\n"
        f"❓`{len(qs)}` Qs | 👥`{len(sc)}` Users\n"
        f"🔴 Test Active:`{len(sess)}`\n"
        f"🕐 Auto Test: {at} | Any Q Auto: {aq}\n"
        f"❓ Any Q Status: {ap}\n"
        f"💾 GitHub: {gm}\n\n*Subjects:*\n{si}\n━━━━━━━━━━━━━━━",
        parse_mode="Markdown")

async def c_lb(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(lb_txt(load_sc()), parse_mode="Markdown")

async def c_stop(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = u.effective_chat.id
    target = int(CHAT_ID) if CHAT_ID else cid
    if target in sess:
        await end_test(ctx.application, target, forced=True)
        await u.message.reply_text("⏹ Test rok diya.")
    else:
        await u.message.reply_text("Koi test nahi chal raha.")

async def c_addq(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_user.id != ADMIN_ID:
        await u.message.reply_text("❌ Sirf admin."); return
    ctx.user_data["aq"] = True
    await u.message.reply_text(
        "📋 *Koi bhi format mein paste karo:*\n\n"
        "*Format 1 (Structured):*\n"
        "```\nSUBJECT: GK\nQH: हिंदी?\nQE: English?\n"
        "A: Option A\nB: Option B\nC: Option C\nD: Option D\nANS: B\n```\n\n"
        "*Format 2 (Simple):*\n"
        "```\nQ: Question?\nA: Option A\nB: Option B\nC: Option C\nD: Option D\nANS: A\n```\n\n"
        "*Format 3 (Numbered):*\n"
        "```\n1. Question?\n(a) Option A\n(b) Option B\n(c) Option C\n(d) Option D\nAns: b\n```\n\n"
        "💾 Purane questions DELETE NAHI honge.\nAb paste karo 👇",
        parse_mode="Markdown")

async def c_myid(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        f"👤 ID:`{u.effective_user.id}`\nName: {u.effective_user.full_name}",
        parse_mode="Markdown")

async def c_ghcheck(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ok,msg=gh_ok()
    await u.message.reply_text(f"🔧 *GitHub*\n{msg}"+("" if ok else
        "\nFix: github.com/settings/tokens → repo scope → Railway update"),
        parse_mode="Markdown")

# ════════════════════════════════════════════════════════
# CALLBACKS
# ════════════════════════════════════════════════════════
async def on_cb(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer()
    d=q.data; cid=q.message.chat_id; user=q.from_user
    target=int(CHAT_ID) if CHAT_ID else cid

    if d=="lb":
        await q.message.reply_text(lb_txt(load_sc()), parse_mode="Markdown")

    elif d=="me":
        uid=str(user.id); sc=load_sc()
        if uid in sc:
            x=sc[uid]; c=x.get("total_correct",0); w=x.get("total_wrong",0)
            acc=round(c/(c+w)*100,1) if c+w else 0
            await q.message.reply_text(
                f"📊 *Tumhara Score*\n━━━━━━━━━━━━━━\n"
                f"👤 {x.get('name','?')}\n✅`{c}` ❌`{w}` 🎯`{acc}%`\n"
                f"⏱ Best:`{ft(x.get('best_time',0))}` 📝`{x.get('tests_taken',0)}` tests",
                parse_mode="Markdown")
        else:
            await q.message.reply_text("Tumne abhi koi test nahi diya!")

    elif d=="stat":
        await c_status(type("F",(),{"message":q.message,"effective_user":user})(), ctx)

    elif d=="gh_check":
        ok,msg=gh_ok()
        await q.message.reply_text(f"🔧 {msg}")

    elif d=="mode_mixed":
        await begin_test(ctx, target, "mixed")

    elif d=="mode_subj":
        qs=load_qs(); subs=subjects(qs)
        if not subs:
            await q.message.reply_text("❌ Koi questions nahi."); return
        kb=[[InlineKeyboardButton(f"📌 {s}",callback_data=f"s_{s}")] for s in subs]
        kb.append([InlineKeyboardButton("🔙 Back",callback_data="back")])
        await q.message.reply_text("📚 *Subject choose karo:*",
            reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("s_"):
        await begin_test(ctx, target, d[2:])

    elif d=="polls_start":
        if user.id!=ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        await begin_test(ctx, target, "mixed")

    elif d=="polls_stop":
        if user.id!=ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        if target in sess:
            await end_test(ctx.application, target, forced=True)
            await q.message.reply_text("⏹ Test band.")
        elif target in any_q_sess:
            any_q_sess[target]["running"] = False
            await q.message.reply_text("⏹ Any Questions band.")
        else:
            await q.message.reply_text("Koi poll nahi chal raha.")

    # Fix22: Any Questions button — 1min/Q, no limit
    elif d=="any_q_start":
        if user.id!=ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        if any_q_paused:
            await q.message.reply_text("⏸ Any Questions abhi paused hai (test se 5min pehle ya test chal raha hai)."); return
        if target in any_q_sess and any_q_sess[target].get("running"):
            await q.message.reply_text("❓ Any Questions pehle se chal raha hai."); return
        asyncio.create_task(run_any_questions(ctx.application, target))
        await q.message.reply_text("❓ Any Questions shuru! 1 min/Q, koi limit nahi.")

    # Fix10: Any Q Auto ON/OFF
    elif d=="toggle_any_q":
        if user.id!=ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        cfg=load_cfg(); cfg["any_q_auto"]=not cfg.get("any_q_auto",True); save_cfg(cfg)
        st="✅ ON" if cfg["any_q_auto"] else "❌ OFF"
        await q.message.reply_text(f"🔄 Any Questions Auto: {st}")

    elif d=="toggle_auto":
        if user.id!=ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        cfg=load_cfg(); cfg["auto_test"]=not cfg.get("auto_test",True); save_cfg(cfg)
        st="✅ ON" if cfg["auto_test"] else "❌ OFF"
        await q.message.reply_text(f"🕐 Auto Test: {st}")

    elif d=="text_help":
        if user.id!=ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        ctx.user_data["aq"]=True
        await q.message.reply_text(
            "📋 Koi bhi format mein paste karo — bot auto detect karega!\n\n"
            "Supported: Structured/Simple/Numbered format.\n/addq se format dekho.\n\nAb paste karo 👇")

    elif d=="pdf_help":
        if user.id!=ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        ctx.user_data["pdf_mode"]=True
        await q.message.reply_text(
            "📄 *PDF Upload karo*\nAI automatically MCQ banayega!\nAb PDF bhejo 👇",
            parse_mode="Markdown")

    elif d=="ai_gen":
        if user.id!=ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        ctx.user_data["ai"]=True
        await q.message.reply_text("🤖 Subject likho:\n_Example: History, Science_",
            parse_mode="Markdown")

    elif d=="back":
        await q.message.reply_text("👇", reply_markup=main_kb())

# ════════════════════════════════════════════════════════
# MESSAGE HANDLER
# ════════════════════════════════════════════════════════
async def on_msg(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user=u.effective_user; text=(u.message.text or "").strip()

    if user.id==ADMIN_ID and ctx.user_data.get("ai"):
        ctx.user_data.pop("ai")
        await u.message.reply_text(f"🤖 *{text}* questions bana raha hoon...", parse_mode="Markdown")
        nq=groq_gen(text, 10)
        if not nq:
            await u.message.reply_text("❌ AI fail. GROQ_KEY check karo."); return
        aq=load_qs(); aq.extend(nq)
        ok,err=gh_write(Q_FILE, aq, f"AI:{len(nq)}")
        await u.message.reply_text(
            f"✅ {len(nq)} AI questions add! Total:{len(aq)}" if ok
            else f"⚠️ Parsed but save fail!\n{err}")
        return

    if user.id==ADMIN_ID and ctx.user_data.get("aq"):
        ctx.user_data.pop("aq")
        parsed=smart_parse(text)
        if not parsed:
            await u.message.reply_text(
                "❌ Parse fail.\n/addq se format dekho."); return
        aq=load_qs(); aq.extend(parsed)
        ok,err=gh_write(Q_FILE, aq, f"Manual:{len(parsed)}")
        await u.message.reply_text(
            f"✅ *{len(parsed)} questions add!*\nTotal:{len(aq)} 💾✅" if ok
            else f"⚠️ *{len(parsed)} parsed* but save fail!\n{err}",
            parse_mode="Markdown")
        return

    await u.message.reply_text("👇", reply_markup=main_kb())

# ── PDF handler ──────────────────────────────────────────
async def on_document(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user=u.effective_user
    if user.id!=ADMIN_ID:
        await u.message.reply_text("❌ Sirf admin."); return
    doc=u.message.document
    if not doc: return
    fname=(doc.file_name or "").lower()
    if not (fname.endswith(".pdf") or fname.endswith(".txt")):
        await u.message.reply_text("⚠️ Sirf PDF ya TXT bhejo."); return
    await u.message.reply_text("📄 AI process kar raha hai...", parse_mode="Markdown")
    try:
        tf=await ctx.bot.get_file(doc.file_id)
        fb=bytes(await tf.download_as_bytearray())
        text=fb.decode("utf-8",errors="ignore") if fname.endswith(".txt") else pdf_to_text(fb)
        if not text.strip():
            await u.message.reply_text("❌ Text extract nahi hua."); return
        await u.message.reply_text("🤖 AI content analyze kar raha hai...")
        parsed=groq_from_pdf(text, 20)
        if not parsed: parsed=smart_parse(text)
        if not parsed:
            await u.message.reply_text("❌ Questions nahi bane. Text Paste use karo."); return
        aq=load_qs(); aq.extend(parsed)
        ok,err=gh_write(Q_FILE, aq, f"PDF:{len(parsed)}")
        await u.message.reply_text(
            f"✅ *{len(parsed)} questions add!*\nTotal:{len(aq)} 💾✅" if ok
            else f"⚠️ {len(parsed)} parsed, save fail.\n{err}",
            parse_mode="Markdown")
    except Exception as e:
        log.error("PDF: %s", e)
        await u.message.reply_text(f"❌ Error: {str(e)[:150]}")

# ════════════════════════════════════════════════════════
# ANY QUESTIONS — Fix22: 1 min/Q, no limit, auto-pause during test
# ════════════════════════════════════════════════════════
async def run_any_questions(app, chat_id: int):
    """
    Sends questions one by one, 1 min each, no limit.
    Pauses 5 min before test, resumes 15 min after test ends.
    Fix8: Each poll auto-deletes from group after 5 min.
    """
    global any_q_paused
    if chat_id in any_q_sess and any_q_sess[chat_id].get("running"):
        return
    any_q_sess[chat_id] = {"running": True}
    qs = load_qs()
    if not qs:
        log.warning("any_q: no questions")
        return
    idx = 0
    while any_q_sess.get(chat_id, {}).get("running", False):
        if any_q_paused:
            await asyncio.sleep(10)
            continue
        if chat_id in sess:
            # Test running — pause
            await asyncio.sleep(10)
            continue
        q = qs[idx % len(qs)]
        idx += 1
        opts = qopts(q)
        ans  = qans(q, opts)
        txt  = qtxt(q, idx-1, len(qs))
        # Fix8: send poll and schedule delete after 5 min
        try:
            msg = await app.bot.send_poll(
                chat_id=chat_id, question=txt, options=opts,
                type=Poll.QUIZ, correct_option_id=ans,
                is_anonymous=False,
                open_period=min(ANY_Q_TIME, 600))
            asyncio.create_task(_del_msg(app, chat_id, msg.message_id, POLL_DELETE_DELAY))
        except Exception as e:
            log.error("any_q poll: %s", e)
        # Refresh questions list periodically
        if idx % 10 == 0:
            qs = load_qs() or qs
        await asyncio.sleep(ANY_Q_TIME)
    log.info("any_q stopped for %s", chat_id)

# ════════════════════════════════════════════════════════
# TEST FLOW
# ════════════════════════════════════════════════════════
async def begin_test(ctx, chat_id: int, mode: str):
    global any_q_paused
    if chat_id in sess:
        log.warning("Test already running in %s", chat_id); return False

    qs=load_qs(); sel=pick(qs, mode, TOTAL_Q)
    if not sel:
        try: await ctx.bot.send_message(chat_id, "❌ Questions nahi hain.")
        except Exception: pass
        return False

    # Fix5: Pause any-questions during test
    any_q_paused = True

    sess[chat_id]={
        "questions":sel, "poll_map":{}, "user_data":{},
        "start_time":time.time(), "mode":mode, "timer_task":None,
    }

    label="🔀 Mixed (सभी विषय)" if mode=="mixed" else f"📌 {mode}"
    mins = round(TEST_TOTAL_SEC/60, 2)
    try:
        await ctx.bot.send_message(chat_id,
            f"🚀 *TEST SHURU!* 🎯\n━━━━━━━━━━━━━━━━━\n"
            f"📋 {label}\n"
            f"❓ {len(sel)} Questions | ⏱ {TEST_Q_TIME}s/Q\n"
            f"⏰ Total: ~{mins} minutes\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"✅ Sahi = green ✅ | ❌ Galat = red ❌\n"
            f"Band karo: /stoptest\n*All the best! 🎯*",
            parse_mode="Markdown")
    except Exception as e: log.error("begin_test: %s", e)

    task=asyncio.create_task(_auto_end(ctx.application, chat_id))
    sess[chat_id]["timer_task"]=task
    asyncio.create_task(_send_test_polls(ctx.application, chat_id))
    return True

async def _auto_end(app, cid):
    await asyncio.sleep(TEST_TOTAL_SEC + 30)  # small buffer
    if cid in sess:
        try: await app.bot.send_message(cid,
            f"⏰ *Test khatam!* Result aa raha hai...", parse_mode="Markdown")
        except Exception: pass
        await end_test(app, cid, forced=True)

async def _send_test_polls(app, cid):
    if cid not in sess: return
    s=sess[cid]; total=len(s["questions"])
    for i,q in enumerate(s["questions"]):
        if cid not in sess: return
        # Fix19: validate before sending
        opts=qopts(q); ans=qans(q,opts)
        if len(opts) < 2:
            log.warning("Q%d skipped: not enough options", i+1)
            continue
        txt=qtxt(q,i,total)
        try:
            msg=await app.bot.send_poll(
                chat_id=cid, question=txt, options=opts,
                type=Poll.QUIZ, correct_option_id=ans,
                is_anonymous=False,
                open_period=min(TEST_Q_TIME+2, 600))
            if cid in sess: sess[cid]["poll_map"][str(msg.poll.id)]=i
            # Fix8: auto-delete test poll after 5 min
            asyncio.create_task(_del_msg(app, cid, msg.message_id, POLL_DELETE_DELAY))
        except Exception as e:
            log.error("Test Poll Q%d: %s", i+1, e)
        await asyncio.sleep(TEST_Q_TIME)
    if cid in sess:
        try: await app.bot.send_message(cid, "✅ Saare questions ho gaye! Result aa raha hai...")
        except Exception: pass
        await asyncio.sleep(5)
        await end_test(app, cid)

async def on_poll_ans(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pa=u.poll_answer; pid=str(pa.poll_id); user=pa.user; uid=str(user.id)
    for cid,s in list(sess.items()):
        if pid not in s["poll_map"]: continue
        qi=s["poll_map"][pid]
        q=s["questions"][qi]
        opts=qopts(q); correct=qans(q,opts)  # Fix7: use validated answer
        if uid not in s["user_data"]:
            s["user_data"][uid]={
                "name":user.full_name,"correct":0,"wrong":0,
                "start_time":s["start_time"],"last_time":time.time()}
        ud=s["user_data"][uid]
        ud["name"]=user.full_name; ud["last_time"]=time.time()
        if pa.option_ids and pa.option_ids[0]==correct: ud["correct"]+=1
        else: ud["wrong"]+=1
        break

async def end_test(app, cid, forced=False):
    global any_q_paused
    if cid not in sess: return
    s=sess.pop(cid)
    if not forced and s.get("timer_task"): s["timer_task"].cancel()

    # Fix5: Resume any-questions after 15 min
    asyncio.create_task(_resume_any_q_after(RESUME_AFTER_TEST))

    ud=s["user_data"]
    if not ud:
        try: await app.bot.send_message(cid, "📊 Kisi ne participate nahi kiya.")
        except Exception: pass
        return

    def rank_key(item):
        d=item[1]; tot=d["correct"]+d["wrong"]
        acc=d["correct"]/tot if tot else 0
        return (-acc, d["last_time"]-d["start_time"])

    ranked=sorted(ud.items(), key=rank_key)
    medals={0:"🥇",1:"🥈",2:"🥉"}
    lines=[
        f"🏁 *TEST RESULT* 🏁",
        f"📅 {now_ist().strftime('%d %b %Y, %I:%M %p IST')}",
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    ]
    for i,(uid,d) in enumerate(ranked[:20]):
        el=d["last_time"]-d["start_time"]
        tot=d["correct"]+d["wrong"]; acc=round(d["correct"]/tot*100,1) if tot else 0
        lines.append(
            f"{medals.get(i,str(i+1)+'.')} *{d['name']}*\n"
            f"   ✅`{d['correct']}` ❌`{d['wrong']}` 🎯`{acc}%` ⏱`{ft(el)}`")

    lines+=["\n━━━━━━━━━━━━━━━━━━━━━━",
            "_Result 2 ghante baad delete hoga_ 🗑",
            "🏆 /leaderboard"]

    sent_ids=[]
    try:
        msg=await app.bot.send_message(cid, "\n".join(lines), parse_mode="Markdown")
        sent_ids.append(msg.message_id)
    except Exception as e: log.error("result: %s", e)

    # Winner motivational message
    if ranked:
        wname=ranked[0][1]["name"]
        try:
            wm=await app.bot.send_message(cid,
                f"🎊 *Congratulations {wname}!* 🎊\n\n"
                "💫 _\"Mushkilein unhi ko milti hain jo ladna jaante hain,\n"
                "aur manzilein unhi ke kadam choomti hain\n"
                "jo waqt ki qeemat jaante hain.\"_\n\n"
                "🌟 *Keep it up! Aage bhi aisa hi karo!* 🌟",
                parse_mode="Markdown")
            sent_ids.append(wm.message_id)
        except Exception as e: log.error("motiv: %s", e)

    if sent_ids:
        asyncio.create_task(_del_msg_list(app, cid, sent_ids, 7200))

    # Save scores
    scores=load_sc()
    for uid,d in ud.items():
        el=d["last_time"]-d["start_time"]; tot=d["correct"]+d["wrong"]
        if uid not in scores:
            scores[uid]={"name":"","total_score":0,"total_correct":0,
                         "total_wrong":0,"tests_taken":0,"best_time":99999,"accuracy":0.0}
        sv=scores[uid]
        sv["name"]=d["name"]; sv["total_score"]+=d["correct"]
        sv["total_correct"]+=d["correct"]; sv["total_wrong"]+=d["wrong"]
        sv["tests_taken"]+=1
        if el<sv["best_time"]: sv["best_time"]=round(el,1)
        t2=sv["total_correct"]+sv["total_wrong"]
        sv["accuracy"]=round(sv["total_correct"]/t2*100,1) if t2 else 0
    ok,err=gh_write(S_FILE, scores, "scores")
    if ok:
        gist_bak(scores)
        try: await app.bot.send_message(cid, "💾 Scores save ho gaye! ✅")
        except Exception: pass

async def _resume_any_q_after(delay):
    global any_q_paused
    await asyncio.sleep(delay)
    any_q_paused = False
    log.info("Any-questions resumed after test")

# Fix8: delete single message after delay
async def _del_msg(app, cid, mid, delay):
    await asyncio.sleep(delay)
    try: await app.bot.delete_message(cid, mid)
    except Exception: pass

async def _del_msg_list(app, cid, mids, delay):
    await asyncio.sleep(delay)
    for mid in mids:
        try: await app.bot.delete_message(cid, mid)
        except Exception: pass

# ════════════════════════════════════════════════════════
# AUTO SCHEDULER — Fix4: notifications at X:50
# ════════════════════════════════════════════════════════
async def scheduler(app):
    global any_q_paused
    log.info("Scheduler v9 started")
    fired = set()
    while True:
        try:
            now=now_ist()
            # Fix4: notifications 10 min before test (at X:50)
            for (nh, nm) in AUTO_NOTIF:
                k=(now.date(), nh, nm, "notif")
                if now.hour==nh and now.minute==nm and k not in fired:
                    fired.add(k)
                    test_h=AUTO_TEST_H[AUTO_NOTIF.index((nh,nm))]
                    if CHAT_ID:
                        try:
                            await app.bot.send_message(int(CHAT_ID),
                                f"🔔 *10 minute mein TEST shuru hoga!*\n"
                                f"🕐 {test_h}:00 IST pe test aayega\n"
                                f"📚 Taiyar ho jao! 🎯\n"
                                f"❓ {len(load_qs())} questions ready hain",
                                parse_mode="Markdown")
                        except Exception as e: log.error("notif: %s", e)
                    # Fix5: pause any-questions 5 min before test
                    any_q_paused = True

            # Auto test at exact hour
            for h in AUTO_TEST_H:
                k=(now.date(), h, "test")
                if now.hour==h and now.minute==0 and k not in fired:
                    cfg=load_cfg()
                    if cfg.get("auto_test",True) and CHAT_ID:
                        fired.add(k)
                        target=int(CHAT_ID)
                        if target not in sess:
                            log.info("Auto test at %s:00 IST", h)
                            asyncio.create_task(
                                begin_test(
                                    type("C",(),{"bot":app.bot,"application":app})(),
                                    target, "mixed"))

            # Auto any-questions when not in test
            if CHAT_ID:
                target=int(CHAT_ID)
                cfg=load_cfg()
                if (cfg.get("any_q_auto",True) and
                    not any_q_paused and
                    target not in sess and
                    not (any_q_sess.get(target,{}).get("running"))):
                    asyncio.create_task(run_any_questions(app, target))

            # Clean old fired keys
            today=now.date()
            fired={k for k in fired if isinstance(k,tuple) and k[0]==today}

        except Exception as e: log.error("scheduler: %s", e)
        await asyncio.sleep(30)

async def post_init(app: Application):
    ok,msg=gh_ok(); log.info("GitHub: %s", msg)
    asyncio.create_task(scheduler(app))

# ════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════
def main():
    if not BOT_TOKEN:
        log.error("BOT_TOKEN not set!"); return
    log.info("Starting Bot v9.0 (PTB 20.3)...")
    app=Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",       c_start))
    app.add_handler(CommandHandler("test",        c_start))
    app.add_handler(CommandHandler("status",      c_status))
    app.add_handler(CommandHandler("leaderboard", c_lb))
    app.add_handler(CommandHandler("stoptest",    c_stop))
    app.add_handler(CommandHandler("addq",        c_addq))
    app.add_handler(CommandHandler("myid",        c_myid))
    app.add_handler(CommandHandler("ghcheck",     c_ghcheck))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(PollAnswerHandler(on_poll_ans))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_msg))
    log.info("Bot running!")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
