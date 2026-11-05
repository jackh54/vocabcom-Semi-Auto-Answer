"""`vocabbot --self-test [result-file]`: check a packaged build can load everything it needs,
without opening a window. Used by CI; the windowed Windows build has no console, so the result
goes to a file when one is given."""
from __future__ import annotations

import sys
from pathlib import Path


def run(args: list[str]) -> int:
    try:
        import openai  # noqa: F401
        import rich  # noqa: F401
        import selenium.webdriver  # noqa: F401
        import undetected_chromedriver  # noqa: F401
        import webview  # noqa: F401

        from . import __version__, cli, gui  # noqa: F401
        from .session import _ACCOUNT_NAME_JS  # noqa: F401

        # Load this OS's window backend (WebKit via pyobjc / WebView2 via pythonnet) without
        # opening a window, so a build missing those pieces fails here, not on a user's machine.
        if sys.platform == "darwin":
            import webview.platforms.cocoa  # noqa: F401
        elif sys.platform == "win32":
            import webview.platforms.winforms  # noqa: F401
        if not gui.UI_FILE.is_file():
            raise FileNotFoundError(f"UI file missing: {gui.UI_FILE}")
        message, code = f"ok {__version__}", 0
    except Exception as e:  # report anything, this is a diagnostic
        message, code = f"fail {type(e).__name__}: {e}", 1
    if args:
        Path(args[0]).write_text(message + "\n", encoding="utf-8")
    elif sys.stdout:
        print(message)
    return code
