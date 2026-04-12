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
TIMER = 30 

# AI Setup
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# Bot Client
app = Client("SNA_FINAL_BOT", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Flask Server for Railway Health Check
server = Flask(__name__)
@server.route('/')
def home(): return "Bot is Online!"

def run_server():
    server.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

# --- DATA STORAGE ---
def save_q(new_data):
    current = []
    if os.path.exists("quiz_data.json"):
        try:
            with open("quiz_data.json", "r") as f: current = json.load(f)
        except: current = []
    current.extend(new_data)
    with open("quiz_data.json", "w") as f: json.dump(current, f)

# --- BOT HANDLERS ---
@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    kb = ReplyKeyboardMarkup([[KeyboardButton("📤 Upload PDF")]], resize_keyboard=True)
    await message.reply_text("👋 **Sarkari Naukri Academy**\n\nBilingual Quiz ke liye niche button dabayein.", reply_markup=kb)

@app.on_message(filters.regex("📤 Upload PDF") & filters.private)
async def ask_pdf(client, message):
    await message.reply_text("📄 Ab apni PDF bhejien. Main scan karke Hindi/English polls bana dunga.")

@app.on_message(filters.document & filters.user(ADMIN_ID) & filters.private)
async def handle_pdf(client, message):
    status = await message.reply_text("🔎 PDF Reading... AI Bilingual MCQs bana raha hai. ⏳")
    path = await message.download()
    
    try:
        doc = fitz.open(path)
        text = "".join([page.get_text() for page in doc])
        doc.close()
        
        prompt = (
            "Extract 25 high-quality Railway MCQs. "
            "Questions and Options MUST be Bilingual (English / Hindi). "
            "Example: 'Capital of India? / भारत की राजधानी?'. "
            "Return ONLY JSON list: [{\"s\": \"Sub 📚\", \"q\": \"Q? / स?❓\", \"o\": [\"A/अ\", \"B/ब\", \"C/स\", \"D/द\"], \"c\": 0}]. "
            f"Text: {text[:8000]}"
        )
        
        response = model.generate_content(prompt)
        res_text = response.text.strip()
        if "
http://googleusercontent.com/immersive_entry_chip/0
http://googleusercontent.com/immersive_entry_chip/1

### Step 3: `quiz_data.json` ko saaf karein
GitHub mein is file ko kholiye aur sab kuch delete karke sirf `[]` likh kar save kar dein.

---

### Ab kya hoga?
1.  Jaise hi aap GitHub par save karenge, Railway deploy karega. Is baar ye crash nahi hoga kyunki humne `asyncio.create_task` aur `Thread` ka sahi combination use kiya hai.
2.  Deploy hone ke baad Telegram par `/start` likhiye.
3.  **"📤 Upload PDF"** button dabaiye aur apni PDF bhej dijiye.
4.  Bot **"Success"** bolega aur thik **30 second** baad aapke group mein **Bilingual (Hindi/English)** poll aa jayega.

Ise commit karke dekhiye, aapka bot ab ekdum "Sarkari Naukri Academy" ka asli champion ban jayega! 🚀
