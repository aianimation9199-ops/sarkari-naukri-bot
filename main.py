import os
import asyncio
import json
import re
import random
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
TIMER = int(os.environ.get("TIMER", 60))

groq_client = Groq(api_key=GROQ_KEY)
app = Client("SNA_BOT", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
server = Flask(__name__)

QUIZ_FILE = "quiz_data.json"
IDX_FILE = "poll_idx.txt"
STATUS_FILE = "poll_status.txt"
WAITING_TEXT = {}

@server.route('/')
def home():
    return "SNA Bot 24x7!", 200

def run_server():
    server.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

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
    try:
        return int(open(IDX_FILE).read().strip()) if os.path.exists(IDX_FILE) else 0
    except:
        return 0

def set_idx(i):
    open(IDX_FILE, "w").write(str(i))

def is_running():
    return open(STATUS_FILE).read().strip() == "1" if os.path.exists(STATUS_FILE) else True

def set_running(val):
    open(STATUS_FILE, "w").write("1" if val else "0")

def clean_text(text):
    text = re.sub(r'http\S+|www\S+|@\S+', '', text)
    for p in ['GK Trick','Nitin Gupta','Test Series','Google Play',
              'Download','YouTube','Telegram','Instagram','Online Course']:
        text = re.sub(p, '', text, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', text).strip()

def split_chunks(text, size=1500):
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
    for fn in [
        lambda t: json.loads(t),
        lambda t: json.loads(re.sub(r'```(?:json)?','',t).strip().rstrip('`')),
        lambda t: json.loads(re.search(r'(\[.*\])', t, re.DOTALL).group(1)),
    ]:
        try:
            return fn(text)
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

async def verify_correct(question, options):
    """Step 2: Alag call — sirf sahi answer index poocho"""
    opts_text = "\n".join([f"{i}: {o}" for i, o in enumerate(options)])
    prompt = f"""Fact checker for Indian government exams.

Question: {question}

Options:
{opts_text}

Which option number (0, 1, 2, or 3) is the CORRECT answer based on real facts?
Reply with ONLY one digit: 0, 1, 2, or 3
Nothing else."""

    r = groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=5
    )
    result = r.choices[0].message.content.strip()
    digit = re.search(r'[0-3]', result)
    return int(digit.group()) if digit else None

async def text_to_polls(text):
    # STEP 1: Bilingual questions + options banao
    prompt = f"""You are an expert bilingual MCQ creator for Indian government exams.

TEXT contains Q&A like: "Gadar Party ke sansthapak? – Lala Hardayal"

YOUR TASK:
1. Extract each question and its correct answer from the text
2. Create 3 wrong but realistic options
3. Put CORRECT answer at index 0 (we handle placement later)
4. Make BOTH question AND options BILINGUAL:
   - Question: "Hindi text? / English translation?"
   - Options: "Hindi option / English option"
5. Keep subject relevant (History/GK/Science etc)

EXAMPLE OUTPUT:
[{{
  "s": "History / इतिहास",
  "q": "गदर पार्टी के संस्थापक कौन थे? / Who founded the Gadar Party?",
  "o": [
    "लाला हरदयाल / Lala Hardayal",
    "भगत सिंह / Bhagat Singh", 
    "सुभाष चंद्र बोस / Subhash Chandra Bose",
    "बाल गंगाधर तिलक / Bal Gangadhar Tilak"
  ],
  "c": 0
}}]

Return ONLY JSON array. No extra text.

TEXT:
{text}"""

    r = groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=4000
    )
    raw_qs = validate_qs(extract_json(r.choices[0].message.content))

    # STEP 2: Har question shuffle + verify
    verified = []
    for q in raw_qs:
        try:
            opts = q['o'].copy()
            correct_text = opts[0]  # index 0 pe correct hai

            # Options shuffle karo
            random.shuffle(opts)
            shuffled_c = opts.index(correct_text)

            # AI se verify karo
            await asyncio.sleep(0.5)
            ai_c = await verify_correct(q['q'], opts)

            q['o'] = opts
            q['c'] = ai_c if ai_c is not None else shuffled_c
            verified.append(q)

        except Exception as e:
            print(f"Verify error: {e}")
            continue

    return verified

def main_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📝 Text Paste Karo"), KeyboardButton("📤 PDF Upload Karo")],
        [KeyboardButton("▶️ Polls Start"),     KeyboardButton("⏹️ Polls Stop")],
        [KeyboardButton("📊 Status"),          KeyboardButton("🗑️ Sab Delete Karo")]
    ], resize_keyboard=True)

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    data = load_questions()
    await message.reply_text(
        "🎓 **Sarkari Naukri Academy Bot**\n\n"
        f"📊 Questions saved: **{len(data)}**\n"
        f"🔄 Polls: **{'Chal rahe hain ✅' if is_running() else 'Ruke hue hain ⏹️'}**\n"
        f"⏱ Interval: **{TIMER} seconds**\n\n"
        "👇 Buttons use karo:",
        reply_markup=main_kb()
    )

@app.on_message(filters.regex("📝 Text Paste Karo") & filters.private & filters.user(ADMIN_ID))
async def ask_text(client, message):
    WAITING_TEXT[message.from_user.id] = True
    await message.reply_text(
        "✏️ **Ab text paste karo — koi bhi format:**\n\n"
        "`Gadar Party ke sansthapak? – Lala Hardayal`\n"
        "`Dandi March kab? – 12 March 1930`\n\n"
        "Ek saath 50+ questions de sakte ho!"
    )

@app.on_message(filters.regex("📤 PDF Upload Karo") & filters.private & filters.user(ADMIN_ID))
async def ask_pdf(client, message):
    await message.reply_text("📄 PDF bhejien.")

@app.on_message(filters.regex("▶️ Polls Start") & filters.private & filters.user(ADMIN_ID))
async def start_polls(client, message):
    set_running(True)
    await message.reply_text(f"✅ Polls shuru! {len(load_questions())} questions hain.")

@app.on_message(filters.regex("⏹️ Polls Stop") & filters.private & filters.user(ADMIN_ID))
async def stop_polls(client, message):
    set_running(False)
    await message.reply_text("⏹️ Polls rok diye.")

@app.on_message(filters.regex("📊 Status") & filters.private & filters.user(ADMIN_ID))
async def status(client, message):
    data = load_questions()
    idx = get_idx()
    await message.reply_text(
        f"📊 **Bot Status**\n\n"
        f"✅ Polls: {'Chal rahe hain' if is_running() else 'Ruke hue hain'}\n"
        f"❓ Total Questions: {len(data)}\n"
        f"🔢 Abhi tak bheje: {idx}\n"
        f"⏱ Interval: {TIMER} sec"
    )

@app.on_message(filters.regex("🗑️ Sab Delete Karo") & filters.private & filters.user(ADMIN_ID))
async def delete_all(client, message):
    for f in [QUIZ_FILE, IDX_FILE]:
        if os.path.exists(f): os.remove(f)
    await message.reply_text("🗑️ Saare questions delete ho gaye!")

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
        return

    status_msg = await message.reply_text("⚙️ Bilingual polls ban rahi hain... thoda wait karo.")
    try:
        lines = text.split('\n')
        all_qs = []
        chunk_size = 15
        total_chunks = (len(lines) + chunk_size - 1) // chunk_size

        for i in range(0, len(lines), chunk_size):
            chunk = '\n'.join(lines[i:i+chunk_size])
            if not chunk.strip(): continue
            cn = i // chunk_size + 1
            await status_msg.edit(
                f"⚙️ Processing {cn}/{total_chunks}...\n"
                f"✅ Questions ready: {len(all_qs)}"
            )
            qs = await text_to_polls(chunk)
            all_qs.extend(qs)
            await asyncio.sleep(2)

        if not all_qs:
            return await status_msg.edit("❌ Questions nahi mile. Format: `Sawal? – Jawab`")

        total = save_questions(all_qs)
        await status_msg.edit(
            f"✅ **{len(all_qs)} bilingual polls ready!**\n"
            f"📊 Total ab: {total} questions\n"
            f"🔄 Group mein jayenge!"
        )
    except Exception as e:
        await status_msg.edit(f"❌ Error: {str(e)[:200]}")

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
        chunks = split_chunks(cleaned, size=1500)
        all_qs = []
        for i, chunk in enumerate(chunks):
            if len(chunk.strip()) < 100: continue
            await status_msg.edit(
                f"⚙️ Section {i+1}/{len(chunks)}\n"
                f"✅ Questions: {len(all_qs)}"
            )
            try:
                qs = await text_to_polls(chunk)
                all_qs.extend(qs)
                await asyncio.sleep(2)
            except Exception as e:
                print(f"PDF chunk error: {e}")
                await asyncio.sleep(4)
        if not all_qs:
            return await status_msg.edit("❌ Koi question nahi bana.")
        total = save_questions(all_qs)
        await status_msg.edit(
            f"🎉 **PDF Done!**\n"
            f"❓ Questions bane: {len(all_qs)}\n"
            f"📊 Total: {total}"
        )
    except Exception as e:
        await status_msg.edit(f"❌ Error: {str(e)[:200]}")
    finally:
        if os.path.exists(path): os.remove(path)

async def poll_loop():
    while True:
        try:
            if is_running():
                data = load_questions()
                if data:
                    idx = get_idx()
                    if idx >= len(data):
                        idx = 0
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
    print("🚀 SNA Bot Online — 24x7!")
    asyncio.create_task(poll_loop())
    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
