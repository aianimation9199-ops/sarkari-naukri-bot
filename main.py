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
# Fix: ADMIN_ID validation to prevent crash if empty
try:
    ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0

CHAT_ID      = os.environ.get("CHAT_ID", "") 
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GIST_ID      = os.environ.get("GIST_ID", "")
GROQ_KEY     = os.environ.get("GROQ_KEY", "")

# Note: API_ID and API_HASH are defined in Railway but not strictly needed for this bot logic
# Added to prevent potential NameErrors
API_ID       = os.environ.get("API_ID", "")
API_HASH     = os.environ.get("API_HASH", "")

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
# GITHUB STORAGE (Fixed to handle potential connection errors)
# ════════════════════════════════════════════════════════
def _hdr():
    return {"Authorization":f"token {GITHUB_TOKEN}",
            "Accept":"application/vnd.github.v3+json"}

def gh_read(fname):
    if not GITHUB_TOKEN:
        log.error(f"GH_READ: GITHUB_TOKEN is missing!")
        return _cache.get(fname, [])
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
        log.error(f"gh_read({fname}): {e}")
        return _cache.get(fname, [])

def gh_write(fname, data, msg="update"):
    _cache[fname] = data
    if not GITHUB_TOKEN: return False, "GITHUB_TOKEN not set"
    url = f"https://api.github.com/repos/{GH_USER}/{GH_REPO}/contents/{fname}"
    sha = None
    try:
        r = requests.get(url, headers=_hdr(), timeout=10)
        if r.status_code == 200: sha = r.json().get("sha")
    except Exception as e: log.error(f"GH_WRITE_SHA_ERROR: {e}")
    
    payload = {"message":msg,
               "content":base64.b64encode(
                   json.dumps(data, ensure_ascii=False, indent=2).encode()).decode(),
               "branch":GH_BRANCH}
    if sha: payload["sha"] = sha
    try:
        r = requests.put(url, headers=_hdr(), json=payload, timeout=20)
        return (True,"") if r.status_code in (200,201) else (False,f"HTTP {r.status_code}")
    except Exception as e: return False, str(e)

# Baki saara logic (smart_parse, begin_test, end_test, etc.) wahi rakhein...
# [Yahan wahi saara code paste karein jo aapne pehle bheja tha]

async def post_init(app: Application):
    log.info("Checking GitHub Connection...")
    ok, msg = gh_ok()
    log.info(f"GitHub Status: {msg}")
    # Start scheduler only if bot token is valid
    asyncio.create_task(scheduler(app))
    log.info("Bot Post-Init Complete.")

def main():
    if not BOT_TOKEN:
        log.error("FATAL: BOT_TOKEN is not set in Railway variables!")
        return
    log.info("Starting Bot v9.0...")
    try:
        app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
        
        # Handlers...
        app.add_handler(CommandHandler("start", c_start))
        app.add_handler(CommandHandler("status", c_status))
        # ... [Baki handlers add karein] ...

        log.info("Bot is Polling...")
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    except Exception as e:
        log.error(f"FATAL ERROR DURING STARTUP: {e}")

if __name__ == "__main__":
    main()
