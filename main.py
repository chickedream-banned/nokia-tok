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

# Железобетонная лента коротких роликов (быстрый CDN, никогда не банит)
BUILTIN_FEED = [
    {
        "id": "clip_01",
        "title": "Blazes Showdown (Short)",
        "author": "viral_box",
        "cover": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/images/ForBiggerBlazes.jpg",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4"
    },
    {
        "id": "clip_02",
        "title": "Escape Drift Run",
        "author": "speed_demon",
        "cover": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/images/ForBiggerEscapes.jpg",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerEscapes.mp4"
    },
    {
        "id": "clip_03",
        "title": "Fun Moment Highlights",
        "author": "laugh_zone",
        "cover": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/images/ForBiggerFun.jpg",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerFun.mp4"
    },
    {
        "id": "clip_04",
        "title": "Joy Explosion Clip",
        "author": "vibes_daily",
        "cover": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/images/ForBiggerJoyBlazes.jpg",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerJoyBlazes.mp4"
    },
    {
        "id": "clip_05",
        "title": "Bullrun Street Race",
        "author": "street_vids",
        "cover": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/images/WeAreGoingOnBullrun.jpg",
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/WeAreGoingOnBullrun.mp4"
    }
]

def download_file(src_url: str, dest_path: str) -> bool:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        r = requests.get(src_url, headers=headers, stream=True, timeout=15)
        if r.status_code == 200:
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=16384):
                    f.write(chunk)
            return os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000
    except Exception as e:
        print(f"[Download error] {e}")
    return False

def transcode_to_3gp(input_path: str, output_path: str) -> bool:
    # Разрешение QCIF (176x144) — идеальный аппаратный стандарт для S40, плеер сам масштабирует его в 240x320
    cmd = [
        FFMPEG_BIN, "-y",
        "-i", input_path,
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

@app.get("/", response_class=HTMLResponse)
def index(idx: int = Query(0)):
    total = len(BUILTIN_FEED)
    if idx < 0:
        idx = 0
    if idx >= total:
        idx = total - 1

    item = BUILTIN_FEED[idx]
    title = item["title"]
    author = item["author"]
    vid_id = item["id"]
    cover_url = item["cover"]
    video_url = item["url"]

    prev_idx = idx - 1
    next_idx = idx + 1

    prev_btn = f'<a href="/?idx={prev_idx}" class="btn">[&lt; Назад]</a>' if prev_idx >= 0 else '<span class="dis">[&lt; Назад]</span>'
    next_btn = f'<a href="/?idx={next_idx}" class="btn">[Вперед &gt;]</a>' if next_idx < total else '<a href="/?idx=0" class="btn">[Сначала]</a>'

    watch_href = f"/watch?id={vid_id}&src={urllib.parse.quote(video_url)}"

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
        .title {{ color:#ddd; height:24px; overflow:hidden; }}
        .card {{ display:block; text-decoration:none; background:#111; border:1px solid #333; margin:3px auto; width:220px; }}
        .cover {{ width:220px; height:170px; display:block; object-fit:cover; background:#222; }}
        .play-bar {{ background:#c00; color:#fff; font-weight:bold; font-size:12px; padding:6px; text-align:center; }}
        .nav {{ margin-top:4px; padding:2px; font-size:12px; }}
        .btn {{ color:#fff; background:#222; border:1px solid #555; padding:3px 8px; text-decoration:none; margin:0 3px; font-weight:bold; }}
        .dis {{ color:#444; padding:3px 8px; margin:0 3px; }}
        .count {{ color:#888; font-size:10px; }}
        .custom-box {{ margin-top:8px; border-top:1px solid #222; padding-top:4px; font-size:10px; }}
        .custom-box input[type="text"] {{ width:90%; font-size:10px; }}
        .custom-box input[type="submit"] {{ font-size:10px; background:#0af; border:none; color:#000; font-weight:bold; padding:2px 4px; }}
    </style>
</head>
<body>
    <div class="header">
        <span>Nokia Tok</span>
        <a href="/?idx=0">[В начало]</a>
    </div>

    <div class="meta">
        <div class="author">@{author}</div>
        <div class="title">{title}</div>
    </div>

    <a href="{watch_href}" class="card">
        <img src="{cover_url}" class="cover" alt="Превью">
        <div class="play-bar">[ СМОТРЕТЬ (ОК) ]</div>
    </a>

    <div class="nav">
        {prev_btn}
        <span class="count">{idx+1}/{total}</span>
        {next_btn}
    </div>

    <div class="custom-box">
        <form action="/watch" method="GET">
            <span>Свой MP4:</span><br>
            <input type="text" name="src" placeholder="https://site.com/video.mp4"><br>
            <input type="submit" value="Сжать в 3GP">
        </form>
    </div>
</body>
</html>"""

@app.get("/watch")
def watch(src: str = Query(...), id: str = Query(None)):
    video_url = urllib.parse.unquote(src).strip()
    
    if not id:
        id = hashlib.md5(video_url.encode()).hexdigest()[:10]

    output_3gp = os.path.join(CACHE_DIR, f"{id}.3gp")
    temp_mp4 = os.path.join(CACHE_DIR, f"{id}_temp.mp4")

    if not os.path.exists(output_3gp):
        print(f"[Transcode] Скачиваем {video_url}...")
        ok_dl = download_file(video_url, temp_mp4)
        if not ok_dl:
            raise HTTPException(status_code=400, detail="Не удалось скачать исходный ролик по ссылке")

        print(f"[Transcode] Пережимаем в 3GP...")
        ok_trans = transcode_to_3gp(temp_mp4, output_3gp)
        
        if os.path.exists(temp_mp4):
            os.remove(temp_mp4)

        if not ok_trans or not os.path.exists(output_3gp):
            raise HTTPException(status_code=500, detail="Ошибка работы кодека FFmpeg")

        print(f"[Transcode] Файл готов: {output_3gp} ({os.path.getsize(output_3gp)} байт)")

    return FileResponse(
        output_3gp,
        media_type="video/3gpp",
        filename=f"{id}.3gp"
    )
