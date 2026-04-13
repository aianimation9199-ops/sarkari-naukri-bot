import os
import asyncio
import json
import re
import random
import fitz  # PyMuPDF
from datetime import datetime
from groq import Groq
from pyrogram import Client, filters, idle, handlers
from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton
from flask import Flask
from threading import Thread

# --- CONFIGURATION (Railway Variables) ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
GROQ_API_KEY = os.environ.get("GROQ_KEY", "") 
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
CHAT_ID = int(os.environ.get("CHAT_ID", 0))
TIMER = int(os.environ.get("TIMER", 30))

# Local Storage
DB_FILE = "quiz_data.json"

# Clients Setup
client_ai = Groq(api_key=GROQ_API_KEY)
app = Client("SNA_PRO_FINAL", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
server = Flask(__name__)

# Global States
IS_RUNNING = True
IS_MEGA_TEST = False
WAITING_TEXT = {}
TEST_POLLS = {} # {poll_id: correct_index}
USER_SCORES = {} # {user_id: {"c": 0, "w": 0, "n": ""}}

@server.route('/')
def home(): return "SNA Professional Bot is Healthy! 🚀", 200

def run_server():
    port = int(os.environ.get("PORT", 8080))
    server.run(host='0.0.0.0', port=port)

# ========== DATA MANAGEMENT ==========
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding='utf-8') as f: return json.load(f)
        except: return []
    return []

def save_db(data):
    with open(DB_FILE, "w", encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ========== GROQ BILINGUAL ENGINE ==========
async def groq_extract_bilingual(text):
    prompt = (
        "You are a professional examiner. Extract exactly 20 high-quality MCQs from the text. "
        "RULES:\n"
        "1. Question and Options must be Bilingual (English / Hindi).\n"
        "   Format: 'Question in English / हिंदी में सवाल? ❓'\n"
        "2. Find the correct answer by looking for 'Ans - (A/B/C/D)' or 'Uttar:' in the text.\n"
        "3. Provide the EXACT correct option text.\n"
        "4. Output ONLY a JSON list: "
        "[{\"q\": \"QE: ? / QH: ?\", \"o\": [\"A / अ\", \"B / ब\", \"C / स\", \"D / द\"], \"ans_txt\": \"Exact correct text\"}]."
        f"\n\nText: {text[:9000]}"
    )
    try:
        r = client_ai.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        res = json.loads(r.choices[0].message.content)
        raw_qs = res.get("questions", res) if isinstance(res, dict) else res
        final_qs = []
        for item in raw_qs:
            opts, ans_text, c_idx = item['o'], item['ans_txt'], 0
            # Accuracy Logic: Finding the correct text index manually
            for i, o in enumerate(opts):
                if ans_text.lower() in o.lower() or o.lower() in ans_text.lower():
                    c_idx = i; break
            final_qs.append({"q": item['q'], "o": opts, "c": c_idx})
        return final_qs
    except Exception as e:
        print(f"Extraction Error: {e}")
        return []

# ========== LEADERBOARD & RESULTS ==========
async def publish_leaderboard():
    global IS_MEGA_TEST, USER_SCORES, TEST_POLLS
    if not USER_SCORES:
        await app.send_message(CHAT_ID, "📊 **Test Alert:** Aaj koi bhagidar nahi mila.")
    else:
        # Rank sorting with 1/3 Negative Marking
        leaderboard = []
        for uid, s in USER_SCORES.items():
            final_marks = s['c'] - (s['w'] * 0.33)
            accuracy = (s['c'] / (s['c'] + s['w']) * 100) if (s['c'] + s['w']) > 0 else 0
            leaderboard.append({"name": s['n'], "score": round(final_marks, 2), "perc": round(accuracy, 1), "c": s['c'], "w": s['w']})
        
        leaderboard = sorted(leaderboard, key=lambda x: x['score'], reverse=True)[:20]
        
        msg = "🏆 **SNA MEGA TEST FINAL RESULT** 🏆\n━━━━━━━━━━━━━━━━━━━━\n\n"
        for i, r in enumerate(leaderboard, 1):
            medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else "🔹"
            msg += f"{medal} **Rank {i}:** {r['name']}\n   ┗ Marks: **{r['score']}** | Sahi: {r['c']} | Galat: {r['w']}\n   ┗ Accuracy: {r['perc']}%\n\n"
        
        # Winner Motivation
        winner = leaderboard[0]['name']
        msg += f"✨ **Winner: {winner}!** ✨\n"
        msg += "━━━━━━━━━━━━━━━━━━━━\n"
        msg += "🎉 Welcome to my group! **और अच्छा से मेहनत करो और Government Job पाओ!** 👮‍♂️🔥"
        await app.send_message(CHAT_ID, msg)

    # Reset test data
    IS_MEGA_TEST, USER_SCORES, TEST_POLLS = False, {}, {}

# FIXED: AttributeError Fix for on_poll_answer
async def handle_poll_ans(client, poll_answer):
    global USER_SCORES
    if not IS_MEGA_TEST: return
    pid = poll_answer.poll_id
    if pid not in TEST_POLLS: return
    
    uid = poll_answer.user.id
    if uid not in USER_SCORES:
        USER_SCORES[uid] = {"c": 0, "w": 0, "n": poll_answer.user.first_name or "Student"}
    
    if poll_answer.option_ids[0] == TEST_POLLS[pid]:
        USER_SCORES[uid]["c"] += 1
    else:
        USER_SCORES[uid]["w"] += 1

# ========== SCHEDULER (9, 12, 3, 5) ==========
async def mega_test_scheduler():
    while True:
        now = datetime.now().strftime("%H:%M")
        if now in ["09:00", "12:00", "15:00", "17:00"]:
            global IS_MEGA_TEST, IS_RUNNING
            IS_MEGA_TEST, IS_RUNNING = True, False
            await app.send_message(CHAT_ID, f"🚨 **MEGA TEST START ({now})** 🚨\nBilingual Mode | Negative Marking (1/3) Active.")
            
            data = load_db()
            if data:
                test_set = random.sample(data, min(len(data), 100))
                for q in test_set:
                    poll = await app.send_poll(CHAT_ID, f"📖 GK MEGA TEST\n\n{q['q']}", q['o'], is_anonymous=False, type="quiz", correct_option_id=q['c'])
                    TEST_POLLS[poll.id] = q['c']
                    await asyncio.sleep(15) # Fast Mega Test Speed
                
                await asyncio.sleep(45); await publish_leaderboard()
            IS_RUNNING = True
        await asyncio.sleep(60)

# ========== ALL 6 BUTTONS & COMMANDS ==========
MAIN_KB = ReplyKeyboardMarkup([
    [KeyboardButton("📝 Text Paste Karo"), KeyboardButton("📥 PDF Upload Karo")],
    [KeyboardButton("▶️ Polls Start"), KeyboardButton("⏹️ Polls Stop")],
    [KeyboardButton("📊 Status"), KeyboardButton("🗑️ Sab Delete Karo")]
], resize_keyboard=True)

@app.on_message(filters.command("start") & filters.private)
async def start(c, m):
    await m.reply_text("🎓 **Sarkari Naukri Academy PRO**\nAccuracy + Results fixed.", reply_markup=MAIN_KB)

@app.on_message(filters.regex("📊 Status"))
async def status(c, m):
    data = load_db()
    state = "Running ✅" if IS_RUNNING else "Stopped ⏹️"
    await m.reply_text(f"📊 **Status**\nPolls: {state}\nQuestions: {len(data)}\nInterval: {TIMER}s")

@app.on_message(filters.regex("⏹️ Polls Stop") & filters.user(ADMIN_ID))
async def stop(c, m):
    global IS_RUNNING
    IS_RUNNING = False
    await m.reply_text("⏹️ Polls rok diye gaye.")

@app.on_message(filters.regex("▶️ Polls Start") & filters.user(ADMIN_ID))
async def start_p(c, m):
    global IS_RUNNING
    IS_RUNNING = True
    await m.reply_text("✅ Polls shuru ho gaye.")

@app.on_message(filters.regex("📥 PDF Upload Karo") & filters.user(ADMIN_ID))
async def pdf_req(c, m): await m.reply_text("📄 Ab apni PDF bhejien.")

@app.on_message(filters.regex("📝 Text Paste Karo") & filters.user(ADMIN_ID))
async def text_req(c, m):
    WAITING_TEXT[m.from_user.id] = True
    await m.reply_text("✏️ Text paste karein (Format: Sawal? - Jawab).")

@app.on_message(filters.document & filters.user(ADMIN_ID))
async def pdf_in(c, m):
    st = await m.reply_text("⏳ Processing Accurate Bilingual Polls... ⚡")
    path = await m.download()
    try:
        doc = fitz.open(path)
        text = " ".join([p.get_text() for p in doc]); doc.close()
        new_qs = await groq_extract_bilingual(text)
        data = load_db(); data.extend(new_qs); save_db(data)
        await st.edit(f"✅ {len(new_qs)} Bilingual questions added safely!")
    except: await st.edit("❌ Error processing PDF.")
    if os.path.exists(path): os.remove(path)

@app.on_message(filters.regex("🗑️ Sab Delete Karo") & filters.user(ADMIN_ID))
async def del_all(c, m):
    save_db([])
    await m.reply_text("🗑️ Saara data delete kar diya gaya.")

# ========== MAIN LOOP ==========
async def polling_loop():
    idx = 0
    while True:
        if IS_RUNNING and not IS_MEGA_TEST:
            try:
                data = load_db()
                if data:
                    if idx >= len(data): idx = 0
                    q = data[idx]
                    await app.send_poll(CHAT_ID, f"📖 GK SPECIAL\n\n{q['q']}", q['o'], is_anonymous=False, type="quiz", correct_option_id=q['c'])
                    idx += 1
            except: pass
        await asyncio.sleep(TIMER)

async def start_everything():
    Thread(target=run_server, daemon=True).start()
    
    # MANUAL HANDLER REGISTRATION to fix AttributeError
    app.add_handler(handlers.PollAnswerHandler(handle_poll_ans))
    
    await app.start()
    print("🚀 SNA Pro Mega Bot Online!")
    asyncio.create_task(polling_loop())
    asyncio.create_task(mega_test_scheduler())
    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(start_everything())
