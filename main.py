import os
import html
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
FEED_CACHE = []

def transcode_to_3gp(stream_url: str, output_path: str) -> bool:
    # Для H.263 используется стандартное разрешение QCIF (176x144) с полями.
    # Прошивка Nokia 301 автоматически растягивает его на весь экран 240x320.
    cmd = [
        FFMPEG_BIN, "-y",
        "-headers", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\r\n",
        "-i", stream_url,
        "-vf", "scale=176:144:force_original_aspect_ratio=decrease,pad=176:144:(ow-iw)/2:(oh-ih)/2",
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

def fetch_reddit_feed():
    global FEED_CACHE
    if len(FEED_CACHE) > 0:
        return FEED_CACHE

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NokiaTok-S40/2.0"
    }

    subreddits = ["TikTokCringe", "tiktok"]
    items = []

    for sub in subreddits:
        try:
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit=30"
            r = requests.get(url, headers=headers, timeout=8)
            if r.status_code == 200:
                data = r.json()
                children = data.get("data", {}).get("children", [])
                for child in children:
                    post = child.get("data", {})
                    if not post.get("is_video"):
                        continue

                    media = post.get("media") or {}
                    r_vid = media.get("reddit_video") or {}
                    
                    # HLS содержит синхронизированную аудио- и видеодорожку
                    stream_url = r_vid.get("hls_url") or r_vid.get("fallback_url")
                    if not stream_url:
                        continue

                    # Достаем превью
                    cover = ""
                    prev_imgs = post.get("preview", {}).get("images", [])
                    if prev_imgs:
                        cover = prev_imgs[0].get("source", {}).get("url", "")
                        cover = html.unescape(cover)
                    elif post.get("thumbnail", "").startswith("http"):
                        cover = post.get("thumbnail")

                    items.append({
                        "id": post.get("id"),
                        "title": post.get("title", "Без названия"),
                        "author": post.get("author", "tiktok"),
                        "stream": stream_url,
                        "cover": cover
                    })

                if len(items) >= 15:
                    break
        except Exception as e:
            print(f"[Reddit {sub} Error] {e}")

    FEED_CACHE = items
    print(f"[Feed] Загружено роликов: {len(FEED_CACHE)}")
    return FEED_CACHE

@app.get("/", response_class=HTMLResponse)
def index(idx: int = Query(0), refresh: int = Query(0)):
    global FEED_CACHE
    if refresh == 1:
        FEED_CACHE = []

    feed = fetch_reddit_feed()
    total = len(feed)

    if total == 0:
        return """<!DOCTYPE html><html><body style="font-family:sans-serif;font-size:12px;padding:8px;background:#000;color:#fff;">
        <b>Nokia Tok</b><br><br>
        Лента пуста или Реддит не ответил вовремя.<br><br>
        <a href="/?refresh=1" style="color:#0af;">[Повторить загрузку]</a>
        </body></html>"""

    if idx < 0:
        idx = 0
    if idx >= total:
        idx = total - 1

    item = feed[idx]
    title = item.get("title")[:42]
    author = item.get("author")
    vid_id = item.get("id")
    stream_url = item.get("stream")
    cover_url = item.get("cover")

    prev_idx = idx - 1
    next_idx = idx + 1

    prev_btn = f'<a href="/?idx={prev_idx}" class="btn">[&lt; Назад]</a>' if prev_idx >= 0 else '<span class="dis">[&lt; Назад]</span>'
    next_btn = f'<a href="/?idx={next_idx}" class="btn">[Вперед &gt;]</a>' if next_idx < total else '<a href="/?refresh=1" class="btn">[Сначала]</a>'

    watch_href = f"/watch?id={vid_id}&src={urllib.parse.quote(stream_url)}"

    img_html = f'<img src="{cover_url}" class="cover" alt="Видео">' if cover_url else '<div class="no-cover">Нет обложки</div>'

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nokia Tok ({idx+1}/{total})</title>
    <style>
        body {{ font-family:sans-serif; margin:0; padding:2px; background:#000; color:#fff; text-align:center; font-size:11px; }}
        .header {{ background:#111; padding:3px; display:flex; justify-content:space-between; font-size:11px; }}
        .header a {{ color:#0af; text-decoration:none; }}
        .meta {{ padding:3px 2px; text-align:left; font-size:11px; }}
        .author {{ color:#0af; font-weight:bold; }}
        .title {{ color:#ddd; height:26px; overflow:hidden; }}
        .card {{ display:block; text-decoration:none; background:#111; border:1px solid #333; margin:3px auto; width:220px; }}
        .cover {{ width:220px; height:180px; display:block; object-fit:cover; background:#222; }}
        .no-cover {{ width:220px; height:180px; line-height:180px; background:#222; color:#777; }}
        .play-bar {{ background:#c00; color:#fff; font-weight:bold; font-size:12px; padding:5px; text-align:center; }}
        .nav {{ margin-top:5px; padding:2px; font-size:12px; }}
        .btn {{ color:#fff; background:#222; border:1px solid #555; padding:3px 6px; text-decoration:none; margin:0 3px; font-weight:bold; }}
        .dis {{ color:#444; padding:3px 6px; margin:0 3px; }}
        .count {{ color:#888; font-size:10px; }}
    </style>
</head>
<body>
    <div class="header">
        <span>Nokia Tok</span>
        <a href="/?refresh=1">[Сброс]</a>
    </div>

    <div class="meta">
        <div class="author">u/{author}</div>
        <div class="title">{title}</div>
    </div>

    <a href="{watch_href}" class="card">
        {img_html}
        <div class="play-bar">[ СМОТРЕТЬ (ОК) ]</div>
    </a>

    <div class="nav">
        {prev_btn}
        <span class="count">{idx+1}/{total}</span>
        {next_btn}
    </div>
</body>
</html>"""

@app.get("/watch")
def watch(id: str = Query(...), src: str = Query(...)):
    stream_url = urllib.parse.unquote(src)
    output_3gp = os.path.join(CACHE_DIR, f"{id}.3gp")

    if not os.path.exists(output_3gp):
        print(f"[Transcode] Конвертируем {id}...")
        ok = transcode_to_3gp(stream_url, output_3gp)
        if not ok or not os.path.exists(output_3gp):
            raise HTTPException(status_code=500, detail="Ошибка перекодирования HLS в 3GP")
        print(f"[Transcode] Готово: {os.path.getsize(output_3gp)} байт")

    return FileResponse(
        output_3gp,
        media_type="video/3gpp",
        filename=f"{id}.3gp"
    )
