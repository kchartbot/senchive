"""업로드 테스트: 사진 1 + mp4 1 을 테스트 갤러리에 올린다. DRY_RUN=true 면 올리지 않고 준비만 확인."""
import os, sys, glob
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from chartbot.dcinside import DcUploader, HumanCheckRequired, SubmitUncertain, UploadFailed

MEDIA = Path(os.environ.get("MEDIA_DIR", "cd/인기가요/media"))
files = sorted(MEDIA.glob("*"))
img = next((f for f in files if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")), None)
vid = next((f for f in files if f.suffix.lower() == ".mp4" and f.stat().st_size < 8_000_000), None)
print("사진:", img, "| 움짤:", vid, "| 후보", len(files))
if not img or not vid:
    sys.exit("테스트용 파일 없음")
import subprocess
def to_gif(src, dst):
    vf = "fps=12,scale='min(480,iw)':-2:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-t", "6", "-i", str(src), "-vf", vf, str(dst)], check=True)
    return dst
Path("out").mkdir(exist_ok=True)
gif = to_gif(vid, Path("out/clip.gif"))
print("gif 변환:", gif.stat().st_size, "B")
title = "[테스트] 업로드 확인 - 곧 삭제"
dry = os.environ.get("DRY_RUN", "true").lower() != "false"
if dry:
    print("DRY_RUN: 올리지 않음. 제목:", title, "갤러리:", os.environ.get("DC_GALLERY_ID"), os.environ.get("DC_KIND"))
    sys.exit(0)
out = Path("out"); out.mkdir(exist_ok=True)
up = DcUploader(
    gallery_id=os.environ["DC_GALLERY_ID"], headtext=os.environ.get("DC_HEADTEXT", ""),
    profile_dir="~/.senchive/profile", minor=os.environ.get("DC_MINOR", "true").lower() == "true",
    storage_state=str(out / ".dc_session.json"), login_id=os.environ.get("DC_ID"), login_pw=os.environ.get("DC_PW"),
    kind=os.environ.get("DC_KIND") or None)
try:
    up.post(title, "업로드 테스트입니다. 확인 후 삭제합니다.", img, out, extra_files=[gif])
    print("게시 완료")
except HumanCheckRequired as e:
    sys.exit("중단(사람 확인 요구, 우회하지 않음): " + str(e))
except (SubmitUncertain, UploadFailed) as e:
    sys.exit("실패: " + str(e))
