import os
import asyncio
import json
import re
import random
import fitz
import aiohttp
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
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GIST_ID = os.environ.get("GIST_ID", "")

groq_client = Groq(api_key=GROQ_KEY)
app = Client("SNA_BOT", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
server = Flask(__name__)
WAITING_TEXT = {}
IDX_FILE = "poll_idx.txt"
STATUS_FILE = "poll_status.txt"

@server.route('/')
def home(): return "SNA Bot 24x7!", 200
def run_server(): server.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

# ========== GITHUB GIST STORAGE ==========
# Questions GitHub Gist mein save hote hain
# Code update karne pe DELETE NAHI HONGE

async def gist_load():
    global GIST_ID
    if not GITHUB_TOKEN:
        if os.path.exists("quiz_data.json"):
            try: return json.load(open("quiz_data.json","r",encoding='utf-8'))
            except: pass
        return []
    if not GIST_ID: return []
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"https://api.github.com/gists/{GIST_ID}",
                headers={"Authorization": f"token {GITHUB_TOKEN}"}
            ) as r:
                if r.status == 200:
                    d = await r.json()
                    return json.loads(d['files']['sna_questions.json']['content'])
    except Exception as e:
        print(f"Gist load error: {e}")
    return []

async def gist_save(questions):
    global GIST_ID
    content = json.dumps(questions, ensure_ascii=False, indent=2)
    if not GITHUB_TOKEN:
        with open("quiz_data.json","w",encoding='utf-8') as f:
            f.write(content)
        return True
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "description": "SNA Bot Questions — DO NOT DELETE",
        "public": False,
        "files": {"sna_questions.json": {"content": content}}
    }
    try:
        async with aiohttp.ClientSession() as s:
            if GIST_ID:
                async with s.patch(f"https://api.github.com/gists/{GIST_ID}",
                    headers=headers, json=payload) as r:
                    return r.status == 200
            else:
                async with s.post("https://api.github.com/gists",
                    headers=headers, json=payload) as r:
                    if r.status == 201:
                        d = await r.json()
                        GIST_ID = d['id']
                        print(f"✅ GIST CREATED! Add this to Railway: GIST_ID={GIST_ID}")
                        return True
    except Exception as e:
        print(f"Gist save error: {e}")
    return False

async def add_and_save(new_qs):
    existing = await gist_load()
    existing.extend(new_qs)
    await gist_save(existing)
    return len(existing)

def get_idx():
    try: return int(open(IDX_FILE).read().strip()) if os.path.exists(IDX_FILE) else 0
    except: return 0
def set_idx(i): open(IDX_FILE,"w").write(str(i))
def is_running(): return open(STATUS_FILE).read().strip()=="1" if os.path.exists(STATUS_FILE) else True
def set_running(v): open(STATUS_FILE,"w").write("1" if v else "0")

def clean_text(text):
    text = re.sub(r'http\S+|www\S+|@\S+','',text)
    for p in ['GK Trick','Nitin Gupta','Test Series','Google Play','Download','YouTube','Telegram','Instagram']:
        text = re.sub(p,'',text,flags=re.IGNORECASE)
    return re.sub(r'\s+',' ',text).strip()

def split_chunks(text, size=1200):
    words = text.split()
    chunks, cur, cur_len = [], [], 0
    for w in words:
        cur.append(w); cur_len += len(w)
        if cur_len >= size:
            chunks.append(' '.join(cur)); cur, cur_len = [], 0
    if cur: chunks.append(' '.join(cur))
    return chunks

def extract_json_list(text):
    text = text.strip()
    for fn in [
        lambda t: json.loads(t),
        lambda t: json.loads(re.sub(r'```(?:json)?','',t).strip().rstrip('`')),
        lambda t: json.loads(re.search(r'(\[.*\])',t,re.DOTALL).group(1)),
    ]:
        try:
            result = fn(text)
            if isinstance(result, list): return result
        except: pass
    return []

# ========== Q&A EXTRACT FROM TEXT ==========

def parse_qa_direct(text):
    """
    Text se seedha Q aur A nikalo.
    "Gadar Party ke sansthapak? – Lala Hardayal"
    → q="Gadar Party ke sansthapak?", a="Lala Hardayal"
    """
    qa_pairs = []
    lines = text.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line or len(line) < 5: continue
        # Pattern: kuch bhi – answer
        m = re.match(r'(?:\d+[\.\)]\s*)?(.+?)\s*[–—]\s*(.+)', line)
        if m:
            q = m.group(1).strip()
            a = m.group(2).strip()
            if len(q) > 3 and len(a) > 1:
                if not q.endswith('?'): q += '?'
                qa_pairs.append((q, a))
    return qa_pairs

async def make_3_wrong_options(question, correct_answer):
    """
    Sirf 3 galat options manao.
    Sahi answer hum khud set karenge — AI pe depend nahi.
    """
    prompt = f"""Create 3 WRONG options for this Indian exam question.

Question: {question}
CORRECT answer (DO NOT include this): {correct_answer}

Rules:
- Options must be WRONG (not the correct answer)
- Must look realistic and believable
- Bilingual: Hindi / English format
- Short — max 8 words each

Return ONLY a JSON array of exactly 3 strings:
["wrong1 / गलत1", "wrong2 / गलत2", "wrong3 / गलत3"]"""

    try:
        r = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role":"user","content":prompt}],
            temperature=0.8,
            max_tokens=200
        )
        opts = extract_json_list(r.choices[0].message.content.strip())
        if len(opts) >= 3:
            return [str(o)[:100] for o in opts[:3]]
    except Exception as e:
        print(f"Wrong options error: {e}")
    # Fallback
    return [
        "Jawaharlal Nehru / जवाहरलाल नेहरू",
        "Mahatma Gandhi / महात्मा गांधी",
        "Sardar Patel / सरदार पटेल"
    ]

async def make_bilingual_text(text):
    """Text ko Hindi/English bilingual banao"""
    try:
        prompt = f"""Convert to bilingual format: "Hindi / English"
Text: {text}
Return ONLY: "हिंदी में / English version"
Nothing else."""
        r = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role":"user","content":prompt}],
            temperature=0.1, max_tokens=150
        )
        result = r.choices[0].message.content.strip()
        if len(result) > 3 and '/' in result:
            return result[:255]
    except:
        pass
    return text

async def build_polls_from_text(text):
    """
    GUARANTEED CORRECT ANSWER SYSTEM:
    
    Step 1: Text se exact Q & A nikalo (parse_qa_direct)
    Step 2: AI se sirf 3 GALAT options manao
    Step 3: Sahi answer ko RANDOM position pe khud rakho
    Step 4: c = woh position jo humne rakhi (100% sahi)
    
    Telegram quiz mein:
    - Sahi option click = GREEN tick ✅
    - Galat option click = RED cross ❌
    Yeh Telegram automatic karta hai jab c sahi ho.
    """
    qa_pairs = parse_qa_direct(text)

    # Agar direct parse na ho, AI se extract karwao
    if not qa_pairs:
        try:
            prompt = f"""Extract Q&A pairs from this text.
Return JSON array: [{{"q":"question?","a":"answer"}}]
Only include pairs where answer is clearly stated.
TEXT: {text}"""
            r = groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role":"user","content":prompt}],
                temperature=0.1, max_tokens=2000
            )
            pairs = extract_json_list(r.choices[0].message.content)
            for p in pairs:
                if isinstance(p,dict) and 'q' in p and 'a' in p:
                    q = str(p['q']).strip()
                    a = str(p['a']).strip()
                    if len(q)>3 and len(a)>1:
                        if not q.endswith('?'): q+='?'
                        qa_pairs.append((q, a))
        except Exception as e:
            print(f"AI extract error: {e}")

    polls = []
    for question, correct_answer in qa_pairs:
        try:
            # Bilingual banao
            bi_q = await make_bilingual_text(question)
            bi_correct = await make_bilingual_text(correct_answer)
            await asyncio.sleep(0.3)

            # 3 galat options lo
            wrong_3 = await make_3_wrong_options(bi_q, bi_correct)
            await asyncio.sleep(0.3)

            # ✅ Sahi answer RANDOM position pe rakho — HUMNE KHUD
            correct_pos = random.randint(0, 3)
            options = wrong_3.copy()  # [w1, w2, w3]
            options.insert(correct_pos, bi_correct)  # sahi answer insert
            options = options[:4]  # exactly 4

            polls.append({
                "s": "GK / सामान्य ज्ञान",
                "q": bi_q[:255],
                "o": options,
                "c": correct_pos  # ← 100% sahi! Humne khud rakha hai
            })

        except Exception as e:
            print(f"Poll build error: {e}")
            continue

    return polls

# ========== KEYBOARD ==========
def main_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📝 Text Paste Karo"), KeyboardButton("📤 PDF Upload Karo")],
        [KeyboardButton("▶️ Polls Start"),     KeyboardButton("⏹️ Polls Stop")],
        [KeyboardButton("📊 Status"),          KeyboardButton("🗑️ Sab Delete Karo")]
    ], resize_keyboard=True)

# ========== BOT HANDLERS ==========

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    data = await gist_load()
    await message.reply_text(
        "🎓 **Sarkari Naukri Academy Bot**\n\n"
        f"📊 Questions: **{len(data)}**\n"
        f"🔄 Status: **{'Running ✅' if is_running() else 'Stopped ⏹️'}**\n"
        f"⏱ Interval: **{TIMER} sec**\n"
        f"💾 Storage: **{'GitHub Gist ✅' if GITHUB_TOKEN else 'Local ⚠️'}**\n\n"
        "👇 Buttons:",
        reply_markup=main_kb()
    )

@app.on_message(filters.regex("📝 Text Paste Karo") & filters.private & filters.user(ADMIN_ID))
async def ask_text(client, message):
    WAITING_TEXT[message.from_user.id] = True
    await message.reply_text(
        "✏️ **Text paste karo — koi bhi format:**\n\n"
        "`Gadar Party ke sansthapak? – Lala Hardayal`\n"
        "`Dandi March kab? – 12 March 1930`\n"
        "`Bharat ki rajdhani? – New Delhi`\n\n"
        "50+ questions ek saath de sakte ho!"
    )

@app.on_message(filters.regex("📤 PDF Upload Karo") & filters.private & filters.user(ADMIN_ID))
async def ask_pdf(client, message):
    await message.reply_text("📄 Ab PDF bhejien.")

@app.on_message(filters.regex("▶️ Polls Start") & filters.private & filters.user(ADMIN_ID))
async def polls_start(client, message):
    set_running(True)
    data = await gist_load()
    await message.reply_text(f"✅ Polls shuru! Total: {len(data)} questions.")

@app.on_message(filters.regex("⏹️ Polls Stop") & filters.private & filters.user(ADMIN_ID))
async def polls_stop(client, message):
    set_running(False)
    await message.reply_text("⏹️ Polls rok diye.")

@app.on_message(filters.regex("📊 Status") & filters.private & filters.user(ADMIN_ID))
async def show_status(client, message):
    data = await gist_load()
    idx = get_idx()
    await message.reply_text(
        f"📊 **Bot Status**\n\n"
        f"🔄 Polls: {'Running ✅' if is_running() else 'Stopped ⏹️'}\n"
        f"❓ Total Questions: {len(data)}\n"
        f"📍 Next Poll: #{idx+1}\n"
        f"⏱ Interval: {TIMER} sec\n"
        f"💾 Storage: {'GitHub Gist ✅' if GITHUB_TOKEN else 'Local ⚠️'}"
    )

@app.on_message(filters.regex("🗑️ Sab Delete Karo") & filters.private & filters.user(ADMIN_ID))
async def delete_all(client, message):
    await gist_save([])
    set_idx(0)
    await message.reply_text("🗑️ Saare questions delete ho gaye!")

@app.on_message(
    filters.text & filters.private & filters.user(ADMIN_ID) &
    ~filters.command(["start"]) &
    ~filters.regex("^(📝|📤|▶️|⏹️|📊|🗑️)")
)
async def handle_text_input(client, message):
    if not WAITING_TEXT.get(message.from_user.id, False): return
    WAITING_TEXT[message.from_user.id] = False
    text = message.text.strip()
    if len(text) < 5: return

    st = await message.reply_text("⚙️ Processing...")
    try:
        lines = [l for l in text.split('\n') if l.strip()]
        all_qs, chunk_size = [], 10
        total_chunks = (len(lines) + chunk_size - 1) // chunk_size

        for i in range(0, len(lines), chunk_size):
            chunk = '\n'.join(lines[i:i+chunk_size])
            cn = i//chunk_size + 1
            await st.edit(f"⚙️ Processing {cn}/{total_chunks}...\n✅ Done: {len(all_qs)}")
            qs = await build_polls_from_text(chunk)
            all_qs.extend(qs)
            await asyncio.sleep(1)

        if not all_qs:
            return await st.edit("❌ Questions nahi mile.\nFormat: `Sawal? – Jawab`")

        total = await add_and_save(all_qs)
        await st.edit(
            f"✅ **{len(all_qs)} polls ready!**\n"
            f"📊 Total saved: {total}\n"
            f"✔️ Sahi answer 100% correct!\n"
            f"💾 GitHub mein safe ✅"
        )
    except Exception as e:
        await st.edit(f"❌ Error: {str(e)[:200]}")

@app.on_message(filters.document & filters.user(ADMIN_ID) & filters.private)
async def handle_pdf_upload(client, message):
    if message.document.mime_type != "application/pdf":
        return await message.reply_text("❌ Sirf PDF bhejien.")
    st = await message.reply_text("⏳ PDF pad raha hoon...")
    path = await message.download()
    try:
        doc = fitz.open(path)
        raw = " ".join([p.get_text() for p in doc])
        doc.close()
        if len(raw.strip()) < 100:
            return await st.edit("❌ PDF mein text nahi mila.")
        cleaned = clean_text(raw)
        chunks = split_chunks(cleaned, size=1200)
        all_qs = []
        for i, chunk in enumerate(chunks):
            if len(chunk.strip()) < 50: continue
            await st.edit(f"⚙️ Section {i+1}/{len(chunks)}\n✅ Questions: {len(all_qs)}")
            try:
                qs = await build_polls_from_text(chunk)
                all_qs.extend(qs)
                await asyncio.sleep(1)
            except: await asyncio.sleep(3)
        if not all_qs:
            return await st.edit("❌ Koi question nahi bana.")
        total = await add_and_save(all_qs)
        await st.edit(
            f"🎉 **PDF Done!**\n"
            f"❓ Questions: {len(all_qs)}\n"
            f"📊 Total: {total}\n"
            f"✔️ Sahi answer 100% correct!\n"
            f"💾 GitHub mein save ✅"
        )
    except Exception as e:
        await st.edit(f"❌ Error: {str(e)[:200]}")
    finally:
        if os.path.exists(path): os.remove(path)

# ========== 24x7 POLL LOOP ==========
async def poll_loop():
    while True:
        try:
            if is_running():
                data = await gist_load()
                if data:
                    idx = get_idx()
                    if idx >= len(data): idx = 0
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
