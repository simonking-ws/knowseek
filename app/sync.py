"""
同步器 - 扫描目录，新增/更新/删除文档索引
增量策略：文件 MD5 hash 变了才重新解析
"""

import os
import time
from . import indexer
from .parser import parse_file, compute_file_hash

SUPPORTED_EXT = {".docx", ".txt", ".md", ".pdf", ".xlsx", ".xls"}


def scan_and_index(directories, extensions=None):
    """
    扫描目录，解析并索引所有支持的文档
    返回 (added, updated, skipped, removed, errors)
    """
    exts = set(extensions or list(SUPPORTED_EXT))
    added = 0
    updated = 0
    skipped = 0
    errors = []
    indexed_paths = set()

    for dir_path in directories:
        if not os.path.isdir(dir_path):
            errors.append(f"目录不存在: {dir_path}")
            continue

        for root, dirs, files in os.walk(dir_path):
            # 跳过隐藏目录
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in exts:
                    continue

                fpath = os.path.join(root, fname)
                indexed_paths.add(os.path.abspath(fpath))

                try:
                    file_hash = compute_file_hash(fpath)
                    existing = indexer.get_db().execute(
                        "SELECT file_hash FROM documents WHERE file_path = ?",
                        (os.path.abspath(fpath),),
                    ).fetchone()

                    if existing and existing["file_hash"] == file_hash:
                        skipped += 1
                        continue

                    chunks = parse_file(fpath)
                    if chunks:
                        count = indexer.index_chunks(chunks)
                        if existing:
                            updated += count
                        else:
                            added += count
                except Exception as e:
                    errors.append(f"{fpath}: {e}")

    # 检查已删除的文件
    conn = indexer.get_db()
    all_docs = conn.execute("SELECT file_path FROM documents").fetchall()
    conn.close()
    removed = 0
    for doc in all_docs:
        if doc["file_path"] not in indexed_paths:
            indexer.remove_doc(doc["file_path"])
            removed += 1

    return added, updated, skipped, removed, errors