"""cx_Freeze build: a 64-bit MSI with everything bundled (Python, Tcl/Tk with
tkdnd, PyAV, Pillow and FFmpeg). The target PC needs nothing pre-installed.

    ..\\..\\.venv\\Scripts\\python setup.py bdist_msi      (or build.ps1)

Output: dist\\KoenektGrecConverter-<version>-win64.msi
"""
import sys
from pathlib import Path

from cx_Freeze import Executable, setup

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "shared"), str(HERE)]

from grec_converter import APP_NAME, COMPANY, VERSION  # noqa: E402

# Never change: Windows uses it to recognise upgrades of this product.
UPGRADE_CODE = "{587BA135-D368-4A8D-82E3-D4FB8212F4E2}"
SHORTCUT_NAME = "Koenekt GREC Converter"
# One icon everywhere: exe, Start menu + desktop shortcuts, Apps & Features.
ICON = ROOT / "brand" / "koenekt-cctv.ico"


def ffmpeg_exe():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def licence_files():
    site = Path(sys.prefix) / "Lib" / "site-packages"
    files = [(str(HERE / "THIRD-PARTY-NOTICES.txt"), "licenses/THIRD-PARTY-NOTICES.txt"),
             (str(Path(sys.base_prefix) / "LICENSE.txt"), "licenses/Python-LICENSE.txt")]
    for pattern, name in (("av-*.dist-info/licenses/*", "PyAV-"),
                          ("imageio_ffmpeg-*.dist-info/LICENSE", "imageio-ffmpeg-"),
                          ("tkinterdnd2-*.dist-info/licenses/LICENSE*", "tkinterdnd2-"),
                          ("pillow-*.dist-info/licenses/LICENSE*", "Pillow-")):
        for f in site.glob(pattern):
            if f.is_file():
                files.append((str(f), f"licenses/{name}{f.name}"))
    return files


build_exe_options = {
    "packages": ["grec_converter", "koenekt_codecs", "av", "tkinterdnd2", "PIL", "tkinter"],
    "includes": ["tkinter.filedialog", "tkinter.messagebox", "tkinter.ttk"],
    # imageio-ffmpeg is only used to locate FFmpeg at build time; the binary
    # itself ships as bin\ffmpeg.exe.
    "excludes": ["imageio_ffmpeg", "numpy", "test", "unittest", "pydoc_data",
                 "pytest", "setuptools", "cx_Freeze"],
    "include_msvcr": True,
    "optimize": 1,
    "include_files": [
        (str(ICON), "brand/koenekt-cctv.ico"),
        (str(ROOT / "brand" / "koenekt-cctv-256.png"), "brand/koenekt-cctv-256.png"),
        (str(ROOT / "brand" / "header_logo.png"), "brand/header_logo.png"),
        (ffmpeg_exe(), "bin/ffmpeg.exe"),
    ] + licence_files(),
}

bdist_msi_options = {
    "upgrade_code": UPGRADE_CODE,
    "add_to_path": False,
    "all_users": True,
    "output_name": f"KoenektGrecConverter-{VERSION}-win64.msi",
    "initial_target_dir": r"[ProgramFiles64Folder]\Koenekt\GREC Converter",
    "install_icon": str(ICON),
    #   (Shortcut, Directory_, Name, Component_, Target, Arguments,
    #    Description, Hotkey, Icon_, IconIndex, ShowCmd, WkDir)
    "data": {
        "Shortcut": [
            ("DesktopShortcut", "DesktopFolder", SHORTCUT_NAME, "TARGETDIR",
             "[TARGETDIR]GrecConverter.exe", None,
             "Convert .grec recordings to MP4 or AVI", None, None, None, None, "TARGETDIR"),
        ],
    },
    "summary_data": {"author": COMPANY, "comments": "Convert .grec recordings to MP4 or AVI"},
}

setup(
    name="KoenektGrecConverter",
    version=VERSION,
    description=APP_NAME,
    author=COMPANY,
    options={"build_exe": build_exe_options, "bdist_msi": bdist_msi_options},
    executables=[
        Executable(
            str(HERE / "main.py"),
            base="gui",
            target_name="GrecConverter.exe",
            icon=str(ICON),
            shortcut_name=SHORTCUT_NAME,
            shortcut_dir="ProgramMenuFolder",
        ),
    ],
)
