"""
启动脚本 - 知识库搜索服务
用法：python run.py
"""

import sys
import os

# 确保能找到 app 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 编码处理：只在输出被重定向时（例如 `start /b pythonw run.py > logs\knowseek.log`）
# 强制 UTF-8，保证日志文件在任何语言的 Windows 上都是 UTF-8，而不会被系统
# 代码页写成 GBK / CP1252 导致编辑器打开乱码。
# 前台运行时保留系统编码，避免控制台里的中文反而乱码。
# pythonw 下 stdout 可能为 None，需逐个判空。
for _stream in (sys.stdout, sys.stderr):
    if _stream is None:
        continue
    try:
        if not _stream.isatty():
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app import indexer, server

if __name__ == "__main__":
    print("=" * 50)
    print("  知寻 KnowSeek - 本地文档全文检索")
    print("  技术栈：SQLite FTS5 + jieba + Flask")
    print("=" * 50)
    
    # 初始化数据库
    indexer.init_db()
    print("[OK] 数据库初始化完成")
    
    # 启动服务
    print("\n[启动] 服务启动中...")
    print(f"[启动] 访问地址：http://127.0.0.1:9876")
    print("[启动] 按 Ctrl+C 停止\n")
    
    server.start_app()