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

# ── Constants & Config ───────────────────────────────────
TEST_Q_TIME = 10
ANY_Q_TIME = 60
TOTAL_Q = 100
TEST_TOTAL_SEC = TOTAL_Q * TEST_Q_TIME
AUTO_TEST_H = [9, 12, 15, 20]
AUTO_NOTIF = [(8, 50), (11, 50), (14, 50), (19, 50)]
IST = timezone(timedelta(hours=5, minutes=30))
POLL_DELETE_DELAY = 300
Q_FILE, S_FILE, CFG_FILE = "quiz_data.json", "scores.json", "bot_config.json"
Q_EMOJIS = ["🎯","📚","🧠","💡","🔥","⚡","🌟","🎓","📖","🏆"]

_cache = {}

# ════════════════════════════════════════════════════════
# CORE FUNCTIONS (Inke bina bot crash hota hai)
# ════════════════════════════════════════════════════════

def _hdr(): return {"Authorization":f"token {GITHUB_TOKEN}","Accept":"application/vnd.github.v3+json"}

def gh_read(fname):
    try:
        r = requests.get(f"https://api.github.com/repos/{GH_USER}/{GH_REPO}/contents/{fname}", headers=_hdr(), timeout=15)
        if r.status_code == 200:
            data = json.loads(base64.b64decode(r.json()["content"]).decode())
            _cache[fname] = data
            return data
    except: pass
    return _cache.get(fname, [])

def gh_write(fname, data, msg="update"):
    if not GITHUB_TOKEN: return False, "No Token"
    url = f"https://api.github.com/repos/{GH_USER}/{GH_REPO}/contents/{fname}"
    sha = None
    try:
        r = requests.get(url, headers=_hdr(), timeout=10)
        if r.status_code == 200: sha = r.json().get("sha")
        payload = {"message":msg, "content":base64.b64encode(json.dumps(data).encode()).decode(), "branch":GH_BRANCH}
        if sha: payload["sha"] = sha
        r = requests.put(url, headers=_hdr(), json=payload, timeout=20)
        return r.status_code in (200, 201), ""
    except Exception as e: return False, str(e)

def gh_ok():
    if not GITHUB_TOKEN: return False, "No Token"
    try:
        r = requests.get(f"https://api.github.com/repos/{GH_USER}/{GH_REPO}", headers=_hdr())
        return (True, "✅ OK") if r.status_code == 200 else (False, f"❌ {r.status_code}")
    except: return False, "❌ Error"

def load_qs(): return gh_read(Q_FILE)
def load_sc(): return gh_read(S_FILE)
def load_cfg():
    d = gh_read(CFG_FILE)
    return d if isinstance(d, dict) else {"auto_test":True, "any_q_auto":True}

def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Mixed Test", callback_data="mode_mixed"), InlineKeyboardButton("🏆 Leaderboard", callback_data="lb")],
        [InlineKeyboardButton("📈 Status", callback_data="stat"), InlineKeyboardButton("🔄 GitHub Check", callback_data="gh_check")]
    ])

# ════════════════════════════════════════════════════════
# HANDLERS (Ye functions upar hone chahiye taaki main() inhe dekh sake)
# ════════════════════════════════════════════════════════

async def c_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text("🎓 *Sarkari Naukri Academy v9.0*\nBot active hai! 👇", reply_markup=main_kb(), parse_mode="Markdown")

async def c_status(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    qs = load_qs()
    ok, msg = gh_ok()
    await u.message.reply_text(f"📊 *Status*\nQs: {len(qs)}\nGitHub: {msg}", parse_mode="Markdown")

async def on_cb(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query; await q.answer()
    if q.data == "stat": await c_status(type("F",(),{"message":q.message,"effective_user":q.from_user})(), ctx)
    elif q.data == "gh_check": ok, msg = gh_ok(); await q.message.reply_text(f"🔧 GitHub: {msg}")

async def post_init(app: Application):
    log.info("Bot Post-Init...")
    # Add any background tasks here

# ════════════════════════════════════════════════════════
# MAIN LAUNCHER
# ════════════════════════════════════════════════════════

def main():
    if not BOT_TOKEN:
        log.error("FATAL: BOT_TOKEN is missing!")
        return
    
    log.info("Starting Bot v9.0...")
    try:
        app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
        
        # Commands registration (Important order)
        app.add_handler(CommandHandler("start", c_start))
        app.add_handler(CommandHandler("status", c_status))
        app.add_handler(CallbackQueryHandler(on_cb))
        
        log.info("Bot started successfully!")
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        log.error(f"FATAL ERROR DURING STARTUP: {e}")

if __name__ == "__main__":
    main()
