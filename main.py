import os
import asyncio
import json
import re
import random
import fitz
import aiohttp
from datetime import datetime
from groq import Groq
from pyrogram import Client, filters, idle
from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton
from flask import Flask
from threading import Thread

# --- CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
GROQ_API_KEY = os.environ.get("GROQ_KEY", "") 
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
CHAT_ID = int(os.environ.get("CHAT_ID", 0))
TIMER = int(os.environ.get("TIMER", 60))
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GIST_ID = os.environ.get("GIST_ID", "")

# Clients
client_ai = Groq(api_key=GROQ_API_KEY)
app = Client("SNA_ULTIMATE_PRO", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
server = Flask(__name__)

# Global State
IS_RUNNING = True
IS_MEGA_TEST = False
WAITING_TEXT = {}
TEST_POLLS = {} 
USER_SCORES = {} 

@server.route('/')
def home(): return "SNA Professional Bot is Live! 🚀", 200

def run_server():
    port = int(os.environ.get("PORT", 8080))
    server.run(host='0.0.0.0', port=port)

# ========== GITHUB STORAGE (GIST) ==========
async def gist_op(action, data=None):
    if not GITHUB_TOKEN or not GIST_ID: return [] if action == "load" else False
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    url = f"https://api.github.com/gists/{GIST_ID}"
    async with aiohttp.ClientSession() as s:
        try:
            if action == "load":
                async with s.get(url, headers=headers) as r:
                    if r.status == 200:
                        d = await r.json()
                        return json.loads(d['files']['sna_questions.json']['content'])
            else:
                payload = {"files": {"sna_questions.json": {"content": json.dumps(data, ensure_ascii=False)}}}
                async with s.patch(url, headers=headers, json=payload) as r:
                    return r.status == 200
        except: return [] if action == "load" else False
    return []

# ========== ACCURACY & BILINGUAL EXTRACTION ==========
async def groq_extract_bilingual(text):
    prompt = (
        "Extract 20 high-quality MCQs from the text. "
        "Every Question and Option MUST be Bilingual (English / Hindi). "
        "Find the correct answer exactly from 'Ans - (A/B/C/D)' or 'Uttar:' in text. "
        "Return ONLY a JSON list: "
        "[{\"q\": \"Q? / स?❓\", \"o\": [\"Opt1\", \"Opt2\", \"Opt3\", \"Opt4\"], \"ans_txt\": \"Exact correct option text\"}].\n\n"
        f"Text: {text[:9500]}"
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
            opts = item['o']
            ans_text = item['ans_txt']
            c_idx = 0
            for i, o in enumerate(opts):
                if ans_text in o or o in ans_text:
                    c_idx = i
                    break
            final_qs.append({"q": item['q'], "o": opts, "c": c_idx})
        return final_qs
    except: return []

# ========== WINNER & LEADERBOARD (1/3 Negative) ==========
async def publish_results():
    global IS_MEGA_TEST, USER_SCORES, TEST_POLLS
    if not USER_SCORES:
        await app.send_message(CHAT_ID, "📊 **Update:** Aaj kisi ne test nahi diya.")
    else:
        results = []
        for uid, s in USER_SCORES.items():
            # 1/3 Negative Marking logic
            score = s['c'] - (s['w'] * 0.33)
            total = s['c'] + s['w']
            perc = (s['c'] / total * 100) if total > 0 else 0
            results.append({"name": s['n'], "score": round(score, 2), "perc": round(perc, 1), "c": s['c'], "w": s['w']})
        
        results = sorted(results, key=lambda x: x['score'], reverse=True)[:10]
        
        msg = "🏆 **SNA MEGA TEST FINAL RESULT** 🏆\n"
        msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
        for i, r in enumerate(results, 1):
            medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else "🔹"
            msg += f"{medal} **Rank {i}:** {r['name']}\n"
            msg += f"   ┗ Marks: **{r['score']}** | Sahi: {r['c']} | Galat: {r['w']}\n"
            msg += f"   ┗ Accuracy: {r['perc']}%\n\n"
        
        winner = results[0]['name']
        msg += f"✨ **Winner: {winner}!** ✨\n"
        msg += "━━━━━━━━━━━━━━━━━━━━\n"
        msg += "🎉 Welcome to my group! **और अच्छा से मेहनत करो और Government Job पाओ!** 👮‍♂️🔥\n"
        await app.send_message(CHAT_ID, msg)

    IS_MEGA_TEST = False
    USER_SCORES = {}
    TEST_POLLS = {}

@app.on_poll_answer()
async def poll_ans(client, poll_answer):
    if not IS_MEGA_TEST: return
    pid = poll_answer.poll_id
    if pid not in TEST_POLLS: return
    uid = poll_answer.user.id
    if uid not in USER_SCORES:
        USER_SCORES[uid] = {"c": 0, "w": 0, "n": poll_answer.user.first_name}
    if poll_answer.option_ids[0] == TEST_POLLS[pid]:
        USER_SCORES[uid]["c"] += 1
    else:
        USER_SCORES[uid]["w"] += 1

# ========== SCHEDULER (9, 12, 3, 5) ==========
async def mega_test_timer():
    while True:
        now = datetime.now().strftime("%H:%M")
        if now in ["09:00", "12:00", "15:00", "17:00"]:
            global IS_MEGA_TEST, IS_RUNNING
            IS_MEGA_TEST, IS_RUNNING = True, False
            await app.send_message(CHAT_ID, f"🚨 **MEGA TEST START ({now})** 🚨\n100 Questions | Bilingual | Negative 1/3 Active.")
            data = await gist_op("load")
            if data:
                test_set = random.sample(data, min(len(data), 100))
                for q in test_set:
                    poll = await app.send_poll(CHAT_ID, f"📖 GK MEGA TEST\n\n{q['q']}", q['o'], is_anonymous=False, type="quiz", correct_option_id=q['c'])
                    TEST_POLLS[poll.poll.id] = q['c']
                    await asyncio.sleep(15)
                await asyncio.sleep(30)
                await publish_results()
            IS_RUNNING = True
        await asyncio.sleep(60)

# ========== ALL BUTTONS & HANDLERS ==========
MAIN_KB = ReplyKeyboardMarkup([
    [KeyboardButton("📝 Text Paste Karo"), KeyboardButton("📥 PDF Upload Karo")],
    [KeyboardButton("▶️ Polls Start"), KeyboardButton("⏹️ Polls Stop")],
    [KeyboardButton("📊 Status"), KeyboardButton("🗑️ Sab Delete Karo")]
], resize_keyboard=True)

@app.on_message(filters.command("start") & filters.private)
async def start(c, m):
    await m.reply_text("🎓 **Sarkari Naukri Academy PRO**\nAccuracy + Negative Marking + Auto Result Active!", reply_markup=MAIN_KB)

@app.on_message(filters.regex("📊 Status"))
async def status(c, m):
    data = await gist_op("load")
    state = "Running ✅" if IS_RUNNING else "Stopped ⏹️"
    await m.reply_text(f"📊 **Status**\nPolls: {state}\nQuestions: {len(data)}\nInterval: {TIMER}s")

@app.on_message(filters.regex("⏹️ Polls Stop") & filters.user(ADMIN_ID))
async def stop(c, m):
    global IS_RUNNING
    IS_RUNNING = False
    await m.reply_text("⏹️ Polls rok diye gaye hain.")

@app.on_message(filters.regex("▶️ Polls Start") & filters.user(ADMIN_ID))
async def start_p(c, m):
    global IS_RUNNING
    IS_RUNNING = True
    await m.reply_text("✅ Normal polls chalu kar diye gaye hain.")

@app.on_message(filters.regex("📥 PDF Upload Karo") & filters.user(ADMIN_ID))
async def pdf_req(c, m): await m.reply_text("📄 PDF file bhejien.")

@app.on_message(filters.regex("📝 Text Paste Karo") & filters.user(ADMIN_ID))
async def text_req(c, m):
    WAITING_TEXT[m.from_user.id] = True
    await m.reply_text("✏️ Text paste karein (Format: Sawal? - Jawab).")

@app.on_message(filters.document & filters.user(ADMIN_ID))
async def pdf_in(c, m):
    st = await m.reply_text("⏳ Accuracy scanning... ⚡")
    path = await m.download()
    try:
        doc = fitz.open(path)
        text = " ".join([p.get_text() for p in doc])
        doc.close()
        new_qs = await groq_extract_bilingual(text)
        old_qs = await gist_op("load")
        old_qs.extend(new_qs)
        await gist_op("save", old_qs)
        await st.edit(f"✅ **{len(new_qs)} questions added safely!**")
    except: await st.edit("❌ Error scanning PDF.")
    if os.path.exists(path): os.remove(path)

@app.on_message(filters.regex("🗑️ Sab Delete Karo") & filters.user(ADMIN_ID))
async def del_all(c, m):
    await gist_op("save", [])
    await m.reply_text("🗑️ Data cleaned.")

# ========== MAIN LOOP ==========
async def normal_poll_loop():
    idx = 0
    while True:
        if IS_RUNNING and not IS_MEGA_TEST:
            try:
                data = await gist_op("load")
                if data:
                    if idx >= len(data): idx = 0
                    q = data[idx]
                    await app.send_poll(CHAT_ID, f"📖 GK SPECIAL\n\n{q['q']}", q['o'], is_anonymous=False, type="quiz", correct_option_id=q['c'])
                    idx += 1
            except: pass
        await asyncio.sleep(TIMER)

async def run_bot():
    Thread(target=run_server, daemon=True).start()
    await app.start()
    print("🚀 SNA Mega Pro Final Ready!")
    asyncio.create_task(normal_poll_loop())
    asyncio.create_task(mega_test_timer())
    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(run_bot())
