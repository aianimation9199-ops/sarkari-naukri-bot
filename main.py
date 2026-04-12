import os
import asyncio
import json
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
TIMER = 30  # Har 30 second mein poll

# --- AI & BOT SETUP ---
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')
app = Client("SNA_FINAL_V2", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- FLASK SERVER (Health Check for Railway) ---
server = Flask(__name__)
@server.route('/')
def home(): return "Sarkari Naukri Academy Bot is Online! 🚀"

def run_server():
    server.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

# --- DATA HELPERS ---
def save_data(new_qs):
    data = []
    if os.path.exists("quiz_data.json"):
        try:
            with open("quiz_data.json", "r") as f: data = json.load(f)
        except: data = []
    data.extend(new_qs)
    with open("quiz_data.json", "w") as f: json.dump(data, f)

# --- BOT HANDLERS ---
@app.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    kb = ReplyKeyboardMarkup([[KeyboardButton("📤 Upload PDF")]], resize_keyboard=True)
    await message.reply_text(
        "👋 **Sarkari Naukri Academy**\n\nBilingual Quiz (Hindi/English) polls shuru karne ke liye niche button dabayein.", 
        reply_markup=kb
    )

@app.on_message(filters.regex("📤 Upload PDF") & filters.private)
async def ask_pdf_handler(client, message):
    await message.reply_text("📄 Ab apni PDF file bhejien. Main use scan karke polls bana dunga.")

@app.on_message(filters.document & filters.user(ADMIN_ID) & filters.private)
async def pdf_handler(client, message):
    if not message.document.mime_type == "application/pdf":
        return await message.reply_text("❌ Kripya sirf PDF file bhejien.")
    
    status = await message.reply_text("🔎 PDF Scan ho rahi hai... AI Bilingual sawal bana raha hai. ⏳")
    path = await message.download()
    
    try:
        doc = fitz.open(path)
        text = "".join([page.get_text() for page in doc])
        doc.close()
        
        prompt = (
            "Extract 20 high-quality MCQs. "
            "Questions and Options MUST be Bilingual (English / Hindi). "
            "Add relevant emojis. Return ONLY a clean JSON list: "
            "[{\"s\": \"Subject 📚\", \"q\": \"English Q? / Hindi Q? ❓\", \"o\": [\"A/अ\", \"B/ब\", \"C/स\", \"D/द\"], \"c\": 0}]. "
            "Rule: 'c' is correct index (0-3). No other text."
            f"\n\nText: {text[:8000]}"
        )
        
        response = model.generate_content(prompt)
        res_text = response.text.strip()
        
        # JSON Cleaning
        if "```json" in res_text:
            res_text = res_text.split("```json")[1].split("```")[0].strip()
        elif "```" in res_text:
            res_text = res_text.split("```")[1].split("```")[0].strip()
            
        new_items = json.loads(res_text)
        save_data(new_items)
        await status.edit(f"✅ Success! {len(new_items)} sawal add ho gaye hain.")
        
    except Exception as e:
        print(f"Error: {e}")
        await status.edit("❌ Error: AI format samajh nahi paya. Ek baar phir try karein.")
    
    if os.path.exists(path): os.remove(path)

# --- POLL SENDER LOOP ---
async def poll_loop():
    idx = 0
    while True:
        try:
            if os.path.exists("quiz_data.json"):
                with open("quiz_data.json", "r") as f: data = json.load(f)
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
            print(f"Poll Loop Error: {e}")
        await asyncio.sleep(TIMER)

# --- MAIN EXECUTION ---
async def start_bot():
    # Start Flask in background
    t = Thread(target=run_server, daemon=True)
    t.start()
    
    # Start Bot
    await app.start()
    print("🤖 Bot is Online!")
    
    # Run Poll Loop
    asyncio.create_task(poll_loop())
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_bot())
