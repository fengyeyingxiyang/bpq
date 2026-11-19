"""Entry point for the standalone binary (and `python run.py`)."""
import os
import socket
import sys


def _lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main() -> None:
    import uvicorn

    from app.main import app, llm

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    print("变频器故障查询已启动")
    print(f"  手机/电脑浏览器访问： http://{_lan_ip()}:{port}")
    print(f"  大模型： {llm.provider if llm.enabled else '未配置（只显示手册条目）'}")
    print("  关闭此窗口即停止服务\n")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # keep the console open on Windows so the error is readable
        print(f"\n启动失败：{exc}")
        if sys.platform == "win32":
            input("按回车键退出…")
        raise
