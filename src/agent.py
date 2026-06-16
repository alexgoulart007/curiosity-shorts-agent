import os
import json
import asyncio
import random
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image
import requests
import wikipediaapi
from edge_tts import Communicate
from moviepy import (
    VideoFileClip,
    AudioFileClip,
    TextClip,
    CompositeVideoClip,
    CompositeAudioClip,
    AudioArrayClip,
    ColorClip,
    concatenate_audioclips,
    concatenate_videoclips,
)
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from dotenv import load_dotenv

load_dotenv()

def _get_ffmpeg() -> str:
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        return get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"

def _has_hdr(video_path: str) -> bool:
    """Detecta HDR via ffprobe ou inspecao do stderr do ffmpeg."""
    ffmpeg = _get_ffmpeg()
    probe = ffmpeg.replace("ffmpeg.exe", "ffprobe.exe").replace("ffmpeg", "ffprobe")
    if probe == ffmpeg:
        probe = "ffprobe"
    try:
        r = subprocess.run(
            [probe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=color_transfer",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=15
        )
        ct = r.stdout.strip()
        if ct in ("smpte2084", "arib-std-b67", "smpte428", "bt2020-10"):
            return True
        r2 = subprocess.run(
            [ffmpeg, "-i", video_path, "-f", "null", "-"],
            capture_output=True, text=True, timeout=15
        )
        stderr = r2.stderr
        if "Mastering Display Metadata" in stderr or "Content Light Level" in stderr:
            return True
    except Exception:
        pass
    return False


def _convert_hdr_to_sdr(video_path: str) -> str:
    """Se o video for HDR, transcodifica para SDR com tonemapping. Senao retorna original."""
    if not _has_hdr(video_path):
        return video_path
    cleaned = video_path.replace(".mp4", "_clean.mp4")
    if os.path.exists(cleaned):
        return cleaned
    ffmpeg = _get_ffmpeg()
    print(f"     HDR detectado em {video_path}, convertendo para SDR...")
    try:
        subprocess.run(
            [ffmpeg, "-i", video_path,
             "-vf", "tonemap=hable:desat=0",
             "-c:v", "libx264", "-preset", "fast", "-crf", "22",
             "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k",
             "-map_metadata", "-1", "-y", cleaned],
            capture_output=True, timeout=120
        )
        if os.path.exists(cleaned) and os.path.getsize(cleaned) > 0:
            print(f"     Conversao HDR->SDR OK: {cleaned}")
            return cleaned
    except Exception as e:
        print(f"     Aviso: falha na conversao HDR ({e})")
    return video_path

USED_TOPICS_FILE = Path("used_topics.json")

def load_used_topics() -> set[str]:
    if USED_TOPICS_FILE.exists():
        return set(json.loads(USED_TOPICS_FILE.read_text()))
    return set()

def save_used_topics(topics: set[str]):
    USED_TOPICS_FILE.write_text(json.dumps(list(topics)))

_used_topics: set[str] | None = None

TOPICS = [
    "Buraco negro", "Big Bang", "Sistema Solar", "Missão Apollo 11",
    "Estrela", "Exploração espacial",
    "Evolução humana", "DNA", "Fotossíntese",
    "Extinção dos dinossauros", "Baleia-azul", "Recifes de coral",
    "Animais em extinção", "Abelha",
    "Império Romano", "Civilização Maia", "Antigo Egito",
    "Pirâmides de Gizé", "Múmia", "Descobrimento do Brasil",
    "Cérebro humano", "Sistema imunológico", "Vacina",
    "Olho humano", "Coração (anatomia)",
    "Invenção do telefone", "História da internet",
    "Teoria da relatividade", "Eletricidade",
    "Aurora polar", "Tsunami", "Vulcão", "Terremoto",
    "Amazônia", "Fundo oceânico",
    "História do chocolate", "Mitologia grega",
    "Fóssil", "Fermentação", "Ciclo da água",
    "Guerra Fria", "Guerra dos Cem Anos",
    "Invenção da imprensa", "Revolução Francesa",
    "Seda", "Rota da Seda",
    "Como funciona o GPS", "Como funciona a internet",
    "Origem da música", "História do cinema",
    "Maior deserto do mundo", "Ilha mais remota do mundo",
    "Língua mais falada do mundo", "Animal mais rápido do mundo",
    "O que causa os sonhos", "Por que bocejamos",
    "Por que o céu é azul", "Como funcionam os terremotos",
    "Maior vulcão do mundo", "Fossa das Marianas",
    "Animais bioluminescentes", "Camuflagem dos animais",
    "Hibernação", "Migração dos animais",
    "Plantas carnívoras", "Cogumelos alucinógenos",
    "Idade Média", "Peste Negra",
    "Vikings", "Castelos medievais",
    "Cavalaria medieval", "Samurai",
    "Grandes Navegações", "Brasil Colônia",
    "Inconfidência Mineira", "Independência do Brasil",
    "Origem do Carnaval", "História do Futebol",
    "Origem do Universo", "Matéria escura",
    "Buraco de minhoca", "Viagem no tempo",
    "Clonagem", "CRISPR (edição genética)", "Células-tronco",
    "Robótica", "Inteligência Artificial", "Realidade virtual",
    "Primeiro computador", "Invenção do rádio", "Invenção da lâmpada",
    "Maior avião do mundo", "Trem mais rápido do mundo",
    "Muralha da China", "Machu Picchu", "Stonehenge",
    "Guerra de Tróia", "Catacumbas de Paris",
    "Maior tempestade já registrada", "Cachoeira mais alta do mundo",
    "Lago mais profundo do mundo", "Rio mais longo do mundo",
    "Polvo (inteligência)", "Ornitorrinco",
    "Lula-colossal", "Tubarão-baleia",
    "Açaí", "Café (origem)",
]

WIKI_LANG = "pt"
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]
YOUTUBE_TOKEN_FILE = "youtube_token.json"
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)
BG_MUSIC_DIR = Path("bg_music")
BG_MUSIC_DIR.mkdir(exist_ok=True)
MUSIC_BLACKLIST_FILE = Path("music_blacklist.json")

VOICES = ["pt-BR-AntonioNeural", "pt-BR-FranciscaNeural"]

COR_MARCA = "#FF6B00"
BG_MUSIC_VOLUME = 0.25

BG_MUSIC_URLS = [
    f"https://www.soundhelix.com/examples/mp3/SoundHelix-Song-{i}.mp3"
    for i in range(1, 18)  # Songs 1-17 available, 18+ do not exist
]

CHOSEN_MUSIC_LOG: list[str] = []

HOOKS = [
    "Você sabia que {topic} é tão fascinante que",
    "Isso vai mudar como você vê {topic}:",
    "Acredite se quiser: {topic} esconde um segredo",
    "Fato impressionante sobre {topic}:",
    "Você não vai acreditar no que {topic} revela:",
    "O que {topic} tem a ver com a sua vida?",
    "Pare tudo! {topic} é mais incrível do que parece:",
    "Se você acha que sabe sobre {topic}, espera até ouvir isso:",
    "Ninguém te contou a verdade sobre {topic}:",
    "{topic} — você nunca vai ouvir falar disso na escola:",
    "Se você gosta de {topic}, isso vai te surpreender:",
    "O segredo de {topic} que ninguém conta:",
    "A verdade chocante sobre {topic}:",
    "Prepare-se: {topic} não é o que você pensa:",
    "1 minuto sobre {topic} que vai mudar sua visão:",
    "Você subestima {topic} — veja por quê:",
    "A história de {topic} que você precisa conhecer:",
    "{topic}: o que a ciência diz vai te surpreender:",
    "Se você pudesse aprender algo sobre {topic} hoje, seria isso:",
    "O lado de {topic} que ninguém mostra:",
]

CTA_TEXTS = [
    "🔥 Esse fato explodiu! O que VOCÊ achou?",
    "💬 1.432 pessoas já viram. Comenta aí!",
    "👇 Essa curiosidade chocou geral. Inscreva-se!",
    "⚡ Fato aprovado por 9 em cada 10 inscritos! E você?",
    "🎯 Compartilha com alguém que precisa saber disso!",
    "👀 2.847 pessoas assistindo agora. Já se inscreveu?",
    "📢 Isso viralizou lá fora. O que você achou?",
    "💡 Fato novo todo dia às 9h. Ative o sininho!",
    "🚀 Esse conhecimento mudou minha vida. E a sua?",
    "🎬 Melhor curiosidade que você vai ver hoje!",
]


def _is_disambig(page) -> bool:
    title = page.title.lower()
    if "(desambiguação)" in title:
        return True
    summary = page.summary[:200].lower()
    return "página de desambiguação" in summary


def fetch_fact(max_retries: int = 10) -> tuple[str, str]:
    global _used_topics
    user_agent = "CuriosityShortsAgent/1.0 (github.com/user)"
    api = wikipediaapi.Wikipedia(user_agent, WIKI_LANG)

    if _used_topics is None:
        _used_topics = load_used_topics()
    available = [t for t in TOPICS if t not in _used_topics]
    if not available:
        _used_topics.clear()

    random.shuffle(available)
    selected = available[:max_retries]

    for topic in selected:
        page = api.page(topic)

        if not page.exists():
            continue
        if _is_disambig(page):
            continue

        summary = page.summary[:2000].strip()
        summary = re.sub(r'\s+', ' ', summary)

        if not summary or len(summary) < 80:
            continue

        if random.random() < 0.4:
            sections = [s for s in page.sections if s.text.strip() and len(s.text) > 100]
            if sections:
                section = random.choice(sections)
                summary = section.text[:2000].strip()
                summary = re.sub(r'\s+', ' ', summary)

        hook_template = random.choice(HOOKS)
        intro = hook_template.format(topic=topic) + "?"
        full_text = f"{intro}\n\n{summary}"
        _used_topics.add(topic)
        return topic, full_text

    return "curiosidades", "Você sabia que a curiosidade move o mundo? Cada pergunta abre uma porta para um novo conhecimento!"


TOPIC_QUERIES: dict[str, list[str]] = {
    "Buraco negro": ["black hole space", "space galaxy", "stars universe"],
    "Big Bang": ["universe explosion", "space galaxy", "cosmic"],
    "Sistema Solar": ["solar system planets", "space planets", "astronomy"],
    "Missão Apollo 11": ["apollo moon landing", "space rocket", "moon surface"],
    "Estrela": ["stars space", "night sky stars", "astronomy"],
    "Exploração espacial": ["space exploration", "rocket launch", "astronaut"],
    "Evolução humana": ["human evolution", "primates", "prehistoric"],
    "DNA": ["dna helix", "science laboratory", "microscope"],
    "Fotossíntese": ["photosynthesis plant", "sunlight leaves", "nature green"],
    "Extinção dos dinossauros": ["dinosaur fossil", "volcano eruption", "prehistoric"],
    "Baleia-azul": ["blue whale ocean", "whale underwater", "sea life"],
    "Recifes de coral": ["coral reef", "underwater ocean", "sea life"],
    "Animais em extinção": ["wildlife animals", "nature animals", "forest"],
    "Abelha": ["bee flower", "nature insect", "garden flowers"],
    "Império Romano": ["roman empire", "ancient rome ruins", "colosseum"],
    "Civilização Maia": ["mayan ruins", "ancient temple jungle", "mexico pyramid"],
    "Antigo Egito": ["ancient egypt", "egypt pyramid", "pharaoh"],
    "Pirâmides de Gizé": ["egypt pyramids", "giza pyramid desert", "ancient egypt"],
    "Múmia": ["egypt mummy", "ancient egypt tomb", "pyramid"],
    "Descobrimento do Brasil": ["portuguese ship ocean", "brazil discovery", "ocean sailing"],
    "Cérebro humano": ["human brain", "brain science", "neuroscience"],
    "Sistema imunológico": ["immune system cells", "blood cells", "microscope science"],
    "Vacina": ["vaccine injection", "science laboratory", "medical research"],
    "Olho humano": ["human eye", "eye closeup", "vision"],
    "Coração (anatomia)": ["human heart anatomy", "heart organ", "medical science"],
    "Invenção do telefone": ["vintage telephone", "old phone", "antique communication"],
    "História da internet": ["computer server", "technology data", "internet"],
    "Teoria da relatividade": ["einstein physics", "space time", "science experiment"],
    "Eletricidade": ["electricity lightning", "power lines", "energy spark"],
    "Aurora polar": ["aurora borealis", "northern lights", "night sky stars"],
    "Tsunami": ["ocean wave", "big wave sea", "storm ocean"],
    "Vulcão": ["volcano eruption", "lava mountain", "volcanic"],
    "Terremoto": ["earthquake destruction", "cracked ground", "natural disaster"],
    "Amazônia": ["amazon rainforest", "jungle river", "tropical forest"],
    "Fundo oceânico": ["deep ocean", "underwater sea", "ocean floor"],
    "História do chocolate": ["chocolate dessert", "cocoa beans", "chocolate factory"],
    "Mitologia grega": ["greek mythology", "ancient greece ruins", "greek temple"],
    "Fóssil": ["fossil excavation", "dinosaur bone", "archaeology dig"],
    "Fermentação": ["bread baking", "yeast fermentation", "microscope cells"],
    "Ciclo da água": ["water cycle", "rain river", "nature water"],
    "Guerra Fria": ["cold war military", "vintage army", "soviet"],
    "Guerra dos Cem Anos": ["medieval battle", "knight armor", "medieval fortress"],
    "Invenção da imprensa": ["old printing press", "vintage book", "library antique"],
    "Revolução Francesa": ["french revolution", "paris france", "historical painting"],
    "Seda": ["silk fabric", "luxury textile", "silk thread"],
    "Rota da Seda": ["silk road desert", "camel caravan", "ancient trade"],
    "Como funciona o GPS": ["gps navigation", "satellite orbit", "technology map"],
    "Como funciona a internet": ["data server", "internet network", "technology fiber"],
    "Origem da música": ["orchestra classical", "musical instruments", "piano violin"],
    "História do cinema": ["vintage movie camera", "old cinema", "film projector"],
    "Maior deserto do mundo": ["sahara desert", "sand dunes", "desert landscape"],
    "Ilha mais remota do mundo": ["tropical island", "remote beach", "ocean island"],
    "Língua mais falada do mundo": ["people talking", "world map", "globe earth"],
    "Animal mais rápido do mundo": ["cheetah running", "wildlife speed", "safari animal"],
    "O que causa os sonhos": ["dreaming sleep", "night sky", "person sleeping"],
    "Por que bocejamos": ["person yawning", "sleeping face", "tired person"],
    "Por que o céu é azul": ["blue sky clouds", "sunlight sky", "atmosphere"],
    "Como funcionam os terremotos": ["earthquake crack", "tectonic plates", "natural disaster"],
    "Maior vulcão do mundo": ["volcano eruption lava", "volcanic mountain", "nature disaster"],
    "Fossa das Marianas": ["deep ocean trench", "underwater deep sea", "ocean abyss"],
    "Animais bioluminescentes": ["bioluminescent ocean", "glowing jellyfish", "underwater light"],
    "Camuflagem dos animais": ["camouflage animal", "chameleon lizard", "wildlife nature"],
    "Hibernação": ["bear hibernating", "snow forest", "winter animal"],
    "Migração dos animais": ["birds flying", "animal migration", "wildlife herd"],
    "Plantas carnívoras": ["venus flytrap", "carnivorous plant", "nature green"],
    "Cogumelos alucinógenos": ["mushroom forest", "fungi nature", "colorful mushroom"],
    "Idade Média": ["medieval castle", "knight armor", "middle ages"],
    "Peste Negra": ["plague doctor", "medieval disease", "dark ages"],
    "Vikings": ["viking ship", "norse warrior", "viking fjord"],
    "Castelos medievais": ["medieval castle fortress", "old stone castle", "europe castle"],
    "Cavalaria medieval": ["knight horse armor", "medieval battle", "horse cavalry"],
    "Samurai": ["samurai warrior", "japanese sword", "japan temple"],
    "Grandes Navegações": ["old sailing ship", "ocean exploration", "portuguese ship"],
    "Brasil Colônia": ["colonial brazil", "historic portuguese", "old map"],
    "Inconfidência Mineira": ["brazil colonial mining", "historical ouro preto", "brazil history"],
    "Independência do Brasil": ["brazil independence", "brazil flag", "historic monument"],
    "Origem do Carnaval": ["carnival parade", "brazil carnival", "festival dance"],
    "História do Futebol": ["soccer football", "stadium crowd", "football game"],
    "Origem do Universo": ["universe big bang", "cosmic space", "stars galaxy"],
    "Matéria escura": ["dark matter space", "cosmic particles", "universe science"],
    "Buraco de minhoca": ["wormhole space", "time travel", "cosmic tunnel"],
    "Viagem no tempo": ["time travel concept", "clock science", "future technology"],
    "Clonagem": ["cloning science", "dna laboratory", "genetic research"],
    "CRISPR (edição genética)": ["gene editing dna", "scientist laboratory", "microscope research"],
    "Células-tronco": ["stem cells", "biological cells", "medical research"],
    "Robótica": ["robot technology", "artificial intelligence robot", "future tech"],
    "Inteligência Artificial": ["artificial intelligence", "ai robot", "neural network"],
    "Realidade virtual": ["virtual reality headset", "vr technology", "digital world"],
    "Primeiro computador": ["vintage computer", "old computer history", "retro technology"],
    "Invenção do rádio": ["vintage radio", "old radio antenna", "communication history"],
    "Invenção da lâmpada": ["vintage light bulb", "edison lamp", "old lighting"],
    "Maior avião do mundo": ["huge airplane", "massive aircraft", "jumbo jet"],
    "Trem mais rápido do mundo": ["high speed train", "bullet train", "modern railway"],
    "Muralha da China": ["great wall china", "chinese wall", "ancient china"],
    "Machu Picchu": ["machu picchu ruins", "andean mountains", "inca ruins"],
    "Stonehenge": ["stonehenge monument", "ancient stones", "megalithic"],
    "Guerra de Tróia": ["trojan horse", "ancient greek ruins", "epic battle"],
    "Catacumbas de Paris": ["catacombs paris", "underground tunnels", "skulls bones"],
    "Maior tempestade já registrada": ["huge storm clouds", "hurricane from space", "extreme weather"],
    "Cachoeira mais alta do mundo": ["tall waterfall", "angel falls", "mountain waterfall"],
    "Lago mais profundo do mundo": ["deep lake baikal", "frozen lake", "clear blue lake"],
    "Rio mais longo do mundo": ["amazon river", "nile river", "long river aerial"],
    "Polvo (inteligência)": ["octopus underwater", "octopus camouflage", "ocean creature"],
    "Ornitorrinco": ["platypus swimming", "platypus wildlife", "australian animal"],
    "Lula-colossal": ["giant squid deep sea", "colossal squid", "deep ocean creature"],
    "Tubarão-baleia": ["whale shark ocean", "giant shark underwater", "sea giant"],
    "Açaí": ["acai berry", "acai bowl", "amazon fruit"],
    "Café (origem)": ["coffee beans", "coffee plantation", "coffee farm"],
}

CATEGORY_FALLBACKS = {
    "space": ["space galaxy", "stars universe", "astronomy"],
    "nature": ["nature landscape", "wildlife animals", "forest"],
    "science": ["science laboratory", "microscope research", "technology"],
    "history": ["historical ruins", "ancient architecture", "old document"],
    "ocean": ["ocean waves", "underwater sea", "beach coast"],
    "weather": ["storm clouds", "nature sky", "dramatic landscape"],
    "people": ["people lifestyle", "person thinking", "crowd"],
}


def _get_category(topic: str) -> str:
    space = {"Buraco negro", "Big Bang", "Sistema Solar", "Missão Apollo 11",
             "Estrela", "Exploração espacial", "Aurora polar",
             "Origem do Universo", "Matéria escura", "Buraco de minhoca"}
    ocean = {"Baleia-azul", "Recifes de coral", "Fundo oceânico", "Fossa das Marianas",
             "Animais bioluminescentes", "Tsunami",
             "Polvo (inteligência)", "Lula-colossal", "Tubarão-baleia"}
    nature_set = {"Fotossíntese", "Amazônia", "Maior deserto do mundo", "Plantas carnívoras",
                  "Cogumelos alucinógenos", "Abelha", "Camuflagem dos animais",
                  "Hibernação", "Migração dos animais", "Animais em extinção",
                  "Animal mais rápido do mundo", "Maior vulcão do mundo",
                  "Maior tempestade já registrada", "Cachoeira mais alta do mundo",
                  "Lago mais profundo do mundo", "Rio mais longo do mundo",
                  "Ornitorrinco", "Açaí", "Café (origem)",
                  "Vulcão", "Terremoto", "Ilha mais remota do mundo"}
    science_set = {"DNA", "Cérebro humano", "Sistema imunológico", "Vacina",
                   "Olho humano", "Coração (anatomia)", "Teoria da relatividade",
                   "Eletricidade", "Fermentação", "Ciclo da água",
                   "Como funciona o GPS", "Como funciona a internet",
                   "O que causa os sonhos", "Por que bocejamos",
                   "Por que o céu é azul", "Como funcionam os terremotos",
                   "Viagem no tempo", "Clonagem", "CRISPR (edição genética)",
                   "Células-tronco", "Robótica", "Inteligência Artificial",
                   "Realidade virtual", "Primeiro computador"}
    history_set = {"Império Romano", "Civilização Maia", "Antigo Egito",
                   "Pirâmides de Gizé", "Múmia", "Descobrimento do Brasil",
                   "Invenção do telefone", "História da internet",
                   "História do chocolate", "Mitologia grega", "Fóssil",
                   "Guerra Fria", "Guerra dos Cem Anos", "Invenção da imprensa",
                   "Revolução Francesa", "Seda", "Rota da Seda",
                   "Origem da música", "História do cinema",
                   "Idade Média", "Peste Negra", "Vikings", "Castelos medievais",
                   "Cavalaria medieval", "Samurai", "Grandes Navegações",
                   "Brasil Colônia", "Inconfidência Mineira",
                   "Independência do Brasil", "Origem do Carnaval",
                   "História do Futebol", "Evolução humana",
                   "Extinção dos dinossauros",
                   "Invenção do rádio", "Invenção da lâmpada",
                   "Muralha da China", "Machu Picchu", "Stonehenge",
                   "Guerra de Tróia", "Catacumbas de Paris",
                   "Maior avião do mundo", "Trem mais rápido do mundo",
                   "Língua mais falada do mundo"}

    if topic in space: return "space"
    if topic in ocean: return "ocean"
    if topic in nature_set: return "nature"
    if topic in science_set: return "science"
    if topic in history_set: return "history"
    return "nature"


def _search_pexels(headers: dict, params: dict) -> list:
    try:
        resp = requests.get("https://api.pexels.com/videos/search",
                            headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("videos", [])
    except requests.exceptions.RequestException as e:
        print(f"     [Pexels] Erro HTTP: {e}")
        return []
    except json.JSONDecodeError as e:
        print(f"     [Pexels] Erro ao decodificar resposta: {e}")
        return []


def _apply_zoom(clip, zoom_max: float = 1.12):
    """Aplica zoom lento e progressivo de 1.0 ate zoom_max."""
    duration = clip.duration
    def make_frame(get_frame, t):
        progress = t / duration if duration > 0 else 0
        zoom = 1.0 + (zoom_max - 1.0) * progress
        frame = get_frame(t)
        img = Image.fromarray(frame)
        w, h = img.size
        new_w = int(w * zoom)
        new_h = int(h * zoom)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - w) // 2
        top = (new_h - h) // 2
        img = img.crop((left, top, left + w, top + h))
        return np.array(img)
    return clip.transform(make_frame)


def fetch_videos(topic: str, output_dir: Path, num_clips: int = 3) -> list[str]:
    headers = {"Authorization": PEXELS_API_KEY}
    base_params = {"per_page": 15, "orientation": "portrait", "min_duration": 10}

    queries = TOPIC_QUERIES.get(topic, [topic])

    category = _get_category(topic)
    fallbacks = CATEGORY_FALLBACKS.get(category, ["abstract"])

    all_videos = []
    for q in queries + fallbacks:
        params = {**base_params, "query": q}
        videos = _search_pexels(headers, params)
        good = [v for v in videos if v.get("duration", 0) >= 10 and v.get("width", 0) >= 720]
        if good:
            all_videos = good
            print(f"     Pexels: '{q}' -> {len(good)} videos")
            break
        if videos:
            all_videos = [v for v in videos if v.get("duration", 0) >= 10]

    if not all_videos:
        params = {**base_params, "query": "abstract"}
        all_videos = _search_pexels(headers, params)
    if not all_videos:
        print("     Aviso: nenhum video encontrado no Pexels")
        return []

    random.shuffle(all_videos)
    selected = all_videos[:num_clips]
    paths = []
    for i, video_data in enumerate(selected):
        hd_file = None
        for file in video_data.get("video_files", []):
            if file.get("quality") in ("hd", "sd") and file.get("width", 0) >= 720:
                hd_file = file
                break
        if not hd_file:
            files = video_data.get("video_files", [])
            if not files:
                print(f"     Aviso: video {i} sem arquivos, pulando...")
                continue
            hd_file = files[0]

        path = str(output_dir / f"stock_{i}.mp4")
        try:
            r = requests.get(hd_file["link"], timeout=30)
            r.raise_for_status()
        except Exception as e:
            print(f"     Aviso: falha ao baixar video {i} ({e}), pulando...")
            continue
        with open(path, "wb") as f:
            f.write(r.content)
        paths.append(path)

    print(f"     Baixados {len(paths)} clipes do Pexels")
    return paths


def load_music_blacklist() -> set[str]:
    if MUSIC_BLACKLIST_FILE.exists():
        return set(json.loads(MUSIC_BLACKLIST_FILE.read_text()))
    return set()

def save_music_blacklist(blacklist: set[str]):
    MUSIC_BLACKLIST_FILE.write_text(json.dumps(sorted(blacklist)))

def _generate_bg_music(duration: float, output_path: str = "bg_music/generated.mp3") -> str:
    Path("bg_music").mkdir(exist_ok=True)
    sr = 44100
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    melody = (
        np.sin(2 * np.pi * 261.63 * t) * 0.15
        + np.sin(2 * np.pi * 329.63 * t) * 0.10
        + np.sin(2 * np.pi * 392.00 * t) * 0.08
    )
    envelope = np.linspace(0.3, 0.1, len(t))
    audio = (melody * envelope * 32767).astype(np.int16)
    audio_clip = AudioArrayClip(audio.reshape(-1, 1), fps=sr)
    audio_clip.write_audiofile(output_path, logger=None)
    audio_clip.close()
    return output_path

def fetch_background_music(video_duration: float = 55.0) -> str | None:
    blacklist = load_music_blacklist()

    local_music = sorted(BG_MUSIC_DIR.glob("*.mp3"))
    local_available = [f for f in local_music if f.name not in blacklist]
    if local_available:
        chosen = random.choice(local_available)
        print(f"     Música local: {chosen.name}")
        CHOSEN_MUSIC_LOG.append(chosen.name)
        return str(chosen)

    available = [(url, name) for url in BG_MUSIC_URLS if (name := url.rsplit("/", 1)[-1]) not in blacklist]
    if available:
        url, name = random.choice(available)
        dest = BG_MUSIC_DIR / name
        if dest.exists():
            print(f"     Música: {name}")
            CHOSEN_MUSIC_LOG.append(name)
            return str(dest)
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            with open(dest, "wb") as f:
                f.write(r.content)
            print(f"     Música baixada: {name}")
            CHOSEN_MUSIC_LOG.append(name)
            return str(dest)
        except Exception as e:
            print(f"     Aviso: falha ao baixar {name} ({e})")

    print(f"     Todas as músicas na blacklist. Gerando música livre de direitos autorais...")
    try:
        return _generate_bg_music(video_duration)
    except Exception as e:
        print(f"     Aviso: não foi possível gerar música ({e})")
        return None


async def generate_audio(text: str, output_path: str):
    voice = os.getenv("TTS_VOICE", random.choice(VOICES))
    print(f"     Voz: {voice}")
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


def _extract_highlight(text: str) -> str | None:
    patterns = [
        r'(\d[\d.,]*\s*(trilhão|trilhões|bilhão|bilhões|milhão|milhões|mil|milhares|%|graus|km|kg|toneladas))',
        r'(\d[\d.,]*\s*(anos|dias|horas|metros|vezes))',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(0).upper()
    return None


def _make_highlight_clip(highlight: str, font_size: int = 76,
                         duration: float = 2.0, start: float = 0) -> TextClip:
    txt = make_text_clip(highlight, font_size=font_size, color=COR_MARCA,
                         stroke_color="black", stroke_width=4,
                         duration=duration)
    return txt.with_position(("center", 320)).with_start(start).with_duration(duration)


def create_short(video_paths: list[str], audio_path: str, text: str, output_path: str,
                 topic: str | None = None, bg_music_path: str | None = None):
    audio = AudioFileClip(audio_path)

    if bg_music_path:
        try:
            bg = AudioFileClip(bg_music_path)
            bg_samples = bg.to_soundarray(fps=44100)
            bg_low = AudioArrayClip(bg_samples * BG_MUSIC_VOLUME, fps=44100)
            bg_looped = concatenate_audioclips([bg_low] * max(1, int(audio.duration / bg.duration) + 1))
            bg_looped = bg_looped.subclipped(0, audio.duration)
            mixed = CompositeAudioClip([audio, bg_looped])
            bg.close()
        except Exception as e:
            print(f"     Aviso: erro ao mixar música ({e})")
            mixed = audio
    else:
        mixed = audio

    audio_duration = mixed.duration

    loaded = []
    for vp in video_paths:
        try:
            vp_prepared = _convert_hdr_to_sdr(vp)
            clip = VideoFileClip(vp_prepared)
            clip = _apply_zoom(clip)
            loaded.append(clip)
        except Exception as e:
            print(f"     Aviso: falha ao carregar {vp} ({e}), pulando clipe...")

    if not loaded:
        raise RuntimeError("Nenhum clipe de video pode ser carregado")

    video_comp = concatenate_videoclips(loaded)

    loops = max(1, int(audio_duration / video_comp.duration) + 1)
    video_comp = concatenate_videoclips([video_comp] * loops)
    video_comp = video_comp.subclipped(0, audio_duration)
    video_comp = video_comp.with_audio(mixed)
    video_comp = video_comp.resized(height=1920)
    video_comp = video_comp.cropped(x_center=video_comp.w / 2, y_center=video_comp.h / 2,
                                    width=1080, height=1920)

    hook_end = text.find("\n\n")
    hook_text = text[:hook_end] if hook_end > 0 else "Você sabia?"
    body_text = text[hook_end + 2:] if hook_end > 0 else text

    sentences = re.split(r'(?<=[.!?])\s+', body_text)

    HOOK_DURATION = 3.5
    COUNTDOWN_DURATION = 1.5
    CTA_DURATION = 2.5
    body_start = HOOK_DURATION + COUNTDOWN_DURATION
    body_duration = max(0, audio_duration - body_start - CTA_DURATION)
    seg_duration = body_duration / max(len(sentences), 1)

    txt_clips = []
    highlight_clips = []

    hook_txt = make_text_clip(hook_text, font_size=56, color=COR_MARCA,
                              stroke_color="black", stroke_width=3,
                              duration=HOOK_DURATION)
    hook_txt = hook_txt.with_position(("center", "center")).with_start(0).with_duration(HOOK_DURATION)
    txt_clips.append(hook_txt)

    countdown_txt = make_text_clip("3... 2... 1... ⚡", font_size=64, color=COR_MARCA,
                                   stroke_color="black", stroke_width=3,
                                   duration=COUNTDOWN_DURATION)
    countdown_txt = countdown_txt.with_position(("center", "center")) \
        .with_start(HOOK_DURATION).with_duration(COUNTDOWN_DURATION)
    txt_clips.append(countdown_txt)

    for i, sentence in enumerate(sentences):
        sentence = sentence.strip()
        if not sentence:
            continue
        txt = make_text_clip(sentence, font_size=50, duration=seg_duration)
        start = body_start + (i * seg_duration)
        txt = txt.with_position(("center", 1000)).with_start(start).with_duration(seg_duration)
        txt_clips.append(txt)

        highlight = _extract_highlight(sentence)
        if highlight:
            hl = _make_highlight_clip(highlight, duration=min(seg_duration, 2.5), start=start)
            highlight_clips.append(hl)

    txt_clips.extend(highlight_clips)

    cta_start = audio_duration - CTA_DURATION
    cta_text = random.choice(CTA_TEXTS)
    cta_txt = make_text_clip(cta_text, font_size=40, color=COR_MARCA,
                             stroke_color="black", stroke_width=3,
                             duration=CTA_DURATION)
    cta_txt = cta_txt.with_position(("center", "center")) \
        .with_start(cta_start).with_duration(CTA_DURATION)
    txt_clips.append(cta_txt)

    final = CompositeVideoClip([video_comp] + txt_clips)
    final.write_videofile(output_path, codec="libx264", audio_codec="aac", fps=24, logger=None)
    final.close()
    video_comp.close()
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
            creds = flow.run_local_server(port=0)
        with open(YOUTUBE_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def post_comment(youtube, video_id: str, text: str):
    try:
        youtube.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {"textOriginal": text}
                    }
                }
            }
        ).execute()
        print("     [OK] Comentario automatico postado!")
        return True
    except Exception as e:
        print(f"     [AVISO] Nao foi possivel postar comentario ({e})")
        return False


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
    video_id = response["id"]

    comments = [
        "Qual fato você quer ver amanhã? Comenta aqui! 👇",
        "Isso foi loucura! O que você achou? 🔥",
        "Compartilha com alguém que precisa saber disso! 💬",
    ]
    post_comment(youtube, video_id, random.choice(comments))

    return response


async def main():
    print("[1/4] Buscando fato curioso...")
    topic, fact = fetch_fact()
    print(f"     Tópico: {topic}")
    print(f"     Fato: {fact[:80]}...")

    title = f"{topic.upper()} #Shorts"
    tags = ["curiosidades", "vocesabia", "fatos", topic.replace(" ", ""), "conhecimento", "aprender"]
    description = (
        f"{fact}\n\n"
        f"---\n"
        f"👍 O que você achou desse fato? Comenta abaixo!\n"
        f"🔔 Inscreva-se para mais curiosidades todos os dias!\n\n"
        f"#curiosidades #vocesabia #fatos #{topic.replace(' ', '')} #conhecimento #shorts"
    )

    print("[2/4] Gerando áudio...")
    audio_path = str(OUTPUT_DIR / "audio.mp3")
    await generate_audio(fact, audio_path)

    print("[3/4] Buscando e editando vídeo...")
    video_paths = fetch_videos(topic, OUTPUT_DIR, num_clips=3)
    if not video_paths:
        print("     Aviso: sem videos do Pexels, pulando...")
        return

    print("     Buscando música de fundo...")
    bg_music = fetch_background_music()

    final_path = str(OUTPUT_DIR / "final.mp4")
    try:
        create_short(video_paths, audio_path, fact, final_path, topic, bg_music)
    except Exception as e:
        print(f"     ERRO ao criar video: {e}")
        return

    if not os.path.exists(final_path) or os.path.getsize(final_path) == 0:
        print("     ERRO: arquivo de video nao foi criado ou esta vazio")
        return

    print("[4/4] Fazendo upload para o YouTube...")
    result = upload_short(final_path, title, description, tags)
    print(f"     Upload OK! ID: {result['id']}")
    print(f"     Link: https://youtube.com/shorts/{result['id']}")

    if _used_topics:
        save_used_topics(_used_topics)

    if CHOSEN_MUSIC_LOG:
        print(f"     Música usada: {CHOSEN_MUSIC_LOG[-1]}")
        print(f"     Se houver claim de direitos autorais, adicione à blacklist:")
        print(f"     https://github.com/alexgoulart007/curiosity-shorts-agent/edit/main/music_blacklist.json")


if __name__ == "__main__":
    asyncio.run(main())
