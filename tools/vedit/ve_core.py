"""영상 편집기 코어: 프로젝트(JSON) -> ffmpeg 한 번 실행. 화면(UI)과 무관하게 단독으로 시험할 수 있다.

프로젝트 모양(모든 시간은 초, 위치/크기는 0~1 비율):
{ "canvas": {"w":1280,"h":720,"fit":"fit|fill"}, "fps":30,
  "media": {"m1": {"path":..., "dur":..., "w":..., "h":..., "audio":true}},
  "clips": [{"id","mid","in","out","speed","vol","mute","crop":{"l","t","r","b"},"rot":0|90|180|270,"fh","fv","fi","fo"}],
  "texts": [{"id","text","start","end","font","size","color","stroke","strokeW","bold","italic","shadow","rot","x","y","spacing"}],
  "mosaics": [{"id","x","y","w","h","start","end","strength"}] }
"""
import json, os, re, shutil, subprocess, sys, tempfile, threading, time
from pathlib import Path

NOWIN = 0x08000000 if os.name == "nt" else 0


def which(name):
    for d in [os.environ.get("VE_BIN", ""), os.path.dirname(os.path.abspath(sys.executable)), getattr(sys, "_MEIPASS", "")]:
        if d:
            for ext in ("", ".exe"):
                p = os.path.join(d, name + ext)
                if os.path.isfile(p): return p
    return shutil.which(name) or name


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN, **kw)


def probe(path):
    r = run([which("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    if r.returncode: raise RuntimeError("영상을 읽지 못했습니다: " + (r.stderr or "")[-300:])
    j = json.loads(r.stdout or "{}")
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in j.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not v: raise RuntimeError("영상 스트림이 없는 파일입니다.")
    w, h = int(v.get("width", 0)), int(v.get("height", 0))
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd: rot = int(sd["rotation"])
    rot = int((v.get("tags") or {}).get("rotate", rot) or rot)
    if abs(rot) % 180 == 90: w, h = h, w
    try:
        n, d = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1").split("/")
        fps = float(n) / float(d) if float(d) else 30.0
    except Exception: fps = 30.0
    dur = float(j.get("format", {}).get("duration") or v.get("duration") or 0)
    return dict(path=path, name=os.path.basename(path), dur=dur, w=w, h=h, fps=round(fps, 3) if fps > 0 else 30.0, audio=bool(a),
                codec=v.get("codec_name", ""), pix=v.get("pix_fmt", ""))


def needs_proxy(m):
    return not (m["codec"] == "h264" and m["pix"] in ("yuv420p", "yuvj420p") and m["h"] <= 1080 and m["path"].lower().endswith((".mp4", ".m4v", ".mov")))


def make_proxy(m, out):
    """미리보기용으로 가볍고 탐색이 빠른 파일을 만든다(원본은 건드리지 않는다)."""
    cmd = [which("ffmpeg"), "-y", "-v", "error", "-i", m["path"], "-vf", "scale=-2:min(540\\,ih),format=yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
           "-crf", "27", "-g", "12", "-keyint_min", "12"]
    cmd += ["-c:a", "aac", "-b:a", "96k", "-ac", "2"] if m["audio"] else ["-an"]
    r = run(cmd + ["-movflags", "+faststart", out])
    if r.returncode: raise RuntimeError(r.stderr[-300:])


# ---------------------------------------------------------------- 시간 계산
def clip_dur(c):
    return max(0.04, (float(c["out"]) - float(c["in"])) / max(0.05, float(c.get("speed", 1) or 1)))


def total_dur(p):
    return sum(clip_dur(c) for c in p["clips"])


# ---------------------------------------------------------------- 문구 -> PNG (글꼴/테두리/그림자/기울임/회전 모두 이 한 곳에서)
def hex_rgb(s, d=(255, 255, 255)):
    s = (s or "").lstrip("#")
    if len(s) == 3: s = "".join(ch * 2 for ch in s)
    try: return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except Exception: return d


def render_text(t, H, out):
    from PIL import Image, ImageDraw, ImageFont
    px = max(6, int(round(float(t.get("size", 8)) / 100 * H)))
    try: font = ImageFont.truetype(t.get("font") or "", px)
    except Exception:
        font = None
        for f in ("malgun.ttf", "NotoSansCJK-Regular.ttc", "DejaVuSans.ttf", "arial.ttf"):
            try: font = ImageFont.truetype(f, px); break
            except Exception: pass
        font = font or ImageFont.load_default()
    text = t.get("text") or " "
    sw = int(round(float(t.get("strokeW", 0)) / 100 * px)) + (max(1, px // 28) if t.get("bold") else 0)
    sp = float(t.get("spacing", 0)) / 100 * px
    lines = text.split("\n")
    dm = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    asc, desc = font.getmetrics()
    lh = int((asc + desc) * 1.15)

    def width(line):
        return dm.textlength(line, font=font) + sp * max(0, len(line) - 1) if sp else dm.textlength(line, font=font)

    wmax = max(width(l) for l in lines)
    pad = sw + int(px * .5) + 4
    W_, H_ = int(wmax) + pad * 2, lh * len(lines) + pad * 2
    img = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))
    fill, stroke = hex_rgb(t.get("color"), (255, 255, 255)), hex_rgb(t.get("stroke"), (0, 0, 0))

    def draw_layer(layer, dx, dy, color, strk, swid):
        d = ImageDraw.Draw(layer)
        for i, line in enumerate(lines):
            x = pad + (wmax - width(line)) / 2 + dx; y = pad + i * lh + dy
            if sp:
                for ch in line:
                    d.text((x, y), ch, font=font, fill=color + (255,), stroke_width=swid, stroke_fill=strk + (255,)); x += dm.textlength(ch, font=font) + sp
            else:
                d.text((x, y), line, font=font, fill=color + (255,), stroke_width=swid, stroke_fill=strk + (255,))

    if t.get("shadow"):
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0)); off = max(2, px // 14)
        draw_layer(sh, off, off, (0, 0, 0), (0, 0, 0), sw); img.alpha_composite(sh)
    draw_layer(img, 0, 0, fill, stroke, sw)
    if t.get("italic"):
        k = .25; img = img.transform((img.width + int(img.height * k), img.height), Image.AFFINE, (1, k, -img.height * k, 0, 1, 0), Image.BICUBIC)
    if float(t.get("rot", 0)): img = img.rotate(-float(t["rot"]), expand=True, resample=Image.BICUBIC)
    img.save(out)
    return img.size


# ---------------------------------------------------------------- 필터 그래프
def atempo_chain(sp):
    f = []
    while sp > 2.0: f.append("atempo=2.0"); sp /= 2.0
    while sp < 0.5: f.append("atempo=0.5"); sp /= 0.5
    f.append("atempo=%.5f" % sp)
    return ",".join(f)


def build(p, opts, workdir):
    """(ffmpeg 인자 목록, 전체 길이) 를 돌려준다. opts: fmt mp4|gif|webp, w(출력 가로), fps, crf, audio(bool), out"""
    cv = p["canvas"]; W, H = int(cv["w"]) // 2 * 2, int(cv["h"]) // 2 * 2
    fit = cv.get("fit", "fit"); fps = int(opts.get("fps") or p.get("fps") or 30)
    clips = p["clips"]
    if not clips: raise RuntimeError("타임라인에 영상이 없습니다.")
    cmd = [which("ffmpeg"), "-y", "-v", "error", "-nostats", "-progress", "pipe:1"]
    g = []; ins = 0; labels = []; want_audio = opts.get("fmt", "mp4") == "mp4" and opts.get("audio", True)
    for i, c in enumerate(clips):
        m = p["media"][c["mid"]]; cmd += ["-i", m["path"]]; ins += 1
        sp = max(0.05, float(c.get("speed", 1) or 1)); ci, co = float(c["in"]), float(c["out"]); d = clip_dur(c)
        cr = c.get("crop") or {}; l, t_, r, b = (float(cr.get(k, 0) or 0) for k in ("l", "t", "r", "b"))
        f = [f"trim=start={ci:.4f}:end={co:.4f}", "setpts=PTS-STARTPTS"]
        if abs(sp - 1) > 1e-6: f.append(f"setpts=PTS/{sp:.5f}")
        if l or t_ or r or b: f.append(f"crop=iw*{max(.02, 1 - l - r):.5f}:ih*{max(.02, 1 - t_ - b):.5f}:iw*{l:.5f}:ih*{t_:.5f}")
        rot = int(c.get("rot", 0) or 0) % 360
        f += {90: ["transpose=1"], 180: ["hflip", "vflip"], 270: ["transpose=2"]}.get(rot, [])
        if c.get("fh"): f.append("hflip")
        if c.get("fv"): f.append("vflip")
        if fit == "fill": f += [f"scale={W}:{H}:force_original_aspect_ratio=increase", f"crop={W}:{H}"]
        else: f += [f"scale={W}:{H}:force_original_aspect_ratio=decrease", f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black"]
        f += ["setsar=1", f"fps={fps}", "format=yuv420p"]
        fi, fo = float(c.get("fi", 0) or 0), float(c.get("fo", 0) or 0)
        if fi > 0: f.append(f"fade=t=in:st=0:d={min(fi, d):.3f}")
        if fo > 0: f.append(f"fade=t=out:st={max(0, d - fo):.3f}:d={min(fo, d):.3f}")
        g.append(f"[{i}:v]" + ",".join(f) + f"[v{i}]")
        if want_audio:
            if m.get("audio") and not c.get("mute"):
                a = [f"atrim=start={ci:.4f}:end={co:.4f}", "asetpts=PTS-STARTPTS"]
                if abs(sp - 1) > 1e-6: a.append(atempo_chain(sp))
                vol = float(c.get("vol", 1) if c.get("vol") is not None else 1)
                if abs(vol - 1) > 1e-6: a.append(f"volume={vol:.3f}")
                if fi > 0: a.append(f"afade=t=in:st=0:d={min(fi, d):.3f}")
                if fo > 0: a.append(f"afade=t=out:st={max(0, d - fo):.3f}:d={min(fo, d):.3f}")
                a += ["aresample=48000", "aformat=sample_fmts=fltp:channel_layouts=stereo", f"atrim=end={d:.4f}", "asetpts=PTS-STARTPTS"]
                g.append(f"[{i}:a]" + ",".join(a) + f"[a{i}]")
            else:
                g.append(f"anullsrc=r=48000:cl=stereo,atrim=end={d:.4f},asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp[a{i}]")
            labels.append(f"[v{i}][a{i}]")
        else: labels.append(f"[v{i}]")
    n = len(clips)
    g.append("".join(labels) + f"concat=n={n}:v=1:a={1 if want_audio else 0}" + ("[v][a]" if want_audio else "[v]"))
    cur = "v"
    for k, m in enumerate(p.get("mosaics", [])):
        x, y, w, h = (float(m[q]) for q in "xywh"); x, y = max(0, x), max(0, y)
        px_, py_ = int(x * W), int(y * H); pw, ph = max(2, min(W - px_, int(w * W))), max(2, min(H - py_, int(h * H)))
        blk = max(2, int(round(float(m.get("strength", 12)) * H / 1080)))
        en = f":enable='between(t,{float(m['start']):.3f},{float(m['end']):.3f})'"
        g.append(f"[{cur}]split=2[ma{k}][mb{k}]")
        g.append(f"[mb{k}]crop={pw}:{ph}:{px_}:{py_},scale={max(1, pw // blk)}:{max(1, ph // blk)}:flags=area,scale={pw}:{ph}:flags=neighbor[mm{k}]")
        g.append(f"[ma{k}][mm{k}]overlay={px_}:{py_}{en}[mo{k}]"); cur = f"mo{k}"
    for k, t in enumerate(p.get("texts", [])):
        if not (t.get("text") or "").strip(): continue
        png = os.path.join(workdir, f"t{k}.png"); tw, th = render_text(t, H, png)
        cmd += ["-i", png]; idx = ins; ins += 1
        cx, cy = float(t.get("x", .5)) * W, float(t.get("y", .85)) * H
        en = f":enable='between(t,{float(t['start']):.3f},{float(t['end']):.3f})'"
        g.append(f"[{cur}][{idx}:v]overlay={int(cx - tw / 2)}:{int(cy - th / 2)}:eof_action=repeat{en}[to{k}]"); cur = f"to{k}"
    fmt = opts.get("fmt", "mp4"); ow = int(opts.get("w") or 0)
    scale = f"scale={ow // 2 * 2}:-2:flags=lanczos," if ow and ow != W else ""
    if fmt == "gif":
        g.append(f"[{cur}]{scale}fps={fps},split[s0][s1];[s0]palettegen=max_colors=256:stats_mode={'single' if opts.get('gifq') == 'best' else 'diff'}[pp];"
                 f"[s1][pp]paletteuse=dither=sierra2_4a" + (":new=1" if opts.get('gifq') == 'best' else "") + "[fin]")
    elif fmt == "webp":
        g.append(f"[{cur}]{scale}fps={fps},format=yuva420p[fin]")
    else:
        g.append(f"[{cur}]{scale}format=yuv420p[fin]" if scale else f"[{cur}]null[fin]")
    gs = os.path.join(workdir, "graph.txt"); Path(gs).write_text(";\n".join(g), encoding="utf-8")
    cmd += ["-filter_complex_script", gs, "-map", "[fin]"]
    if fmt == "mp4":
        if want_audio: cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
        cmd += ["-c:v", "libx264", "-preset", opts.get("preset", "veryfast"), "-crf", str(int(opts.get("crf", 20))), "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    elif fmt == "webp":
        cmd += ["-c:v", "libwebp", "-loop", "0", "-q:v", str(int(opts.get("q", 80))), "-compression_level", "4", "-an"]
    else: cmd += ["-loop", "0"]
    cmd.append(opts["out"])
    return cmd, total_dur(p)


class Exporter:
    def __init__(self): self.st = dict(state="idle", pct=0, msg="", out="", eta=0); self.proc = None; self.cancel = False

    def start(self, p, opts):
        if self.st["state"] == "run": raise RuntimeError("이미 내보내는 중입니다.")
        self.cancel = False; self.st = dict(state="run", pct=0, msg="준비 중…", out=opts["out"], eta=0)
        threading.Thread(target=self._run, args=(p, opts), daemon=True).start()

    def _run(self, p, opts):
        wd = tempfile.mkdtemp(prefix="ve_"); t0 = time.time()
        try:
            cmd, total = build(p, opts, wd)
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN)
            err = []; threading.Thread(target=lambda: err.append(self.proc.stderr.read()), daemon=True).start()
            for line in self.proc.stdout:
                if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                    try: sec = int(line.split("=")[1]) / 1e6
                    except Exception: continue
                    pct = max(0, min(99, sec / max(total, .1) * 100)); el = time.time() - t0
                    self.st.update(pct=round(pct, 1), msg="만드는 중…", eta=round(el / pct * (100 - pct)) if pct > 3 else 0)
            self.proc.wait()
            if self.cancel:
                self.st.update(state="cancel", msg="취소했습니다."); Path(opts["out"]).unlink(missing_ok=True)
            elif self.proc.returncode:
                self.st.update(state="error", msg=("".join(err) or "ffmpeg 오류")[-600:])
            else:
                self.st.update(state="done", pct=100, msg="완료", size=os.path.getsize(opts["out"]))
        except Exception as e:
            self.st.update(state="error", msg=str(e))
        finally: shutil.rmtree(wd, ignore_errors=True)

    def stop(self):
        self.cancel = True
        if self.proc and self.proc.poll() is None: self.proc.terminate()
