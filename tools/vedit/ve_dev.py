"""개발·시험 전용: 같은 화면과 Api 를 일반 브라우저(Playwright)에서 돌려 보기 위한 작은 서버. exe 에는 들어가지 않는다.
사용: python ve_dev.py 8800 영상1.mp4 영상2.mp4   (파일 선택창 대신 인자로 준 파일을 쓴다)"""
import json, os, sys, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ve_api

HERE = Path(__file__).resolve().parent


class DevApi(ve_api.Api):
    def __init__(self, files, outdir):
        super().__init__(); self.files = files; self.outdir = outdir; self.paths = {}
    def dialog_open(self, title, exts, multiple):
        if any("*.vproj" in e for e in exts): return [str(self.outdir / "p.vproj")] if (self.outdir / "p.vproj").exists() else []
        if any("ttf" in e for e in exts): return []
        return self.files
    def dialog_save(self, title, name, ext): return str(self.outdir / (name + ext))
    def url_for(self, mid, path): self.paths[mid] = path; return "/media/" + mid + "?" + Path(path).name


def make_handler(api):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            p = self.path.split("?")[0]
            if p in ("/", "/ve_ui.html"): return self.send(200, (HERE / "ve_ui.html").read_bytes(), "text/html; charset=utf-8")
            if p.startswith("/media/"):
                fp = api.paths.get(p[7:])
                if not fp or not os.path.isfile(fp): return self.send(404, b"")
                size = os.path.getsize(fp); rng = self.headers.get("Range"); s, e = 0, size - 1
                if rng:
                    m = re.match(r"bytes=(\d*)-(\d*)", rng)
                    if m.group(1): s = int(m.group(1))
                    if m.group(2): e = int(m.group(2))
                    self.send_response(206); self.send_header("Content-Range", f"bytes {s}-{e}/{size}")
                else: self.send_response(200)
                self.send_header("Content-Type", "video/mp4"); self.send_header("Accept-Ranges", "bytes"); self.send_header("Content-Length", str(e - s + 1)); self.end_headers()
                with open(fp, "rb") as f:
                    f.seek(s); left = e - s + 1
                    while left > 0:
                        b = f.read(min(1 << 20, left))
                        if not b: break
                        try: self.wfile.write(b)
                        except Exception: return
                        left -= len(b)
                return
            self.send(404, b"")
        def do_POST(self):
            m = self.path.split("/rpc/")[-1]; n = int(self.headers.get("Content-Length") or 0)
            args = json.loads(self.rfile.read(n) or b"[]")
            try: r = getattr(api, m)(*args)
            except Exception as ex: r = None; print("ERR", m, ex)
            self.send(200, json.dumps(r, ensure_ascii=False).encode("utf-8"), "application/json")
        def send(self, c, b, ct="application/octet-stream"):
            self.send_response(c); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    return H


if __name__ == "__main__":
    port = int(sys.argv[1]); outdir = Path(os.environ.get("VE_OUT", "."))
    api = DevApi([os.path.abspath(f) for f in sys.argv[2:]], outdir)
    ThreadingHTTPServer(("127.0.0.1", port), make_handler(api)).serve_forever()
