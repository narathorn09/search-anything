# PyInstaller spec for the desktop app (Windows, macOS; Linux for testing).
#
#   python packaging/make_icon.py packaging/build/icons
#   pyinstaller packaging/search-anything.spec --noconfirm
#
# Optional: packaging/build/tesseract/ (tesseract executable + its libraries
# + tessdata/ with eng and tha) is copied into the app; CI fills it in.
# Output: dist/Search Anything/ (folder app) and, on macOS, dist/Search Anything.app

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).parent
BUILD = ROOT / "packaging" / "build"
APP = "Search Anything"
ICON = BUILD / "icons" / ("icon.ico" if sys.platform.startswith("win") else "icon.icns")

datas = [(str(ROOT / "search_anything" / "static"), "search_anything/static")]
datas += collect_data_files("docx") + collect_data_files("pptx") + collect_data_files("openpyxl")
datas += collect_data_files("pypdfium2") + collect_data_files("pypdfium2_raw")
binaries = collect_dynamic_libs("pypdfium2_raw")
tess = BUILD / "tesseract"
if tess.is_dir():
    datas.append((str(tess), "tesseract"))

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("search_anything")
    + ["sa_native", "xlrd", "olefile", "multipart", "python_multipart", "webview"]
)

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "IPython", "matplotlib", "numpy.tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP,
    console=False,  # a windowed app: no terminal window
    icon=str(ICON) if ICON.exists() else None,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name=APP, upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP}.app",
        icon=str(ICON) if ICON.exists() else None,
        bundle_identifier="app.searchanything.desktop",
        info_plist={
            "CFBundleName": APP,
            "CFBundleDisplayName": APP,
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            # Asked once by macOS when the app first opens these folders.
            "NSDocumentsFolderUsageDescription": "ค้นหาไฟล์ในโฟลเดอร์ Documents",
            "NSDesktopFolderUsageDescription": "ค้นหาไฟล์ในโฟลเดอร์ Desktop",
            "NSDownloadsFolderUsageDescription": "ค้นหาไฟล์ในโฟลเดอร์ Downloads",
        },
    )
