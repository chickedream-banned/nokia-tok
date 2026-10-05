import os
import hashlib
import subprocess
import requests
import imageio_ffmpeg
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse

app = FastAPI()
CACHE_DIR = "/tmp/nokia_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

# Получаем путь к встроенному бинарнику ffmpeg
FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()

def transcode_to_3gp(input_url: str, output_path: str):
    cmd = [
        FFMPEG_BIN, "-y",
        "-i", input_url,
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

@app.get("/", response_class=HTMLResponse)
def index():
    feed_html = ""
    try:
        r = requests.get("https://www.tikwm.com/api/feed/list?region=US", timeout=6)
        if r.status_code == 200:
            data = r.json().get("data", [])
            for item in data[:8]:
                title = item.get("title", "Без названия")[:35]
                vid_id = item.get("video_id")
                play_url = item.get("play")
                if vid_id and play_url:
                    feed_html += f"""
                    <div style="border-bottom:1px solid #ccc; padding:4px 0;">
                        <div><b>{title}</b></div>
                        <a href="/watch?id={vid_id}&src={requests.utils.quote(play_url)}">[Смотреть 3GP]</a>
                    </div>
                    """
    except Exception:
        feed_html = "<div>Не удалось подтянуть тренды. Вставь ссылку вручную.</div>"

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nokia TikTok 3GP</title>
    <style>
        body {{ font-family:sans-serif; font-size:12px; margin:4px; padding:0; background:#fff; color:#000; }}
        h1 {{ font-size:14px; margin:0 0 6px 0; color:#0055aa; border-bottom:2px solid #0055aa; padding-bottom:2px; }}
        input[type="text"] {{ width:95%; font-size:11px; margin-bottom:4px; }}
        input[type="submit"] {{ background:#0055aa; color:#fff; border:none; padding:4px 8px; font-weight:bold; font-size:11px; }}
        .box {{ background:#f4f4f4; border:1px solid #ddd; padding:4px; margin-bottom:6px; }}
    </style>
</head>
<body>
    <h1>Nokia Tok 240x320</h1>
    <div class="box">
        <form action="/watch" method="GET">
            <b>Ссылка на TikTok:</b><br>
            <input type="text" name="url" placeholder="https://vm.tiktok.com/..."><br>
            <input type="submit" value="Конвертировать">
        </form>
    </div>
    <b>Тренды:</b>
    {feed_html}
</body>
</html>"""

@app.get("/watch")
def watch(url: str = Query(None), id: str = Query(None), src: str = Query(None)):
    video_url = src
    video_id = id

    if url:
        try:
            api_res = requests.post("https://www.tikwm.com/api/", data={"url": url}, timeout=8).json()
            if api_res.get("code") == 0:
                video_url = api_res["data"]["play"]
                video_id = api_res["data"]["id"]
            else:
                raise HTTPException(status_code=400, detail="Ошибка API TikWM")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка: {e}")

    if not video_url:
        raise HTTPException(status_code=400, detail="Нет ссылки на видео")

    if not video_id:
        video_id = hashlib.md5(video_url.encode()).hexdigest()

    output_file = os.path.join(CACHE_DIR, f"{video_id}.3gp")

    if not os.path.exists(output_file):
        ok = transcode_to_3gp(video_url, output_file)
        if not ok or not os.path.exists(output_file):
            raise HTTPException(status_code=500, detail="Ошибка сжатия через FFmpeg")

    return FileResponse(
        output_file,
        media_type="video/3gpp",
        filename=f"{video_id}.3gp"
    )
