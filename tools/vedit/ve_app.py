"""exe 진입점. 어떤 이유로든 시작에 실패하면 창이 안 뜨고 사라지지 않도록 오류를 파일과 메시지 창으로 남긴다."""
import os, sys, traceback, time


def _log_dir():
    base = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    for d in (os.path.join(base, "data"), os.path.expanduser("~")):
        try:
            os.makedirs(d, exist_ok=True)
            return d
        except Exception:
            pass
    return base


def _fail(stage):
    msg = "[%s] %s\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), stage, traceback.format_exc())
    path = os.path.join(_log_dir(), "vedit_error.log")
    try:
        with open(path, "a", encoding="utf-8") as f: f.write(msg)
    except Exception: pass
    try:
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, "영상 편집기를 시작하지 못했습니다.\n\n" + msg[-900:] + "\n(자세한 내용: " + path + ")", "영상 편집기", 0x10)
    except Exception: pass
    print(msg)


here = getattr(sys, "_MEIPASS", None)
dirs = [os.path.dirname(os.path.abspath(sys.executable))] + ([here] if here else [])
os.environ["PATH"] = os.pathsep.join(dirs + [os.environ.get("PATH", "")])
try:
    import ve_gui
except Exception:
    _fail("불러오기"); sys.exit(1)
try:
    ve_gui.main()
except Exception:
    _fail("실행"); sys.exit(1)
