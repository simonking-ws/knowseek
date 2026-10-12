"""
启动脚本 - 知识库搜索服务
用法：python run.py
"""

import argparse
import logging
import os
import sys
import threading
import webbrowser

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
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
    force=True,
)

from app import indexer, server


def _open_browser(url):
    try:
        webbrowser.open(url)
    except Exception:
        logging.exception("打开浏览器失败")


def main():
    parser = argparse.ArgumentParser(description="知寻 KnowSeek 本地文档全文检索")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    args = parser.parse_args()

    print("=" * 50)
    print("  知寻 KnowSeek - 本地文档全文检索")
    print("  技术栈：SQLite FTS5 + jieba + Flask")
    print("=" * 50)

    indexer.init_db()
    print("[OK] 数据库初始化完成")
    print(f"[数据] {runtime.DATA_DIR}")
    print(f"[日志] {LOG_PATH}")

    port = int(server.config.get("port", 9876))
    url = f"http://127.0.0.1:{port}"
    print("\n[启动] 服务启动中...")
    print(f"[启动] 访问地址：{url}")
    print("[启动] 按 Ctrl+C 停止\n")

    if not args.no_browser:
        timer = threading.Timer(1.2, _open_browser, args=(url,))
        timer.daemon = True
        timer.start()

    server.start_app()


if __name__ == "__main__":
    main()
