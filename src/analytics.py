"""Feedback loop de analytics do Curiosity Shorts Agent.

Roda 1x por semana (workflow analytics-update.yml). Le as estatisticas reais
dos videos do canal (views/likes/comments), cruza com o registro de publicacoes
(`published_videos.json` preenchido em cada upload) e recalcula:

  1. analytics/nicho_weights.json  -> pesos de nicho por media de views real
     (usado por _active_theme() no agent.py; cada ponto ~= 12 views de media).
  2. analytics/title_bias.json     -> estilo de titulo vencedor (pergunta vs
     afirmacao), injetado no prompt de _generate_seo_title().

Comportamento seguro:
  - So reajusta um nicho com >= MIN_SAMPLES videos; os demais ficam com o peso padrao.
  - Pesos limitados a [MIN_WEIGHT, MAX_WEIGHT] (nenhum nicho zera de vez).
  - Sem o escopo youtube.readonly no token, aborta com instrucao clara (nao publica nada).

Uso:
  python src/analytics.py [--limit N]
"""
import argparse
import datetime
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent import THEMES, get_authenticated_service  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PUBLISHED_FILE = ROOT / "published_videos.json"
ANALYTICS_DIR = ROOT / "analytics"

MIN_SAMPLES = 2      # videos minimos por nicho/estilo para reajustar
MAX_VIDEOS = 60      # janela de videos analisados
DEFAULT_WEIGHTS = {
    "tecnologia": 30,
    "natureza": 25,
    "animais": 22,
    "espaco": 12,
    "cultura": 4,
    "corpo humano": 3,
    "historia": 4,
    "ciencia": 4,
}
MIN_WEIGHT = 1
MAX_WEIGHT = 40
VIEWS_PER_WEIGHT_POINT = 12


def _get_uploads_playlist(youtube) -> str:
    resp = youtube.channels().list(part="contentDetails", mine=True).execute()
    return resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]


def _fetch_recent_videos(youtube, limit: int) -> list[dict]:
    """Lista os videos mais recentes do canal com estatisticas basicas."""
    playlist = _get_uploads_playlist(youtube)
    items: list[dict] = []
    page_token = None
    while len(items) < limit:
        params = {
            "part": "contentDetails",
            "playlistId": playlist,
            "maxResults": 50,
        }
        if page_token:
            params["pageToken"] = page_token
        data = youtube.playlistItems().list(**params).execute()
        items += data["items"]
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    ids = [it["contentDetails"]["videoId"] for it in items[:limit]]
    if not ids:
        return []

    videos: list[dict] = []
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        stats = youtube.videos().list(
            part="snippet,statistics", id=",".join(batch),
            maxResults=len(batch),
        ).execute()
        for item in stats.get("items", []):
            st = item.get("statistics", {})
            videos.append({
                "video_id": item["id"],
                "title": item["snippet"]["title"],
                "published_at": item["snippet"]["publishedAt"],
                "views": int(st.get("viewCount", 0)),
                "likes": int(st.get("likeCount", 0)),
                "comments": int(st.get("commentCount", 0)),
            })
    return videos


def _merge_with_records(videos: list[dict], records: list[dict]) -> list[dict]:
    """Atribui topic/theme de cada video a partir do registro do bot."""
    by_id: dict[str, list[dict]] = {}
    for rec in records:
        by_id.setdefault(rec.get("video_id", ""), []).append(rec)
    for v in videos:
        recs = by_id.get(v["video_id"], [])
        v["topic"] = recs[0].get("topic") if recs else None
        v["theme"] = recs[0].get("theme") if recs else None
    return videos


def _compute_nicho_weights(videos: list[dict]) -> tuple[dict, dict]:
    per_theme = {t: {"views": [], "count": 0} for t in THEMES}
    for v in videos:
        theme = v.get("theme")
        if theme not in per_theme:
            continue
        per_theme[theme]["views"].append(int(v.get("views", 0)))
        per_theme[theme]["count"] += 1

    weights = dict(DEFAULT_WEIGHTS)
    for theme in THEMES:
        info = per_theme[theme]
        if info["count"] >= MIN_SAMPLES:
            avg = sum(info["views"]) / info["count"]
            new_w = int(round(avg / VIEWS_PER_WEIGHT_POINT))
            weights[theme] = max(MIN_WEIGHT, min(MAX_WEIGHT, new_w))
    return weights, per_theme


def _compute_title_bias(videos: list[dict]) -> dict:
    per_style = {
        "pergunta": {"views": [], "count": 0},
        "afirmacao": {"views": [], "count": 0},
    }
    for v in videos:
        title = (v.get("title") or "").strip()
        if not title or v.get("theme") is None:
            continue
        style = "pergunta" if "?" in title else "afirmacao"
        per_style[style]["views"].append(int(v.get("views", 0)))
        per_style[style]["count"] += 1

    bias: dict[str, float] = {}
    for style, info in per_style.items():
        if info["count"] >= MIN_SAMPLES:
            bias[style] = round(sum(info["views"]) / info["count"], 1)
    return bias


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=MAX_VIDEOS)
    args = parser.parse_args()

    print("[1/3] Autenticando no YouTube...")
    try:
        youtube = get_authenticated_service()
    except Exception as e:
        print(f"     ERRO na autenticacao: {e}")
        print("     Rode 'python auth_youtube.py' localmente para renovar o token")
        print("     (o escopo youtube.readonly e necessario para ler analytics).")
        return 1

    print("[2/3] Lendo estatisticas reais do canal...")
    try:
        videos = _fetch_recent_videos(youtube, args.limit)
    except Exception as e:
        print(f"     ERRO ao ler videos: {e}")
        print("     O token provavelmente NAO tem o escopo youtube.readonly.")
        print("     Corrige: 'python auth_youtube.py' + atualize o secret YOUTUBE_TOKEN.")
        return 1
    print(f"     {len(videos)} videos encontrados")

    records: list[dict] = []
    if PUBLISHED_FILE.exists():
        try:
            records = json.loads(PUBLISHED_FILE.read_text(encoding="utf-8"))
        except Exception:
            print("     Aviso: published_videos.json ilegivel (registros vazios)")
    videos = _merge_with_records(videos, records)
    tracked = [v for v in videos if v.get("theme")]

    if not tracked:
        print("     Ainda sem videos rastreados (nenhum upload registrado).")
        print("     Nenhum arquivo de analytics gravado - o bot segue com os pesos atuais.")
        return 0

    print("[3/3] Calculando pesos de nicho e vies de titulo...")
    weights, per_theme = _compute_nicho_weights(tracked)
    bias = _compute_title_bias(videos)

    ANALYTICS_DIR.mkdir(exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    (ANALYTICS_DIR / "nicho_weights.json").write_text(
        json.dumps({
            "updated": now,
            "weights": weights,
            "samples": {t: per_theme[t]["count"] for t in THEMES},
        }, ensure_ascii=False, indent=2),
        encoding="utf-8")

    if bias:
        (ANALYTICS_DIR / "title_bias.json").write_text(
            json.dumps({
                "updated": now,
                "bias": bias,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8")
    else:
        if (ANALYTICS_DIR / "title_bias.json").exists():
            try:
                (ANALYTICS_DIR / "title_bias.json").unlink()
            except OSError:
                pass

    # Relatorio legivel
    for v in tracked[:12]:
        print(f"     {v['video_id']} [{v['theme']}] views={v['views']} :: {v['title'][:70]}")
    print(f"     Pesos de nicho -> {weights}")
    print(f"     Views por estilo de titulo -> {bias}")

    if any(per_theme[t]["count"] < MIN_SAMPLES for t in THEMES):
        print("     (nichos sem amostra suficiente mantiveram o peso padrao)")
    print("     Analytics gravados em analytics/. O bot usa isso automaticamente.")
    return 0


if __name__ == "__main__":
    sys.exit(main())