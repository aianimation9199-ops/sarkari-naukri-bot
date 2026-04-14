"""
SARKARI NAUKRI ACADEMY — QUIZ BOT v7.0
Changes v7.0:
 - 100 questions in 10 minutes (6 seconds per question)
 - Polls go to GROUP (CHAT_ID), not DM
 - Menu as bottom ReplyKeyboard buttons
 - Auto-schedule polls at 9:00, 12:00, 15:00, 20:00 (IST)
Railway Variables: BOT_TOKEN, ADMIN_ID, CHAT_ID,
                   GITHUB_TOKEN, GIST_ID, GROQ_KEY
"""

import os, json, time, asyncio, logging, random, re, base64
from datetime import datetime, timezone, timedelta
import requests

from telegram import (
    Update, Poll, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    PollAnswerHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

# ── Logging ──────────────────────────────────────────
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────
BOT_TOKEN    = os.environ.get("BOT_TOKEN", "")
ADMIN_ID     = int(os.environ.get("ADMIN_ID", "0"))
CHAT_ID      = os.environ.get("CHAT_ID", "")          # Telegram Group chat id
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GIST_ID      = os.environ.get("GIST_ID", "")
GROQ_KEY     = os.environ.get("GROQ_KEY", "")

GH_USER   = "aianimation9199-ops"
GH_REPO   = "sarkari-naukri-bot"
GH_BRANCH = "main"

TOTAL_Q        = 100
Q_TIME_SEC     = 6           # 6 seconds per question
TEST_MIN       = 10          # Total 10 minutes
TEST_SEC       = TEST_MIN * 60

# Auto-schedule times (IST = UTC+5:30) — hour, minute
SCHEDULE_TIMES = [(9, 0), (12, 0), (15, 0), (20, 0)]

Q_FILE    = "quiz_data.json"
S_FILE    = "scores.json"
CFG_FILE  = "bot_config.json"

_cache = {}

# ════════════════════════════════════════════════════
# KEYBOARD HELPERS
# ════════════════════════════════════════════════════

def bottom_kb():
    """Bottom ReplyKeyboard for admin — shows in message bar"""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📝 Mixed Test (सभी विषय)"), KeyboardButton("📚 Subject-wise Test")],
            [KeyboardButton("▶️ Polls Start"),            KeyboardButton("⏹ Polls Stop")],
            [KeyboardButton("📄 PDF Upload कर"),          KeyboardButton("📋 Text Paste करो")],
            [KeyboardButton("🤖 AI Questions बनाओ")],
            [KeyboardButton("🏆 Leaderboard"),            KeyboardButton("📊 My Score")],
            [KeyboardButton("📈 Status"),                 KeyboardButton("🗑 Sab Delete")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )

def user_bottom_kb():
    """Bottom ReplyKeyboard for normal users"""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🏆 Leaderboard"), KeyboardButton("📊 My Score")],
            [KeyboardButton("📈 Status")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )

def inline_subj_kb(qs):
    sub = subjects(qs)
    kb = [[InlineKeyboardButton(f"📌 {s}", callback_data=f"s_{s}")] for s in sub]
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="back")])
    return InlineKeyboardMarkup(kb)

# ════════════════════════════════════════════════════
# GITHUB HELPERS
# ════════════════════════════════════════════════════

def _gh_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

def gh_read(fname):
    try:
        url = f"https://api.github.com/repos/{GH_USER}/{GH_REPO}/contents/{fname}"
        r = requests.get(url, headers=_gh_headers(), timeout=15)
        if r.status_code == 404:
            return _cache.get(fname, [])
        r.raise_for_status()
        data = json.loads(base64.b64decode(r.json()["content"]).decode("utf-8"))
        _cache[fname] = data
        return data
    except Exception as e:
        log.error("gh_read(%s): %s", fname, e)
        return _cache.get(fname, [])

def gh_write(fname, data, msg="bot update"):
    _cache[fname] = data
    if not GITHUB_TOKEN:
        return False, "GITHUB_TOKEN not set in Railway variables"
    url = f"https://api.github.com/repos/{GH_USER}/{GH_REPO}/contents/{fname}"
    hdr = _gh_headers()
    sha = None
    try:
        r = requests.get(url, headers=hdr, timeout=10)
        if r.status_code == 200:
            sha = r.json().get("sha")
        elif r.status_code == 401:
            return False, "Token invalid ya expired"
        elif r.status_code == 403:
            return False, "Token ko 'repo' write permission nahi"
    except Exception as e:
        return False, f"Network error: {e}"

    content_b64 = base64.b64encode(
        json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode()
    payload = {"message": msg, "content": content_b64, "branch": GH_BRANCH}
    if sha:
        payload["sha"] = sha
    try:
        r = requests.put(url, headers=hdr, json=payload, timeout=20)
        if r.status_code in (200, 201):
            return True, ""
        return False, f"HTTP {r.status_code}: {r.text[:100]}"
    except Exception as e:
        return False, f"Network error: {e}"

def gist_bak(data):
    if not GIST_ID: return
    try:
        requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=_gh_headers(),
            json={"files": {"scores.json": {
                "content": json.dumps(data, ensure_ascii=False, indent=2)
            }}}, timeout=10)
    except Exception:
        pass

def check_github_token():
    if not GITHUB_TOKEN:
        return False, "GITHUB_TOKEN set nahi hai Railway mein"
    try:
        r = requests.get(
            f"https://api.github.com/repos/{GH_USER}/{GH_REPO}",
            headers=_gh_headers(), timeout=10)
        if r.status_code == 200:   return True,  "GitHub connection OK ✅"
        elif r.status_code == 401: return False, "Token invalid/expired ❌"
        elif r.status_code == 403: return False, "Token permission nahi ❌"
        elif r.status_code == 404: return False, f"Repo '{GH_USER}/{GH_REPO}' nahi mila ❌"
        return False, f"HTTP {r.status_code} ❌"
    except Exception as e:
        return False, f"Network error: {e}"

# ════════════════════════════════════════════════════
# DATA HELPERS
# ════════════════════════════════════════════════════

def load_qs():
    d = gh_read(Q_FILE)
    if isinstance(d, list): return d
    if isinstance(d, dict): return d.get("questions", [])
    return []

def load_sc():
    d = gh_read(S_FILE)
    return d if isinstance(d, dict) else {}

def subjects(qs):
    return sorted({q.get("subject", "General") for q in qs})

def pick(qs, mode, n):
    pool = qs if mode == "mixed" else [q for q in qs if q.get("subject","General") == mode]
    return random.sample(pool, min(n, len(pool)))

def ft(sec):
    return f"{int(sec)//60}m {int(sec)%60}s"

def qtxt(q, i, total):
    hi = q.get("question_hi") or q.get("question", "")
    en = q.get("question_en", "")
    body = (f"{hi}\n{en}" if hi and en and hi != en else hi or en or "?")
    return (f"Q{i+1}/{total}: " + body)[:300]

def qopts(q):
    return [str(o)[:100] for o in q.get("options", ["A","B","C","D"])[:10]]

def lb_msg(scores, top=20):
    if not scores: return "📊 Koi score nahi hai abhi."
    ranked = sorted(scores.items(),
        key=lambda x: (-x[1].get("total_score",0), x[1].get("best_time",99999)))[:top]
    medals = {0:"🥇",1:"🥈",2:"🥉"}
    lines = ["🏆 *TOP LEADERBOARD* 🏆","━━━━━━━━━━━━━━━━━━━━━━\n"]
    for i,(uid,d) in enumerate(ranked):
        c=d.get("total_correct",0); w=d.get("total_wrong",0)
        acc = round(c/(c+w)*100,1) if c+w else 0
        lines.append(
            f"{medals.get(i,str(i+1)+'.')} *{d.get('name','?')}*\n"
            f"   ✅`{c}` ❌`{w}` ⏱`{ft(d.get('best_time',0))}` 🎯`{acc}%`")
    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

# ════════════════════════════════════════════════════
# ACTIVE SESSIONS
# ════════════════════════════════════════════════════
sess = {}

# ════════════════════════════════════════════════════
# TEST FLOW  (polls always go to GROUP = CHAT_ID)
# ════════════════════════════════════════════════════

async def begin(app_or_ctx, cid, mode, *, app=None):
    """Start a quiz session.
    Can be called with (ctx, cid, mode) from handlers
    or (app, cid, mode, app=app) from scheduler.
    """
    bot = (app or app_or_ctx.application).bot if app else app_or_ctx.application.bot

    group_cid = int(CHAT_ID) if CHAT_ID else cid

    if group_cid in sess:
        await bot.send_message(group_cid, "⚠️ Test chal raha hai. /stoptest se band karo.")
        return
    all_qs = load_qs()
    selected = pick(all_qs, mode, TOTAL_Q)
    if not selected:
        await bot.send_message(group_cid, "❌ Questions nahi hain.\n📋 Text Paste se add karo.")
        return

    sess[group_cid] = {
        "questions": selected, "poll_map": {},
        "user_data": {}, "start_time": time.time(),
        "mode": mode, "timer_task": None,
    }
    label = "🔀 Mixed (सभी विषय)" if mode == "mixed" else f"📌 {mode}"
    the_app = app or app_or_ctx.application
    await bot.send_message(
        group_cid,
        f"🚀 *TEST SHURU!*\n━━━━━━━━━━━━━━━━━\n"
        f"📋 {label}\n❓ {len(selected)} Questions\n⏱ {TEST_MIN} Minutes\n"
        f"⏲ Har question: {Q_TIME_SEC} seconds\n"
        f"━━━━━━━━━━━━━━━━━\n✅ Sahi = +1 | ❌ Galat = counted\n"
        f"*All the best! 🎯*",
        parse_mode="Markdown")

    task = asyncio.create_task(_auto_end(the_app, group_cid))
    sess[group_cid]["timer_task"] = task
    asyncio.create_task(_send_polls(the_app, group_cid))

async def _auto_end(app, cid):
    await asyncio.sleep(TEST_SEC)
    if cid in sess:
        await app.bot.send_message(
            cid, f"⏰ *{TEST_MIN} min khatam!* Result aa raha hai...", parse_mode="Markdown")
        await end_test(app, cid, forced=True)

async def _send_polls(app, cid):
    if cid not in sess: return
    s = sess[cid]; total = len(s["questions"])
    for i, q in enumerate(s["questions"]):
        if cid not in sess: return
        text = qtxt(q, i, total)
        opts = qopts(q)
        ans  = max(0, min(int(q.get("answer_index",0)), len(opts)-1))
        try:
            msg = await app.bot.send_poll(
                chat_id=cid,
                question=text,
                options=opts,
                type=Poll.QUIZ,
                correct_option_id=ans,
                is_anonymous=False,
                open_period=max(Q_TIME_SEC, 5),   # min 5s (Telegram limit)
            )
            sess[cid]["poll_map"][str(msg.poll.id)] = i
        except Exception as e:
            log.error("Poll Q%d: %s", i+1, e)
        await asyncio.sleep(Q_TIME_SEC)

    if cid in sess:
        await app.bot.send_message(cid, "✅ Saare questions ho gaye! Result aa raha hai...")
        await asyncio.sleep(5)
        await end_test(app, cid)

async def on_poll_ans(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pa = u.poll_answer; pid = str(pa.poll_id)
    user = pa.user; uid = str(user.id)
    for cid, s in list(sess.items()):
        if pid not in s["poll_map"]: continue
        qi = s["poll_map"][pid]
        correct = int(s["questions"][qi].get("answer_index",0))
        if uid not in s["user_data"]:
            s["user_data"][uid] = {
                "name": user.full_name, "correct": 0, "wrong": 0,
                "start_time": s["start_time"], "last_time": time.time(),
            }
        ud = s["user_data"][uid]
        ud["name"] = user.full_name; ud["last_time"] = time.time()
        if pa.option_ids and pa.option_ids[0] == correct:
            ud["correct"] += 1
        else:
            ud["wrong"] += 1
        break

async def end_test(app, cid, forced=False):
    if cid not in sess: return
    s = sess.pop(cid)
    if not forced and s.get("timer_task"):
        s["timer_task"].cancel()
    ud = s["user_data"]
    if not ud:
        await app.bot.send_message(cid, "📊 Kisi ne participate nahi kiya."); return

    ranked = sorted(ud.items(),
        key=lambda x: (-x[1]["correct"], x[1]["last_time"]-x[1]["start_time"]))
    medals = {0:"🥇",1:"🥈",2:"🥉"}
    lines = ["🏁 *TEST RESULT* 🏁","━━━━━━━━━━━━━━━━━━━━━━\n"]
    for i,(uid,d) in enumerate(ranked[:20]):
        el = d["last_time"]-d["start_time"]
        tot = d["correct"]+d["wrong"]
        acc = round(d["correct"]/tot*100,1) if tot else 0
        lines.append(
            f"{medals.get(i,str(i+1)+'.')} *{d['name']}*\n"
            f"   ✅`{d['correct']}` ❌`{d['wrong']}` ⏱`{ft(el)}` 🎯`{acc}%`")
    lines += ["\n━━━━━━━━━━━━━━━━━━━━━━","🏆 /leaderboard"]
    await app.bot.send_message(cid, "\n".join(lines), parse_mode="Markdown")

    scores = load_sc()
    for uid, d in ud.items():
        el = d["last_time"]-d["start_time"]
        tot = d["correct"]+d["wrong"]
        if uid not in scores:
            scores[uid] = {"name":"","total_score":0,"total_correct":0,
                           "total_wrong":0,"tests_taken":0,"best_time":99999,"accuracy":0.0}
        s2 = scores[uid]
        s2["name"]=d["name"]; s2["total_score"]+=d["correct"]
        s2["total_correct"]+=d["correct"]; s2["total_wrong"]+=d["wrong"]
        s2["tests_taken"]+=1
        if el < s2["best_time"]: s2["best_time"]=round(el,1)
        tot2=s2["total_correct"]+s2["total_wrong"]
        s2["accuracy"]=round(s2["total_correct"]/tot2*100,1) if tot2 else 0

    ok, err = gh_write(S_FILE, scores, "Scores updated")
    if ok:
        gist_bak(scores)
        await app.bot.send_message(cid, "💾 Scores GitHub mein save ho gaye! ✅")
    else:
        await app.bot.send_message(cid, f"⚠️ Scores save nahi hue.\n❌ {err}")

# ════════════════════════════════════════════════════
# AUTO SCHEDULER  (9:00, 12:00, 15:00, 20:00 IST)
# ════════════════════════════════════════════════════

IST = timezone(timedelta(hours=5, minutes=30))

async def _scheduler(app: Application):
    """Background task — waits for next scheduled time then fires a mixed test."""
    log.info("Scheduler started. Times: %s IST", SCHEDULE_TIMES)
    while True:
        now = datetime.now(IST)
        # Find next slot
        next_dt = None
        for h, m in sorted(SCHEDULE_TIMES):
            candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if candidate > now:
                next_dt = candidate
                break
        if next_dt is None:
            # All slots passed today — use first slot tomorrow
            h, m = sorted(SCHEDULE_TIMES)[0]
            next_dt = (now + timedelta(days=1)).replace(
                hour=h, minute=m, second=0, microsecond=0)

        wait = (next_dt - datetime.now(IST)).total_seconds()
        log.info("Next auto-test at %s IST (in %.0f s)", next_dt.strftime("%H:%M"), wait)
        await asyncio.sleep(wait)

        if not CHAT_ID:
            log.warning("CHAT_ID not set — skipping scheduled test")
            continue
        try:
            group_cid = int(CHAT_ID)
            await app.bot.send_message(
                group_cid,
                f"🕐 Scheduled Test — {next_dt.strftime('%H:%M')} IST\n🚀 Shuru ho raha hai!",
            )
            # Use a simple namespace to carry app
            class FakeCtx:
                application = app
            await begin(FakeCtx(), group_cid, "mixed")
        except Exception as e:
            log.error("Scheduler start error: %s", e)

# ════════════════════════════════════════════════════
# PARSE QUESTIONS
# ════════════════════════════════════════════════════

def parse_qs(text):
    result = []; am = {"A":0,"B":1,"C":2,"D":3}
    for block in text.strip().split("---"):
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

# ════════════════════════════════════════════════════
# COMMANDS
# ════════════════════════════════════════════════════

async def c_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    is_admin = u.effective_user.id == ADMIN_ID
    kb = bottom_kb() if is_admin else user_bottom_kb()
    await u.message.reply_text(
        "🎓 *Sarkari Naukri Academy Quiz Bot*\n\n"
        "• 100 Questions | ⏱ 10 Minutes\n"
        "• ⏲ Har question: 6 seconds\n"
        "• ✅ Sahi = +1 | ❌ Galat = counted\n"
        "• 🏆 Top-20 Leaderboard\n\n"
        "👇 Neeche buttons se choose karo:",
        reply_markup=kb, parse_mode="Markdown")

async def c_status(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    qs = load_qs(); sc = load_sc()
    sub = subjects(qs)
    gh_ok, gh_msg = check_github_token()
    si = "\n".join(
        f"  • {s}: {sum(1 for q in qs if q.get('subject','General')==s)}"
        for s in sub) or "  None"
    await u.message.reply_text(
        f"📊 *Bot Status*\n━━━━━━━━━━━━━━━\n"
        f"❓`{len(qs)}` Questions | 👥`{len(sc)}` Users\n"
        f"🔴 Active Tests:`{len(sess)}` | ⏲ Q-Timer:`{Q_TIME_SEC}s` | ⏱ Total:`{TEST_MIN}m`\n"
        f"💾 GitHub: {gh_msg}\n\n"
        f"*Subjects:*\n{si}\n━━━━━━━━━━━━━━━",
        parse_mode="Markdown")

async def c_lb(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(lb_msg(load_sc()), parse_mode="Markdown")

async def c_stop(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_user.id != ADMIN_ID:
        await u.message.reply_text("❌ Sirf admin."); return
    cid = int(CHAT_ID) if CHAT_ID else u.effective_chat.id
    if cid in sess:
        await end_test(ctx.application, cid, forced=True)
        await u.message.reply_text("⏹ Test rok diya.")
    else:
        await u.message.reply_text("Koi test nahi chal raha.")

async def c_addq(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_user.id != ADMIN_ID:
        await u.message.reply_text("❌ Sirf admin."); return
    ctx.user_data["aq"] = True
    await u.message.reply_text(
        "📋 *Text Paste Karo — Format:*\n\n"
        "```\nSUBJECT: History\n"
        "QH: हिंदी प्रश्न?\nQE: English question?\n"
        "A: Option A\nB: Option B\nC: Option C\nD: Option D\nANS: B\n---\n```\n"
        "Multiple questions ke beech `---` lagao.",
        parse_mode="Markdown")

async def c_myid(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        f"👤 ID:`{u.effective_user.id}`\nName: {u.effective_user.full_name}",
        parse_mode="Markdown")

async def c_ghcheck(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ok, msg = check_github_token()
    icon = "✅" if ok else "❌"
    await u.message.reply_text(
        f"🔧 *GitHub Token Check*\n\n{icon} {msg}\n\n"
        + ("" if ok else
           "🔑 *Fix karo:*\n"
           "1. github.com/settings/tokens pe jao\n"
           "2. New token banao (classic)\n"
           "3. `repo` scope select karo ✅\n"
           "4. Railway → Variables → GITHUB_TOKEN update karo"),
        parse_mode="Markdown")

# ════════════════════════════════════════════════════
# MESSAGE HANDLER  (bottom keyboard text buttons)
# ════════════════════════════════════════════════════
