"""exe 로 묶었을 때의 진입점. 인자 없이 실행하면 화면을 띄우고, 내부적으로 --maker / --ytdlp 로 자기 자신을 다시 호출한다."""
import os, sys
here = getattr(sys, "_MEIPASS", None)
dirs = [os.path.dirname(os.path.abspath(sys.executable))] + ([here] if here else [])
os.environ["PATH"] = os.pathsep.join(dirs + [os.environ.get("PATH", "")])   # exe 옆의 ffmpeg 를 찾게 한다

if len(sys.argv) > 1 and sys.argv[1] == "--ytdlp":
    import yt_dlp
    sys.argv = ["yt-dlp"] + sys.argv[2:]
    yt_dlp.main()
elif len(sys.argv) > 1 and sys.argv[1] == "--maker":
    sys.argv = ["con_maker"] + sys.argv[2:]
    import con_maker
    con_maker.main()
else:
    import con_web
    con_web.main()
