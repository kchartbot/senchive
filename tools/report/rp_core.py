"""악성 댓글 탐색/검수/신고서 만들기 - 수집·판별·제출서 로직. 데이터는 프로그램 옆 data 폴더에만 저장한다."""
import csv, hashlib, io, json, re, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://www.googleapis.com/youtube/v3/"
KST = timezone(timedelta(hours=9))

# 후보를 띄우는 기본 단어(검수 화면에서 사람이 확정하므로 넓게 잡는다). 설정에서 자유롭게 바꿀 수 있다.
DEFAULT_RULES = """욕설·비하: 시발, 씨발, 씨바, ㅅㅂ, ㅆㅂ, 병신, 븅신, ㅂㅅ, 지랄, 좆, 개새끼, 미친년, 미친놈, 쓰레기, 꺼져, 닥쳐
성적 모욕: 창녀, 걸레, 화냥, 몸팔
외모 비하: 성괴, 못생, 추녀, 뚱뚱, 돼지, 역겹
죽음·자해 조롱: 죽어, 뒤져, 뒤질, 디져, 자살해
위협: 찾아가, 죽여, 죽일, 불질러, 테러"""

# 유튜브 신고 메뉴에서 가장 가까운 항목(메뉴 이름은 유튜브가 바꿀 수 있다)
YT_MAP = {"욕설·비하": "괴롭힘 또는 사이버 폭력", "성적 모욕": "괴롭힘 또는 사이버 폭력", "외모 비하": "괴롭힘 또는 사이버 폭력",
          "죽음·자해 조롱": "괴롭힘 또는 사이버 폭력 (자해를 부추기면 자해 관련 항목)", "위협": "폭력 위협·협박"}
OTHER = "기타(직접 선택)"


def data_dir():
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    d = base / "data"; d.mkdir(exist_ok=True)
    return d


def load_json(name, default):
    p = data_dir() / name
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return default


def save_json(name, obj):
    p = data_dir() / name
    tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8"); tmp.replace(p)


# ---------- 판별 ----------
def parse_rules(text):
    rules = {}
    for line in (text or "").splitlines():
        if ":" not in line: continue
        cat, words = line.split(":", 1)
        ws = [w.strip() for w in re.split(r"[,\n]", words) if w.strip()]
        if cat.strip() and ws: rules[cat.strip()] = ws
    return rules


def squash(t):
    return re.sub(r"[\W_]+", "", (t or "").lower())   # 띄어쓰기·점으로 쪼갠 욕설(시.발)도 잡는다


def detect(text, rules):
    s = squash(text); cats, hits = [], []
    for cat, ws in rules.items():
        for w in ws:
            if squash(w) and squash(w) in s:
                if cat not in cats: cats.append(cat)
                hits.append(w)
    return cats, hits


# ---------- 유튜브 API ----------
class ApiError(Exception):
    def __init__(self, reason, msg=""): super().__init__(msg or reason); self.reason = reason


def api_get(ep, params, key, tries=3):
    url = API + ep + "?" + urllib.parse.urlencode(dict(params, key=key))
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try: reason = json.loads(e.read().decode("utf-8", "ignore"))["error"]["errors"][0]["reason"]
            except Exception: reason = str(e.code)
            if e.code >= 500 and i < tries - 1: time.sleep(1.5 * (i + 1)); continue
            raise ApiError(reason, f"{e.code} {reason}")
        except urllib.error.URLError as e:
            if i == tries - 1: raise ApiError("network", "네트워크 오류: " + str(e.reason))
            time.sleep(1.5 * (i + 1))


def parse_target(s):
    s = s.strip()
    if not s: return None
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/live/|/embed/)([\w-]{11})", s)
    if m: return ("video", m.group(1))
    if re.fullmatch(r"[\w-]{11}", s) and not s.startswith("@"): return ("video", s)
    m = re.search(r"/channel/(UC[\w-]{22})", s) or re.fullmatch(r"(UC[\w-]{22})", s)
    if m: return ("channel_id", m.group(1))
    m = re.search(r"@([\w.\-]+)", s)
    if m: return ("handle", m.group(1))
    return None


def channel_videos(target, n, key):
    kind, v = target
    p = {"part": "contentDetails"}; p["id" if kind == "channel_id" else "forHandle"] = v
    d = api_get("channels", p, key)
    if not d.get("items"): raise ApiError("notfound", "채널을 찾지 못했습니다: " + v)
    up = d["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    d = api_get("playlistItems", {"part": "contentDetails", "playlistId": up, "maxResults": min(50, n)}, key)
    return [i["contentDetails"]["videoId"] for i in d.get("items", [])][:n]


def search_videos(q, n, key):
    d = api_get("search", {"part": "snippet", "type": "video", "q": q, "order": "date", "maxResults": min(50, n)}, key)   # 호출 1회 = 100 단위
    return [i["id"]["videoId"] for i in d.get("items", [])]


def video_titles(ids, key):
    out = {}
    for i in range(0, len(ids), 50):
        d = api_get("videos", {"part": "snippet", "id": ",".join(ids[i:i + 50])}, key)
        for it in d.get("items", []): out[it["id"]] = it["snippet"]["title"]
    return out


def iso_kst(s):
    try: return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(KST).strftime("%Y-%m-%d %H:%M")
    except Exception: return s


def collect_comments(vid, key, rules, since=None, limit=2000, stop=lambda: False, on_page=None):
    """영상 하나의 댓글을 최신순으로 모아 판별한다. since(ISO 날짜) 이전 댓글이 나오면 멈춘다."""
    out, tok, n = [], None, 0
    while not stop():
        p = {"part": "snippet,replies", "videoId": vid, "maxResults": 100, "order": "time", "textFormat": "plainText"}
        if tok: p["pageToken"] = tok
        d = api_get("commentThreads", p, key)
        old = False
        for th in d.get("items", []):
            top = th["snippet"]["topLevelComment"]
            batch = [(top, False)] + [(r, True) for r in (th.get("replies") or {}).get("comments", [])]
            for c, is_reply in batch:
                sn = c["snippet"]; n += 1
                if since and sn["publishedAt"][:10] < since and not is_reply: old = True; continue
                cats, hits = detect(sn.get("textDisplay", ""), rules)
                out.append(dict(id=c["id"], vid=vid, text=sn.get("textDisplay", ""), author=sn.get("authorDisplayName", ""),
                                channel=(sn.get("authorChannelId") or {}).get("value", ""), time=iso_kst(sn["publishedAt"]), likes=sn.get("likeCount", 0),
                                reply=is_reply, cats=cats, hits=hits, link=f"https://www.youtube.com/watch?v={vid}&lc={c['id']}"))
        if on_page: on_page(n)
        tok = d.get("nextPageToken")
        if not tok or old or n >= limit: break
    return out


# ---------- 제출서 ----------
def esc(s): return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def explain(it):
    cat = it.get("rcat") or (it["cats"][0] if it.get("cats") else "")
    return {"위협": "특정인을 향한 위협·협박성 표현이 포함된 댓글입니다.", "죽음·자해 조롱": "특정인을 향해 죽음·자해를 조롱하거나 부추기는 표현이 포함된 댓글입니다.",
            "성적 모욕": "특정인을 향한 성적 모욕 표현이 포함된 댓글입니다.", "외모 비하": "특정인의 외모를 비하하는 표현이 포함된 댓글입니다."}.get(
        cat, "특정인을 향한 욕설·모욕적 표현이 포함되어 괴롭힘에 해당하는 댓글입니다.")


def by_account(items):
    g = {}
    for it in items: g.setdefault(it.get("channel") or it["author"], []).append(it)
    return sorted(g.values(), key=lambda x: -len(x))


def evidence_hash(items):
    raw = json.dumps([[i["id"], i["text"], i["time"], i["channel"]] for i in sorted(items, key=lambda x: x["id"])], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def pack_youtube(items, titles):
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    L = [f"[YouTube 댓글 신고 제출서]  작성 {now} (KST) · 확정 {len(items)}건", "",
         "신고 방법: ① 댓글 링크를 엽니다 ② 댓글 오른쪽 ⋮ → 신고 ③ 아래 '신고 분류'와 가장 가까운 항목을 고릅니다 ④ 설명 칸이 나오면 '신고 설명'을 붙여넣습니다 ⑤ 제출", "(신고 메뉴의 이름은 유튜브 개편에 따라 다를 수 있습니다)", ""]
    n = 0
    for k, grp in enumerate(by_account(items), 1):
        a = grp[0]
        L.append(f"■ 계정 {k}: {a['author']}  (https://www.youtube.com/channel/{a['channel']})  - {len(grp)}건" if a["channel"] else f"■ 계정 {k}: {a['author']}  - {len(grp)}건")
        for it in grp:
            n += 1; cat = it.get("rcat") or (it["cats"][0] if it["cats"] else OTHER)
            L += [f" {n}) 영상: {titles.get(it['vid'], it['vid'])}", f"    댓글 링크: {it['link']}", f"    작성 시각: {it['time']}", f"    댓글 내용: {it['text']}",
                  f"    신고 분류: {YT_MAP.get(cat, '가장 가까운 항목을 직접 선택')}", f"    신고 설명: {explain(it)}"]
            if it.get("memo"): L.append(f"    메모: {it['memo']}")
            L.append("")
    L.append(f"증거 해시(SHA-256): {evidence_hash(items)}")
    return "\n".join(L)


def pack_agency(items, titles):
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    L = [f"[악성 댓글 제보 자료]  작성 {now} (KST) · {len(items)}건", "번호\t영상\t댓글 링크\t작성자 표시명\t채널 주소\t작성 시각\t분류\t내용"]
    for n, it in enumerate(items, 1):
        cat = it.get("rcat") or (it["cats"][0] if it["cats"] else OTHER)
        ch = f"https://www.youtube.com/channel/{it['channel']}" if it["channel"] else ""
        L.append("\t".join([str(n), titles.get(it["vid"], it["vid"]), it["link"], it["author"], ch, it["time"], cat, it["text"].replace("\n", " ").replace("\t", " ")]))
    L.append(f"증거 해시(SHA-256): {evidence_hash(items)}")
    return "\n".join(L)


def pack_police(items, titles):
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    L = [f"[사이버범죄 신고용 증거 정리표]  작성 {now} (KST)", "신고처: 경찰청 사이버범죄 신고시스템 (https://ecrm.police.go.kr)",
         "※ 어떤 죄에 해당하는지는 수사기관이 판단합니다. 아래는 사실관계와 증거 목록입니다.", "",
         "1. 플랫폼: YouTube", f"2. 증거 수집 일시: {now} (KST)", f"3. 대상 댓글 수: {len(items)}건 / 작성 계정 수: {len(by_account(items))}개", ""]
    n = 0
    for k, grp in enumerate(by_account(items), 1):
        a = grp[0]; L.append(f"[계정 {k}] 표시명: {a['author']} / 채널: {'https://www.youtube.com/channel/' + a['channel'] if a['channel'] else '확인 불가'}")
        for it in grp:
            n += 1; L += [f"  {n}. {it['time']}  {it['link']}", f"     내용: {it['text']}"]
        L.append("")
    L += ["4. 증거 보관: 댓글 화면 캡처를 함께 첨부하세요(댓글 링크가 삭제될 수 있습니다).", f"5. 증거 해시(SHA-256): {evidence_hash(items)}"]
    return "\n".join(L)


def to_csv(items, titles):
    b = io.StringIO(); w = csv.writer(b)
    w.writerow(["번호", "영상", "댓글 링크", "작성자 표시명", "채널 ID", "작성 시각", "분류", "내용", "메모"])
    for n, it in enumerate(items, 1):
        w.writerow([n, titles.get(it["vid"], it["vid"]), it["link"], it["author"], it["channel"], it["time"], it.get("rcat") or (it["cats"][0] if it["cats"] else OTHER), it["text"], it.get("memo", "")])
    return b.getvalue()


def to_html(title, text, items):
    rows = "".join(f'<li><a href="{esc(i["link"])}" target="_blank">{esc(i["author"])} · {esc(i["time"])}</a><br>{esc(i["text"])}</li>' for i in items)
    return f'<!doctype html><meta charset="utf-8"><title>{esc(title)}</title><style>body{{font:14px sans-serif;max-width:800px;margin:24px auto;padding:0 14px}}pre{{white-space:pre-wrap;background:#f4f4f4;padding:12px;border-radius:6px}}</style><h2>{esc(title)}</h2><pre>{esc(text)}</pre><h3>댓글 목록</h3><ol>{rows}</ol>'
