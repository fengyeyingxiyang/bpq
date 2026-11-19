# PyInstaller spec: build with `pyinstaller fault-assistant.spec` on the target OS.
from PyInstaller.utils.hooks import collect_submodules

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("anyio")
    + ["python_multipart", "multipart"]
)

a = Analysis(
    ["run.py"],
    pathex=["."],
    datas=[("app/static", "app/static"), ("data", "data")],
    hiddenimports=hidden,
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="fault-assistant",
    console=True,
    upx=False,
)
