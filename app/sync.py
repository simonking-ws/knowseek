"""
同步器 - 扫描目录，新增/更新/删除文档索引
增量策略：文件 MD5 hash 变了才重新解析
"""

import os
import time
from . import indexer
from .parser import parse_file, compute_file_hash

SUPPORTED_EXT = {".docx", ".doc", ".txt", ".md", ".pdf", ".xlsx", ".xls"}
UPLOAD_PREFIX = "upload://"   # 上传件虚拟路径，与 server.py 保持一致


def scan_and_index(directories, extensions=None, prune=True, progress_cb=None, result_cb=None):
    """
    扫描目录，解析并索引所有支持的文档
    prune=True  : 全量同步，本次未扫描到的文档视为已删除并移除索引
    prune=False : 增量索引（仅索引指定目录），不清理其它来源的文档
    progress_cb : 可选回调 progress_cb(done, total, current_file)，供前端进度条轮询；
                  返回 False 表示「请求终止」，立即停止并返回已完成的计数
    result_cb   : 可选回调 result_cb({"path","status","detail"})，每处理完一个文件回调一次，
                  status ∈ added / updated / skipped / error，供前端逐条展示结果
    返回 (added, updated, skipped, removed, errors)
    """
    exts = set(extensions or list(SUPPORTED_EXT))
    added = 0
    updated = 0
    skipped = 0
    errors = []
    indexed_paths = set()
    pending = []

    # 先收集全部待处理文件，这样进度才有稳定的总数
    for dir_path in directories:
        # 单个文件：直接作为一个待处理项
        if os.path.isfile(dir_path):
            if os.path.splitext(dir_path)[1].lower() in exts:
                fpath = os.path.abspath(dir_path)
                indexed_paths.add(fpath)
                pending.append(fpath)
            else:
                errors.append(f"不支持的文件格式: {dir_path}")
            continue

        if not os.path.isdir(dir_path):
            errors.append(f"路径不存在: {dir_path}")
            continue

        for root, dirs, files in os.walk(dir_path):
            # 跳过隐藏目录
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in exts:
                    continue
                fpath = os.path.abspath(os.path.join(root, fname))
                indexed_paths.add(fpath)
                pending.append(fpath)

    total = len(pending)
    if progress_cb and progress_cb(0, total, "") is False:
        return added, updated, skipped, 0, errors

    def emit(path, status, detail):
        if not result_cb:
            return
        try:
            result_cb({"path": path, "status": status, "detail": detail})
        except Exception:
            pass                                     # 回调异常不影响索引主流程

    cancelled = False
    for idx, fpath in enumerate(pending, 1):
        if progress_cb and progress_cb(idx - 1, total, fpath) is False:
            cancelled = True
            break
        try:
            file_hash = compute_file_hash(fpath)
            existing = indexer.get_db().execute(
                "SELECT file_hash FROM documents WHERE file_path = ?",
                (fpath,),
            ).fetchone()

            if existing and existing["file_hash"] == file_hash:
                skipped += 1
                emit(fpath, "skipped", "未变更，跳过")
                continue

            chunks = parse_file(fpath)
            if chunks:
                count = indexer.index_chunks(chunks)
                if existing:
                    updated += count
                    emit(fpath, "updated", f"更新 {count} 片段")
                else:
                    added += count
                    emit(fpath, "added", f"新增 {count} 片段")
            else:
                emit(fpath, "skipped", "无可索引内容，跳过")
        except Exception as e:
            errors.append(f"{fpath}: {e}")
            emit(fpath, "error", str(e))

    if progress_cb and not cancelled:
        progress_cb(total, total, "")

    # prune=False 时为增量索引：保留其它目录/上传文件的索引，不做删除清理
    if not prune:
        return added, updated, skipped, 0, errors

    # 检查已删除的文件
    conn = indexer.get_db()
    all_docs = conn.execute("SELECT file_path FROM documents").fetchall()
    conn.close()
    removed = 0
    for doc in all_docs:
        fp = doc["file_path"] or ""
        # 上传件只有索引、磁盘上没有原文件，永远扫不到，不能被判为"已删除"
        if fp.startswith(UPLOAD_PREFIX):
            continue
        if fp not in indexed_paths:
            indexer.remove_doc(fp)
            removed += 1

    return added, updated, skipped, removed, errors