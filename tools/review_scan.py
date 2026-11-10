"""검수 화면용 스캔: 기간 내 개념글 중 센둥이 관련 글의 사진·움짤을 모아 썸네일과 index.json 을 out/review 에 만든다 (읽기 전용)."""
import os, re, io, json, subprocess, sys, time
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dc_digest as d

KST = d.KST
SINCE = os.environ.get("SINCE") or datetime.now(KST).strftime("%Y.%m.%d")
MAXP = int(os.environ.get("MAXP", "12"))
MAXFILES = int(os.environ.get("MAXFILES", "40"))
d.GALL, d.KIND, d.HEAD = "kpopcontent", "mgallery", ""
GROUP = [k.lower() for k in "리센느,센느,센둥이,RESCENE,리브,원이,미나미,메이,제나,대장,원짱,원쨩,냠이,미남이,여보,리부,메갓,까엉,펄스,PULSE,20kg,06즈,막내즈,mz즈".split(",")]
OUT_KW = re.compile("버블|디콘|dccon|밈")
OTHER = [k.strip() for k in os.environ.get("OTHER_GROUP", "베니,쿠미,아이브,뉴진스,에스파,르세라핌,아일릿,아이들,엔믹스,트와이스,있지,스테이씨,키오프,베이비몬스터,피프티,하투하,이즈나,유니스,빌리,아이유,블랙핑크,fromis,프로미스,엔하이픈,보넥도,투바투,라이즈").split(",") if k.strip()]
out = Path("out/review"); (out / "t").mkdir(parents=True, exist_ok=True)


def rows():
    res = []
    for p in range(1, MAXP + 1):
        url = f"{d.BASE}/mgallery/board/lists/?id=kpopcontent&sort_type=N&page={p}&exception_mode=recommend"
        soup = BeautifulSoup(d.get(url).text, "html.parser"); page = []
        for tr in soup.select("tr.ub-content"):
            no = tr.get("data-no"); a = tr.select_one("td.gall_tit a")
            if not (no and no.isdigit() and a): continue
            dt = tr.select_one("td.gall_date"); when = (dt.get("title") or dt.get_text()).strip().replace("-", ".") if dt else ""
            num = lambda sel: int(re.sub(r"\D", "", (tr.select_one(sel).get_text() if tr.select_one(sel) else "") or "0") or 0)
            head = tr.select_one("td.gall_subject")
            page.append(dict(no=int(no), title=a.get_text(" ", strip=True), when=when, views=num("td.gall_count"), rec=num("td.gall_recommend"), head=head.get_text(strip=True) if head else ""))
        if not page: break
        res += page
        dates = sorted(r["when"] for r in page if re.match(r"\d{4}\.", r["when"]))
        if dates and dates[len(dates) // 2] < SINCE: break
    return [r for r in {r["no"]: r for r in res}.values() if r["when"] >= SINCE or (":" in r["when"] and len(r["when"]) <= 5)]


def thumb(im, name):
    im.seek(0); im = im.convert("RGB"); w, h = im.size; s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s)).resize((240, 240))
    im.save(out / "t" / f"{name}.jpg", "JPEG", quality=66)


def frame_thumb(src, name, headers=""):
    f = out / "t" / f"{name}.png"
    cmd = ["ffmpeg", "-y", "-loglevel", "error"] + (["-headers", headers] if headers else []) + ["-i", str(src), "-frames:v", "1", str(f)]
    subprocess.run(cmd, capture_output=True, timeout=90)
    if f.exists():
        thumb(Image.open(f), name); f.unlink(); return True
    return False


def main():
    rs = rows(); posts = []
    print("개념글", len(rs))
    for r in rs:
        if OUT_KW.search(r["title"]) or any(k in r["title"] for k in OTHER): continue
        try: p = d.post(r["no"])
        except SystemExit: raise
        except Exception as e: print("글 실패", r["no"], str(e)[:60]); continue
        if p.get("error"): continue
        blob = (r["title"] + " " + p.get("text", "")).lower()
        if not any(g in blob for g in GROUP): continue
        files = []
        vlist = []
        for u0 in p.get("videos", []):
            if "movie_view" in u0:
                for r_ in d.resolve_video(u0):
                    if ".m3u8" in r_:
                        name = f"{p['no']}_m{len(vlist)}"
                        if frame_thumb(r_, name, f"Referer: {d.BASE}/\r\n"): files.append(dict(id=name, t="clip"))
                    elif r_ not in vlist: vlist.append(r_)
            else: vlist.append(u0)
        for i, u in enumerate(vlist):
            name = f"{p['no']}_v{i}"
            try:
                b = d.S.get(u, headers={"Referer": p["url"]}, timeout=40); time.sleep(d.DELAY)
                if not (b.ok and b.content[4:8] == b"ftyp" and len(b.content) <= 12_000_000): continue
                tmp = out / f"{name}.mp4"; tmp.write_bytes(b.content)
                ok = frame_thumb(tmp, name); tmp.unlink()
                if ok: files.append(dict(id=name, t="clip"))
            except SystemExit: raise
            except Exception as e: print("영상 실패", name, str(e)[:60])
        for i, u in enumerate(p.get("images", [])[:MAXFILES]):
            name = f"{p['no']}_{i}"
            try:
                b = d.S.get(u, headers={"Referer": p["url"]}, timeout=30); time.sleep(d.DELAY); h = b.content[:12]
                ext = "gif" if h[:3] == b"GIF" else "png" if h[:4] == b"\x89PNG" else "jpg" if h[:3] == b"\xff\xd8\xff" else "webp" if h[:4] == b"RIFF" else None
                if not (b.ok and ext and len(b.content) <= 8_000_000): continue
                im = Image.open(io.BytesIO(b.content)); thumb(im, name)
                anim = ext == "gif" or (ext == "webp" and b"ANIM" in b.content[:200])
                files.append(dict(id=name, t="clip" if anim else "img"))
            except SystemExit: raise
            except Exception as e: print("이미지 실패", name, str(e)[:60])
        if not files and not p.get("links"): continue
        posts.append(dict(no=p["no"], title=p["title"], when=r["when"], head=r["head"], rec=r["rec"], views=r["views"], url=p["url"], links=p.get("links", []), files=files))
        print("글", p["no"], p["title"][:30], len(files))
    posts.sort(key=lambda x: x["when"], reverse=True)
    (out / "index.json").write_text(json.dumps(dict(generated=datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"), since=SINCE, run=os.environ.get("GITHUB_RUN_ID", ""), posts=posts), ensure_ascii=False), encoding="utf-8")
    print("저장", len(posts), "글")


if __name__ == "__main__":
    main()
