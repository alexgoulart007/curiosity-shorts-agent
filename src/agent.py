import os
import json
import asyncio
import random
import re
from pathlib import Path

import requests
import wikipediaapi
from edge_tts import Communicate
from moviepy import (
    VideoFileClip,
    AudioFileClip,
    TextClip,
    CompositeVideoClip,
    concatenate_videoclips,
)
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from dotenv import load_dotenv

load_dotenv()

TOPICS = [
    "curiosidades", "ciência", "história do mundo", "tecnologia",
    "natureza", "astronomia", "animais", "geografia",
    "invenções", "corpo humano", "biologia", "física",
    "química", "medicina", "arte", "música", "filosofia",
    "psicologia", "economia", "arqueologia", "paleontologia",
    "geologia", "oceanografia", "mitologia", "gastronomia",
    "esporte", "cinema", "literatura",
]

WIKI_LANG = "pt"
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
YOUTUBE_TOKEN_FILE = "youtube_token.json"
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


HOOKS = [
    "Você sabia que", "Isso vai te surpreender:", "Acredite se quiser:",
    "Fato impressionante:", "Você não vai acreditar:",
    "O que será que acontece quando", "Sabia que",
]


def _is_disambig(page) -> bool:
    title = page.title.lower()
    if "(desambiguação)" in title:
        return True
    summary = page.summary[:200].lower()
    return "página de desambiguação" in summary


def fetch_fact(max_retries: int = 5) -> tuple[str, str]:
    user_agent = "CuriosityShortsAgent/1.0 (github.com/user)"
    api = wikipediaapi.Wikipedia(user_agent, WIKI_LANG)

    shuffled = TOPICS[:]
    random.shuffle(shuffled)
    selected = shuffled[:max_retries]

    for topic in selected:
        page = api.page(topic)

        if not page.exists():
            continue
        if _is_disambig(page):
            continue

        summary = page.summary[:600].strip()
        summary = re.sub(r'\s+', ' ', summary)

        if not summary or len(summary) < 80:
            continue

        if random.random() < 0.3:
            sections = [s for s in page.sections if s.text.strip() and len(s.text) > 100]
            if sections:
                section = random.choice(sections)
                summary = section.text[:600].strip()
                summary = re.sub(r'\s+', ' ', summary)

        hook = random.choice(HOOKS)
        intro = f"{hook} {topic}?"
        full_text = f"{intro}\n\n{summary}"
        return topic, full_text

    return "curiosidades", "Você sabia que a curiosidade move o mundo? Cada pergunta abre uma porta para um novo conhecimento!"


def fetch_video(query: str, output_path: str, per_page: int = 5) -> str | None:
    url = "https://api.pexels.com/videos/search"
    headers = {"Authorization": PEXELS_API_KEY}
    params = {"query": query, "per_page": per_page, "orientation": "portrait", "min_duration": 10}

    resp = requests.get(url, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if not data.get("videos"):
        params["query"] = "abstract"
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

    if not data.get("videos"):
        return None

    videos = [v for v in data["videos"] if v.get("duration", 0) >= 10 and v.get("width", 0) >= 720]
    if not videos:
        videos = data["videos"]
    video = random.choice(videos)
    hd_file = None
    for file in video.get("video_files", []):
        if file.get("quality") in ("hd", "sd") and file.get("width", 0) >= 720:
            hd_file = file
            break
    if not hd_file:
        hd_file = video["video_files"][0]

    link = hd_file["link"]
    r = requests.get(link, timeout=30)
    with open(output_path, "wb") as f:
        f.write(r.content)

    return output_path


async def generate_audio(text: str, output_path: str):
    voice = os.getenv("TTS_VOICE", "pt-BR-AntonioNeural")
    communicate = Communicate(text, voice)
    await communicate.save(output_path)


def make_text_clip(text: str, font_size: int, color: str = "white",
                   stroke_color: str = "black", stroke_width: int = 3,
                   size: tuple = (900, None), duration: float = 3) -> TextClip:
    return TextClip(
        text=text,
        font=os.getenv("VIDEO_FONT", "Arial"),
        font_size=font_size,
        color=color,
        stroke_color=stroke_color,
        stroke_width=stroke_width,
        text_align="center",
        size=size,
        method="caption",
    )


def create_short(video_path: str, audio_path: str, text: str, output_path: str, topic: str):
    video = VideoFileClip(video_path)
    audio = AudioFileClip(audio_path)
    audio_duration = audio.duration

    max_loops = max(1, int(audio_duration / video.duration) + 1)
    clips = [video] * max_loops
    video_looped = concatenate_videoclips(clips)
    video_looped = video_looped.subclipped(0, audio_duration)
    video_looped = video_looped.with_audio(audio)
    video_looped = video_looped.resized(height=1920)
    video_looped = video_looped.cropped(x_center=video_looped.w / 2, y_center=video_looped.h / 2, width=1080, height=1920)

    hook_end = text.find("\n\n")
    hook_text = text[:hook_end] if hook_end > 0 else "Você sabia?"
    body_text = text[hook_end + 2:] if hook_end > 0 else text

    sentences = re.split(r'(?<=[.!?])\s+', body_text)
    body_duration = audio_duration - 3.5 - 2.5
    seg_duration = body_duration / max(len(sentences), 1)

    txt_clips = []

    hook_txt = make_text_clip(hook_text, font_size=56, color="#FFD700",
                               stroke_color="black", stroke_width=3,
                               duration=3.5)
    hook_txt = hook_txt.with_position(("center", "center")).with_start(0).with_duration(3.5)
    txt_clips.append(hook_txt)

    for i, sentence in enumerate(sentences):
        sentence = sentence.strip()
        if not sentence:
            continue
        txt = make_text_clip(sentence, font_size=50, duration=seg_duration)
        start = 3.5 + (i * seg_duration)
        txt = txt.with_position(("center", "center")).with_start(start).with_duration(seg_duration)
        txt_clips.append(txt)

    cta_start = audio_duration - 2.5
    cta_txt = make_text_clip("Gostou? Inscreva-se! 🔔", font_size=44, color="#FF4444",
                              stroke_color="black", stroke_width=3,
                              duration=2.5)
    cta_txt = cta_txt.with_position(("center", "center")).with_start(cta_start).with_duration(2.5)
    txt_clips.append(cta_txt)

    final = CompositeVideoClip([video_looped] + txt_clips)
    final.write_videofile(output_path, codec="libx264", audio_codec="aac", fps=24, logger=None)
    final.close()
    video.close()
    audio.close()


def get_authenticated_service():
    creds = None
    if os.path.exists(YOUTUBE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(YOUTUBE_TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
            creds = flow.run_local_server(port=8080)
        with open(YOUTUBE_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def upload_short(file_path: str, title: str, description: str, tags: list[str] | None = None):
    youtube = get_authenticated_service()
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags or [],
            "categoryId": "27",
        },
        "status": {
            "privacyStatus": os.getenv("VIDEO_PRIVACY", "public"),
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(file_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    return response


async def main():
    print("[1/4] Buscando fato curioso...")
    topic, fact = fetch_fact()
    print(f"     Tópico: {topic}")
    print(f"     Fato: {fact[:80]}...")

    title = f"{topic.upper()} 🧠 Curiosidade #{(random.randint(1000, 9999))}"
    tags = ["curiosidades", "vocesabia", "fatos", topic, "conhecimento", "aprender"]
    description = (
        f"{fact}\n\n"
        f"---\n"
        f"👍 Gostou? Deixa seu like e inscreva-se para mais curiosidades!\n"
        f"🔔 Ative o sininho para não perder nenhum vídeo\n\n"
        f"#curiosidades #vocesabia #fatos #{topic} #conhecimento"
    )

    print("[2/4] Gerando áudio...")
    audio_path = str(OUTPUT_DIR / "audio.mp3")
    await generate_audio(fact[:500], audio_path)

    print("[3/4] Buscando e editando vídeo...")
    video_path = str(OUTPUT_DIR / "stock.mp4")
    fetch_video(topic, video_path)

    final_path = str(OUTPUT_DIR / "final.mp4")
    create_short(video_path, audio_path, fact, final_path, topic)

    print("[4/4] Fazendo upload para o YouTube...")
    result = upload_short(final_path, title, description, tags)
    print(f"     Upload OK! ID: {result['id']}")
    print(f"     Link: https://youtube.com/shorts/{result['id']}")


if __name__ == "__main__":
    asyncio.run(main())
