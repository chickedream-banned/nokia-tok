import os
import hashlib
import subprocess
import urllib.parse
import requests
import imageio_ffmpeg
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse

app = FastAPI()
CACHE_DIR = "/tmp/nokia_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()

# Локальный кэш списка трендов, чтобы не дергать прокси на каждый клик
FEED_CACHE = []

def download_video_to_disk(url: str, dest_path: str) -> bool:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    urls_to_try = []
    if "tikwm.com" in url:
        urls_to_try.append(f"https://api.allorigins.win/raw?url={urllib.parse.quote(url)}")
        urls_to_try.append(f"https://corsproxy.io/?url={urllib.parse.quote(url)}")
    urls_to_try.append(url)

    for u in urls_to_try:
        try:
            r = requests.get(u, headers=headers, stream=True, timeout=15)
            if r.status_code == 200:
                with open(dest_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=16384):
                        f.write(chunk)
                if os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000:
                    return True
        except Exception as e:
            print(f"[Download Error] {e}")
    return False

def transcode_to_3gp(input_path: str, output_path: str) -> bool:
    cmd = [
        FFMPEG_BIN, "-y",
        "-i", input_path,
        "-vf", "scale=240:320:force_original_aspect_ratio=decrease,pad=240:320:(ow-iw)/2:(oh-ih)/2",
        "-r", "15",
        "-c:v", "h263",
        "-b:v", "128k",
        "-c:a", "amr_nb",
        "-ar", "8000",
        "-ac", "1",
        output_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return res.returncode == 0

def fetch_trending_feed():
    global FEED_CACHE
    if len(FEED_CACHE) > 0:
        return FEED_CACHE

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    # 1. TikWM через AllOrigins
    try:
        target = "https://www.tikwm.com/api/feed/list?region=US"
        proxy_url = f"https://api.allorigins.win/raw?url={urllib.parse.quote(target)}"
        r = requests.get(proxy_url, headers=headers, timeout=8)
        if r.status_code == 200:
            items = r.json().get("data", [])
            if isinstance(items, list) and len(items) > 0:
                FEED_CACHE = items[:20]
                return FEED_CACHE
    except Exception as e:
        print(f"[Feed AllOrigins Error] {e}")

    # 2. TikWM через CorsProxy
    try:
        proxy_url2 = f"https://corsproxy.io/?url={urllib.parse.quote('https://www.tikwm.com/api/feed/list?region=US')}"
        r2 = requests.get(proxy_url2, headers=headers, timeout=8)
        if r2.status_code == 200:
            items = r2.json().get("data", [])
            if isinstance(items, list) and len(items) > 0:
                FEED_CACHE = items[:20]
                return FEED_CACHE
    except Exception as e:
        print(f"[Feed CorsProxy Error] {e}")

    return []

@app.get("/", response_class=HTMLResponse)
def index(idx: int = Query(0), refresh: int = Query(0)):
    global FEED_CACHE
    if refresh == 1:
        FEED_CACHE = []

    feed = fetch_trending_feed()
    total = len(feed)

    if total == 0:
        return """<!DOCTYPE html><html><body style="font-family:sans-serif;font-size:12px;padding:5px;">
        <b>Nokia Tok</b><br><br>
        Лента пока пуста или прокси перезагружается.<br>
        <a href="/?refresh=1">[Попробовать снова]</a>
        </body></html>"""

    # Защита от выхода за пределы списка
    if idx < 0:
        idx = 0
    if idx >= total:
        idx = total - 1

    item = feed[idx]
    title = (item.get("title") or "Видео без названия")[:40]
    author = item.get("author", {}).get("unique_id") or "tiktok"
    vid_id = item.get("video_id") or item.get("id")
    play_url = item.get("play")
    cover_url = item.get("cover") or item.get("origin_cover") or ""

    prev_idx = idx - 1
    next_idx = idx + 1

    prev_btn = f'<a href="/?idx={prev_idx}" class="btn-nav">[&lt; Назад]</a>' if prev_idx >= 0 else '<span class="btn-disabled">[&lt; Назад]</span>'
    next_btn = f'<a href="/?idx={next_idx}" class="btn-nav">[Вперед &gt;]</a>' if next_idx < total else '<a href="/?refresh=1" class="btn-nav">[Обновить]</a>'

    watch_href = f"/watch?id={vid_id}&src={urllib.parse.quote(play_url)}"

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nokia Tok ({idx+1}/{total})</title>
    <style>
        body {{ font-family: sans-serif; margin: 0; padding: 2px; background: #000; color: #fff; text-align: center; font-size: 11px; }}
        .header {{ background: #111; padding: 2px 4px; display: flex; justify-content: space-between; font-size: 11px; }}
        .header a {{ color: #0af; text-decoration: none; }}
        .meta {{ padding: 3px 2px; text-align: left; font-size: 11px; }}
        .author {{ color: #0af; font-weight: bold; }}
        .title {{ color: #ddd; max-height: 28px; overflow: hidden; }}
        .screen-link {{ display: block; text-decoration: none; background: #111; border: 1px solid #333; margin: 2px auto; width: 220px; }}
        .cover-img {{ width: 220px; height: 180px; display: block; object-fit: cover; background: #222; }}
        .play-bar {{ background: #c00; color: #fff; font-weight: bold; font-size: 12px; padding: 4px; text-align: center; }}
        .nav-bar {{ margin-top: 4px; padding: 2px; font-size: 12px; }}
        .btn-nav {{ color: #fff; background: #222; border: 1px solid #555; padding: 3px 6px; text-decoration: none; margin: 0 4px; font-weight: bold; }}
        .btn-disabled {{ color: #555; padding: 3px 6px; margin: 0 4px; }}
        .counter {{ color: #888; font-size: 10px; }}
    </style>
</head>
<body>
    <div class="header">
        <span>Nokia Tok</span>
        <a href="/?refresh=1">[Сброс]</a>
    </div>

    <div class="meta">
        <div class="author">@{author}</div>
        <div class="title">{title}</div>
    </div>

    <a href="{watch_href}" class="screen-link">
        <img src="{cover_url}" class="cover-img" alt="Обложка">
        <div class="play-bar">[ СМОТРЕТЬ (ОК) ]</div>
    </a>

    <div class="nav-bar">
        {prev_btn}
        <span class="counter">{idx+1}/{total}</span>
        {next_btn}
    </div>
</body>
</html>"""

@app.get("/watch")
def watch(url: str = Query(None), id: str = Query(None), src: str = Query(None)):
    video_url = src
    video_id = id

    if url:
        clean_url = url.strip()
        parsed_ok = False
        session = requests.Session()
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

        target_url = clean_url
        if "tiktok.com" in clean_url:
            try:
                res_head = session.get(clean_url, headers={"User-Agent": ua}, allow_redirects=True, timeout=8)
                target_url = res_head.url.split("?")[0]
            except Exception:
                pass

        try:
            r1 = session.post(
                "https://lovetik.com/api/ajax/search",
                data={"query": target_url},
                headers={
                    "User-Agent": ua,
                    "Referer": "https://lovetik.com/",
                    "Origin": "https://lovetik.com",
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
                },
                timeout=10
            )
            if r1.status_code == 200:
                data1 = r1.json()
                if data1.get("status") == "ok" and data1.get("links"):
                    video_id = data1.get("vid")
                    for link in data1.get("links", []):
                        t_lbl = link.get("t", "").lower()
                        if "watermark" in t_lbl and "no" in t_lbl:
                            video_url = link.get("a")
                            break
                        if not video_url and link.get("a"):
                            video_url = link.get("a")
                    if video_url:
                        parsed_ok = True
        except Exception:
            pass

        if not parsed_ok or not video_url:
            raise HTTPException(status_code=400, detail="Не удалось распарсить ссылку")

    if not video_url:
        raise HTTPException(status_code=400, detail="Отсутствует URL видео")

    if not video_id:
        video_id = hashlib.md5(video_url.encode()).hexdigest()

    output_3gp = os.path.join(CACHE_DIR, f"{video_id}.3gp")
    temp_mp4 = os.path.join(CACHE_DIR, f"{video_id}_temp.mp4")

    if not os.path.exists(output_3gp):
        download_ok = download_video_to_disk(video_url, temp_mp4)
        if not download_ok:
            raise HTTPException(status_code=500, detail="Не удалось скачать видео")

        trans_ok = transcode_to_3gp(temp_mp4, output_3gp)
        if os.path.exists(temp_mp4):
            os.remove(temp_mp4)

        if not trans_ok or not os.path.exists(output_3gp):
            raise HTTPException(status_code=500, detail="Ошибка сжатия через FFmpeg")

    return FileResponse(
        output_3gp,
        media_type="video/3gpp",
        filename=f"{video_id}.3gp"
    )
