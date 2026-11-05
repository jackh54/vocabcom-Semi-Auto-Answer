# PyInstaller spec for the vocabbot desktop app.
#   pyinstaller packaging/vocabbot.spec
# macOS: dist/vocabbot.app (a normal app bundle).  Windows: dist/vocabbot.exe (one file, no console).
# Both open the desktop window; build on each OS/architecture you want to ship (CI does this).
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from vocabbot import __version__  # noqa: E402

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "vocabbot" / "ui"), "vocabbot/ui")],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="vocabbot",
        console=False,
        icon=str(ROOT / "packaging" / "icon.icns"),
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="vocabbot")
    app = BUNDLE(
        coll,
        name="vocabbot.app",
        icon=str(ROOT / "packaging" / "icon.icns"),
        bundle_identifier="com.pandascript.vocabbot",
        version=__version__,
        info_plist={
            "CFBundleDisplayName": "vocabbot",
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            # Keep running at full speed while the window is hidden behind the Chrome windows.
            "NSAppSleepDisabled": True,
        },
    )
else:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="vocabbot",
        console=False,
        upx=False,
        icon=str(ROOT / "packaging" / "icon.ico"),
    )
