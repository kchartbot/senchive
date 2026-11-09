"""시간대(WSTART~WEND, 오늘) 안의 글을 키워드 없이 훑는다 (읽기 전용): ㅋ 도배/키워드 추이 + 📷📺 말머리 글의 영상 정보."""
import os, re, io, json, subprocess, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from bs4 import BeautifulSoup
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dc_digest as d
from PIL import Image

KST = timezone(timedelta(hours=9)); today = datetime.now(KST).strftime("%Y.%m.%d")
WS, WE = os.environ.get("WSTART", "19:30"), os.environ.get("WEND", "22:00")
KWS = [k for k in os.environ.get("WKW", "스포티파이,스포,대기방,위드,with,백화요란,팬싸,캡쳐,갈매기").split(",") if k]
d.GALL, d.KIND = "kpopcontent", "mgallery"
out = Path("out/win"); out.mkdir(parents=True, exist_ok=True)

def rows(extra, maxp=14):
    res = []
    for p in range(1, maxp + 1):
        soup = BeautifulSoup(d.get(f"{d.BASE}/{d.KIND}/board/lists/?id={d.GALL}&sort_type=N&page={p}{extra}").text, "html.parser")
        page = []
        for tr in soup.select("tr.ub-content"):
            no = tr.get("data-no"); a = tr.select_one("td.gall_tit a")
            if not (no and no.isdigit() and a): continue
            dt = tr.select_one("td.gall_date"); when = (dt.get("title") or dt.get_text()).strip().replace("-", ".") if dt else ""
            num = lambda sel: int(re.sub(r"\D", "", (tr.select_one(sel).get_text() if tr.select_one(sel) else "") or "0") or 0)
            page.append(dict(no=int(no), title=a.get_text(" ", strip=True), when=when, rec=num("td.gall_recommend"), views=num("td.gall_count")))
        res += page
        ts = [r["when"][11:16] for r in page if r["when"].startswith(today)]
        if page and (not ts or min(ts) < WS): break
    return [r for r in {r["no"]: r for r in res}.values() if r["when"].startswith(today) and WS <= r["when"][11:16] <= WE]

# A. 전체 글 추이 (10분 단위)
allr = rows("")
bins = {}
for r in allr:
    h, m = r["when"][11:13], int(r["when"][14:16]); k = f"{h}:{m//10*10:02d}"
    b = bins.setdefault(k, dict(n=0, kk=0, **{w: 0 for w in KWS}))
    b["n"] += 1; b["kk"] += len(re.findall("ㅋ", r["title"])) >= 4
    for w in KWS: b[w] += w.lower() in r["title"].lower()
print("== 10분 단위 추이 (n=글수, kk=ㅋ4개이상 제목수) ==")
for k in sorted(bins): print(k, bins[k])

# B. 📷📺 말머리 글의 영상
d.HEAD = "20"
pic = rows("&search_head=20")
print("== 📷📺 글", len(pic), "==")
info = []
def probe(f):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate,nb_frames,duration", "-of", "json", str(f)], capture_output=True, text=True)
    try: return json.loads(r.stdout)["streams"][0]
    except Exception: return {}
for r in sorted(pic, key=lambda r: r["when"]):
    try: p = d.post(r["no"])
    except SystemExit: raise
    except Exception as e: print(r["no"], "읽기 실패", e); continue
    vids = []
    for u in p.get("videos", []):
        vids += d.resolve_video(u) if "movie_view" in u else [u]
    ent = dict(no=r["no"], when=r["when"][11:16], title=r["title"], rec=r["rec"], images=len(p.get("images", [])), videos=[], yt=[l for l in p.get("links", []) if "youtu" in l])
    for i, u in enumerate(vids):
        try:
            b = d.S.get(u, headers={"Referer": p["url"]}, timeout=60); time.sleep(d.DELAY)
        except Exception as e: ent["videos"].append(dict(err=str(e)[:60])); continue
        if not (b.ok and b.content[4:8] == b"ftyp"): ent["videos"].append(dict(src=u[:80], note="mp4 아님", head=b.content[:8].hex())); continue
        f = out / f"{r['no']}_v{i}.mp4"; f.write_bytes(b.content)
        s = probe(f); fr = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1", "-i", str(f), "-frames:v", "1", "-vf", "scale=240:-2", str(out / f"{r['no']}_v{i}.png")], capture_output=True)
        ent["videos"].append(dict(file=f.name, size=len(b.content), w=s.get("width"), h=s.get("height"), fps=s.get("r_frame_rate"), frames=s.get("nb_frames"), dur=s.get("duration"), name=re.findall(r"f_no=([^&]+)", u)))
    info.append(ent)
    print(ent["when"], r["no"], r["rec"], r["title"][:30], "| 영상", [(v.get("w"), v.get("h"), v.get("fps"), v.get("dur")) for v in ent["videos"]], "| yt", ent["yt"][:1])
json.dump(dict(bins=bins, posts=info), open(out / "info.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
