"""
SARKARI NAUKRI ACADEMY — QUIZ BOT v7.0
=======================================
FEATURES:
1. Auto test at fixed times: 09:00, 12:00, 03:00, 08:00 (IST)
2. 100 questions per test
3. Per-question time: 6 seconds (test mode) / 60 seconds (normal polls)
4. Test duration: 10 minutes total
5. Bot buttons: Text Paste, Polls Start/Stop, Auto Save, Mixed/Subject Test, PDF, AI, Leaderboard, Score, Status
6. Subject-wise auto-detect from text
7. Auto scheduled tests
8. Full rank result in GROUP after test ends
9. Result auto-delete after 2 hours, new test data fresh
10. Normal polls = 1 min per Q; Test mode = 6 sec per Q, 100Q, 10 min
11. All functions working
12. Questions sent to TELEGRAM GROUP (CHAT_ID), not just bot DM
13. Hindi + English bilingual questions & options
14. Correct answer = green tick, wrong = red cross (Telegram Quiz Poll)

Railway Variables:
  BOT_TOKEN, ADMIN_ID, CHAT_ID, GITHUB_TOKEN, GIST_ID, GROQ_KEY, TIMER
"""

import os, json, time, asyncio, logging, random, re, base64
from datetime import datetime, timezone, timedelta
import requests

from telegram import Update, Poll, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    PollAnswerHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

# ── Logging ──────────────────────────────────────────────
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────
BOT_TOKEN    = os.environ.get("BOT_TOKEN", "")
ADMIN_ID     = int(os.environ.get("ADMIN_ID", "0"))
CHAT_ID      = os.environ.get("CHAT_ID", "")          # Telegram GROUP where tests go
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GIST_ID      = os.environ.get("GIST_ID", "")
GROQ_KEY     = os.environ.get("GROQ_KEY", "")
TIMER        = int(os.environ.get("TIMER", "60"))      # Normal poll interval (seconds)

GH_USER   = "aianimation9199-ops"
GH_REPO   = "sarkari-naukri-bot"
GH_BRANCH = "main"

# Test settings
TOTAL_Q        = 100           # Questions per test
TEST_Q_TIME    = 6             # Seconds per question in TEST mode
TEST_DURATION  = 10 * 60       # 10 minutes total test

# Auto test times in IST (24h format)
AUTO_TEST_HOURS_IST = [9, 12, 15, 20]   # 09:00, 12:00, 15:00, 20:00 IST

# IST offset
IST = timezone(timedelta(hours=5, minutes=30))

Q_FILE   = "quiz_data.json"
S_FILE   = "scores.json"
CFG_FILE = "bot_config.json"

# In-memory cache
_cache: dict = {}

# ════════════════════════════════════════════════════════
# GITHUB STORAGE
# ════════════════════════════════════════════════════════

def _gh_hdr():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

def gh_read(fname):
    try:
        r = requests.get(
            f"https://api.github.com/repos/{GH_USER}/{GH_REPO}/contents/{fname}",
            headers=_gh_hdr(), timeout=15)
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
    """Safe write — only this file changes, others untouched."""
    _cache[fname] = data
    if not GITHUB_TOKEN:
        return False, "GITHUB_TOKEN not set"
    url = f"https://api.github.com/repos/{GH_USER}/{GH_REPO}/contents/{fname}"
    sha = None
    try:
        r = requests.get(url, headers=_gh_hdr(), timeout=10)
        if r.status_code == 200:
            sha = r.json().get("sha")
        elif r.status_code == 401:
            return False, "Token invalid/expired — Railway mein naya GITHUB_TOKEN daalo"
        elif r.status_code == 403:
            return False, "Token ko 'repo' write permission nahi"
    except Exception as e:
        return False, f"Network error: {e}"

    payload = {
        "message": msg,
        "content": base64.b64encode(
            json.dumps(data, ensure_ascii=False, indent=2).encode()
        ).decode(),
        "branch": GH_BRANCH,
    }
    if sha:
        payload["sha"] = sha
    try:
        r = requests.put(url, headers=_gh_hdr(), json=payload, timeout=20)
        if r.status_code in (200, 201):
            return True, ""
        elif r.status_code == 401:
            return False, "Token expired"
        elif r.status_code == 403:
            return False, "No write permission"
        else:
            return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, f"Error: {e}"

def gist_bak(data):
    if not GIST_ID: return
    try:
        requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=_gh_hdr(),
            json={"files": {"scores.json": {
                "content": json.dumps(data, ensure_ascii=False, indent=2)
            }}}, timeout=10)
    except Exception:
        pass

def gh_token_ok():
    if not GITHUB_TOKEN:
        return False, "GITHUB_TOKEN not set"
    try:
        r = requests.get(
            f"https://api.github.com/repos/{GH_USER}/{GH_REPO}",
            headers=_gh_hdr(), timeout=10)
        if r.status_code == 200: return True, "✅ GitHub OK"
        if r.status_code == 401: return False, "❌ Token invalid/expired"
        if r.status_code == 403: return False, "❌ No permission"
        if r.status_code == 404: return False, f"❌ Repo not found"
        return False, f"❌ HTTP {r.status_code}"
    except Exception as e:
        return False, f"❌ {e}"

# ════════════════════════════════════════════════════════
# DATA HELPERS
# ════════════════════════════════════════════════════════

def load_qs() -> list:
    d = gh_read(Q_FILE)
    if isinstance(d, list): return d
    if isinstance(d, dict): return d.get("questions", [])
    return []

def load_sc() -> dict:
    d = gh_read(S_FILE)
    return d if isinstance(d, dict) else {}

def load_cfg() -> dict:
    d = gh_read(CFG_FILE)
    if isinstance(d, dict): return d
    return {"auto_enabled": True, "current_index": 0}

def save_cfg(cfg):
    gh_write(CFG_FILE, cfg, "cfg update")

def get_subjects(qs: list) -> list:
    return sorted({q.get("subject", "General") for q in qs})

def pick_qs(qs: list, mode: str, n: int) -> list:
    pool = qs if mode == "mixed" else [q for q in qs if q.get("subject","General") == mode]
    return random.sample(pool, min(n, len(pool)))

def fmt_time(sec: float) -> str:
    return f"{int(sec)//60}m {int(sec)%60}s"

def now_ist() -> datetime:
    return datetime.now(IST)

def q_text(q: dict, i: int, total: int) -> str:
    hi = q.get("question_hi") or q.get("question", "")
    en = q.get("question_en", "")
    if hi and en and hi.strip() != en.strip():
        body = f"{hi}\n{en}"
    else:
        body = hi or en or "?"
    return (f"Q{i+1}/{total}: " + body)[:300]

def q_opts(q: dict) -> list:
    return [str(o)[:100] for o in q.get("options", ["A","B","C","D"])[:10]]

def lb_text(scores: dict, top: int = 20) -> str:
    if not scores:
        return "📊 Koi score nahi hai abhi."
    ranked = sorted(scores.items(),
        key=lambda x: (-x[1].get("total_score", 0), x[1].get("best_time", 99999)))[:top]
    medals = {0:"🥇", 1:"🥈", 2:"🥉"}
    lines = ["🏆 *TOP LEADERBOARD* 🏆", "━━━━━━━━━━━━━━━━━━━━━━\n"]
    for i, (uid, d) in enumerate(ranked):
        c = d.get("total_correct", 0); w = d.get("total_wrong", 0)
        acc = round(c/(c+w)*100, 1) if c+w else 0
        lines.append(
            f"{medals.get(i, str(i+1)+'.')} *{d.get('name','?')}*\n"
            f"   ✅`{c}` ❌`{w}` ⏱`{fmt_time(d.get('best_time',0))}` 🎯`{acc}%`\n"
            f"   📝Tests:`{d.get('tests_taken',0)}`")
    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

# ════════════════════════════════════════════════════════
# KEYBOARDS
# ════════════════════════════════════════════════════════

def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Mixed Test",          callback_data="mode_mixed"),
         InlineKeyboardButton("📚 Subject Test",        callback_data="mode_subj")],
        [InlineKeyboardButton("▶️ Polls Start",         callback_data="polls_start"),
         InlineKeyboardButton("⏹ Polls Stop",           callback_data="polls_stop")],
        [InlineKeyboardButton("📋 Text Paste",          callback_data="text_help"),
         InlineKeyboardButton("📄 PDF Upload",          callback_data="pdf_help")],
        [InlineKeyboardButton("🤖 AI Questions",        callback_data="ai_gen"),
         InlineKeyboardButton("💾 Auto Save ON/OFF",    callback_data="toggle_auto")],
        [InlineKeyboardButton("🏆 Leaderboard",         callback_data="lb"),
         InlineKeyboardButton("📊 My Score",            callback_data="me")],
        [InlineKeyboardButton("📈 Status",              callback_data="stat"),
         InlineKeyboardButton("🗑 Sab Delete",          callback_data="ask_del")],
        [InlineKeyboardButton("🔧 GitHub Check",        callback_data="gh_check")],
    ])

# ════════════════════════════════════════════════════════
# ACTIVE STATE
# ════════════════════════════════════════════════════════
# sess[chat_id] = {questions, poll_map, user_data, start_time, mode, timer_task, result_msg_ids}
sess: dict = {}
# result_msgs[chat_id] = [msg_id, ...] — for auto-delete after 2h
result_msgs: dict = {}

# ════════════════════════════════════════════════════════
# COMMANDS
# ════════════════════════════════════════════════════════

async def c_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        "🎓 *Sarkari Naukri Academy Quiz Bot v7.0*\n\n"
        "• 100 Questions | ⏱ 10 Minutes\n"
        "• Test: 6 sec/Q | Normal: 60 sec/Q\n"
        "• ✅ Sahi = green tick | ❌ Galat = red cross\n"
        "• 📖 Hindi + English bilingual\n"
        "• 🏆 Auto rank result in group\n"
        "• 🕐 Auto tests: 9AM, 12PM, 3PM, 8PM IST\n\n"
        "👇 Choose karo:",
        reply_markup=main_kb(), parse_mode="Markdown")

async def c_status(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    qs = load_qs(); sc = load_sc(); cfg = load_cfg()
    gh_ok, gh_msg = gh_token_ok()
    subs = get_subjects(qs)
    si = "\n".join(
        f"  • {s}: {sum(1 for q in qs if q.get('subject','General')==s)}"
        for s in subs) or "  None"
    auto = "✅ ON" if cfg.get("auto_enabled", True) else "❌ OFF"
    await u.message.reply_text(
        f"📊 *Bot Status*\n━━━━━━━━━━━━━━━\n"
        f"❓`{len(qs)}` Questions | 👥`{len(sc)}` Users\n"
        f"🔴 Active:`{len(sess)}` | ⏱ Timer:`{TIMER}s`\n"
        f"🕐 Auto Tests: {auto}\n"
        f"🕐 Next at: 9AM/12PM/3PM/8PM IST\n"
        f"💾 GitHub: {gh_msg}\n\n"
        f"*Subjects:*\n{si}\n━━━━━━━━━━━━━━━",
        parse_mode="Markdown")

async def c_lb(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(lb_text(load_sc()), parse_mode="Markdown")

async def c_stop(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = u.effective_chat.id
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
        "📋 *Text Paste Format:*\n\n"
        "```\nSUBJECT: History\n"
        "QH: हिंदी प्रश्न?\nQE: English question?\n"
        "A: विकल्प A / Option A\n"
        "B: विकल्प B / Option B\n"
        "C: विकल्प C / Option C\n"
        "D: विकल्प D / Option D\n"
        "ANS: B\n---\n```\n"
        "Multiple questions: `---` se alag karo.\n"
        "💾 Purane questions DELETE NAHI honge.",
        parse_mode="Markdown")

async def c_myid(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        f"👤 ID:`{u.effective_user.id}`\nName: {u.effective_user.full_name}",
        parse_mode="Markdown")

async def c_ghcheck(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ok, msg = gh_token_ok()
    await u.message.reply_text(
        f"🔧 *GitHub Status*\n\n{msg}\n\n"
        + ("" if ok else
           "🔑 *Fix:*\n1. github.com/settings/tokens\n"
           "2. New token (classic) → `repo` scope ✅\n"
           "3. Railway → GITHUB_TOKEN update karo"),
        parse_mode="Markdown")

# ════════════════════════════════════════════════════════
# CALLBACK HANDLER
# ════════════════════════════════════════════════════════

async def on_cb(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    await q.answer()
    d = q.data; cid = q.message.chat_id; user = q.from_user

    if d == "lb":
        await q.message.reply_text(lb_text(load_sc()), parse_mode="Markdown")

    elif d == "me":
        uid = str(user.id); sc = load_sc()
        if uid in sc:
            x = sc[uid]; c = x.get("total_correct",0); w = x.get("total_wrong",0)
            acc = round(c/(c+w)*100,1) if c+w else 0
            await q.message.reply_text(
                f"📊 *Tumhara Score*\n━━━━━━━━━━━━━━\n"
                f"👤 {x.get('name','?')}\n"
                f"✅ Sahi:`{c}` ❌ Galat:`{w}`\n"
                f"🎯 Accuracy:`{acc}%` 📝 Tests:`{x.get('tests_taken',0)}`\n"
                f"⏱ Best:`{fmt_time(x.get('best_time',0))}` 🏆 Score:`{x.get('total_score',0)}`",
                parse_mode="Markdown")
        else:
            await q.message.reply_text("Tumne abhi koi test nahi diya!")

    elif d == "stat":
        await c_status(
            type("F", (), {"message": q.message, "effective_user": user})(),
            ctx)

    elif d == "gh_check":
        ok, msg = gh_token_ok()
        await q.message.reply_text(
            f"🔧 *GitHub*\n{msg}\n\n"
            + ("" if ok else
               "Fix: github.com/settings/tokens → `repo` scope → Railway update"),
            parse_mode="Markdown")

    elif d == "toggle_auto":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        cfg = load_cfg()
        cfg["auto_enabled"] = not cfg.get("auto_enabled", True)
        save_cfg(cfg)
        state = "✅ ON" if cfg["auto_enabled"] else "❌ OFF"
        await q.message.reply_text(f"🕐 Auto Tests: {state}")

    elif d == "mode_mixed":
        # Start test in GROUP
        target = int(CHAT_ID) if CHAT_ID else cid
        await begin_test(ctx, target, "mixed", q_time=TEST_Q_TIME)

    elif d == "mode_subj":
        qs = load_qs(); subs = get_subjects(qs)
        if not subs:
            await q.message.reply_text("❌ Koi questions nahi. Pehle add karo."); return
        kb = [[InlineKeyboardButton(f"📌 {s}", callback_data=f"s_{s}")] for s in subs]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="back")])
        await q.message.reply_text("📚 *Subject choose karo:*",
            reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("s_"):
        target = int(CHAT_ID) if CHAT_ID else cid
        await begin_test(ctx, target, d[2:], q_time=TEST_Q_TIME)

    elif d == "polls_start":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        target = int(CHAT_ID) if CHAT_ID else cid
        await begin_test(ctx, target, "mixed", q_time=TIMER)

    elif d == "polls_stop":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        target = int(CHAT_ID) if CHAT_ID else cid
        if target in sess:
            await end_test(ctx.application, target, forced=True)
            await q.message.reply_text("⏹ Polls band.")
        else:
            await q.message.reply_text("Koi poll nahi chal raha.")

    elif d == "text_help":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        ctx.user_data["aq"] = True
        await q.message.reply_text(
            "📋 *Text Paste Format:*\n\n"
            "```\nSUBJECT: Geography\n"
            "QH: हिंदी प्रश्न?\nQE: English?\n"
            "A: हिंदी / English\nB: हिंदी / English\n"
            "C: हिंदी / English\nD: हिंदी / English\nANS: A\n---\n```\n"
            "Ab text paste karo 👇",
            parse_mode="Markdown")

    elif d == "pdf_help":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        ctx.user_data["pdf_mode"] = True
        await q.message.reply_text(
            "📄 *PDF Upload Karo*\n\nSeedha PDF bhejo — questions auto extract honge!\n\n"
            "PDF format:\n```\n1. Question?\n(A) Option A\n(B) Option B\n(C) Option C\n(D) Option D\n```",
            parse_mode="Markdown")

    elif d == "ai_gen":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        ctx.user_data["ai"] = True
        await q.message.reply_text(
            "🤖 Subject likho:\n_Example: History, Science, Geography, Polity, Math_",
            parse_mode="Markdown")

    elif d == "ask_del":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        await q.message.reply_text(
            "⚠️ *Saare questions delete karne hain?*",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Haan", callback_data="yes_del"),
                 InlineKeyboardButton("❌ Nahi",  callback_data="no_del")]
            ]), parse_mode="Markdown")

    elif d == "yes_del":
        if user.id != ADMIN_ID: return
        ok, err = gh_write(Q_FILE, [], "Admin: delete all")
        await q.message.reply_text("🗑 Done." if ok else f"❌ {err}")

    elif d == "no_del":
        await q.message.reply_text("✅ Cancel.")

    elif d == "back":
        await q.message.reply_text("👇", reply_markup=main_kb())

# ════════════════════════════════════════════════════════
# MESSAGE HANDLER
# ════════════════════════════════════════════════════════

async def on_msg(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = u.effective_user
    text = (u.message.text or "").strip()

    if user.id == ADMIN_ID and ctx.user_data.get("ai"):
        ctx.user_data.pop("ai")
        await u.message.reply_text(f"🤖 *{text}* ke questions bana raha hoon...", parse_mode="Markdown")
        new_qs = groq_gen(text, 10)
        if not new_qs:
            await u.message.reply_text("❌ AI se questions nahi aaye."); return
        all_qs = load_qs(); all_qs.extend(new_qs)
        ok, err = gh_write(Q_FILE, all_qs, f"AI: {len(new_qs)} {text}")
        if ok:
            await u.message.reply_text(f"✅ {len(new_qs)} AI questions add!\nTotal: {len(all_qs)} 💾✅")
        else:
            await u.message.reply_text(
                f"⚠️ {len(new_qs)} questions ready but save fail!\n❌ {err}\n\n"
                f"🔑 Fix: github.com/settings/tokens → repo scope → Railway update")
        return

    if user.id == ADMIN_ID and ctx.user_data.get("aq"):
        ctx.user_data.pop("aq")
        parsed = parse_qs(text)
        if not parsed:
            await u.message.reply_text(
                "❌ Koi question parse nahi hua.\nFormat check karo.\n"
                "SUBJECT/QH/QE/A/B/C/D/ANS sab hona chahiye."); return
        all_qs = load_qs(); all_qs.extend(parsed)
        ok, err = gh_write(Q_FILE, all_qs, f"Manual: {len(parsed)} questions")
        if ok:
            await u.message.reply_text(
                f"✅ *{len(parsed)} questions add!*\nTotal: {len(all_qs)} 💾✅",
                parse_mode="Markdown")
        else:
            await u.message.reply_text(
                f"⚠️ *{len(parsed)} questions parsed* lekin save fail!\n\n"
                f"❌ Reason: {err}\n\n"
                f"🔑 *Fix:*\n1. github.com/settings/tokens\n"
                f"2. New token (classic) → `repo` ✅\n"
                f"3. Railway → GITHUB_TOKEN update",
                parse_mode="Markdown")
        return

    await u.message.reply_text("👇 Menu:", reply_markup=main_kb())

# ── PDF handler ──────────────────────────────────────────
async def on_document(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = u.effective_user
    if user.id != ADMIN_ID:
        await u.message.reply_text("❌ Sirf admin."); return
    doc = u.message.document
    if not doc: return
    fname = (doc.file_name or "").lower()
    if not (fname.endswith(".pdf") or fname.endswith(".txt")):
        await u.message.reply_text("⚠️ Sirf PDF ya TXT bhejo."); return
    await u.message.reply_text(f"📄 Processing *{doc.file_name}*...", parse_mode="Markdown")
    try:
        tg_file = await ctx.bot.get_file(doc.file_id)
        fb = bytes(await tg_file.download_as_bytearray())
        text = fb.decode("utf-8", errors="ignore") if fname.endswith(".txt") else _pdf_text(fb)
        parsed = parse_qs(text) or _parse_mcq(text)
        if not parsed:
            await u.message.reply_text("❌ Questions extract nahi ho sake.\n📋 Text Paste use karo."); return
        all_qs = load_qs(); all_qs.extend(parsed)
        ok, err = gh_write(Q_FILE, all_qs, f"PDF: {len(parsed)} from {doc.file_name}")
        if ok:
            await u.message.reply_text(f"✅ *{len(parsed)} questions add!*\nTotal: {len(all_qs)} 💾✅", parse_mode="Markdown")
        else:
            await u.message.reply_text(f"⚠️ {len(parsed)} parsed, save fail.\n❌ {err}")
    except Exception as e:
        log.error("PDF: %s", e)
        await u.message.reply_text(f"❌ Error: {str(e)[:150]}")

def _pdf_text(b: bytes) -> str:
    try:
        t = b.decode("latin-1", errors="ignore")
        chunks = re.findall(r'\((.*?)\)', t)
        r = re.sub(r'\s+', ' ', re.sub(r'\\[nrt]', ' ', " ".join(chunks)))
        return r[:50000]
    except Exception:
        return ""

def _parse_mcq(text: str) -> list:
    result = []
    blocks = re.split(r'(?:^|\s)(?:Q\.?\s*)?(\d+)[.)]\s+', text, flags=re.MULTILINE)
    for block in blocks:
        block = block.strip()
        if len(block) < 20: continue
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if not lines: continue
        qt = lines[0]; opts = []; ans = 0
        for line in lines[1:]:
            m = re.match(r'^[\(\[]?([A-Da-d])[\)\]\.]\s*(.+)', line)
            if m: opts.append(m.group(2).strip()[:100])
            a = re.search(r'(?:ans(?:wer)?|correct)[:\s]*([A-Da-d])', line, re.I)
            if a: ans = ord(a.group(1).upper()) - ord('A')
        if qt and len(opts) >= 2:
            result.append({
                "question": qt[:300], "question_hi": qt[:300], "question_en": qt[:300],
                "options": opts[:4], "answer_index": max(0, min(ans, len(opts)-1)),
                "subject": "General",
            })
    return result[:200]

# ════════════════════════════════════════════════════════
# GROQ AI
# ════════════════════════════════════════════════════════

def groq_gen(subject: str, count: int = 10) -> list:
    if not GROQ_KEY: return []
    prompt = (
        f'Generate {count} MCQ for "{subject}" for SSC/Railway/UPSC exams.\n'
        'Return ONLY valid JSON array, no extra text:\n'
        '[{"question_hi":"हिंदी?","question_en":"English?",'
        '"options":["हिंदी A / English A","हिंदी B / English B",'
        '"हिंदी C / English C","हिंदी D / English D"],'
        f'"answer_index":0,"subject":"{subject}"}}]'
    )
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={"model":"llama3-8b-8192",
                  "messages":[{"role":"user","content":prompt}],
                  "temperature":0.5,"max_tokens":4000},
            timeout=30)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if m: return json.loads(m.group())
    except Exception as e:
        log.error("groq: %s", e)
    return []

# ════════════════════════════════════════════════════════
# TEST FLOW — sends to CHAT_ID (GROUP)
# ════════════════════════════════════════════════════════

async def begin_test(ctx, chat_id: int, mode: str, q_time: int = TEST_Q_TIME):
    """Start a test in the given chat_id (always the group)."""
    if chat_id in sess:
        log.warning("Test already running in %s", chat_id)
        return False

    all_qs = load_qs()
    selected = pick_qs(all_qs, mode, TOTAL_Q)
    if not selected:
        try:
            await ctx.bot.send_message(
                chat_id,
                "❌ Questions nahi hain. Admin se contact karo.")
        except Exception:
            pass
        return False

    sess[chat_id] = {
        "questions":  selected,
        "poll_map":   {},        # poll_id -> q_index
        "user_data":  {},        # uid -> stats
        "start_time": time.time(),
        "mode":       mode,
        "q_time":     q_time,
        "timer_task": None,
        "result_msgs": [],
    }

    label = "🔀 Mixed (सभी विषय)" if mode == "mixed" else f"📌 {mode}"
    try:
        await ctx.bot.send_message(
            chat_id,
            f"🚀 *TEST SHURU!*\n━━━━━━━━━━━━━━━━━\n"
            f"📋 {label}\n"
            f"❓ {len(selected)} Questions\n"
            f"⏱ {q_time} sec per question\n"
            f"⏰ Total: 10 minutes\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"✅ Sahi = green ✅ | ❌ Galat = red ❌\n"
            f"Band karne ke liye: /stoptest\n\n"
            f"*All the best! 🎯*",
            parse_mode="Markdown")
    except Exception as e:
        log.error("begin_test announce: %s", e)

    # Auto-end after TEST_DURATION
    task = asyncio.create_task(_auto_end(ctx.application, chat_id))
    sess[chat_id]["timer_task"] = task

    # Send polls
    asyncio.create_task(_send_polls(ctx.application, chat_id))
    return True

async def _auto_end(app, cid: int):
    await asyncio.sleep(TEST_DURATION)
    if cid in sess:
        try:
            await app.bot.send_message(
                cid, f"⏰ *10 minutes khatam!* Result aa raha hai...",
                parse_mode="Markdown")
        except Exception:
            pass
        await end_test(app, cid, forced=True)

async def _send_polls(app, cid: int):
    if cid not in sess: return
    s = sess[cid]
    total = len(s["questions"])
    q_time = s.get("q_time", TEST_Q_TIME)

    for i, q in enumerate(s["questions"]):
        if cid not in sess: return

        text = q_text(q, i, total)
        opts = q_opts(q)
        ans  = max(0, min(int(q.get("answer_index", 0)), len(opts)-1))

        try:
            msg = await app.bot.send_poll(
                chat_id          = cid,
                question         = text,
                options          = opts,
                type             = Poll.QUIZ,
                correct_option_id= ans,       # ✅ sahi = green, galat = red
                is_anonymous     = False,
                open_period      = min(max(q_time, 5), 600),
            )
            if cid in sess:
                sess[cid]["poll_map"][str(msg.poll.id)] = i
        except Exception as e:
            log.error("Poll Q%d: %s", i+1, e)

        await asyncio.sleep(q_time)

    if cid in sess:
        try:
            await app.bot.send_message(cid, "✅ Saare questions ho gaye! Result aa raha hai...")
        except Exception:
            pass
        await asyncio.sleep(5)
        await end_test(app, cid)

# ── Poll answer ──────────────────────────────────────────
async def on_poll_ans(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pa   = u.poll_answer
    pid  = str(pa.poll_id)
    user = pa.user
    uid  = str(user.id)

    for cid, s in list(sess.items()):
        if pid not in s["poll_map"]: continue
        qi      = s["poll_map"][pid]
        correct = int(s["questions"][qi].get("answer_index", 0))

        if uid not in s["user_data"]:
            s["user_data"][uid] = {
                "name":       user.full_name,
                "correct":    0,
                "wrong":      0,
                "start_time": s["start_time"],
                "last_time":  time.time(),
            }
        ud = s["user_data"][uid]
        ud["name"]      = user.full_name
        ud["last_time"] = time.time()

        if pa.option_ids and pa.option_ids[0] == correct:
            ud["correct"] += 1
        else:
            ud["wrong"] += 1
        break

# ── End test ─────────────────────────────────────────────
async def end_test(app, cid: int, forced: bool = False):
    if cid not in sess: return
    s = sess.pop(cid)

    if not forced and s.get("timer_task"):
        s["timer_task"].cancel()

    ud = s["user_data"]
    if not ud:
        try:
            await app.bot.send_message(cid, "📊 Kisi ne participate nahi kiya.")
        except Exception:
            pass
        return

    # Build result
    ranked = sorted(ud.items(),
        key=lambda x: (-x[1]["correct"], x[1]["last_time"]-x[1]["start_time"]))

    medals = {0:"🥇", 1:"🥈", 2:"🥉"}
    lines  = [
        f"🏁 *TEST RESULT — {now_ist().strftime('%d %b %Y, %I:%M %p IST')}* 🏁",
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    ]
    for i, (uid, d) in enumerate(ranked[:20]):
        el  = d["last_time"] - d["start_time"]
        tot = d["correct"] + d["wrong"]
        acc = round(d["correct"]/tot*100, 1) if tot else 0
        medal = medals.get(i, f"`{i+1}.`")
        lines.append(
            f"{medal} *{d['name']}*\n"
            f"   ✅ Sahi:`{d['correct']}` ❌ Galat:`{d['wrong']}`\n"
            f"   ⏱ Time:`{fmt_time(el)}` | 🎯 Accuracy:`{acc}%`")

    lines += ["\n━━━━━━━━━━━━━━━━━━━━━━",
              "🗑 _Ye result 2 ghante baad delete ho jayega_",
              "🏆 /leaderboard"]

    result_text = "\n".join(lines)

    # Send to group
    sent_ids = []
    try:
        msg = await app.bot.send_message(cid, result_text, parse_mode="Markdown")
        sent_ids.append(msg.message_id)
    except Exception as e:
        log.error("end_test send result: %s", e)

    # Schedule auto-delete after 2 hours
    if sent_ids:
        asyncio.create_task(_auto_delete(app, cid, sent_ids, delay=7200))

    # Save scores
    scores = load_sc()
    for uid, d in ud.items():
        el  = d["last_time"] - d["start_time"]
        tot = d["correct"] + d["wrong"]
        if uid not in scores:
            scores[uid] = {
                "name":"","total_score":0,"total_correct":0,
                "total_wrong":0,"tests_taken":0,"best_time":99999,"accuracy":0.0,
            }
        sv = scores[uid]
        sv["name"]          = d["name"]
        sv["total_score"]   += d["correct"]
        sv["total_correct"] += d["correct"]
        sv["total_wrong"]   += d["wrong"]
        sv["tests_taken"]   += 1
        if el < sv["best_time"]: sv["best_time"] = round(el, 1)
        tot2 = sv["total_correct"] + sv["total_wrong"]
        sv["accuracy"] = round(sv["total_correct"]/tot2*100, 1) if tot2 else 0

    ok, err = gh_write(S_FILE, scores, "Scores updated")
    if ok:
        gist_bak(scores)
        try:
            await app.bot.send_message(cid, "💾 Scores GitHub mein save ho gaye! ✅")
        except Exception:
            pass
    else:
        try:
            await app.bot.send_message(cid, f"⚠️ Scores save fail: {err}")
        except Exception:
            pass

async def _auto_delete(app, cid: int, msg_ids: list, delay: int):
    """Delete result messages after `delay` seconds."""
    await asyncio.sleep(delay)
    for mid in msg_ids:
        try:
            await app.bot.delete_message(cid, mid)
        except Exception:
            pass
    log.info("Auto-deleted result messages in %s", cid)

# ════════════════════════════════════════════════════════
# AUTO SCHEDULED TESTS
# ════════════════════════════════════════════════════════

async def auto_scheduler(app):
    """
    Runs forever. At each scheduled IST hour, starts a test in CHAT_ID.
    """
    log.info("Auto scheduler started. Test times IST: %s", AUTO_TEST_HOURS_IST)
    fired_hours = set()

    while True:
        try:
            now = now_ist()
            hour_min = (now.hour, now.minute)

            for h in AUTO_TEST_HOURS_IST:
                key = (now.date(), h)
                if now.hour == h and now.minute == 0 and key not in fired_hours:
                    cfg = load_cfg()
                    if cfg.get("auto_enabled", True) and CHAT_ID:
                        log.info("Auto test firing at %s IST", h)
                        fired_hours.add(key)
                        target = int(CHAT_ID)
                        if target not in sess:
                            asyncio.create_task(
                                begin_test(
                                    type("C",(),{"bot":app.bot,"application":app})(),
                                    target, "mixed", q_time=TEST_Q_TIME
                                )
                            )
                        else:
                            log.info("Test already running, skip auto at %s", h)

            # Keep fired_hours clean (only today)
            today = now.date()
            fired_hours = {k for k in fired_hours if k[0] == today}

        except Exception as e:
            log.error("scheduler: %s", e)

        await asyncio.sleep(30)   # check every 30 seconds

# ════════════════════════════════════════════════════════
# PARSE QUESTIONS TEXT
# ════════════════════════════════════════════════════════

def parse_qs(text: str) -> list:
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
                v = line.split(":",1)[1].strip()
                d["question_hi"] = v; d["question_en"] = v
            elif re.match(r"^[ABCD]:", low):
                opts.append(line.split(":",1)[1].strip())
            elif low.startswith("ANS:"):
                d["answer_index"] = am.get(line.split(":",1)[1].strip().upper(), 0)
        has_q = "question_hi" in d or "question_en" in d
        if has_q and len(opts) >= 2 and "answer_index" in d:
            d["options"]  = opts
            d["question"] = d.get("question_hi") or d.get("question_en","")
            result.append(d)
    return result

# ════════════════════════════════════════════════════════
# POST INIT
# ════════════════════════════════════════════════════════

async def post_init(app: Application):
    ok, msg = gh_token_ok()
    log.info("GitHub: %s", msg)
    # Start auto scheduler
    asyncio.create_task(auto_scheduler(app))

# ════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════

def main():
    if not BOT_TOKEN:
        log.error("BOT_TOKEN not set!"); return

    log.info("Starting Sarkari Naukri Academy Bot v7.0 (PTB 20.3)...")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

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
