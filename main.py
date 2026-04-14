"""
SARKARI NAUKRI ACADEMY — QUIZ BOT v6.0
Fixed: GitHub save fail → detailed error + local cache fallback
Railway Variables: BOT_TOKEN, ADMIN_ID, CHAT_ID,
                   GITHUB_TOKEN, GIST_ID, GROQ_KEY, TIMER
"""

import os, json, time, asyncio, logging, random, re, base64
import requests

from telegram import Update, Poll, InlineKeyboardButton, InlineKeyboardMarkup
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
CHAT_ID      = os.environ.get("CHAT_ID", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GIST_ID      = os.environ.get("GIST_ID", "")
GROQ_KEY     = os.environ.get("GROQ_KEY", "")
TIMER        = int(os.environ.get("TIMER", "30"))

GH_USER   = "aianimation9199-ops"
GH_REPO   = "sarkari-naukri-bot"
GH_BRANCH = "main"

TOTAL_Q   = 100
TEST_MIN  = 15
TEST_SEC  = TEST_MIN * 60

Q_FILE    = "quiz_data.json"
S_FILE    = "scores.json"
CFG_FILE  = "bot_config.json"

# ── Local in-memory cache (fallback when GitHub fails) ─
_cache = {}

# ════════════════════════════════════════════════════
# GITHUB HELPERS
# ════════════════════════════════════════════════════

def _gh_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

def gh_read(fname):
    """Read file from GitHub. Returns [] or {} on any failure."""
    # Return from cache first if GitHub fails
    try:
        url = f"https://api.github.com/repos/{GH_USER}/{GH_REPO}/contents/{fname}"
        r = requests.get(url, headers=_gh_headers(), timeout=15)
        if r.status_code == 404:
            return _cache.get(fname, [])
        r.raise_for_status()
        data = json.loads(base64.b64decode(r.json()["content"]).decode("utf-8"))
        _cache[fname] = data   # update cache on success
        return data
    except Exception as e:
        log.error("gh_read(%s): %s", fname, e)
        return _cache.get(fname, [])

def gh_write(fname, data, msg="bot update"):
    """
    Write file to GitHub.
    Returns (True, "") on success or (False, error_reason) on failure.
    NEVER deletes other files — only touches this one file.
    """
    _cache[fname] = data   # always update local cache

    if not GITHUB_TOKEN:
        return False, "GITHUB_TOKEN not set in Railway variables"

    url = f"https://api.github.com/repos/{GH_USER}/{GH_REPO}/contents/{fname}"
    hdr = _gh_headers()

    # Get current SHA
    sha = None
    try:
        r = requests.get(url, headers=hdr, timeout=10)
        if r.status_code == 200:
            sha = r.json().get("sha")
        elif r.status_code == 401:
            return False, "Token invalid ya expired — Railway mein naya GITHUB_TOKEN daalo"
        elif r.status_code == 403:
            return False, "Token ko 'repo' write permission nahi — naya token banao"
        elif r.status_code == 404:
            pass  # new file, ok
        else:
            log.warning("gh_read_sha %s: %s", fname, r.status_code)
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
        elif r.status_code == 401:
            return False, "Token expired — Railway mein GITHUB_TOKEN update karo"
        elif r.status_code == 403:
            return False, "Token mein 'Contents: Write' permission nahi"
        elif r.status_code == 409:
            return False, "Conflict — dobara try karo"
        elif r.status_code == 422:
            return False, "SHA mismatch — dobara try karo"
        else:
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

# ── Token health check ───────────────────────────────
def check_github_token():
    """Returns (ok, message)"""
    if not GITHUB_TOKEN:
        return False, "GITHUB_TOKEN set nahi hai Railway mein"
    try:
        r = requests.get(
            f"https://api.github.com/repos/{GH_USER}/{GH_REPO}",
            headers=_gh_headers(), timeout=10)
        if r.status_code == 200:
            return True, "GitHub connection OK ✅"
        elif r.status_code == 401:
            return False, "Token invalid/expired ❌"
        elif r.status_code == 403:
            return False, "Token permission nahi ❌"
        elif r.status_code == 404:
            return False, f"Repo '{GH_USER}/{GH_REPO}' nahi mila ❌"
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

def load_cfg():
    d = gh_read(CFG_FILE)
    if isinstance(d, dict): return d
    return {"auto_running": False, "auto_chat_id": CHAT_ID, "current_index": 0}

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

def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Mixed Test (सभी विषय)", callback_data="mode_mixed")],
        [InlineKeyboardButton("📚 Subject-wise Test",      callback_data="mode_subj")],
        [InlineKeyboardButton("▶️ Polls Start", callback_data="polls_start"),
         InlineKeyboardButton("⏹ Polls Stop",  callback_data="polls_stop")],
        [InlineKeyboardButton("📄 PDF Upload",  callback_data="pdf_help"),
         InlineKeyboardButton("📋 Text Paste",  callback_data="text_help")],
        [InlineKeyboardButton("🤖 AI Questions बनाओ", callback_data="ai_gen")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="lb"),
         InlineKeyboardButton("📊 My Score",    callback_data="me")],
        [InlineKeyboardButton("📈 Status",      callback_data="stat"),
         InlineKeyboardButton("🗑 Sab Delete",  callback_data="ask_del")],
        [InlineKeyboardButton("🔧 GitHub Check", callback_data="gh_check")],
    ])

# ════════════════════════════════════════════════════
# ACTIVE SESSIONS
# ════════════════════════════════════════════════════
sess = {}

# ════════════════════════════════════════════════════
# COMMANDS
# ════════════════════════════════════════════════════

async def c_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        "🎓 *Sarkari Naukri Academy Quiz Bot*\n\n"
        "• 100 Questions | ⏱ 15 Minutes\n"
        "• ✅ Sahi option = Sahi | ❌ Galat = Wrong\n"
        "• 📖 Hindi + English bilingual\n"
        "• 🏆 Top-20 Leaderboard\n\n"
        "👇 Mode choose karo:",
        reply_markup=main_kb(), parse_mode="Markdown")

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
        f"🔴 Active Tests:`{len(sess)}` | ⏱ Timer:`{TIMER}s`\n"
        f"💾 GitHub: {gh_msg}\n\n"
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
# CALLBACK HANDLER
# ════════════════════════════════════════════════════

async def on_cb(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    await q.answer()
    d = q.data; cid = q.message.chat_id; user = q.from_user

    if d == "lb":
        await q.message.reply_text(lb_msg(load_sc()), parse_mode="Markdown")

    elif d == "me":
        uid = str(user.id); sc = load_sc()
        if uid in sc:
            x=sc[uid]; c=x.get("total_correct",0); w=x.get("total_wrong",0)
            acc = round(c/(c+w)*100,1) if c+w else 0
            await q.message.reply_text(
                f"📊 *Tumhara Score*\n━━━━━━━━━━━━━━\n"
                f"👤 {x.get('name','?')}\n"
                f"✅ Sahi:`{c}` ❌ Galat:`{w}`\n"
                f"🎯 Accuracy:`{acc}%` 📝 Tests:`{x.get('tests_taken',0)}`\n"
                f"⏱ Best:`{ft(x.get('best_time',0))}` 🏆 Score:`{x.get('total_score',0)}`",
                parse_mode="Markdown")
        else:
            await q.message.reply_text("Tumne abhi koi test nahi diya!")

    elif d == "stat":
        qs=load_qs(); sc=load_sc()
        gh_ok, gh_msg = check_github_token()
        si = "\n".join(
            f"  • {s}: {sum(1 for q2 in qs if q2.get('subject','General')==s)}"
            for s in subjects(qs)) or "  None"
        await q.message.reply_text(
            f"📊 `{len(qs)}` Qs | 👥`{len(sc)}` Users | 🔴`{len(sess)}` Tests\n"
            f"💾 GitHub: {'✅' if gh_ok else '❌'} {gh_msg}\n\n*Subjects:*\n{si}",
            parse_mode="Markdown")

    elif d == "gh_check":
        ok, msg = check_github_token()
        icon = "✅" if ok else "❌"
        await q.message.reply_text(
            f"🔧 *GitHub Status*\n\n{icon} {msg}\n\n"
            + ("" if ok else
               "🔑 *Fix:*\n1. github.com/settings/tokens\n"
               "2. New token → `repo` scope ✅\n"
               "3. Railway → GITHUB_TOKEN update karo"),
            parse_mode="Markdown")

    elif d == "mode_mixed":
        await begin(ctx, cid, "mixed")

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

    elif d == "polls_start":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        await begin(ctx, cid, "mixed")

    elif d == "polls_stop":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        if cid in sess:
            await end_test(ctx.application, cid, forced=True)
            await q.message.reply_text("⏹ Polls band kar diye.")
        else:
            await q.message.reply_text("Koi poll nahi chal raha.")

    elif d == "pdf_help":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        ctx.user_data["pdf_mode"] = True
        await q.message.reply_text(
            "📄 *PDF Upload Karo*\n\n"
            "Seedha yahan PDF bhejo.\n"
            "Bot questions extract kar lega!\n\n"
            "PDF format:\n"
            "```\n1. Question?\n(A) Option A\n(B) Option B\n(C) Option C\n(D) Option D\n```",
            parse_mode="Markdown")

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
            "💾 Purane questions DELETE NAHI honge.\n\nAb text paste karo 👇",
            parse_mode="Markdown")

    elif d == "ai_gen":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        ctx.user_data["ai"] = True
        await q.message.reply_text(
            "🤖 Subject likho:\n_Example: History, Science, Geography_",
            parse_mode="Markdown")

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
        ok, err = gh_write(Q_FILE, [], "Admin: delete all")
        if ok:
            await q.message.reply_text("🗑 Saare questions delete ho gaye.")
        else:
            await q.message.reply_text(f"❌ Delete fail: {err}")

    elif d == "no_del":
        await q.message.reply_text("✅ Cancel. Kuch delete nahi hua.")

    elif d == "back":
        await q.message.reply_text("👇 Mode:", reply_markup=main_kb())

# ════════════════════════════════════════════════════
# MESSAGE HANDLER
# ════════════════════════════════════════════════════

async def on_msg(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = u.effective_user
    text = (u.message.text or "").strip()

    # ── AI subject ───────────────────────────────────
    if user.id == ADMIN_ID and ctx.user_data.get("ai"):
        ctx.user_data.pop("ai")
        await u.message.reply_text(
            f"🤖 AI se *{text}* questions bana raha hoon...", parse_mode="Markdown")
        new_qs = groq_gen(text, 10)
        if not new_qs:
            await u.message.reply_text(
                "❌ AI se questions nahi aaye.\nGROQ_KEY check karo ya manually add karo."); return
        all_qs = load_qs(); all_qs.extend(new_qs)
        ok, err = gh_write(Q_FILE, all_qs, f"AI: {len(new_qs)} {text} questions")
        if ok:
            await u.message.reply_text(
                f"✅ {len(new_qs)} AI questions add!\nTotal: {len(all_qs)} 💾✅")
        else:
            await u.message.reply_text(
                f"⚠️ Questions ready hain lekin save nahi hua!\n\n"
                f"❌ Error: {err}\n\n"
                f"🔑 *Fix karo:*\n"
                f"1. github.com/settings/tokens\n"
                f"2. New token → `repo` scope ✅\n"
                f"3. Railway → GITHUB_TOKEN update karo\n\n"
                f"Questions is session mein memory mein hain.")
        return

    # ── Text paste questions ──────────────────────────
    if user.id == ADMIN_ID and ctx.user_data.get("aq"):
        ctx.user_data.pop("aq")
        parsed = parse_qs(text)
        if not parsed:
            await u.message.reply_text(
                "❌ Koi question parse nahi hua.\n\n"
                "Format sahi hona chahiye:\n"
                "```\nSUBJECT: History\n"
                "QH: हिंदी?\nQE: English?\n"
                "A: ...\nB: ...\nC: ...\nD: ...\nANS: A\n---\n```",
                parse_mode="Markdown"); return

        all_qs = load_qs(); all_qs.extend(parsed)
        ok, err = gh_write(Q_FILE, all_qs, f"Manual: {len(parsed)} questions")
        if ok:
            await u.message.reply_text(
                f"✅ *{len(parsed)} questions add ho gaye!*\n"
                f"📊 Total: {len(all_qs)} questions\n"
                f"💾 GitHub safe ✅", parse_mode="Markdown")
        else:
            # Questions are in memory cache — they'll work this session
            await u.message.reply_text(
                f"⚠️ *{len(parsed)} questions parse hue lekin GitHub save nahi hua!*\n\n"
                f"❌ Reason: {err}\n\n"
                f"🔑 *GitHub Token Fix karo:*\n"
                f"1. github.com/settings/tokens pe jao\n"
                f"2. 'Generate new token (classic)' click karo\n"
                f"3. `repo` checkbox ✅ karo (poora)\n"
                f"4. Token copy karo\n"
                f"5. Railway → Variables → GITHUB_TOKEN mein paste karo\n\n"
                f"Questions abhi memory mein hain — test chal sakta hai!",
                parse_mode="Markdown")
        return

    # Default
    await u.message.reply_text("👇 Menu:", reply_markup=main_kb())

# ── PDF handler ──────────────────────────────────────
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
        file_bytes = bytes(await tg_file.download_as_bytearray())
        if fname.endswith(".txt"):
            text = file_bytes.decode("utf-8", errors="ignore")
        else:
            text = _pdf_extract(file_bytes)

        parsed = parse_qs(text)
        if not parsed:
            parsed = _pdf_parse_mcq(text)
        if not parsed:
            await u.message.reply_text(
                "❌ Questions extract nahi ho sake.\n📋 Text Paste button use karo."); return

        all_qs = load_qs(); all_qs.extend(parsed)
        ok, err = gh_write(Q_FILE, all_qs, f"PDF: {len(parsed)} from {doc.file_name}")
        if ok:
            await u.message.reply_text(
                f"✅ *{len(parsed)} questions add!*\nTotal: {len(all_qs)} 💾✅",
                parse_mode="Markdown")
        else:
            await u.message.reply_text(
                f"⚠️ {len(parsed)} questions parse hue, GitHub save fail.\n❌ {err}")
    except Exception as e:
        log.error("PDF: %s", e)
        await u.message.reply_text(f"❌ Error: {str(e)[:150]}")

def _pdf_extract(b: bytes) -> str:
    try:
        text = b.decode("latin-1", errors="ignore")
        chunks = re.findall(r'\((.*?)\)', text)
        result = " ".join(chunks)
        result = re.sub(r'\\[nrt]', ' ', result)
        return re.sub(r'\s+', ' ', result)[:50000]
    except Exception:
        return ""

def _pdf_parse_mcq(text: str) -> list:
    questions = []
    blocks = re.split(r'(?:^|\s)(?:Q\.?\s*)?(\d+)[.)]\s+', text, flags=re.MULTILINE)
    for block in blocks:
        block = block.strip()
        if len(block) < 20: continue
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if not lines: continue
        q_text = lines[0]; opts = []; ans_idx = 0
        for line in lines[1:]:
            m = re.match(r'^[\(\[]?([A-Da-d])[\)\]\.]\s*(.+)', line)
            if m: opts.append(m.group(2).strip()[:100])
            a = re.search(r'(?:ans(?:wer)?|correct)[:\s]*([A-Da-d])', line, re.I)
            if a: ans_idx = ord(a.group(1).upper()) - ord('A')
        if q_text and len(opts) >= 2:
            questions.append({
                "question": q_text[:300], "question_hi": q_text[:300],
                "question_en": q_text[:300], "options": opts[:4],
                "answer_index": max(0, min(ans_idx, len(opts)-1)),
                "subject": "General",
            })
    return questions[:200]

# ════════════════════════════════════════════════════
# GROQ AI
# ════════════════════════════════════════════════════
def groq_gen(subject, count=10):
    if not GROQ_KEY: return []
    prompt = (
        f'Generate {count} MCQ for "{subject}" Indian Govt exams.\n'
        'Return ONLY JSON array:\n'
        '[{"question_hi":"हिंदी?","question_en":"English?",'
        '"options":["A","B","C","D"],'
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

# ════════════════════════════════════════════════════
# TEST FLOW
# ════════════════════════════════════════════════════

async def begin(ctx, cid, mode):
    if cid in sess:
        await ctx.bot.send_message(cid, "⚠️ Test chal raha hai. /stoptest se band karo."); return
    all_qs = load_qs()
    selected = pick(all_qs, mode, TOTAL_Q)
    if not selected:
        await ctx.bot.send_message(cid, "❌ Questions nahi hain.\n📋 Text Paste se add karo."); return
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
        f"/stoptest se band karo\n*All the best! 🎯*",
        parse_mode="Markdown")
    task = asyncio.create_task(_auto_end(ctx.application, cid))
    sess[cid]["timer_task"] = task
    asyncio.create_task(_send_polls(ctx.application, cid))

async def _auto_end(app, cid):
    await asyncio.sleep(TEST_SEC)
    if cid in sess:
        await app.bot.send_message(cid,
            f"⏰ *{TEST_MIN} min khatam!* Result aa raha hai...", parse_mode="Markdown")
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
# POST INIT
# ════════════════════════════════════════════════════

async def post_init(app: Application):
    ok, msg = check_github_token()
    log.info("GitHub token: %s — %s", "OK" if ok else "FAIL", msg)
    if not ok:
        log.warning("GitHub token issue: %s", msg)

# ════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════

def main():
    if not BOT_TOKEN:
        log.error("BOT_TOKEN not set!"); return
    log.info("Starting Bot v6.0 (PTB 20.3)...")
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
