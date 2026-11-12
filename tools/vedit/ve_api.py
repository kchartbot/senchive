"""화면(HTML)이 부르는 기능 모음. 파일 선택창만 pywebview 쪽(ve_gui)에서 덧씌우고, 나머지는 여기서 처리한다."""
import hashlib, json, os, platform, subprocess, sys, threading
from pathlib import Path
import ve_core as C

VIDEO_EXT = "*.mp4;*.mov;*.mkv;*.avi;*.webm;*.m4v;*.wmv;*.flv;*.ts;*.mts;*.gif"
FONT_EXT = (".ttf", ".otf", ".ttc")


def data_dir():
    base = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    d = Path(base) / "data"
    try:
        d.mkdir(exist_ok=True); (d / ".w").write_text("1")
    except Exception:
        d = Path.home() / ".vedit"; d.mkdir(exist_ok=True)
    (d / "proxy").mkdir(exist_ok=True)
    return d


class Api:
    def __init__(self):
        self._dir = data_dir(); self._media = {}; self._exp = C.Exporter(); self._lock = threading.Lock()

    # ---- 겹쳐쓸 것들 (창 / 시험용 서버가 각자 구현)
    def dialog_open(self, title, exts, multiple): raise NotImplementedError
    def dialog_save(self, title, name, ext): raise NotImplementedError
    def url_for(self, mid, path): return Path(path).resolve().as_uri()

    # ---- 영상 불러오기
    def _id(self, path): return "m" + hashlib.md5(os.path.abspath(path).encode("utf-8")).hexdigest()[:8]

    def _register(self, path):
        mid = self._id(path)
        with self._lock:
            if mid in self._media: return self._media[mid]
        info = C.probe(path); info["id"] = mid
        px = self._dir / "proxy" / (mid + ".mp4")
        if C.needs_proxy(info):
            info["proxy"] = str(px); info["ready"] = px.exists() and px.stat().st_size > 0
            if not info["ready"]:
                def job():
                    try: C.make_proxy(info, str(px)); info["ready"] = True
                    except Exception as e: info["err"] = str(e); info["ready"] = True; info["proxy"] = None
                threading.Thread(target=job, daemon=True).start()
        else: info["proxy"] = None; info["ready"] = True
        with self._lock: self._media[mid] = info
        return info

    def _view(self, m):
        play = m["proxy"] if m.get("proxy") and m["ready"] else m["path"]
        return dict(id=m["id"], path=m["path"], name=m["name"], dur=m["dur"], w=m["w"], h=m["h"], fps=m["fps"], audio=m["audio"], ready=m["ready"],
                    url=self.url_for(m["id"], play) if m["ready"] else "")

    def open_files(self):
        paths = self.dialog_open("영상 선택", ("영상 파일 (%s)" % VIDEO_EXT, "모든 파일 (*.*)"), True)
        out = []
        for p in paths or []:
            try: out.append(self._view(self._register(p)))
            except Exception as e: out.append(dict(error=str(e), name=os.path.basename(p)))
        bad = [o for o in out if "error" in o]
        if bad and len(bad) == len(out): raise RuntimeError(bad[0]["error"])
        return [o for o in out if "error" not in o]

    def media_ready(self, ids):
        r = {}
        for i in ids:
            m = self._media.get(i)
            if m: r[i] = dict(ready=m["ready"], url=self._view(m)["url"])
        return r

    def reopen_media(self, items):
        r = {}
        for it in items:
            try:
                if not os.path.isfile(it["path"]): r[it["id"]] = dict(ok=False); continue
                m = self._register(it["path"]); v = self._view(m)
                if m["id"] != it["id"]:  # 프로젝트가 쓰던 id 로 되돌려 연결한다
                    self._media[it["id"]] = m
                    v["url"] = self.url_for(it["id"], m["proxy"] if m.get("proxy") and m["ready"] else m["path"]) if m["ready"] else ""
                r[it["id"]] = dict(ok=True, url=v["url"], ready=m["ready"], dur=m["dur"], w=m["w"], h=m["h"], audio=m["audio"])
            except Exception: r[it["id"]] = dict(ok=False)
        return r

    def thumbs(self, mid, n):
        """타임라인 필름용 작은 그림 n장 (JPEG, data URL). 브라우저가 파일 영상의 픽셀을 읽지 못해서 여기서 만든다."""
        import base64, tempfile
        from concurrent.futures import ThreadPoolExecutor
        m = self._media.get(mid)
        if not m: return []
        src = m["proxy"] if m.get("proxy") and m["ready"] and os.path.exists(m["proxy"]) else m["path"]
        n = max(1, min(60, int(n))); h = 64; w = max(2, int(round(h * m["w"] / max(1, m["h"]))) // 2 * 2)
        tmp = tempfile.mkdtemp(prefix="vt_")
        def one(i):
            t = (i + .5) / n * m["dur"]; out = os.path.join(tmp, "%d.jpg" % i)
            C.run([C.which("ffmpeg"), "-y", "-v", "error", "-ss", "%.3f" % t, "-i", src, "-frames:v", "1", "-vf", "scale=%d:%d" % (w, h), "-q:v", "6", out])
            try: return dict(t=t, u="data:image/jpeg;base64," + base64.b64encode(open(out, "rb").read()).decode(), w=w)
            except Exception: return None
        with ThreadPoolExecutor(4) as ex: res = [r for r in ex.map(one, range(n)) if r]
        import shutil; shutil.rmtree(tmp, ignore_errors=True)
        return res

    # ---- 글꼴
    def fonts(self):
        cache = self._dir / "fonts.json"
        dirs = []
        if os.name == "nt":
            dirs = [Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts", Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Windows/Fonts"]
        elif platform.system() == "Darwin": dirs = [Path("/System/Library/Fonts"), Path("/Library/Fonts"), Path.home() / "Library/Fonts"]
        else: dirs = [Path("/usr/share/fonts"), Path.home() / ".fonts"]
        files = []
        for d in dirs:
            if d.is_dir(): files += [p for p in d.rglob("*") if p.suffix.lower() in FONT_EXT]
        sig = "%d:%d" % (len(files), sum(int(p.stat().st_mtime) for p in files[:400]))
        try:
            c = json.loads(cache.read_text(encoding="utf-8"))
            if c.get("sig") == sig: return c["fonts"]
        except Exception: pass
        from PIL import ImageFont
        out = {}
        for p in files:
            try:
                fam, sty = ImageFont.truetype(str(p), 12).getname()
            except Exception: continue
            if sty.lower() not in ("regular", "book", "normal", "medium", "standard") or fam in out: continue
            out[fam] = str(p)
        ko = ("malgun", "nanum", "noto sans cjk", "noto sans kr", "gulim", "batang", "gothic", "pretendard", "gmarket", "나눔", "맑은", "굴림", "바탕", "고딕", "카페", "여기어때", "배달")
        fl = sorted(out.items(), key=lambda kv: (not any(k in kv[0].lower() for k in ko), kv[0].lower()))
        fonts = [dict(name=n, path=p) for n, p in fl[:400]]
        try: cache.write_text(json.dumps(dict(sig=sig, fonts=fonts), ensure_ascii=False), encoding="utf-8")
        except Exception: pass
        return fonts

    def pick_font(self):
        r = self.dialog_open("글꼴 파일 선택", ("글꼴 (*.ttf;*.otf;*.ttc)",), False)
        if not r: return None
        from PIL import ImageFont
        p = r[0]
        try: fam = ImageFont.truetype(p, 12).getname()[0]
        except Exception: fam = Path(p).stem
        return dict(name=fam, path=p, url=Path(p).resolve().as_uri())

    # ---- 프로젝트 / 자동 저장
    def autosave(self, proj):
        try: (self._dir / "autosave.json").write_text(json.dumps(proj, ensure_ascii=False), encoding="utf-8")
        except Exception: pass
        return True

    def has_autosave(self):
        p = self._dir / "autosave.json"
        try: return p.exists() and bool(json.loads(p.read_text(encoding="utf-8")).get("clips"))
        except Exception: return False

    def load_autosave(self):
        try: return json.loads((self._dir / "autosave.json").read_text(encoding="utf-8"))
        except Exception: return None

    def save_project(self, proj):
        p = self.dialog_save("프로젝트 저장", "내 편집", ".vproj")
        if not p: return None
        if not p.lower().endswith(".vproj"): p += ".vproj"
        Path(p).write_text(json.dumps(proj, ensure_ascii=False, indent=1), encoding="utf-8"); return p

    def open_project(self):
        r = self.dialog_open("프로젝트 열기", ("프로젝트 (*.vproj)",), False)
        return json.loads(Path(r[0]).read_text(encoding="utf-8")) if r else None

    # ---- 내보내기
    def pick_out(self, fmt, base):
        ext = {"mp4": ".mp4", "gif": ".gif", "webp": ".webp"}[fmt]
        p = self.dialog_save("저장 위치", base, ext)
        if p and not p.lower().endswith(ext): p += ext
        return p

    def export(self, proj, opts):
        try:
            for mid, m in proj["media"].items():  # 경로는 항상 원본 파일을 쓴다
                if mid in self._media: m["path"] = self._media[mid]["path"]
            self._exp.start(proj, opts); return dict(ok=True)
        except Exception as e: return dict(error=str(e))

    def export_status(self): return self._exp.st
    def export_cancel(self): self._exp.stop(); return True

    def reveal(self, path):
        try:
            if os.name == "nt": subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            elif platform.system() == "Darwin": subprocess.Popen(["open", "-R", path])
            else: subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except Exception: pass
        return True
