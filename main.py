"""
SARKARI NAUKRI ACADEMY — QUIZ BOT v8.0
=======================================
Changes from v7:
1. Test timer = 10 seconds per question
2. Normal/any question timer = 1 minute (60s)
3. "Sab Delete" button REMOVED from main menu (safety)
4. Text paste: NO --- separator needed (questions auto-split)
5. 10-min advance notification in group before test
6. Winner = highest ACCURACY (not score); tie-break = time
7. Winner gets motivational message
8. PDF → Groq AI reads & generates proper MCQ questions
9. All previous features intact
"""

import os, json, time, asyncio, logging, random, re, base64
from datetime import datetime, timezone, timedelta
import requests

from telegram import Update, Poll, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    PollAnswerHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────
BOT_TOKEN    = os.environ.get("BOT_TOKEN", "")
ADMIN_ID     = int(os.environ.get("ADMIN_ID", "0"))
CHAT_ID      = os.environ.get("CHAT_ID", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GIST_ID      = os.environ.get("GIST_ID", "")
GROQ_KEY     = os.environ.get("GROQ_KEY", "")

GH_USER   = "aianimation9199-ops"
GH_REPO   = "sarkari-naukri-bot"
GH_BRANCH = "main"

# Timings
TEST_Q_TIME   = 10          # FIX1: 10 sec per question in TEST mode
NORMAL_Q_TIME = 60          # FIX2: 1 min for normal/manual polls
TEST_TOTAL    = 10 * 60     # 10 minutes total test

# Auto test schedule IST hours
AUTO_HOURS = [9, 12, 15, 20]
IST = timezone(timedelta(hours=5, minutes=30))

Q_FILE   = "quiz_data.json"
S_FILE   = "scores.json"
CFG_FILE = "bot_config.json"

_cache: dict = {}

# ════════════════════════════════════════════════════════
# GITHUB
# ════════════════════════════════════════════════════════
def _hdr():
    return {"Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"}

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
        elif r.status_code == 401: return False, "Token invalid/expired"
        elif r.status_code == 403: return False, "No write permission"
    except Exception as e:
        return False, str(e)
    payload = {"message": msg,
               "content": base64.b64encode(
                   json.dumps(data, ensure_ascii=False, indent=2).encode()).decode(),
               "branch": GH_BRANCH}
    if sha: payload["sha"] = sha
    try:
        r = requests.put(url, headers=_hdr(), json=payload, timeout=20)
        if r.status_code in (200, 201): return True, ""
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)

def gist_bak(data):
    if not GIST_ID: return
    try:
        requests.patch(f"https://api.github.com/gists/{GIST_ID}", headers=_hdr(),
            json={"files": {"scores.json": {
                "content": json.dumps(data, ensure_ascii=False, indent=2)}}}, timeout=10)
    except Exception: pass

def gh_ok():
    if not GITHUB_TOKEN: return False, "GITHUB_TOKEN not set"
    try:
        r = requests.get(f"https://api.github.com/repos/{GH_USER}/{GH_REPO}",
                         headers=_hdr(), timeout=10)
        if r.status_code == 200: return True, "✅ GitHub OK"
        if r.status_code == 401: return False, "❌ Token invalid/expired"
        if r.status_code == 403: return False, "❌ No permission"
        if r.status_code == 404: return False, "❌ Repo not found"
        return False, f"❌ HTTP {r.status_code}"
    except Exception as e:
        return False, f"❌ {e}"

# ════════════════════════════════════════════════════════
# DATA
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
    return d if isinstance(d, dict) else {"auto_enabled": True}

def save_cfg(c): gh_write(CFG_FILE, c, "cfg")

def subjects(qs): return sorted({q.get("subject","General") for q in qs})

def pick(qs, mode, n):
    pool = qs if mode == "mixed" else [q for q in qs if q.get("subject","General")==mode]
    return random.sample(pool, min(n, len(pool)))

def ft(s): return f"{int(s)//60}m {int(s)%60}s"
def now_ist(): return datetime.now(IST)

def qtxt(q, i, total):
    hi = q.get("question_hi") or q.get("question","")
    en = q.get("question_en","")
    body = f"{hi}\n{en}" if hi and en and hi.strip()!=en.strip() else hi or en or "?"
    return (f"Q{i+1}/{total}: "+body)[:300]

def qopts(q): return [str(o)[:100] for o in q.get("options",["A","B","C","D"])[:10]]

# FIX6: Winner = highest accuracy; tie = least time
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
            f"   ✅`{c}` ❌`{w}` ⏱`{ft(d.get('best_time',0))}` 🎯`{acc}%`")
    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

# FIX3: "Sab Delete" REMOVED from main_kb
def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Mixed Test",       callback_data="mode_mixed"),
         InlineKeyboardButton("📚 Subject Test",     callback_data="mode_subj")],
        [InlineKeyboardButton("▶️ Polls Start",      callback_data="polls_start"),
         InlineKeyboardButton("⏹ Polls Stop",        callback_data="polls_stop")],
        [InlineKeyboardButton("📋 Text Paste",       callback_data="text_help"),
         InlineKeyboardButton("📄 PDF Upload",       callback_data="pdf_help")],
        [InlineKeyboardButton("🤖 AI Questions",     callback_data="ai_gen"),
         InlineKeyboardButton("🕐 Auto Test ON/OFF", callback_data="toggle_auto")],
        [InlineKeyboardButton("🏆 Leaderboard",      callback_data="lb"),
         InlineKeyboardButton("📊 My Score",         callback_data="me")],
        [InlineKeyboardButton("📈 Status",           callback_data="stat"),
         InlineKeyboardButton("🔧 GitHub Check",     callback_data="gh_check")],
    ])

# Session state
sess: dict = {}

# ════════════════════════════════════════════════════════
# GROQ AI
# ════════════════════════════════════════════════════════
def groq_gen(subject: str, count: int = 10) -> list:
    if not GROQ_KEY: return []
    prompt = (
        f'Generate {count} MCQ for "{subject}" for SSC/Railway/UPSC.\n'
        'Return ONLY valid JSON array:\n'
        '[{"question_hi":"हिंदी?","question_en":"English?",'
        '"options":["हिंदी A / English A","हिंदी B / English B",'
        '"हिंदी C / English C","हिंदी D / English D"],'
        f'"answer_index":0,"subject":"{subject}"}}]\n'
        'Rules: answer_index 0-based, facts correct, bilingual options.'
    )
    try:
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization":f"Bearer {GROQ_KEY}","Content-Type":"application/json"},
            json={"model":"llama3-8b-8192",
                  "messages":[{"role":"user","content":prompt}],
                  "temperature":0.5,"max_tokens":4000}, timeout=30)
        r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\[.*\]", txt, re.DOTALL)
        if m: return json.loads(m.group())
    except Exception as e:
        log.error("groq: %s", e)
    return []

# FIX8: PDF → Groq reads content and generates proper MCQ
def groq_from_pdf_text(content: str, max_q: int = 20) -> list:
    """Send PDF text to Groq, get proper MCQ questions back."""
    if not GROQ_KEY: return []
    # Truncate content to fit in context
    snippet = content[:8000]
    prompt = (
        f"Read this study material and generate {max_q} MCQ questions from it "
        f"for Indian Govt exams (SSC/Railway/UPSC).\n\n"
        f"MATERIAL:\n{snippet}\n\n"
        "Return ONLY valid JSON array, no extra text:\n"
        '[{"question_hi":"हिंदी में प्रश्न?","question_en":"Question in English?",'
        '"options":["हिंदी A / English A","हिंदी B / English B",'
        '"हिंदी C / English C","हिंदी D / English D"],'
        '"answer_index":0,"subject":"General"}]'
    )
    try:
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization":f"Bearer {GROQ_KEY}","Content-Type":"application/json"},
            json={"model":"llama3-8b-8192",
                  "messages":[{"role":"user","content":prompt}],
                  "temperature":0.4,"max_tokens":6000}, timeout=60)
        r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\[.*\]", txt, re.DOTALL)
        if m: return json.loads(m.group())
    except Exception as e:
        log.error("groq_pdf: %s", e)
    return []

def pdf_to_text(b: bytes) -> str:
    try:
        t = b.decode("latin-1", errors="ignore")
        chunks = re.findall(r'\((.*?)\)', t)
        r2 = re.sub(r'\s+', ' ', re.sub(r'\\[nrt]', ' ', " ".join(chunks)))
        return r2[:15000]
    except Exception:
        return ""

# FIX4: Parse questions WITHOUT needing --- separator
def parse_qs(text: str) -> list:
    """
    Smart parser — works with OR without --- separator.
    Splits on blank lines or SUBJECT: keyword.
    """
    result = []; am = {"A":0,"B":1,"C":2,"D":3}

    # If --- present, use it; otherwise split on double newline or SUBJECT:
    if "---" in text:
        blocks = text.strip().split("---")
    else:
        # Split on blank line between questions
        blocks = re.split(r'\n\s*\n(?=(?:SUBJECT:|QH:|QE:|Q:))', text.strip())
        if len(blocks) == 1:
            # Try splitting on SUBJECT: keyword
            blocks = re.split(r'(?=SUBJECT:)', text.strip())

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
        has_q = "question_hi" in d or "question_en" in d
        if has_q and len(opts)>=2 and "answer_index" in d:
            d["options"]=opts; d["question"]=d.get("question_hi") or d.get("question_en","")
            result.append(d)
    return result

# ════════════════════════════════════════════════════════
# COMMANDS
# ════════════════════════════════════════════════════════
async def c_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        "🎓 *Sarkari Naukri Academy Quiz Bot v8.0*\n\n"
        "• 100 Questions | ⏱ 10 Minutes\n"
        "• Test: 10 sec/Q | Normal: 60 sec/Q\n"
        "• ✅ Sahi = green | ❌ Galat = red\n"
        "• 📖 Hindi + English bilingual\n"
        "• 🏆 Winner = Highest Accuracy\n"
        "• 🕐 Auto: 9AM/12PM/3PM/8PM IST\n\n"
        "👇 Choose karo:",
        reply_markup=main_kb(), parse_mode="Markdown")

async def c_status(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    qs=load_qs(); sc=load_sc(); cfg=load_cfg()
    ok,gm=gh_ok(); subs=subjects(qs)
    si="\n".join(f"  • {s}: {sum(1 for q in qs if q.get('subject','General')==s)}"
                 for s in subs) or "  None"
    auto="✅ ON" if cfg.get("auto_enabled",True) else "❌ OFF"
    await u.message.reply_text(
        f"📊 *Bot Status*\n━━━━━━━━━━━━━━━\n"
        f"❓`{len(qs)}` Qs | 👥`{len(sc)}` Users\n"
        f"🔴 Active:`{len(sess)}` | ⏱ Test:`{TEST_Q_TIME}s`/Q\n"
        f"🕐 Auto: {auto} | Next: 9AM/12PM/3PM/8PM IST\n"
        f"💾 GitHub: {gm}\n\n*Subjects:*\n{si}\n━━━━━━━━━━━━━━━",
        parse_mode="Markdown")

async def c_lb(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(lb_txt(load_sc()), parse_mode="Markdown")

async def c_stop(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid=u.effective_chat.id
    if cid in sess:
        await end_test(ctx.application, cid, forced=True)
        await u.message.reply_text("⏹ Test rok diya.")
    else:
        await u.message.reply_text("Koi test nahi chal raha.")

async def c_addq(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_user.id!=ADMIN_ID:
        await u.message.reply_text("❌ Sirf admin."); return
    ctx.user_data["aq"]=True
    await u.message.reply_text(
        "📋 *Text Paste Format* (--- separator optional!):\n\n"
        "```\nSUBJECT: History\n"
        "QH: हिंदी प्रश्न?\nQE: English question?\n"
        "A: हिंदी A / English A\nB: हिंदी B / English B\n"
        "C: हिंदी C / English C\nD: हिंदी D / English D\n"
        "ANS: B\n```\n\n"
        "Multiple questions: blank line se alag karo ya --- use karo.\n"
        "💾 Purane questions DELETE NAHI honge.",
        parse_mode="Markdown")

async def c_myid(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        f"👤 ID:`{u.effective_user.id}`\nName: {u.effective_user.full_name}",
        parse_mode="Markdown")

async def c_ghcheck(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ok,msg=gh_ok()
    await u.message.reply_text(
        f"🔧 *GitHub*\n{msg}\n\n"+(""if ok else
        "Fix:\n1. github.com/settings/tokens\n"
        "2. New token → `repo` scope\n3. Railway → update"),
        parse_mode="Markdown")

# ════════════════════════════════════════════════════════
# CALLBACKS
# ════════════════════════════════════════════════════════
async def on_cb(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer()
    d=q.data; cid=q.message.chat_id; user=q.from_user

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
        qs=load_qs(); sc=load_sc(); cfg=load_cfg()
        ok,gm=gh_ok()
        si="\n".join(f"  • {s}: {sum(1 for x in qs if x.get('subject','General')==s)}"
                     for s in subjects(qs)) or "  None"
        auto="✅ ON" if cfg.get("auto_enabled",True) else "❌ OFF"
        await q.message.reply_text(
            f"📊 `{len(qs)}` Qs | 👥`{len(sc)}` Users\n"
            f"🕐 Auto: {auto} | GitHub: {gm}\n\n*Subjects:*\n{si}",
            parse_mode="Markdown")

    elif d=="gh_check":
        ok,msg=gh_ok()
        await q.message.reply_text(f"🔧 {msg}"+("" if ok else
            "\nFix: github.com/settings/tokens → repo scope → Railway update"))

    elif d=="toggle_auto":
        if user.id!=ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        cfg=load_cfg(); cfg["auto_enabled"]=not cfg.get("auto_enabled",True); save_cfg(cfg)
        await q.message.reply_text(f"🕐 Auto Tests: {'✅ ON' if cfg['auto_enabled'] else '❌ OFF'}")

    elif d=="mode_mixed":
        target=int(CHAT_ID) if CHAT_ID else cid
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
        target=int(CHAT_ID) if CHAT_ID else cid
        await begin_test(ctx, target, d[2:])

    elif d=="polls_start":
        if user.id!=ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        target=int(CHAT_ID) if CHAT_ID else cid
        await begin_test(ctx, target, "mixed", q_time=NORMAL_Q_TIME)

    elif d=="polls_stop":
        if user.id!=ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        target=int(CHAT_ID) if CHAT_ID else cid
        if target in sess:
            await end_test(ctx.application, target, forced=True)
            await q.message.reply_text("⏹ Polls band.")
        else:
            await q.message.reply_text("Koi poll nahi chal raha.")

    elif d=="text_help":
        if user.id!=ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        ctx.user_data["aq"]=True
        await q.message.reply_text(
            "📋 *Format* (--- optional):\n```\n"
            "SUBJECT: GK\nQH: हिंदी?\nQE: English?\n"
            "A: हिंदी A / English A\nB: ...\nC: ...\nD: ...\nANS: A\n```\n"
            "Ab paste karo 👇", parse_mode="Markdown")

    elif d=="pdf_help":
        if user.id!=ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        ctx.user_data["pdf_mode"]=True
        await q.message.reply_text(
            "📄 *PDF Upload karo*\n\nAI PDF ko padhkar automatic MCQ banayega!\n"
            "GROQ_KEY se AI content analyze karega.\n\nAb PDF bhejo 👇",
            parse_mode="Markdown")

    elif d=="ai_gen":
        if user.id!=ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        ctx.user_data["ai"]=True
        await q.message.reply_text(
            "🤖 Subject likho:\n_Example: History, Science, Polity_",
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
        ok,err=gh_write(Q_FILE, aq, f"AI:{len(nq)} {text}")
        if ok:
            await u.message.reply_text(f"✅ {len(nq)} questions add! Total:{len(aq)} 💾✅")
        else:
            await u.message.reply_text(
                f"⚠️ {len(nq)} ready but save fail!\n❌ {err}\n\n"
                "Fix: github.com/settings/tokens → repo scope → Railway update")
        return

    if user.id==ADMIN_ID and ctx.user_data.get("aq"):
        ctx.user_data.pop("aq")
        parsed=parse_qs(text)
        if not parsed:
            await u.message.reply_text(
                "❌ Parse fail.\nFormat:\nSUBJECT/QH/QE/A/B/C/D/ANS\n"
                "(--- optional between questions)"); return
        aq=load_qs(); aq.extend(parsed)
        ok,err=gh_write(Q_FILE, aq, f"Manual:{len(parsed)}")
        if ok:
            await u.message.reply_text(
                f"✅ *{len(parsed)} questions add!*\nTotal:{len(aq)} 💾✅",
                parse_mode="Markdown")
        else:
            await u.message.reply_text(
                f"⚠️ *{len(parsed)} parsed* but save fail!\n❌ {err}\n\n"
                "Fix: github.com/settings/tokens → repo scope → Railway update",
                parse_mode="Markdown")
        return

    await u.message.reply_text("👇", reply_markup=main_kb())

# ── PDF handler ─────────────────────────────────────────
async def on_document(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user=u.effective_user
    if user.id!=ADMIN_ID:
        await u.message.reply_text("❌ Sirf admin."); return
    doc=u.message.document
    if not doc: return
    fname=(doc.file_name or "").lower()
    if not (fname.endswith(".pdf") or fname.endswith(".txt")):
        await u.message.reply_text("⚠️ Sirf PDF ya TXT bhejo."); return

    await u.message.reply_text(
        f"📄 *{doc.file_name}* AI se process ho raha hai...\n"
        "Groq AI PDF padhkar MCQ banayega 🤖", parse_mode="Markdown")
    try:
        tf=await ctx.bot.get_file(doc.file_id)
        fb=bytes(await tf.download_as_bytearray())
        text=fb.decode("utf-8",errors="ignore") if fname.endswith(".txt") else pdf_to_text(fb)

        if not text.strip():
            await u.message.reply_text("❌ PDF se text extract nahi hua."); return

        # FIX8: Use Groq to read PDF content and generate questions
        await u.message.reply_text("🤖 AI PDF content analyze kar raha hai...")
        parsed=groq_from_pdf_text(text, max_q=20)

        if not parsed:
            # Fallback: try structured parse
            parsed=parse_qs(text)
        if not parsed:
            await u.message.reply_text(
                "❌ AI se questions nahi bane.\n\n"
                "Reasons:\n• GROQ_KEY set nahi\n• PDF scanned/image hai\n\n"
                "📋 Text Paste button use karo."); return

        aq=load_qs(); aq.extend(parsed)
        ok,err=gh_write(Q_FILE, aq, f"PDF:{len(parsed)} from {doc.file_name}")
        if ok:
            await u.message.reply_text(
                f"✅ *AI ne {len(parsed)} questions banaye!*\n"
                f"Total:{len(aq)} 💾✅", parse_mode="Markdown")
        else:
            await u.message.reply_text(f"⚠️ {len(parsed)} questions ready, save fail.\n❌ {err}")
    except Exception as e:
        log.error("PDF: %s", e)
        await u.message.reply_text(f"❌ Error: {str(e)[:150]}")

# ════════════════════════════════════════════════════════
# TEST FLOW
# ════════════════════════════════════════════════════════
async def begin_test(ctx, chat_id: int, mode: str, q_time: int = TEST_Q_TIME):
    if chat_id in sess:
        log.warning("Test already running in %s", chat_id); return False

    qs=load_qs(); sel=pick(qs, mode, 100)
    if not sel:
        try: await ctx.bot.send_message(chat_id, "❌ Questions nahi hain.")
        except Exception: pass
        return False

    sess[chat_id]={
        "questions":sel, "poll_map":{}, "user_data":{},
        "start_time":time.time(), "mode":mode,
        "q_time":q_time, "timer_task":None,
    }
    label="🔀 Mixed (सभी विषय)" if mode=="mixed" else f"📌 {mode}"
    try:
        await ctx.bot.send_message(chat_id,
            f"🚀 *TEST SHURU!*\n━━━━━━━━━━━━━━━━━\n"
            f"📋 {label}\n❓ {len(sel)} Questions\n"
            f"⏱ {q_time} sec/Q | Total: 10 min\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"✅ Sahi = green ✅ | ❌ Galat = red ❌\n"
            f"/stoptest se band karo\n*All the best! 🎯*",
            parse_mode="Markdown")
    except Exception as e:
        log.error("begin_test: %s", e)

    task=asyncio.create_task(_auto_end(ctx.application, chat_id))
    sess[chat_id]["timer_task"]=task
    asyncio.create_task(_send_polls(ctx.application, chat_id))
    return True

async def _auto_end(app, cid):
    await asyncio.sleep(TEST_TOTAL)
    if cid in sess:
        try: await app.bot.send_message(cid, "⏰ *10 min khatam!* Result aa raha hai...", parse_mode="Markdown")
        except Exception: pass
        await end_test(app, cid, forced=True)

async def _send_polls(app, cid):
    if cid not in sess: return
    s=sess[cid]; total=len(s["questions"]); qt=s.get("q_time", TEST_Q_TIME)
    for i,q in enumerate(s["questions"]):
        if cid not in sess: return
        txt=qtxt(q,i,total); opts=qopts(q)
        ans=max(0,min(int(q.get("answer_index",0)),len(opts)-1))
        try:
            msg=await app.bot.send_poll(
                chat_id=cid, question=txt, options=opts,
                type=Poll.QUIZ, correct_option_id=ans,
                is_anonymous=False,
                open_period=min(max(qt,5),600))
            if cid in sess: sess[cid]["poll_map"][str(msg.poll.id)]=i
        except Exception as e:
            log.error("Poll Q%d: %s", i+1, e)
        await asyncio.sleep(qt)
    if cid in sess:
        try: await app.bot.send_message(cid, "✅ Saare questions ho gaye!")
        except Exception: pass
        await asyncio.sleep(5)
        await end_test(app, cid)

async def on_poll_ans(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pa=u.poll_answer; pid=str(pa.poll_id); user=pa.user; uid=str(user.id)
    for cid,s in list(sess.items()):
        if pid not in s["poll_map"]: continue
        qi=s["poll_map"][pid]; correct=int(s["questions"][qi].get("answer_index",0))
        if uid not in s["user_data"]:
            s["user_data"][uid]={
                "name":user.full_name,"correct":0,"wrong":0,
                "start_time":s["start_time"],"last_time":time.time()}
        ud=s["user_data"][uid]
        ud["name"]=user.full_name; ud["last_time"]=time.time()
        if pa.option_ids and pa.option_ids[0]==correct: ud["correct"]+=1
        else: ud["wrong"]+=1
        break

# FIX6+7: Winner = highest accuracy; winner gets motivational message
async def end_test(app, cid, forced=False):
    if cid not in sess: return
    s=sess.pop(cid)
    if not forced and s.get("timer_task"): s["timer_task"].cancel()
    ud=s["user_data"]
    if not ud:
        try: await app.bot.send_message(cid, "📊 Kisi ne participate nahi kiya.")
        except Exception: pass
        return

    # FIX6: Sort by accuracy DESC, then time ASC
    def rank_key(item):
        d=item[1]; tot=d["correct"]+d["wrong"]
        acc=d["correct"]/tot if tot else 0
        el=d["last_time"]-d["start_time"]
        return (-acc, el)

    ranked=sorted(ud.items(), key=rank_key)
    medals={0:"🥇",1:"🥈",2:"🥉"}
    lines=[
        f"🏁 *TEST RESULT — {now_ist().strftime('%d %b %Y, %I:%M %p IST')}* 🏁",
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    ]
    for i,(uid,d) in enumerate(ranked[:20]):
        el=d["last_time"]-d["start_time"]
        tot=d["correct"]+d["wrong"]; acc=round(d["correct"]/tot*100,1) if tot else 0
        lines.append(
            f"{medals.get(i,str(i+1)+'.')} *{d['name']}*\n"
            f"   ✅`{d['correct']}` ❌`{d['wrong']}` ⏱`{ft(el)}` 🎯`{acc}%`")

    lines+=["\n━━━━━━━━━━━━━━━━━━━━━━",
            "🗑 _Result 2 ghante baad delete hoga_",
            "🏆 /leaderboard"]

    sent_ids=[]
    try:
        msg=await app.bot.send_message(cid, "\n".join(lines), parse_mode="Markdown")
        sent_ids.append(msg.message_id)
    except Exception as e:
        log.error("result send: %s", e)

    # FIX7: Motivational message for winner
    if ranked:
        winner_name=ranked[0][1]["name"]
        try:
            motiv_msg=await app.bot.send_message(cid,
                f"🎊 *Congratulations {winner_name}!* 🎊\n\n"
                "💫 _\"Mushkilein unhi ko milti hain jo ladna jaante hain,\n"
                "aur manzilein unhi ke kadam choomti hain\n"
                "jo waqt ki qeemat jaante hain.\"_ 💫\n\n"
                "🌟 Keep it up! Aage bhi aisa hi karo! 🌟",
                parse_mode="Markdown")
            sent_ids.append(motiv_msg.message_id)
        except Exception as e:
            log.error("motiv msg: %s", e)

    if sent_ids:
        asyncio.create_task(_auto_del(app, cid, sent_ids, 7200))

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
    else:
        try: await app.bot.send_message(cid, f"⚠️ Save fail: {err}")
        except Exception: pass

async def _auto_del(app, cid, msg_ids, delay):
    await asyncio.sleep(delay)
    for mid in msg_ids:
        try: await app.bot.delete_message(cid, mid)
        except Exception: pass

# ════════════════════════════════════════════════════════
# AUTO SCHEDULER
# ════════════════════════════════════════════════════════
async def scheduler(app):
    log.info("Scheduler started. Times IST: %s", AUTO_HOURS)
    fired=set()
    while True:
        try:
            now=now_ist(); key=(now.date(), now.hour)
            for h in AUTO_HOURS:
                k=(now.date(), h)
                # FIX5: 10-min advance notification
                if now.hour==h and now.minute==50 and (k,"notif") not in fired:
                    fired.add((k,"notif"))
                    if CHAT_ID:
                        try:
                            await app.bot.send_message(int(CHAT_ID),
                                f"⏰ *10 minute mein test shuru hoga!*\n"
                                f"🕐 {h}:00 IST pe auto test aayega\n"
                                f"📚 Taiyar ho jao! 🎯",
                                parse_mode="Markdown")
                        except Exception as e:
                            log.error("notif: %s", e)

                # Start test at exact hour
                if now.hour==h and now.minute==0 and k not in fired:
                    cfg=load_cfg()
                    if cfg.get("auto_enabled",True) and CHAT_ID:
                        fired.add(k)
                        target=int(CHAT_ID)
                        if target not in sess:
                            log.info("Auto test at %s:00 IST", h)
                            asyncio.create_task(
                                begin_test(
                                    type("C",(),{"bot":app.bot,"application":app})(),
                                    target, "mixed", q_time=TEST_Q_TIME))

            # Clean old fired keys
            today=now.date()
            fired={k for k in fired if (k[0] if isinstance(k,tuple) else k)==today}
        except Exception as e:
            log.error("scheduler: %s", e)
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
    log.info("Starting Bot v8.0 (PTB 20.3)...")
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
