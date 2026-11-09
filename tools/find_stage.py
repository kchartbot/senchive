"""유튜브에서 오늘자 무대 영상 링크 찾기 (읽기 전용 검색). 못 찾으면 빈 목록."""
import re, json, requests

def find(event_kw, group_kw=("리센느", "RESCENE"), hours=36, limit=3):
    out = []
    for q in (f"{event_kw[0]} 리센느 무대", f"{event_kw[0]} RESCENE", f"{event_kw[0]} 리센느 With", f"{event_kw[0]} 리센느 백화요란"):
        try:
            r = requests.get("https://www.youtube.com/results", params={"search_query": q, "sp": "CAI%3D", "hl": "ko"},
                             headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR,ko;q=0.9"}, timeout=20)
            m = re.search(r"var ytInitialData = (\{.*?\});</script>", r.text, re.S)
            data = json.loads(m.group(1))
        except Exception as e:
            print("유튜브 검색 실패:", q, str(e)[:100]); continue
        def walk(o):
            if isinstance(o, dict):
                if "videoRenderer" in o: yield o["videoRenderer"]
                for v in o.values(): yield from walk(v)
            elif isinstance(o, list):
                for v in o: yield from walk(v)
        for v in walk(data):
            title = "".join(x.get("text", "") for x in v.get("title", {}).get("runs", []))
            when = v.get("publishedTimeText", {}).get("simpleText", "")
            chan = "".join(x.get("text", "") for x in v.get("ownerText", {}).get("runs", []))
            print("후보:", title[:60], "|", chan, "|", when)
            if not any(g.lower() in title.lower() for g in group_kw): continue
            blob = (title + " " + chan).lower()
            if not any(k.lower() in blob for k in event_kw) and "inkigayo" not in blob: continue
            if not any(c in chan.lower() for c in ("inkigayo", "sbs")): continue  # 방송사 공식 채널만
            if "직캠" in title or "fancam" in blob or "fullcam" in blob or "사녹" in title or "퇴근길" in title: continue
            if not re.search(r"(분|시간|minute|hour)", when): continue
            h = re.search(r"(\d+)\s*(시간|hour)", when)
            if h and int(h.group(1)) > hours: continue
            url = "https://www.youtube.com/watch?v=" + v["videoId"]
            if url not in out: out.append(url)
    return out[:limit]
