"""스캔 결과(out/review/index.json)의 글 정보를 아카이브(out/archive/archive.json)에 합친다. 사진 파일은 저장하지 않고 글 정보만 쌓는다."""
import json
from pathlib import Path

LIMIT = 20000
idx = json.loads(Path("out/review/index.json").read_text(encoding="utf-8"))
ap = Path("out/archive/archive.json")
old = {}
if ap.exists():
    try: old = {str(p["no"]): p for p in json.loads(ap.read_text(encoding="utf-8")).get("posts", [])}
    except Exception: old = {}
inc = (idx.get("kw") or {}).get("include", [])
for p in idx.get("posts", []):
    no = str(p["no"]); prev = old.get(no, {})
    kws = p.get("kws") or prev.get("kws") or [k for k in inc if k.lower() in p["title"].lower()]   # 예전 스캔 결과는 제목에서만 찾는다
    old[no] = dict(no=no, title=p["title"], when=p["when"], head=p.get("head", ""), rec=p.get("rec", 0), views=p.get("views", 0), url=p["url"],
                   kws=kws, links=len(p.get("links", [])), files=len(p.get("files", [])), bait=bool(p.get("bait")), seen=prev.get("seen") or idx.get("generated", ""))
posts = sorted(old.values(), key=lambda x: x["when"], reverse=True)[:LIMIT]
ap.parent.mkdir(parents=True, exist_ok=True)
ap.write_text(json.dumps(dict(updated=idx.get("generated", ""), posts=posts), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print("아카이브", len(posts), "글")
