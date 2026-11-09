"""확실한 팬싸 글(제목 = 멤버 1명 + 팬싸/출근/퇴근)의 짤을 기준으로 다른 글의 짤을 비교한다 (읽기 전용).
- 오늘 팬싸 여부: 화면 전체(배경 + 의상) DINOv2 유사도, 기준 글과 가장 가까운 값
- 멤버: 얼굴 아래 몸통(의상) DINOv2 + 색 분포, 멤버별 기준 중 가장 가까운 값 (기준 글 수에 치우치지 않게 최근접 1개)
- 여러 명: 얼굴마다 멤버를 따로 판정, 2명 이상이면 센둥이 모음집
입력: out/fan/info.json + 파일 (fansign-scan 결과)   출력: out/match/match.json, sheet_*.jpg
"""
import json, os, re, subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np, torch, cv2
from transformers import AutoImageProcessor, AutoModel

SRC = Path(os.environ.get("SRC", "out/fan")); OUT = Path("out/match"); OUT.mkdir(parents=True, exist_ok=True)
info = json.load(open(SRC / "info.json", encoding="utf-8"))
SEED_KW = re.compile(r"팬싸|팬사|사인회|출근|퇴근")
COMMUTE = re.compile(r"출근|퇴근")
proc = AutoImageProcessor.from_pretrained("facebook/dinov2-small")
model = AutoModel.from_pretrained("facebook/dinov2-small").eval()
try: face = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
except Exception as ex: print("얼굴 검출 사용 불가", ex); face = None
try: FONT = ImageFont.truetype("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", 13)
except Exception: FONT = None

def frames(f, n=6):
    f = Path(f)
    if f.suffix == ".mp4":
        tmp = OUT / "_fr"; tmp.mkdir(exist_ok=True)
        for x in tmp.glob("*"): x.unlink()
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-vf", "fps=1", "-frames:v", str(n), str(tmp / "f%02d.jpg")], capture_output=True)
        return [Image.open(x).convert("RGB") for x in sorted(tmp.glob("f*.jpg"))]
    im = Image.open(f); fr = []
    try:
        k = getattr(im, "n_frames", 1); step = max(1, k // n)
        for i in range(0, k, step):
            im.seek(i); fr.append(im.convert("RGB").copy())
            if len(fr) >= n: break
    except Exception:
        fr = [im.convert("RGB")]
    return fr

def detect(im):
    """얼굴 상자 목록 (큰 것부터). 너무 작은 얼굴(가장 큰 얼굴의 40% 미만)은 버린다."""
    if face is None: return []
    g = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2GRAY); s = min(1.0, 640 / max(g.shape))
    if s < 1: g = cv2.resize(g, None, fx=s, fy=s)
    fs = sorted(([int(v / s) for v in b] for b in face.detectMultiScale(g, 1.1, 6, minSize=(28, 28))), key=lambda b: -b[2])
    return [b for b in fs if b[2] >= fs[0][2] * 0.4] if fs else []

def torso(im, b):
    W, H = im.size; x, y, w, h = b
    box = (max(0, x - w), min(H - 1, y + int(h * 1.1)), min(W, x + 2 * w), min(H, y + int(h * 4.5)))
    return im.crop(box) if box[3] - box[1] > h and box[2] - box[0] > w else None

def center(im):
    W, H = im.size; return im.crop((int(W * .25), int(H * .3), int(W * .75), int(H * .95)))

@torch.no_grad()
def emb(ims):
    out = []
    for k in range(0, len(ims), 16):
        x = proc(images=ims[k:k + 16], return_tensors="pt")
        e = model(**x).last_hidden_state[:, 0]; out.append(torch.nn.functional.normalize(e, dim=-1).numpy())
    return np.concatenate(out) if out else np.zeros((0, 384))

def hist(im):
    hsv = cv2.cvtColor(np.array(im.resize((64, 64))), cv2.COLOR_RGB2HSV)
    h = cv2.calcHist([hsv], [0, 1], None, [12, 4], [0, 180, 0, 256]).flatten(); return h / (h.sum() or 1)

post = {}
for e in info:
    fr = []
    for x in e["files"]:
        try: fr += frames(SRC / x["file"])
        except Exception as ex: print("프레임 실패", x["file"], ex)
    if not fr: continue
    tm = e["title_members"]; seed = len(tm) == 1 and bool(SEED_KW.search(e["title"]))
    crops = []  # (프레임 번호, 몸통 이미지)
    nf = 0
    for i, im in enumerate(fr):
        bs = detect(im); nf = max(nf, len(bs))
        if seed: bs = bs[:1]  # 기준 글은 주인공(가장 큰 얼굴)만
        cs = [c for c in (torso(im, b) for b in bs) if c is not None] or [center(im)]
        crops += [(i, c) for c in cs]
    post[e["no"]] = dict(e=e, fr=fr, full=emb(fr), crops=crops, ce=emb([c for _, c in crops]), ch=np.array([hist(c) for _, c in crops]),
                         faces=nf, seed=seed, kind=("출퇴근" if COMMUTE.search(e["title"]) else "팬싸") if seed else None)
    print("임베딩", e["no"], "기준" if seed else "", len(fr), "프레임", len(crops), "몸통 | 얼굴", nf, "|", e["title"][:30])

seeds = {}
for no, p in post.items():
    if p["seed"]: seeds.setdefault(p["e"]["title_members"][0], []).append(no)
print("기준 글", {m: v for m, v in seeds.items()})

def outfit(a, b):  # 몸통 a개 x b개 유사도 행렬
    pa, pb = post[a], post[b]
    d = pa["ce"] @ pb["ce"].T
    hi = np.minimum(pa["ch"][:, None, :], pb["ch"][None, :, :]).sum(-1)
    return 0.75 * d + 0.25 * hi

def event_score(no, skip=()):
    p = post[no]; best = (0.0, None)
    for m, nos in seeds.items():
        for n in nos:
            if n == no or n in skip: continue
            s = float((p["full"] @ post[n]["full"].T).max())
            if s > best[0]: best = (s, n)
    return best

def member_scores(no, skip=()):
    """몸통마다 멤버별 최근접 유사도 -> {몸통 번호: {멤버: (유사도, 기준 글)}}"""
    res = {}
    for m, nos in seeds.items():
        for n in nos:
            if n == no or n in skip: continue
            M = outfit(no, n); k = M.max(axis=1); arg = M.argmax(axis=1)
            for ci, v in enumerate(k):
                cur = res.setdefault(ci, {}).get(m)
                if cur is None or v > cur[0]: res[ci][m] = (float(v), n, int(arg[ci]))
    return res

def decide_face(sc):
    srt = sorted(sc.items(), key=lambda t: -t[1][0])
    if not srt: return None, 0, None
    return srt[0][0], srt[0][1][0] - (srt[1][1][0] if len(srt) > 1 else 0), srt[0][1]

# 1) 기준 글 하나씩 빼고 맞혀 보기 -> 정확도, 기준값
ok = tot = 0; margins = []; evs = []
for m, nos in seeds.items():
    for no in nos:
        ev, _ = event_score(no); evs.append(ev)
        ms = member_scores(no)
        votes = {}
        for ci, sc in ms.items():
            b, mg, _ = decide_face(sc)
            if b: votes[b] = votes.get(b, 0) + 1
        if not votes: continue
        guess = max(votes, key=votes.get); tot += 1; ok += guess == m
        margins.append(guess == m)
        print("검증", no, "정답", m, "추정", guess, votes, "| 행사", round(ev, 3), "|", post[no]["e"]["title"][:28])
print(f"멤버 맞힘 {ok}/{tot}", "| 기준 글 행사 유사도", sorted(round(x, 3) for x in evs))
EV_T = float(os.environ.get("EV_T") or 0.55)
MG_T = float(os.environ.get("MG_T") or 0.02)
print("기준값 행사", EV_T, "멤버 차이", MG_T)

# 2) 나머지 글 판정
res = []
for no, p in post.items():
    if p["seed"]: continue
    ev, evn = event_score(no); tm = p["e"]["title_members"]
    ms = member_scores(no); per = []
    for ci, sc in ms.items():
        b, mg, ref = decide_face(sc)
        if b and mg >= MG_T: per.append((b, round(sc[b][0], 3), round(mg, 3), ref[1]))
    found = sorted({b for b, *_ in per})
    if ev < EV_T: dec = "제외(오늘 팬싸 아님)"
    elif tm: dec = "센둥이 모음집" if len(tm) >= 2 else tm[0] + "(제목)"
    elif len(found) >= 2: dec = "센둥이 모음집"
    elif len(found) == 1: dec = found[0]
    else: dec = "애매"
    near = per[0][3] if per else evn
    res.append(dict(no=no, title=p["e"]["title"], title_members=tm, event=round(ev, 3), event_ref=evn, faces=p["faces"], per_crop=per, decision=dec, near=near))
    print("판정", no, dec, "| 행사", round(ev, 3), "| 몸통별", per[:4], "| 얼굴", p["faces"], "|", p["e"]["title"][:30])

json.dump(dict(EV_T=EV_T, MG_T=MG_T, seeds=seeds, result=res), open(OUT / "match.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# 3) 검토용 시트: 후보 프레임 3장 | 가장 가까운 기준 글 프레임 2장
rows = []
for r in sorted(res, key=lambda r: (r["decision"].startswith("제외"), r["no"])):
    p = post[r["no"]]; ims = p["fr"][:3]
    if r["near"] in post: ims = ims + [None] + post[r["near"]]["fr"][:2]
    row = Image.new("RGB", (6 * 160, 182), "white"); dr = ImageDraw.Draw(row)
    for i, im in enumerate(ims[:6]):
        if im is None: continue
        t = im.copy(); t.thumbnail((156, 156)); row.paste(t, (i * 160, 22))
    dr.text((4, 3), f"{r['no']} 판정 {r['decision']} | 행사 {r['event']} | 얼굴 {r['faces']} | {r['title'][:22]} | 오른쪽: 기준 {r['near']}", fill="black", font=FONT)
    rows.append(row)
for k in range(0, len(rows), 12):
    part = rows[k:k + 12]; sh = Image.new("RGB", (960, 182 * len(part)), "white")
    for i, r in enumerate(part): sh.paste(r, (0, 182 * i))
    sh.save(OUT / f"sheet_{k // 12:02d}.jpg", quality=80)
# 기준 글 시트 (기준이 깨끗한지 확인용)
srows = []
for m, nos in seeds.items():
    for n in nos:
        p = post[n]; row = Image.new("RGB", (6 * 160, 182), "white"); dr = ImageDraw.Draw(row)
        for i, c in enumerate([c for _, c in p["crops"][:3]] + p["fr"][:3]):
            t = c.copy(); t.thumbnail((156, 156)); row.paste(t, (i * 160, 22))
        dr.text((4, 3), f"기준 {m} {n} {p['kind']} | {p['e']['title'][:30]} | 왼쪽 3: 몸통, 오른쪽 3: 화면", fill="black", font=FONT)
        srows.append(row)
if srows:
    sh = Image.new("RGB", (960, 182 * len(srows)), "white")
    for i, r in enumerate(srows): sh.paste(r, (0, 182 * i))
    sh.save(OUT / "seeds.jpg", quality=80)
