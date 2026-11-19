"""Assemble the release folder + archive for one platform.

usage: python packaging/make_release.py <platform-name>   (e.g. linux-x64, windows-x64)
Expects the PyInstaller output in dist/. Writes dist/release/fault-assistant-<name>/ and an archive next to it.
"""
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = """变频器故障查询（施耐德）— 单文件版
====================================

1. 把本文件夹整个放到任意位置。
2. 复制 .env.example 为 .env，用记事本/文本编辑器打开，选择大模型并填写 API Key
   （不配置也能用，只显示手册英文原文，不能识别照片）。
3. 启动：
   - Windows：双击 fault-assistant.exe
   - Linux：  chmod +x fault-assistant && ./fault-assistant
4. 窗口里会显示访问地址，手机和电脑在同一局域网内，浏览器打开该地址即可。
   默认端口 8080，可在 .env 里加一行 PORT=9000 修改。

说明
- data 文件夹是故障码库，可直接用文本编辑器增删条目，重启程序后生效。格式见在线仓库 README。
- Windows 首次运行会弹出防火墙提示，请选择“允许访问”（专用网络），否则手机连不上。
- Windows 可能提示“未知发布者”（程序没有代码签名），选择“更多信息 → 仍要运行”。
- 没有密码，请只在厂内局域网使用。
- 长期运行请用 systemd（Linux）或“任务计划程序 / NSSM”（Windows）托管。
"""


def main() -> None:
    name = sys.argv[1]
    exe = next(p for p in (ROOT / "dist").glob("fault-assistant*") if p.is_file())
    out = ROOT / "dist" / "release"
    folder = out / f"fault-assistant-{name}"
    shutil.rmtree(out, ignore_errors=True)
    (folder / "data").mkdir(parents=True)

    shutil.copy2(exe, folder / exe.name)
    for f in (ROOT / "data").glob("*.psv"):
        shutil.copy2(f, folder / "data" / f.name)
    shutil.copy2(ROOT / ".env.example", folder / ".env.example")
    (folder / "使用说明.txt").write_text(README, encoding="utf-8")

    if name.startswith("windows"):
        archive = out / f"fault-assistant-{name}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for p in folder.rglob("*"):
                z.write(p, p.relative_to(out))
    else:
        archive = out / f"fault-assistant-{name}.tar.gz"
        with tarfile.open(archive, "w:gz") as t:
            t.add(folder, arcname=folder.name)  # keeps the executable bit
    print(f"built {archive} ({archive.stat().st_size // 1024} KB)")
    print(f"folder {folder}")


if __name__ == "__main__":
    main()
