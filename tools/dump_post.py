import os, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dc_digest as d
from bs4 import BeautifulSoup
d.GALL, d.KIND = "kpopcontent", "mgallery"
for no in os.environ["NOS"].split(","):
    s = BeautifulSoup(d.get(f"{d.BASE}/{d.KIND}/board/view/?id={d.GALL}&no={no}").text, "html.parser")
    w = s.select_one("div.write_div")
    h = re.sub(r"(viewimage\.php\?[^\"']{30})[^\"']*", r"\1…", str(w))
    print("==", no, len(h)); print(h[:1800])
    print("첨부:", [(a.get_text(strip=True)[:40], a.get("href", "")[:90]) for a in s.select(".appending_file li a")])
    for f in w.select("iframe"):
        u = f.get("src", "")
        if "movie_view" in u:
            r = d.resolve_video(u)
            print("  resolve", u[-12:], r, d.RESOLVE_DBG[-1:] if not r else "")
            t = d.get(u, headers={"Referer": d.BASE + "/"}).text.replace("\\/", "/")
            print("  URLs:", re.findall(r"https?://[^\"'\s<>]*(?:dcm|download|vod|stream|mov)[^\"'\s<>]*", t)[:6])
            print("  tags:", [m[:200] for m in re.findall(r"<(?:source|video)[^>]*>", t)][:4])
            print("  data:", [m[:160] for m in re.findall(r"(?:src|url|file|path)\s*[:=]\s*[\"'][^\"']{8,}[\"']", t)][:8])
