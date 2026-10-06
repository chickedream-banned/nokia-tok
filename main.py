import os
import hashlib
import subprocess
import urllib.parse
import requests
import imageio_ffmpeg
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse

app = FastAPI()
CACHE_DIR = "/tmp/nokia_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()

# ВСТАВЬ СЮДА ССЫЛКУ НА СВОЙ CLOUDFLARE WORKER
CF_WORKER_URL = "https://tiktok-bridge.bozhkogleb4.workers.dev/"

FEED_CACHE = []

def transcode_to_3gp(input_path: str, output_path: str) -> bool:
    """Аппаратное сжатие в 3GP (QCIF 176x144, 15 FPS, AAC-LC) под Nokia 301"""
    vf_filter = "scale=w=176:h=144:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=176:144:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
    cmd = [
        FFMPEG_BIN, "-y",
        "-i", input_path,
        "-vf", vf_filter,
        "-r", "15",
        "-c:v", "h263",
        "-b:v", "128k",
        "-c:a", "aac",
        "-b:a", "32k",
        "-ar", "16000",
        "-ac", "1",
        output_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000

def fetch_tiktok_feed():
    global FEED_CACHE
    if len(FEED_CACHE) > 0:
        return FEED_CACHE

    try:
        r = requests.get(CF_WORKER_URL, timeout=10)
        if r.status_code == 200:
            data = r.json()
            items = data.get("data", [])
            extracted = []

            for item in items:
                play_url = item.get("play")
                if not play_url:
                    continue

                vid_id = item.get("video_id") or item.get("id") or hashlib.md5(play_url.encode()).hexdigest()[:8]
                title = (item.get("title") or "TikTok Clip").replace("\n", " ").strip()[:32]
                author = item.get("author", {}).get("unique_id") or "tiktok"

                extracted.append({
                    "id": str(vid_id),
                    "author": str(author),
                    "title": str(title),
                    "video_url": str(play_url)
                })

            FEED_CACHE = extracted
            print(f"[TikTok] Успешно загружено тиктоков: {len(FEED_CACHE)}")
            return FEED_CACHE
        else:
            print(f"[TikTok Bridge Error]: HTTP {r.status_code}")
    except Exception as e:
        print(f"[TikTok Bridge Fail]: {e}")

    return []

@app.get("/api/feed", response_class=PlainTextResponse)
def api_feed(shuffle: int = 0):
    global FEED_CACHE
    if shuffle == 1:
        FEED_CACHE = []

    feed = fetch_tiktok_feed()
    lines = []
    base_host = "https://nokia-tok.onrender.com"

    for item in feed:
        vid_id = item["id"]
        v_url = urllib.parse.quote(item["video_url"])
        stream_url = f"{base_host}/watch?id={vid_id}&src={v_url}"
        clean_title = item["title"].replace("|", " ")
        clean_author = item["author"].replace("|", " ")
        lines.append(f"{clean_author}|{clean_title}|{stream_url}")

    return "\n".join(lines)

@app.get("/watch")
def watch(id: str = Query(...), src: str = Query(...)):
    raw_url = urllib.parse.unquote(src).strip()
    output_3gp = os.path.join(CACHE_DIR, f"{id}.3gp")
    temp_mp4 = os.path.join(CACHE_DIR, f"{id}_temp.mp4")

    if not os.path.exists(output_3gp):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        r = requests.get(raw_url, headers=headers, stream=True, timeout=20)
        if r.status_code != 200:
            raise HTTPException(status_code=400, detail="Ошибка загрузки тиктока")

        with open(temp_mp4, "wb") as f:
            for chunk in r.iter_content(chunk_size=32768):
                f.write(chunk)

        ok = transcode_to_3gp(temp_mp4, output_3gp)
        if os.path.exists(temp_mp4):
            os.remove(temp_mp4)

        if not ok or not os.path.exists(output_3gp):
            raise HTTPException(status_code=500, detail="Ошибка сжатия через FFmpeg")

    return FileResponse(
        output_3gp,
        media_type="video/3gpp",
        filename=f"{id}.3gp"
    )
