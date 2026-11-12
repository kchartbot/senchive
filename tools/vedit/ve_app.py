"""exe 진입점. exe 폴더 옆의 ffmpeg.exe / ffprobe.exe 를 찾도록 PATH 를 잡고 창을 연다."""
import os, sys
here = getattr(sys, "_MEIPASS", None)
dirs = [os.path.dirname(os.path.abspath(sys.executable))] + ([here] if here else [])
os.environ["PATH"] = os.pathsep.join(dirs + [os.environ.get("PATH", "")])
import ve_gui
ve_gui.main()
