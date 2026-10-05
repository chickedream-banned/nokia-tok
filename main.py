import os
import re
import html
import random
import hashlib
import subprocess
import urllib.parse
import requests
import imageio_ffmpeg
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse

app = FastAPI()
CACHE_DIR = "/tmp/nokia_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()

# Пул проверенных открытых каналов с короткими видео без мусора
CHANNELS_POOL = [
    "Fun_vidos",
    "memreels",
    "reels_memes",
    "vine_video",
    "ru_tik_tok",
    "tiktok_vines",
    "humor_reels",
    "tik_tok_vids",
    "reels_tiktok_top",
    "tiktok_ru_top",
    "videoprikol",
    "memvideo",
    "tiktok_prikoly",
    "shuriki_vines",
    "funny_tik_toks",
    "cats_vines",
    "animal_reels",
    "failarmy_tg",
    "best_vines_ever",
    "shorts_reels_tt",
    "memes_video_tg",
    "top_tik_tok_clips",
    "laugh_clips",
    "reels_humor",
    "tiktok_hype_clips"
]

FEED_DECK = []

def transcode_to_3gp(input_path: str, output_path: str) -> bool:
    """Сжатие в 3GP (QCIF 176x144, 15 FPS) под родной плеер S40"""
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

def parse_tg_page(html_text: str, ch_name: str, collector: dict):
    posts = re.split(r'<div class="tgme_widget_message\s+', html_text)
    min_post_num = None

    for post in posts[1:]:
        id_match = re.search(r'data-post=["\']' + re.escape(ch_name) + r'/(\d+)["\']', post)
        if id_match:
            post_num = int(id_match.group(1))
            if min_post_num is None or post_num < min_post_num:
                min_post_num = post_num

        video_match = re.search(r'<video[^>]+src=["\']([^"\']+)["\']', post)
        if not video_match:
            continue

        video_url = video_match.group(1)
        if video_url in collector:
            continue

        raw_id = id_match.group(1) if id_match else hashlib.md5(video_url.encode()).hexdigest()[:8]
        post_id = f"{ch_name}_{raw_id}"

        thumb_match = re.search(r'tgme_widget_message_video_thumb[^"\']*style=["\'][^"\']*url\([\'"]?([^\'"]+)[\'"]?\)', post)
        cover_url = thumb_match.group(1) if thumb_match else ""

        text_match = re.search(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', post, re.DOTALL)
        if text_match:
            raw_text = re.sub(r'<[^>]+>', '', text_match.group(1)).strip()
            title = html.unescape(raw_text).replace("\n", " ")[:36]
        else:
            title = f"Ролик @{ch_name}"

        collector[video_url] = {
            "id": post_id,
            "title": title or "Короткое видео",
            "channel": ch_name,
            "video_url": video_url,
            "cover": cover_url
        }

    return min_post_num

def fetch_single_channel(ch: str, collected: dict, headers: dict):
    try:
        url1 = f"https://t.me/s/{ch}"
        r1 = requests.get(url1, headers=headers, timeout=5)
        if r1.status_code == 200:
            min_id = parse_tg_page(r1.text, ch, collected)
            if min_id and min_id > 15:
                url2 = f"https://t.me/s/{ch}?before={min_id}"
                r2 = requests.get(url2, headers=headers, timeout=5)
                if r2.status_code == 200:
                    parse_tg_page(r2.text, ch, collected)
    except Exception as e:
        print(f"[Error fetching @{ch}]: {e}")

def build_random_feed():
    global FEED_DECK
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    collected = {}
    # Выбираем случайные 7 каналов из пула для быстрой загрузки
    selected = random.sample(CHANNELS_POOL, min(len(CHANNELS_POOL), 7))

    with ThreadPoolExecutor(max_workers=5) as executor:
        for ch in selected:
            executor.submit(fetch_single_channel, ch, collected, headers)

    items = list(collected.values())
    random.shuffle(items)
    FEED_DECK = items
    print(f"[Deck Ready] Загружено роликов: {len(FEED_DECK)}")
    return FEED_DECK

@app.get("/", response_class=HTMLResponse)
def index(idx: int = Query(0), shuffle: int = Query(0)):
    global FEED_DECK
    if shuffle == 1 or len(FEED_DECK) == 0:
        build_random_feed()

    total = len(FEED_DECK)
    if total == 0:
        return """<!DOCTYPE html><html><body style="font-family:sans-serif;font-size:12px;padding:8px;background:#000;color:#fff;text-align:center;">
        <b>Nokia Tok</b><br><br>
        Не удалось собрать ролики.<br><br>
        <a href="/?shuffle=1" style="color:#0af;">[Повторить поиск]</a>
        </body></html>"""

    if idx < 0:
        idx = 0
    if idx >= total:
        idx = total - 1

    item = FEED_DECK[idx]
    title = item["title"]
    channel = item["channel"]
    post_id = item["id"]
    video_url = item["video_url"]
    cover_url = item["cover"]

    prev_idx = idx - 1
    next_idx = idx + 1

    prev_btn = f'<a href="/?idx={prev_idx}" class="btn">[&lt; Назад]</a>' if prev_idx >= 0 else '<span class="dis">[&lt; Назад]</span>'
    next_btn = f'<a href="/?idx={next_idx}" class="btn">[Вперед &gt;]</a>' if next_idx < total else '<a href="/?shuffle=1" class="btn">[Перемешать]</a>'

    watch_href = f"/watch?id={post_id}&src={urllib.parse.quote(video_url)}"
    img_tag = f'<img src="{cover_url}" class="cover" alt="Превью">' if cover_url else '<div class="no-cover">Видео</div>'

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nokia Tok ({idx+1}/{total})</title>
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
        <span>Nokia Tok [Random]</span>
        <a href="/?shuffle=1">[Перемешать]</a>
    </div>

    <div class="meta">
        <div class="author">@{channel}</div>
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
            raise HTTPException(status_code=400, detail="Ошибка загрузки видеофайла")

        with open(temp_mp4, "wb") as f:
            for chunk in r.iter_content(chunk_size=32768):
                f.write(chunk)

        ok = transcode_to_3gp(temp_mp4, output_3gp)

        if os.path.exists(temp_mp4):
            os.remove(temp_mp4)

        if not ok or not os.path.exists(output_3gp):
            raise HTTPException(status_code=500, detail="Ошибка сжатия видео через FFmpeg")

    return FileResponse(
        output_3gp,
        media_type="video/3gpp",
        filename=f"{id}.3gp"
    )
