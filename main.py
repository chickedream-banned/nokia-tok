import os
import re
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

# Проверенные чистые каналы с ежедневными короткими видео
DEFAULT_CHANNELS = {
    "vidos": "Fun_vidos",
    "reels": "memreels",
    "memes": "reels_memes"
}

# Кэш каналов: { "имя_канала": [список_видео] }
CH_CACHE = {}

def transcode_to_3gp(input_path: str, output_path: str) -> bool:
    """Аппаратное сжатие в 3GP (176x144, 15 FPS) под родной плеер Series 40"""
    vf_filter = "scale=w=176:h=144:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=176:144:(ow-iw)/2:(oh-ih)/2,format=yuv420p"

    # H.263 + AAC (гарантированно поддерживается и FFmpeg, и Нокией)
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

def get_channel_videos(channel: str):
    global CH_CACHE
    if channel in CH_CACHE and len(CH_CACHE[channel]) > 0:
        return CH_CACHE[channel]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    items = []
    try:
        url = f"https://t.me/s/{channel}"
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            posts = re.split(r'<div class="tgme_widget_message\s+', r.text)
            for post in posts[1:]:
                # Ищем прямой MP4 файл
                video_match = re.search(r'<video[^>]+src=["\']([^"\']+)["\']', post)
                if not video_match:
                    continue

                video_url = video_match.group(1)

                # ID поста
                id_match = re.search(r'data-post=["\']([^"\']+)["\']', post)
                post_id = id_match.group(1).replace("/", "_") if id_match else hashlib.md5(video_url.encode()).hexdigest()[:8]

                # Превью
                thumb_match = re.search(r'tgme_widget_message_video_thumb[^"\']*style=["\'][^"\']*url\([\'"]?([^\'"]+)[\'"]?\)', post)
                cover_url = thumb_match.group(1) if thumb_match else ""

                # Текст поста
                text_match = re.search(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', post, re.DOTALL)
                if text_match:
                    raw_text = re.sub(r'<[^>]+>', '', text_match.group(1)).strip()
                    title = html.unescape(raw_text).replace("\n", " ")[:40]
                else:
                    title = f"Ролик #{post_id[-4:]}"

                items.append({
                    "id": post_id,
                    "title": title or "Короткое видео",
                    "video_url": video_url,
                    "cover": cover_url
                })
    except Exception as e:
        print(f"[Fetch Error {channel}]: {e}")

    # Свежие ролики ставим первыми
    items.reverse()
    CH_CACHE[channel] = items
    return items

@app.get("/", response_class=HTMLResponse)
def index(ch: str = Query("Fun_vidos"), idx: int = Query(0), refresh: int = Query(0)):
    global CH_CACHE
    if refresh == 1 and ch in CH_CACHE:
        del CH_CACHE[ch]

    feed = get_channel_videos(ch)
    total = len(feed)

    if total == 0:
        return f"""<!DOCTYPE html><html><body style="font-family:sans-serif;font-size:12px;padding:8px;background:#000;color:#fff;text-align:center;">
        <b>Nokia Tok</b><br><br>
        Канал @{ch} пуст или закрыт.<br><br>
        <a href="/?ch=Fun_vidos" style="color:#0af;">[Открыть Приколы]</a> | 
        <a href="/?ch=memreels" style="color:#0af;">[Открыть Рилсы]</a>
        </body></html>"""

    if idx < 0:
        idx = 0
    if idx >= total:
        idx = total - 1

    item = feed[idx]
    title = item["title"]
    post_id = item["id"]
    video_url = item["video_url"]
    cover_url = item["cover"]

    prev_idx = idx - 1
    next_idx = idx + 1

    prev_btn = f'<a href="/?ch={ch}&idx={prev_idx}" class="btn">[&lt; Назад]</a>' if prev_idx >= 0 else '<span class="dis">[&lt; Назад]</span>'
    next_btn = f'<a href="/?ch={ch}&idx={next_idx}" class="btn">[Вперед &gt;]</a>' if next_idx < total else f'<a href="/?ch={ch}&refresh=1" class="btn">[Сначала]</a>'

    watch_href = f"/watch?id={post_id}&src={urllib.parse.quote(video_url)}"
    img_tag = f'<img src="{cover_url}" class="cover" alt="Видео">' if cover_url else '<div class="no-cover">Видео</div>'

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nokia Tok ({idx+1}/{total})</title>
    <style>
        body {{ font-family:sans-serif; margin:0; padding:2px; background:#000; color:#fff; text-align:center; font-size:11px; }}
        .nav-ch {{ background:#111; padding:3px; margin-bottom:3px; font-size:10px; }}
        .nav-ch a {{ color:#0af; text-decoration:none; margin:0 3px; }}
        .meta {{ padding:2px; text-align:left; font-size:11px; }}
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
        .box-src {{ margin-top:6px; border-top:1px solid #222; padding-top:4px; font-size:10px; }}
        .box-src input[type="text"] {{ width:80%; font-size:10px; }}
    </style>
</head>
<body>
    <div class="nav-ch">
        <a href="/?ch=Fun_vidos">[Приколы]</a>|
        <a href="/?ch=memreels">[Рилсы]</a>|
        <a href="/?ch=reels_memes">[Мемы]</a>
    </div>

    <div class="meta">
        <div class="author">@{ch}</div>
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

    <div class="box-src">
        <form action="/" method="GET">
            <span>Канал @:</span>
            <input type="text" name="ch" value="{ch}">
            <input type="submit" value="Открыть">
        </form>
    </div>
</body>
</html>"""

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
            raise HTTPException(status_code=400, detail="Сбой загрузки видеофайла")

        with open(temp_mp4, "wb") as f:
            for chunk in r.iter_content(chunk_size=32768):
                f.write(chunk)

        ok = transcode_to_3gp(temp_mp4, output_3gp)

        if os.path.exists(temp_mp4):
            os.remove(temp_mp4)

        if not ok or not os.path.exists(output_3gp):
            raise HTTPException(status_code=500, detail="Ошибка сжатия видео")

    return FileResponse(
        output_3gp,
        media_type="video/3gpp",
        filename=f"{id}.3gp"
    )
