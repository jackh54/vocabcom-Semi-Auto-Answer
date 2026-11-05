"""Desktop window: the HTML UI in vocabbot/ui, shown in the system web view by pywebview
(WebKit on macOS, Edge WebView2 on Windows), driving a Controller."""
from __future__ import annotations

import logging
import os
import platform
import subprocess
import webbrowser
from pathlib import Path

import webview

from .controller import Controller
from .logfile import setup_logging
from .paths import app_home

UI_FILE = Path(__file__).resolve().parent / "ui" / "index.html"
log = logging.getLogger(__name__)


def _reveal(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    system = platform.system()
    if system == "Windows":
        os.startfile(path)  # type: ignore[attr-defined]  # Windows only
    elif system == "Darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class Api:
    """Methods the page calls as window.pywebview.api.<name>(...). Each returns JSON-able data;
    actions return an error message for the user, or None on success."""

    def __init__(self, controller: Controller, home: Path):
        self._ctl = controller
        self._home = home

    def boot(self):
        log.info("Window loaded and connected")
        return {"settings": self._ctl.settings()}

    def poll(self, since=0):
        snap = self._ctl.snapshot(int(since or 0))
        snap["accounts"] = self._ctl.accounts()
        return snap

    def start(self, name):
        return self._ctl.start(str(name).strip())

    def stop(self, name):
        self._ctl.stop(str(name))

    def stop_all(self):
        self._ctl.stop_all()

    def dismiss(self, name):
        self._ctl.dismiss(str(name))

    def forget(self, name):
        return self._ctl.forget_account(str(name))

    def new_account_name(self):
        return self._ctl.next_account_name()

    def set_api_key(self, key):
        return self._ctl.set_api_key(str(key or ""))

    def save_settings(self, model, min_wait, max_wait):
        return self._ctl.save_settings(model, min_wait, max_wait)

    def open_folder(self, which):
        _reveal(self._home / ("logs" if which == "logs" else "data"))

    def open_url(self, url):
        if str(url).startswith("https://"):
            webbrowser.open(str(url))


def _prevent_app_nap():
    """macOS throttles apps whose windows are hidden or covered ("App Nap"). The user mostly
    looks at the Chrome windows, so without this the sessions can stall. Returns a token that
    must stay referenced. The .app also sets NSAppSleepDisabled; this covers running from source."""
    if platform.system() != "Darwin":
        return None
    try:
        from Foundation import NSProcessInfo
        user_initiated_allowing_idle_sleep = 0x00EFFFFF  # NSActivityUserInitiatedAllowingIdleSystemSleep
        return NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
            user_initiated_allowing_idle_sleep, "Answering Vocabulary.com questions")
    except Exception:
        log.warning("Couldn't opt out of App Nap", exc_info=True)
        return None


def run() -> int:
    home = app_home()
    setup_logging(home / "logs" / "vocabbot.log")
    activity = _prevent_app_nap()  # noqa: F841  (held for the app's lifetime)
    controller = Controller(home)
    window = webview.create_window(
        "vocabbot",
        html=UI_FILE.read_text(encoding="utf-8").replace(
            "<head>", '<head><meta name="vocabbot-host" content="desktop">', 1),
        js_api=Api(controller, home),
        width=1180, height=800, min_size=(900, 600),
    )
    # Closing the window ends every session and its Chrome window.
    window.events.closing += lambda: controller.stop_all()
    log.info("Desktop app starting (data folder %s)", home)
    webview.start()
    controller.shutdown()
    return 0
