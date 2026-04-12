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

def pro_clean_text(text):
    text = re.sub(r'http\S+|www\S+|@\S+', '', text)
    junk = ['GK Trick By Nitin Gupta', 'Ultimate Key to Success', 'Google Play Store',
            'Nitin-Gupta.com', 'Test Series', 'High-Quality PDF Notes', 'Online Course',
            'Daily Monthly Yearly', 'Download our App', 'YouTube', 'Telegram', 'Instagram']
    for p in junk:
        text = re.sub(p, '', text, flags=re.IGNORECASE)
    text = re.sub(r'\n+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

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
    raise ValueError(f"JSON nahi mila: {text[:200]}")

def validate_questions(questions):
    valid = []
    for q in questions:
        if not isinstance(q, dict): continue
        if not all(k in q for k in ['q', 'o', 'c']): continue
        if not isinstance(q['o'], list) or len(q['o']) < 2: continue
        if not isinstance(q['c'], int) or q['c'] >= len(q['o']): continue
        valid.append(q)
    return valid

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    kb = ReplyKeyboardMarkup([[KeyboardButton("📤 Upload PDF")]], resize_keyboard=True)
    await message.reply_text("💪 **Sarkari Naukri Academy Pro**\n\nPDF bhejien, main Bilingual polls bana dunga.", reply_markup=kb)

@app.on_message(filters.regex("📤 Upload PDF") & filters.private)
async def ask(client, message):
    await message.reply_text("📄 Ab apni PDF bhejien.")

@app.on_message(filters.document & filters.user(ADMIN_ID) & filters.private)
async def handle_pdf(client, message):
    if message.document.mime_type != "application/pdf":
        return await message.reply_text("❌ Kripya sirf PDF bhejien.")

    status = await message.reply_text("⏳ PDF process ho rahi hai... wait karein.")
    path = await message.download()

    try:
        doc = fitz.open(path)
        raw_text = " ".join([page.get_text() for page in doc])
        doc.close()

        if len(raw_text.strip()) < 100:
            return await status.edit("❌ PDF mein readable text nahi mila.")

        cleaned = pro_clean_text(raw_text)

        prompt = """You are an expert MCQ creator for Indian government exams.
Extract exactly 10 MCQs from the given text.
RULES:
- Each question MUST be bilingual: English first, then Hindi
- Each option MUST be bilingual: English / Hindi
- correct_option_id is 0-indexed (0=A, 1=B, 2=C, 3=D)
- Return ONLY a valid JSON array, no extra text, no markdown

FORMAT:
[{"s": "Subject", "q": "English? / हिंदी?", "o": ["A/अ", "B/ब", "C/स", "D/द"], "c": 0}]

TEXT:
""" + cleaned[:6000]

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )

        raw = response.choices[0].message.content
        questions = extract_json(raw)
        questions = validate_questions(questions)

        if not questions:
            raise ValueError("Koi valid question nahi mila")

        data = []
        if os.path.exists("quiz_data.json"):
            try:
                with open("quiz_data.json", "r", encoding='utf-8') as f:
                    data = json.load(f)
            except:
                data = []

        data.extend(questions)
        with open("quiz_data.json", "w", encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        await status.edit(f"✅ **Done!** {len(questions)} bilingual sawaal add ho gaye!")

    except Exception as e:
        await status.edit(f"❌ Error:\n{str(e)[:400]}")

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
                    if idx >= len(data): idx = 0
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
