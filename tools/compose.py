"""스케줄의 오늘 지난 일정마다 두 갤러리에서 관련 글을 찾아 '무대 링크 + 움짤(없으면 사진)' 글을 조립한다. 읽기 전용, 겹치는 건 제외."""
import hashlib, io, json, os, re, subprocess, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import dc_digest as d
from PIL import Image

KST = timezone(timedelta(hours=9))
GROUP_EXTRA = ["대장", "원짱", "원쨩", "냠이", "미남이", "여보", "리부", "리뿌", "미냠이", "정씨", "정작가", "파이리", "햇살", "메갓", "까엉", "까엉이", "펄스", "PULSE"]
GROUP_KW = [k.strip() for k in os.environ.get("GROUP_KW", "센느,센둥이,리센느,RESCENE,리브,원이,미나미,메이,제나").split(",") if k.strip()]
GALLERIES = [g.split(":") for g in os.environ.get("GALLERIES", "mgallery:kpopcontent:20,mgallery:kpopgirlgroup:").split(",")]
PAGES = int(os.environ.get("PAGES", "4"))
MAXCLIP = int(os.environ.get("MAXCLIP", "14"))
INC = {x.strip() for x in os.environ.get("INCLUDE", "").split(",") if x.strip()}   # 지정하면 이 파일만 내려받는다(중복 제거·개수 제한도 이 파일 안에서만)
MAXIMG = int(os.environ.get("MAXIMG", "30"))   # 사진은 움짤과 같이 올린다 (디시 파일 50개 제한 안)
ONLY = os.environ.get("EVENT_NAME", "").strip()
YT = re.compile(r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|shorts/|live/))([\w-]{11})")


def ahash(im):
    g = im.convert("L").resize((8, 8)); px = list(g.getdata()); m = sum(px) / 64
    return sum(1 << i for i, v in enumerate(px) if v > m)


def ham(a, b): return bin(a ^ b).count("1")


def first_frame(path):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
    return Image.open(io.BytesIO(r.stdout)) if r.stdout else None


OTHER_SHOWS = ["음중", "음악중심", "뮤뱅", "뮤직뱅크", "엠카", "엠카운트다운", "쇼챔", "쇼챔피언", "더쇼", "쇼케이스", "라디오", "예능", "팬싸", "팬사인"]

OTHER_GROUP = [k.strip() for k in os.environ.get("OTHER_GROUP", "베니,쿠미,아이브,뉴진스,에스파,르세라핌,아일릿,아이들,엔믹스,트와이스,있지,스테이씨,키오프,베이비몬스터,피프티,하투하,이즈나,유니스,빌리,아이유,블랙핑크,걸스데이,fromis,프로미스,엔하이픈,보넥도,투바투,라이즈").split(",") if k.strip()]

def title_ok(t, ev):
    if any(o.lower() in t.lower() for o in OTHER_GROUP):
        return False
    return _title_ok(t, ev)

def _title_ok(t, ev):
    """방송 이름(인기가요/인가)이 있으면 통과. 곡 제목(위드/with/백화요란)만 있으면 다른 방송 이름이 없을 때만 통과."""
    tl = t.lower()
    if any(k.lower() in tl for k in ev["event_kw"]):
        return True
    if any(k.lower() in tl for k in ev.get("song_kw", [])):
        return not any(o in t for o in OTHER_SHOWS)
    return False

def search_rows(gid, head, kw, pages):
    """개념글 중 제목+내용에 kw 가 있는 글 (읽기 전용)."""
    from bs4 import BeautifulSoup
    out = []
    for pg in range(1, pages + 1):
        url = f"{d.BASE}/{d.KIND}/board/lists/?id={gid}&sort_type=N&exception_mode=recommend&search_pos=&s_type=search_subject_memo&s_keyword={kw}&page={pg}"
        soup = BeautifulSoup(d.get(url).text, "html.parser"); n = 0
        for tr in soup.select("tr.ub-content"):
            no = tr.get("data-no"); a = tr.select_one("td.gall_tit a")
            if not (no and no.isdigit() and a): continue
            dt = tr.select_one("td.gall_date"); when = (dt.get("title") or dt.get_text()).strip().replace("-", ".") if dt else ""
            num = lambda sel: int(re.sub(r"\D", "", (tr.select_one(sel).get_text() if tr.select_one(sel) else "") or "0") or 0)
            out.append(dict(no=int(no), title=a.get_text(" ", strip=True), when=when, views=num("td.gall_count"), rec=num("td.gall_recommend"))); n += 1
        if not n: break
    return list({r["no"]: r for r in out}.values())

LINK_OK = re.compile(r"(youtube\.com|youtu\.be|instagram\.com|twitter\.com|x\.com)/")

def collect(ev, today):
    out = Path("out") / ev["name"]; (out / "media").mkdir(parents=True, exist_ok=True)
    kws = ev["event_kw"]; posts = []
    for kind, gid, head in GALLERIES:
        d.GALL, d.KIND, d.HEAD = gid, kind, head
        try: rows = [dict(no=int(n), title="", when=today, rec=0, views=0) for n in ev["posts"]] if ev.get("posts") else (search_rows(gid, head, ev["keyword"], 2) if ev.get("keyword") else d.lists_n(PAGES))
        except SystemExit: raise
        hit = [r for r in rows if (r["when"].startswith(today) or (":" in r["when"] and len(r["when"]) <= 5)) and
               (ev.get("keyword") or ev.get("posts") or (title_ok(r["title"], ev) and any(g in r["title"] for g in GROUP_KW)))]
        print(f"[{gid}] 목록 {len(rows)}건 → 일치 {len(hit)}건")
        for r in hit:
            p = d.post(r["no"])
            if ev.get("keyword") and r["rec"] < 25 and not any(g.lower() in (p.get("title", "") + " " + p.get("text", "")).lower() for g in GROUP_KW + GROUP_EXTRA): continue
            p.update(gallery=gid, rec=r["rec"], views=r["views"], when=r["when"], list_title=r["title"]); posts.append(p)
    posts.sort(key=lambda p: (p["rec"], p["views"]), reverse=True)
    stage, seen_yt = [], set()
    clips, imgs, hashes = [], [], []
    def dup(h):
        return any(ham(h, x) <= 4 for x in hashes)
    for p in posts:
        print("글", p["no"], p["title"][:30], "| 영상", [v[:110] for v in p.get("videos", [])], "| 이미지", len(p.get("images", [])))
        for l in p.get("links", []):
            if (ev.get("keyword") or ev.get("posts")) and LINK_OK.search(l):
                ig = re.search(r"instagram\.com/(?:p|reel|tv)/([\w-]+)", l)
                key = ("ig", ig.group(1)) if ig else l.split("?")[0]
                if key not in seen_yt:
                    seen_yt.add(key); stage.append(dict(url=(f"https://www.instagram.com/p/{ig.group(1)}/" if ig else l), src=p["url"], title=p["title"]))
                continue
            m = YT.search(l)
            if m and m.group(1) not in seen_yt: seen_yt.add(m.group(1)); stage.append(dict(url=f"https://www.youtube.com/watch?v={m.group(1)}", src=p["url"], title=p["title"]))
        vlist = []
        for u0 in p.get("videos", []):
            if "movie_view" in u0:
                res = d.resolve_video(u0)
                print("  movie_view →", res or d.RESOLVE_DBG[-1:])
                for r_ in res:
                    if ".m3u8" in r_:  # 스트림은 ffmpeg 로 mp4 로 받는다
                        f = out / "media" / f"{p['no']}_m{len(vlist)}.mp4"
                        rr = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-headers", f"Referer: {d.BASE}/\r\n", "-i", r_, "-t", "60", "-c", "copy", str(f)], capture_output=True)
                        if f.exists() and f.stat().st_size > 1000:
                            fr = first_frame(f); ah = ahash(fr) if fr else None
                            if ah is not None and not dup(ah):
                                hashes.append(ah); clips.append(dict(file=f.name, src=p["url"], title=p["title"], gallery=p["gallery"]))
                            else: f.unlink()
                    elif r_ not in vlist: vlist.append(r_)
            else:
                vlist.append(u0)
        for i, u in enumerate(vlist):
            if INC and f"{p['no']}_v{i}" not in INC: continue
            b = d.S.get(u, headers={"Referer": p["url"]}, timeout=40); time.sleep(d.DELAY); h = b.content[:12]
            if not (b.ok and h[4:8] == b"ftyp" and len(b.content) <= 12_000_000): continue
            f = out / "media" / f"{p['no']}_v{i}.mp4"; f.write_bytes(b.content)
            fr = first_frame(f)
            if fr is None: continue
            ah = ahash(fr)
            if dup(ah): f.unlink(); continue
            hashes.append(ah); clips.append(dict(file=f.name, src=p["url"], title=p["title"], gallery=p["gallery"]))
        for i, u in enumerate(p.get("images", [])):
            if INC and f"{p['no']}_{i}" not in INC: continue
            b = d.S.get(u, headers={"Referer": p["url"]}, timeout=30); time.sleep(d.DELAY); h = b.content[:12]
            ext = "gif" if h[:3] == b"GIF" else "png" if h[:4] == b"\x89PNG" else "jpg" if h[:3] == b"\xff\xd8\xff" else "webp" if h[:4] == b"RIFF" else None
            if not (b.ok and ext and len(b.content) <= 8_000_000): continue
            im = Image.open(io.BytesIO(b.content)); ah = ahash(im)
            if dup(ah): continue
            f = out / "media" / f"{p['no']}_{i}.{ext}"; f.write_bytes(b.content)
            hashes.append(ah)
            item = dict(file=f.name, src=p["url"], title=p["title"], gallery=p["gallery"])
            (clips if (ext == "gif" or (ext == "webp" and b"ANIM" in b.content[:200])) else imgs).append(item)  # 움직이는 gif/webp 는 움짤
    media = clips[:MAXCLIP] + imgs[:MAXIMG]   # 움짤(15개 미만) + 사진 같이
    res = dict(event=ev["name"], title=f"[{ev['date'].replace('-', '')}] {ev['title_name']} 링크+짤 모음", date=ev["date"], stage_links=stage, media_kind="움짤+사진" if clips and imgs else ("움짤" if clips else "사진"),
               media=media, posts=[dict(no=p["no"], gallery=p["gallery"], title=p["title"], rec=p["rec"], url=p["url"]) for p in posts], counts=dict(clips=len(clips), images=len(imgs), dropped_dup=True))
    (out / "post.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(res["title"], "| 링크", len(stage), "| 움짤", len(clips), "| 사진", len(imgs), "| 글", len(posts))


def main():
    today = datetime.now(KST).strftime("%Y.%m.%d"); iso = today.replace(".", "-")
    if os.environ.get("EVDATE"): iso = os.environ["EVDATE"]   # 행사 날짜 (자정을 넘겨 올릴 때)
    if os.environ.get("TOPIC"):
        t = os.environ["TOPIC"]; sch = [dict(date=iso, name=t, title_name=t, keyword=t, event_kw=[t])]
        if os.environ.get("POSTS"): sch[0]["posts"] = [x for x in os.environ["POSTS"].split(",") if x.strip()]; sch[0].pop("keyword")
    else:
        sch = [e for e in json.load(open("schedule.json", encoding="utf-8")) if e["date"] == iso and (not ONLY or e["name"] == ONLY)]
    print("오늘 일정", [e["name"] for e in sch])
    for ev in sch: collect(ev, today)


if __name__ == "__main__":
    main()
