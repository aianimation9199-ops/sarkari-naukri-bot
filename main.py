import os
import asyncio
import json
import re
import fitz  # PyMuPDF
import google.generativeai as genai
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

# AI Setup
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel(
    model_name='gemini-1.5-flash',
    generation_config={"response_mime_type": "application/json"}
)
app = Client("SNA_HEALTH_FIX", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- FLASK SERVER (For Railway Health Check) ---
server = Flask(__name__)

@server.route('/')
def health_check():
    # Railway ko 'OK' signal bhejne ke liye
    return "Bot is healthy and running!", 200

def run_server():
    # Railway's dynamic port use karein
    port = int(os.environ.get("PORT", 8080))
    server.run(host='0.0.0.0', port=port)

# --- LOGIC & HANDLERS ---
def clean_text(text):
    text = re.sub(r'http\S+|www\S+|@\S+', '', text)
    patterns = [r'GK Trick By Nitin Gupta', r'Google Play Store', r'Nitin-Gupta.com']
    for p in patterns: text = re.sub(p, '', text, flags=re.IGNORECASE)
    return text.strip()

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    kb = ReplyKeyboardMarkup([[KeyboardButton("📤 Upload PDF")]], resize_keyboard=True)
    await message.reply_text("👋 **SNA Bot Active!**\nBilingual polls ke liye niche button dabayein.", reply_markup=kb)

@app.on_message(filters.regex("📤 Upload PDF") & filters.private)
async def instruct(client, message):
    await message.reply_text("📄 Ab apni PDF bhejien.")

@app.on_message(filters.document & filters.user(ADMIN_ID) & filters.private)
async def handle_pdf(client, message):
    status = await message.reply_text("📥 Scanning PDF...")
    path = await message.download()
    try:
        doc = fitz.open(path)
        raw_text = "".join([page.get_text() for page in doc])
        doc.close()
        
        cleaned = clean_text(raw_text)
        prompt = (
            "Extract 25 high-quality MCQs. Both Q and Options must be English / Hindi. "
            "JSON Format: [{\"s\": \"Sub 📚\", \"q\": \"Eng Q / हिंदी स ❓\", \"o\": [\"A/अ\", \"B/ब\", \"C/स\", \"D/द\"], \"c\": 0}]."
            f"\n\nText: {cleaned[:9000]}"
        )
        
        response = model.generate_content(prompt)
        new_qs = json.loads(response.text)
        
        data = []
        if os.path.exists("quiz_data.json"):
            try:
                with open("quiz_data.json", "r") as f: data = json.load(f)
            except: data = []
        data.extend(new_qs)
        with open("quiz_data.json", "w") as f: json.dump(data, f)
        
        await status.edit(f"✅ Success! {len(new_qs)} questions added.")
    except Exception as e:
        await status.edit(f"❌ Error: AI format issue.")
    if os.path.exists(path): os.remove(path)

# --- AUTOMATIC POLL SENDER ---
async def poll_loop():
    idx = 0
    while True:
        try:
            if os.path.exists("quiz_data.json"):
                with open("quiz_data.json", "r") as f: data = json.load(f)
                if data:
                    if idx >= len(data): idx = 0
                    q = data[idx]
                    await app.send_poll(CHAT_ID, f"📖 {q['s']}\n\n{q['q']}", q['o'], is_anonymous=False, type="quiz", correct_option_id=q['c'])
                    idx += 1
        except: pass
        await asyncio.sleep(TIMER)

# --- STARTUP SEQUENCE ---
async def main():
    # 1. Sabse pehle Server chalu karein (Health Check Pass karne ke liye)
    t = Thread(target=run_server, daemon=True)
    t.start()
    
    # 2. Bot ko start karein
    await app.start()
    print("🤖 Bot is Online!")
    
    # 3. Poll loop chalu karein
    asyncio.create_task(poll_loop())
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
