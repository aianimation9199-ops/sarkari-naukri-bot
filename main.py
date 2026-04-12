import os
import asyncio
import json
import random
import fitz  # PyMuPDF
import google.generativeai as genai
from pyrogram import Client, filters
from flask import Flask
from threading import Thread

# Variables (Railway se uthayega)
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
CHAT_ID = int(os.environ.get("CHAT_ID", 0))

# Gemini Setup
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

app = Client("railway_quiz_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def load_data():
    if not os.path.exists("quiz_data.json"): return []
    try:
        with open("quiz_data.json", "r", encoding="utf-8") as f: return json.load(f)
    except: return []

def save_data(data):
    with open("quiz_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# PDF Processing with AI
@app.on_message(filters.document & filters.user(ADMIN_ID))
async def handle_pdf(client, message):
    if message.document.mime_type == "application/pdf":
        m = await message.reply_text("⏳ Gemini AI PDF scan kar raha hai...")
        path = await message.download()
        
        text = ""
        with fitz.open(path) as doc:
            for page in doc: text += page.get_text()
        
        prompt = f"Extract 15 important MCQs for Railway/SSC from this text. Return ONLY raw JSON list: [{{'subject': 'GK', 'question': '...', 'options': ['A','B','C','D'], 'correct': 0}}]. Text: {text[:5000]}"
        
        try:
            response = model.generate_content(prompt)
            raw_res = response.text
            start, end = raw_res.find("["), raw_res.rfind("]") + 1
            new_qs = json.loads(raw_res[start:end])
            
            data = load_data()
            data.extend(new_qs)
            save_data(data)
            await m.edit(f"✅ {len(new_qs)} Questions Railway database mein add ho gaye!")
        except Exception as e:
            await m.edit(f"❌ Error: AI format samajh nahi paya.")
        os.remove(path)

# Auto Poll Loop (1 Minute)
async def auto_poll():
    while True:
        data = load_data()
        if data:
            q = random.choice(data)
            try:
                await app.send_poll(
                    chat_id=CHAT_ID,
                    question=f"📚 [{q['subject']}]\n\n{q['question']}",
                    options=q['options'],
                    is_anonymous=False,
                    type="quiz",
                    correct_option_id=q['correct']
                )
            except: pass
        await asyncio.sleep(60)

# Web Server for Railway
server = Flask('')
@server.route('/')
def home(): return "Sarkari Naukri Academy is Live!"
def run_s(): server.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

async def start_bot():
    Thread(target=run_s).start()
    await app.start()
    await auto_poll()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(start_bot())
