import os
import asyncio
import json
import re
import fitz
from groq import Groq
from pyrogram import Client, filters, idle
from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton
from flask import Flask
from threading import Thread

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
GROQ_KEY = os.environ.get("GROQ_KEY", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
CHAT_ID = int(os.environ.get("CHAT_ID", 0))
TIMER = 30

groq_client = Groq(api_key=GROQ_KEY)
app = Client("SNA_PRO_V3", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
server = Flask(__name__)

@server.route('/')
def home():
    return "SNA Bot is Healthy!", 200

def run_server():
    port = int(os.environ.get("PORT", 8080))
    server.run(host='0.0.0.0', port=port)

def clean_text(text):
    text = re.sub(r'http\S+|www\S+|@\S+', '', text)
    junk = ['GK Trick', 'Nitin Gupta', 'Test Series', 'Google Play', 'Download',
            'YouTube', 'Telegram', 'Instagram', 'Online Course']
    for p in junk:
        text = re.sub(p, '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def split_chunks(text, size=2500):
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
    text = text.strip()
    try:
        return json.loads(text)
    except:
        pass
    try:
        cleaned = re.sub(r'```(?:json)?', '', text).strip().rstrip('`').strip()
        return json.loads(cleaned)
    except:
        pass
    try:
        match = re.search(r'(\[.*\])', text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
    except:
        pass
    return []

def validate_questions(questions):
    valid = []
    for q in questions:
        if not isinstance(q, dict): continue
        if not all(k in q for k in ['q', 'o', 'c']): continue
        if not isinstance(q['o'], list) or len(q['o']) < 4: continue
        if not isinstance(q['c'], int): continue
        if q['c'] < 0 or q['c'] >= len(q['o']): continue
        valid.append(q)
    return valid

def make_prompt(chunk, i, total):
    return f"""You are processing an Indian government exam question paper (PDF).

Your job is to EXTRACT questions EXACTLY as written in the text — do NOT create new questions.

RULES:
1. Find questions that are ALREADY in the text (numbered like Q1, 1., (1) etc)
2. Extract the question text EXACTLY
3. Extract all 4 options EXACTLY as given (A, B, C, D)
4. Find the correct answer — it may be marked as "Ans:", "Answer:", "उत्तर:" etc
5. "c" = index of correct option (0=A, 1=B, 2=C, 3=D)
6. Translate to bilingual format: "English text / हिंदी अनुवाद"
7. If answer is NOT given in text, use your knowledge to find correct answer
8. Return ONLY JSON array

CRITICAL: The option at index "c" MUST be the CORRECT answer!

Verify example:
- Options: ["Delhi/दिल्ली", "Mumbai/मुंबई", "Patna/पटना", "Jaipur/जयपुर"]
- If correct answer is Mumbai → c must be 1
- If correct answer is Patna → c must be 2

JSON FORMAT:
[{{"s": "Subject Name", "q": "Question in English / हिंदी में सवाल", "o": ["A/अ", "B/ब", "C/स", "D/द"], "c": 1}}]

TEXT CHUNK {i}/{total}:
{chunk}

Return ONLY the JSON array. If no questions found in this chunk, return empty array [].
"""

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    kb = ReplyKeyboardMarkup([[KeyboardButton("📤 Upload PDF")]], resize_keyboard=True)
    await message.reply_text(
        "💪 **Sarkari Naukri Academy Pro**\n\n"
        "PDF ke exact questions extract karunga!\n"
        "Sahi answer 100% correct hoga ✅",
        reply_markup=kb
    )

@app.on_message(filters.regex("📤 Upload PDF") & filters.private)
async def ask(client, message):
    await message.reply_text("📄 Ab apni PDF bhejien.")

@app.on_message(filters.document & filters.user(ADMIN_ID) & filters.private)
async def handle_pdf(client, message):
    if message.document.mime_type != "application/pdf":
        return await message.reply_text("❌ Kripya sirf PDF bhejien.")

    status = await message.reply_text("⏳ PDF pad raha hoon...")
    path = await message.download()

    try:
        doc = fitz.open(path)
        raw_text = " ".join([page.get_text() for page in doc])
        doc.close()

        if len(raw_text.strip()) < 100:
            return await status.edit("❌ PDF mein readable text nahi mila.")

        cleaned = clean_text(raw_text)
        chunks = split_chunks(cleaned, size=2500)
        total = len(chunks)

        await status.edit(f"📚 {total} sections mile. Questions extract ho rahi hain...")

        all_questions = []

        for i, chunk in enumerate(chunks):
            if len(chunk.strip()) < 150:
                continue
            try:
                await status.edit(
                    f"⚙️ Section {i+1}/{total} process ho raha hai...\n"
                    f"✅ Abhi tak: {len(all_questions)} questions"
                )

                response = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "user", "content": make_prompt(chunk, i+1, total)}],
                    temperature=0.1,  # Low temperature = exact extraction
                    max_tokens=2000
                )

                raw = response.choices[0].message.content
                qs = extract_json(raw)
                qs = validate_questions(qs)
                all_questions.extend(qs)
                await asyncio.sleep(2)

            except Exception as e:
                print(f"Chunk {i+1} error: {e}")
                await asyncio.sleep(5)
                continue

        if not all_questions:
            return await status.edit(
                "❌ PDF mein koi MCQ format nahi mila.\n"
                "Yeh PDF question paper hai? Agar haan toh dobara bhejien."
            )

        # Save
        data = []
        if os.path.exists("quiz_data.json"):
            try:
                with open("quiz_data.json", "r", encoding='utf-8') as f:
                    data = json.load(f)
            except:
                data = []

        data.extend(all_questions)
        with open("quiz_data.json", "w", encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        await status.edit(
            f"✅ **Kaam Ho Gaya!**\n\n"
            f"📄 PDF sections: {total}\n"
            f"❓ Questions extract hue: {len(all_questions)}\n"
            f"📊 Total loop mein: {len(data)}\n\n"
            f"🔄 Polls har {TIMER} sec mein channel mein jayenge!"
        )

    except Exception as e:
        await status.edit(f"❌ Error:\n{str(e)[:300]}")

    finally:
        if os.path.exists(path):
            os.remove(path)

async def poll_loop():
    idx = 0
    while True:
        try:
            if os.path.exists("quiz_data.json"):
                with open("quiz_data.json", "r", encoding='utf-8') as f:
                    data = json.load(f)
                if data:
                    if idx >= len(data):
                        idx = 0
                    q = data[idx]
                    await app.send_poll(
                        CHAT_ID,
                        f"📖 {q.get('s', 'GK')}\n\n{q['q']}",
                        q['o'],
                        is_anonymous=False,
                        type="quiz",
                        correct_option_id=q['c']
                    )
                    idx += 1
        except Exception as e:
            print(f"[POLL ERROR] {e}")
        await asyncio.sleep(TIMER)

async def main():
    Thread(target=run_server, daemon=True).start()
    await app.start()
    print("SNA Pro Online!")
    asyncio.create_task(poll_loop())
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
