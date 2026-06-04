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
    "curiosidades", "ciência", "história", "tecnologia",
    "natureza", "espaço", "animais", "geografia",
    "invenções", "corpo humano", "curiosidades históricas",
]

WIKI_LANG = "pt"
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
YOUTUBE_TOKEN_FILE = "youtube_token.json"
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


def fetch_fact() -> str:
    user_agent = "CuriosityShortsAgent/1.0 (github.com/user)"
    api = wikipediaapi.Wikipedia(user_agent, WIKI_LANG)

    topic = random.choice(TOPICS)
    page = api.page(topic)

    if not page.exists():
        return "Você sabia que a Wikipédia tem milhões de artigos? Pois é, aprenda algo novo todo dia!"

    summary = page.summary[:600].strip()
    summary = re.sub(r'\s+', ' ', summary)

    if random.random() < 0.3:
        sections = [s for s in page.sections if s.text.strip()]
        if sections:
            section = random.choice(sections)
            summary = section.text[:600].strip()
            summary = re.sub(r'\s+', ' ', summary)

    return summary if summary else "Fato interessante não encontrado. Tente novamente!"


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

    video = random.choice(data["videos"])
    hd_file = None
    for file in video.get("video_files", []):
        if file.get("quality") in ("hd", "sd") and file.get("width", 0) >= 360:
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


def create_short(video_path: str, audio_path: str, text: str, output_path: str):
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

    sentences = re.split(r'(?<=[.!?])\s+', text)
    seg_duration = audio_duration / max(len(sentences), 1)

    txt_clips = []
    for i, sentence in enumerate(sentences):
        sentence = sentence.strip()
        if not sentence:
            continue
        txt = TextClip(
            text=sentence,
            font="Arial",
            font_size=48,
            color="white",
            stroke_color="black",
            stroke_width=2,
            text_align="center",
            size=(900, None),
            method="caption",
        )
        start = i * seg_duration
        txt = txt.with_position(("center", "center")).with_start(start).with_duration(seg_duration)
        txt_clips.append(txt)

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
    fact = fetch_fact()
    print(f"     Fato: {fact[:80]}...")

    title = f"Você sabia? 🧠 #{random.randint(1000, 9999)}"
    description = f"{fact}\n\nInscreva-se para mais curiosidades! 🧠\n#curiosidades #vocesabia #fatos"

    print("[2/4] Gerando áudio...")
    audio_path = str(OUTPUT_DIR / "audio.mp3")
    await generate_audio(fact[:500], audio_path)

    print("[3/4] Buscando e editando vídeo...")
    video_path = str(OUTPUT_DIR / "stock.mp4")
    query_words = fact.split()[:3]
    query = " ".join(query_words)
    fetch_video(query, video_path)

    final_path = str(OUTPUT_DIR / "final.mp4")
    create_short(video_path, audio_path, fact, final_path)

    print("[4/4] Fazendo upload para o YouTube...")
    result = upload_short(final_path, title, description)
    print(f"     Upload OK! ID: {result['id']}")
    print(f"     Link: https://youtube.com/shorts/{result['id']}")


if __name__ == "__main__":
    asyncio.run(main())
