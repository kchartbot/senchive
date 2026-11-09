import os, sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dc_digest as d
from bs4 import BeautifulSoup
want = [int(x) for x in os.environ["NOS"].split(",")]
found = {}
for p in range(1, 5):
    s = BeautifulSoup(d.get(f"{d.BASE}/mgallery/board/lists/?id=kpopcontent&sort_type=N&exception_mode=recommend&page={p}").text, "html.parser")
    for tr in s.select("tr.ub-content[data-no]"):
        no = int(tr["data-no"])
        if no in want:
            rec = tr.select_one("td.gall_recommend"); found[no] = (tr.select_one("td.gall_tit a").get_text(" ", strip=True)[:30], rec.get_text(strip=True) if rec else "")
for n in want: print("개념글" if n in found else "일반글", n, found.get(n, ""))
