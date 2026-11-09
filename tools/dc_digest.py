"""갤러리 글 목록에서 오늘 인기 글을 골라 본문의 이미지·영상·링크를 모은다 (읽기 전용).
공개 글만 읽고, 인증/차단 화면이 보이면 그 자리에서 멈춘다."""
import json, os, re, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

GALL = os.environ.get("GALL_ID", "kpopcontent")
KIND = os.environ.get("GALL_KIND", "mgallery")
HEAD = os.environ.get("SEARCH_HEAD", "20")
PAGES = int(os.environ.get("PAGES", "3"))
TOP = int(os.environ.get("TOP", "10"))
DELAY = float(os.environ.get("DELAY", "2.5"))
KW = [k.strip() for k in os.environ.get("KEYWORDS", "리센느,원이,리브,미나미,메이,제나,센둥이,인기가요,인가,엔딩,직캠,무대").split(",") if k.strip()]
KST = timezone(timedelta(hours=9))
BASE = "https://gall.dcinside.com"
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept-Language": "ko-KR,ko;q=0.9"})
BLOCK = re.compile(r"자동입력 방지|captcha|보안 문자|비정상적인 접근|접근이 제한")


def get(url, **kw):
    r = S.get(url, timeout=25, **kw)
    time.sleep(DELAY)
    if r.status_code in (403, 429) or BLOCK.search(r.text[:6000]):
        print(f"BLOCKED {r.status_code} {url}", file=sys.stderr)
        sys.exit(3)
    r.raise_for_status()
    return r


def lists(pages=None):
    out = []
    for p in range(1, (pages or PAGES) + 1):
        url = f"{BASE}/{KIND}/board/lists/?id={GALL}&sort_type=N&search_head={HEAD}&page={p}"
        soup = BeautifulSoup(get(url).text, "html.parser")
        for tr in soup.select("tr.ub-content"):
            no = tr.get("data-no")
            a = tr.select_one("td.gall_tit a")
            if not (no and no.isdigit() and a): continue
            d = tr.select_one("td.gall_date")
            when = (d.get("title") or d.get_text()).strip().replace("-", ".") if d else ""
            num = lambda sel: int(re.sub(r"\D", "", (tr.select_one(sel).get_text() if tr.select_one(sel) else "") or "0") or 0)
            out.append(dict(no=int(no), title=a.get_text(" ", strip=True), when=when, views=num("td.gall_count"), rec=num("td.gall_recommend")))
    return list({r["no"]: r for r in out}.values())


def lists_n(n):
    return lists(n)


def post(no):
    url = f"{BASE}/{KIND}/board/view/?id={GALL}&no={no}"
    soup = BeautifulSoup(get(url).text, "html.parser")
    title = (soup.select_one("span.title_subject") or soup.select_one("title")).get_text(" ", strip=True)
    w = soup.select_one("div.write_div")
    if not w: return dict(no=no, url=url, title=title, error="본문을 찾지 못함")
    imgs, vids, links = [], [], []
    for im in w.select("img"):
        src = im.get("data-original") or im.get("src") or ""
        if "dccon" in " ".join(im.get("class", [])) or "dccon" in src or "dcimg5" in src and "viewimage" not in src: continue  # 디시콘(이모티콘) 제외
        if src and "gallview_loading" not in src and "nstatic.dcinside.com" not in src: imgs.append(src)
    for v in w.select("video"):
        s = v.get("src") or (v.select_one("source") or {}).get("src")
        if s: vids.append(s)
    for f in w.select("iframe"):
        if f.get("src"): vids.append(f["src"])
    for a in w.select("a[href]"):
        h = a["href"]
        if h.startswith("http") and "dcinside.com" not in h: links.append(h)
    text = re.sub(r"\s+", " ", w.get_text(" ", strip=True))[:300]
    return dict(no=no, url=url, title=title, images=list(dict.fromkeys(imgs)), videos=list(dict.fromkeys(vids)), links=list(dict.fromkeys(links)), text=text)


RESOLVE_DBG = []


def resolve_video(u):
    """디시 영상 페이지(movie_view)에서 mp4/m3u8 주소를 찾는다"""
    try:
        rr = get(u, headers={"Referer": f"{BASE}/"})
        t = rr.text
        RESOLVE_DBG.append([u[-30:], rr.status_code, len(t), re.sub(r"\s+", " ", t)[:700]])
        tt = t.replace("\\/", "/")
        m = re.findall(r"https?:[^\"'\s<>]+?\.(?:mp4|m3u8|webm)[^\"'\s<>]*", tt)
        m += [x for x in re.findall(r"https?://[^\"'\s<>]*viewmovie\.php[^\"'\s<>]*", tt) if "type=mp4" in x]  # 확장자 없는 형식
        return list(dict.fromkeys(m))[:2]
    except SystemExit: raise
    except Exception as e: return []


def kind(title, p):
    t = title
    if re.search("엔딩", t): return "엔딩요정"
    if re.search("직캠|무대|풀캠|라이브|퍼포|댄브", t): return "무대"
    if re.search("대기|출근|퇴근|착장|목격|사진|짤|이미지", t): return "사진"
    return "기타"


def main():
    today = datetime.now(KST).strftime("%Y.%m.%d")
    rows = lists()
    print("목록", len(rows), "건")
    for r in rows[:3]: print("  샘플", r)
    pick = [r for r in rows if any(k.lower() in r["title"].lower() for k in KW) and (r["when"].startswith(today) or ":" in r["when"] and len(r["when"]) <= 5)]
    pick.sort(key=lambda r: (r["rec"], r["views"]), reverse=True)
    print("조건 일치", len(pick), "건 (오늘=" + today + ")")
    pick = pick[:TOP]
    out = Path("out"); (out / "img").mkdir(parents=True, exist_ok=True)
    res = []
    for r in pick:
        p = post(r["no"]); p.update(views=r["views"], rec=r["rec"], when=r["when"])
        mism = p["title"] and r["title"][:6] not in p["title"]
        if mism: p["warn"] = "목록 제목과 본문 제목이 다름"
        for i, u in enumerate(p.get("images", [])[:3]):
            try:
                b = S.get(u, headers={"Referer": p["url"]}, timeout=25)
                time.sleep(DELAY)
                ct = b.headers.get("content-type", "")
                p.setdefault("img_dbg", []).append([b.status_code, ct, len(b.content), u[:90]])
                h = b.content[:12]
                ext = "gif" if h[:3] == b"GIF" else "png" if h[:4] == b"\x89PNG" else "jpg" if h[:3] == b"\xff\xd8\xff" else "webp" if h[:4] == b"RIFF" and h[8:12] == b"WEBP" else None
                if b.ok and ext and len(b.content) <= 8_000_000:
                    f = out / "img" / f"{r['no']}_{i}.{ext}"; f.write_bytes(b.content); p.setdefault("saved", []).append(f.name)
            except Exception as e: p.setdefault("img_err", []).append(str(e)[:80])
        p["kind"] = kind(r["title"], p)
        p["video_files"] = []
        for i, u in enumerate([v for v in p.get("videos", []) if "movie_view" not in v][:6]):
            try:
                b = S.get(u, headers={"Referer": p["url"]}, timeout=40)
                time.sleep(DELAY)
                h = b.content[:12]
                ext = "mp4" if h[4:8] == b"ftyp" else "webm" if h[:4] == b"\x1a\x45\xdf\xa3" else "gif" if h[:3] == b"GIF" else "webp" if h[:4] == b"RIFF" else None
                p.setdefault("vid_dbg", []).append([b.status_code, b.headers.get("content-type", ""), len(b.content), ext])
                if b.ok and ext and len(b.content) <= 12_000_000:
                    f = out / "img" / f"{r['no']}_v{i}.{ext}"; f.write_bytes(b.content); p.setdefault("vsaved", []).append(f.name)
            except Exception as e: p.setdefault("img_err", []).append(str(e)[:80])
        res.append(p)
        print(r["no"], r["rec"], r["title"][:40], "이미지", len(p.get("images", [])), "영상", len(p.get("videos", [])), p.get("warn", ""))
    (out / "resolve_dbg.json").write_text(json.dumps(RESOLVE_DBG[:6], ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "digest.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
