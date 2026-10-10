"""
启动脚本 - 知识库搜索服务
用法：python run.py
"""

import sys
import os

# 确保能找到 app 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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