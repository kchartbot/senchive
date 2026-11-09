"""사진/영상 단위 라우팅: 얼굴 2명 이상 -> 센둥이 모음집, 1명 -> 가장 닮은 멤버 (읽기 전용, 업로드 안 함).
기준 얼굴 = fan_sets.json 의 seeds (제목으로 확정된 글) 중 얼굴이 1명인 사진. 결과: out/route/route.json + 확인용 시트."""
import json, os, subprocess
from pathlib import Path
import numpy as np, torch
from PIL import Image, ImageDraw, ImageFont
from facenet_pytorch import MTCNN, InceptionResnetV1

SRC = Path(os.environ.get("SRC", "out/fan")); OUT = Path("out/route"); OUT.mkdir(parents=True, exist_ok=True)
cfg = json.load(open(Path(__file__).with_name("fan_sets.json"), encoding="utf-8"))
EX = set(json.load(open(Path(__file__).with_name("exclude_media.json"), encoding="utf-8")))
info = {str(e["no"]): e for e in json.load(open(SRC / "info.json", encoding="utf-8"))}
mtcnn = MTCNN(keep_all=True, device="cpu", min_face_size=24, thresholds=[0.6, 0.7, 0.8], post_process=True)
net = InceptionResnetV1(pretrained="vggface2").eval()
MINFRAC = float(os.environ.get("MINFRAC", "0.12"))  # 얼굴 높이가 화면의 이 비율 이상이어야 '주인공급' 얼굴로 센다

def frames(f, n=4):
    f = str(f)
    if f.endswith(".mp4"):
        tmp = OUT / "_fr"; tmp.mkdir(exist_ok=True)
        for x in tmp.glob("*"): x.unlink()
        subprocess.run(["ffmpeg", "-v", "error", "-i", f, "-vf", "fps=1", "-frames:v", str(n), str(tmp / "f%02d.jpg")], capture_output=True)
        return [Image.open(x).convert("RGB") for x in sorted(tmp.glob("f*.jpg"))]
    im = Image.open(f); fr = []
    try:
        k = getattr(im, "n_frames", 1); step = max(1, k // n)
        for i in range(0, k, step):
            im.seek(i); fr.append(im.convert("RGB").copy())
            if len(fr) >= n: break
    except Exception: fr = [im.convert("RGB")]
    return fr

@torch.no_grad()
def faces(im):
    """(상자, 임베딩) 목록 - 주인공급 얼굴만"""
    boxes, probs = mtcnn.detect(im)
    if boxes is None: return []
    H = im.size[1]; out = []
    for b, p in zip(boxes, probs):
        if p is None or p < 0.9 or (b[3] - b[1]) < H * MINFRAC: continue
        crop = im.crop(tuple(int(v) for v in b)).resize((160, 160))
        x = torch.from_numpy(np.asarray(crop)).permute(2, 0, 1).float()
        x = (x - 127.5) / 128.0
        e = net(x.unsqueeze(0))[0].numpy(); out.append((b, e / np.linalg.norm(e)))
    return out

items = []
for g, nos in cfg["sets"].items():
    for n in nos:
        for x in info[str(n)]["files"]:
            stem = os.path.splitext(x["file"])[0].replace("_i", "_")
            if stem in EX: continue
            items.append(dict(group=g, no=n, stem=stem, file=x["file"]))
seedset = {n: m for m, ns in cfg["seeds"].items() for n in ns}
data = {}
for it in items:
    res = []
    for im in frames(SRC / it["file"]):
        res.append((im, faces(im)))
    data[it["stem"]] = res
    print("얼굴", it["stem"], [len(f) for _, f in res])

ref = {}
for it in items:
    m = seedset.get(it["no"])
    if not m: continue
    for im, fs in data[it["stem"]]:
        if len(fs) == 1: ref.setdefault(m, []).append(fs[0][1])
print("기준 얼굴 수", {m: len(v) for m, v in ref.items()})
R = {m: np.stack(v) for m, v in ref.items()}

def who(e, skip_stem=None):
    sc = {}
    for m, arr in R.items():
        s = np.sort(arr @ e)[::-1][:3]; sc[m] = float(s.mean())
    srt = sorted(sc.items(), key=lambda t: -t[1])
    return srt[0][0], srt[0][1] - srt[1][1], srt[0][1], sc

# 기준 사진 자체 검증(자기 자신 제외 불가하므로 참고용), 라우팅
routes = []
for it in items:
    fr = data[it["stem"]]
    nface = max((len(fs) for _, fs in fr), default=0)
    votes = {}; margins = []
    for _, fs in fr:
        if len(fs) == 1:
            m, mg, top, sc = who(fs[0][1]); votes[m] = votes.get(m, 0) + 1; margins.append(mg)
    if nface >= 2: dest, why = "모음", f"얼굴 {nface}명"
    elif nface == 0: dest, why = "모음", "얼굴 없음/작음 (미확인)"
    else:
        m = max(votes, key=votes.get); mg = float(np.mean(margins))
        dest, why = (m, f"1명 → {m} (차이 {mg:.2f})") if mg >= 0.03 else ("모음", f"1명이지만 구분 애매 (차이 {mg:.2f}, 후보 {m})")
    routes.append(dict(it, dest=dest, why=why, faces=nface, votes=votes))
    print("라우팅", it["stem"], it["group"], "→", dest, "|", why)
json.dump(routes, open(OUT / "route.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

try: F = ImageFont.truetype("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", 12)
except Exception: F = None
cols, w, h = 6, 156, 190
for k in range(0, len(routes), 30):
    part = routes[k:k + 30]; rows = (len(part) + cols - 1) // cols
    s = Image.new("RGB", (cols * w, rows * (h + 26)), "white"); d = ImageDraw.Draw(s)
    for i, r in enumerate(part):
        im = data[r["stem"]][0][0].copy(); im.thumbnail((w - 4, h - 4))
        x = (i % cols) * w; y = (i // cols) * (h + 26); s.paste(im, (x, y + 26))
        d.text((x + 2, y), r["stem"], fill="black", font=F); d.text((x + 2, y + 12), f"{r['group']}→{r['dest']} ({r['faces']})", fill="red", font=F)
    s.save(OUT / f"route_{k // 30}.jpg", quality=80)
