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
MAXPOSTS = int(os.environ.get("MAXPOSTS", "0"))   # 0 = 제한 없음
MAXFILES = int(os.environ.get("MAXFILES", "40"))
RECOMMEND = os.environ.get("RECOMMEND", "true").lower() != "false"   # false 면 개념글이 아닌 글도 훑는다
def nh(h): return (h or "").replace("\ufe0f", "").replace(" ", "").strip() or "(없음)"   # 이모지 변형문자·공백 차이를 무시
HEAD_OFF = {nh(h) for h in os.environ.get("HEAD_OFF", "").split(",") if h.strip()}   # 건너뛸 말머리
d.GALL, d.KIND, d.HEAD = "kpopcontent", "mgallery", ""
INCREMENTAL = os.environ.get("INCREMENTAL", "false").lower() == "true"   # 지난 결과를 재사용하고 새 글만 읽는다


def retry(fn, *a, tries=3, **k):
    """일시적인 네트워크 오류면 간격을 늘려 다시 시도한다 (차단 감지로 인한 종료는 그대로 전달)."""
    for i in range(tries):
        try: return fn(*a, **k)
        except SystemExit: raise
        except Exception:
            if i == tries - 1: raise
            time.sleep(3 * (i + 1))


def fetch(u, ref, timeout):
    r = d.S.get(u, headers={"Referer": ref}, timeout=timeout)
    if r.status_code >= 500: raise RuntimeError(f"HTTP {r.status_code}")
    time.sleep(d.DELAY)
    return r


def kw(env, default):
    v = os.environ.get(env, "").strip()
    return [k.strip() for k in (v or default).split(",") if k.strip()]
INC_L = kw("KW_INCLUDE", "리센느,센느,센둥이,RESCENE,리브,원이,미나미,메이,제나,대장,원짱,원쨩,냠이,미남이,여보,리부,메갓,까엉,펄스,PULSE,20kg,06즈,막내즈,mz즈")
EXC_L = kw("KW_EXCLUDE", "버블,디콘,dccon,밈")
OTHER = kw("KW_OTHER", "베니,쿠미,아이브,뉴진스,에스파,르세라핌,아일릿,아이들,엔믹스,트와이스,있지,스테이씨,키오프,베이비몬스터,피프티,하투하,이즈나,유니스,빌리,아이유,블랙핑크,fromis,프로미스,엔하이픈,보넥도,투바투,라이즈")
BAIT = kw("KW_BAIT", "비하인드,떴다,떳다")
GROUP = [k.lower() for k in INC_L]
OUT_KW = re.compile("|".join(re.escape(k) for k in EXC_L) or "(?!)", re.I)
out = Path("out/review"); (out / "t").mkdir(parents=True, exist_ok=True); (out / "m").mkdir(exist_ok=True)


def rows():
    res = []
    for p in range(1, MAXP + 1):
        url = f"{d.BASE}/mgallery/board/lists/?id=kpopcontent&sort_type=N&page={p}" + ("&exception_mode=recommend" if RECOMMEND else "")
        soup = BeautifulSoup(retry(d.get, url).text, "html.parser"); page = []
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
    im.seek(0); im = im.convert("RGB")
    big = im.copy(); big.thumbnail((1000, 1000)); big.save(out / "m" / f"{name}.jpg", "JPEG", quality=80)   # 원본 보기용 큰 미리보기
    w, h = im.size; s = min(w, h)
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
    heads = {}
    prev = {}
    if INCREMENTAL and (out / "index.json").exists():
        try: prev = json.loads((out / "index.json").read_text(encoding="utf-8"))
        except Exception: prev = {}
    prev_posts = {int(p["no"]): p for p in prev.get("posts", [])}
    sig = ",".join(sorted(INC_L)) + f"|{MAXFILES}"
    skip = set(prev.get("skip", [])) if prev.get("sig") == sig else set()   # 포함 키워드가 바뀌면 "해당 없음" 기록은 버린다
    new_skip = set(); stat = dict(read=0, reused=0, skipped=0)
    for r in rs: heads[nh(r["head"])] = heads.get(nh(r["head"]), 0) + 1
    print("개념글", len(rs))
    read = 0
    for r in rs:
        if nh(r["head"]) in HEAD_OFF: continue
        if OUT_KW.search(r["title"]) or any(k in r["title"] for k in OTHER): continue
        if r["no"] in prev_posts:
            p0 = prev_posts[r["no"]]
            p0.update(bait=any(k in r["title"] for k in BAIT), when=r["when"], head=r["head"], rec=r["rec"], views=r["views"])
            posts.append(p0); stat["reused"] += 1; continue
        if r["no"] in skip: new_skip.add(r["no"]); stat["skipped"] += 1; continue
        if MAXPOSTS and read >= MAXPOSTS: continue
        read += 1
        try: p = retry(d.post, r["no"])
        except SystemExit: raise
        except Exception as e: print("글 실패", r["no"], str(e)[:60]); continue
        if p.get("error"): new_skip.add(r["no"]); continue
        blob = (r["title"] + " " + p.get("text", "")).lower()
        if not any(g in blob for g in GROUP): new_skip.add(r["no"]); continue
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
                b = retry(fetch, u, p["url"], 40)
                if not (b.ok and b.content[4:8] == b"ftyp" and len(b.content) <= 12_000_000): continue
                tmp = out / f"{name}.mp4"; tmp.write_bytes(b.content)
                ok = frame_thumb(tmp, name)
                keep = ok and tmp.stat().st_size <= 6_000_000
                if keep: tmp.replace(out / "m" / f"{name}.mp4")   # 가벼운 영상은 검수 화면에서 재생한다
                else: tmp.unlink()
                if ok: files.append(dict(id=name, t="clip", **({"o": "mp4"} if keep else {})))
            except SystemExit: raise
            except Exception as e: print("영상 실패", name, str(e)[:60])
        for i, u in enumerate(p.get("images", [])[:MAXFILES]):
            name = f"{p['no']}_{i}"
            try:
                b = retry(fetch, u, p["url"], 30); h = b.content[:12]
                ext = "gif" if h[:3] == b"GIF" else "png" if h[:4] == b"\x89PNG" else "jpg" if h[:3] == b"\xff\xd8\xff" else "webp" if h[:4] == b"RIFF" else None
                if not (b.ok and ext and len(b.content) <= 8_000_000): continue
                im = Image.open(io.BytesIO(b.content)); thumb(im, name)
                anim = ext == "gif" or (ext == "webp" and b"ANIM" in b.content[:200])
                f = dict(id=name, t="clip" if anim else "img")
                if anim and len(b.content) <= 6_000_000:
                    (out / "m" / f"{name}.{ext}").write_bytes(b.content); f["o"] = ext   # 가벼운 움짤은 원본 그대로 보여 준다
                files.append(f)
            except SystemExit: raise
            except Exception as e: print("이미지 실패", name, str(e)[:60])
        if not files and not p.get("links"): new_skip.add(r["no"]); continue
        stat["read"] += 1
        posts.append(dict(no=p["no"], bait=any(k in r["title"] for k in BAIT), title=p["title"], when=r["when"], head=r["head"], rec=r["rec"], views=r["views"], url=p["url"], links=p.get("links", []), files=files))
        print("글", p["no"], p["title"][:30], len(files))
    posts.sort(key=lambda x: x["when"], reverse=True)
    keep = {f["id"] for x in posts for f in x["files"]}
    for f in list((out / "t").glob("*")) + list((out / "m").glob("*")):
        if f.stem not in keep: f.unlink()   # 더 이상 쓰지 않는 미리보기 정리
    skip_all = sorted(skip | new_skip, reverse=True)[:6000]
    print(f"새로 읽음 {stat['read']} · 재사용 {stat['reused']} · 건너뜀 {stat['skipped']}")
    (out / "index.json").write_text(json.dumps(dict(kw=dict(include=INC_L, exclude=EXC_L, other=OTHER, bait=BAIT), heads=heads, recommend=RECOMMEND, skip=skip_all, sig=sig, stat=stat, generated=datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"), since=SINCE, run=os.environ.get("GITHUB_RUN_ID", ""), posts=posts), ensure_ascii=False), encoding="utf-8")
    print("저장", len(posts), "글")


if __name__ == "__main__":
    main()
