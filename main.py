```python
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
TIMER_SECONDS = 30  # Har 30 second mein poll

# --- AI SETUP ---
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

app = Client("SNA_Bilingual_Bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- WEB SERVER ---
server = Flask('')
@server.route('/')
def home(): return "Sarkari Naukri Academy Bot is Active! 🚀"

def run_server():
    server.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

# --- DATA STORAGE ---
def save_questions(new_q):
    data = []
    if os.path.exists("quiz_data.json"):
        try:
            with open("quiz_data.json", "r") as f: data = json.load(f)
        except: data = []
    data.extend(new_q)
    with open("quiz_data.json", "w") as f: json.dump(data, f)

# --- COMMANDS ---
@app.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    keyboard = ReplyKeyboardMarkup([[KeyboardButton("📤 Upload PDF")]], resize_keyboard=True)
    await message.reply_text(
        "👋 **Sarkari Naukri Academy** mein aapka swagat hai!\n\n"
        "Main PDF se **Hindi & English** dono mein sawal bana sakta hoon. 📚✨\n\n"
        "Niche button par click karke PDF bhejien.",
        reply_markup=keyboard
    )

@app.on_message(filters.regex("📤 Upload PDF") & filters.private)
async def upload_btn(client, message):
    await message.reply_text("Theek hai! Ab apni **PDF file** bhejien. Main use scan karke bilingual quiz bana dunga. 📄⬇️")

# --- PDF & BILINGUAL AI PROCESSING ---
@app.on_message(filters.document & filters.user(ADMIN_ID) & filters.private)
async def handle_pdf(client, message):
    if not message.document.mime_type == "application/pdf":
        return await message.reply_text("❌ Kripya sirf PDF file bhejien.")
    
    status = await message.reply_text("📥 PDF mil gayi! AI ab Hindi aur English mein sawal bana raha hai... ⏳")
    path = await message.download()
    
    try:
        text = ""
        with fitz.open(path) as doc:
            for page in doc: text += page.get_text()
        
        # Power Prompt for Bilingual + Emojis
        prompt = (
            "You are a professional exam content creator. Extract 25 high-quality MCQs from the text. "
            "IMPORTANT: Every question and every option MUST be in both English and Hindi. "
            "Example Question: 'What is the capital of India? / भारत की राजधानी क्या है? 🇮🇳' "
            "Use relevant emojis for each subject. "
            "Return ONLY a clean JSON list: "
            "[{\"s\": \"Subject 📚\", \"q\": \"English Q? / Hindi Q? ❓\", \"o\": [\"Eng / Hin\", \"Eng / Hin\", \"Eng / Hin\", \"Eng / Hin\"], \"c\": 0}]. "
            "Rule: 'c' is correct option index (0-3). No other text."
            f"\n\nText: {text[:9000]}"
        )
        
        response = model.generate_content(prompt)
        res_text = response.text.strip()
        
        # Clean JSON string
        if "

```
