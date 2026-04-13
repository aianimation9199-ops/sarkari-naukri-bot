"""
╔══════════════════════════════════════════════════════╗
║     SARKARI NAUKRI ACADEMY - ADVANCED QUIZ BOT       ║
║     Railway.app + GitHub Storage + Groq AI           ║
╚══════════════════════════════════════════════════════╝

Railway Environment Variables needed:
  BOT_TOKEN     - Telegram Bot Token
  ADMIN_ID      - Your Telegram User ID
  CHAT_ID       - Your Channel/Group ID
  GITHUB_TOKEN  - GitHub Personal Access Token
  API_ID        - Telegram API ID (for Pyrogram if needed)
  API_HASH      - Telegram API Hash
  GROQ_KEY      - Groq AI API Key
  TIMER         - Poll interval in seconds (e.g. 60)
"""

import os, json, time, asyncio, logging, random, re
import requests
from datetime import datetime
from telegram import (
    Update, Poll, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    PollAnswerHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# ════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════
BOT_TOKEN     = os.environ.get("BOT_TOKEN", "")
ADMIN_ID      = int(os.environ.get("ADMIN_ID", "0"))
CHAT_ID       = os.environ.get("CHAT_ID", "")
GITHUB_TOKEN  = os.environ.get("GITHUB_TOKEN", "")
GROQ_KEY      = os.environ.get("GROQ_KEY", "")
TIMER         = int(os.environ.get("TIMER", "60"))

# GitHub repo details — apna update karo
GITHUB_USER   = "aianimation9199-ops"
GITHUB_REPO   = "sarkari-naukri-bot"
GITHUB_BRANCH = "main"

# Test settings
TOTAL_Q       = 100          # Questions per test
TEST_MINUTES  = 15           # Test duration
TEST_SECONDS  = TEST_MINUTES * 60

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ════════════════════════════════════════════
# GITHUB FILE STORAGE (repo-based, safe update)
# ════════════════════════════════════════════

def github_read(filename: str):
    """Read a JSON file from GitHub repo. Returns {} or [] on failure."""
    url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{filename}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        import base64
        content = base64.b64decode(r.json()["content"]).decode("utf-8")
        return json.loads(content)
    except Exception as e:
        logger.error(f"GitHub read error ({filename}): {e}")
        return {}

def github_write(filename: str, data, commit_msg: str = "Bot update"):
    """Write/update a JSON file in GitHub repo. Existing other files stay safe."""
    url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{filename}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    import base64

    # Get current SHA (needed for update)
    sha = None
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            sha = r.json().get("sha")
    except Exception:
        pass

    content_b64 = base64.b64encode(
        json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("utf-8")

    payload = {
        "message": commit_msg,
        "content": content_b64,
        "branch": GITHUB_BRANCH
    }
    if sha:
        payload["sha"] = sha

    try:
        r = requests.put(url, headers=headers, json=payload, timeout=15)
        r.raise_for_status()
        logger.info(f"GitHub updated: {filename}")
        return True
    except Exception as e:
        logger.error(f"GitHub write error ({filename}): {e}")
        return False

# File names in repo
QUESTIONS_FILE = "quiz_data.json"   # Already exists in your repo!
SCORES_FILE    = "scores.json"
SESSIONS_FILE  = "sessions.json"

# ════════════════════════════════════════════
# GROQ AI — Hindi+English question generator
# ════════════════════════════════════════════

def groq_generate_questions(subject: str, count: int = 5) -> list:
    """Use Groq AI to generate bilingual quiz questions."""
    if not GROQ_KEY:
        return []

    prompt = f"""Generate {count} multiple choice quiz questions about "{subject}" for Indian government job exams (SSC, Railway, UPSC).

STRICT FORMAT — return ONLY valid JSON array, nothing else:
[
  {{
    "question_hi": "हिंदी में प्रश्न?",
    "question_en": "Question in English?",
    "options": [
      "हिंदी option1 / English option1",
      "हिंदी option2 / English option2",
      "हिंदी option3 / English option3",
      "हिंदी option4 / English option4"
    ],
    "answer_index": 0,
    "subject": "{subject}",
    "explanation_hi": "संक्षिप्त व्याख्या",
    "explanation_en": "Brief explanation"
  }}
]

Rules:
- answer_index is 0-based (0=first option is correct)
- Questions must be factually correct
- Mix Hindi and English in options (format: हिंदी / English)
- Suitable for SSC CGL, Railway, UPSC level"""

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama3-8b-8192",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 3000
            },
            timeout=30
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        # Extract JSON array safely
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        logger.error(f"Groq error: {e}")
    return []

# ════════════════════════════════════════════
# IN-MEMORY TEST SESSIONS
# ════════════════════════════════════════════
# active_tests[chat_id] = {
#   questions, current, poll_map, user_data,
#   start_time, mode, timer_task
# }
active_tests = {}

# ════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════

def get_subjects(questions: list) -> list:
    return sorted(set(q.get("subject", "General") for q in questions))

def select_questions(questions: list, mode: str, count: int) -> list:
    pool = questions if mode == "mixed" else [
        q for q in questions if q.get("subject", "General") == mode
    ]
    count = min(count, len(pool))
    return random.sample(pool, count) if pool else []

def fmt_time(seconds: float) -> str:
    m, s = int(seconds) // 60, int(seconds) % 60
    return f"{m}m {s}s"

def build_question_text(q: dict, idx: int, total: int) -> str:
    """Build bilingual question text."""
    hi = q.get("question_hi") or q.get("question", "")
    en = q.get("question_en", "")
    num = f"Q{idx+1}/{total}"

    if hi and en:
        text = f"{num}: {hi}\n{en}"
    elif hi:
        text = f"{num}: {hi}"
    else:
        text = f"{num}: {en or q.get('question','?')}"

    return text[:300]  # Telegram poll limit

def build_options(q: dict) -> list:
    """Return options list, bilingual if available."""
    return q.get("options", ["A", "B", "C", "D"])[:10]

def leaderboard_text(scores: dict, top_n: int = 20) -> str:
    if not scores:
        return "📊 Abhi koi score nahi hai.\nPehle /test karke participate karo!"

    sorted_s = sorted(
        scores.items(),
        key=lambda x: (-x[1].get("total_score", 0), x[1].get("best_time", 99999))
    )[:top_n]

    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    lines = [
        "🏆 *LEADERBOARD — TOP 20* 🏆",
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    ]
    for i, (uid, d) in enumerate(sorted_s):
        medal = medals.get(i, f"`{i+1}.`")
        name  = d.get("name", "Unknown")
        score = d.get("total_score", 0)
        best  = fmt_time(d.get("best_time", 0))
        tests = d.get("tests_taken", 0)
        acc   = round(d.get("total_correct_pct", 0), 1)
        lines.append(
            f"{medal} *{name}*\n"
            f"   ✅ Score: `{score}` | ⏱ Best: `{best}`\n"
            f"   📝 Tests: `{tests}` | 🎯 Accuracy: `{acc}%`"
        )

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Mixed Test (सभी विषय)", callback_data="mode_mixed")],
        [InlineKeyboardButton("📚 Subject-wise Test",      callback_data="mode_subject")],
        [InlineKeyboardButton("🤖 AI से Questions बनाओ",  callback_data="ai_generate")],
        [InlineKeyboardButton("🏆 Leaderboard",            callback_data="leaderboard"),
         InlineKeyboardButton("📊 My Score",               callback_data="myscore")],
        [InlineKeyboardButton("➕ Questions Add करो",      callback_data="addq_help")],
    ])

# ════════════════════════════════════════════
# COMMANDS
# ════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎓 *Sarkari Naukri Academy Quiz Bot*\n\n"
        "📋 *Test Format:*\n"
        "• 100 Questions | ⏱ 15 Minutes\n"
        "• ✅ Sahi answer = +1 mark\n"
        "• ❌ Galat answer = wrong count\n"
        "• 🏆 Top 20 Leaderboard\n"
        "• 📖 Hindi + English dono mein\n\n"
        "Mode choose karo 👇",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    questions = github_read(QUESTIONS_FILE)
    if isinstance(questions, dict):
        # Handle old format {questions: [...]}
        questions = questions.get("questions", [])
    if not isinstance(questions, list):
        questions = []

    scores = github_read(SCORES_FILE)
    if not isinstance(scores, dict):
        scores = {}

    subjects = get_subjects(questions)
    subj_lines = "\n".join(
        f"  • {s}: {sum(1 for q in questions if q.get('subject','General')==s)} Qs"
        for s in subjects
    ) or "  None"

    await update.message.reply_text(
        f"📊 *Bot Status*\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"❓ Total Questions: `{len(questions)}`\n"
        f"👥 Registered Users: `{len(scores)}`\n"
        f"🔴 Active Tests: `{len(active_tests)}`\n"
        f"⏱ Poll Timer: `{TIMER}s`\n\n"
        f"*📚 Subjects:*\n{subj_lines}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"💾 Storage: GitHub Repo ✅",
        parse_mode="Markdown"
    )

async def cmd_leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    scores = github_read(SCORES_FILE)
    if not isinstance(scores, dict):
        scores = {}
    await update.message.reply_text(leaderboard_text(scores), parse_mode="Markdown")

async def cmd_stoptest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in active_tests:
        await end_test(ctx.application, chat_id, forced=True)
        await update.message.reply_text("⏹ Test rok diya gaya.")
    else:
        await update.message.reply_text("⚠️ Koi test chal nahi raha.")

async def cmd_addq(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Sirf admin use kar sakta hai.")
        return
    ctx.user_data["awaiting_questions"] = True
    await update.message.reply_text(
        "📝 *Questions Paste Karo — Format:*\n\n"
        "```\n"
        "SUBJECT: History\n"
        "QH: हिंदी में प्रश्न?\n"
        "QE: Question in English?\n"
        "A: Option 1 हिंदी / English\n"
        "B: Option 2 हिंदी / English\n"
        "C: Option 3 हिंदी / English\n"
        "D: Option 4 हिंदी / English\n"
        "ANS: B\n"
        "---\n"
        "```\n"
        "Multiple questions ke beech `---` lagao.\n"
        "⚠️ Existing questions DELETE NAHI HONGE.",
        parse_mode="Markdown"
    )

async def cmd_deleteall(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin only: delete all questions with confirmation."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Sirf admin.")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Haan, Delete Karo", callback_data="confirm_deleteall")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_delete")]
    ])
    await update.message.reply_text(
        "⚠️ *Kya aap SARE questions delete karna chahte ho?*\n"
        "Ye action undo nahi hoga!",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

# ════════════════════════════════════════════
# CALLBACK HANDLER
# ════════════════════════════════════════════

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data
    chat_id = query.message.chat_id
    user    = query.from_user

    # ── Leaderboard ──────────────────────────
    if data == "leaderboard":
        scores = github_read(SCORES_FILE)
        if not isinstance(scores, dict):
            scores = {}
        await query.message.reply_text(leaderboard_text(scores), parse_mode="Markdown")
        return

    # ── My Score ─────────────────────────────
    if data == "myscore":
        uid = str(user.id)
        scores = github_read(SCORES_FILE)
        if not isinstance(scores, dict):
            scores = {}
        if uid in scores:
            d = scores[uid]
            total_ans = d.get("total_correct", 0) + d.get("total_wrong", 0)
            acc = round(d["total_correct"] / total_ans * 100, 1) if total_ans else 0
            text = (
                f"📊 *Tumhara Score*\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"👤 {d.get('name','?')}\n"
                f"✅ Total Correct: `{d.get('total_correct',0)}`\n"
                f"❌ Total Wrong: `{d.get('total_wrong',0)}`\n"
                f"🎯 Accuracy: `{acc}%`\n"
                f"📝 Tests Liye: `{d.get('tests_taken',0)}`\n"
                f"⏱ Best Time: `{fmt_time(d.get('best_time',0))}`\n"
                f"🏆 Total Score: `{d.get('total_score',0)}`"
            )
        else:
            text = "Tumne abhi koi test nahi diya.\n/test se shuru karo!"
        await query.message.reply_text(text, parse_mode="Markdown")
        return

    # ── Mixed Test ───────────────────────────
    if data == "mode_mixed":
        await start_test(ctx, chat_id, mode="mixed", trigger_msg=query.message)
        return

    # ── Subject List ─────────────────────────
    if data == "mode_subject":
        questions = _load_questions()
        subjects  = get_subjects(questions)
        if not subjects:
            await query.message.reply_text("❌ Koi questions nahi. Pehle add karo.")
            return
        kb = [[InlineKeyboardButton(f"📌 {s}", callback_data=f"subject_{s}")] for s in subjects]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="back_main")])
        await query.message.reply_text(
            "📚 *Subject choose karo:*",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
        return

    # ── Subject chosen ───────────────────────
    if data.startswith("subject_"):
        subject = data[len("subject_"):]
        await start_test(ctx, chat_id, mode=subject, trigger_msg=query.message)
        return

    # ── AI Generate ──────────────────────────
    if data == "ai_generate":
        if user.id != ADMIN_ID:
            await query.message.reply_text("❌ Sirf admin AI generate kar sakta hai.")
            return
        ctx.user_data["awaiting_ai_subject"] = True
        await query.message.reply_text(
            "🤖 *AI Question Generator*\n\n"
            "Subject ka naam likho (Hindi ya English):\n"
            "Example: `History`, `Science`, `Geography`, `Polity`",
            parse_mode="Markdown"
        )
        return

    # ── Add Q Help ───────────────────────────
    if data == "addq_help":
        if user.id != ADMIN_ID:
            await query.message.reply_text("❌ Sirf admin.")
            return
        await cmd_addq(
            type("obj", (object,), {
                "message": query.message,
                "effective_user": user
            })(),
            ctx
        )
        return

    # ── Back to main ─────────────────────────
    if data == "back_main":
        await query.message.reply_text(
            "Mode choose karo 👇",
            reply_markup=main_keyboard()
        )
        return

    # ── Delete all confirm ───────────────────
    if data == "confirm_deleteall":
        if user.id != ADMIN_ID:
            return
        github_write(QUESTIONS_FILE, [], "Admin: Delete all questions")
        await query.message.reply_text("🗑 Saare questions delete ho gaye.")
        return

    if data == "cancel_delete":
        await query.message.reply_text("✅ Cancel. Koi bhi question delete nahi hua.")
        return

# ════════════════════════════════════════════
# MESSAGE HANDLER (Text)
# ════════════════════════════════════════════

async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()

    # ── Admin: AI subject input ──────────────
    if user.id == ADMIN_ID and ctx.user_data.get("awaiting_ai_subject"):
        ctx.user_data["awaiting_ai_subject"] = False
        subject = text
        await update.message.reply_text(f"🤖 AI se {subject} ke questions generate ho rahe hain...")

        qs = groq_generate_questions(subject, count=10)
        if not qs:
            await update.message.reply_text("❌ AI se questions nahi mile. GROQ_KEY check karo.")
            return

        questions = _load_questions()
        questions.extend(qs)
        ok = github_write(QUESTIONS_FILE, questions, f"AI generated: {subject} questions")
        if ok:
            await update.message.reply_text(
                f"✅ {len(qs)} AI questions add ho gaye!\n"
                f"📊 Total: {len(questions)} questions"
            )
        else:
            await update.message.reply_text("❌ GitHub save nahi hua. Token check karo.")
        return

    # ── Admin: Manual questions paste ────────
    if user.id == ADMIN_ID and ctx.user_data.get("awaiting_questions"):
        ctx.user_data["awaiting_questions"] = False
        parsed = parse_questions_text(text)
        if not parsed:
            await update.message.reply_text(
                "❌ Format galat hai.\n/addq command se dobara dekho."
            )
            return

        questions = _load_questions()
        questions.extend(parsed)
        ok = github_write(QUESTIONS_FILE, questions, f"Added {len(parsed)} questions manually")
        if ok:
            await update.message.reply_text(
                f"✅ {len(parsed)} questions add ho gaye!\n"
                f"📊 Total: {len(questions)} questions\n"
                f"💾 GitHub mein safe ✅"
            )
        else:
            await update.message.reply_text("❌ GitHub save nahi hua.")
        return

    # Default
    await update.message.reply_text(
        "Menu ke liye /start dabao 👇",
        reply_markup=main_keyboard()
    )

# ════════════════════════════════════════════
# LOAD QUESTIONS (handles both formats)
# ════════════════════════════════════════════

def _load_questions() -> list:
    """Load questions safely, handling dict or list format."""
    data = github_read(QUESTIONS_FILE)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Old format: {questions: [...]} or direct dict
        return data.get("questions", [])
    return []

# ════════════════════════════════════════════
# TEST FLOW
# ════════════════════════════════════════════

async def start_test(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, mode: str, trigger_msg=None):
    if chat_id in active_tests:
        await ctx.bot.send_message(
            chat_id,
            "⚠️ Ek test pehle se chal raha hai.\n/stoptest se band karo pehle."
        )
        return

    questions_all = _load_questions()
    if not questions_all:
        await ctx.bot.send_message(chat_id, "❌ Koi questions nahi. Admin se contact karo.")
        return

    selected = select_questions(questions_all, mode, TOTAL_Q)
    if not selected:
        await ctx.bot.send_message(
            chat_id,
            f"❌ '{mode}' mein koi questions nahi hain.\n"
            f"Pehle questions add karo."
        )
        return

    active_tests[chat_id] = {
        "questions":  selected,
        "current":    0,
        "poll_map":   {},    # poll_id -> q_index
        "user_data":  {},    # user_id -> stats
        "start_time": time.time(),
        "mode":       mode,
        "timer_task": None,
        "sending":    False,
    }

    mode_label = "🔀 Mixed (सभी विषय)" if mode == "mixed" else f"📌 {mode}"
    await ctx.bot.send_message(
        chat_id,
        f"🚀 *TEST SHURU HO GAYA!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 Mode: {mode_label}\n"
        f"❓ Questions: {len(selected)}\n"
        f"⏱ Time: {TEST_MINUTES} Minutes\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Sahi = +1 | ❌ Galat = Wrong count\n"
        f"🔚 Test band karne ke liye: /stoptest\n\n"
        f"*All the best! 🎯*",
        parse_mode="Markdown"
    )

    # Start auto-end timer
    task = asyncio.create_task(test_auto_end(ctx.application, chat_id))
    active_tests[chat_id]["timer_task"] = task

    # Start sending polls
    asyncio.create_task(send_polls_loop(ctx.application, chat_id))


async def test_auto_end(app, chat_id: int):
    """Auto end test after TEST_SECONDS."""
    await asyncio.sleep(TEST_SECONDS)
    if chat_id in active_tests:
        await app.bot.send_message(
            chat_id,
            f"⏰ *{TEST_MINUTES} minutes khatam!*\nTest band ho raha hai...",
            parse_mode="Markdown"
        )
        await end_test(app, chat_id, forced=True)


async def send_polls_loop(app, chat_id: int):
    """Send all quiz polls one by one with TIMER interval."""
    if chat_id not in active_tests:
        return

    session = active_tests[chat_id]
    questions = session["questions"]

    for idx in range(len(questions)):
        if chat_id not in active_tests:
            break  # Test was stopped

        session = active_tests[chat_id]
        session["current"] = idx
        q = questions[idx]

        q_text   = build_question_text(q, idx, len(questions))
        options  = build_options(q)
        ans_idx  = int(q.get("answer_index", 0))

        # Clamp answer_index to valid range
        ans_idx = max(0, min(ans_idx, len(options) - 1))

        try:
            msg = await app.bot.send_poll(
                chat_id=chat_id,
                question=q_text,
                options=options,
                type=Poll.QUIZ,
                correct_option_id=ans_idx,   # ✅ SIRF SAHI OPTION PAR TICK
                is_anonymous=False,
                open_period=min(TIMER, 600),
            )
            poll_id = str(msg.poll.id)
            session["poll_map"][poll_id] = idx
        except Exception as e:
            logger.error(f"Poll send error (Q{idx+1}): {e}")

        # Wait before next poll
        await asyncio.sleep(TIMER)

    # All polls sent
    if chat_id in active_tests:
        await app.bot.send_message(
            chat_id,
            "✅ Saare questions bhej diye gaye!\nThodi der mein result aayega...",
        )
        await asyncio.sleep(5)
        await end_test(app, chat_id)

# ════════════════════════════════════════════
# POLL ANSWER HANDLER
# ════════════════════════════════════════════

async def poll_answer_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ans     = update.poll_answer
    poll_id = str(ans.poll_id)
    user    = ans.user
    uid     = str(user.id)
    name    = user.full_name

    for chat_id, session in list(active_tests.items()):
        if poll_id not in session["poll_map"]:
            continue

        q_idx   = session["poll_map"][poll_id]
        question = session["questions"][q_idx]
        correct  = int(question.get("answer_index", 0))

        # Init user
        if uid not in session["user_data"]:
            session["user_data"][uid] = {
                "name":       name,
                "correct":    0,
                "wrong":      0,
                "start_time": session["start_time"],
                "last_time":  time.time(),
            }

        ud = session["user_data"][uid]
        ud["name"]      = name
        ud["last_time"] = time.time()

        if ans.option_ids and ans.option_ids[0] == correct:
            ud["correct"] += 1
        else:
            ud["wrong"] += 1
        break

# ════════════════════════════════════════════
# END TEST
# ════════════════════════════════════════════

async def end_test(app, chat_id: int, forced: bool = False):
    if chat_id not in active_tests:
        return

    session = active_tests.pop(chat_id)

    # Cancel timer task if not forced
    if not forced and session.get("timer_task"):
        session["timer_task"].cancel()

    user_data = session["user_data"]
    if not user_data:
        await app.bot.send_message(
            chat_id,
            "📊 Kisi ne participate nahi kiya."
        )
        return

    # Sort: most correct first, then least time
    results = sorted(
        user_data.items(),
        key=lambda x: (
            -x[1]["correct"],
            x[1]["last_time"] - x[1]["start_time"]
        )
    )

    # Build result message
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    lines  = [
        "🏁 *TEST RESULT* 🏁",
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    ]
    for i, (uid, d) in enumerate(results[:20]):
        medal   = medals.get(i, f"`{i+1}.`")
        elapsed = d["last_time"] - d["start_time"]
        total   = d["correct"] + d["wrong"]
        acc     = round(d["correct"] / total * 100, 1) if total else 0
        lines.append(
            f"{medal} *{d['name']}*\n"
            f"   ✅ Sahi: `{d['correct']}` | ❌ Galat: `{d['wrong']}`\n"
            f"   ⏱ Time: `{fmt_time(elapsed)}` | 🎯 Accuracy: `{acc}%`"
        )

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("🏆 Leaderboard ke liye /leaderboard")

    await app.bot.send_message(
        chat_id,
        "\n".join(lines),
        parse_mode="Markdown"
    )

    # ── Save scores to GitHub (SAFE — no overwrite of other files) ──
    scores = github_read(SCORES_FILE)
    if not isinstance(scores, dict):
        scores = {}

    for uid, d in user_data.items():
        elapsed = d["last_time"] - d["start_time"]
        total   = d["correct"] + d["wrong"]
        acc_pct = round(d["correct"] / total * 100, 1) if total else 0

        if uid not in scores:
            scores[uid] = {
                "name":              d["name"],
                "total_score":       0,
                "total_correct":     0,
                "total_wrong":       0,
                "tests_taken":       0,
                "best_time":         99999,
                "total_correct_pct": 0.0,
            }

        scores[uid]["name"]          = d["name"]
        scores[uid]["total_score"]   += d["correct"]
        scores[uid]["total_correct"] += d["correct"]
        scores[uid]["total_wrong"]   += d["wrong"]
        scores[uid]["tests_taken"]   += 1
        scores[uid]["total_correct_pct"] = round(
            scores[uid]["total_correct"] /
            (scores[uid]["total_correct"] + scores[uid]["total_wrong"]) * 100, 1
        )
        if elapsed < scores[uid]["best_time"]:
            scores[uid]["best_time"] = elapsed

    ok = github_write(SCORES_FILE, scores, "Test result saved")
    if ok:
        await app.bot.send_message(chat_id, "💾 Scores GitHub mein save ho gaye! ✅")

# ════════════════════════════════════════════
# PARSE QUESTIONS FROM TEXT
# ════════════════════════════════════════════

def parse_questions_text(text: str) -> list:
    """
    Parse bilingual questions from text.
    Supports both QH:/QE: (bilingual) and Q: (single language).
    """
    blocks  = text.strip().split("---")
    parsed  = []
    ans_map = {"A": 0, "B": 1, "C": 2, "D": 3}

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        d       = {"subject": "General", "options": []}
        options = []

        for line in block.split("\n"):
            line = line.strip()
            if not line:
                continue
            low = line.upper()

            if low.startswith("SUBJECT:"):
                d["subject"] = line.split(":", 1)[1].strip()
            elif low.startswith("QH:"):
                d["question_hi"] = line.split(":", 1)[1].strip()
            elif low.startswith("QE:"):
                d["question_en"] = line.split(":", 1)[1].strip()
            elif low.startswith("Q:"):
                # Single Q — store as both
                q = line.split(":", 1)[1].strip()
                d["question_hi"] = q
                d["question_en"] = q
            elif low.startswith("A:"):
                options.append(line.split(":", 1)[1].strip())
            elif low.startswith("B:"):
                options.append(line.split(":", 1)[1].strip())
            elif low.startswith("C:"):
                options.append(line.split(":", 1)[1].strip())
            elif low.startswith("D:"):
                options.append(line.split(":", 1)[1].strip())
            elif low.startswith("ANS:"):
                ans = line.split(":", 1)[1].strip().upper()
                d["answer_index"] = ans_map.get(ans, 0)

        if ("question_hi" in d or "question_en" in d) and len(options) >= 2 and "answer_index" in d:
            d["options"]  = options
            d["question"] = d.get("question_hi") or d.get("question_en", "")
            parsed.append(d)

    return parsed

# ════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("test",        cmd_start))
    app.add_handler(CommandHandler("status",      cmd_status))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("stoptest",    cmd_stoptest))
    app.add_handler(CommandHandler("addq",        cmd_addq))
    app.add_handler(CommandHandler("deleteall",   cmd_deleteall))

    # Handlers
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(PollAnswerHandler(poll_answer_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("✅ Sarkari Naukri Academy Bot chal raha hai...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
