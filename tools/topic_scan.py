"""떡밥 후보 탐색용 읽기 전용 수집: 개념글(+평소 글 제목 기준선)을 기간 내 모아 out/topics.json 에 저장."""
import os, re, json, sys
from pathlib import Path
from bs4 import BeautifulSoup
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dc_digest as d

SINCE = os.environ.get("SINCE", "2026.11.02")
GALL = os.environ.get("GALL_ID", "kpopcontent")
d.GALL, d.KIND, d.HEAD = GALL, os.environ.get("GALL_KIND", "mgallery"), ""
MAXP = int(os.environ.get("MAXP", "40"))
GROUP = [k for k in os.environ.get("GROUP_KW", "리센느,센느,센둥이,RESCENE,rescene,리브,원이,미나미,메이,제나,대장,원짱,원쨩,냠이,미남이,여보,리부,메갓,까엉,까엉이,펄스,PULSE,20kg,06즈,막내즈,mz즈").split(",") if k]
# 떡밥 신호 단어 (제목에 있으면 r["bait"]에 표시)
BAIT = [k for k in os.environ.get("BAIT_KW", "비하인드,떴다,떳다").split(",") if k]

def rows(extra, maxp):
    out = []
    for p in range(1, maxp + 1):
        url = f"{d.BASE}/{d.KIND}/board/lists/?id={GALL}&sort_type=N&page={p}{extra}"
        soup = BeautifulSoup(d.get(url).text, "html.parser")
        page = []
        for tr in soup.select("tr.ub-content"):
            no = tr.get("data-no"); a = tr.select_one("td.gall_tit a")
            if not (no and no.isdigit() and a): continue
            dt = tr.select_one("td.gall_date"); when = (dt.get("title") or dt.get_text()).strip().replace("-", ".") if dt else ""
            num = lambda sel: int(re.sub(r"\D", "", (tr.select_one(sel).get_text() if tr.select_one(sel) else "") or "0") or 0)
            head = tr.select_one("td.gall_subject"); 
            page.append(dict(no=int(no), title=a.get_text(" ", strip=True), when=when, views=num("td.gall_count"), rec=num("td.gall_recommend"), head=head.get_text(strip=True) if head else ""))
        if not page: break
        out += page
        if min((r["when"] for r in page if re.match(r"\d{4}\.", r["when"])), default="9999") < SINCE: break
    return [r for r in {r["no"]: r for r in out}.values() if r["when"] >= SINCE]

best = rows("&exception_mode=recommend", MAXP)
print("개념글", len(best))
base = rows("", MAXP)
print("기준선(전체글 제목)", len(base))
for i, r in enumerate(best):
    try:
        p = d.post(r["no"])
    except SystemExit:
        raise
    except Exception as e:
        p = dict(error=str(e)[:80])
    r.update(images=len(p.get("images", [])), videos=len(p.get("videos", [])), links=p.get("links", []), text=p.get("text", ""))
    r["bait"] = [k for k in BAIT if k in r["title"]]
    r["group"] = any(k.lower() in (r["title"] + " " + r["text"]).lower() for k in GROUP)
    if i % 20 == 0: print("본문", i, "/", len(best))
Path("out").mkdir(exist_ok=True)
json.dump(dict(since=SINCE, best=best, base=[dict(title=r["title"], when=r["when"], rec=r["rec"]) for r in base]), open("out/topics.json", "w", encoding="utf-8"), ensure_ascii=False)
print("저장 완료")
