"""compose 결과(cd/<event>/post.json)를 디시에 실제 글로 올린다. 제목 + (유튜브 링크) + 움짤/사진. mp4 는 올리지 않고 gif 로 바꿔 올린다."""
import json, os, sys, json, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from chartbot.dcinside import DcUploader, HumanCheckRequired, SubmitUncertain, UploadFailed

event = os.environ.get("EVENT_NAME", "인기가요")
base = Path(os.environ.get("CD_DIR", "cd")) / event
d = json.load(open(base / "post.json", encoding="utf-8"))
out = Path("out"); out.mkdir(exist_ok=True)
MAXN = int(os.environ.get("MAX_FILES", "50"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

def to_webp(src, dst):
    """mp4 -> 움직이는 webp. 원본 fps/크기 그대로(길이 제한 없음), 18MB 를 넘으면 품질 -> 크기 순으로 낮춘다."""
    for q, w in ((80, 0), (70, 0), (60, 0), (60, 600), (50, 480)):
        vf = (f"scale='min({w},iw)':-2:flags=lanczos" if w else "null")  # 원본 fps 그대로 (60fps 원본도 낮추지 않음)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf", vf, "-c:v", "libwebp", "-lossless", "0",
                        "-q:v", str(q), "-loop", "0", "-an", "-fps_mode", "passthrough", str(dst)], check=True)
        if dst.stat().st_size <= 18_000_000:
            break
    return dst

from find_stage import find
ev_kw = [event, "인기가요", "인가"] if event == "인기가요" else [event]
links = [x["url"] if isinstance(x, dict) else x for x in (d.get("stage_links") or [])] or (find(ev_kw) if not os.environ.get("NO_YT_SEARCH") else [])
links = [l for l in (os.environ.get("LINKS", "").replace(",", " ").split()) if l] + [l for l in links if l not in os.environ.get("LINKS", "")]
files = []
allm = [base / "media" / m["file"] for m in d["media"]]
for f in allm:
    if f.suffix.lower() == ".mp4":
        f = to_webp(f, out / (f.stem + ".webp"))
    files.append(f)
if d.get("media_kind") == "움짤" and not files:
    sys.exit("올릴 움짤 없음")
if os.environ.get("INCLUDE"):
    inc = [x.strip() for x in os.environ["INCLUDE"].split(",") if x.strip()]
    files = [f for f in files if f.stem in inc]
    print("선택한 파일만:", [f.name for f in files])
_ex = set(json.load(open(Path(__file__).with_name("exclude_media.json"), encoding="utf-8"))) if Path(__file__).with_name("exclude_media.json").exists() else set()
if _ex:
    _n = len(files); files = [f for f in files if f.stem not in _ex]
    if len(files) != _n: print("제외한 파일(밈/캡처 등):", _n - len(files))
files = files[:MAXN]
body = "\n".join(links)
if os.environ.get("RAW_TITLE"): d["title"] = event   # 제목은 입력한 그대로 쓴다
elif not links: d["title"] = d["title"].replace("링크+", "")
if links and not files and not os.environ.get("RAW_TITLE"): d["title"] = d["title"].replace("링크+짤 모음", "링크 모음")   # 짤이 없으면 짤 문구 제거
if not links and not files: sys.exit("링크도 짤도 없어 올리지 않음")
print("제목:", d["title"], "| 링크", links, "| 파일", len(files), [f.name for f in files])
if os.environ.get("DRY_RUN", "true").lower() != "false":
    print("DRY_RUN: 올리지 않음"); sys.exit(0)
up = DcUploader(
    gallery_id=os.environ["DC_GALLERY_ID"], headtext=os.environ.get("DC_HEADTEXT", ""),
    profile_dir="~/.senchive/profile", minor=os.environ.get("DC_MINOR", "true").lower() == "true",
    storage_state=str(out / ".dc_session.json"), login_id=os.environ.get("DC_ID"), login_pw=os.environ.get("DC_PW"),
    kind=os.environ.get("DC_KIND") or None)
try:
    up.post(d["title"], body, files[0], out, extra_files=files[1:], body_first=True)
    print("게시 완료")
except HumanCheckRequired as e:
    sys.exit("중단(사람 확인 요구, 우회하지 않음): " + str(e))
except (SubmitUncertain, UploadFailed) as e:
    sys.exit("실패: " + str(e))
