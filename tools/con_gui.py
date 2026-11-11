"""콘 만들기 프로그램 창. 서버 없이 창 안에서 바로 동작한다(pywebview). 파일은 내 컴퓨터 밖으로 나가지 않는다."""
import base64, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = Path(tempfile.gettempdir()) / "dccon_gui"
NOWIN = 0x08000000 if os.name == "nt" else 0

HTML = """<!doctype html><meta charset=utf-8><title>콘 만들기</title>
<style>*{box-sizing:border-box}body{font:14px "Malgun Gothic",system-ui,sans-serif;margin:0;padding:18px;background:#1c1c1e;color:#e8e8e8}
h2{margin:0 0 12px;font-size:18px}input,select,button{font:inherit;padding:7px 10px;border-radius:6px;border:1px solid #444;background:#2a2a2c;color:inherit}
button{cursor:pointer}button.p{background:#5b6ee1;border-color:#5b6ee1}button:disabled{opacity:.5;cursor:default}
.row{display:flex;gap:8px;flex-wrap:wrap;margin:9px 0;align-items:center}label{color:#aaa}#src{flex:1;min-width:220px}
#log{white-space:pre-wrap;color:#8a9;font-size:12px;margin:8px 0;max-height:110px;overflow:auto}
.g{display:flex;flex-wrap:wrap;gap:10px}.c{background:#252527;padding:8px;border-radius:8px;text-align:center;font-size:12px;color:#aaa;width:216px}
.c img{display:block;margin:0 auto 6px;background:#fff;width:200px;height:200px}</style>
<h2>콘 만들기</h2>
<div class=row><input id=src placeholder="유튜브 링크를 붙여넣거나, 오른쪽에서 영상 파일 선택"><button id=pick>영상 파일 선택</button></div>
<div class=row><label>개수</label><input id=count type=number value=10 style=width:60px><label>길이(초)</label><input id=length type=number step=.5 value=2.5 style=width:60px>
<label>크기</label><input id=size type=number value=200 style=width:65px><label>최대 KB</label><input id=maxkb type=number value=500 style=width:70px>
<label>문구</label><select id=text><option value=auto>자동</option><option value=subtitle>자막만</option><option value=phrase>고정 문구</option><option value=none>없음</option></select>
<label>구간(초)</label><input id=start type=number value=0 style=width:55px>~<input id=end type=number value=0 style=width:55px></div>
<div class=row><button class=p id=go>만들기</button><button id=save style=display:none>zip 저장</button><button id=open style=display:none>폴더 열기</button></div>
<div id=log></div><div class=g id=g></div>
<script>
const $=id=>document.getElementById(id);const api=()=>window.pywebview.api;
$('pick').onclick=async()=>{const p=await api().pick_file();if(p)$('src').value=p};
$('go').onclick=async()=>{const s=$('src').value.trim();if(!s){$('log').textContent='링크를 넣거나 영상 파일을 선택하세요';return}
 $('go').disabled=true;$('save').style.display=$('open').style.display='none';$('g').innerHTML='';$('log').textContent='만드는 중입니다… (영상 길이에 따라 1~3분)';
 const o={src:s};for(const k of['count','length','size','maxkb','text','start','end'])o[k]=$(k).value;
 try{const j=await api().make(o);$('log').textContent=j.log||'';
  if(j.items){$('g').innerHTML=j.items.map(x=>`<div class=c><img src="${x.data}">${x.file} · ${x.kb}KB<br>문구 ${x.caption||''} · 알트 ${x.alt}</div>`).join('');$('save').style.display=$('open').style.display=''}}
 catch(e){$('log').textContent='오류: '+e}$('go').disabled=false};
$('save').onclick=async()=>{const r=await api().save_zip();if(r)$('log').textContent='저장했습니다: '+r};
$('open').onclick=()=>api().open_folder();
</script>"""


class Api:
    def __init__(self):
        self.last = None

    def pick_file(self):
        import webview
        w = webview.windows[0]
        kind = webview.FileDialog.OPEN if hasattr(webview, "FileDialog") else webview.OPEN_DIALOG
        r = w.create_file_dialog(kind, file_types=("영상 파일 (*.mp4;*.mov;*.mkv;*.webm;*.avi)", "모든 파일 (*.*)"))
        return r[0] if r else None

    def make(self, o):
        OUT.mkdir(exist_ok=True)
        d = OUT / str(int(time.time()))
        exe = [sys.executable, "--maker"] if getattr(sys, "frozen", False) else [sys.executable, str(ROOT / "con_maker.py")]
        num = lambda k, dflt: str(o.get(k) or dflt)
        cmd = exe + [str(o["src"]), "--out", str(d), "--count", num("count", 10), "--length", num("length", 2.5), "--size", num("size", 200),
                     "--max-kb", num("maxkb", 500), "--text", str(o.get("text") or "auto"), "--start", num("start", 0), "--end", num("end", 0)]
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NOWIN, encoding="utf-8", errors="replace",
                           env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
        items = None
        if (d / "index.json").exists():
            items = json.loads((d / "index.json").read_text(encoding="utf-8"))
            for x in items:
                x["data"] = "data:image/gif;base64," + base64.b64encode((d / x["file"]).read_bytes()).decode()
            self.last = d
        return dict(items=items, log=(r.stdout + r.stderr)[-1200:])

    def save_zip(self):
        if not self.last: return None
        import webview
        kind = webview.FileDialog.SAVE if hasattr(webview, "FileDialog") else webview.SAVE_DIALOG
        r = webview.windows[0].create_file_dialog(kind, save_filename="dccon.zip")
        if not r: return None
        dst = r if isinstance(r, str) else r[0]
        shutil.copy(self.last / "dccon.zip", dst)
        return dst

    def open_folder(self):
        if self.last:
            try: os.startfile(str(self.last))
            except AttributeError: subprocess.run(["xdg-open", str(self.last)])


def main():
    if os.name == "nt" and getattr(sys, "frozen", False):   # 검은 콘솔 창은 숨긴다
        try:
            import ctypes
            h = ctypes.windll.kernel32.GetConsoleWindow()
            if h: ctypes.windll.user32.ShowWindow(h, 0)
        except Exception: pass
    import webview
    webview.create_window("콘 만들기", html=HTML, js_api=Api(), width=960, height=760, min_size=(700, 500))
    webview.start()


if __name__ == "__main__":
    main()
