"""
启动脚本 - 知识库搜索服务
用法：python run.py
"""

import argparse
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser

import yaml

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

for _stream in (sys.stdout, sys.stderr):
    try:
        if not _stream.isatty():
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import runtime

runtime.ensure_runtime()

LOG_PATH = os.path.join(runtime.LOG_DIR, "knowseek.log")
_NOWINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def load_port():
    try:
        with open(runtime.CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        return int(config.get("port", 9876))
    except Exception:
        return 9876


def _url(port):
    return f"http://127.0.0.1:{port}"


def _open_browser(url):
    try:
        webbrowser.open(url)
    except Exception:
        pass


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )


def _port_pids(port):
    if os.name != "nt":
        return []
    try:
        output = subprocess.check_output(
            ["netstat", "-ano", "-p", "tcp"],
            text=True,
            errors="ignore",
            creationflags=_NOWINDOW,
        )
    except Exception:
        return []

    pids = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local, remote, state, pid = parts[1], parts[2], parts[3], parts[4]
        if local.rsplit(":", 1)[-1] != str(port):
            continue
        if not (state.upper().startswith("LISTEN") or remote.rsplit(":", 1)[-1] == "0"):
            continue
        try:
            pids.add(int(pid))
        except ValueError:
            pass
    return sorted(pids)


def kill_port(port):
    killed = []
    for pid in _port_pids(port):
        if pid in (0, 4, os.getpid()):
            continue
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_NOWINDOW,
                check=False,
            )
            killed.append(pid)
        except Exception:
            pass

    for _ in range(30):
        if not _port_pids(port):
            break
        time.sleep(0.1)
    return killed


def _port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _wait_for_port(port, timeout=4.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.2)
    return False


def serve(open_browser):
    from app import indexer, server

    _setup_logging()

    print("=" * 50)
    print("  知寻 KnowSeek - 本地文档全文检索")
    print("  技术栈：SQLite FTS5 + jieba + Flask")
    print("=" * 50)

    indexer.init_db()
    print("[OK] 数据库初始化完成")
    print(f"[数据] {runtime.DATA_DIR}")
    print(f"[日志] {LOG_PATH}")

    port = int(server.config.get("port", 9876))
    url = _url(port)
    print("\n[启动] 服务启动中...")
    print(f"[启动] 访问地址：{url}")
    print("[启动] 按 Ctrl+C 停止\n")

    if open_browser:
        timer = threading.Timer(1.2, _open_browser, args=(url,))
        timer.daemon = True
        timer.start()

    server.start_app()


def launch_background(port, open_browser):
    started = time.monotonic()
    killed = kill_port(port)
    if killed:
        print(f"[启动] 已结束占用端口 {port} 的旧实例：{', '.join(map(str, killed))}")

    command = [sys.executable]
    if not runtime.FROZEN:
        command.append(os.path.abspath(__file__))
    command += ["--serve", "--no-browser"]

    kwargs = {
        "cwd": runtime.BASE_DIR,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    subprocess.Popen(command, **kwargs)
    ready = _wait_for_port(port)
    url = _url(port)

    if ready and open_browser:
        _open_browser(url)
        print(f"[启动] 已在浏览器打开：{url}")
    elif ready:
        print(f"[启动] 服务已就绪：{url}")
    else:
        print(f"[错误] 服务未能在端口 {port} 启动，请查看 {LOG_PATH}")
        print("[提示] 可改用 --foreground 查看控制台错误")

    print("[提示] 此窗口将在 5 秒后自动关闭，服务继续在后台运行")

    remaining = 5 - (time.monotonic() - started)
    if remaining > 0:
        time.sleep(remaining)


def main():
    parser = argparse.ArgumentParser(description="知寻 KnowSeek 本地文档全文检索")
    parser.add_argument("--foreground", action="store_true", help="前台运行，保留控制台，Ctrl+C 停止")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    parser.add_argument("--stop", action="store_true", help="停止占用当前端口的旧实例")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    port = load_port()

    if args.stop:
        killed = kill_port(port)
        if killed:
            print(f"已停止旧实例：{', '.join(map(str, killed))}")
        else:
            print(f"端口 {port} 当前没有运行中的实例")
        return

    if args.serve:
        serve(not args.no_browser)
        return

    if args.foreground or os.name != "nt":
        killed = kill_port(port)
        if killed:
            print(f"[启动] 已结束占用端口 {port} 的旧实例：{', '.join(map(str, killed))}")
        serve(not args.no_browser)
        return

    launch_background(port, not args.no_browser)


if __name__ == "__main__":
    main()
