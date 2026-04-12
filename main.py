import os
import asyncio
import json
import fitz  # PyMuPDF
import google.generativeai as genai
from pyrogram import Client, filters
from flask import Flask
from threading import Thread

# --- CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
CHAT_ID = int(os.environ.get("CHAT_ID", 0))
TIMER = 30  # Har 30 second mein poll (Ise aap badal sakte hain)

# --- AI SETUP ---
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')
app = Client("SNA_Quiz_Bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- WEB SERVER FOR RAILWAY ---
server = Flask('')
@server.route('/')
def home(): return "Sarkari Naukri Academy Bot is Live!"

def run_server():
    server.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

# --- PDF TO SUBJECT-WISE MCQs ---
@app.on_message(filters.document & filters.user(ADMIN_ID))
async def process_pdf(client, message):
    if message.document.mime_type == "application/pdf":
        status = await message.reply_text("🔎 PDF Scan ho rahi hai... AI important questions nikal raha hai.")
        path = await message.download()
        
        text = ""
        with fitz.open(path) as doc:
            for page in doc: text += page.get_text()
        
        prompt = (
            "Extract top 50 Railway/SSC MCQs from this text. "
            "Categorize each by subject. Return ONLY a valid JSON list like this: "
            "[{\"s\": \"History\", \"q\": \"Question?\", \"o\": [\"A\", \"B\", \"C\", \"D\"], \"c\": 0}]. "
            f"Text: {text[:10000]}"
        )
        
        try:
            response = model.generate_content(prompt)
            clean_json = response.text[response.text.find("["):response.text.rfind("]")+1]
            new_questions = json.loads(clean_json)
            
            data = []
            if os.path.exists("quiz_data.json"):
                with open("quiz_data.json", "r") as f: data = json.load(f)
            
            data.extend(new_questions)
            with open("quiz_data.json", "w") as f: json.dump(data, f)
            
            await status.edit(f"✅ Success! {len(new_questions)} sawal subject-wise add ho gaye hain.")
        except Exception as e:
            await status.edit(f"❌ Error: AI format samajh nahi paya. Fir se try karein.")
        
        if os.path.exists(path): os.remove(path)

# --- AUTOMATIC SEQUENTIAL POLL TIMER ---
async def start_quiz_loop():
    current_pos = 0
    while True:
        try:
            if os.path.exists("quiz_data.json"):
                with open("quiz_data.json", "r") as f:
                    data = json.load(f)
                
                if data:
                    if current_pos >= len(data): current_pos = 0 # Loop restart
                    
                    q = data[current_pos]
                    subject = q.get("s", "General Knowledge")
                    
                    await app.send_poll(
                        chat_id=CHAT_ID,
                        question=f"📚 Subject: {subject}\n\n{q['q']}",
                        options=q['o'],
                        is_anonymous=False,
                        type="quiz",
                        correct_option_id=q['c']
                    )
                    current_pos += 1
        except Exception as e:
            print(f"Loop Error: {e}")
        
        await asyncio.sleep(TIMER)

# --- START BOT ---
async def main():
    Thread(target=run_server).start()
    await app.start()
    print("🤖 Bot is Online!")
    await start_quiz_loop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
