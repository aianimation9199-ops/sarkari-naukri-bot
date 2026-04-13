import os
import asyncio
import json
import re
import fitz
from groq import Groq
from pyrogram import Client, filters, idle
from pyrogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from flask import Flask
from threading import Thread

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
GROQ_KEY = os.environ.get("GROQ_KEY", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
CHAT_ID = int(os.environ.get("CHAT_ID", 0))
TIMER = int(os.environ.get("TIMER", 30))

groq_client = Groq(api_key=GROQ_KEY)
app = Client("SNA_BOT", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
server = Flask(__name__)

QUIZ_FILE = "quiz_data.json"
IDX_FILE = "poll_idx.txt"
STATUS_FILE = "poll_status.txt"
WAITING_TEXT = {}  # user_id: True/False

@server.route('/')
def home():
    return "SNA Bot Running 24x7!", 200

def run_server():
    server.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

# ===== HELPERS =====

def load_questions():
    if os.path.exists(QUIZ_FILE):
        try:
            with open(QUIZ_FILE, "r", encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return []

def save_questions(questions):
    existing = load_questions()
    existing.extend(questions)
    with open(QUIZ_FILE, "w", encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    return len(existing)

def get_idx():
    if os.path.exists(IDX_FILE):
        try:
            return int(open(IDX_FILE).read().strip())
        except:
            pass
    return 0

def set_idx(i):
    with open(IDX_FILE, "w") as f:
        f.write(str(i))

def is_running():
    if os.path.exists(STATUS_FILE):
        return open(STATUS_FILE).read().strip() == "1"
    return True

def set_running(val):
    with open(STATUS_FILE, "w") as f:
        f.write("1" if val else "0")

def clean_text(text):
    text = re.sub(r'http\S+|www\S+|@\S+', '', text)
    for p in ['GK Trick','Nitin Gupta','Test Series','Google Play',
              'Download','YouTube','Telegram','Instagram','Online Course']:
        text = re.sub(p, '', text, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', text).strip()

def split_chunks(text, size=2000):
    words = text.split()
    chunks, cur, cur_len = [], [], 0
    for w in words:
        cur.append(w)
        cur_len += len(w)
        if cur_len >= size:
            chunks.append(' '.join(cur))
            cur, cur_len = [], 0
    if cur:
        chunks.append(' '.join(cur))
    return chunks

def extract_json(text):
    for attempt in [
        lambda t: json.loads(t),
        lambda t: json.loads(re.sub(r'```(?:json)?', '', t).strip().rstrip('`')),
        lambda t: json.loads(re.search(r'(\[.*\])', t, re.DOTALL).group(1)),
    ]:
        try:
            return attempt(text.strip())
        except:
            pass
    return []

def validate_qs(questions):
    valid = []
    for q in questions:
        if not isinstance(q, dict): continue
        if not all(k in q for k in ['q','o','c']): continue
        if not isinstance(q['o'], list) or len(q['o']) < 4: continue
        if not isinstance(q['c'], int) or not (0 <= q['c'] < len(q['o'])): continue
        q['q'] = str(q['q'])[:255]
        q['o'] = [str(o)[:100] for o in q['o']]
        valid.append(q)
    return valid

async def text_to_polls(text):
    prompt = f"""You are an expert MCQ creator for Indian government exams.

INPUT: Questions with answers in any format like:
"56. Gadar Party ke sansthapak? – Lala Hardayal"
"Q. Capital? A. Delhi"

RULES:
1. Extract EACH question + its correct answer from text
2. Make 3 WRONG realistic options  
3. Place correct answer at RANDOM index (use all of 0,1,2,3 across questions)
4. CRITICAL: options[c] MUST equal the correct answer — verify before outputting
5. Keep original Hindi/English language

Return ONLY JSON:
[{{"s":"GK","q":"Question","o":["w1","w2","correct","w3"],"c":2}}]

TEXT:
{text}"""

    r = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role":"user","content":prompt}],
        temperature=0.2,
        max_tokens=4000
    )
    return validate_qs(extract_json(r.choices[0].message.content))

# ===== KEYBOARD =====

def main_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📝 Text Paste Karo"), KeyboardButton("📤 PDF Upload Karo")],
        [KeyboardButton("▶️ Polls Start"), KeyboardButton("⏹️ Polls Stop")],
        [KeyboardButton("📊 Status"), KeyboardButton("🗑️ Sab Delete Karo")]
    ], resize_keyboard=True)

# ===== HANDLERS =====

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    data = load_questions()
    running = is_running()
    await message.reply_text(
        "🎓 **Sarkari Naukri Academy Bot**\n\n"
        f"📊 Questions saved: **{len(data)}**\n"
        f"🔄 Polls: **{'Chal rahe hain ✅' if running else 'Ruke hue hain ⏹️'}**\n"
        f"⏱ Interval: **{TIMER} seconds**\n\n"
        "Neeche buttons use karo 👇",
        reply_markup=main_kb()
    )

@app.on_message(filters.regex("📝 Text Paste Karo") & filters.private & filters.user(ADMIN_ID))
async def ask_text(client, message):
    WAITING_TEXT[message.from_user.id] = True
    await message.reply_text(
        "✏️ **Ab apna text paste karo:**\n\n"
        "Koi bhi format chalega:\n"
        "• `Sawal? – Jawab`\n"
        "• `56. Sawal kya hai? – Answer`\n"
        "• `Q. Question? A. Answer`\n\n"
        "Ek saath 50+ questions bhi de sakte ho! 🚀"
    )

@app.on_message(filters.regex("📤 PDF Upload Karo") & filters.private & filters.user(ADMIN_ID))
async def ask_pdf(client, message):
    await message.reply_text("📄 Ab PDF file bhejien.")

@app.on_message(filters.regex("▶️ Polls Start") & filters.private & filters.user(ADMIN_ID))
async def start_polls(client, message):
    set_running(True)
    data = load_questions()
    await message.reply_text(f"✅ Polls shuru! {len(data)} questions hain loop mein.")

@app.on_message(filters.regex("⏹️ Polls Stop") & filters.private & filters.user(ADMIN_ID))
async def stop_polls(client, message):
    set_running(False)
    await message.reply_text("⏹️ Polls rok diye gaye.")

@app.on_message(filters.regex("📊 Status") & filters.private & filters.user(ADMIN_ID))
async def status(client, message):
    data = load_questions()
    idx = get_idx()
    running = is_running()
    await message.reply_text(
        f"📊 **Bot Status**\n\n"
        f"✅ Polls: {'Chal rahe hain' if running else 'Ruke hue hain'}\n"
        f"❓ Total Questions: {len(data)}\n"
        f"🔢 Current Index: {idx}\n"
        f"⏱ Interval: {TIMER} sec\n"
        f"📍 Next Question: {idx+1}/{len(data)}"
    )

@app.on_message(filters.regex("🗑️ Sab Delete Karo") & filters.private & filters.user(ADMIN_ID))
async def delete_all(client, message):
    for f in [QUIZ_FILE, IDX_FILE]:
        if os.path.exists(f):
            os.remove(f)
    await message.reply_text("🗑️ Saare questions delete ho gaye! Naye add karo.")

# TEXT HANDLER — paste kiya hua text
@app.on_message(
    filters.text & filters.private & filters.user(ADMIN_ID) &
    ~filters.command(["start"]) &
    ~filters.regex("^(📝|📤|▶️|⏹️|📊|🗑️)")
)
async def handle_text(client, message):
    if not WAITING_TEXT.get(message.from_user.id, False):
        return
    
    WAITING_TEXT[message.from_user.id] = False
    text = message.text.strip()
    
    if len(text) < 10:
        return await message.reply_text("❌ Text bahut chhota hai.")

    status_msg = await message.reply_text("⚙️ Processing... thoda wait karo.")
    try:
        # Bade text ko chunks mein process karo
        if len(text) > 3000:
            lines = text.split('\n')
            chunk_size = 30
            all_qs = []
            for i in range(0, len(lines), chunk_size):
                chunk = '\n'.join(lines[i:i+chunk_size])
                if chunk.strip():
                    qs = await text_to_polls(chunk)
                    all_qs.extend(qs)
                    await asyncio.sleep(1)
        else:
            all_qs = await text_to_polls(text)

        if not all_qs:
            return await status_msg.edit(
                "❌ Questions nahi mile.\n"
                "Format: `Sawal? – Jawab`"
            )

        total = save_questions(all_qs)
        await status_msg.edit(
            f"✅ **{len(all_qs)} polls ready!**\n"
            f"📊 Total questions ab: {total}\n"
            f"🔄 Loop mein add ho gaye!"
        )
    except Exception as e:
        await status_msg.edit(f"❌ Error: {str(e)[:200]}")

# PDF HANDLER
@app.on_message(filters.document & filters.user(ADMIN_ID) & filters.private)
async def handle_pdf(client, message):
    if message.document.mime_type != "application/pdf":
        return await message.reply_text("❌ Sirf PDF bhejien.")

    status_msg = await message.reply_text("⏳ PDF pad raha hoon...")
    path = await message.download()

    try:
        doc = fitz.open(path)
        raw = " ".join([p.get_text() for p in doc])
        doc.close()

        if len(raw.strip()) < 100:
            return await status_msg.edit("❌ PDF mein text nahi mila.")

        cleaned = clean_text(raw)
        chunks = split_chunks(cleaned, size=2000)
        total_chunks = len(chunks)
        all_qs = []

        for i, chunk in enumerate(chunks):
            if len(chunk.strip()) < 100:
                continue
            try:
                await status_msg.edit(
                    f"⚙️ Section {i+1}/{total_chunks}\n"
                    f"✅ Questions bane: {len(all_qs)}"
                )
                qs = await text_to_polls(chunk)
                all_qs.extend(qs)
                await asyncio.sleep(1.5)
            except Exception as e:
                print(f"Chunk error: {e}")
                await asyncio.sleep(3)

        if not all_qs:
            return await status_msg.edit("❌ Koi question nahi bana.")

        total = save_questions(all_qs)
        await status_msg.edit(
            f"🎉 **PDF Done!**\n"
            f"❓ Questions bane: {len(all_qs)}\n"
            f"📊 Total loop mein: {total}\n"
            f"🔄 Polls 24x7 chalte rahenge!"
        )
    except Exception as e:
        await status_msg.edit(f"❌ Error: {str(e)[:300]}")
    finally:
        if os.path.exists(path):
            os.remove(path)

# ===== 24x7 POLL LOOP =====
async def poll_loop():
    while True:
        try:
            if is_running():
                data = load_questions()
                if data:
                    idx = get_idx()
                    if idx >= len(data):
                        idx = 0  # Loop back to start
                    
                    q = data[idx]
                    await app.send_poll(
                        CHAT_ID,
                        f"📖 {q.get('s','GK')}\n\n{q['q']}",
                        q['o'],
                        is_anonymous=False,
                        type="quiz",
                        correct_option_id=q['c']
                    )
                    set_idx(idx + 1)
        except Exception as e:
            print(f"[POLL ERROR] {e}")
        
        await asyncio.sleep(TIMER)

async def main():
    Thread(target=run_server, daemon=True).start()
    await app.start()
    print("🚀 SNA Bot Online — 24x7 Mode!")
    asyncio.create_task(poll_loop())
    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
