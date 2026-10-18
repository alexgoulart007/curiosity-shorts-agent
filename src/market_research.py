"""Pesquisa de mercado: valida nichos com views de canais concorrentes.

Roda 1x por semana (workflow market-research.yml, domingo 23h BRT — logo apos
o analytics-update). Busca os canais concorrentes definidos em
COMPETITOR_CHANNELS, extrai views/titulo dos Shorts recentes de cada um,
classifica cada video em nicho (palavras-chave no titulo) e grava:

  analytics/market_weights.json -> pesos de nicho calibrados pelo MERCADO.

O _active_theme() do agent.py mistura estes pesos (~30%) com os pesos do
proprio canal (~70%). Dados proprios sempre pesam mais; mercado serve para
nichos novos entrarem com peso realista antes de terem 2+ videos proprios.
TEMA_SEMANA continua sendo prioridade absoluta (ignora tudo se definido).

Comportamento seguro:
  - So calcula peso para nicho com >= MIN_SAMPLES videos no mercado.
  - Pesos NORMALIZADOS (media do nicho / media geral * 15) — preserva
    proporcoes do mercado numa escala comparavel aos pesos do bot.
  - Se API falhar ou nenhum video classificado, nao grava nada (fallback
    silencioso: bot segue com pesos proprios).
  - Canais sem Shorts validos sao pulados com aviso no log.

Uso:
  python src/market_research.py [--videos-per-channel N]
"""
import argparse
import datetime
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent import THEMES, get_authenticated_service  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ANALYTICS_DIR = ROOT / "analytics"

# Canais concorrentes de curiosidades em PT-BR (handles do YouTube).
# Analisamos os Shorts recentes deles como termometro do mercado.
COMPETITOR_CHANNELS = [
    "vocesabia",           # Você Sabia? (~47M inscritos) — curiosidades/misterios
    "FatosDesconhecidos",  # Fatos Desconhecidos (~23M) — curiosidades classico
    "CienciaTodoDia",      # Ciência Todo Dia (~8M) — ciencia/espaco
    "MegaCurioso",         # Mega Curioso — curiosidades
    "fatoscuriosos_",      # Fatos Curiosos (~3M) — 99% Shorts, formato proximo
]

MIN_SAMPLES = 2        # videos minimos por nicho para gerar peso
MAX_VIDEOS_PER_CHANNEL = 50
BASE_MARKET_WEIGHT = 15  # ratio 1.0 (nicho na media do mercado) -> peso 15
MIN_WEIGHT = 1
MAX_WEIGHT = 40
SHORT_MAX_SECONDS = 60
SHORT_MIN_SECONDS = 3

# Keywords por nicho (PT) para classificar titulos dos concorrentes.
# Heuristica simples: tema com mais matches vence; sem match = descarta.
_THEME_KEYWORDS: dict[str, list[str]] = {
    "animais": [
        "animal", "cachorro", "gato", "tubarão", "tubarao", "peixe", "formiga",
        "aranha", "inseto", "pássaro", "passaro", "lobo", "urso", "leão", "leao",
        "elefante", "golfinho", "polvo", "cobra", "ave", "aves", "mamífero",
        "mamifero", "baleia", "dinossauro", "abelha", "vespa", "escorpião",
        "escorpiao", "sapo", "jacaré", "jacare", "tartaruga", "girafa",
        "canguru", "pinguim", "coruja", "águia", "aguia", "bicho", "fauna",
        "espécie", "especie", "predador", "venenoso", "raposa", "golfinho",
        "cavalo", "macaco", "gorila", "hipopótamo", "rinoceronte", "camaleão",
        "camaleao", "sardinha", "sardinha", "mergulho", "colmeia", "ninho",
    ],
    "espaco": [
        "espaço", "espaco", "espacial", "planeta", "estrela", "galáxia",
        "galaxia", "buraco negro", "astronauta", "lua", "marte", "satélite",
        "satelite", "cometa", "asteroide", "universo", "nasa", "órbita",
        "orbita", "nebulosa", "sistema solar", "cosmos", "cósmico", "cosmico",
        "foguete", "supernova", "constelação", "constelacao", "júpiter",
        "jupiter", "saturno", "venus", "mercurio", "netuno", "urano", "plutão",
        "estação espacial", "telescópio", "telescopio", "via láctea",
    ],
    "natureza": [
        "natureza", "oceano", "floresta", "montanha", "vulcão", "vulcao",
        "terremoto", "tsunami", "clima", "rio", "lago", "deserto", "ilha",
        "caverna", "cachoeira", "glaciar", "tempestade", "furacão", "furacao",
        "tornado", "mar", "praia", "selva", "bioma", "ecossistema", "fungo",
        "cogumelo", "planta", "árvore", "arvore", "flor", "coral", "areia",
        "geleira", "pantano", "mangue", "reflorestamento", "derretimento",
    ],
    "corpo humano": [
        "corpo humano", "cérebro", "cerebro", "coração", "coracao", "sangue",
        "osso", "ossos", "músculo", "musculo", "olho", "olhos", "dna",
        "célula", "celula", "células", "imunológico", "imunologico", "doença",
        "doenca", "vírus", "virus", "bactéria", "bacteria", "saúde", "saude",
        "cabeça", "cabeça", "pele", "cabelo", "dente", "anatomia", "organismo",
        "neurônio", "neuronio", "pulmão", "pulmao", "fígado", "figado",
        "estômago", "estomago", "intestino", "medula", "artéria", "arteria",
        "hormônio", "hormonio", "alergia", "câncer", "cancer", "infecção",
        "infeccao", "sangramento", "grávida", "gravida", "gêmeos", "gemeos",
        "dentro de você", "seu corpo", "humano", "pessoa", "acreditou",
    ],
    "tecnologia": [
        "tecnologia", "computador", "celular", "inteligência artificial",
        "inteligencia artificial", " robô", "robo", "robôs", "robos",
        "internet", "software", "invenção", "invencao", "inventou", "máquina",
        "maquina", "chip", "processador", "bateria", "smartphone", "app",
        "aplicativo", "código", "codigo", "programação", "programacao",
        "hacker", "cyber", "digital", "drone", "impressora 3d", "bluetooth",
        "wifi", "wi-fi", "nanotecnologia", "quântico", "quantico", "tela",
        "tela", "robôs", "carro", "tesla", "IA", "algoritmo", "filtro",
    ],
    "historia": [
        "história", "historia", "histórico", "guerra", "rei", "rainha",
        "império", "imperio", "antigo", "medieval", "faraó", "farao",
        "civilização", "civilizacao", "batalha", "século", "seculo",
        "dinastia", "imperador", "papa", "cruzada", "egito", "roma", "grega",
        "grego", "colonização", "colonizacao", "escravidão", "escravidao",
        "revolução", "revolucao", "mapa antigo", "ruínas", "ruinas",
        "pirâmide", "piramide", "múmia", "mumia", "castelo", "cavaleiro",
        "arqueólogo", "arqueologo", "artefato", "ditador", "império",
        "monarquia", "ditadura", "descobriu", "séculos", "antiga",
    ],
    "ciencia": [
        "ciência", "ciencia", "cientista", "experimento", "física", "fisica",
        "química", "quimica", "matemática", "matematica", "teoria", "átomo",
        "atomo", "energia", "pesquisa", "elemento", "molécula", "molecula",
        "reação", "reacao", "gravidade", "magnetismo", "eletricidade",
        "fórmula", "formula", "laboratório", "laboratorio", "estudo",
        "pesquisadores", "genoma", "partícula", "particula", "fóton", "foton",
        "elétron", "eletron", "fusão nuclear", "fusao nuclear", "físicos",
        "experimentos", "comprovado", "provado", "pesquisa", "estudos",
        "cientistas", "descoberta", "descobriram",
    ],
    "cultura": [
        "cultura", "filme", "música", "musica", "comida", "tradição",
        "tradicao", "língua", "lingua", "país", "pais", "cidade", "esporte",
        "jogo", "festa", "religião", "religiao", "deus", "santo", "mito",
        "lenda", "superstição", "supersticao", "signo", "zodíaco", "zodiaco",
        "astrologia", "natal", "carnaval", "halloween", "casamento", "nome",
        "origem do nome", "sobrenome", "receita", "prato", "bebida", "café",
        "cafe", "chocolate", "pizza", "sushi", "símbolo", "simbolo",
        "expressão", "expressao", "costume", "artesanato", "literatura",
    ],
}


def _normalize(text: str) -> str:
    """Remove acentos e caixa para matching robusto (tubarões -> tubaroes)."""
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _parse_duration_seconds(iso: str) -> int:
    m = re.match(r"PT(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)


def _classify_theme(title: str) -> str | None:
    """Heuristica: tema com mais keywords no titulo vence; sem match = None.
    Normaliza acentos, gera plurais (-ao -> -oes) e usa word boundaries
    (ex: 'ave' nao casa em 'caverna')."""
    title_norm = _normalize(title)
    scores: dict[str, int] = {}
    for theme, keywords in _THEME_KEYWORDS.items():
        score = 0
        for kw in keywords:
            kw_norm = _normalize(kw)
            variants = [kw_norm]
            if kw_norm.endswith("ao"):
                variants.append(kw_norm[:-2] + "oes")  # tubarao -> tubaroes
            if any(re.search(rf"\b{re.escape(v)}", title_norm) for v in variants):
                score += 1
        if score:
            scores[theme] = score
    if not scores:
        return None
    return max(scores, key=scores.get)


def _get_uploads_playlist(youtube, handle: str) -> str | None:
    resp = youtube.channels().list(forHandle=handle, part="contentDetails").execute()
    items = resp.get("items") or []
    if not items:
        return None
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def _fetch_channel_shorts(youtube, handle: str, limit: int) -> list[dict]:
    """Busca os Shorts recentes de um canal (titulo + views)."""
    playlist = _get_uploads_playlist(youtube, handle)
    if not playlist:
        print(f"     Aviso: canal '@{handle}' nao encontrado, pulando...")
        return []

    data = youtube.playlistItems().list(
        part="contentDetails", playlistId=playlist, maxResults=min(limit, 50),
    ).execute()
    ids = [it["contentDetails"]["videoId"] for it in data.get("items", [])]
    if not ids:
        return []

    shorts: list[dict] = []
    stats = youtube.videos().list(
        part="snippet,statistics,contentDetails", id=",".join(ids),
        maxResults=len(ids),
    ).execute()
    for item in stats.get("items", []):
        duration = _parse_duration_seconds(
            item.get("contentDetails", {}).get("duration", ""))
        if not (SHORT_MIN_SECONDS <= duration <= SHORT_MAX_SECONDS):
            continue
        st = item.get("statistics", {})
        shorts.append({
            "video_id": item["id"],
            "title": item["snippet"]["title"],
            "views": int(st.get("viewCount", 0)),
        })
    return shorts


def _compute_market_weights(per_theme: dict) -> dict:
    """Pesos NORMALIZADOS: media do nicho / media geral * BASE_MARKET_WEIGHT.

    Canais grandes tem views na casa dos milhoes — escala absoluta estouraria
    o limite de peso. A razao relativa entre nichos e o que importa.
    """
    avgs = {
        theme: sum(info["views"]) / info["count"]
        for theme, info in per_theme.items()
        if info["count"] >= MIN_SAMPLES and info["views"]
    }
    if not avgs:
        return {}
    overall = sum(avgs.values()) / len(avgs)
    weights = {}
    for theme, avg in avgs.items():
        ratio = avg / overall if overall else 1.0
        weights[theme] = max(MIN_WEIGHT, min(MAX_WEIGHT, round(ratio * BASE_MARKET_WEIGHT)))
    return weights


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--videos-per-channel", type=int, default=MAX_VIDEOS_PER_CHANNEL)
    args = parser.parse_args()

    print("[1/4] Autenticando no YouTube...")
    try:
        youtube = get_authenticated_service()
    except Exception as e:
        print(f"     ERRO na autenticacao: {e}")
        return 1

    print(f"[2/4] Analisando {len(COMPETITOR_CHANNELS)} canais concorrentes...")
    all_shorts: list[dict] = []
    for handle in COMPETITOR_CHANNELS:
        try:
            shorts = _fetch_channel_shorts(youtube, handle, args.videos_per_channel)
        except Exception as e:
            print(f"     Aviso: falha ao buscar '@{handle}' ({e}), pulando...")
            continue
        for s in shorts:
            s["channel"] = handle
        all_shorts += shorts
        print(f"     @{handle}: {len(shorts)} Shorts validos")
    print(f"     Total: {len(all_shorts)} Shorts coletados")

    if not all_shorts:
        print("     Nenhum Short coletado — nada gravado. Bot segue com pesos proprios.")
        return 0

    print("[3/4] Classificando titulos em nichos...")
    per_theme = {t: {"views": [], "count": 0} for t in THEMES}
    classified = 0
    for s in all_shorts:
        theme = _classify_theme(s["title"])
        if theme in per_theme:
            per_theme[theme]["views"].append(s["views"])
            per_theme[theme]["count"] += 1
            classified += 1
    print(f"     {classified}/{len(all_shorts)} videos classificados")

    print("[4/4] Calculando pesos de mercado (normalizados)...")
    weights = _compute_market_weights(per_theme)
    if not weights:
        print("     Nenhum nicho com amostra suficiente — nada gravado.")
        return 0

    ANALYTICS_DIR.mkdir(exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (ANALYTICS_DIR / "market_weights.json").write_text(
        json.dumps({
            "updated": now,
            "weights": weights,
            "channels": COMPETITOR_CHANNELS,
            "channels_analyzed": len([h for h in COMPETITOR_CHANNELS
                                      if any(s["channel"] == h for s in all_shorts)]),
            "videos_analyzed": len(all_shorts),
            "samples": {t: per_theme[t]["count"] for t in THEMES},
        }, ensure_ascii=False, indent=2),
        encoding="utf-8")

    for theme, info in sorted(per_theme.items(), key=lambda x: -x[1]["count"]):
        if info["count"]:
            avg = sum(info["views"]) / info["count"]
            print(f"     {theme}: {info['count']} videos, media {avg:,.0f} views -> peso {weights.get(theme, '-')}")
    print("     Pesos de mercado gravados em analytics/market_weights.json.")
    print("     O bot mistura ~30% mercado + ~70% dados proprios automaticamente.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
