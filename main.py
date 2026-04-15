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
    await u.mess
