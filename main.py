"""
╔══════════════════════════════════════════════════════════╗
║      SARKARI NAUKRI ACADEMY — ADVANCED QUIZ BOT v3.0     ║
║      Fixed for Railway + Python 3.13 + GitHub Storage    ║
╚══════════════════════════════════════════════════════════╝

Railway Variables Required:
  BOT_TOKEN     - Telegram Bot Token (BotFather se)
  ADMIN_ID      - Tumhara Telegram User ID (number)
  CHAT_ID       - Channel/Group ID ya @username
  GITHUB_TOKEN  - GitHub Personal Access Token
  GIST_ID       - GitHub Gist ID (scores backup)
  GROQ_KEY      - Groq AI API Key
  TIMER         - Seconds between polls (e.g. 30)
"""

import os
import json
import time
import asyncio
import logging
import random
import re
import base64

import requests
from telegram import (
    Update,
    Poll,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    PollAnswerHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ══════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════
BOT_TOKEN    = os.environ.get("BOT_TOKEN", "")
ADMIN_ID     = int(os.environ.get("ADMIN_ID", "0"))
CHAT_ID      = os.environ.get("CHAT_ID", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GIST_ID      = os.environ.get("GIST_ID", "")
GROQ_KEY     = os.environ.get("GROQ_KEY", "")
TIMER        = int(os.environ.get("TIMER", "30"))

GH_USER   = "aianimation9199-ops"
GH_REPO   = "sarkari-naukri-bot"
GH_BRANCH = "main"

TOTAL_Q      = 100
TEST_MINUTES = 15
TEST_SECONDS = TEST_MINUTES * 60

QUESTIONS_FILE = "quiz_data.json"
SCORES_FILE    = "scores.json"

# ══════════════════════════════════════════
# GITHUB STORAGE  (safe — never deletes other files)
# ══════════════════════════════════════════
GH_HDR = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept":        "application/vnd.github.v3+json",
}


def gh_read(filename: str):
    url = f"https://api.github.com/repos/{GH_USER}/{GH_REPO}/contents/{filename}"
    try:
        r = requests.get(url, headers=GH_HDR, timeout=15)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        raw = base64.b64decode(r.json()["content"]).decode("utf-8")
        return json.loads(raw)
    except Exception as exc:
        logger.error("gh_read(%s): %s", filename, exc)
        return []


def gh_write(filename: str, data, msg: str = "bot update") -> bool:
    url = f"https://api.github.com/repos/{GH_USER}/{GH_REPO}/contents/{filename}"
    sha = None
    try:
        r = requests.get(url, headers=GH_HDR, timeout=10)
        if r.status_code == 200:
            sha = r.json().get("sha")
    except Exception:
        pass

    content_b64 = base64.b64encode(
        json.dumps(data, ensure_ascii=False, indent=2).encode()
    ).decode()

    payload = {"message": msg, "content": content_b64, "branch": GH_BRANCH}
    if sha:
        payload["sha"] = sha

    try:
        r = requests.put(url, headers=GH_HDR, json=payload, timeout=20)
        r.raise_for_status()
        return True
    except Exception as exc:
        logger.error("gh_write(%s): %s", filename, exc)
        return False


def gist_backup(data: dict):
    if not GIST_ID:
        return
    try:
        requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=GH_HDR,
            json={"files": {"scores.json": {
                "content": json.dumps(data, ensure_ascii=False, indent=2)
            }}},
            timeout=10,
        )
    except Exception as exc:
        logger.warning("gist_backup: %s", exc)


# ══════════════════════════════════════════
# GROQ AI
# ══════════════════════════════════════════
def groq_generate(subject: str, count: int = 10) -> list:
    if not GROQ_KEY:
        return []
    prompt = (
        f'Generate {count} MCQ questions about "{subject}" for Indian Govt exams '
        f"(SSC/Railway/UPSC).\n"
        "Return ONLY valid JSON array. No extra text.\n"
        "[\n"
        '  {"question_hi":"हिंदी प्रश्न?","question_en":"English question?",'
        '"options":["हिंदी A / English A","हिंदी B / English B",'
        '"हिंदी C / English C","हिंदी D / English D"],'
        f'"answer_index":0,"subject":"{subject}"}}\n'
        "]\n"
        "answer_index is 0-based. Facts must be correct."
    )
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama3-8b-8192",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.5,
                "max_tokens": 4000,
            },
            timeout=30,
        )
        r.raise_for_status()
        text  = r.json()["choices"][0]["message"]["content"]
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as exc:
        logger.error("groq_generate: %s", exc)
    return []


# ══════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════

def load_questions() -> list:
    data = gh_read(QUESTIONS_FILE)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("questions", [])
    return []


def load_scores() -> dict:
    data = gh_read(SCORES_FILE)
    return data if isinstance(data, dict) else {}


def get_subjects(qs: list) -> list:
    return sorted({q.get("subject", "General") for q in qs})


def pick_questions(qs: list, mode: str, n: int) -> list:
    pool = qs if mode == "mixed" else [
        q for q in qs if q.get("subject", "General") == mode
    ]
    return random.sample(pool, min(n, len(pool)))


def fmt_time(sec: float) -> str:
    m, s = int(sec) // 60, int(sec) % 60
    return f"{m}m {s}s"


def build_q_text(q: dict, idx: int, total: int) -> str:
    hi = q.get("question_hi") or q.get("question", "")
    en = q.get("question_en", "")
    prefix = f"Q{idx + 1}/{total}: "
    if hi and en and hi != en:
        body = f"{hi}\n{en}"
    else:
        body = hi or en or "?"
    return (prefix + body)[:300]


def build_options(q: dict) -> list:
    return [str(o)[:100] for o in q.get("options", ["A", "B", "C", "D"])[:10]]


def leaderboard_msg(scores: dict, top: int = 20) -> str:
    if not scores:
        return "📊 Abhi koi score nahi hai.\n/test se shuru karo!"
    ranked = sorted(
        scores.items(),
        key=lambda x: (
            -x[1].get("total_score", 0),
            x[1].get("best_time", 99999),
        ),
    )[:top]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    lines  = ["🏆 *TOP LEADERBOARD* 🏆", "━━━━━━━━━━━━━━━━━━━━━━\n"]
    for i, (uid, d) in enumerate(ranked):
        correct = d.get("total_correct", 0)
        wrong   = d.get("total_wrong", 0)
        total   = correct + wrong
        acc     = round(correct / total * 100, 1) if total else 0
        medal   = medals.get(i, f"{i + 1}.")
        lines.append(
            f"{medal} *{d.get('name', '?')}*\n"
            f"   ✅ `{correct}` ❌ `{wrong}` | "
            f"⏱ `{fmt_time(d.get('best_time', 0))}` | 🎯 `{acc}%`\n"
            f"   📝 Tests: `{d.get('tests_taken', 0)}`"
        )
    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Mixed Test (सभी विषय)",  callback_data="mode_mixed")],
        [InlineKeyboardButton("📚 Subject-wise Test",       callback_data="mode_subject")],
        [InlineKeyboardButton("🤖 AI से Questions बनाओ",  callback_data="ai_gen")],
        [
            InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard"),
            InlineKeyboardButton("📊 My Score",    callback_data="myscore"),
        ],
        [InlineKeyboardButton("➕ Questions Add करो",      callback_data="addq_info")],
        [InlineKeyboardButton("📈 Status",                 callback_data="status")],
    ])


# ══════════════════════════════════════════
# ACTIVE SESSIONS
# ══════════════════════════════════════════
sessions: dict = {}


# ══════════════════════════════════════════
# COMMANDS
# ══════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎓 *Sarkari Naukri Academy Quiz Bot*\n\n"
        "• 100 Questions | ⏱ 15 Minutes\n"
        "• ✅ Sahi = +1 | ❌ Galat = counted\n"
        "• 📖 Hindi + English bilingual\n"
        "• 🏆 Live Leaderboard Top-20\n\n"
        "👇 Mode choose karo:",
        reply_markup=main_kb(),
        parse_mode="Markdown",
    )


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    qs     = load_questions()
    scores = load_scores()
    subj   = get_subjects(qs)
    s_info = "\n".join(
        f"  • {s}: {sum(1 for q in qs if q.get('subject', 'General') == s)}"
        for s in subj
    ) or "  None"
    await update.message.reply_text(
        f"📊 *Bot Status*\n━━━━━━━━━━━━━━━━━\n"
        f"❓ Questions: `{len(qs)}`\n"
        f"👥 Users: `{len(scores)}`\n"
        f"🔴 Active Tests: `{len(sessions)}`\n"
        f"⏱ Poll Timer: `{TIMER}s`\n\n"
        f"*Subjects:*\n{s_info}\n━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown",
    )


async def cmd_leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        leaderboard_msg(load_scores()), parse_mode="Markdown"
    )


async def cmd_stoptest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if cid in sessions:
        await finish_test(ctx.application, cid, forced=True)
        await update.message.reply_text("⏹ Test rok diya gaya.")
    else:
        await update.message.reply_text("Koi test chal nahi raha abhi.")


async def cmd_addq(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Sirf admin.")
        return
    ctx.user_data["await_q"] = True
    await update.message.reply_text(
        "📝 *Questions Paste Karo — Format:*\n\n"
        "```\nSUBJECT: History\n"
        "QH: हिंदी में प्रश्न?\n"
        "QE: Question in English?\n"
        "A: Option A हिंदी / English\n"
        "B: Option B हिंदी / English\n"
        "C: Option C हिंदी / English\n"
        "D: Option D हिंदी / English\n"
        "ANS: B\n---\n```\n"
        "Multiple questions ke beech `---` lagao.\n"
        "⚠️ Purane questions DELETE NAHI HONGE.",
        parse_mode="Markdown",
    )


async def cmd_myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text(
        f"👤 *Your Info*\nID: `{u.id}`\nName: {u.full_name}",
        parse_mode="Markdown",
    )


async def cmd_deleteall(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Sirf admin.")
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Haan Delete Karo", callback_data="confirm_del")],
        [InlineKeyboardButton("❌ Cancel",           callback_data="cancel_del")],
    ])
    await update.message.reply_text(
        "⚠️ *Kya SAARE questions delete karne hain?*\nYe undo nahi hoga!",
        reply_markup=kb,
        parse_mode="Markdown",
    )


# ══════════════════════════════════════════
# CALLBACK HANDLER
# ══════════════════════════════════════════

async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    await q.answer()
    data = q.data
    cid  = q.message.chat_id
    user = q.from_user

    if data == "leaderboard":
        await q.message.reply_text(
            leaderboard_msg(load_scores()), parse_mode="Markdown"
        )

    elif data == "myscore":
        uid    = str(user.id)
        scores = load_scores()
        if uid in scores:
            d       = scores[uid]
            correct = d.get("total_correct", 0)
            wrong   = d.get("total_wrong", 0)
            total   = correct + wrong
            acc     = round(correct / total * 100, 1) if total else 0
            await q.message.reply_text(
                f"📊 *Tumhara Score*\n━━━━━━━━━━━━━━\n"
                f"👤 {d.get('name', '?')}\n"
                f"✅ Sahi: `{correct}`\n"
                f"❌ Galat: `{wrong}`\n"
                f"🎯 Accuracy: `{acc}%`\n"
                f"📝 Tests: `{d.get('tests_taken', 0)}`\n"
                f"⏱ Best Time: `{fmt_time(d.get('best_time', 0))}`\n"
                f"🏆 Total Score: `{d.get('total_score', 0)}`",
                parse_mode="Markdown",
            )
        else:
            await q.message.reply_text(
                "Tumne abhi koi test nahi diya.\n/test se shuru karo!"
            )

    elif data == "status":
        qs     = load_questions()
        scores = load_scores()
        subj   = get_subjects(qs)
        s_info = "\n".join(
            f"  • {s}: {sum(1 for x in qs if x.get('subject', 'General') == s)}"
            for s in subj
        ) or "  None"
        await q.message.reply_text(
            f"📊 *Status*\n"
            f"❓ `{len(qs)}` Questions | 👥 `{len(scores)}` Users\n"
            f"🔴 Active Tests: `{len(sessions)}`\n\n"
            f"*Subjects:*\n{s_info}",
            parse_mode="Markdown",
        )

    elif data == "mode_mixed":
        await begin_test(ctx, cid, "mixed")

    elif data == "mode_subject":
        qs   = load_questions()
        subj = get_subjects(qs)
        if not subj:
            await q.message.reply_text("❌ Koi questions nahi. Pehle add karo.")
            return
        kb = [[InlineKeyboardButton(f"📌 {s}", callback_data=f"subj_{s}")] for s in subj]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="back")])
        await q.message.reply_text(
            "📚 *Subject choose karo:*",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown",
        )

    elif data.startswith("subj_"):
        await begin_test(ctx, cid, data[5:])

    elif data == "ai_gen":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin AI generate kar sakta hai.")
            return
        ctx.user_data["await_ai"] = True
        await q.message.reply_text(
            "🤖 *Subject ka naam likho:*\n_Example: History, Science, Geography_",
            parse_mode="Markdown",
        )

    elif data == "addq_info":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin.")
            return
        ctx.user_data["await_q"] = True
        await q.message.reply_text(
            "📝 *Format:*\n```\nSUBJECT: GK\n"
            "QH: हिंदी प्रश्न?\nQE: English question?\n"
            "A: Option A\nB: Option B\nC: Option C\nD: Option D\n"
            "ANS: A\n---\n```",
            parse_mode="Markdown",
        )

    elif data == "back":
        await q.message.reply_text("👇 Mode choose karo:", reply_markup=main_kb())

    elif data == "confirm_del":
        if user.id != ADMIN_ID:
            return
        gh_write(QUESTIONS_FILE, [], "Admin: delete all questions")
        await q.message.reply_text("🗑 Saare questions delete ho gaye.")

    elif data == "cancel_del":
        await q.message.reply_text("✅ Cancelled. Kuch delete nahi hua.")


# ══════════════════════════════════════════
# MESSAGE HANDLER
# ══════════════════════════════════════════

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()

    if user.id == ADMIN_ID and ctx.user_data.get("await_ai"):
        ctx.user_data.pop("await_ai")
        await update.message.reply_text(
            f"🤖 AI se *{text}* ke questions bana raha hoon...",
            parse_mode="Markdown",
        )
        qs_new = groq_generate(text, 10)
        if not qs_new:
            await update.message.reply_text(
                "❌ AI se questions nahi aaye.\nGROQ_KEY check karo ya baad mein try karo."
            )
            return
        qs_all = load_questions()
        qs_all.extend(qs_new)
        if gh_write(QUESTIONS_FILE, qs_all, f"AI: {len(qs_new)} {text} questions"):
            await update.message.reply_text(
                f"✅ {len(qs_new)} questions add!\nTotal: {len(qs_all)}"
            )
        else:
            await update.message.reply_text("❌ GitHub save fail. Token check karo.")
        return

    if user.id == ADMIN_ID and ctx.user_data.get("await_q"):
        ctx.user_data.pop("await_q")
        parsed = parse_q_text(text)
        if not parsed:
            await update.message.reply_text("❌ Format galat.\n/addq se format dekho.")
            return
        qs_all = load_questions()
        qs_all.extend(parsed)
        if gh_write(QUESTIONS_FILE, qs_all, f"Manual: {len(parsed)} questions"):
            await update.message.reply_text(
                f"✅ {len(parsed)} questions add!\nTotal: {len(qs_all)}\n💾 GitHub safe ✅"
            )
        else:
            await update.message.reply_text("❌ GitHub save fail.")
        return

    await update.message.reply_text("👇 Menu:", reply_markup=main_kb())


# ══════════════════════════════════════════
# TEST FLOW
# ══════════════════════════════════════════

async def begin_test(ctx: ContextTypes.DEFAULT_TYPE, cid: int, mode: str):
    if cid in sessions:
        await ctx.bot.send_message(
            cid, "⚠️ Ek test chal raha hai.\n/stoptest se pehle band karo."
        )
        return

    qs_all   = load_questions()
    selected = pick_questions(qs_all, mode, TOTAL_Q)

    if not selected:
        msg = (
            "❌ Koi questions nahi hai." if not qs_all
            else f"❌ '{mode}' mein questions nahi hain."
        )
        await ctx.bot.send_message(cid, msg)
        return

    sessions[cid] = {
        "questions":  selected,
        "poll_map":   {},
        "user_data":  {},
        "start_time": time.time(),
        "mode":       mode,
        "timer_task": None,
    }

    label = "🔀 Mixed (सभी विषय)" if mode == "mixed" else f"📌 {mode}"
    await ctx.bot.send_message(
        cid,
        f"🚀 *TEST SHURU!*\n━━━━━━━━━━━━━━━━━\n"
        f"📋 Mode: {label}\n"
        f"❓ Questions: {len(selected)}\n"
        f"⏱ Time Limit: {TEST_MINUTES} minutes\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"✅ Sahi = +1 mark | ❌ Galat = counted\n"
        f"Band karne ke liye: /stoptest\n\n"
        f"*All the best! 🎯*",
        parse_mode="Markdown",
    )

    task = asyncio.create_task(_auto_end(ctx.application, cid))
    sessions[cid]["timer_task"] = task
    asyncio.create_task(_send_polls(ctx.application, cid))


async def _auto_end(app, cid: int):
    await asyncio.sleep(TEST_SECONDS)
    if cid in sessions:
        await app.bot.send_message(
            cid,
            f"⏰ *{TEST_MINUTES} minutes khatam!*\nResults aa rahe hain...",
            parse_mode="Markdown",
        )
        await finish_test(app, cid, forced=True)


async def _send_polls(app, cid: int):
    if cid not in sessions:
        return
    sess  = sessions[cid]
    total = len(sess["questions"])

    for idx, q in enumerate(sess["questions"]):
        if cid not in sessions:
            return

        text    = build_q_text(q, idx, total)
        options = build_options(q)
        ans     = max(0, min(int(q.get("answer_index", 0)), len(options) - 1))

        try:
            msg = await app.bot.send_poll(
                chat_id           = cid,
                question          = text,
                options           = options,
                type              = Poll.QUIZ,
                correct_option_id = ans,        # ✅ SIRF SAHI OPTION PAR TICK
                is_anonymous      = False,
                open_period       = min(max(TIMER, 5), 600),
            )
            sessions[cid]["poll_map"][str(msg.poll.id)] = idx
        except Exception as exc:
            logger.error("Poll send error Q%d: %s", idx + 1, exc)

        await asyncio.sleep(TIMER)

    if cid in sessions:
        await app.bot.send_message(
            cid, "✅ Saare questions ho gaye!\nResult aa raha hai..."
        )
        await asyncio.sleep(10)
        await finish_test(app, cid)


# ══════════════════════════════════════════
# POLL ANSWER HANDLER
# ══════════════════════════════════════════

async def on_poll_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pa   = update.poll_answer
    pid  = str(pa.poll_id)
    user = pa.user
    uid  = str(user.id)

    for cid, sess in list(sessions.items()):
        if pid not in sess["poll_map"]:
            continue

        q_idx   = sess["poll_map"][pid]
        correct = int(sess["questions"][q_idx].get("answer_index", 0))

        if uid not in sess["user_data"]:
            sess["user_data"][uid] = {
                "name":       user.full_name,
                "correct":    0,
                "wrong":      0,
                "start_time": sess["start_time"],
                "last_time":  time.time(),
            }

        ud = sess["user_data"][uid]
        ud["name"]      = user.full_name
        ud["last_time"] = time.time()

        if pa.option_ids and pa.option_ids[0] == correct:
            ud["correct"] += 1
        else:
            ud["wrong"] += 1
        break


# ══════════════════════════════════════════
# FINISH TEST
# ══════════════════════════════════════════

async def finish_test(app, cid: int, forced: bool = False):
    if cid not in sessions:
        return

    sess = sessions.pop(cid)
    if not forced and sess.get("timer_task"):
        sess["timer_task"].cancel()

    ud = sess["user_data"]
    if not ud:
        await app.bot.send_message(cid, "📊 Kisi ne participate nahi kiya.")
        return

    ranked = sorted(
        ud.items(),
        key=lambda x: (
            -x[1]["correct"],
            x[1]["last_time"] - x[1]["start_time"],
        ),
    )

    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    lines  = ["🏁 *TEST RESULT* 🏁", "━━━━━━━━━━━━━━━━━━━━━━\n"]

    for i, (uid, d) in enumerate(ranked[:20]):
        elapsed = d["last_time"] - d["start_time"]
        total   = d["correct"] + d["wrong"]
        acc     = round(d["correct"] / total * 100, 1) if total else 0
        medal   = medals.get(i, f"{i + 1}.")
        lines.append(
            f"{medal} *{d['name']}*\n"
            f"   ✅ Sahi: `{d['correct']}` | ❌ Galat: `{d['wrong']}`\n"
            f"   ⏱ Time: `{fmt_time(elapsed)}` | 🎯 Acc: `{acc}%`"
        )

    lines += ["\n━━━━━━━━━━━━━━━━━━━━━━", "🏆 /leaderboard"]
    await app.bot.send_message(cid, "\n".join(lines), parse_mode="Markdown")

    # Save scores (safe — only scores.json touched)
    scores = load_scores()

    for uid, d in ud.items():
        elapsed = d["last_time"] - d["start_time"]
        total   = d["correct"] + d["wrong"]
        acc_pct = round(d["correct"] / total * 100, 1) if total else 0

        if uid not in scores:
            scores[uid] = {
                "name":          d["name"],
                "total_score":   0,
                "total_correct": 0,
                "total_wrong":   0,
                "tests_taken":   0,
                "best_time":     99999,
                "accuracy":      0.0,
            }

        s = scores[uid]
        s["name"]          = d["name"]
        s["total_score"]   += d["correct"]
        s["total_correct"] += d["correct"]
        s["total_wrong"]   += d["wrong"]
        s["tests_taken"]   += 1
        if elapsed < s["best_time"]:
            s["best_time"] = round(elapsed, 1)
        tot = s["total_correct"] + s["total_wrong"]
        s["accuracy"] = round(s["total_correct"] / tot * 100, 1) if tot else 0

    if gh_write(SCORES_FILE, scores, "Scores updated after test"):
        gist_backup(scores)
        await app.bot.send_message(cid, "💾 Scores GitHub mein save ho gaye! ✅")
    else:
        await app.bot.send_message(
            cid, "⚠️ Scores save nahi hue. GitHub token check karo."
        )


# ══════════════════════════════════════════
# PARSE QUESTIONS
# ══════════════════════════════════════════

def parse_q_text(text: str) -> list:
    blocks  = text.strip().split("---")
    result  = []
    ans_map = {"A": 0, "B": 1, "C": 2, "D": 3}

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        d       = {"subject": "General"}
        options = []

        for line in block.splitlines():
            line = line.strip()
            if not line:
                continue
            low = line.upper()

            if low.startswith("SUBJECT:"):
                d["subject"]     = line.split(":", 1)[1].strip()
            elif low.startswith("QH:"):
                d["question_hi"] = line.split(":", 1)[1].strip()
            elif low.startswith("QE:"):
                d["question_en"] = line.split(":", 1)[1].strip()
            elif low.startswith("Q:"):
                v                = line.split(":", 1)[1].strip()
                d["question_hi"] = v
                d["question_en"] = v
            elif re.match(r"^[ABCD]:", low):
                options.append(line.split(":", 1)[1].strip())
            elif low.startswith("ANS:"):
                ans = line.split(":", 1)[1].strip().upper()
                d["answer_index"] = ans_map.get(ans, 0)

        has_q = "question_hi" in d or "question_en" in d
        if has_q and len(options) >= 2 and "answer_index" in d:
            d["options"]  = options
            d["question"] = d.get("question_hi") or d.get("question_en", "")
            result.append(d)

    return result


# ══════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set in Railway variables!")
        return

    logger.info("Starting Sarkari Naukri Academy Bot v3.0...")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("test",        cmd_start))
    app.add_handler(CommandHandler("status",      cmd_status))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("stoptest",    cmd_stoptest))
    app.add_handler(CommandHandler("addq",        cmd_addq))
    app.add_handler(CommandHandler("myid",        cmd_myid))
    app.add_handler(CommandHandler("deleteall",   cmd_deleteall))

    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(PollAnswerHandler(on_poll_answer))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    logger.info("Bot is running!")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
