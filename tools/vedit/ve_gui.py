"""영상 편집기 창(pywebview). 브라우저/서버 없이 내 창 하나로 열린다."""
import os, sys
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import ve_api


class GuiApi(ve_api.Api):
    def _dlg(self):
        import webview
        return webview, webview.windows[0]

    def dialog_open(self, title, exts, multiple):
        webview, w = self._dlg()
        kind = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
        r = w.create_file_dialog(kind, allow_multiple=multiple, file_types=tuple(exts))
        return list(r) if r else []

    def dialog_save(self, title, name, ext):
        webview, w = self._dlg()
        kind = getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG
        r = w.create_file_dialog(kind, save_filename=name + ext, file_types=("%s (*%s)" % (ext[1:].upper(), ext),))
        if not r: return None
        return r if isinstance(r, str) else r[0]


def main():
    if os.name == "nt" and getattr(sys, "frozen", False):
        try:
            import ctypes
            h = ctypes.windll.kernel32.GetConsoleWindow()
            if h: ctypes.windll.user32.ShowWindow(h, 0)
        except Exception: pass
    import webview
    api = GuiApi()
    webview.create_window("영상 편집기", url=__import__("pathlib").Path(HERE, "ve_ui.html").resolve().as_uri(), js_api=api, width=1480, height=900, min_size=(1100, 680))
    webview.start()


if __name__ == "__main__":
    main()
