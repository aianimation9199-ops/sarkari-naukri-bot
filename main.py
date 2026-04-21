"""
SARKARI NAUKRI ACADEMY — QUIZ BOT v11.0
Fixes in v11.0:
1. Text paste → SIRF BOT mein rehta hai, group mein nahi jata
2. Gemini API add kiya (Groq + Gemini dono use honge, fallback hai)
3. PDF Purchase → Proper inline button menu with all subjects
4. AI Questions → Groq fail hone par Gemini try karta hai automatically
5. Notice add karte waqt group mein bhi jata hai (ye sahi tha, rakha)
6. Broadcast sirf admin request par hota hai
"""

import os, json, time, asyncio, logging, random, re, base64, io
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

# ── Railway Environment Variables ────────────────────────
BOT_TOKEN    = os.environ.get("BOT_TOKEN", "")
ADMIN_ID     = int(os.environ.get("ADMIN_ID", "0"))
CHAT_ID      = os.environ.get("CHAT_ID", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GIST_ID      = os.environ.get("GIST_ID", "")
GROQ_KEY     = os.environ.get("GROQ_KEY", "")
GEMINI_KEY   = os.environ.get("GEMINI_KEY", "")   # NEW: Add GEMINI_KEY in Railway

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

Q_FILE      = "quiz_data.json"
S_FILE      = "scores.json"
CFG_FILE    = "bot_config.json"
NOTICE_FILE = "notices.json"
REQ_FILE    = "pdf_requests.json"

_cache: dict = {}

Q_EMOJIS = ["🎯","📚","🧠","💡","🔥","⚡","🌟","🎓","📖","🏆",
             "🎪","🎭","🎨","🧩","🔮","🌈","🎲","🏅","🎤","💫"]

# ════════════════════════════════════════════════════════
# PAID PDF CATALOG — All subjects with prices
# ════════════════════════════════════════════════════════
# Format: (callback_id, subject_group, display_name, price)
PDF_CATALOG = [
    # ── Bihar Police ──
    ("bp_bundle",  "Bihar Police",    "👮 Bihar Police All Subjects Bundle",    199),
    ("bp_gk",      "Bihar Police",    "👮 Bihar Police GK Full Notes",           49),
    ("bp_ca",      "Bihar Police",    "👮 Bihar Police Current Affairs 2026",    49),
    ("bp_sci",     "Bihar Police",    "👮 Bihar Police Science Notes",           49),
    ("bp_math",    "Bihar Police",    "👮 Bihar Police Math Notes",              49),
    ("bp_hindi",   "Bihar Police",    "👮 Bihar Police Hindi Notes",             49),
    # ── Indian Polity ──
    ("pol_obj",    "Indian Polity",   "📜 Indian Polity Objective 2026",         49),
    ("pol_sub",    "Indian Polity",   "📜 Indian Polity Subjective",             49),
    ("pol_notes",  "Indian Polity",   "📜 Indian Polity Full Notes",             49),
    # ── Chemistry ──
    ("chem_obj",   "Chemistry",       "⚗️ Chemistry Objective (New 2026)",       49),
    ("chem_sub",   "Chemistry",       "⚗️ Chemistry Subjective (New 2026)",      49),
    ("chem_notes", "Chemistry",       "⚗️ Chemistry Full Notes",                 49),
    # ── Biology ──
    ("bio_obj",    "Biology",         "🧬 Biology Objective (New 2026)",         49),
    ("bio_sub",    "Biology",         "🧬 Biology Subjective (New 2026)",        49),
    ("bio_notes",  "Biology",         "🧬 Biology Full Notes",                   49),
    # ── Geography ──
    ("geo_obj",    "Geography",       "🌍 Indian Geography 2026 Objective",      49),
    ("geo_sub",    "Geography",       "🌍 Indian Geography 2026 Subjective",     49),
    ("geo_notes",  "Geography",       "🌍 Indian Geography Full Notes",          49),
    # ── History ──
    ("hist_obj",   "History",         "🏛️ Indian History Objective",            49),
    ("hist_sub",   "History",         "🏛️ Indian History Subjective",           49),
    ("hist_notes", "History",         "🏛️ Indian History Full Notes",           49),
    # ── Current Affairs ──
    ("ca_2026",    "Current Affairs", "📰 Current Affairs 2026 Full",            49),
    ("ca_monthly", "Current Affairs", "📰 Monthly CA Jan-Mar 2026",              49),
    # ── Science ──
    ("sci_obj",    "Science",         "🔬 General Science Objective",            49),
    ("sci_sub",    "Science",         "🔬 General Science Subjective",           49),
    # ── Mathematics ──
    ("math_obj",   "Mathematics",     "🔢 Mathematics Objective",                49),
    ("math_notes", "Mathematics",     "🔢 Mathematics Full Notes",               49),
    # ── Economy ──
    ("eco_obj",    "Economy",         "💰 Indian Economy Objective",             49),
    ("eco_notes",  "Economy",         "💰 Indian Economy Full Notes",            49),
    # ── English ──
    ("eng_obj",    "English",         "🅰️ English Grammar Objective",           49),
    ("eng_notes",  "English",         "🅰️ English Grammar Full Notes",          49),
    # ── Hindi ──
    ("hindi_obj",  "Hindi",           "🔤 Hindi Vyakaran Objective",             49),
    ("hindi_notes","Hindi",           "🔤 Hindi Vyakaran Full Notes",            49),
    # ── Computer ──
    ("comp_obj",   "Computer",        "💻 Computer Awareness Objective",         49),
    ("comp_notes", "Computer",        "💻 Computer Full Notes",                  49),
    # ── Physics ──
    ("phy_obj",    "Physics",         "⚛️ Physics Objective",                    49),
    ("phy_notes",  "Physics",         "⚛️ Physics Full Notes",                   49),
]

# Ordered unique subjects for navigation
PDF_SUBJECTS = list(dict.fromkeys(p[1] for p in PDF_CATALOG))

def pdf_catalog_text():
    """Full catalog text for broadcast to group"""
    lines = [
        "📚 *PREMIUM PDF STORE — SARKARI NAUKRI ACADEMY* 📚",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🎯 *Bihar Police | SSC | Railway | UPSC 2026*",
        "",
    ]
    prev_subj = None
    for pid, subj, name, price in PDF_CATALOG:
        if subj != prev_subj:
            lines.append(f"\n*📂 {subj}:*")
            prev_subj = subj
        lines.append(f"  • {name} — *₹{price}*")
    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "💳 *Kharidne ke 2 tarike:*",
        "1️⃣ Bot mein /buypdf likhein",
        "2️⃣ Group mein: purchase <PDF naam>",
        "",
        "✅ *Payment ke baad turant PDF milega!*",
    ]
    return "\n".join(lines)

def pdf_subj_catalog_text(subj: str) -> str:
    items = [(pid, name, price) for pid, s, name, price in PDF_CATALOG if s == subj]
    lines = [f"📂 *{subj} — Available PDFs*", "━━━━━━━━━━━━━━━━━━━━━━", ""]
    for pid, name, price in items:
        lines.append(f"• {name} — *₹{price}*")
    lines += ["", "👇 Jo chahiye uska button dabao:"]
    return "\n".join(lines)

# ════════════════════════════════════════════════════════
# GITHUB STORAGE
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
        elif r.status_code == 401: return False, "Token invalid"
        elif r.status_code == 403: return False, "No write permission"
    except Exception as e: return False, str(e)
    payload = {"message": msg,
               "content": base64.b64encode(
                   json.dumps(data, ensure_ascii=False, indent=2).encode()).decode(),
               "branch": GH_BRANCH}
    if sha: payload["sha"] = sha
    try:
        r = requests.put(url, headers=_hdr(), json=payload, timeout=20)
        return (True, "") if r.status_code in (200, 201) else (False, f"HTTP {r.status_code}")
    except Exception as e: return False, str(e)

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
        codes = {200: (True, "✅ GitHub OK"), 401: (False, "❌ Token invalid"),
                 403: (False, "❌ No permission"), 404: (False, "❌ Repo not found")}
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
    return {"auto_test": True, "any_q_auto": True}

def save_cfg(c): gh_write(CFG_FILE, c, "cfg")

def load_notices():
    d = gh_read(NOTICE_FILE)
    return d if isinstance(d, list) else []

def save_notices(n): gh_write(NOTICE_FILE, n, "notices")

def load_requests():
    d = gh_read(REQ_FILE)
    return d if isinstance(d, list) else []

def save_requests(r): gh_write(REQ_FILE, r, "requests")

def subjects(qs): return sorted({q.get("subject", "General") for q in qs})

def pick(qs, mode, n):
    pool = qs if mode == "mixed" else [q for q in qs if q.get("subject", "General") == mode]
    return random.sample(pool, min(n, len(pool)))

def ft(s): return f"{int(s) // 60}m {int(s) % 60}s"
def now_ist(): return datetime.now(IST)

def qtxt(q, i, total):
    emoji = Q_EMOJIS[i % len(Q_EMOJIS)]
    hi = q.get("question_hi") or q.get("question", "")
    en = q.get("question_en", "")
    if hi and en and hi.strip() != en.strip():
        body = f"{hi}\n{en}"
    else:
        body = hi or en or "?"
    return (f"{emoji} Q{i + 1}/{total}\n" + body)[:300]

def qopts(q):
    raw = q.get("options", [])
    opts = [str(o).strip()[:100] for o in raw if str(o).strip()]
    while len(opts) < 2:
        opts.append(f"Option {len(opts) + 1}")
    return opts[:10]

def qans(q, opts):
    idx = q.get("answer_index", 0)
    try: idx = int(idx)
    except Exception: idx = 0
    return max(0, min(idx, len(opts) - 1))

def lb_txt(scores, top=20):
    if not scores: return "📊 Koi score nahi hai abhi."
    ranked = sorted(scores.items(),
                    key=lambda x: (-x[1].get("accuracy", 0), x[1].get("best_time", 99999)))[:top]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    lines = ["🏆 *TOP LEADERBOARD* 🏆", "━━━━━━━━━━━━━━━━━━━━━━\n"]
    for i, (uid, d) in enumerate(ranked):
        c = d.get("total_correct", 0); w = d.get("total_wrong", 0)
        acc = round(c / (c + w) * 100, 1) if c + w else 0
        lines.append(
            f"{medals.get(i, str(i + 1) + '.')} *{d.get('name', '?')}*\n"
            f"   ✅`{c}` ❌`{w}` 🎯`{acc}%` ⏱`{ft(d.get('best_time', 0))}`")
    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

# ════════════════════════════════════════════════════════
# KEYBOARDS
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
        [InlineKeyboardButton("📢 Broadcast",         callback_data="broadcast"),
         InlineKeyboardButton("📌 Notice Board",      callback_data="notices")],
        [InlineKeyboardButton("📦 PDF Requests",      callback_data="view_requests"),
         InlineKeyboardButton("🛒 PDF Store",         callback_data="pdf_store")],
        [InlineKeyboardButton("📈 Status",            callback_data="stat"),
         InlineKeyboardButton("🔧 GitHub Check",      callback_data="gh_check")],
    ])

def pdf_store_kb():
    """Main PDF store — subject selection buttons"""
    emoji_map = {
        "Bihar Police": "👮", "Indian Polity": "📜", "Chemistry": "⚗️",
        "Biology": "🧬", "Geography": "🌍", "History": "🏛️",
        "Current Affairs": "📰", "Science": "🔬", "Mathematics": "🔢",
        "Economy": "💰", "English": "🅰️", "Hindi": "🔤",
        "Computer": "💻", "Physics": "⚛️",
    }
    rows = []
    row = []
    for i, subj in enumerate(PDF_SUBJECTS):
        em = emoji_map.get(subj, "📂")
        label = f"{em} {subj}"
        row.append(InlineKeyboardButton(label, callback_data=f"pstore_{subj}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="back")])
    return InlineKeyboardMarkup(rows)

def pdf_subj_kb(subj: str):
    """PDFs for one subject as buttons"""
    items = [(pid, name, price) for pid, s, name, price in PDF_CATALOG if s == subj]
    rows = []
    for pid, name, price in items:
        # Remove emoji prefix for shorter button label
        short = re.sub(r'^[^\w\s]+\s*', '', name).strip()[:38]
        rows.append([InlineKeyboardButton(
            f"{short} — ₹{price}", callback_data=f"preq_{pid}")])
    rows.append([InlineKeyboardButton("🔙 Subjects", callback_data="pdf_store")])
    return InlineKeyboardMarkup(rows)

# ════════════════════════════════════════════════════════
# SMART TEXT PARSER
# ════════════════════════════════════════════════════════
def smart_parse(text: str) -> list:
    if re.search(r'(?:QH:|QE:|SUBJECT:|ANS:)', text, re.I):
        result = _parse_structured(text)
        if result: return result
    result = _parse_numbered(text)
    if result: return result
    return _parse_simple(text)

def _parse_structured(text: str) -> list:
    result = []; am = {"A": 0, "B": 1, "C": 2, "D": 3}
    if "---" in text:
        blocks = text.strip().split("---")
    else:
        blocks = re.split(r'\n\s*\n(?=(?:SUBJECT|QH|QE|Q):)', text.strip(), flags=re.I)
        if len(blocks) == 1:
            blocks = re.split(r'(?=SUBJECT:)', text.strip(), flags=re.I)
    for block in blocks:
        block = block.strip()
        if not block: continue
        d = {"subject": "General"}; opts = []
        for line in block.splitlines():
            line = line.strip()
            if not line: continue
            low = line.upper()
            if low.startswith("SUBJECT:"):   d["subject"]     = line.split(":", 1)[1].strip()
            elif low.startswith("QH:"):      d["question_hi"] = line.split(":", 1)[1].strip()
            elif low.startswith("QE:"):      d["question_en"] = line.split(":", 1)[1].strip()
            elif low.startswith("Q:"):
                v = line.split(":", 1)[1].strip(); d["question_hi"] = v; d["question_en"] = v
            elif re.match(r"^[ABCD]:", low): opts.append(line.split(":", 1)[1].strip())
            elif low.startswith("ANS:"):
                d["answer_index"] = am.get(line.split(":", 1)[1].strip().upper(), 0)
        has_q = "question_hi" in d or "question_en" in d
        if has_q and len(opts) >= 2 and "answer_index" in d:
            d["options"] = opts
            d["question"] = d.get("question_hi") or d.get("question_en", "")
            result.append(d)
    return result

def _parse_numbered(text: str) -> list:
    result = []
    am = {"a": 0, "b": 1, "c": 2, "d": 3, "1": 0, "2": 1, "3": 2, "4": 3}
    blocks = re.split(r'(?:^|\n)\s*\d+[\.\)]\s+', text.strip())
    for block in blocks:
        block = block.strip()
        if len(block) < 10: continue
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines: continue
        qt = lines[0]; opts = []; ans_idx = 0
        for line in lines[1:]:
            m = re.match(r'^[\(\[]?([A-Da-d1-4])[\)\]\.]\s*(.+)', line)
            if m: opts.append(m.group(2).strip()[:100])
            a = re.search(r'(?:ans(?:wer)?|correct|sahi)\s*[:–-]\s*([A-Da-d1-4])', line, re.I)
            if a: ans_idx = am.get(a.group(1).lower(), 0)
        if qt and len(opts) >= 2:
            result.append({
                "question": qt[:300], "question_hi": qt[:300], "question_en": qt[:300],
                "options": opts[:4], "answer_index": ans_idx, "subject": "General"})
    return result

def _parse_simple(text: str) -> list:
    result = []
    am = {"A": 0, "B": 1, "C": 2, "D": 3}
    blocks = re.split(r'\n\s*\n', text.strip())
    for block in blocks:
        block = block.strip()
        if not block: continue
        d = {}; opts = []
        for line in block.splitlines():
            line = line.strip(); low = line.upper()
            if low.startswith("Q:"):
                v = line.split(":", 1)[1].strip()
                d["question_hi"] = v; d["question_en"] = v; d["question"] = v
            elif re.match(r"^[ABCD]:", low): opts.append(line.split(":", 1)[1].strip())
            elif low.startswith("ANS:"):
                d["answer_index"] = am.get(line.split(":", 1)[1].strip().upper(), 0)
        if "question" in d and len(opts) >= 2 and "answer_index" in d:
            d["options"] = opts; d.setdefault("subject", "General")
            result.append(d)
    return result

# ════════════════════════════════════════════════════════
# PDF TEXT EXTRACTION
# ════════════════════════════════════════════════════════
def pdf_to_text(b: bytes) -> str:
    # Method 1: pypdf/PyPDF2
    try:
        try:
            from pypdf import PdfReader
        except ImportError:
            from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(b))
        pages = []
        for page in reader.pages:
            try:
                t = page.extract_text()
                if t: pages.append(t)
            except Exception: pass
        text = "\n".join(pages)
        if len(text.strip()) > 100:
            return text[:20000]
    except Exception as e:
        log.warning("pypdf failed: %s", e)

    # Method 2: Raw binary scan
    try:
        t = b.decode("latin-1", errors="ignore")
        chunks = re.findall(r'\(((?:[^()\\]|\\.)*)\)', t)
        cleaned = []
        for chunk in chunks:
            chunk = chunk.replace('\\n', '\n').replace('\\r', '\n').replace('\\t', ' ')
            chunk = re.sub(r'\\[0-7]{1,3}', '', chunk)
            if len(chunk) > 2: cleaned.append(chunk)
        result = re.sub(r'\s+', ' ', ' '.join(cleaned))
        if len(result.strip()) > 50:
            return result[:20000]
    except Exception as e:
        log.warning("raw pdf scan failed: %s", e)
    return ""

# ════════════════════════════════════════════════════════
# AI — GROQ (primary) + GEMINI (fallback)
# ════════════════════════════════════════════════════════
def _validate_qs(qs: list) -> list:
    valid = []
    for q in qs:
        opts = [str(o).strip() for o in q.get("options", []) if str(o).strip()]
        if len(opts) < 2: continue
        idx = q.get("answer_index", 0)
        try: idx = int(idx)
        except Exception: idx = 0
        idx = max(0, min(idx, len(opts) - 1))
        q["options"] = opts[:4]; q["answer_index"] = idx
        valid.append(q)
    return valid

def _extract_json(txt: str) -> list:
    m = re.search(r"\[.*\]", txt, re.DOTALL)
    if m:
        try: return json.loads(m.group())
        except Exception: pass
    try:
        cleaned = re.sub(r',\s*\]', ']', txt)
        m2 = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if m2: return json.loads(m2.group())
    except Exception: pass
    return []

def _groq_call(prompt: str, max_tok: int = 6000) -> list:
    if not GROQ_KEY: return []
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={"model": "llama3-8b-8192",
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.3, "max_tokens": max_tok},
            timeout=90)
        r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"]
        return _validate_qs(_extract_json(txt))
    except Exception as e:
        log.error("groq_call: %s", e)
        return []

def _gemini_call(prompt: str) -> list:
    if not GEMINI_KEY: return []
    try:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"gemini-1.5-flash:generateContent?key={GEMINI_KEY}")
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 8000}
        }
        r = requests.post(url, json=body, timeout=90)
        r.raise_for_status()
        txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return _validate_qs(_extract_json(txt))
    except Exception as e:
        log.error("gemini_call: %s", e)
        return []

def _ai_call(prompt: str, max_tok: int = 6000) -> list:
    """Try Groq first, fallback to Gemini automatically"""
    result = _groq_call(prompt, max_tok)
    if result:
        return result
    log.info("Groq failed/empty → trying Gemini fallback...")
    return _gemini_call(prompt)

MCQ_SCHEMA = ('[{"question_hi":"हिंदी प्रश्न?","question_en":"English question?",'
              '"options":["Option A","Option B","Option C","Option D"],'
              '"answer_index":0,"subject":"SUBJECT_NAME"}]')

def groq_gen(subject: str, count: int = 10) -> list:
    schema = MCQ_SCHEMA.replace("SUBJECT_NAME", subject)
    prompt = (
        f'Generate {count} MCQ for "{subject}" for SSC/Railway/UPSC/Bihar Police.\n'
        f'Return ONLY valid JSON array (no other text, no markdown):\n{schema}\n'
        f'IMPORTANT: answer_index 0-3. Every answer must be factually correct.'
    )
    return _ai_call(prompt, 4000)

def groq_from_pdf(content: str, count: int = 30, subject: str = "General") -> list:
    snippet = content[:10000]
    schema = MCQ_SCHEMA.replace("SUBJECT_NAME", subject)
    prompt = (
        f"You are an expert MCQ extractor for Indian government exams.\n"
        f"Subject: {subject}\n\n"
        f"TASK: Extract or generate {count} MCQ from this study material.\n"
        f"If the material has questions with options, extract them EXACTLY with correct answers.\n"
        f"If no MCQs found, generate MCQs from the content.\n\n"
        f"MATERIAL:\n{snippet}\n\n"
        f"RULES:\n"
        f"1. answer_index: 0=first option correct, 1=second, 2=third, 3=fourth\n"
        f"2. Every answer MUST be factually correct — double check before including\n"
        f"3. Return ONLY JSON array, no preamble, no markdown:\n{schema}"
    )
    return _ai_call(prompt, 8000)

# ════════════════════════════════════════════════════════
# STATE
# ════════════════════════════════════════════════════════
sess: dict = {}
any_q_sess: dict = {}
any_q_paused = False

# ════════════════════════════════════════════════════════
# COMMANDS
# ════════════════════════════════════════════════════════
async def c_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    groq_s = "✅ Groq" if GROQ_KEY else ""
    gem_s  = "✅ Gemini" if GEMINI_KEY else ""
    ai_s   = " + ".join(filter(None, [groq_s, gem_s])) or "❌ No AI key"
    await u.message.reply_text(
        "🎓 *Sarkari Naukri Academy Quiz Bot v11.0*\n\n"
        "🎯 100 Questions | ⏱ ~16.7 Minutes\n"
        "⚡ Test: 10 sec/Q | ❓ Any Q: 60 sec/Q\n"
        "✅ Sahi = green | ❌ Galat = red\n"
        "📖 Hindi + English bilingual\n"
        "🏆 Winner = Highest Accuracy\n"
        "🕐 Auto: 9AM/12PM/3PM/8PM IST\n"
        f"🤖 AI: {ai_s}\n\n"
        "👇 Choose karo:",
        reply_markup=main_kb(), parse_mode="Markdown")

async def c_status(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    qs = load_qs(); sc = load_sc(); cfg = load_cfg()
    ok, gm = gh_ok(); subs = subjects(qs)
    si = "\n".join(f"  • {s}: {sum(1 for q in qs if q.get('subject', 'General') == s)}"
                   for s in subs) or "  None"
    at = "✅ ON" if cfg.get("auto_test", True) else "❌ OFF"
    aq = "✅ ON" if cfg.get("any_q_auto", True) else "❌ OFF"
    ap = "⏸ PAUSED" if any_q_paused else "▶️ Active"
    groq_s = "✅" if GROQ_KEY else "❌"
    gem_s  = "✅" if GEMINI_KEY else "❌"
    await u.message.reply_text(
        f"📊 *Bot Status v11.0*\n━━━━━━━━━━━━━━━\n"
        f"❓`{len(qs)}` Qs | 👥`{len(sc)}` Users\n"
        f"🔴 Test Active:`{len(sess)}`\n"
        f"🕐 Auto Test: {at} | Any Q Auto: {aq}\n"
        f"❓ Any Q Status: {ap}\n"
        f"🤖 Groq: {groq_s} | Gemini: {gem_s}\n"
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
        "⚠️ *Ye sirf bot mein save hoga — group mein nahi jayega.*\nAb paste karo 👇",
        parse_mode="Markdown")

async def c_myid(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        f"👤 ID:`{u.effective_user.id}`\nName: {u.effective_user.full_name}",
        parse_mode="Markdown")

async def c_ghcheck(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ok, msg = gh_ok()
    await u.message.reply_text(f"🔧 *GitHub*\n{msg}" + ("" if ok else
                                "\nFix: github.com/settings/tokens → repo scope → Railway update"),
                                parse_mode="Markdown")

async def c_buypdf(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show PDF store with subject buttons"""
    await u.message.reply_text(
        "🛒 *PREMIUM PDF STORE*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📂 Subject choose karo:",
        reply_markup=pdf_store_kb(), parse_mode="Markdown")

async def c_notices(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    notices = load_notices()
    if not notices:
        await u.message.reply_text("📌 Abhi koi notice nahi hai."); return
    lines = ["📌 *NOTICE BOARD* 📌", "━━━━━━━━━━━━━━━━━━━━━━", ""]
    for i, n in enumerate(notices[-10:], 1):
        lines.append(f"*{i}.* {n['text']}")
        lines.append(f"   _— {n.get('date', '')}_ \n")
    await u.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def c_addnotice(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_user.id != ADMIN_ID:
        await u.message.reply_text("❌ Sirf admin."); return
    ctx.user_data["add_notice"] = True
    await u.message.reply_text("📌 Notice likhein (group mein bhi post hoga):")

async def c_broadcast(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_user.id != ADMIN_ID:
        await u.message.reply_text("❌ Sirf admin."); return
    ctx.user_data["broadcast"] = True
    await u.message.reply_text(
        "📢 *Broadcast Message*\n\n"
        "Kya group mein bhejna hai?\n"
        "• Koi bhi message likho\n"
        "• `catalog` likho → PDF store list bhejega",
        parse_mode="Markdown")

async def c_pdfpoll(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_user.id != ADMIN_ID:
        await u.message.reply_text("❌ Sirf admin."); return
    ctx.user_data["pdf_mode"] = "polls"
    await u.message.reply_text(
        "📊 *PDF → Group Polls Mode*\n\n"
        "PDF bhejo → bot automatically:\n"
        "1️⃣ MCQ extract karega\n"
        "2️⃣ Subject-wise polls group mein bheji\n"
        "3️⃣ Sahi answer ✅ marked hoga\n\n"
        "Ab PDF bhejo 👇",
        parse_mode="Markdown")

# ════════════════════════════════════════════════════════
# CALLBACKS
# ════════════════════════════════════════════════════════
async def on_cb(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query; await q.answer()
    d = q.data; cid = q.message.chat_id; user = q.from_user
    target = int(CHAT_ID) if CHAT_ID else cid

    # ── PDF Store: subject list ──────────────────────
    if d == "pdf_store":
        await q.message.reply_text(
            "🛒 *PREMIUM PDF STORE*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Har subject ka PDF ₹49 mein\n"
            "Bihar Police Bundle ₹199\n\n"
            "📂 Subject choose karo:",
            reply_markup=pdf_store_kb(), parse_mode="Markdown")
        return

    # ── PDF Store: subject PDFs ──────────────────────
    if d.startswith("pstore_"):
        subj = d[7:]
        await q.message.reply_text(
            pdf_subj_catalog_text(subj),
            reply_markup=pdf_subj_kb(subj),
            parse_mode="Markdown")
        return

    # ── PDF Store: user clicks a PDF button ─────────
    if d.startswith("preq_"):
        pid = d[5:]
        matched = [(name, price) for p_id, subj, name, price in PDF_CATALOG if p_id == pid]
        if not matched:
            await q.message.reply_text("❌ PDF nahi mila."); return
        pdf_name, price = matched[0]
        reqs = load_requests()
        reqs.append({
            "uid":    str(user.id),
            "name":   user.full_name,
            "pdf":    pdf_name,
            "price":  price,
            "date":   now_ist().strftime("%d %b %Y, %I:%M %p IST"),
            "status": "⏳ Pending"
        })
        save_requests(reqs)
        await q.message.reply_text(
            f"✅ *Purchase Request Send Ho Gayi!*\n\n"
            f"📄 {pdf_name}\n"
            f"💳 Price: *₹{price}*\n\n"
            f"🔔 Admin ko notification mil gayi.\n"
            f"Payment ke baad turant PDF milega! 📩",
            parse_mode="Markdown")
        if ADMIN_ID:
            try:
                await ctx.bot.send_message(ADMIN_ID,
                    f"🔔 *NEW PDF REQUEST!*\n\n"
                    f"👤 {user.full_name} (ID: `{user.id}`)\n"
                    f"📄 *{pdf_name}*\n"
                    f"💳 ₹{price}\n"
                    f"🕐 {now_ist().strftime('%d %b %Y, %I:%M %p IST')}\n\n"
                    f"Bot → PDF Requests mein dekho.",
                    parse_mode="Markdown")
            except Exception as e:
                log.error("admin notify: %s", e)
        return

    # ── Standard callbacks ───────────────────────────
    if d == "lb":
        await q.message.reply_text(lb_txt(load_sc()), parse_mode="Markdown")

    elif d == "me":
        uid = str(user.id); sc = load_sc()
        if uid in sc:
            x = sc[uid]; c = x.get("total_correct", 0); w = x.get("total_wrong", 0)
            acc = round(c / (c + w) * 100, 1) if c + w else 0
            await q.message.reply_text(
                f"📊 *Tumhara Score*\n━━━━━━━━━━━━━━\n"
                f"👤 {x.get('name', '?')}\n✅`{c}` ❌`{w}` 🎯`{acc}%`\n"
                f"⏱ Best:`{ft(x.get('best_time', 0))}` 📝`{x.get('tests_taken', 0)}` tests",
                parse_mode="Markdown")
        else:
            await q.message.reply_text("Tumne abhi koi test nahi diya!")

    elif d == "stat":
        await c_status(type("F", (), {"message": q.message, "effective_user": user})(), ctx)

    elif d == "gh_check":
        ok, msg = gh_ok()
        await q.message.reply_text(f"🔧 {msg}")

    elif d == "mode_mixed":
        await begin_test(ctx, target, "mixed")

    elif d == "mode_subj":
        qs = load_qs(); subs = subjects(qs)
        if not subs:
            await q.message.reply_text("❌ Koi questions nahi."); return
        kb = [[InlineKeyboardButton(f"📌 {s}", callback_data=f"s_{s}")] for s in subs]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="back")])
        await q.message.reply_text("📚 *Subject choose karo:*",
                                    reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("s_"):
        await begin_test(ctx, target, d[2:])

    elif d == "polls_start":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        await begin_test(ctx, target, "mixed")

    elif d == "polls_stop":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        if target in sess:
            await end_test(ctx.application, target, forced=True)
            await q.message.reply_text("⏹ Test band.")
        elif target in any_q_sess:
            any_q_sess[target]["running"] = False
            await q.message.reply_text("⏹ Any Questions band.")
        else:
            await q.message.reply_text("Koi poll nahi chal raha.")

    elif d == "any_q_start":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        if any_q_paused:
            await q.message.reply_text("⏸ Paused hai (test ke aas-paas)."); return
        if target in any_q_sess and any_q_sess[target].get("running"):
            await q.message.reply_text("❓ Already chal raha hai."); return
        asyncio.create_task(run_any_questions(ctx.application, target))
        await q.message.reply_text("❓ Any Questions shuru! 1 min/Q.")

    elif d == "toggle_any_q":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        cfg = load_cfg(); cfg["any_q_auto"] = not cfg.get("any_q_auto", True); save_cfg(cfg)
        st = "✅ ON" if cfg["any_q_auto"] else "❌ OFF"
        await q.message.reply_text(f"🔄 Any Questions Auto: {st}")

    elif d == "toggle_auto":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        cfg = load_cfg(); cfg["auto_test"] = not cfg.get("auto_test", True); save_cfg(cfg)
        st = "✅ ON" if cfg["auto_test"] else "❌ OFF"
        await q.message.reply_text(f"🕐 Auto Test: {st}")

    elif d == "text_help":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        ctx.user_data["aq"] = True
        await q.message.reply_text(
            "📋 Text paste karo — bot auto detect karega!\n"
            "⚠️ *Ye sirf bot mein save hoga, group mein nahi jayega.*\n\n"
            "Ab paste karo 👇", parse_mode="Markdown")

    elif d == "pdf_help":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💾 PDF → Quiz Bank (Save only)",
                                  callback_data="pdf_save")],
            [InlineKeyboardButton("📊 PDF → Group Polls (Turant bhejo)",
                                  callback_data="pdf_polls")],
            [InlineKeyboardButton("🔙 Back", callback_data="back")],
        ])
        await q.message.reply_text(
            "📄 *PDF Upload — kya karna hai?*",
            reply_markup=kb, parse_mode="Markdown")

    elif d == "pdf_save":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        ctx.user_data["pdf_mode"] = "save"
        await q.message.reply_text(
            "📄 PDF bhejo — questions sirf quiz bank mein save honge.\n"
            "⚠️ Group mein koi message nahi jayega.")

    elif d == "pdf_polls":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        ctx.user_data["pdf_mode"] = "polls"
        await q.message.reply_text(
            "📊 PDF bhejo — questions nikal ke group mein polls bheji!\n"
            "Subject auto-detect. Sahi answer ✅ marked hoga.")

    elif d == "ai_gen":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        ctx.user_data["ai"] = True
        groq_s = "✅ Groq" if GROQ_KEY else "❌ Groq"
        gem_s  = "✅ Gemini" if GEMINI_KEY else "❌ Gemini"
        await q.message.reply_text(
            f"🤖 AI Status: {groq_s} | {gem_s}\n\n"
            f"Subject likho:\n_Example: History, Chemistry, Biology_",
            parse_mode="Markdown")

    elif d == "broadcast":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        ctx.user_data["broadcast"] = True
        await q.message.reply_text(
            "📢 Group mein bhejna hai woh likho:\n"
            "_(Catalog bhejne ke liye 'catalog' likho)_")

    elif d == "notices":
        notices = load_notices()
        if not notices:
            kb = None
            if user.id == ADMIN_ID:
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("➕ Notice Add", callback_data="add_notice")
                ]])
            await q.message.reply_text("📌 Koi notice nahi hai abhi.", reply_markup=kb)
            return
        lines = ["📌 *NOTICE BOARD* 📌", "━━━━━━━━━━━━━━━━━━━━━━", ""]
        for i, n in enumerate(notices[-10:], 1):
            lines.append(f"*{i}.* {n['text']}")
            lines.append(f"   _— {n.get('date', '')}_ \n")
        kb = None
        if user.id == ADMIN_ID:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("➕ Notice Add", callback_data="add_notice"),
                InlineKeyboardButton("🗑 Clear All", callback_data="clear_notices"),
            ]])
        await q.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=kb)

    elif d == "add_notice":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        ctx.user_data["add_notice"] = True
        await q.message.reply_text("📌 Notice likhein (group mein bhi post hoga):")

    elif d == "clear_notices":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        save_notices([])
        await q.message.reply_text("🗑 Saare notices delete ho gaye.")

    elif d == "view_requests":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        reqs = load_requests()
        if not reqs:
            await q.message.reply_text("📦 Koi pending request nahi hai."); return
        lines = ["📦 *PDF PURCHASE REQUESTS*", "━━━━━━━━━━━━━━━━━━━━━━", ""]
        for i, r in enumerate(reqs[-20:], 1):
            lines.append(
                f"*{i}.* 👤 {r.get('name', '?')} (`{r.get('uid', '?')}`)\n"
                f"   📄 {r.get('pdf', '?')}\n"
                f"   💳 ₹{r.get('price', 49)} | 🕐 {r.get('date', '?')}\n"
                f"   {r.get('status', '⏳ Pending')}\n")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🗑 Clear All", callback_data="clear_requests")
        ]])
        await q.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=kb)

    elif d == "clear_requests":
        if user.id != ADMIN_ID:
            await q.message.reply_text("❌ Sirf admin."); return
        save_requests([])
        await q.message.reply_text("🗑 Requests clear ho gayi.")

    elif d == "back":
        await q.message.reply_text("👇", reply_markup=main_kb())

# ════════════════════════════════════════════════════════
# MESSAGE HANDLER
# ════════════════════════════════════════════════════════
async def on_msg(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = u.effective_user
    text = (u.message.text or "").strip()
    chat_type = u.effective_chat.type  # 'private', 'group', 'supergroup'

    # ── ADMIN: AI Questions ──────────────────────────
    if user.id == ADMIN_ID and ctx.user_data.get("ai"):
        ctx.user_data.pop("ai")
        await u.message.reply_text(
            f"🤖 *{text}* ke liye questions bana raha hoon...", parse_mode="Markdown")
        nq = groq_gen(text, 10)
        if not nq:
            groq_info = "Groq ❌" if GROQ_KEY else "Groq: key nahi"
            gem_info  = "Gemini ❌" if GEMINI_KEY else "Gemini: key nahi"
            await u.message.reply_text(
                f"❌ AI questions nahi bane.\n{groq_info} | {gem_info}\n"
                f"Railway mein GROQ_KEY ya GEMINI_KEY check karo.")
            return
        aq = load_qs(); aq.extend(nq)
        ok, err = gh_write(Q_FILE, aq, f"AI:{len(nq)}")
        await u.message.reply_text(
            f"✅ *{len(nq)} questions add!* Total:{len(aq)}" if ok
            else f"⚠️ Parsed but save fail!\n{err}",
            parse_mode="Markdown")
        return

    # ── ADMIN: Text Paste → SIRF BOT MEIN, GROUP MEIN NAHI ──
    if user.id == ADMIN_ID and ctx.user_data.get("aq"):
        ctx.user_data.pop("aq")
        parsed = smart_parse(text)
        if not parsed:
            await u.message.reply_text(
                "❌ Parse fail. Format sahi nahi.\n/addq se format dekho."); return
        aq = load_qs(); aq.extend(parsed)
        ok, err = gh_write(Q_FILE, aq, f"Manual:{len(parsed)}")
        # ONLY reply to admin — DO NOT send to group
        await u.message.reply_text(
            f"✅ *{len(parsed)} questions bot mein save ho gaye!*\n"
            f"Total: {len(aq)} questions 💾\n"
            f"_Group mein koi message nahi bheja gaya._" if ok
            else f"⚠️ *{len(parsed)} parse* but save fail!\n{err}",
            parse_mode="Markdown")
        return

    # ── ADMIN: Broadcast (sirf explicit broadcast mode) ──
    if user.id == ADMIN_ID and ctx.user_data.get("broadcast"):
        ctx.user_data.pop("broadcast")
        if not CHAT_ID:
            await u.message.reply_text("❌ CHAT_ID set nahi hai Railway mein."); return
        try:
            if text.lower() == "catalog":
                msg_text = pdf_catalog_text()
            else:
                msg_text = (f"📢 *ANNOUNCEMENT*\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                            f"{text}\n\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"_— Sarkari Naukri Academy_")
            await ctx.bot.send_message(int(CHAT_ID), msg_text, parse_mode="Markdown")
            await u.message.reply_text("✅ Group mein broadcast bhej diya!")
        except Exception as e:
            await u.message.reply_text(f"❌ Broadcast fail: {e}")
        return

    # ── ADMIN: Add Notice ────────────────────────────
    if user.id == ADMIN_ID and ctx.user_data.get("add_notice"):
        ctx.user_data.pop("add_notice")
        notices = load_notices()
        notices.append({
            "text": text,
            "date": now_ist().strftime("%d %b %Y, %I:%M %p IST"),
            "by":   user.full_name
        })
        save_notices(notices)
        await u.message.reply_text("✅ Notice save ho gaya!")
        # Notice intentionally posts to group too
        if CHAT_ID:
            try:
                await ctx.bot.send_message(int(CHAT_ID),
                    f"📌 *NOTICE*\n━━━━━━━━━━━━━━━━━━━━━━\n\n{text}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n_— Sarkari Naukri Academy_",
                    parse_mode="Markdown")
            except Exception as e:
                log.error("notice group: %s", e)
        return

    # ── ANY USER: PDF Purchase request via text ──────
    if text.lower().startswith("purchase ") or text.lower().startswith("buy "):
        pdf_name = text.split(" ", 1)[1].strip() if " " in text else "Unknown"
        price = 49
        for pid, subj, name, p in PDF_CATALOG:
            if pdf_name.lower() in name.lower():
                price = p; break
        reqs = load_requests()
        reqs.append({
            "uid":    str(user.id),
            "name":   user.full_name,
            "pdf":    pdf_name,
            "price":  price,
            "date":   now_ist().strftime("%d %b %Y, %I:%M %p IST"),
            "status": "⏳ Pending"
        })
        save_requests(reqs)
        await u.message.reply_text(
            f"✅ *Request Receive Ho Gayi!*\n\n"
            f"📄 PDF: *{pdf_name}*\n"
            f"💳 Price: *₹{price}*\n\n"
            f"🔔 Admin ko notification mil gayi.\n"
            f"Payment ke baad turant PDF milega! 📩",
            parse_mode="Markdown")
        if ADMIN_ID:
            try:
                await ctx.bot.send_message(ADMIN_ID,
                    f"🔔 *NEW PDF REQUEST!*\n\n"
                    f"👤 {user.full_name} (ID: `{user.id}`)\n"
                    f"📄 *{pdf_name}*\n"
                    f"💳 ₹{price}\n"
                    f"🕐 {now_ist().strftime('%d %b %Y, %I:%M %p IST')}\n\n"
                    f"Bot → PDF Requests mein dekho.",
                    parse_mode="Markdown")
            except Exception as e:
                log.error("admin notify: %s", e)
        return

    # ── Default: show menu (only in private/bot DM) ──
    if chat_type in ("group", "supergroup"):
        return  # Group mein random text par menu mat bhejo
    await u.message.reply_text("👇", reply_markup=main_kb())

# ════════════════════════════════════════════════════════
# PDF HANDLER
# ════════════════════════════════════════════════════════
async def on_document(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = u.effective_user
    if user.id != ADMIN_ID:
        await u.message.reply_text("❌ Sirf admin."); return
    doc = u.message.document
    if not doc: return
    fname = (doc.file_name or "").lower()
    if not (fname.endswith(".pdf") or fname.endswith(".txt")):
        await u.message.reply_text("⚠️ Sirf PDF ya TXT bhejo."); return

    pdf_mode = ctx.user_data.pop("pdf_mode", "save")
    pdf_poll_mode = ctx.user_data.pop("pdf_poll_mode", False)
    if pdf_poll_mode: pdf_mode = "polls"

    await u.message.reply_text("📄 PDF process ho rahi hai...")
    try:
        tf = await ctx.bot.get_file(doc.file_id)
        fb = bytes(await tf.download_as_bytearray())
        text = fb.decode("utf-8", errors="ignore") if fname.endswith(".txt") else pdf_to_text(fb)
        if not text.strip():
            await u.message.reply_text(
                "❌ Text extract nahi hua.\n"
                "PDF scanned/protected hai ya text layer nahi hai."); return

        await u.message.reply_text("🤖 AI questions extract kar raha hai... (30-60 sec lagenge)")

        # Detect subject from filename
        subj = "General"
        fname_clean = fname.replace("_", " ").replace("-", " ")
        subj_map = {
            "chemistry": "Chemistry", "bio": "Biology", "polity": "Indian Polity",
            "history": "History", "geography": "Geography", "physics": "Physics",
            "math": "Mathematics", "economy": "Economy", "english": "English",
            "hindi": "Hindi", "computer": "Computer", "science": "Science",
            "gk": "GK", "current": "Current Affairs", "bihar": "Bihar Police",
            "ssc": "SSC", "railway": "Railway",
        }
        for kw, s in subj_map.items():
            if kw in fname_clean:
                subj = s; break

        parsed = groq_from_pdf(text, 30, subj)
        if not parsed:
            parsed = smart_parse(text)
        if not parsed:
            await u.message.reply_text(
                "❌ Questions nahi bane.\n"
                "PDF mein MCQ format hona chahiye,\n"
                "ya Railway mein GROQ_KEY/GEMINI_KEY check karo."); return

        if pdf_mode == "polls":
            target = int(CHAT_ID) if CHAT_ID else u.effective_chat.id
            await u.message.reply_text(
                f"✅ *{len(parsed)} questions extract hue!*\n"
                f"📊 Group mein polls bheji ja rahi hain...\n"
                f"Subject: {subj}", parse_mode="Markdown")

            subj_qs: dict = {}
            for qobj in parsed:
                s = qobj.get("subject", subj)
                subj_qs.setdefault(s, []).append(qobj)

            total_sent = 0
            for s, qs_list in subj_qs.items():
                try:
                    await ctx.bot.send_message(target,
                        f"📚 *{s} — {len(qs_list)} Questions*\n⏱ 60 sec/Q | ✅ = Sahi Answer",
                        parse_mode="Markdown")
                except Exception: pass
                await asyncio.sleep(1)
                for i, qobj in enumerate(qs_list):
                    opts = qopts(qobj); ans = qans(qobj, opts)
                    txt = qtxt(qobj, i, len(qs_list))
                    try:
                        msg = await ctx.bot.send_poll(
                            chat_id=target, question=txt, options=opts,
                            type=Poll.QUIZ, correct_option_id=ans,
                            is_anonymous=False, open_period=60)
                        asyncio.create_task(
                            _del_msg(ctx.application, target, msg.message_id, POLL_DELETE_DELAY))
                        total_sent += 1
                    except Exception as e:
                        log.error("PDF poll Q%d: %s", i + 1, e)
                    await asyncio.sleep(3)
            await u.message.reply_text(
                f"✅ *{total_sent} polls group mein bhej diye!*", parse_mode="Markdown")

        else:  # save mode
            aq = load_qs(); aq.extend(parsed)
            ok, err = gh_write(Q_FILE, aq, f"PDF:{len(parsed)}")
            await u.message.reply_text(
                f"✅ *{len(parsed)} questions quiz bank mein save!*\n"
                f"Subject: {subj} | Total: {len(aq)} 💾\n"
                f"_Group mein koi message nahi bheja._" if ok
                else f"⚠️ {len(parsed)} parsed, save fail.\n{err}",
                parse_mode="Markdown")

    except Exception as e:
        log.error("PDF handler: %s", e)
        await u.message.reply_text(f"❌ Error: {str(e)[:200]}")

# ════════════════════════════════════════════════════════
# ANY QUESTIONS
# ════════════════════════════════════════════════════════
async def run_any_questions(app, chat_id: int):
    global any_q_paused
    if chat_id in any_q_sess and any_q_sess[chat_id].get("running"):
        return
    any_q_sess[chat_id] = {"running": True}
    qs = load_qs()
    if not qs:
        log.warning("any_q: no questions"); return
    idx = 0
    while any_q_sess.get(chat_id, {}).get("running", False):
        if any_q_paused:
            await asyncio.sleep(10); continue
        if chat_id in sess:
            await asyncio.sleep(10); continue
        q = qs[idx % len(qs)]; idx += 1
        opts = qopts(q); ans = qans(q, opts); txt = qtxt(q, idx - 1, len(qs))
        try:
            msg = await app.bot.send_poll(
                chat_id=chat_id, question=txt, options=opts,
                type=Poll.QUIZ, correct_option_id=ans,
                is_anonymous=False, open_period=min(ANY_Q_TIME, 600))
            asyncio.create_task(_del_msg(app, chat_id, msg.message_id, POLL_DELETE_DELAY))
        except Exception as e:
            log.error("any_q poll: %s", e)
        if idx % 10 == 0:
            qs = load_qs() or qs
        await asyncio.sleep(ANY_Q_TIME)
    log.info("any_q stopped for %s", chat_id)

# ════════════════════════════════════════════════════════
# TEST FLOW
# ════════════════════════════════════════════════════════
async def begin_test(ctx, chat_id: int, mode: str):
    global any_q_paused
    if chat_id in sess:
        log.warning("Test already running in %s", chat_id); return False
    qs = load_qs(); sel = pick(qs, mode, TOTAL_Q)
    if not sel:
        try: await ctx.bot.send_message(chat_id, "❌ Questions nahi hain.")
        except Exception: pass
        return False
    any_q_paused = True
    sess[chat_id] = {
        "questions": sel, "poll_map": {}, "user_data": {},
        "start_time": time.time(), "mode": mode, "timer_task": None,
    }
    label = "🔀 Mixed (सभी विषय)" if mode == "mixed" else f"📌 {mode}"
    mins = round(TEST_TOTAL_SEC / 60, 2)
    try:
        await ctx.bot.send_message(chat_id,
            f"🚀 *TEST SHURU!* 🎯\n━━━━━━━━━━━━━━━━━\n"
            f"📋 {label}\n"
            f"❓ {len(sel)} Questions | ⏱ {TEST_Q_TIME}s/Q\n"
            f"⏰ Total: ~{mins} minutes\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"✅ Sahi = green ✅ | ❌ Galat = red ❌\n"
            f"Band karo: /stoptest\n*All the best! 🎯*",
            parse_mode="Markdown")
    except Exception as e: log.error("begin_test: %s", e)
    task = asyncio.create_task(_auto_end(ctx.application, chat_id))
    sess[chat_id]["timer_task"] = task
    asyncio.create_task(_send_test_polls(ctx.application, chat_id))
    return True

async def _auto_end(app, cid):
    await asyncio.sleep(TEST_TOTAL_SEC + 30)
    if cid in sess:
        try: await app.bot.send_message(cid,
            "⏰ *Test khatam!* Result aa raha hai...", parse_mode="Markdown")
        except Exception: pass
        await end_test(app, cid, forced=True)

async def _send_test_polls(app, cid):
    if cid not in sess: return
    s = sess[cid]; total = len(s["questions"])
    for i, q in enumerate(s["questions"]):
        if cid not in sess: return
        opts = qopts(q); ans = qans(q, opts)
        if len(opts) < 2:
            log.warning("Q%d skipped", i + 1); continue
        txt = qtxt(q, i, total)
        try:
            msg = await app.bot.send_poll(
                chat_id=cid, question=txt, options=opts,
                type=Poll.QUIZ, correct_option_id=ans,
                is_anonymous=False, open_period=min(TEST_Q_TIME + 2, 600))
            if cid in sess: sess[cid]["poll_map"][str(msg.poll.id)] = i
            asyncio.create_task(_del_msg(app, cid, msg.message_id, POLL_DELETE_DELAY))
        except Exception as e:
            log.error("Test Poll Q%d: %s", i + 1, e)
        await asyncio.sleep(TEST_Q_TIME)
    if cid in sess:
        try: await app.bot.send_message(cid, "✅ Saare questions ho gaye! Result aa raha hai...")
        except Exception: pass
        await asyncio.sleep(5)
        await end_test(app, cid)

async def on_poll_ans(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pa = u.poll_answer; pid = str(pa.poll_id); user = pa.user; uid = str(user.id)
    for cid, s in list(sess.items()):
        if pid not in s["poll_map"]: continue
        qi = s["poll_map"][pid]; q = s["questions"][qi]
        opts = qopts(q); correct = qans(q, opts)
        if uid not in s["user_data"]:
            s["user_data"][uid] = {
                "name": user.full_name, "correct": 0, "wrong": 0,
                "start_time": s["start_time"], "last_time": time.time()}
        ud = s["user_data"][uid]
        ud["name"] = user.full_name; ud["last_time"] = time.time()
        if pa.option_ids and pa.option_ids[0] == correct: ud["correct"] += 1
        else: ud["wrong"] += 1
        break

async def end_test(app, cid, forced=False):
    global any_q_paused
    if cid not in sess: return
    s = sess.pop(cid)
    if not forced and s.get("timer_task"): s["timer_task"].cancel()
    asyncio.create_task(_resume_any_q_after(RESUME_AFTER_TEST))
    ud = s["user_data"]
    if not ud:
        try: await app.bot.send_message(cid, "📊 Kisi ne participate nahi kiya.")
        except Exception: pass
        return

    def rank_key(item):
        d = item[1]; tot = d["correct"] + d["wrong"]
        acc = d["correct"] / tot if tot else 0
        return (-acc, d["last_time"] - d["start_time"])

    ranked = sorted(ud.items(), key=rank_key)
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    lines = ["🏁 *TEST RESULT* 🏁",
             f"📅 {now_ist().strftime('%d %b %Y, %I:%M %p IST')}",
             "━━━━━━━━━━━━━━━━━━━━━━\n"]
    for i, (uid, d) in enumerate(ranked[:20]):
        el = d["last_time"] - d["start_time"]
        tot = d["correct"] + d["wrong"]
        acc = round(d["correct"] / tot * 100, 1) if tot else 0
        lines.append(
            f"{medals.get(i, str(i + 1) + '.')} *{d['name']}*\n"
            f"   ✅`{d['correct']}` ❌`{d['wrong']}` 🎯`{acc}%` ⏱`{ft(el)}`")
    lines += ["\n━━━━━━━━━━━━━━━━━━━━━━",
              "_Result 2 ghante baad delete hoga_ 🗑",
              "🏆 /leaderboard"]
    sent_ids = []
    try:
        msg = await app.bot.send_message(cid, "\n".join(lines), parse_mode="Markdown")
        sent_ids.append(msg.message_id)
    except Exception as e: log.error("result: %s", e)
    if ranked:
        wname = ranked[0][1]["name"]
        try:
            wm = await app.bot.send_message(cid,
                f"🎊 *Congratulations {wname}!* 🎊\n\n"
                "💫 _\"Mushkilein unhi ko milti hain jo ladna jaante hain,\n"
                "aur manzilein unhi ke kadam choomti hain\n"
                "jo waqt ki qeemat jaante hain.\"_\n\n"
                "🌟 *Keep it up! Aage bhi aisa hi karo!* 🌟",
                parse_mode="Markdown")
            sent_ids.append(wm.message_id)
        except Exception as e: log.error("motiv: %s", e)
    if sent_ids:
        asyncio.create_task(_del_msg_list(app, cid, sent_ids, 7200))

    scores = load_sc()
    for uid, d in ud.items():
        el = d["last_time"] - d["start_time"]; tot = d["correct"] + d["wrong"]
        if uid not in scores:
            scores[uid] = {"name": "", "total_score": 0, "total_correct": 0,
                           "total_wrong": 0, "tests_taken": 0, "best_time": 99999, "accuracy": 0.0}
        sv = scores[uid]
        sv["name"] = d["name"]; sv["total_score"] += d["correct"]
        sv["total_correct"] += d["correct"]; sv["total_wrong"] += d["wrong"]
        sv["tests_taken"] += 1
        if el < sv["best_time"]: sv["best_time"] = round(el, 1)
        t2 = sv["total_correct"] + sv["total_wrong"]
        sv["accuracy"] = round(sv["total_correct"] / t2 * 100, 1) if t2 else 0
    ok, err = gh_write(S_FILE, scores, "scores")
    if ok:
        gist_bak(scores)
        try: await app.bot.send_message(cid, "💾 Scores save ho gaye! ✅")
        except Exception: pass

async def _resume_any_q_after(delay):
    global any_q_paused
    await asyncio.sleep(delay)
    any_q_paused = False

async def _del_msg(app, cid, mid, delay):
    await asyncio.sleep(delay)
    try: await app.bot.delete_message(cid, mid)
    except Exception: pass

async def _del_msg_list(app, cid, mids, delay):
    await asyncio.sleep(delay)
    for mid in mids:
        try: await app.bot.delete_message(cid, mid)
        except Exception: pass

# ════════════════════════════════════════════════════════
# AUTO SCHEDULER
# ════════════════════════════════════════════════════════
async def scheduler(app):
    global any_q_paused
    log.info("Scheduler v11 started")
    fired = set()
    while True:
        try:
            now = now_ist()
            for (nh, nm) in AUTO_NOTIF:
                k = (now.date(), nh, nm, "notif")
                if now.hour == nh and now.minute == nm and k not in fired:
                    fired.add(k)
                    test_h = AUTO_TEST_H[AUTO_NOTIF.index((nh, nm))]
                    if CHAT_ID:
                        try:
                            await app.bot.send_message(int(CHAT_ID),
                                f"🔔 *10 minute mein TEST shuru hoga!*\n"
                                f"🕐 {test_h}:00 IST pe test aayega\n"
                                f"📚 Taiyar ho jao! 🎯\n"
                                f"❓ {len(load_qs())} questions ready hain",
                                parse_mode="Markdown")
                        except Exception as e: log.error("notif: %s", e)
                    any_q_paused = True

            for h in AUTO_TEST_H:
                k = (now.date(), h, "test")
                if now.hour == h and now.minute == 0 and k not in fired:
                    cfg = load_cfg()
                    if cfg.get("auto_test", True) and CHAT_ID:
                        fired.add(k)
                        target = int(CHAT_ID)
                        if target not in sess:
                            asyncio.create_task(
                                begin_test(
                                    type("C", (), {"bot": app.bot, "application": app})(),
                                    target, "mixed"))

            if CHAT_ID:
                target = int(CHAT_ID)
                cfg = load_cfg()
                if (cfg.get("any_q_auto", True) and
                        not any_q_paused and
                        target not in sess and
                        not (any_q_sess.get(target, {}).get("running"))):
                    asyncio.create_task(run_any_questions(app, target))

            today = now.date()
            fired = {k for k in fired if isinstance(k, tuple) and k[0] == today}

        except Exception as e: log.error("scheduler: %s", e)
        await asyncio.sleep(30)

async def post_init(app: Application):
    ok, msg = gh_ok(); log.info("GitHub: %s", msg)
    log.info("Groq: %s | Gemini: %s",
             "✅" if GROQ_KEY else "❌ Not set",
             "✅" if GEMINI_KEY else "❌ Not set")
    asyncio.create_task(scheduler(app))

# ════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════
def main():
    if not BOT_TOKEN:
        log.error("BOT_TOKEN not set!"); return
    log.info("Starting Bot v11.0 ...")
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",       c_start))
    app.add_handler(CommandHandler("test",        c_start))
    app.add_handler(CommandHandler("status",      c_status))
    app.add_handler(CommandHandler("leaderboard", c_lb))
    app.add_handler(CommandHandler("stoptest",    c_stop))
    app.add_handler(CommandHandler("addq",        c_addq))
    app.add_handler(CommandHandler("myid",        c_myid))
    app.add_handler(CommandHandler("ghcheck",     c_ghcheck))
    app.add_handler(CommandHandler("buypdf",      c_buypdf))
    app.add_handler(CommandHandler("notices",     c_notices))
    app.add_handler(CommandHandler("addnotice",   c_addnotice))
    app.add_handler(CommandHandler("broadcast",   c_broadcast))
    app.add_handler(CommandHandler("pdfpoll",     c_pdfpoll))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(PollAnswerHandler(on_poll_ans))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_msg))
    log.info("Bot v11.0 running!")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
