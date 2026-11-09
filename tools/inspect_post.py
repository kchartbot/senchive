import os, re, requests
from bs4 import BeautifulSoup
g = os.environ["DC_GALLERY_ID"]; H = {"User-Agent": "Mozilla/5.0"}
kind = {"mini": "mini/board", "minor": "mgallery/board", "mgallery": "mgallery/board", "main": "board", "board": "board"}.get((os.environ.get("DC_KIND") or "").strip().lower(), "mini/board")
rows = BeautifulSoup(requests.get(f"https://gall.dcinside.com/{kind}/lists/?id={g}", headers=H, timeout=30).text, "html.parser").select("tr.ub-content[data-no]")
nos = sorted((int(r["data-no"]) for r in rows), reverse=True)[:int(os.environ.get("N", "3"))]
print("kind", kind, "rows", len(rows), nos)
for no in nos:
    s = BeautifulSoup(requests.get(f"https://gall.dcinside.com/{kind}/view/?id={g}&no={no}", headers=H, timeout=30).text, "html.parser")
    w = s.select_one("div.write_div"); t = (s.select_one("span.title_subject") or s.select_one("title")).get_text(" ", strip=True)
    if not w: print("==", no, t, "본문 없음"); continue
    html = str(w)
    print("==", no, t, "| img", html.count("<img"), "| video", html.count("<video"), "| iframe/embed", html.count("<iframe") + html.count("<embed"), "| 첨부", len(s.select(".appending_file li")))
    print("  classes:", sorted(set(re.findall(r'class="([^"]*)"', html)))[:8])
    print("  앞부분:", re.sub(r"(viewimage\.php\?[^\"']{16})[^\"']*", r"\1…", html)[:700])
