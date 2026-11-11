"""유튜브 링크 / mp4 -> 디시콘용 움짤 세트(+문구) 자동 생성.
사용: python tools/con_maker.py <유튜브링크 또는 mp4경로> [--out out/con] [--count 8] ...
규격(크기/용량/길이)은 전부 옵션이라 디시 규격에 맞게 바꿀 수 있다."""
import argparse, json, os, random, re, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path

import numpy as np

PHRASES = ["ㅋㅋㅋ", "헉", "레전드", "심쿵", "미쳤다", "귀엽다", "인정", "찢었다", "대박", "아 진짜", "사랑해", "최고"]
FONTS = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
         "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", "C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf",
         "/System/Library/Fonts/AppleSDGothicNeo.ttc", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"]


NOWIN = 0x08000000 if os.name == "nt" else 0   # 윈도우에서 검은 창이 번쩍이지 않게


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, creationflags=NOWIN, **kw)


def find_font(custom=None):
    for f in ([custom] if custom else []) + FONTS:
        if f and Path(f).exists(): return f
    return None


def fetch(src, work):
    """링크면 yt-dlp 로 받고(자막 포함), 파일이면 그대로 쓴다. -> (영상경로, 자막경로|None)"""
    if not re.match(r"https?://", src):
        p = Path(src)
        if not p.exists(): sys.exit("파일이 없습니다: " + src)
        return p, None
    ytd = [sys.executable, "--ytdlp"] if getattr(sys, "frozen", False) else [sys.executable, "-m", "yt_dlp"]
    cmd = ytd + ["-f", "bv*[height<=720]+ba/b[height<=720]/b", "--merge-output-format", "mp4",
           "--write-subs", "--write-auto-subs", "--sub-langs", "ko.*,ko", "--sub-format", "vtt", "--no-playlist",
           "-o", str(work / "src.%(ext)s"), src]
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NOWIN, encoding="utf-8", errors="replace", env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    vids = sorted(work.glob("src.mp4")) or [p for p in work.glob("src.*") if p.suffix in (".mp4", ".mkv", ".webm")]
    if not vids:
        sys.exit("다운로드 실패(유튜브가 막았을 수 있음 - PC에서 실행하거나 mp4를 직접 쓰세요):\n" + (r.stderr or "")[-600:])
    subs = sorted(work.glob("src*.vtt"))
    return vids[0], (subs[0] if subs else None)


def probe(v):
    j = json.loads(run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height", "-of", "json", str(v)]).stdout)
    s = next((x for x in j["streams"] if x.get("width")), {})
    return float(j["format"]["duration"]), int(s["width"]), int(s["height"])


def motion_series(v, fps=4):
    """저해상도 흑백 프레임 차이(움직임) + 급격한 컷 위치. 초당 fps 개 샘플."""
    W, H = 64, 36
    raw = run(["ffmpeg", "-v", "error", "-i", str(v), "-vf", f"fps={fps},scale={W}:{H},format=gray", "-f", "rawvideo", "-"]).stdout
    fr = np.frombuffer(raw, np.uint8)
    n = len(fr) // (W * H)
    fr = fr[: n * W * H].reshape(n, W * H).astype(np.float32)
    d = np.abs(np.diff(fr, axis=0)).mean(axis=1) if n > 1 else np.zeros(1)
    return np.concatenate([[0], d])


def audio_series(v, fps=4):
    raw = run(["ffmpeg", "-v", "error", "-i", str(v), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"]).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768 if raw else np.zeros(1)
    step = 8000 // fps
    n = len(a) // step
    if n == 0: return np.zeros(1)
    return np.sqrt((a[: n * step].reshape(n, step) ** 2).mean(axis=1))


def pick_segments(v, length, count, fps=4):
    dur = probe(v)[0]
    m, a = motion_series(v, fps), audio_series(v, fps)
    n = min(len(m), len(a)) or len(m)
    m, a = m[:n], (a[:n] if len(a) >= n else np.pad(a, (0, n - len(a))))
    cut_thr = max(25.0, float(np.percentile(m, 98)) * 1.2)
    nm, na = m / (m.max() or 1), a / (a.max() or 1)
    score = 0.6 * nm + 0.4 * na
    w = max(2, int(length * fps))
    cand = []
    for i in range(0, max(1, n - w)):
        seg = slice(i, i + w)
        if (m[i + 1: i + w] > cut_thr).any(): continue          # 중간에 장면 컷이 있으면 콘이 어색하다
        if m[seg].mean() < 1.0: continue                         # 거의 정지 화면은 제외
        cand.append((float(score[seg].mean()), i / fps))
    cand.sort(reverse=True)
    chosen = []
    for sc, t in cand:
        if all(abs(t - c) >= length * 1.2 for _, c in chosen): chosen.append((sc, t))
        if len(chosen) >= count: break
    return sorted(c for _, c in chosen), dur


def parse_vtt(p):
    cues = []
    if not p or not Path(p).exists(): return cues
    def sec(s):
        h, m, x = s.replace(",", ".").split(":") if s.count(":") == 2 else ("0", *s.replace(",", ".").split(":"))
        return int(h) * 3600 + int(m) * 60 + float(x)
    blocks = re.split(r"\n\s*\n", Path(p).read_text(encoding="utf-8", errors="ignore"))
    for b in blocks:
        m = re.search(r"([\d:.]+)\s*-->\s*([\d:.]+)", b)
        if not m: continue
        txt = " ".join(l for l in b.splitlines()[1:] if "-->" not in l)
        txt = re.sub(r"<[^>]+>|\[[^\]]*\]|♪", "", txt).strip()
        if txt: cues.append((sec(m.group(1)), sec(m.group(2)), txt))
    return cues


def clean_caption(t, maxc):
    t = re.sub(r"\s+", " ", t).strip(" .,!?~")
    if len(t) <= maxc: return t
    cut = t[:maxc]
    return cut.rsplit(" ", 1)[0] if " " in cut[maxc // 2:] else cut


def claude_caption(lines, maxc):
    """ANTHROPIC_API_KEY 가 있을 때만 사용. 자막을 보고 짧은 반응 문구를 만든다. 실패하면 None."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key: return None
    try:
        import requests
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=30,
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                          json={"model": os.environ.get("CON_MODEL", "claude-haiku-5-5"), "max_tokens": 60,
                                "messages": [{"role": "user", "content": f"걸그룹 영상 구간의 자막: {' / '.join(lines) or '(없음)'}\n이 장면에 어울리는 디시콘 문구를 {maxc}자 이내로 한 줄만 써줘. 따옴표·설명 없이 문구만."}]})
        t = r.json()["content"][0]["text"].strip().splitlines()[0].strip("\"'“” ")
        return clean_caption(t, maxc) or None
    except Exception:
        return None


def make_caption(i, t0, length, cues, mode, maxc):
    if mode == "none": return "", "none"
    inside = [c[2] for c in cues if c[1] > t0 and c[0] < t0 + length]
    seen, lines = set(), []
    for x in inside:
        if x not in seen: seen.add(x); lines.append(x)
    cc = claude_caption(lines, maxc) if mode in ("auto", "claude") else None
    if cc: return cc, "claude"
    if lines and mode != "phrase":
        best = min(lines, key=lambda s: abs(len(s) - maxc * 0.6))
        c = clean_caption(best, maxc)
        if c: return c, "subtitle"
    return random.Random(i * 7919 + int(t0)).choice(PHRASES), "phrase"


def make_alt(cap, i):
    """디시콘 알트값(연상 단어): 1~3자. 문구의 첫 단어를 3자로 줄이고, 없으면 고정 단어."""
    w = re.sub(r"[^\w*^!~+]", "", (cap or "").split(" ")[0])[:3]
    return w or random.Random(i).choice(["ㅋㅋ", "헉", "굿", "대박"])


def face_center(v, t0, length, W, H):
    """구간 안에서 얼굴이 가장 크게 잡히는 위치를 중심으로 쓴다. 못 찾으면 정중앙."""
    try:
        import cv2
        xml = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        if not xml.exists(): return W / 2, H / 2
        casc = cv2.CascadeClassifier(str(xml))
        cap_pts = []
        for k in (0.2, 0.5, 0.8):
            raw = run(["ffmpeg", "-v", "error", "-ss", f"{t0 + length * k:.2f}", "-i", str(v), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"]).stdout
            img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
            if img is None: continue
            for (x, y, w, h) in casc.detectMultiScale(img, 1.1, 5, minSize=(max(30, H // 12),) * 2):
                cap_pts.append((w * h, x + w / 2, y + h / 2))
        if cap_pts:
            _, cx, cy = max(cap_pts)
            return cx, cy
    except Exception:
        pass
    return W / 2, H / 2


def render(v, t0, length, W, H, center, size, fps, colors, caption, font, out, fontsize):
    s = min(W, H)
    cx = min(max(center[0] - s / 2, 0), W - s)
    cy = min(max(center[1] - s / 2 - s * 0.05, 0), H - s)   # 얼굴이 약간 위쪽에 오게
    vf = f"crop={s}:{s}:{int(cx)}:{int(cy)},fps={fps},scale={size}:{size}:flags=lanczos"
    tmp = Path(tempfile.mkdtemp())
    if caption and font:
        (tmp / "t.txt").write_text(caption, encoding="utf-8")
        shutil.copy(font, tmp / ("f" + Path(font).suffix))
        vf += f",drawtext=fontfile=f{Path(font).suffix}:textfile=t.txt:fontsize={fontsize}:fontcolor=white:borderw=3:bordercolor=black:x=(w-text_w)/2:y=h-text_h-{max(4, size // 20)}"
    pal = tmp / "p.png"
    base = ["ffmpeg", "-v", "error", "-y", "-ss", f"{t0:.2f}", "-t", f"{length:.2f}", "-i", str(v)]
    run(base + ["-vf", f"{vf},palettegen=max_colors={colors}:stats_mode=diff", str(pal)], cwd=str(tmp))
    run(base + ["-i", str(pal), "-lavfi", f"{vf}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4", "-loop", "0", str(Path(out).resolve())], cwd=str(tmp))
    shutil.rmtree(tmp, ignore_errors=True)


def build(i, v, t0, a, W, H, center, caption, font, out):
    """용량 제한(max_kb)을 넘으면 색 -> fps -> 크기 순으로 낮춘다."""
    steps = [(a.size, a.fps, 128), (a.size, a.fps, 64), (a.size, max(8, a.fps - 3), 64), (a.size, max(8, a.fps - 5), 48),
             (int(a.size * 0.85), max(8, a.fps - 5), 48), (int(a.size * 0.7), 8, 32)]
    for size, fps, colors in steps:
        render(v, t0, a.length, W, H, center, size, fps, colors, caption, font, out, max(12, int(size * 0.14)))
        if out.stat().st_size <= a.max_kb * 1024: return size, fps, colors
    return size, fps, colors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", default="out/con")
    ap.add_argument("--count", type=int, default=10, help="만들 콘 개수(디시콘 등록은 최소 10개, 최대 200개)")
    ap.add_argument("--length", type=float, default=2.5, help="콘 하나의 길이(초)")
    ap.add_argument("--size", type=int, default=200, help="가로=세로 픽셀(디시 규격에 맞추기)")
    ap.add_argument("--max-kb", type=int, default=500, help="콘 하나 최대 용량 KB(디시 규격은 2MB 이하)")
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--text", default="auto", choices=["auto", "subtitle", "phrase", "claude", "none"], help="문구 방식")
    ap.add_argument("--maxc", type=int, default=6, help="문구 최대 글자수")
    ap.add_argument("--font", default=None)
    ap.add_argument("--start", type=float, default=0, help="이 시각(초) 이후만 사용")
    ap.add_argument("--end", type=float, default=0, help="이 시각(초) 이전만 사용(0=끝까지)")
    a = ap.parse_args()

    out = Path(a.out); shutil.rmtree(out, ignore_errors=True); out.mkdir(parents=True)
    work = Path(tempfile.mkdtemp(prefix="con_"))
    v, vtt = fetch(a.src, work)
    if a.start or a.end:
        cut = work / "cut.mp4"
        cmd = ["ffmpeg", "-v", "error", "-y", "-ss", str(a.start), "-i", str(v)] + (["-t", str(a.end - a.start)] if a.end else []) + ["-c", "copy", str(cut)]
        run(cmd); cues_off = a.start; v = cut
    else:
        cues_off = 0
    dur, W, H = probe(v)
    cues = [(s - cues_off, e - cues_off, t) for s, e, t in parse_vtt(vtt)]
    font = find_font(a.font)
    if a.text != "none" and not font: print("경고: 한글 글꼴을 못 찾아 문구를 넣지 못합니다(--font 로 지정).")
    segs, _ = pick_segments(v, a.length, a.count)
    if not segs: sys.exit("콘으로 쓸 만한 구간을 못 찾았습니다(영상이 너무 짧거나 거의 정지 화면).")
    print(f"영상 {dur:.0f}초 {W}x{H}, 구간 {len(segs)}개 선택")
    items = []
    for i, t0 in enumerate(segs, 1):
        cap, how = make_caption(i, t0, a.length, cues, a.text, a.maxc)
        center = face_center(v, t0, a.length, W, H)
        f = out / f"con_{i:02d}.gif"
        size, fps, colors = build(i, v, t0, a, W, H, center, cap if font else "", font, f)
        items.append(dict(file=f.name, alt=make_alt(cap, i), start=round(t0 + a.start, 1), caption=cap, caption_by=how, kb=round(f.stat().st_size / 1024), size=size, fps=fps))
        print(f"  {f.name}  {t0 + a.start:6.1f}s  {items[-1]['kb']}KB  [{how}] {cap}")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(out / items[0]["file"]), "-frames:v", "1", str(out / "대표.png")], creationflags=NOWIN)   # 대표 디시콘(png, 200x200 이상, 1MB 이하)
    (out / "index.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    rows = "".join(f'<figure><img src="{x["file"]}" width="{x["size"]}"><figcaption>{x["file"]} · {x["kb"]}KB<br>문구: {x["caption"]}<br>알트: {x["alt"]}</figcaption></figure>' for x in items)
    (out / "preview.html").write_text(f'<meta charset="utf-8"><style>body{{font:14px sans-serif;background:#222;color:#ddd}}figure{{display:inline-block;margin:8px;text-align:center}}</style>{rows}', encoding="utf-8")
    with zipfile.ZipFile(out / "dccon.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for x in items: z.write(out / x["file"], x["file"])
        z.write(out / "대표.png", "대표.png")
    if len(items) < 10: print("참고: 디시콘 등록은 10개 이상이 필요합니다. --count 를 늘리거나 영상을 더 긴 걸 쓰세요.")
    shutil.rmtree(work, ignore_errors=True)
    print("완료:", out)


if __name__ == "__main__":
    main()
