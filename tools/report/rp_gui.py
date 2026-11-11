"""악성 댓글 신고서 만들기 - 프로그램 창(pywebview). 서버 없이 창 안에서 동작하고, 데이터는 프로그램 옆 data 폴더에만 저장한다."""
import os, subprocess, sys, threading, time, webbrowser
from datetime import datetime
from pathlib import Path
import rp_core as core

NOWIN = 0x08000000 if os.name == "nt" else 0
OPEN_OK = ("https://www.youtube.com/", "https://youtu.be/", "https://ecrm.police.go.kr")

HTML = r"""<!doctype html><meta charset=utf-8><title>악성 댓글 신고서</title>
<style>*{box-sizing:border-box}body{font:14px "Malgun Gothic",system-ui,sans-serif;margin:0;background:#1c1c1e;color:#e8e8e8}
header{display:flex;gap:4px;padding:10px 14px;border-bottom:1px solid #333;position:sticky;top:0;background:#1c1c1e;z-index:2}
header b{margin-right:14px;line-height:32px}.tab{padding:6px 14px;border-radius:6px;cursor:pointer;color:#aaa}.tab.on{background:#2f2f33;color:#fff}
main{padding:16px 18px;max-width:1000px;margin:auto}section{display:none}section.on{display:block}
input,select,button,textarea{font:inherit;padding:7px 10px;border-radius:6px;border:1px solid #444;background:#2a2a2c;color:inherit}
textarea{width:100%;resize:vertical}button{cursor:pointer}button.p{background:#5b6ee1;border-color:#5b6ee1}button.d{background:#8a3b3b;border-color:#8a3b3b}button:disabled{opacity:.5}
.row{display:flex;gap:8px;flex-wrap:wrap;margin:9px 0;align-items:center}label{color:#aaa}.note{color:#999;font-size:12px;margin:4px 0}
#log{white-space:pre-wrap;color:#8a9;font-size:12px;margin:8px 0;max-height:150px;overflow:auto}
.card{background:#252527;border-radius:8px;padding:11px 13px;margin:9px 0}.card.confirm{border-left:3px solid #d65;}.card.skip{opacity:.5}
.meta{color:#999;font-size:12px}.txt{white-space:pre-wrap;margin:6px 0;word-break:break-word}mark{background:#6b4;color:#000;padding:0 2px;border-radius:3px}
.tag{display:inline-block;background:#3a3a40;border-radius:10px;padding:1px 8px;font-size:11px;margin-right:4px}
.chip{padding:4px 11px;border-radius:14px;background:#2a2a2c;cursor:pointer;border:1px solid #444}.chip.on{background:#5b6ee1;border-color:#5b6ee1}
pre{white-space:pre-wrap;background:#16161a;padding:12px;border-radius:8px;font-size:12.5px;max-height:520px;overflow:auto}</style>
<header><b>악성 댓글 신고서</b><span class="tab on" data-t=scan>탐색</span><span class=tab data-t=review>검수 <span id=cnt></span></span><span class=tab data-t=pack>신고서</span><span class=tab data-t=set>설정</span></header>
<main>
<section id=scan class=on>
 <div class=note>영상 링크나 채널 링크(@이름)를 한 줄에 하나씩 넣으세요. 댓글을 모아 악성 후보를 표시합니다.</div>
 <textarea id=targets rows=5 placeholder="https://www.youtube.com/watch?v=...&#10;https://www.youtube.com/@채널이름"></textarea>
 <div class=row><label>채널은 최근 영상</label><input id=nvid type=number value=10 style=width:60px><label>개</label>
 <label>영상당 최대 댓글</label><input id=lim type=number value=2000 style=width:80px><label>이 날짜 이후만</label><input id=since type=date></div>
 <div class=row><label>키워드로 영상 찾기</label><input id=kw placeholder="예: 리센느" style="width:180px"><input id=kwn type=number value=10 style=width:60px><label>개 (1회 100 단위 사용)</label></div>
 <div class=row><button class=p id=go>탐색 시작</button><button id=stop disabled>중지</button></div>
 <div id=log></div>
</section>
<section id=review>
 <div class=row><span class="chip on" data-f=cand>후보</span><span class=chip data-f=confirm>확정</span><span class=chip data-f=skip>제외</span><span class=chip data-f=all>전체</span>
 <input id=q placeholder="내용·작성자 검색" style="flex:1;min-width:160px"></div>
 <div class=note>비판이나 의견은 신고 대상이 아닙니다. 욕설·모욕·위협처럼 분명한 것만 '확정'하세요. 확정한 것만 신고서에 들어갑니다.</div>
 <div id=list></div><div class=row><button id=more style=display:none>더 보기</button></div>
</section>
<section id=pack>
 <div id=sum class=note></div>
 <div class=row><button class=p data-k=youtube>유튜브 신고 제출서</button><button data-k=agency>소속사 제보용</button><button data-k=police>경찰청 신고용 증거표</button></div>
 <div id=packout></div>
</section>
<section id=set>
 <div class=row><label>YouTube API 키</label><input id=key type=password style="flex:1;min-width:240px" placeholder="AIza..."></div>
 <div class=note>Google Cloud에서 YouTube Data API v3 키를 발급받아 넣으세요. 키는 이 컴퓨터의 data 폴더에만 저장됩니다.</div>
 <div class=note>후보 단어 (한 줄에 "분류: 단어, 단어")</div><textarea id=rules rows=9></textarea>
 <div class=row><button class=p id=saveset>저장</button><button id=openfolder>데이터 폴더 열기</button><span id=setmsg class=note></span></div>
</section>
</main>
<script>
const $=id=>document.getElementById(id),api=()=>window.pywebview.api;let flt='cand',shown=60,timer=null,cats=[];
const esc=s=>(s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x===t));document.querySelectorAll('section').forEach(s=>s.classList.toggle('on',s.id===t.dataset.t));if(t.dataset.t=='review')render();if(t.dataset.t=='pack')summary()});
document.querySelectorAll('.chip').forEach(c=>c.onclick=()=>{document.querySelectorAll('.chip').forEach(x=>x.classList.toggle('on',x===c));flt=c.dataset.f;shown=60;render()});
$('q').oninput=()=>{shown=60;render()};$('more').onclick=()=>{shown+=60;render()};
async function init(){const s=await api().get_settings();$('key').value=s.key;$('rules').value=s.rules;cats=s.cats;render()}
window.addEventListener('pywebviewready',init);
$('saveset').onclick=async()=>{await api().save_settings($('key').value.trim(),$('rules').value);$('setmsg').textContent='저장했습니다'};
$('openfolder').onclick=()=>api().open_folder();
$('go').onclick=async()=>{const r=await api().start_scan({targets:$('targets').value,nvid:$('nvid').value,lim:$('lim').value,since:$('since').value,kw:$('kw').value,kwn:$('kwn').value});
 if(r.error){$('log').textContent=r.error;return}$('go').disabled=true;$('stop').disabled=false;poll()};
$('stop').onclick=()=>api().stop_scan();
function poll(){clearInterval(timer);timer=setInterval(async()=>{const s=await api().status();$('log').textContent=s.log;if(!s.running){clearInterval(timer);$('go').disabled=false;$('stop').disabled=true;render()}},1000)}
async function render(){const r=await api().list_items(flt,$('q').value,shown);$('cnt').textContent='('+r.counts.cand+')';
 document.querySelectorAll('.chip').forEach(c=>{const k=c.dataset.f;c.textContent={cand:'후보',confirm:'확정',skip:'제외',all:'전체'}[k]+' '+r.counts[k]});
 $('list').innerHTML=r.items.map(it=>{let t=esc(it.text);for(const h of it.hits){const e=esc(h);t=t.split(e).join('<mark>'+e+'</mark>')}
  return `<div class="card ${it.status}" id="c_${it.id}"><div class=meta><b>${esc(it.author)}</b> · ${it.time} · 👍${it.likes}${it.reply?' · 답글':''} · ${esc(it.vtitle)}</div>
  <div class=txt>${t}</div><div>${it.cats.map(c=>`<span class=tag>${esc(c)}</span>`).join('')}</div>
  <div class=row><button class="${it.status=='confirm'?'d':''}" onclick="st('${it.id}','confirm')">확정</button><button onclick="st('${it.id}','skip')">제외</button><button onclick="st('${it.id}','cand')">되돌리기</button>
  <button onclick="api().open_url('${it.link}')">댓글 열기</button>
  <select onchange="rc('${it.id}',this.value)">${r.cats.map(c=>`<option ${c==it.rcat?'selected':''}>${esc(c)}</option>`).join('')}</select>
  <input placeholder="메모" value="${esc(it.memo||'')}" onchange="mm('${it.id}',this.value)" style="flex:1;min-width:120px"></div></div>`}).join('')||'<div class=note>표시할 댓글이 없습니다.</div>';
 $('more').style.display=r.total>r.items.length?'':'none'}
async function st(id,s){await api().set_status(id,s);render()}async function rc(id,c){await api().set_cat(id,c)}async function mm(id,m){await api().set_memo(id,m)}
async function summary(){const s=await api().summary();$('sum').textContent=`확정 ${s.n}건 · 계정 ${s.acc}개`+(s.n?'':' — 검수 탭에서 먼저 확정하세요')}
document.querySelectorAll('#pack button[data-k]').forEach(b=>b.onclick=async()=>{const r=await api().make_pack(b.dataset.k);
 if(r.error){$('packout').innerHTML='<div class=note>'+esc(r.error)+'</div>';return}
 window._k=b.dataset.k;$('packout').innerHTML=`<div class=row><button class=p id=cp>전체 복사</button><button id=sv>파일로 저장</button><span id=pm class=note></span></div><pre id=ptxt>${esc(r.text)}</pre>`;
 $('cp').onclick=async()=>{const ok=await api().copy(r.text);$('pm').textContent=ok?'복사했습니다':'복사 실패 - 글을 직접 선택해 복사하세요'};
 $('sv').onclick=async()=>{const p=await api().save_pack(window._k);$('pm').textContent='저장: '+p}});
</script>"""


class Api:
    def __init__(self):
        self.job = dict(running=False, log="", stop=False)
        self.lock = threading.Lock()

    # --- 설정 ---
    def get_settings(self):
        s = core.load_json("settings.json", {})
        return dict(key=s.get("key", ""), rules=s.get("rules") or core.DEFAULT_RULES, cats=list(core.parse_rules(s.get("rules") or core.DEFAULT_RULES)) + [core.OTHER])

    def save_settings(self, key, rules):
        core.save_json("settings.json", dict(key=key, rules=rules)); return True

    def open_folder(self):
        d = str(core.data_dir())
        try: os.startfile(d)
        except AttributeError: subprocess.run(["xdg-open", d])

    def open_url(self, url):
        if any(url.startswith(p) for p in OPEN_OK): webbrowser.open(url)

    def copy(self, text):
        try:
            if os.name == "nt":
                subprocess.run(["clip"], input=("﻿" + text).encode("utf-16le"), check=True, creationflags=NOWIN); return True
        except Exception: pass
        return False

    # --- 탐색 ---
    def _log(self, m):
        with self.lock: self.job["log"] += m + "\n"

    def status(self):
        with self.lock: return dict(running=self.job["running"], log=self.job["log"][-3000:])

    def stop_scan(self): self.job["stop"] = True

    def start_scan(self, o):
        s = core.load_json("settings.json", {})
        if not s.get("key"): return dict(error="설정 탭에서 YouTube API 키를 먼저 넣어주세요.")
        if self.job["running"]: return dict(error="이미 실행 중입니다.")
        self.job = dict(running=True, log="", stop=False)
        threading.Thread(target=self._scan, args=(o, s), daemon=True).start()
        return dict(ok=True)

    def _scan(self, o, s):
        key = s["key"]; rules = core.parse_rules(s.get("rules") or core.DEFAULT_RULES); stop = lambda: self.job["stop"]
        items = core.load_json("items.json", {}); meta = core.load_json("meta.json", {"titles": {}})
        try:
            vids = []
            for line in o["targets"].splitlines():
                t = core.parse_target(line)
                if not line.strip(): continue
                if not t: self._log("알 수 없는 링크 건너뜀: " + line.strip()[:60]); continue
                if t[0] == "video": vids.append(t[1])
                else:
                    got = core.channel_videos(t, int(o.get("nvid") or 10), key); self._log(f"채널 {t[1]}: 최근 영상 {len(got)}개"); vids += got
            if (o.get("kw") or "").strip():
                got = core.search_videos(o["kw"].strip(), int(o.get("kwn") or 10), key); self._log(f"키워드 '{o['kw']}': 영상 {len(got)}개"); vids += got
            vids = list(dict.fromkeys(vids))
            if not vids: self._log("탐색할 영상이 없습니다."); return
            meta["titles"].update(core.video_titles(vids, key))
            new = total = 0
            for i, v in enumerate(vids, 1):
                if stop(): self._log("중지했습니다."); break
                try:
                    rows = core.collect_comments(v, key, rules, o.get("since") or None, int(o.get("lim") or 2000), stop)
                except core.ApiError as e:
                    if e.reason == "quotaExceeded": self._log("오늘 API 사용량을 모두 썼습니다. 내일 다시 하세요."); break
                    self._log(f"[{i}/{len(vids)}] 건너뜀({e.reason}): {meta['titles'].get(v, v)[:40]}"); continue
                total += len(rows); f = [r for r in rows if r["cats"]]; n = 0
                for r in f:
                    if r["id"] in items: items[r["id"]].update(hits=r["hits"], cats=r["cats"], likes=r["likes"]); continue
                    r["status"] = "cand"; r["seen"] = datetime.now().strftime("%Y-%m-%d %H:%M"); items[r["id"]] = r; n += 1
                new += n; self._log(f"[{i}/{len(vids)}] 댓글 {len(rows)}개 확인, 새 후보 {n}개 · {meta['titles'].get(v, v)[:40]}")
                core.save_json("items.json", items); core.save_json("meta.json", meta)
            self._log(f"완료: 댓글 {total}개 확인, 새 후보 {new}개. 검수 탭에서 확인하세요.")
        except core.ApiError as e: self._log("오류: " + str(e) + (" (키를 확인하세요)" if e.reason in ("keyInvalid", "forbidden", "badRequest") else ""))
        except Exception as e: self._log("오류: " + repr(e))
        finally:
            core.save_json("items.json", items); core.save_json("meta.json", meta); self.job["running"] = False

    # --- 검수 ---
    def list_items(self, flt, q, limit):
        items = core.load_json("items.json", {}); titles = core.load_json("meta.json", {"titles": {}})["titles"]; q = (q or "").lower()
        allv = sorted(items.values(), key=lambda x: x["time"], reverse=True)
        counts = {k: sum(1 for i in allv if k == "all" or i.get("status") == k) for k in ("cand", "confirm", "skip", "all")}
        sel = [i for i in allv if (flt == "all" or i.get("status") == flt) and (not q or q in i["text"].lower() or q in i["author"].lower())]
        out = [dict(i, vtitle=titles.get(i["vid"], i["vid"]), status=i.get("status", "cand"), rcat=i.get("rcat") or (i["cats"][0] if i["cats"] else core.OTHER)) for i in sel[:limit]]
        return dict(items=out, total=len(sel), counts=counts, cats=self.get_settings()["cats"])

    def _upd(self, id, **kw):
        items = core.load_json("items.json", {})
        if id in items: items[id].update(kw); core.save_json("items.json", items)
        return True

    def set_status(self, id, s): return self._upd(id, status=s) if s in ("cand", "confirm", "skip") else False
    def set_cat(self, id, c): return self._upd(id, rcat=c)
    def set_memo(self, id, m): return self._upd(id, memo=m[:200])

    # --- 신고서 ---
    def _confirmed(self):
        items = core.load_json("items.json", {})
        return [dict(i, rcat=i.get("rcat") or (i["cats"][0] if i["cats"] else core.OTHER)) for i in sorted(items.values(), key=lambda x: x["time"]) if i.get("status") == "confirm"]

    def summary(self):
        c = self._confirmed(); return dict(n=len(c), acc=len(core.by_account(c)))

    def make_pack(self, kind):
        c = self._confirmed()
        if not c: return dict(error="확정한 댓글이 없습니다. 검수 탭에서 먼저 확정하세요.")
        t = core.load_json("meta.json", {"titles": {}})["titles"]
        return dict(text={"youtube": core.pack_youtube, "agency": core.pack_agency, "police": core.pack_police}[kind](c, t))

    def save_pack(self, kind):
        c = self._confirmed(); t = core.load_json("meta.json", {"titles": {}})["titles"]
        text = self.make_pack(kind).get("text", ""); d = core.data_dir() / "reports"; d.mkdir(exist_ok=True)
        stem = f"{ {'youtube': '유튜브신고', 'agency': '소속사제보', 'police': '경찰청증거표'}[kind] }_{datetime.now():%Y%m%d_%H%M%S}"
        (d / (stem + ".html")).write_text(core.to_html(stem, text, c), encoding="utf-8")
        (d / (stem + ".csv")).write_text(core.to_csv(c, t), encoding="utf-8-sig")
        return str(d / (stem + ".html"))


def main():
    if os.name == "nt" and getattr(sys, "frozen", False):
        try:
            import ctypes
            h = ctypes.windll.kernel32.GetConsoleWindow()
            if h: ctypes.windll.user32.ShowWindow(h, 0)
        except Exception: pass
    import webview
    webview.create_window("악성 댓글 신고서", html=HTML, js_api=Api(), width=1040, height=780, min_size=(760, 520))
    webview.start()


if __name__ == "__main__":
    main()
