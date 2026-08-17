import os
import json
import re
from datetime import datetime
import base64
from io import BytesIO

from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
from dotenv import load_dotenv

from google import genai
from google.genai import types

import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
import speech_recognition as sr
import asyncio
import edge_tts
from pydub import AudioSegment
from pydub.silence import detect_silence
import smtplib
from email.mime.text import MIMEText



app = Flask(__name__)
CORS(app)

load_dotenv()
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)
MODEL_NAME = "gemini-3.1-flash-lite"

SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS_PATH = os.getenv("GOOGLE_CREDS_PATH", "credentials/service_account.json")
CREDS = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, SCOPE)
gc = gspread.authorize(CREDS)
spreadsheet = gc.open("DivyaSree_Whispers_Of_The_Wind")

with open("prompts/system_prompt.txt", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()
active_chats = {}



VOICE_MAP = {
    "hindi": {"voice": "hi-IN-MadhurNeural", "rate": "+20%"},
    "english_indian": {"voice": "en-IN-PrabhatNeural", "rate": "+25%"},
    "english_us": {"voice": "en-US-AndrewMultilingualNeural", "rate": "+0%"},
    "english_uk": {"voice": "en-GB-RyanNeural", "rate": "+0%"},
}
DEFAULT_VOICE = VOICE_MAP["english_uk"]



STT_LANGUAGE_MAP = {
    "hindi": "hi-IN",
    "english_indian": "en-IN",
    "english_us": "en-US",
    "english_uk": "en-GB",
}
DEFAULT_STT_LANGUAGE = STT_LANGUAGE_MAP["english_uk"]

def resolve_stt_language(language_choice):
    key = (language_choice or "").strip().lower()
    if key in STT_LANGUAGE_MAP:
        return STT_LANGUAGE_MAP[key]
    if "hindi" in key:
        return STT_LANGUAGE_MAP["hindi"]
    if "us" in key:
        return STT_LANGUAGE_MAP["english_us"]
    if "uk" in key or "british" in key:
        return STT_LANGUAGE_MAP["english_uk"]
    if "indian" in key:
        return STT_LANGUAGE_MAP["english_indian"]
    return DEFAULT_STT_LANGUAGE

def convert_to_wav(input_path, output_path):
    audio = AudioSegment.from_file(input_path)
    audio.export(output_path, format="wav")
    return output_path

def transcribe(wav_path, language_choice=""):
    recognizer = sr.Recognizer()
    lang_code = resolve_stt_language(language_choice)

    with sr.AudioFile(wav_path) as source:
        audio_data = recognizer.record(source)

    try:
        return recognizer.recognize_google(audio_data, language=lang_code)
    except sr.UnknownValueError:
        return ""
    except sr.RequestError as e:
        print("STT request error:", e)
        return ""

def speech_to_text(raw_audio_path, session_id, language_choice=""):
    wav_path = f"static/audio/input_{session_id}.wav"
    convert_to_wav(raw_audio_path, wav_path)
    text = transcribe(wav_path, language_choice)
    os.remove(wav_path)
    return text


def format_list_for_sheet(items):
    if not items:
        return ""
    return "\n".join(f"- {item}" for item in items)

def log_call_data(call_data):
    name = call_data.get("name", "") or "Unknown"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    end_category = call_data.get("end_category", "")

    if end_category in ("Later_Calls_For_Confirmation", "Negative_Framing"):
        timing = call_data.get("reschedule_timing", "") or "NOT SAID"
        row = [timestamp, name, timing]

        spreadsheet.worksheet("Negative_Framing").append_row(row)

        if "FLAG_TO_BE_CHECKED" not in timing:
            spreadsheet.worksheet("Later_Calls_For_Confirmation").append_row(row)

    elif end_category in ("Qualified_Leads", "Non-Qualified_Leads"):
        questions = format_list_for_sheet(call_data.get("questions_asked", []))
        answers = format_list_for_sheet(call_data.get("answers_given", []))
        reason = call_data.get("reason", "")
        row = [timestamp, name, questions, answers, reason]
        spreadsheet.worksheet(end_category).append_row(row)

    else:
        print("Call not marked ended yet, or missing end_category:", repr(end_category))

PROJECT_DETAILS_TEXT = """
PROJECT OVERVIEW
Whispers of the Wind — Newly Launched Premium Private Valley Plots
Location: Nandi Hills, Heggadihalli Village, Doddaballapura Taluk, Bengaluru Rural, Pincode 562110
Total Extent: 38 Acres | 207 luxury villa plots
Plot Sizes: 1,200 to 4,000 sq. ft.
RERA Registered: Yes (RERA No. PRM/KA/RERA/1250/301/PR/070525/007718)
Possession: Last date to possess — December 31, 2029

PRICING
Starting from Rs. 92.4 Lakh to Rs. 3.08 Cr (inclusive of taxes)
Base price: approx. Rs. 7,700 per sq. ft.
  1,200 sq.ft. — Rs. 92.4 Lakh
  1,800 sq.ft. — Rs. 1.39 Cr
  2,003 sq.ft. — Rs. 1.54 Cr
  2,400 sq.ft. — Rs. 1.85 Cr
  3,199 sq.ft. — Rs. 2.46 Cr
  4,000 sq.ft. — Rs. 3.08 Cr

SITE INFRASTRUCTURE
- Electrical supply from 4 KVA onwards (as per KERC guidelines, based on plot size)
- Gravity-fed water system from a central ground-level reservoir
- STP-treated water for landscaping and irrigation
- Percolation pits integrated into stormwater drainage
- Concrete paver roads and pedestrian pathways
- LED street lighting throughout

AMENITIES
- 20,000+ sq. ft. clubhouse, swimming pool, indoor games room, gymnasium
- Badminton courts, library & lounge, yoga deck, mini-theatre
- Multipurpose hall, party deck, spa & salon, business centre
- EV charging stations, cycle stacking zone, curated restaurant
- Skating rink, futsal court, pickleball & putt-putt golf
- Five themed parks with eco-trails, biker pods, sound sculptures & arrival plaza

KEY CONNECTIVITY
- Kempegowda International Airport — 14 km / 20 mins
- Nandi Hills — 6 km / 10 mins
- Devanahalli Business Park — 15 km / 25 mins
- Stonehill International School — 29 km / 40 mins
- Akash Hospital, Devanahalli — 13 km / 25 mins
- Aerospace SEZ & Hardware Park — 12-15 km / 20-25 mins
- RMZ Galleria Mall, Yelahanka — 32 km / 45 mins

ABOUT DIVYASREE DEVELOPERS
Founded in 1997 and headquartered in Bengaluru, Divyasree Developers has over two decades of
experience delivering residential, commercial, and IT infrastructure projects across South India.
Led by Mr. Bhaskar Bhat, the group is known for timely delivery, customer-centricity, and green
architecture, with landmark developments including Divyasree Republic of Whitefield,
Divyasree 77 Degree Place, and Divyasree Technopark.
"""

def send_confirmation_email(to_email, customer_name):
    if not to_email:
        return
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {"accept": "application/json", "api-key": BREVO_API_KEY, "content-type": "application/json"}
    intro = (f"Hi {customer_name or 'there'},\n\n"
             "Thank you for your time today. Our property expert will reach out shortly to discuss "
             "financing, options, and next steps.\n\nHere are the full details of Whispers of the Wind "
             "for your reference:\n")
    body = intro + PROJECT_DETAILS_TEXT + "\nWarm regards,\nSwetha\nDivyasree Developers"
    payload = {
        "sender": {"email": EMAIL_ADDRESS, "name": "Swetha - Divyasree Developers"},
        "to": [{"email": to_email}],
        "subject": "Divyasree Whispers of the Wind — Thank You & Project Details",
        "textContent": body
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        print("Brevo status:", response.status_code)
        print("Brevo response:", response.text)
    except Exception as e:
        print("Email send error:", e)


def get_or_create_chat(session_id):
    if session_id not in active_chats:
        active_chats[session_id] = client.chats.create(
            model=MODEL_NAME,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                thinking_config=types.ThinkingConfig(thinking_level="minimal")
            )
        )
    return active_chats[session_id]



def start_call(session_id):
    chat = get_or_create_chat(session_id)
    response = chat.send_message("[CALL_TRIGGER: START_CALL]")
    return response.text



def extract_call_data(full_reply_text):
    match = re.search(r"<CALL_DATA>(.*?)</CALL_DATA>", full_reply_text, re.DOTALL)

    if match:
        spoken_text = full_reply_text[:match.start()].strip()
        json_text = match.group(1).strip()
        try:
            call_data = json.loads(json_text)
        except json.JSONDecodeError:
            call_data = {}
    else:
        spoken_text = full_reply_text.strip()
        call_data = {}

    return spoken_text, call_data


PRONUNCIATION_MAP = {
    "Divyasree": "Divya-shree",
    "Nandi": "None-thee",
    "Bengaluru": "Ben-gha-loo-roo",
    "Bangalore": "Ben-gha-loo-roo",
    "Heggadihalli": "Heg-gha-dha-ha-llee",
    "Doddaballapura": "Though-the-bhal-lla-poo-raa",
    "Doddaballapur": "Though-the-bhal-lla-poor",
    "Taluk": "Thaa-look",
    "Kempegowda": "Khem -peg-go-dhaa",
    "Devanahalli": "They-vah-nah-hal-lee",
    "Lakh": "Lak",
    "Crore": "Cro"
}

def apply_pronunciation_fixes(text):
    for word, phonetic in PRONUNCIATION_MAP.items():
        text = re.sub(rf"\b{re.escape(word)}\b", phonetic, text, flags=re.IGNORECASE)
    return text


def cap_pause_length_bytes(audio_bytes, max_pause_ms=1000, padding_ms=150):
    audio = AudioSegment.from_file(BytesIO(audio_bytes), format="mp3")
    silence_ranges = detect_silence(audio, min_silence_len=500, silence_thresh=-45)

    out_buffer = BytesIO()
    if not silence_ranges:
        audio.export(out_buffer, format="mp3")
        return out_buffer.getvalue()

    output = AudioSegment.empty()
    prev_end = 0
    for start, end in silence_ranges:
        safe_cut_point = min(start + padding_ms, end)
        output += audio[prev_end:safe_cut_point]
        gap_len = max(min(end - safe_cut_point, max_pause_ms), 0)
        output += AudioSegment.silent(duration=gap_len)
        prev_end = end
    output += audio[prev_end:]

    output.export(out_buffer, format="mp3")
    return out_buffer.getvalue()


def resolve_voice(language_choice):
        key = (language_choice or "").strip().lower()
        if key in VOICE_MAP:
            return VOICE_MAP[key]
        if "hindi" in key:
            return VOICE_MAP["hindi"]
        if "us" in key:
            return VOICE_MAP["english_us"]
        if "uk" in key or "british" in key:
            return VOICE_MAP["english_uk"]
        if "indian" in key:
            return VOICE_MAP["english_indian"]
        return DEFAULT_VOICE

def speak(text, language_choice=""):
    voice_config = resolve_voice(language_choice)
    voice = voice_config["voice"]
    rate = voice_config["rate"]
    text = apply_pronunciation_fixes(text)
    text = re.sub(r'(?<=\w)-(?=\w)', ' ', text)

    async def synthesize():
        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
        audio_bytes = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_bytes.extend(chunk["data"])
        return bytes(audio_bytes)

    raw_audio = asyncio.run(synthesize())
    return cap_pause_length_bytes(raw_audio)



@app.route("/")
def home():
    return render_template("index.html")

@app.route("/start", methods=["POST"])
def start():
    session_id = request.json.get("session_id")
    opening_reply = start_call(session_id)
    spoken, data = extract_call_data(opening_reply)
    audio_bytes = speak(spoken, data.get("language_choice", ""))
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    return jsonify({"text": spoken, "audio_base64": audio_b64, "call_data": data})

@app.route("/talk", methods=["POST"])
def talk():
    session_id = request.form.get("session_id")
    language_choice = request.form.get("language_choice", "")
    audio_file = request.files["audio"]

    raw_path = f"static/audio/raw_{session_id}.webm"
    audio_file.save(raw_path)
    user_text = speech_to_text(raw_path, session_id, language_choice)
    os.remove(raw_path)

    chat = get_or_create_chat(session_id)
    reply = chat.send_message(user_text if user_text else "[No speech detected]")
    spoken, data = extract_call_data(reply.text)

    audio_bytes = speak(spoken, data.get("language_choice", ""))
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

    if data.get("call_ended"):
        log_call_data(data)
        if data.get("email_stage") == "confirmed" and data.get("email"):
            send_confirmation_email(data.get("email"), data.get("name"))

    return jsonify({
        "user_text": user_text, "text": spoken,
        "audio_base64": audio_b64, "call_data": data
    })

if __name__ == "__main__":
    app.run(port=8000, debug=True)