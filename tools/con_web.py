"""내 PC 에서 쓰는 콘 만들기 화면. 실행: python tools/con_web.py  ->  브라우저에서 http://localhost:8765
유튜브 링크를 붙여넣거나 mp4 를 끌어다 놓으면 콘 세트와 문구를 만들어 보여준다. 파일은 내 컴퓨터 밖으로 나가지 않는다."""
import json, subprocess, sys, tempfile, threading, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse, unquote

ROOT = Path(__file__).resolve().parent
OUT = Path(tempfile.gettempdir()) / "con_web_out"
OUT.mkdir(exist_ok=True)
LOCK = threading.Lock()

PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>콘 만들기</title>
<style>body{font:15px system-ui,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;background:#1a1a1a;color:#e8e8e8}
input,select,button{font:inherit;padding:8px 10px;border-radius:6px;border:1px solid #444;background:#262626;color:inherit}
button{background:#5b6ee1;border-color:#5b6ee1;cursor:pointer}button:disabled{opacity:.5}
.row{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0;align-items:center}#drop{border:2px dashed #555;border-radius:10px;padding:22px;text-align:center;color:#999}
#drop.on{border-color:#5b6ee1;color:#fff}#log{white-space:pre-wrap;color:#9aa;font-size:13px;margin:10px 0}
.g{display:flex;flex-wrap:wrap;gap:12px;margin-top:14px}.c{background:#242424;padding:8px;border-radius:8px;text-align:center;font-size:12px;color:#aaa}
.c img{display:block;margin:0 auto 6px;background:#fff}</style>
<h2>콘 만들기</h2>
<div class=row><input id=url placeholder="유튜브 링크" style="flex:1;min-width:240px"></div>
<div id=drop>또는 mp4 파일을 여기에 끌어다 놓기 (클릭해서 선택)<input id=file type=file accept="video/*" hidden></div>
<div class=row>개수 <input id=count type=number value=8 style=width:60px> 길이(초) <input id=length type=number step=.5 value=2.5 style=width:60px>
크기(px) <input id=size type=number value=200 style=width:70px> 최대 KB <input id=maxkb type=number value=300 style=width:70px>
문구 <select id=text><option value=auto>자동</option><option value=subtitle>자막만</option><option value=phrase>고정 문구</option><option value=none>없음</option></select>
시작 <input id=start type=number value=0 style=width:60px>초 끝 <input id=end type=number value=0 style=width:60px>초</div>
<div class=row><button id=go>만들기</button><a id=zip style=display:none href=# download>zip 받기</a></div>
<div id=log></div><div class=g id=g></div>
<script>
const $=id=>document.getElementById(id);let picked=null;
$('drop').onclick=()=>$('file').click();$('file').onchange=e=>{picked=e.target.files[0];$('drop').textContent=picked?picked.name:'';};
$('drop').ondragover=e=>{e.preventDefault();$('drop').classList.add('on')};$('drop').ondragleave=()=>$('drop').classList.remove('on');
$('drop').ondrop=e=>{e.preventDefault();$('drop').classList.remove('on');picked=e.dataTransfer.files[0];$('drop').textContent=picked.name};
$('go').onclick=async()=>{
  const q=new URLSearchParams({count:count.value,length:length.value,size:size.value,maxkb:maxkb.value,text:text.value,start:start.value,end:end.value});
  let init;
  if(picked){q.set('name',picked.name);init={method:'POST',body:picked};}else if(url.value.trim()){q.set('url',url.value.trim());init={method:'POST',body:''};}else{$('log').textContent='링크나 파일을 넣어주세요';return}
  $('go').disabled=true;$('g').innerHTML='';$('zip').style.display='none';$('log').textContent='만드는 중… (영상 길이에 따라 1~3분)';
  try{const r=await fetch('/make?'+q,init);const j=await r.json();$('log').textContent=j.log||'';
    if(j.items){$('g').innerHTML=j.items.map(x=>`<div class=c><img src="/f/${j.id}/${x.file}" width=${x.size}>${x.file} · ${x.kb}KB<br>${x.caption||''}</div>`).join('');
      $('zip').href=`/f/${j.id}/dccon.zip`;$('zip').style.display=''}}
  catch(e){$('log').textContent='오류: '+e}$('go').disabled=false};
</script>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", ctype + ("; charset=utf-8" if "text" in ctype or "json" in ctype else ""))
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/": return self.send(200, PAGE, "text/html")
        if u.path.startswith("/f/"):
            parts = unquote(u.path).split("/")
            if len(parts) == 4 and parts[2].isdigit() and "/" not in parts[3] and ".." not in parts[3]:
                p = OUT / parts[2] / parts[3]
                if p.exists():
                    ct = {"gif": "image/gif", "zip": "application/zip"}.get(p.suffix[1:], "application/octet-stream")
                    return self.send(200, p.read_bytes(), ct)
        self.send(404, "{}")

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/make": return self.send(404, "{}")
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        n = int(self.headers.get("Content-Length") or 0)
        with LOCK:
            jid = str(len(list(OUT.iterdir())) + 1000 + int(__import__("time").time()) % 100000)
            d = OUT / jid; d.mkdir(parents=True)
            if q.get("url"):
                src = q["url"]
            else:
                src = str(d / ("in" + Path(q.get("name", "a.mp4")).suffix)); remain = n
                with open(src, "wb") as f:
                    while remain > 0:
                        chunk = self.rfile.read(min(1 << 20, remain)); f.write(chunk); remain -= len(chunk)
            cmd = [sys.executable, str(ROOT / "con_maker.py"), src, "--out", str(d / "o"), "--count", q.get("count", "8"), "--length", q.get("length", "2.5"),
                   "--size", q.get("size", "200"), "--max-kb", q.get("maxkb", "300"), "--text", q.get("text", "auto"),
                   "--start", q.get("start", "0"), "--end", q.get("end", "0")]
            r = subprocess.run(cmd, capture_output=True, text=True)
            o = d / "o"
            items = json.loads((o / "index.json").read_text(encoding="utf-8")) if (o / "index.json").exists() else None
            if items:
                for f in o.iterdir(): f.rename(d / f.name)
            self.send(200, json.dumps(dict(id=jid, items=items, log=(r.stdout + r.stderr)[-1500:]), ensure_ascii=False))


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", 8765), H)
    print("http://localhost:8765 에서 열립니다 (끄려면 Ctrl+C)")
    try: webbrowser.open("http://localhost:8765")
    except Exception: pass
    srv.serve_forever()
