"""Feedback loop de analytics do Curiosity Shorts Agent.

Roda 1x por semana (workflow analytics-update.yml). Le as estatisticas reais
dos videos do canal (views/likes/comments), cruza com o registro de publicacoes
(`published_videos.json` preenchido em cada upload) e recalcula:

  1. analytics/nicho_weights.json  -> pesos de nicho por mediana de views/dia
     (normaliza a idade do video e aplica shrinkage para nao explodir com
     poucas amostras). Usado por _active_theme() no agent.py.
  2. analytics/title_bias.json     -> estilo de titulo vencedor (pergunta vs
     afirmacao) por mediana, injetado no prompt de _generate_seo_title().
  3. analytics/subscriber_history.json -> serie temporal de inscritos (snapshot
     semanal; o bot nunca media isso antes).

Comportamento seguro:
  - Shrinkage puxa nichos com pouca amostra para o prior neutro; pesos ficam
    limitados a [MIN_WEIGHT, MAX_WEIGHT] (nenhum nicho zera de vez).
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

MIN_SAMPLES = 5      # amostras minimas para confiar no vies de titulo
MAX_VIDEOS = 60      # janela de videos analisados
PRIOR_WEIGHT = 10    # prior neutro (media geral) usado no shrinkage
MIN_WEIGHT = 4       # piso: nenhum nicho morre de vez por azar de amostra
MAX_WEIGHT = 40
VIEWS_PER_WEIGHT_POINT = 12
REFERENCE_DAYS = 30  # normaliza views por idade para uma base de 30 dias
MIN_AGE_DAYS = 7     # videos novos demais ainda nao estabilizaram (views front-loaded)
SHRINKAGE_K = 3      # forca do prior (maior = mais conservador)
SUBSCRIBER_FILE = ANALYTICS_DIR / "subscriber_history.json"


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


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _age_days(published_at: str) -> float:
    """Idade do video em dias (minimo 1) para normalizar views acumuladas."""
    try:
        stamp = (published_at or "").replace("Z", "+00:00")
        published = datetime.datetime.fromisoformat(stamp)
        if published.tzinfo is None:
            published = published.replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        return max((now - published).total_seconds() / 86400.0, 1.0)
    except (ValueError, TypeError):
        return 1.0


def _compute_nicho_weights(videos: list[dict]) -> tuple[dict, dict]:
    """Mediana de views/dia + shrinkage para o prior neutro.

    - Views acumuladas normalizadas pela idade (video de 30 dias vs 2 dias).
    - Mediana ignora 1 viral que distorceria a media.
    - Shrinkage puxa nichos com pouca amostra para o prior (evita peso 21 com
      10 videos e peso 1 com 3).
    """
    per_theme = {t: {"views": [], "rates": [], "count": 0} for t in THEMES}
    for v in videos:
        theme = v.get("theme")
        if theme not in per_theme:
            continue
        views = int(v.get("views", 0))
        age = _age_days(v.get("published_at", ""))
        per_theme[theme]["views"].append(views)
        per_theme[theme]["count"] += 1
        # Shorts muito recentes tem views front-loaded; espera estabilizar.
        if age >= MIN_AGE_DAYS:
            per_theme[theme]["rates"].append(views / age)

    weights: dict[str, int] = {}
    for theme in THEMES:
        info = per_theme[theme]
        n = info["count"]
        if not info["rates"]:
            # todos recentes demais — usa o prior neutro sem opinar
            weights[theme] = PRIOR_WEIGHT
            continue
        median_rate = _median(info["rates"])
        raw_w = median_rate * REFERENCE_DAYS / VIEWS_PER_WEIGHT_POINT
        # shrinkage usa o total de videos rastreados (amostra do nicho),
        # nao so os com idade estavel
        shrunk = (n * raw_w + SHRINKAGE_K * PRIOR_WEIGHT) / (n + SHRINKAGE_K)
        weights[theme] = max(MIN_WEIGHT, min(MAX_WEIGHT, int(round(shrunk))))
    return weights, per_theme


def _compute_title_bias(videos: list[dict]) -> tuple[dict, dict, str | None]:
    """Vies de titulo por mediana de views, com contagem por estilo.

    So declara um vencedor quando OS DOIS estilos tem >= MIN_SAMPLES videos;
    caso contrario o agent usa o prompt neutro (evita decidir com 2 amostras).
    """
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
    samples: dict[str, int] = {}
    for style, info in per_style.items():
        samples[style] = info["count"]
        if info["count"] >= MIN_SAMPLES:
            bias[style] = round(_median(info["views"]), 1)

    winner = None
    if all(samples[s] >= MIN_SAMPLES for s in ("pergunta", "afirmacao")):
        winner = max(bias, key=bias.get)
    return bias, samples, winner


def _fetch_subscriber_count(youtube) -> int | None:
    """Total de inscritos do canal (None se oculto/indisponivel)."""
    try:
        resp = youtube.channels().list(part="statistics", mine=True).execute()
        items = resp.get("items") or []
        if not items:
            return None
        stats = items[0].get("statistics", {})
        if stats.get("hiddenSubscriberCount"):
            return None
        return int(stats["subscriberCount"])
    except (KeyError, ValueError, TypeError):
        return None


def _append_subscriber_snapshot(count: int | None):
    """Grava um ponto da serie de inscritos (mantem os ultimos 200)."""
    if count is None:
        return
    history: list[dict] = []
    if SUBSCRIBER_FILE.exists():
        try:
            history = json.loads(SUBSCRIBER_FILE.read_text(encoding="utf-8"))
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    history.append({"updated": now, "subscribers": int(count)})
    SUBSCRIBER_FILE.write_text(
        json.dumps(history[-200:], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"     Inscritos: {count} (snapshot salvo em analytics/subscriber_history.json)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=MAX_VIDEOS)
    args = parser.parse_args()

    print("[1/4] Autenticando no YouTube...")
    try:
        youtube = get_authenticated_service()
    except Exception as e:
        print(f"     ERRO na autenticacao: {e}")
        print("     Rode 'python auth_youtube.py' localmente para renovar o token")
        print("     (o escopo youtube.readonly e necessario para ler analytics).")
        return 1

    print("[2/4] Lendo estatisticas reais do canal...")
    _append_subscriber_snapshot(_fetch_subscriber_count(youtube))
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

    print("[3/4] Calculando pesos de nicho e vies de titulo...")
    weights, per_theme = _compute_nicho_weights(tracked)
    bias, bias_samples, bias_winner = _compute_title_bias(videos)

    print("[4/4] Gravando analytics...")
    ANALYTICS_DIR.mkdir(exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    (ANALYTICS_DIR / "nicho_weights.json").write_text(
        json.dumps({
            "updated": now,
            "metric": "median_views_per_day",
            "weights": weights,
            "samples": {t: per_theme[t]["count"] for t in THEMES},
            "prior": PRIOR_WEIGHT,
            "shrinkage_k": SHRINKAGE_K,
            "reference_days": REFERENCE_DAYS,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8")

    if bias:
        payload = {
            "updated": now,
            "metric": "median_views",
            "bias": bias,
            "samples": bias_samples,
        }
        if bias_winner:
            payload["winner"] = bias_winner
        (ANALYTICS_DIR / "title_bias.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
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
    print(f"     Pesos de nicho (mediana views/dia + shrinkage) -> {weights}")
    print(f"     Vies de titulo (mediana views) -> {bias} {bias_samples}")

    if bias and not bias_winner:
        print("     (estilos sem amostra suficiente: prompt de titulo segue neutro)")
    under = [t for t in THEMES if per_theme[t]["count"] < MIN_SAMPLES]
    if under:
        print(f"     (nichos com < {MIN_SAMPLES} amostras: {', '.join(under)})")
    print("     Analytics gravados em analytics/. O bot usa isso automaticamente.")
    return 0


if __name__ == "__main__":
    sys.exit(main())