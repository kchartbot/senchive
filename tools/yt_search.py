import os, re, json, requests
q = os.environ["Q"]
r = requests.get("https://www.youtube.com/results", params={"search_query": q, "sp": "CAI%3D", "hl": "ko"}, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR,ko;q=0.9"}, timeout=20)
data = json.loads(re.search(r"var ytInitialData = (\{.*?\});</script>", r.text, re.S).group(1))
def walk(o):
    if isinstance(o, dict):
        if "videoRenderer" in o: yield o["videoRenderer"]
        for v in o.values(): yield from walk(v)
    elif isinstance(o, list):
        for v in o: yield from walk(v)
for v in list(walk(data))[:12]:
    t = "".join(x.get("text", "") for x in v.get("title", {}).get("runs", [])); c = "".join(x.get("text", "") for x in v.get("ownerText", {}).get("runs", []))
    print(v["videoId"], "|", t[:70], "|", c, "|", v.get("publishedTimeText", {}).get("simpleText", ""))
