"""
SARKARI NAUKRI ACADEMY — QUIZ BOT v5.0
Features:
- Polls Start / Stop buttons
- PDF Upload → questions auto extract
- Text Paste → questions add
- Auto scheduled quiz (TIMER interval, no manual action)
- Hindi + English bilingual
- Top-20 Leaderboard
- GitHub safe storage (no delete)
Railway Variables: BOT_TOKEN, ADMIN_ID, CHAT_ID,
                   GITHUB_TOKEN, GIST_ID, GROQ_KEY, TIMER
"""

import os, json, time, asyncio, logging, random, re, base64, io
import requests

from telegram import Update, Poll, InlineKeyboardButton, InlineKeyboardMarkup, Document
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
CHAT_ID      = os.environ.get("CHAT_ID", "")        # group/channel for auto quiz
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GIST_ID      = os.environ.get("GIST_ID", "")
GROQ_KEY     = os.environ.get("GROQ_KEY", "")
TIMER        = int(os.environ.get("TIMER", "30"))    # seconds between polls

GH_USER      = "aianimation9199-ops"
GH_REPO      = "sarkari-naukri-bot"
GH_BRANCH    = "main"

TOTAL_Q      = 100
TEST_MIN     = 15
TEST_SEC     = TEST_MIN * 60

Q_FILE       = "quiz_data.json"
S_FILE       = "scores.json"
CFG_FILE     = "bot_config.json"   # stores auto-schedule config

# ── GitHub helpers ───────────────────────────────────
GH_HDR = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

def gh_read(fname):
    try:
        r = requests.get(
            f"https://api.github.com/repos/{GH_USER}/{GH_REPO}/contents/{fname}",
            headers=GH_HDR, timeout=15)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        return json.loads(base64.b64decode(r.json()["content"]).decode())
    except Exception as e:
        log.error("gh_read %s: %s", fname, e)
        return []

def gh_write(fname, data, msg="bot update"):
    """Safe write — only updates this one file, all others untouched."""
    url = f"https://api.github.com/repos/{GH_USER}/{GH_REPO}/contents/{fname}"
    sha = None
    try:
        r = requests.get(url, headers=GH_HDR, timeout=10)
        if r.status_code == 200:
            sha = r.json().get("sha")
    except Exception:
        pass
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
        r = requests.put(url, headers=GH_HDR, json=payload, timeout=20)
        r.raise_for_status()
        return True
    except Exception as e:
        log.error("gh_write %s: %s", fname, e)
        return False

def gist_bak(data):
    if not GIST_ID: return
    try:
        requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=GH_HDR,
            json={"files": {"scores.json": {
                "content": json.dumps(data, ensure_ascii=False, indent=2)
            }}}, timeout=10)
    except Exception:
        pass

# ── Data helpers ─────────────────────────────────────
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
    return {"auto_running": False, "auto_chat_id": CHAT_ID, "current_index": 0}

def save_cfg(cfg):
    gh_write(CFG_FILE, cfg, "config update")

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
    if not scores: return "📊 Koi score nahi hai abhi.\n/test se shuru karo!"
    ranked = sorted(scores.items(),
        key=lambda x: (-x[1].get("total_score",0), x[1].get("best_time",99999)))[:top]
    medals = {0:"🥇",1:"🥈",2:"🥉"}
    lines = ["🏆 *TOP LEADERBOARD* 🏆","━━━━━━━━━━━━━━━━━━━━━━\n"]
    for i,(uid,d) in enumerate(ranked):
        c=d.get("total_correct",0); w=d.get("total_wrong",0)
        acc = round(c/(c+w)*100,1) if c+w else 0
        lines.append(
            f"{medals.get(i,str(i+1)+'.')} *{d.get('name','?')}*\n"
            f"   ✅`{c}` ❌`{w}` ⏱`{ft(d.get('best_time',0))}` 🎯`{acc}%`\n"
            f"   📝Tests:`{d.get('tests_taken',0)}`")
    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

# ── Keyboards ─────────────────────────────────────────
def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Mixed Test (सभी विषय)", callback_data="mode_mixed")],
        [InlineKeyboardButton("📚 Subject-wise Test",      callback_data="mode_subj")],
        [InlineKeyboardButton("▶️ Polls Start",  callback_data="polls_start"),
         InlineKeyboardButton("⏹ Polls Stop",   callback_data="polls_stop")],
        [InlineKeyboardButton("📄 PDF Upload करो",        callback_data="pdf_help"),
         InlineKeyboardButton("📋 Text Paste करो",        callback_data="text_help")],
        [InlineKeyboardButton("🤖 AI Questions बनाओ",     callback_data="ai_gen")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="lb"),
         InlineKeyboardButton("📊 My Score",    callback_data="me")],
        [InlineKeyboardButton("📈 Status",      callback_data="stat"),
         InlineKeyboardButton("🗑 Sab Delete",  callback_data="ask_del")],
    ])

def admin_kb():
    """Extra admin buttons shown to admin."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Auto Quiz START", callback_data="auto_start"),
         InlineKeyboardButton("⏹ Auto Quiz STOP",  callback_data="auto_stop")],
        [InlineKeyboardButton("📄 PDF Upload",      callback_data="pdf_help"),
         InlineKeyboardButton("📋 Text Paste",      callback_data="text_help")],
        [InlineKeyboardButton("🔙 Main Menu",       callback_data="back")],
    ])

# ── Active sessions ───────────────────────────────────
sess = {}          # chat_id -> test session
auto_task = None   # background auto-quiz task

# ══════════════════════════════════════════════════════
# PDF TEXT EXTRACTION (without pypdf — pure requests)
# ══════════════════════════════════════════════════════
def extract_pdf_text(pdf_bytes: bytes) -> str:
    """
    Simple PDF text extractor using string scanning.
    Works for text-based PDFs without external libraries.
    """
    try:
        text = pdf_bytes.decode("latin-1", errors="ignore")
        # Extract text between BT...ET blocks (PDF text objects)
        chunks = re.findall(r'\((.*?)\)', text)
        result = " ".join(chunks)
        # Clean up
        result = re.sub(r'\\[nrt]', ' ', result)
        result = re.sub(r'\s+', ' ', result)
        return result[:50000]  # limit
    except Exception as e:
        log.error("PDF extract: %s", e)
        return ""

def parse_pdf_to_questions(text: str) -> list:
    """
    Try to parse questions from extracted PDF text.
    Handles common MCQ formats found in PDFs.
    """
    questions = []
    # Try to split on question numbers like "1.", "Q1", "Q.1"
    blocks = re.split(r'(?:^|\s)(?:Q\.?\s*)?(\d+)[.)]\s+', text, flags=re.MULTILINE)

    for block in blocks:
        block = block.strip()
        if len(block) < 20: continue
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if not lines: continue

        q_text = lines[0]
        opts = []
        ans_idx = 0

        for line in lines[1:]:
            m = re.match(r'^[\(\[]?([A-Da-d])[\)\]\.]\s*(.+)', line)
            if m:
                opts.append(m.group(2).strip()[:100])
            # Look for answer hint
            a = re.search(r'(?:ans(?:wer)?|correct)[:\s]*([A-Da-d])', line, re.I)
            if a:
                ans_idx = ord(a.group(1).upper()) - ord('A')

        if q_text and len(opts) >= 2:
            questions.append({
                "question": q_text[:300],
                "question_hi": q_text[:300],
                "question_en": q_text[:300],
                "options": opts[:4],
                "answer_index": max(0, min(ans_idx, len(opts)-1)),
                "subject": "General",
            })

    return questions[:200]  # max 200 from one PDF

# ══════════════════════════════════════════════════════
# GROQ AI
# ══════════════════════════════════════════════════════
def groq_gen(subject, count=10):
    if not GROQ_KEY: return []
    prompt = (
        f'Generate {count} MCQ for "{subject}" Indian Govt exams (SSC/Railway/UPSC).\n'
        'Return ONLY JSON array, no extra text:\n'
        '[{"question_hi":"हिंदी?","question_en":"English?",'
        '"options":["A हिंदी/English","B हिंदी/English","C हिंदी/English","D हिंदी/English"],'
        f'"answer_index":0,"subject":"{subject}"}}]'
    )
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={"model": "llama3-8b-8192",
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.5, "max_tokens": 4000},
            timeout=30)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if m: return json.loads(m.group())
    except Exception as e:
        log.error("groq: %s", e)
    return []

# ══════════════════════════════════════════════════════
# COMMANDS
# ══════════════════════════════════════════════════════
async def c_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        "🎓 *Sarkari Naukri Academy Quiz Bot*\n\n"
        "• 100 Questions | ⏱ 15 Minutes\n"
        "• ✅ Sahi option par ✅ | ❌ Galat par ❌\n"
        "• 📖 Hindi + English bilingual\n"
        "• 🏆 Top-20 Leaderboard\n"
        "• 🤖 AI se auto questions\n\n"
        "👇 Mode choose karo:",
        reply_markup=main_kb(), parse_mode="Markdown")

async def c_status(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    qs = load_qs(); sc = load_sc(); sub = subjects(qs)
    cfg = load_cfg()
    si = "\n".join(
        f"  • {s}: {sum(1 for q in qs if q.get('subject','General')==s)}"
        for s in sub) or "  None"
    auto = "✅ Running" if cfg.get("auto_running") else "❌ Stopped"
    await u.message.reply_text(
        f"📊 *Bot Status*\n━━━━━━━━━━━━━━━\n"
        f"❓`{len(qs)}` Questions | 👥`{len(sc)}` Users\n"
        f"🔴 Active Tests:`{len(sess)}` | ⏱ Timer:`{TIMER}s`\n"
        f"🤖 Auto Quiz: {auto}\n\n"
        f"*Subjects:*\n{si}\n━━━━━━━━━━━━━━━",
        parse_mode="Markdown")

async def c_lb(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(lb_msg(load_sc()), parse_mode="Markdown")

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
        "📝 *Text Paste Karo — Format:*\n\n"
        "```\nSUBJECT: History\n"
        "QH: हिंदी प्रश्न?\nQE: English question?\n"
        "A: Option A\nB: Option B\nC: Option C\nD: Option D\nANS: B\n---\n```\n"
        "Multiple questions ke beech `---` lagao.",
        parse_mode="Markdown")

async def c_myid(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        f"👤 ID:`{u.effective_user.id}`\nName: {u.effective_user.full_name}",
        parse_mode="Markdown")

async def c_delall(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_user.id != ADMIN_ID:
        await u.message.reply_text("❌ Sirf admin."); return
    await u.message.reply_text(
        "⚠️ *Saare questions delete karne hain?*",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Haan Delete", callback_data="yes_del"),
             InlineKeyboardButton("❌ Cancel",       callback_data="no_del")]
        ]), parse_mode="Markdown")

# ══════════════════════════════════════════════════════
# CALLBACK HANDLER
# ══════════════════════════════════════════════════════
async def on_cb(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    await q.answer()
    d = q.data; cid = q.message.chat_id; user = q.from_user

    # ── Leaderboard ──────────────────────────────────
    if d == "lb":
        await q.message.reply_text(lb_msg(load_sc()), parse_mode="Markdown")

    # ── My Score ─────────────────────────────────────
    elif d == "me":
        uid = str(user.id); sc = load_sc()
        if uid in sc:
            x=sc[uid]; c=x.get("total_correct",0); w=x.get("total_wrong",0)
            acc = round(c/(c+w)*100,1) if c+w else 0
            await q.message.reply_text(
                f"📊 *Tumhara Score*\n━━━━━━━━━━━━━━\n"
                f"👤 {x.get('name','?')}\n✅ Sahi:`{c}` ❌ Galat:`{w}`\n"
                f"🎯 Accuracy:`{acc}%` 📝 Tests:`{x.get('tests_taken',0)}`\n"
                f"⏱ Best:`{ft(x.get('best_time',0))}` 🏆 Score:`{x.get('total_score',0)}`",
                parse_mode="Markdown")
        else:
            await q.message.reply_text("Tumne abhi koi test nahi diya!")

    # ── Status ───────────────────────────────────────
    elif d == "stat":
        qs=load_qs(); sc=load_sc(); sub=subjects(qs)
        cfg=load_cfg()
        si = "\n".join(f"  • {s}: {sum(1 for q2 in qs if q2.get('subject','General')==s)}" for s in sub) or "  None"
        auto = "✅ Running" if cfg.get("auto_running") else "❌ Stopped"
        await q.message.reply_text(
            f"📊 `{len(qs)}` Qs | 👥`{len(sc)}` Users\n"
            f"🔴 Tests:`{len(sess)}` | 🤖 Auto:{auto}\n\n*Subjects:*\n{si}",
            parse_mode="Markdown")

    # ── Mixed Test ───────────────────────────────────
    elif d == "mode_mixed":
        await begin(ctx, cid, "mixed")

    # ── Subject List ─────────────────────────────────
    elif d == "mode_subj":
        qs=load_qs(); sub=subjects(qs)
        if not sub:
            await q.message.reply_text("❌ Koi questions nahi."); return
        kb = [[InlineKeyboardButton(f"📌 {s}", callback_data=f"s_{s}")] for s in sub]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="back")])
        await q.message.reply_text("📚 *Subject choose karo:*",
            reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("s_"):
        await begin(ctx, cid, d[2:])

    # ── Polls Start ──────────────────────────────────
    elif d == "polls_start":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin polls start kar sakta hai."); return
        await begin(ctx, cid, "mixed")

    # ── Polls Stop ───────────────────────────────────
    elif d == "polls_stop":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        if cid in sess:
            await end_test(ctx.application, cid, forced=True)
            await q.message.reply_text("⏹ Polls band kar diye gaye.")
        else:
            await q.message.reply_text("Koi poll nahi chal raha.")

    # ── Auto Quiz Start ──────────────────────────────
    elif d == "auto_start":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        cfg = load_cfg()
        cfg["auto_running"] = True
        cfg["auto_chat_id"] = str(cid)
        cfg["current_index"] = 0
        save_cfg(cfg)
        asyncio.create_task(run_auto_quiz(ctx.application, str(cid)))
        await q.message.reply_text(
            "🤖 *Auto Quiz shuru ho gaya!*\n"
            f"Har `{TIMER}` seconds mein ek question aayega automatically.\n"
            "Band karne ke liye: Auto Quiz STOP button dabao.",
            parse_mode="Markdown")

    # ── Auto Quiz Stop ───────────────────────────────
    elif d == "auto_stop":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        cfg = load_cfg()
        cfg["auto_running"] = False
        save_cfg(cfg)
        await q.message.reply_text("⏹ Auto Quiz band kar diya gaya.")

    # ── PDF Help ─────────────────────────────────────
    elif d == "pdf_help":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        ctx.user_data["pdf_mode"] = True
        await q.message.reply_text(
            "📄 *PDF Upload Karo*\n\n"
            "Apna questions PDF seedha yahan bhejo.\n"
            "Bot automatically questions extract kar lega!\n\n"
            "⚠️ PDF mein questions is format mein hone chahiye:\n"
            "```\n1. Question text?\n(A) Option A\n(B) Option B\n"
            "(C) Option C\n(D) Option D\n```\n"
            "Ab PDF bhejo 👇",
            parse_mode="Markdown")

    # ── Text Paste Help ──────────────────────────────
    elif d == "text_help":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        ctx.user_data["aq"] = True
        await q.message.reply_text(
            "📋 *Text Paste Karo — Format:*\n\n"
            "```\nSUBJECT: History\n"
            "QH: हिंदी प्रश्न?\nQE: English question?\n"
            "A: Option A\nB: Option B\nC: Option C\nD: Option D\nANS: B\n---\n```\n"
            "Multiple questions ke beech `---` lagao.\n"
            "💾 Purane questions delete NAHI honge.\n\nAb text paste karo 👇",
            parse_mode="Markdown")

    # ── AI Generate ──────────────────────────────────
    elif d == "ai_gen":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin AI use kar sakta hai."); return
        ctx.user_data["ai"] = True
        await q.message.reply_text(
            "🤖 Subject ka naam likho:\n_Example: History, Science, Geography, Polity_",
            parse_mode="Markdown")

    # ── Delete confirm ───────────────────────────────
    elif d == "ask_del":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        await q.message.reply_text(
            "⚠️ *Saare questions delete karne hain?*",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Haan Delete", callback_data="yes_del"),
                 InlineKeyboardButton("❌ Cancel",       callback_data="no_del")]
            ]), parse_mode="Markdown")

    elif d == "yes_del":
        if user.id != ADMIN_ID: return
        gh_write(Q_FILE, [], "Admin: delete all questions")
        await q.message.reply_text("🗑 Saare questions delete ho gaye.")

    elif d == "no_del":
        await q.message.reply_text("✅ Cancel. Kuch delete nahi hua.")

    # ── Back ─────────────────────────────────────────
    elif d == "back":
        await q.message.reply_text("👇 Mode:", reply_markup=main_kb())

# ══════════════════════════════════════════════════════
# MESSAGE HANDLER — Text + PDF
# ══════════════════════════════════════════════════════
async def on_msg(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = u.effective_user; text = (u.message.text or "").strip()

    # ── AI subject input ─────────────────────────────
    if user.id == ADMIN_ID and ctx.user_data.get("ai"):
        ctx.user_data.pop("ai")
        await u.message.reply_text(f"🤖 AI se *{text}* questions bana raha hoon...", parse_mode="Markdown")
        new_qs = groq_gen(text, 10)
        if not new_qs:
            await u.message.reply_text("❌ AI se questions nahi aaye. GROQ_KEY check karo."); return
        all_qs = load_qs(); all_qs.extend(new_qs)
        if gh_write(Q_FILE, all_qs, f"AI: {len(new_qs)} {text}"):
            await u.message.reply_text(f"✅ {len(new_qs)} AI questions add!\nTotal: {len(all_qs)} 💾✅")
        else:
            await u.message.reply_text("❌ GitHub save fail.")
        return

    # ── Manual text paste ────────────────────────────
    if user.id == ADMIN_ID and ctx.user_data.get("aq"):
        ctx.user_data.pop("aq")
        parsed = parse_qs(text)
        if not parsed:
            await u.message.reply_text("❌ Format galat. /addq se format dekho."); return
        all_qs = load_qs(); all_qs.extend(parsed)
        if gh_write(Q_FILE, all_qs, f"Manual: {len(parsed)} questions"):
            await u.message.reply_text(
                f"✅ {len(parsed)} questions add!\nTotal: {len(all_qs)}\n💾 GitHub safe ✅")
        else:
            await u.message.reply_text("❌ Save fail.")
        return

    # Default
    await u.message.reply_text("👇 Menu:", reply_markup=main_kb())


# ── PDF upload handler ────────────────────────────────
async def on_document(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = u.effective_user
    if user.id != ADMIN_ID:
        await u.message.reply_text("❌ Sirf admin PDF upload kar sakta hai."); return

    doc = u.message.document
    if not doc or not doc.file_name:
        return

    fname = doc.file_name.lower()
    if not fname.endswith(".pdf") and not fname.endswith(".txt"):
        await u.message.reply_text("⚠️ Sirf PDF ya TXT file bhejo."); return

    await u.message.reply_text(f"📄 *{doc.file_name}* process ho raha hai...", parse_mode="Markdown")

    try:
        # Download file
        tg_file = await ctx.bot.get_file(doc.file_id)
        file_bytes = await tg_file.download_as_bytearray()

        if fname.endswith(".txt"):
            text = bytes(file_bytes).decode("utf-8", errors="ignore")
            # Try structured parse first
            parsed = parse_qs(text)
            if not parsed:
                parsed = parse_pdf_to_questions(text)
        else:
            # PDF
            text = extract_pdf_text(bytes(file_bytes))
            parsed = parse_pdf_to_questions(text)
            # Also try structured format in case PDF has it
            structured = parse_qs(text)
            if structured:
                parsed = structured

        if not parsed:
            await u.message.reply_text(
                "❌ PDF se questions extract nahi ho sake.\n\n"
                "📋 *Text Paste* button use karo aur manually paste karo:\n"
                "Format: SUBJECT/QH/QE/A/B/C/D/ANS"); return

        # Ask subject for extracted questions
        for q2 in parsed:
            if q2.get("subject") == "General":
                q2["subject"] = "General"   # can be improved

        all_qs = load_qs(); all_qs.extend(parsed)
        if gh_write(Q_FILE, all_qs, f"PDF: {len(parsed)} questions from {doc.file_name}"):
            await u.message.reply_text(
                f"✅ PDF se *{len(parsed)}* questions add ho gaye!\n"
                f"📊 Total: {len(all_qs)} questions\n"
                f"💾 GitHub mein safe ✅",
                parse_mode="Markdown")
        else:
            await u.message.reply_text("❌ GitHub save fail. Token check karo.")

    except Exception as e:
        log.error("PDF handler: %s", e)
        await u.message.reply_text(f"❌ Error: {str(e)[:100]}\nManually text paste karo.")

# ══════════════════════════════════════════════════════
# AUTO QUIZ (runs continuously, sends one Q every TIMER sec)
# ══════════════════════════════════════════════════════
async def run_auto_quiz(app, chat_id: str):
    """
    Sends individual quiz questions automatically.
    No manual action needed — just runs in background.
    Saves position to GitHub so it resumes after restart.
    """
    global auto_task
    log.info("Auto quiz started for chat %s", chat_id)

    while True:
        try:
            cfg = load_cfg()
            if not cfg.get("auto_running"):
                log.info("Auto quiz stopped.")
                break

            qs = load_qs()
            if not qs:
                await asyncio.sleep(60)
                continue

            idx = int(cfg.get("current_index", 0)) % len(qs)
            q = qs[idx]

            text = qtxt(q, idx, len(qs))
            opts = qopts(q)
            ans  = max(0, min(int(q.get("answer_index", 0)), len(opts)-1))

            try:
                await app.bot.send_poll(
                    chat_id=chat_id,
                    question=text,
                    options=opts,
                    type=Poll.QUIZ,
                    correct_option_id=ans,   # ✅ sirf sahi par tick
                    is_anonymous=False,
                    open_period=min(max(TIMER, 5), 600),
                )
            except Exception as e:
                log.error("Auto poll send: %s", e)

            # Update index
            cfg["current_index"] = (idx + 1) % len(qs)
            save_cfg(cfg)

        except Exception as e:
            log.error("Auto quiz loop: %s", e)

        await asyncio.sleep(TIMER)

# ══════════════════════════════════════════════════════
# MANUAL TEST FLOW (100 Q, 15 min)
# ══════════════════════════════════════════════════════
async def begin(ctx, cid, mode):
    if cid in sess:
        await ctx.bot.send_message(cid, "⚠️ Test chal raha hai. /stoptest se band karo."); return
    all_qs = load_qs()
    selected = pick(all_qs, mode, TOTAL_Q)
    if not selected:
        await ctx.bot.send_message(cid, "❌ Questions nahi hain.\n📋 Text Paste ya 📄 PDF Upload button use karo."); return

    sess[cid] = {
        "questions": selected, "poll_map": {},
        "user_data": {}, "start_time": time.time(),
        "mode": mode, "timer_task": None,
    }
    label = "🔀 Mixed (सभी विषय)" if mode == "mixed" else f"📌 {mode}"
    await ctx.bot.send_message(cid,
        f"🚀 *TEST SHURU!*\n━━━━━━━━━━━━━━━━━\n"
        f"📋 {label}\n❓ {len(selected)} Questions\n⏱ {TEST_MIN} Minutes\n"
        f"━━━━━━━━━━━━━━━━━\n✅ Sahi = +1 | ❌ Galat = counted\n"
        f"/stoptest se band karo\n\n*All the best! 🎯*",
        parse_mode="Markdown")

    task = asyncio.create_task(auto_end(ctx.application, cid))
    sess[cid]["timer_task"] = task
    asyncio.create_task(send_polls(ctx.application, cid))

async def auto_end(app, cid):
    await asyncio.sleep(TEST_SEC)
    if cid in sess:
        await app.bot.send_message(cid,
            f"⏰ *{TEST_MIN} min khatam!* Result aa raha hai...", parse_mode="Markdown")
        await end_test(app, cid, forced=True)

async def send_polls(app, cid):
    if cid not in sess: return
    s = sess[cid]; total = len(s["questions"])
    for i, q in enumerate(s["questions"]):
        if cid not in sess: return
        text = qtxt(q, i, total)
        opts = qopts(q)
        ans  = max(0, min(int(q.get("answer_index",0)), len(opts)-1))
        try:
            msg = await app.bot.send_poll(
                chat_id=cid, question=text, options=opts,
                type=Poll.QUIZ,
                correct_option_id=ans,   # ✅ sirf sahi par tick
                is_anonymous=False,
                open_period=min(max(TIMER,5), 600),
            )
            sess[cid]["poll_map"][str(msg.poll.id)] = i
        except Exception as e:
            log.error("Poll Q%d: %s", i+1, e)
        await asyncio.sleep(TIMER)
    if cid in sess:
        await app.bot.send_message(cid, "✅ Saare questions ho gaye! Result aa raha hai...")
        await asyncio.sleep(10)
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
            f"   ✅ Sahi:`{d['correct']}` ❌ Galat:`{d['wrong']}`\n"
            f"   ⏱`{ft(el)}` 🎯`{acc}%`")
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

    if gh_write(S_FILE, scores, "Scores updated"):
        gist_bak(scores)
        await app.bot.send_message(cid, "💾 Scores GitHub mein save ho gaye! ✅")
    else:
        await app.bot.send_message(cid, "⚠️ Scores save nahi hue.")

# ══════════════════════════════════════════════════════
# PARSE QUESTIONS TEXT
# ══════════════════════════════════════════════════════
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
        if ("question_hi" in d or "question_en" in d) and len(opts)>=2 and "answer_index" in d:
            d["options"]=opts; d["question"]=d.get("question_hi") or d.get("question_en","")
            result.append(d)
    return result

# ══════════════════════════════════════════════════════
# POST INIT — resume auto quiz if it was running
# ══════════════════════════════════════════════════════
async def post_init(app: Application):
    cfg = load_cfg()
    if cfg.get("auto_running") and cfg.get("auto_chat_id"):
        log.info("Resuming auto quiz...")
        asyncio.create_task(run_auto_quiz(app, str(cfg["auto_chat_id"])))

# ══════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════
def main():
    if not BOT_TOKEN:
        log.error("BOT_TOKEN not set!"); return
    log.info("Starting Bot v5.0 (PTB 20.3)...")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start",       c_start))
    app.add_handler(CommandHandler("test",        c_start))
    app.add_handler(CommandHandler("status",      c_status))
    app.add_handler(CommandHandler("leaderboard", c_lb))
    app.add_handler(CommandHandler("stoptest",    c_stop))
    app.add_handler(CommandHandler("addq",        c_addq))
    app.add_handler(CommandHandler("myid",        c_myid))
    app.add_handler(CommandHandler("deleteall",   c_delall))

    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(PollAnswerHandler(on_poll_ans))

    # PDF/Document handler — must be before text handler
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_msg))

    log.info("Bot running!")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
