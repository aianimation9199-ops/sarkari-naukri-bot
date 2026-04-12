import os
import asyncio
import json
import re
import fitz  # PyMuPDF
from google import genai
from google.genai import types
from pyrogram import Client, filters, idle
from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton
from flask import Flask
from threading import Thread

# --- CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
CHAT_ID = int(os.environ.get("CHAT_ID", 0))
TIMER = 30

# --- NEW GEMINI SETUP (google-genai package) ---
client_ai = genai.Client(api_key=GEMINI_KEY)

app = Client("SNA_PRO_V3", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Flask Server for Railway
server = Flask(__name__)

@server.route('/')
def home():
    return "SNA Bot is Healthy! 🚀", 200

def run_server():
    port = int(os.environ.get("PORT", 8080))
    server.run(host='0.0.0.0', port=port)

# --- TEXT CLEANER ---
def pro_clean_text(text):
    text = re.sub(r'http\S+|www\S+|@\S+', '', text)
    junk = [
        'GK Trick By Nitin Gupta', 'Ultimate Key to Success', 'Google Play Store',
        'Nitin-Gupta.com', 'Test Series', 'High-Quality PDF Notes', 'Online Course',
        'Daily Monthly Yearly', 'Download our App', 'YouTube', 'Telegram', 'Instagram'
    ]
    for pattern in junk:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    text = re.sub(r'\n+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

# --- ROBUST JSON EXTRACTOR ---
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
    raise ValueError(f"JSON nahi mila response mein: {text[:200]}")

# --- VALIDATE QUESTIONS ---
def validate_questions(questions):
    valid = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        if not all(k in q for k in ['q', 'o', 'c']):
            continue
        if not isinstance(q['o'], list) or len(q['o']) < 2:
            continue
        if not isinstance(q['c'], int) or q['c'] >= len(q['o']):
            continue
        valid.append(q)
    return valid

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    kb = ReplyKeyboardMarkup([[KeyboardButton("📤 Upload PDF")]], resize_keyboard=True)
    await message.reply_text(
        "💪 **Sarkari Naukri Academy Pro**\n\nPDF bhejien, main Bilingual polls bana dunga.",
        reply_markup=kb
    )

@app.on_message(filters.regex("📤 Upload PDF") & filters.private)
async def ask(client, message):
    await message.reply_text("📄 Ab apni PDF bhejien.")

@app.on_message(filters.document & filters.user(ADMIN_ID) & filters.private)
async def handle_pdf(client, message):
    if message.document.mime_type != "application/pdf":
        return await message.reply_text("❌ Kripya sirf PDF bhejien.")

    status = await message.reply_text("⏳ PDF process ho rahi hai... thoda wait karein.")
    path = await message.download()

    try:
        # Step 1: PDF se text nikalo
        doc = fitz.open(path)
        pages_text = [page.get_text() for page in doc]
        doc.close()
        raw_text = " ".join(pages_text)

        if len(raw_text.strip()) < 100:
            return await status.edit("❌ PDF mein readable text nahi mila. Scanned/image PDF supported nahi hai.")

        cleaned = pro_clean_text(raw_text)

        # Step 2: Gemini ko bhejo
        prompt = """You are an expert MCQ creator for Indian government exams.

TASK: Extract exactly 10 MCQs from the given text.

RULES:
- Each question MUST be bilingual: English first, then Hindi
- Each option MUST be bilingual: English / Hindi  
- correct_option_id is 0-indexed (0=A, 1=B, 2=C, 3=D)
- Return ONLY a valid JSON array, no extra text, no markdown

OUTPUT FORMAT:
[
  {
    "s": "Subject Name",
    "q": "English Question? / हिंदी सवाल?",
    "o": ["Option A / विकल्प अ", "Option B / विकल्प ब", "Option C / विकल्प स", "Option D / विकल्प द"],
    "c": 0
  }
]

TEXT:
""" + cleaned[:8000]

        response = client_ai.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                response_mime_type="application/json"
            )
        )

        raw_response = response.text

        # Step 3: JSON parse karo
        questions = extract_json(raw_response)
        questions = validate_questions(questions)

        if not questions:
            raise ValueError("Koi valid question nahi mila")

        # Step 4: Save karo
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
        error_msg = str(e)
        print(f"[ERROR] {error_msg}")

        # Quota error ke liye special message
        if "429" in error_msg or "quota" in error_msg.lower():
            await status.edit(
                "❌ **Gemini API Quota Khatam!**\n\n"
                "Kya karna hai:\n"
                "1. https://aistudio.google.com par jao\n"
                "2. Naya API Key banao (free mein milti hai)\n"
                "3. Railway mein GEMINI_KEY update karo\n\n"
                "Ya kal try karo — daily limit reset hoti hai."
            )
        else:
            await status.edit(f"❌ Error: {error_msg[:150]}\n\nDobara try karein.")

    finally:
        if os.path.exists(path):
            os.remove(path)

# --- POLL LOOP ---
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
    print("🤖 SNA Pro Online!")
    asyncio.create_task(poll_loop())
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
