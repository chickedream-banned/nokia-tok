import os
import random
import hashlib
import subprocess
import urllib.parse
import requests
import imageio_ffmpeg
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse

app = FastAPI()
CACHE_DIR = "/tmp/nokia_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()

# Публичные шлюзы Piped, не блокирующие IP дата-центров
PIPED_INSTANCES = [
    "https://pipedapi.leptons.xyz",
    "https://api.piped.privacydev.net",
    "https://pipedapi.tokhmi.xyz",
    "https://api.piped.yt",
    "https://pipedapi.kavin.rocks"
]

SEARCH_TOPICS = [
    "%23shorts+memes",
    "%23shorts+shitpost",
    "%23shorts+viral",
    "%23shorts+humor",
    "%23shorts+fun"
]

FEED_CACHE = []

def transcode_to_3gp(stream_url: str, output_path: str, audio_url: str = None) -> bool:
    """Аппаратное сжатие в 3GP (176x144 QCIF, 15 FPS, H.263/AAC) под Nokia 301"""
    vf_filter = "scale=w=176:h=144:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=176:144:(ow-iw)/2:(oh-ih)/2,format=yuv420p"

    cmd = [
        FFMPEG_BIN, "-y",
        "-headers", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\r\n",
        "-i", stream_url
    ]

    if audio_url:
        cmd.extend([
            "-headers", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\r\n",
            "-i", audio_url,
            "-map", "0:v:0",
            "-map", "1:a:0"
        ])

    cmd.extend([
        "-vf", vf_filter,
        "-r", "15",
        "-c:v", "h263",
        "-b:v", "128k",
        "-c:a", "aac",
        "-b:a", "32k",
        "-ar", "16000",
        "-ac", "1",
        output_path
    ])

    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000

def get_stream_urls(vid_id: str):
    """Вытаскивает прямую ссылку на HLS или видео/аудио потоки через Piped"""
    for inst in PIPED_INSTANCES:
        try:
            r = requests.get(f"{inst}/streams/{vid_id}", timeout=6)
            if r.status_code == 200:
                data = r.json()
                hls = data.get("hls")
                if hls:
                    return hls, None

                video_streams = data.get("videoStreams", [])
                audio_streams = data.get("audioStreams", [])

                if video_streams and audio_streams:
                    # Ищем легкий поток 360p для максимально быстрого сжатия
                    v_url = None
                    for vs in video_streams:
                        if vs.get("quality") in ["360p", "480p", "240p"]:
                            v_url = vs.get("url")
                            break
                    if not v_url:
                        v_url = video_streams[0].get("url")

                    a_url = audio_streams[0].get("url")
                    return v_url, a_url
        except Exception:
            continue
    return None, None

def fetch_shorts():
    """Сбор свежих YouTube Shorts через поисковые запросы по мемам"""
    global FEED_CACHE
    collected = {}
    query = random.choice(SEARCH_TOPICS)

    for inst in PIPED_INSTANCES:
        try:
            target_url = f"{inst}/search?q={query}&filter=videos"
            r = requests.get(target_url, timeout=7)
            if r.status_code == 200:
                data = r.json()
                items = data.get("items", [])
                for item in items:
                    duration = item.get("duration", 0)
                    # Строгий фильтр Shorts: длительность до 60 секунд
                    if duration <= 0 or duration > 60:
                        continue

                    url_path = item.get("url", "")
                    vid_id = url_path.replace("/watch?v=", "").strip()
                    if not vid_id or vid_id in collected:
                        continue

                    title = item.get("title", "Shorts").replace("\n", " ").strip()[:36]
                    author = item.get("uploaderName", "YouTube").strip()
                    thumbnail = item.get("thumbnail", "")

                    collected[vid_id] = {
                        "id": vid_id,
                        "title": title,
                        "author": author,
                        "cover": thumbnail
                    }

                if len(collected) >= 15:
                    break
        except Exception as e:
            print(f"[Piped Search Error {inst}]: {e}")

    result = list(collected.values())
    random.shuffle(result)
    FEED_CACHE = result
    print(f"[Shorts Ready] Собрано роликов: {len(FEED_CACHE)}")
    return FEED_CACHE

@app.get("/", response_class=HTMLResponse)
def index(idx: int = Query(0), shuffle: int = Query(0)):
    global FEED_CACHE
    if shuffle == 1 or len(FEED_CACHE) == 0:
        fetch_shorts()

    total = len(FEED_CACHE)
    if total == 0:
        return """<!DOCTYPE html><html><body style="font-family:sans-serif;font-size:12px;padding:8px;background:#000;color:#fff;text-align:center;">
        <b>Nokia Shorts</b><br><br>
        Лента обновляется...<br><br>
        <a href="/?shuffle=1" style="color:#0af;">[Попробовать снова]</a>
        </body></html>"""

    if idx < 0:
        idx = 0
    if idx >= total:
        idx = total - 1

    item = FEED_CACHE[idx]
    title = item["title"]
    author = item["author"]
    vid_id = item["id"]
    cover_url = item["cover"]

    prev_idx = idx - 1
    next_idx = idx + 1

    prev_btn = f'<a href="/?idx={prev_idx}" class="btn">[&lt; Назад]</a>' if prev_idx >= 0 else '<span class="dis">[&lt; Назад]</span>'
    next_btn = f'<a href="/?idx={next_idx}" class="btn">[Вперед &gt;]</a>' if next_idx < total else '<a href="/?shuffle=1" class="btn">[Перемешать]</a>'

    watch_href = f"/watch?id={vid_id}"
    img_tag = f'<img src="{cover_url}" class="cover" alt="Видео">' if cover_url else '<div class="no-cover">Shorts</div>'

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nokia Shorts ({idx+1}/{total})</title>
    <style>
        body {{ font-family:sans-serif; margin:0; padding:2px; background:#000; color:#fff; text-align:center; font-size:11px; }}
        .top-bar {{ background:#111; padding:3px; display:flex; justify-content:space-between; font-size:11px; }}
        .top-bar a {{ color:#0af; text-decoration:none; font-weight:bold; }}
        .meta {{ padding:3px 2px; text-align:left; font-size:11px; }}
        .author {{ color:#0af; font-weight:bold; }}
        .title {{ color:#ddd; height:24px; overflow:hidden; }}
        .card {{ display:block; text-decoration:none; background:#111; border:1px solid #333; margin:2px auto; width:220px; }}
        .cover {{ width:220px; height:160px; display:block; object-fit:cover; background:#222; }}
        .no-cover {{ width:220px; height:160px; line-height:160px; background:#222; color:#777; }}
        .play-bar {{ background:#c00; color:#fff; font-weight:bold; font-size:12px; padding:6px; text-align:center; }}
        .nav {{ margin-top:4px; padding:2px; font-size:12px; }}
        .btn {{ color:#fff; background:#222; border:1px solid #555; padding:3px 8px; text-decoration:none; margin:0 2px; font-weight:bold; }}
        .dis {{ color:#444; padding:3px 8px; margin:0 2px; }}
        .count {{ color:#888; font-size:10px; }}
    </style>
</head>
<body>
    <div class="top-bar">
        <span>Nokia Shorts</span>
        <a href="/?shuffle=1">[Обновить]</a>
    </div>

    <div class="meta">
        <div class="author">@{author}</div>
        <div class="title">{title}</div>
    </div>

    <a href="{watch_href}" class="card">
        {img_tag}
        <div class="play-bar">[ СМОТРЕТЬ (ОК) ]</div>
    </a>

    <div class="nav">
        {prev_btn}
        <span class="count">{idx+1}/{total}</span>
        {next_btn}
    </div>
</body>
</html>"""

@app.get("/api/feed", response_class=PlainTextResponse)
def api_feed(shuffle: int = 0):
    global FEED_CACHE
    if shuffle == 1 or len(FEED_CACHE) == 0:
        fetch_shorts()

    lines = []
    base_host = "https://nokia-tok.onrender.com"
    for item in FEED_CACHE:
        vid_id = item["id"]
        stream_url = f"{base_host}/watch?id={vid_id}"
        clean_title = item["title"].replace("|", " ").replace("\n", " ")
        clean_author = item["author"].replace("|", " ")
        lines.append(f"{clean_author}|{clean_title}|{stream_url}")

    return "\n".join(lines)

@app.get("/watch")
def watch(id: str = Query(...)):
    output_3gp = os.path.join(CACHE_DIR, f"{id}.3gp")

    if not os.path.exists(output_3gp):
        print(f"[Shorts] Получаем потоки для {id}...")
        v_url, a_url = get_stream_urls(id)
        if not v_url:
            raise HTTPException(status_code=400, detail="Не удалось извлечь видеопоток из YouTube")

        print(f"[FFmpeg] Конвертируем шортс {id} в 3GP...")
        ok = transcode_to_3gp(v_url, output_3gp, audio_url=a_url)

        if not ok or not os.path.exists(output_3gp):
            raise HTTPException(status_code=500, detail="Ошибка сжатия видео через FFmpeg")

        print(f"[FFmpeg] Ролик готов: {os.path.getsize(output_3gp)} байт")

    return FileResponse(
        output_3gp,
        media_type="video/3gpp",
        filename=f"{id}.3gp"
    )
