"""
Sarkari Naukri Academy - Telegram Quiz Bot
==========================================
Features:
- Subject-wise + Mixed quiz mode
- 100 questions, 15 min timed test
- Correct answer only gets ✅ tick
- Wrong answer = Wrong count
- Top 20 Leaderboard (score + time)
- GitHub Gist storage (existing data safe)
- Railway.app compatible
"""

import os
import json
import time
import asyncio
import requests
import logging
from datetime import datetime
from telegram import (
    Update, Poll, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    PollAnswerHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# ─────────────────────────────────────────────
# CONFIG — Set these in Railway Environment Variables
# ─────────────────────────────────────────────
BOT_TOKEN       = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
ADMIN_ID        = int(os.environ.get("ADMIN_ID", "123456789"))   # Your Telegram user ID
GITHUB_TOKEN    = os.environ.get("GITHUB_TOKEN", "")             # GitHub Personal Access Token
GIST_ID         = os.environ.get("GIST_ID", "")                  # Your GitHub Gist ID
CHANNEL_ID      = os.environ.get("CHANNEL_ID", "@your_channel")  # Channel/Group username or ID

# Quiz settings
TOTAL_QUESTIONS  = 100     # Questions per test
TEST_DURATION    = 15 * 60 # 15 minutes in seconds
POLL_INTERVAL    = 8       # Seconds between polls during test

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# GITHUB GIST STORAGE
# ─────────────────────────────────────────────
GIST_HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

def gist_read(filename: str) -> dict | list:
    """Read a JSON file from GitHub Gist. Returns empty dict/list on failure."""
    try:
        r = requests.get(f"https://api.github.com/gists/{GIST_ID}", headers=GIST_HEADERS, timeout=10)
        r.raise_for_status()
        content = r.json()["files"].get(filename, {}).get("content", "{}")
        return json.loads(content)
    except Exception as e:
        logger.error(f"Gist read error ({filename}): {e}")
        return {}

def gist_write(filename: str, data: dict | list):
    """Write/update a single file in GitHub Gist without touching other files."""
    try:
        payload = {"files": {filename: {"content": json.dumps(data, ensure_ascii=False, indent=2)}}}
        r = requests.patch(f"https://api.github.com/gists/{GIST_ID}", headers=GIST_HEADERS,
                           json=payload, timeout=10)
        r.raise_for_status()
        logger.info(f"Gist updated: {filename}")
    except Exception as e:
        logger.error(f"Gist write error ({filename}): {e}")

# ─────────────────────────────────────────────
# GIST FILE NAMES
# ─────────────────────────────────────────────
QUESTIONS_FILE  = "questions.json"    # [{question, options, answer_index, subject}, ...]
SCORES_FILE     = "scores.json"       # {user_id: {name, total_score, tests_taken, best_time}}
SESSIONS_FILE   = "sessions.json"     # Active test sessions

# ─────────────────────────────────────────────
# IN-MEMORY SESSION STATE
# ─────────────────────────────────────────────
# active_tests[chat_id] = {
#   "questions": [...],       # Selected questions for this test
#   "current": 0,             # Current question index
#   "poll_id_map": {},        # poll_id -> question_index
#   "user_answers": {},       # user_id -> {correct, wrong, time_start, time_end}
#   "start_time": float,
#   "mode": "mixed"|subject,
#   "timer_task": asyncio.Task
# }
active_tests = {}

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def get_subjects(questions: list) -> list:
    subjects = sorted(set(q.get("subject", "General") for q in questions))
    return subjects

def select_questions(questions: list, mode: str, count: int) -> list:
    import random
    if mode == "mixed":
        pool = questions.copy()
    else:
        pool = [q for q in questions if q.get("subject", "General") == mode]
    if len(pool) < count:
        count = len(pool)
    return random.sample(pool, count)

def format_time(seconds: float) -> str:
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m}m {s}s"

def leaderboard_text(scores: dict, top_n: int = 20) -> str:
    if not scores:
        return "📊 Abhi koi score nahi hai."
    
    sorted_scores = sorted(
        scores.items(),
        key=lambda x: (-x[1].get("total_score", 0), x[1].get("best_time", 9999))
    )[:top_n]
    
    medals = ["🥇","🥈","🥉"]
    lines = ["🏆 *TOP LEADERBOARD* 🏆\n"]
    for i, (uid, data) in enumerate(sorted_scores):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = data.get("name", "Unknown")
        score = data.get("total_score", 0)
        best = format_time(data.get("best_time", 0))
        tests = data.get("tests_taken", 0)
        lines.append(f"{medal} *{name}*\n   ✅ Score: {score} | ⏱ Best: {best} | 📝 Tests: {tests}")
    
    return "\n".join(lines)

# ─────────────────────────────────────────────
# COMMANDS
# ─────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📝 Start Test (Mixed)", callback_data="mode_mixed")],
        [InlineKeyboardButton("📚 Subject-wise Test", callback_data="mode_subject")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
        [InlineKeyboardButton("📊 My Score", callback_data="myscore")],
    ]
    await update.message.reply_text(
        "🎓 *Sarkari Naukri Academy Quiz Bot*\n\n"
        "100 questions | ⏱ 15 minutes\n"
        "Sahi answer = ✅ | Galat = ❌\n\n"
        "Mode choose karo:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def cmd_addq(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin: Add questions via text paste.
    Format (one question per block):
    SUBJECT: History
    Q: Question text?
    A: Option1
    B: Option2
    C: Option3
    D: Option4
    ANS: B
    ---
    """
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Sirf admin use kar sakta hai.")
        return
    
    ctx.user_data["awaiting_questions"] = True
    await update.message.reply_text(
        "📝 Questions paste karo is format mein:\n\n"
        "```\nSUBJECT: History\n"
        "Q: Question yahan?\n"
        "A: Option 1\nB: Option 2\nC: Option 3\nD: Option 4\n"
        "ANS: B\n---\n```\n"
        "Multiple questions ke beech `---` lagao.",
        parse_mode="Markdown"
    )

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    questions = gist_read(QUESTIONS_FILE)
    if not isinstance(questions, list):
        questions = []
    scores = gist_read(SCORES_FILE)
    if not isinstance(scores, dict):
        scores = {}
    
    subjects = get_subjects(questions)
    subj_counts = {s: sum(1 for q in questions if q.get("subject") == s) for s in subjects}
    subj_text = "\n".join(f"  📌 {s}: {c}" for s, c in subj_counts.items())
    
    active = len(active_tests)
    text = (
        f"📊 *Bot Status*\n\n"
        f"❓ Total Questions: {len(questions)}\n"
        f"👥 Total Users: {len(scores)}\n"
        f"🔴 Active Tests: {active}\n\n"
        f"*Subjects:*\n{subj_text or '  None'}\n\n"
        f"💾 Storage: GitHub Gist ✅"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    scores = gist_read(SCORES_FILE)
    if not isinstance(scores, dict):
        scores = {}
    await update.message.reply_text(leaderboard_text(scores), parse_mode="Markdown")

async def cmd_stop_test(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in active_tests:
        await end_test(ctx.application, chat_id, forced=True)
        await update.message.reply_text("⏹ Test rok diya gaya.")
    else:
        await update.message.reply_text("Koi test chal nahi raha.")

# ─────────────────────────────────────────────
# CALLBACK HANDLER (Inline Buttons)
# ─────────────────────────────────────────────

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    if data == "leaderboard":
        scores = gist_read(SCORES_FILE)
        if not isinstance(scores, dict):
            scores = {}
        await query.message.reply_text(leaderboard_text(scores), parse_mode="Markdown")
        return

    if data == "myscore":
        uid = str(query.from_user.id)
        scores = gist_read(SCORES_FILE)
        if not isinstance(scores, dict):
            scores = {}
        if uid in scores:
            d = scores[uid]
            text = (
                f"📊 *Tumhara Score*\n\n"
                f"👤 {d.get('name','?')}\n"
                f"✅ Total Score: {d.get('total_score',0)}\n"
                f"📝 Tests Liye: {d.get('tests_taken',0)}\n"
                f"⏱ Best Time: {format_time(d.get('best_time',0))}"
            )
        else:
            text = "Tumne abhi koi test nahi diya."
        await query.message.reply_text(text, parse_mode="Markdown")
        return

    if data == "mode_mixed":
        await start_test(update, ctx, chat_id, mode="mixed")
        return

    if data == "mode_subject":
        questions = gist_read(QUESTIONS_FILE)
        if not isinstance(questions, list):
            questions = []
        subjects = get_subjects(questions)
        if not subjects:
            await query.message.reply_text("❌ Koi questions nahi hain. Pehle questions add karo.")
            return
        keyboard = [[InlineKeyboardButton(s, callback_data=f"subject_{s}")] for s in subjects]
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_start")])
        await query.message.reply_text(
            "📚 Subject choose karo:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("subject_"):
        subject = data[len("subject_"):]
        await start_test(update, ctx, chat_id, mode=subject)
        return

    if data == "back_start":
        keyboard = [
            [InlineKeyboardButton("📝 Start Test (Mixed)", callback_data="mode_mixed")],
            [InlineKeyboardButton("📚 Subject-wise Test", callback_data="mode_subject")],
            [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
            [InlineKeyboardButton("📊 My Score", callback_data="myscore")],
        ]
        await query.message.reply_text(
            "Mode choose karo:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

# ─────────────────────────────────────────────
# TEST FLOW
# ─────────────────────────────────────────────

async def start_test(update: Update, ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, mode: str):
    if chat_id in active_tests:
        await ctx.bot.send_message(chat_id, "⚠️ Ek test pehle se chal raha hai. Pehle /stoptest karo.")
        return

    questions_all = gist_read(QUESTIONS_FILE)
    if not isinstance(questions_all, list) or len(questions_all) == 0:
        await ctx.bot.send_message(chat_id, "❌ Koi questions nahi hain. Admin se contact karo.")
        return

    selected = select_questions(questions_all, mode, TOTAL_QUESTIONS)
    if len(selected) == 0:
        await ctx.bot.send_message(chat_id, f"❌ '{mode}' subject mein koi questions nahi.")
        return

    active_tests[chat_id] = {
        "questions": selected,
        "current": 0,
        "poll_id_map": {},         # poll_id (str) -> question_index
        "user_answers": {},        # user_id -> {name, correct, wrong, start_time, end_time}
        "start_time": time.time(),
        "mode": mode,
        "chat_id": chat_id,
        "timer_task": None,
    }

    mode_text = "🔀 Mixed (All Subjects)" if mode == "mixed" else f"📚 {mode}"
    await ctx.bot.send_message(
        chat_id,
        f"🚀 *TEST SHURU!*\n\n"
        f"📋 Mode: {mode_text}\n"
        f"❓ Questions: {len(selected)}\n"
        f"⏱ Time: 15 minutes\n\n"
        f"Har sahi answer = +1 | Galat = counted as wrong\n"
        f"*All the best! 🎯*",
        parse_mode="Markdown"
    )

    # Send first poll immediately, then schedule rest
    await send_next_poll(ctx.application, chat_id)

    # Start test timer — auto-end after 15 min
    task = asyncio.create_task(test_timer(ctx.application, chat_id))
    active_tests[chat_id]["timer_task"] = task

async def test_timer(app, chat_id: int):
    """Auto-end test after TEST_DURATION seconds."""
    await asyncio.sleep(TEST_DURATION)
    if chat_id in active_tests:
        await app.bot.send_message(chat_id, "⏰ *15 minutes khatam!* Test automatically band ho raha hai...", parse_mode="Markdown")
        await end_test(app, chat_id, forced=True)

async def send_next_poll(app, chat_id: int):
    """Send the next quiz poll in the active test."""
    if chat_id not in active_tests:
        return
    
    session = active_tests[chat_id]
    idx = session["current"]
    questions = session["questions"]
    
    if idx >= len(questions):
        await end_test(app, chat_id)
        return

    q = questions[idx]
    question_text = q.get("question", "Question?")
    options = q.get("options", ["A", "B", "C", "D"])
    correct_idx = int(q.get("answer_index", 0))

    # Prefix with question number
    full_question = f"Q{idx+1}/{len(questions)}: {question_text}"
    if len(full_question) > 300:
        full_question = full_question[:297] + "..."

    try:
        msg = await app.bot.send_poll(
            chat_id=chat_id,
            question=full_question,
            options=options,
            type=Poll.QUIZ,
            correct_option_id=correct_idx,
            is_anonymous=False,
            open_period=POLL_INTERVAL + 2,  # Auto-close slightly after interval
        )
        poll_id = str(msg.poll.id)
        session["poll_id_map"][poll_id] = idx
        session["current"] += 1

        # Schedule next poll
        await asyncio.sleep(POLL_INTERVAL)
        await send_next_poll(app, chat_id)

    except Exception as e:
        logger.error(f"Error sending poll: {e}")
        await asyncio.sleep(2)
        session["current"] += 1
        await send_next_poll(app, chat_id)

# ─────────────────────────────────────────────
# POLL ANSWER HANDLER
# ─────────────────────────────────────────────

async def poll_answer_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    poll_id = str(answer.poll_id)
    user = answer.user
    uid = str(user.id)
    name = user.full_name

    # Find which test this poll belongs to
    for chat_id, session in active_tests.items():
        if poll_id not in session["poll_id_map"]:
            continue

        q_idx = session["poll_id_map"][poll_id]
        question = session["questions"][q_idx]
        correct_idx = int(question.get("answer_index", 0))

        # Init user tracking
        if uid not in session["user_answers"]:
            session["user_answers"][uid] = {
                "name": name,
                "correct": 0,
                "wrong": 0,
                "start_time": session["start_time"],
                "end_time": None,
            }

        user_data = session["user_answers"][uid]
        user_data["name"] = name  # Update name
        user_data["end_time"] = time.time()  # Update last answer time

        if answer.option_ids and answer.option_ids[0] == correct_idx:
            user_data["correct"] += 1
        else:
            user_data["wrong"] += 1

        break  # Found the session, stop searching

# ─────────────────────────────────────────────
# END TEST & SAVE SCORES
# ─────────────────────────────────────────────

async def end_test(app, chat_id: int, forced: bool = False):
    if chat_id not in active_tests:
        return

    session = active_tests.pop(chat_id)

    # Cancel timer if test ended naturally
    if session.get("timer_task") and not forced:
        session["timer_task"].cancel()

    user_answers = session["user_answers"]
    test_start = session["start_time"]

    if not user_answers:
        await app.bot.send_message(chat_id, "📊 Kisi ne bhi participate nahi kiya.")
        return

    # Sort by correct DESC, then time ASC
    results = sorted(
        user_answers.items(),
        key=lambda x: (-x[1]["correct"], (x[1]["end_time"] or time.time()) - x[1]["start_time"])
    )

    # Build result message
    medals = ["🥇","🥈","🥉"]
    lines = ["🏁 *TEST RESULT* 🏁\n"]
    for i, (uid, d) in enumerate(results[:20]):
        medal = medals[i] if i < 3 else f"{i+1}."
        elapsed = (d["end_time"] or time.time()) - d["start_time"]
        lines.append(
            f"{medal} *{d['name']}*\n"
            f"   ✅ Sahi: {d['correct']} | ❌ Galat: {d['wrong']} | ⏱ Time: {format_time(elapsed)}"
        )

    await app.bot.send_message(chat_id, "\n".join(lines), parse_mode="Markdown")

    # Save to GitHub Gist (safe update — don't overwrite other data)
    scores = gist_read(SCORES_FILE)
    if not isinstance(scores, dict):
        scores = {}

    for uid, d in user_answers.items():
        elapsed = (d["end_time"] or time.time()) - d["start_time"]
        if uid not in scores:
            scores[uid] = {
                "name": d["name"],
                "total_score": 0,
                "tests_taken": 0,
                "best_time": 9999
            }
        scores[uid]["name"] = d["name"]
        scores[uid]["total_score"] += d["correct"]
        scores[uid]["tests_taken"] += 1
        if elapsed < scores[uid]["best_time"]:
            scores[uid]["best_time"] = elapsed

    gist_write(SCORES_FILE, scores)
    await app.bot.send_message(chat_id, "💾 Scores GitHub Gist mein save ho gaye! ✅")

# ─────────────────────────────────────────────
# ADD QUESTIONS VIA TEXT (Admin)
# ─────────────────────────────────────────────

async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text or ""

    # Admin: add questions
    if user.id == ADMIN_ID and ctx.user_data.get("awaiting_questions"):
        ctx.user_data["awaiting_questions"] = False
        parsed = parse_questions_text(text)
        if not parsed:
            await update.message.reply_text("❌ Format galat hai. /addq command se dobara try karo.")
            return

        questions = gist_read(QUESTIONS_FILE)
        if not isinstance(questions, list):
            questions = []
        questions.extend(parsed)
        gist_write(QUESTIONS_FILE, questions)
        await update.message.reply_text(
            f"✅ {len(parsed)} questions add ho gaye!\n"
            f"📊 Total questions: {len(questions)}"
        )
        return

    # Default: show menu
    await cmd_start(update, ctx)

def parse_questions_text(text: str) -> list:
    """
    Parse questions from text format:
    SUBJECT: History
    Q: Question?
    A: Option1
    B: Option2
    C: Option3
    D: Option4
    ANS: B
    ---
    """
    blocks = text.strip().split("---")
    parsed = []
    
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        
        lines = block.split("\n")
        data = {}
        options = []
        
        for line in lines:
            line = line.strip()
            if line.upper().startswith("SUBJECT:"):
                data["subject"] = line.split(":", 1)[1].strip()
            elif line.upper().startswith("Q:"):
                data["question"] = line.split(":", 1)[1].strip()
            elif line.upper().startswith("A:"):
                options.append(line.split(":", 1)[1].strip())
            elif line.upper().startswith("B:"):
                options.append(line.split(":", 1)[1].strip())
            elif line.upper().startswith("C:"):
                options.append(line.split(":", 1)[1].strip())
            elif line.upper().startswith("D:"):
                options.append(line.split(":", 1)[1].strip())
            elif line.upper().startswith("ANS:"):
                ans = line.split(":", 1)[1].strip().upper()
                ans_map = {"A": 0, "B": 1, "C": 2, "D": 3}
                data["answer_index"] = ans_map.get(ans, 0)
        
        if "question" in data and len(options) >= 2 and "answer_index" in data:
            data["options"] = options
            data.setdefault("subject", "General")
            parsed.append(data)
    
    return parsed

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("addq", cmd_addq))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("stoptest", cmd_stop_test))
    
    # Callbacks
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    # Poll answers
    app.add_handler(PollAnswerHandler(poll_answer_handler))
    
    # Text messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("✅ Bot chal raha hai...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
