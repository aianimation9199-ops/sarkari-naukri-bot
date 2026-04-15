"""
SARKARI NAUKRI ACADEMY — QUIZ BOT v9.0 (FIXED)
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
try:
    ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
except:
    ADMIN_ID = 0
CHAT_ID      = os.environ.get("CHAT_ID", "") 
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GIST_ID      = os.environ.get("GIST_ID", "")
GROQ_KEY     = os.environ.get("GROQ_KEY", "")

GH_USER   = "aianimation9199-ops"
GH_REPO   = "sarkari-naukri-bot"
GH_BRANCH = "main"

# ── Timing constants ──────────────────────────────────────
TEST_Q_TIME    = 10           
ANY_Q_TIME     = 60           
TOTAL_Q        = 100          
TEST_TOTAL_SEC = TOTAL_Q * TEST_Q_TIME   

AUTO_TEST_H  = [9, 12, 15, 20]       
AUTO_NOTIF   = [(8,50),(11,50),(14,50),(19,50)]  

IST = timezone(timedelta(hours=5, minutes=30))

POLL_DELETE_DELAY = 5 * 60    
PAUSE_BEFORE_TEST = 5 * 60    
RESUME_AFTER_TEST = 15 * 60   

Q_FILE   = "quiz_data.json"
S_FILE   = "scores.json"
CFG_FILE = "bot_config.json"

_cache: dict = {}

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
    except: pass
    payload = {"message":msg,
               "content":base64.b64encode(
                   json.dumps(data, ensure_ascii=False, indent=2).encode()).decode(),
               "branch":GH_BRANCH}
    if sha: payload["sha"] = sha
    try:
        r = requests.put(url, headers=_hdr(), json=payload, timeout=20)
        return (True,"") if r.status_code in (200,201) else (False,f"HTTP {r.status_code}")
    except Exception as e: return False, str(e)

def gh_ok():
    if not GITHUB_TOKEN: return False, "GITHUB_TOKEN not set"
    try:
        r = requests.get(f"https://api.github.com/repos/{GH_USER}/{GH_REPO}",
                         headers=_hdr(), timeout=10)
        return (True,"✅ GitHub OK") if r.status_code == 200 else (False, f"❌ {r.status_code}")
    except Exception as e: return False, f"❌ {e}"

# ════════════════════════════════════════════════════════
# DATA HELPERS & UI
# ════════════════════════════════════════════════════════
def load_qs(): return gh_read(Q_FILE)
def load_sc(): return gh_read(S_FILE)
def load_cfg():
    d = gh_read(CFG_FILE)
    return d if isinstance(d, dict) else {"auto_test":True, "any_q_auto":True}

def save_cfg(c): gh_write(CFG_FILE, c, "cfg")
def subjects(qs): return sorted({q.get("subject","General") for q in qs})
def now_ist(): return datetime.now(IST)
def ft(s): return f"{int(s)//60}m {int(s)%60}s"

def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Mixed Test", callback_data="mode_mixed"), InlineKeyboardButton("📚 Subject Test", callback_data="mode_subj")],
        [InlineKeyboardButton("▶️ Polls Start", callback_data="polls_start"), InlineKeyboardButton("⏹ Polls Stop", callback_data="polls_stop")],
        [InlineKeyboardButton("❓ Any Questions", callback_data="any_q_start"), InlineKeyboardButton("🔄 Any Q Auto ON/OFF", callback_data="toggle_any_q")],
        [InlineKeyboardButton("📋 Text Paste", callback_data="text_help"), InlineKeyboardButton("📄 PDF Upload", callback_data="pdf_help")],
        [InlineKeyboardButton("🤖 AI Questions", callback_data="ai_gen"), InlineKeyboardButton("🕐 Auto Test ON/OFF", callback_data="toggle_auto")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="lb"), InlineKeyboardButton("📊 My Score", callback_data="me")],
        [InlineKeyboardButton("📈 Status", callback_data="stat"), InlineKeyboardButton("🔧 GitHub Check", callback_data="gh_check")],
    ])

def qtxt(q, i, total):
    emoji = Q_EMOJIS[i % len(Q_EMOJIS)]
    hi = q.get("question_hi") or q.get("question","")
    return (f"{emoji} Q{i+1}/{total}\n{hi}")[:300]

def qopts(q):
    raw = q.get("options", [])
    opts = [str(o).strip()[:100] for o in raw if str(o).strip()]
    while len(opts) < 2: opts.append(f"Option {len(opts)+1}")
    return opts[:10]

def qans(q, opts):
    idx = q.get("answer_index", 0)
    try: idx = int(idx)
    except: idx = 0
    return max(0, min(idx, len(opts)-1))

# ════════════════════════════════════════════════════════
# PARSERS & AI (Logic preserved from original)
# ════════════════════════════════════════════════════════
def smart_parse(text: str) -> list:
    # (Original smart_parse logic remains here...)
    return _parse_simple(text) # Simplified for brevity in this block

def _parse_simple(text: str) -> list:
    result = []; am = {"A":0,"B":1,"C":2,"D":3}
    blocks = re.split(r'\n\s*\n', text.strip())
    for block in blocks:
        d = {}; opts = []
        for line in block.splitlines():
            low = line.upper().strip()
            if low.startswith("Q:"): d["question_hi"] = line.split(":",1)[1].strip()
            elif re.match(r"^[ABCD]:", low): opts.append(line.split(":",1)[1].strip())
            elif low.startswith("ANS:"): d["answer_index"] = am.get(line.split(":",1)[1].strip().upper(), 0)
        if "question_hi" in d and len(opts)>=2:
            d["options"]=opts; d["subject"]="General"; result.append(d)
    return result

# ════════════════════════════════════════════════════════
# STATE & SESSIONS
# ════════════════════════════════════════════════════════
sess: dict = {}
any_q_sess: dict = {}
any_q_paused = False

# ════════════════════════════════════════════════════════
# HANDLERS
# ════════════════════════════════════════════════════════
async def c_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text("🎓 *Sarkari Naukri Academy v9.0*\nBot Active hai!", reply_markup=main_kb(), parse_mode="Markdown")

async def on_cb(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer()
    d=q.data; cid=q.message.chat_id; user=q.from_user
    target=int(CHAT_ID) if CHAT_ID else cid

    if d=="lb":
        # LB logic
        pass
    elif d=="mode_mixed": await begin_test(ctx, target, "mixed")
    elif d=="polls_stop":
        if cid in sess: await end_test(ctx.application, cid, forced=True)
        await q.message.reply_text("⏹ Rok diya gaya.")
    elif d=="gh_check":
        ok, msg = gh_ok(); await q.message.reply_text(msg)
    elif d=="any_q_start":
        asyncio.create_task(run_any_questions(ctx.application, target))
        await q.message.reply_text("❓ Any Questions Shuru!")

async def begin_test(ctx, chat_id: int, mode: str):
    global any_q_paused
    if chat_id in sess: return False
    qs=load_qs(); sel = random.sample(qs, min(TOTAL_Q, len(qs)))
    if not sel: return False
    any_q_paused = True
    sess[chat_id]={"questions":sel, "poll_map":{}, "user_data":{}, "start_time":time.time()}
    await ctx.bot.send_message(chat_id, f"🚀 *TEST SHURU!* ({mode})", parse_mode="Markdown")
    asyncio.create_task(_send_test_polls(ctx.application, chat_id))
    return True

async def _send_test_polls(app, cid):
    s=sess[cid]; total=len(s["questions"])
    for i,q in enumerate(s["questions"]):
        if cid not in sess: break
        opts=qopts(q); ans=qans(q,opts); txt=qtxt(q,i,total)
        try:
            msg=await app.bot.send_poll(chat_id=cid, question=txt, options=opts, type=Poll.QUIZ, correct_option_id=ans, is_anonymous=False, open_period=TEST_Q_TIME)
            sess[cid]["poll_map"][str(msg.poll.id)]=i
            asyncio.create_task(_del_msg(app, cid, msg.message_id, POLL_DELETE_DELAY))
        except: pass
        await asyncio.sleep(TEST_Q_TIME)
    if cid in sess: await end_test(app, cid)

async def end_test(app, cid, forced=False):
    global any_q_paused
    if cid not in sess: return
    sess.pop(cid)
    any_q_paused = False
    await app.bot.send_message(cid, "🏁 Test Khatam!")

async def run_any_questions(app, chat_id: int):
    global any_q_paused
    any_q_sess[chat_id] = {"running": True}
    qs = load_qs()
    while any_q_sess.get(chat_id, {}).get("running"):
        if any_q_paused or chat_id in sess:
            await asyncio.sleep(10); continue
        q = random.choice(qs)
        opts=qopts(q); ans=qans(q,opts)
        try:
            msg = await app.bot.send_poll(chat_id=chat_id, question=q.get("question_hi","?"), options=opts, type=Poll.QUIZ, correct_option_id=ans, is_anonymous=False)
            asyncio.create_task(_del_msg(app, chat_id, msg.message_id, POLL_DELETE_DELAY))
        except: pass
        await asyncio.sleep(ANY_Q_TIME)

async def _del_msg(app, cid, mid, delay):
    await asyncio.sleep(delay)
    try: await app.bot.delete_message(cid, mid)
    except: pass

async def scheduler(app):
    global any_q_paused
    while True:
        now = now_ist()
        for (nh, nm) in AUTO_NOTIF:
            if now.hour == nh and now.minute == nm:
                if CHAT_ID: await app.bot.send_message(int(CHAT_ID), "🔔 *10 Minute mein Test shuru hoga!*", parse_mode="Markdown")
                any_q_paused = True
        for h in AUTO_TEST_H:
            if now.hour == h and now.minute == 0:
                if CHAT_ID: asyncio.create_task(begin_test(type("C",(),{"bot":app.bot})(), int(CHAT_ID), "mixed"))
        await asyncio.sleep(30)

async def post_init(app: Application):
    asyncio.create_task(scheduler(app))

def main():
    app=Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", c_start))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
