"""팬싸 관련 글을 멤버별로 분류해서 영상/사진을 받아 둔다 (읽기 전용). 검토용: out/fan/<멤버>/..., out/fan/info.json"""
import os, re, io, json, subprocess, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from bs4 import BeautifulSoup
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dc_digest as d
KST = timezone(timedelta(hours=9)); today = os.environ.get("DAY") or datetime.now(KST).strftime("%Y.%m.%d")
WS = os.environ.get("WSTART", "18:00")
d.GALL, d.KIND = "kpopcontent", "mgallery"
KEYS = [k for k in os.environ.get("KEYS", "팬싸,팬사,사인회,출근").split(",") if k]
# 확실한 별명만 (대장/여보/미남이 등 불확실한 건 따로 표시)
MEM = {"리브": ["리브", "리부", "리뿌", "여보"], "원이": ["원이", "원짱", "원쨩", "정원이", "대장", "정씨", "정작가", "파이리", "원아지"], "미나미": ["미나미", "미남이", "미냠이", "냠이", "냠깅"], "메이": ["메이", "메갓", "햇살"], "제나": ["제나", "까엉", "까엉이"]}
# 둘 이상을 가리키는 별칭 (제목에 있으면 해당 멤버 모두로 본다 -> 센둥이 모음집 쪽)
PAIRS = {"20kg": ["미나미", "리브"], "06즈": ["미나미", "리브"], "막내즈": ["메이", "제나"], "mz즈": ["메이", "제나"]}
UNSURE = []
ALL_KW = ["전원", "단체", "다같이", "다 같이", "멤버들", "센둥이", "리센느", "센느"]
out = Path("out/fan"); out.mkdir(parents=True, exist_ok=True)

def search(kw):
    res = []
    for p in range(1, 8):
        s = BeautifulSoup(d.get(f"{d.BASE}/{d.KIND}/board/lists/?id={d.GALL}&sort_type=N&s_type=search_subject&s_keyword={kw}&page={p}").text, "html.parser")
        page = []
        for tr in s.select("tr.ub-content[data-no]"):
            a = tr.select_one("td.gall_tit a"); dt = tr.select_one("td.gall_date")
            if not a: continue
            when = (dt.get("title") or dt.get_text()).strip().replace("-", ".") if dt else ""
            num = lambda sel: int(re.sub(r"\D", "", (tr.select_one(sel).get_text() if tr.select_one(sel) else "") or "0") or 0)
            page.append(dict(no=int(tr["data-no"]), title=a.get_text(" ", strip=True), when=when, rec=num("td.gall_recommend"), views=num("td.gall_count")))
        res += page
        ts = [r["when"][11:16] for r in page if r["when"].startswith(today)]
        if not page or (ts and min(ts) < WS) or not ts: break
    return [r for r in res if r["when"].startswith(today) and r["when"][11:16] >= WS]
def listscan(min_no, extra=""):
    res = []
    for p in range(1, 40):
        s = BeautifulSoup(d.get(f"{d.BASE}/{d.KIND}/board/lists/?id={d.GALL}&sort_type=N&page={p}{extra}").text, "html.parser")
        nos = []
        for tr in s.select("tr.ub-content[data-no]"):
            no = int(tr["data-no"]) if tr["data-no"].isdigit() else 0
            a = tr.select_one("td.gall_tit a"); dt = tr.select_one("td.gall_date")
            if not a: continue
            nos.append(no)
            sj = tr.select_one("td.gall_subject"); head = sj.get_text(strip=True) if sj else ""
            media = tr.select_one("td.gall_tit em.icon_pic, td.gall_tit em.icon_movie")
            when = (dt.get("title") or dt.get_text()).strip().replace("-", ".") if dt else ""
            num = lambda sel: int(re.sub(r"\D", "", (tr.select_one(sel).get_text() if tr.select_one(sel) else "") or "0") or 0)
            if no >= min_no and when.startswith(today):
                res.append(dict(no=no, title=a.get_text(" ", strip=True), when=when, rec=num("td.gall_recommend"), views=num("td.gall_count"), media=bool(media), head=head))
        if not nos or max(nos) < min_no: break
    return res
def members(text):
    low = text.lower()
    got = {m for m, al in MEM.items() if any(a in text for a in al)}
    for k, ms in PAIRS.items():
        if k.lower() in low: got.update(ms)
    return [m for m in MEM if m in got]
rows = {}
if os.environ.get("MIN_NO"):
    # 우리가 정한 조건: 📷📺 ∪ 개념글 ∪ 일반 말머리(미디어 글) (아이돌 컨텐츠 마이너 갤러리), 시간대 안, 사진/영상이 있는 글만
    import collections
    u = {}
    for r in listscan(int(os.environ["MIN_NO"]), "&exception_mode=recommend"): u[r["no"]] = r
    print("개념글 말머리 분포", dict(collections.Counter(r["head"] for r in u.values())))
    u = {k: r for k, r in u.items() if r["head"] in ("일반", "") or any(t in r["head"] for t in ("📷", "📺", "컨텐", "베스트"))}
    allr = list(u.values())
    print("전체 글", len(allr), "| 미디어 아이콘", sum(r["media"] for r in allr))
    if os.environ.get("LISTONLY") not in (None, "", "0"):
        import collections
        cnt = collections.Counter(); un = []
        for r in allr:
            m = members(r["title"])
            key = m[0] if len(m) == 1 else ("복수:" + "+".join(m) if m else "미분류")
            cnt[key] += 1
            if key == "미분류": un.append(r)
        print("분류(제목 별명 기준)", dict(cnt))
        if os.environ.get("SHOWMEM"):   # 점검용: 특정 멤버가 나온 글 전부 (개념글 여부 표시)
            best = {r["no"] for r in listscan(int(os.environ["MIN_NO"]), "&exception_mode=recommend")}
            gen = {r["no"]: r for r in listscan(int(os.environ["MIN_NO"]), "")}
            for r in listscan(int(os.environ["MIN_NO"]), "&search_head=20"): gen.setdefault(r["no"], r)
            for no, r in sorted(gen.items()):
                if os.environ["SHOWMEM"] in members(r["title"]): print("MEM", no, r["when"][11:16], "개념글" if no in best else "일반", "rec", r["rec"], "head", r["head"], "|", r["title"][:50])
        print("미분류 + 미디어 아이콘", len(un))
        for r in un: print("  미분류", r["when"][11:16], r["no"], "rec", r["rec"], r["title"][:50])
        sys.exit(0)
    NOT = re.compile(r"챌린지|총공|모금|스밍|디바엑스|디어리스트|데자부|구매|샀다|앨범|뮤빗|하이어|멜론|차트|사과문|등업|초동|케플러|라이즈|올데프|하이키|베스티|미야오|제베원|자컨|영업|공구|포카|굿즈|인증|순위|입갤|대기방|꾸준글|헬퍼|버블")
    for r in allr:
        if NOT.search(r["title"]) and not members(r["title"]): continue   # 누가 봐도 팬싸/행사와 무관한 제목
        rows[r["no"]] = r
else:
    for k in KEYS:
        for r in search(k): rows[r["no"]] = r
print("팬싸 관련 글", len(rows))
def members(text):
    low = text.lower()
    got = {m for m, al in MEM.items() if any(a in text for a in al)}
    for k, ms in PAIRS.items():
        if k.lower() in low: got.update(ms)
    return [m for m in MEM if m in got]
def probe(f):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate,duration", "-of", "json", str(f)], capture_output=True, text=True)
    try: return json.loads(r.stdout)["streams"][0]
    except Exception: return {}
info = []
for r in sorted(rows.values(), key=lambda r: r["no"]):
    try: p = d.post(r["no"])
    except SystemExit: raise
    except Exception as e: print("읽기 실패", r["no"], e); continue
    t = r["title"]; mt = members(t); mb = members(t + " " + p.get("text", ""))
    vids = []
    for u in p.get("videos", []):
        vids += (d.resolve_video(u) if "movie_view" in u else [u])
    ent = dict(no=r["no"], when=r["when"][11:16], title=t, rec=r["rec"], views=r["views"], title_members=mt, body_members=mb,
               unsure=[u for u in UNSURE if u in t], all_kw=[k for k in ALL_KW if k in t], links=[l for l in p.get("links", []) if re.search(r"youtu|instagram|twitter|x\.com", l)], files=[])
    seen = set()
    for i, u in enumerate(vids):
        try: b = d.S.get(u, headers={"Referer": p["url"]}, timeout=60); time.sleep(d.DELAY)
        except Exception: continue
        if not (b.ok and b.content[4:8] == b"ftyp") or len(b.content) in seen: continue
        seen.add(len(b.content))
        f = out / f"{r['no']}_v{i}.mp4"; f.write_bytes(b.content); s = probe(f)
        ent["files"].append(dict(file=f.name, kind="video", size=len(b.content), w=s.get("width"), h=s.get("height"), fps=s.get("r_frame_rate"), dur=s.get("duration")))
    for i, u in enumerate(p.get("images", [])):
        try: b = d.S.get(u, headers={"Referer": p["url"]}, timeout=40); time.sleep(d.DELAY)
        except Exception: continue
        h = b.content[:12]; ext = "gif" if h[:3] == b"GIF" else "png" if h[:4] == b"\x89PNG" else "jpg" if h[:3] == b"\xff\xd8\xff" else "webp" if h[:4] == b"RIFF" else None
        if not (b.ok and ext): continue
        f = out / f"{r['no']}_i{i}.{ext}"; f.write_bytes(b.content); ent["files"].append(dict(file=f.name, kind="image", size=len(b.content)))
    info.append(ent)
    print(ent["when"], r["no"], "rec", r["rec"], t[:36], "| 제목멤버", mt, "| 본문멤버", mb, "| 불확실", ent["unsure"], "| 파일", [(x["kind"][0], x.get("fps")) for x in ent["files"]])
json.dump(info, open(out / "info.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ---- 분류 안 된 글을 멤버 글의 이미지와 대조 (같은 행사 장면/의상인지) ----
import hashlib
from PIL import Image
def frames(f):
    f = Path(f); tmp = out / "_fr"; tmp.mkdir(exist_ok=True)
    for x in tmp.glob("*"): x.unlink()
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-vf", "fps=1,scale=64:64", "-frames:v", "6", str(tmp / "f%02d.png")], capture_output=True)
    return sorted(tmp.glob("f*.png"))
def feat(im):
    g = im.convert("L").resize((8, 8)); px = list(g.getdata()); m = sum(px) / 64
    bits = [1 if v > m else 0 for v in px]
    hsv = im.convert("RGB").resize((32, 32)).convert("HSV"); hist = [0] * 12
    for h, sa, v in hsv.getdata():
        if sa > 40 and v > 40: hist[h * 12 // 256] += 1
    t = sum(hist) or 1
    return bits, [x / t for x in hist]
feats = {}
for e in info:
    fs = []
    for x in e["files"]:
        try:
            if x["kind"] == "video": ims = [Image.open(q) for q in frames(out / x["file"])]
            else:
                im = Image.open(out / x["file"]); ims = [im.convert("RGB")]
            fs += [feat(i.convert("RGB")) for i in ims]
        except Exception: pass
    feats[e["no"]] = fs
def dist(a, b):
    ham = sum(x != y for x, y in zip(a[0], b[0])); hd = sum(abs(x - y) for x, y in zip(a[1], b[1]))
    return ham, hd
known = {}
for e in info:
    if len(e["title_members"]) == 1: known.setdefault(e["title_members"][0], []).append(e["no"])
for e in info:
    if e["title_members"]: continue
    best = {}
    for m, nos in known.items():
        c = [dist(a, b) for n in nos for a in feats[e["no"]] for b in feats[n]]
        if c: best[m] = min(c, key=lambda t: t[0] + t[1] * 20)
    e["match"] = {m: [h, round(c, 2)] for m, (h, c) in best.items()}
    print("대조", e["no"], e["title"][:30], {m: v for m, v in e["match"].items() if v[0] <= 12})
json.dump(info, open(out / "info.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
