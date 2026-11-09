"""ㅋ 급증 감지 -> 직전 개념글 확인 -> 관련 키워드가 많으면 키워드 추가 후 검색 (읽기 전용, 업로드 없음).
1) 최근 SPAN_H 시간 글 제목을 15분 단위로 나눠 'ㅋㅋㅋ 이상' 제목 비율을 본다. 평소(중앙값)의 2배 이상이고 MINRATIO 이상이면 급증.
2) 급증 시작 시각 직전 LOOKBACK_MIN 분 안에 개념글이 된 글을 모은다.
3) 그 글 제목에서 단어를 뽑아, 급증 구간 전체 글 제목에 몇 번 나오는지 센다. MINHITS 이상이면 '관련 키워드가 많다'.
4) 그런 키워드로 갤러리를 검색해 글 목록을 출력하고, out/spike/spike.json 에 add_keywords 로 저장한다 (수집/업로드는 하지 않음)."""
import os, re, json, sys, statistics, collections
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from bs4 import BeautifulSoup
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dc_digest as d

KST = timezone(timedelta(hours=9))
SPAN_H = float(os.environ.get("SPAN_H") or 4)
LOOKBACK_MIN = int(os.environ.get("LOOKBACK_MIN") or 90)
MINRATIO = float(os.environ.get("MINRATIO") or 0.25)
MINHITS = int(os.environ.get("MINHITS") or 5)
KK = re.compile(r"ㅋ{3,}|ㅌ{3,}")
STOP = set("이거 이건 저거 오늘 지금 진짜 그냥 근데 이제 너무 완전 하는 하고 했다 있는 없는 같은 다들 우리 여기 이게 저게 그게 아니 ㄹㅇ ㅇㅇ 시발 씨발 존나 사람 미친 ㅅㅂ 개추 개념글 오늘자".split())
KEEP_OUT = re.compile(r"버블|챌린지|총공|모금|스밍|구매|공구|굿즈|인증|입갤|대기방|꾸준글|헬퍼")
OUT = Path("out/spike"); OUT.mkdir(parents=True, exist_ok=True)
now = datetime.now(KST).replace(tzinfo=None)

def rows(extra="", pages=60, since=None):
    out = []
    for p in range(1, pages + 1):
        s = BeautifulSoup(d.get(f"{d.BASE}/{d.KIND}/board/lists/?id={d.GALL}&sort_type=N&page={p}{extra}").text, "html.parser")
        page = []
        for tr in s.select("tr.ub-content[data-no]"):
            a = tr.select_one("td.gall_tit a"); dt = tr.select_one("td.gall_date")
            if not (a and tr["data-no"].isdigit() and dt): continue
            w = (dt.get("title") or dt.get_text()).strip()
            try: t = datetime.strptime(w[:19], "%Y-%m-%d %H:%M:%S")
            except Exception: continue
            rec = tr.select_one("td.gall_recommend"); sj = tr.select_one("td.gall_subject")
            page.append(dict(no=int(tr["data-no"]), title=a.get_text(" ", strip=True), t=t, rec=int(re.sub(r"\D", "", rec.get_text()) or 0) if rec else 0, head=sj.get_text(strip=True) if sj else ""))
        print(f"  p{p}: {len(page)}개 {min((r['t'] for r in page), default='-')} ~ {max((r['t'] for r in page), default='-')}", file=sys.stderr, flush=True)
        if not page: break
        out += page
        if since and sorted(r["t"] for r in page)[len(page) // 2] < since: break  # 맨 위 고정 공지(옛 날짜)는 무시
    return [r for r in {r["no"]: r for r in out}.values() if not since or r["t"] >= since]

allp = rows(since=now - timedelta(hours=SPAN_H))
print(f"최근 {SPAN_H}시간 글 {len(allp)}개")
b = collections.defaultdict(lambda: [0, 0])
for r in allp:
    k = r["t"].replace(minute=r["t"].minute // 15 * 15, second=0); b[k][0] += 1; b[k][1] += bool(KK.search(r["title"]))
keys = sorted(b); ratios = {k: b[k][1] / b[k][0] for k in keys if b[k][0] >= 5}
for k in keys: print(f"  {k:%H:%M} 글 {b[k][0]:3d} ㅋ제목 {b[k][1]:3d} 비율 {b[k][1] / b[k][0]:.2f}")
base = statistics.median(ratios.values()) if ratios else 0
spikes = [k for k, v in ratios.items() if v >= max(MINRATIO, 2 * base)]
print("평소 비율", round(base, 2), "| 급증 구간", [f"{k:%H:%M}" for k in spikes])
res = dict(base=round(base, 3), spikes=[str(k) for k in spikes], best=[], add_keywords=[], hits={})
if spikes:
    start = min(spikes)
    best = [r for r in rows("&exception_mode=recommend", 30, since=start - timedelta(minutes=LOOKBACK_MIN)) if r["t"] <= start + timedelta(minutes=15)]
    best = [r for r in best if not KEEP_OUT.search(r["title"])]
    print(f"급증 시작 {start:%H:%M} 직전 {LOOKBACK_MIN}분 개념글 {len(best)}개")
    for r in sorted(best, key=lambda r: -r["rec"]): print("  ", r["no"], f"{r['t']:%H:%M}", "추", r["rec"], r["head"], r["title"][:50])
    window = [r for r in allp if r["t"] >= start - timedelta(minutes=30)]
    cnt = collections.Counter()
    for r in best:
        for w in {w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", r["title"]) if w not in STOP}:
            cnt[w] = sum(w in x["title"] for x in window)
    res["best"] = [dict(no=r["no"], title=r["title"], rec=r["rec"]) for r in best]
    res["add_keywords"] = [w for w, c in cnt.most_common() if c >= MINHITS][:8]
    print("키워드별 등장 글 수", cnt.most_common(12), "| 추가 키워드", res["add_keywords"])
    for w in res["add_keywords"]:
        hit = rows(f"&s_type=search_subject_memo&s_keyword={quote(w)}", 3, since=start - timedelta(minutes=LOOKBACK_MIN))
        res["hits"][w] = [dict(no=r["no"], title=r["title"], when=f"{r['t']:%H:%M}", rec=r["rec"]) for r in hit]
        print(f"[{w}] 검색 {len(hit)}개")
        for r in hit[:6]: print("    ", r["no"], f"{r['t']:%H:%M}", r["title"][:50])
json.dump(res, open(OUT / "spike.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
