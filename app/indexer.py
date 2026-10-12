"""
索引器 - jieba 分词 + SQLite FTS5 全文索引
核心能力：
  - jieba.cut_for_search 搜索引擎模式分词
  - FTS5 BM25 相关性排序
  - Python 层关键词高亮（不受 UNINDEXED 列限制）
"""

import sqlite3
import os
import re
import json
import html
import jieba

from .runtime import DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "knowseek.db")


def get_db():
    """获取数据库连接（写锁最多等待 30s，避免并发索引时直接报 locked）"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db():
    """初始化数据库表结构"""
    conn = get_db()
    # WAL：索引写入时搜索仍可正常读；不支持 WAL 的文件系统会自动保持原 journal 模式
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError:
        pass
    conn.executescript("""
        -- 文档元数据表
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE NOT NULL,
            file_hash TEXT,
            source_type TEXT DEFAULT 'word',
            title TEXT,
            indexed_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        -- 全文索引虚拟表
        -- 注意：content 也参与索引（不用 UNINDEXED），这样 highlight() 能生效
        -- 但我们用 Python 层高亮更灵活，所以 content 存 UNINDEXED 原文
        -- 新增 content_indexed 列专门用于高亮
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            content_tokenized,
            content UNINDEXED,
            doc_id UNINDEXED,
            file_path UNINDEXED,
            title UNINDEXED,
            section_path UNINDEXED,
            para_index UNINDEXED,
            source_type UNINDEXED,
            tokenize = 'unicode61 remove_diacritics 2'
        );

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.commit()
    conn.close()

    # 知识图谱表（L0 结构图谱）
    from . import kg
    kg.init_tables()


def load_custom_dict(dict_path):
    """加载自定义词典"""
    if os.path.exists(dict_path):
        jieba.load_userdict(dict_path)


def tokenize(text):
    """jieba 搜索引擎模式分词，空格拼接"""
    tokens = jieba.cut_for_search(text)
    return " ".join(t for t in tokens if t.strip())


def get_doc_hash(file_path):
    """读取已索引文件的 MD5；未索引返回 None（连接即用即关）"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT file_hash FROM documents WHERE file_path = ?", (file_path,)
        ).fetchone()
        return row["file_hash"] if row else None
    finally:
        conn.close()


def index_chunks(chunks):
    """将一批 chunk 写入索引"""
    conn = get_db()

    if not chunks:
        conn.close()
        return 0

    file_path = chunks[0]["file_path"]
    file_hash = chunks[0]["file_hash"]
    source_type = chunks[0].get("source_type", "word")
    title = chunks[0].get("title", "")

    row = conn.execute(
        "SELECT id, file_hash FROM documents WHERE file_path = ?", (file_path,)
    ).fetchone()

    if row:
        if row["file_hash"] == file_hash:
            conn.close()
            return 0
        conn.execute("DELETE FROM chunks_fts WHERE doc_id = ?", (row["id"],))
        doc_id = row["id"]
        conn.execute(
            "UPDATE documents SET file_hash = ?, source_type = ?, title = ?, indexed_at = datetime('now', 'localtime') WHERE id = ?",
            (file_hash, source_type, title, doc_id),
        )
    else:
        cur = conn.execute(
            "INSERT INTO documents (file_path, file_hash, source_type, title) VALUES (?, ?, ?, ?)",
            (file_path, file_hash, source_type, title),
        )
        doc_id = cur.lastrowid

    count = 0
    for chunk in chunks:
        tokenized = tokenize(chunk["content"])
        conn.execute(
            "INSERT INTO chunks_fts (content_tokenized, content, doc_id, file_path, "
            "title, section_path, para_index, source_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tokenized,
                chunk["content"],
                doc_id,
                chunk["file_path"],
                chunk.get("title", ""),
                chunk.get("section_path", ""),
                chunk.get("para_index", 0),
                chunk.get("source_type", ""),
            ),
        )
        count += 1

    conn.commit()
    conn.close()

    # 结构图谱：随索引同步更新（失败不影响检索主流程）
    try:
        from . import kg
        kg.extract_file(chunks)
    except Exception:
        pass

    return count


def empty_doc(file_path, file_hash=None):
    """文件解析不到任何文本时：清掉旧片段与图谱，保留文档记录并更新 hash。

    避免文件内容被清空后，旧片段仍能被搜索到。
    """
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM documents WHERE file_path = ?", (file_path,)
        ).fetchone()
        if not row:
            return 0
        conn.execute("DELETE FROM chunks_fts WHERE doc_id = ?", (row["id"],))
        if file_hash:
            conn.execute(
                "UPDATE documents SET file_hash = ?, indexed_at = datetime('now', 'localtime') "
                "WHERE id = ?",
                (file_hash, row["id"]),
            )
        conn.commit()
    finally:
        conn.close()

    # 同步清理该文档在图谱中的节点、提及与关系
    try:
        from . import kg
        kg.remove_file(file_path)
    except Exception:
        pass
    return 1


def remove_doc(file_path):
    """从索引中删除文档"""
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM documents WHERE file_path = ?", (file_path,)
    ).fetchone()
    if row:
        conn.execute("DELETE FROM chunks_fts WHERE doc_id = ?", (row["id"],))
        conn.execute("DELETE FROM documents WHERE id = ?", (row["id"],))
        conn.commit()
    conn.close()

    # 同步清理该文档在图谱中的节点与关系
    if row:
        try:
            from . import kg
            kg.remove_file(file_path)
        except Exception:
            pass


def clear_all():
    """清空全部索引（documents / chunks_fts / meta）+ 图谱。

    只清数据库，绝不删除磁盘上的原文件。返回被清掉的文档数。
    """
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"]
    conn.executescript(
        "DELETE FROM chunks_fts; DELETE FROM documents; DELETE FROM meta;"
    )
    conn.commit()
    try:
        conn.execute("VACUUM")          # 回收 knowseek.db 体积
    except Exception:
        pass
    conn.close()

    try:
        from . import kg
        kg.clear_all()
    except Exception:
        pass
    return {"removed_docs": total}


def get_meta_json(key, default=None):
    """读 meta 表里的 JSON 值（无记录或解析失败返回 default）"""
    conn = get_db()
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    conn.close()
    if not row or row["value"] is None:
        return default
    try:
        return json.loads(row["value"])
    except Exception:
        return default


def set_meta_json(key, value):
    """写 meta 表里的 JSON 值"""
    conn = get_db()
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


def get_doc_dirs(file_only=None):
    """从已索引文档的真实路径反推扫描根目录（去重）。

    - 上传件用的虚拟路径（upload://文件名）没有磁盘目录，直接跳过
    - file_only 里的路径是「单独索引的单文件」：用文件本身当扫描根，
      避免把该文件所在的整个目录都拉进同步范围
    """
    file_only = {os.path.normcase(os.path.abspath(p)) for p in (file_only or [])}

    conn = get_db()
    rows = conn.execute("SELECT file_path FROM documents").fetchall()
    conn.close()

    dirs, seen = [], set()
    for r in rows:
        path = r["file_path"] or ""
        if not path or "://" in path:
            continue
        ap = os.path.abspath(path)
        d = ap if os.path.normcase(ap) in file_only else os.path.dirname(ap)
        key = os.path.normcase(d)
        if key in seen:
            continue
        seen.add(key)
        dirs.append(d)

    # 只保留最外层目录：子目录会被父目录递归覆盖，避免重复扫描
    dirs.sort(key=len)
    roots = []
    for d in dirs:
        nd = os.path.normcase(d)
        if any(nd == os.path.normcase(r) or nd.startswith(os.path.normcase(r) + os.sep)
               for r in roots):
            continue
        roots.append(d)
    return roots


def get_doc_list(page=1, per_page=20, source_type=None):
    """获取文档列表（分页）"""
    conn = get_db()
    offset = (page - 1) * per_page

    where_clause = ""
    params = []
    if source_type:
        where_clause = "WHERE source_type = ?"
        params.append(source_type)

    total = conn.execute(
        f"SELECT COUNT(*) as c FROM documents {where_clause}", params
    ).fetchone()["c"]

    sql = f"""
        SELECT d.id, d.file_path, d.file_hash, d.source_type, d.title, d.indexed_at,
               (SELECT COUNT(*) FROM chunks_fts WHERE doc_id = d.id) as chunk_count
        FROM documents d {where_clause}
        ORDER BY d.indexed_at DESC
        LIMIT ? OFFSET ?
    """
    params.extend([per_page, offset])
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    docs = []
    for r in rows:
        docs.append({
            "id": r["id"],
            "file_path": r["file_path"],
            "source_type": r["source_type"],
            "title": r["title"],
            "indexed_at": r["indexed_at"],
            "chunk_count": r["chunk_count"],
        })
    return docs, total


def get_chunks_by_file(file_path, para_index=None, context=2):
    """
    从数据库取某文件的 chunk 列表（不重新解析文件）
    如果指定 para_index，返回目标 chunk + 前后 context 个 chunk
    返回 (target_chunk, all_relevant_chunks)
    """
    conn = get_db()
    rows = conn.execute(
        "SELECT content, file_path, title, section_path, para_index, source_type "
        "FROM chunks_fts WHERE file_path = ? ORDER BY para_index",
        (file_path,)
    ).fetchall()
    conn.close()

    if not rows:
        return None, []

    chunks = [dict(r) for r in rows]

    if para_index is None:
        return None, chunks

    target = None
    target_idx = 0
    for i, c in enumerate(chunks):
        if c["para_index"] == para_index:
            target = c
            target_idx = i
            break

    if not target:
        return None, chunks[:5]

    start = max(0, target_idx - context)
    end = min(len(chunks), target_idx + context + 1)
    relevant = chunks[start:end]
    return target, relevant


def get_stats():
    """获取索引统计信息"""
    conn = get_db()
    doc_count = conn.execute("SELECT COUNT(*) as c FROM documents").fetchone()["c"]
    chunk_count = conn.execute("SELECT COUNT(*) as c FROM chunks_fts").fetchone()["c"]

    # 按来源统计
    by_source = {}
    rows = conn.execute("SELECT source_type, COUNT(*) as c FROM documents GROUP BY source_type").fetchall()
    for r in rows:
        by_source[r["source_type"] or "unknown"] = r["c"]

    conn.close()
    return {"doc_count": doc_count, "chunk_count": chunk_count, "by_source": by_source}


# ==================== 搜索 ====================

def _build_fts_query(keyword):
    """将用户输入转换为 FTS5 MATCH 表达式"""
    tokens = list(jieba.cut_for_search(keyword))
    parts = []
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        t = t.replace('"', '""')
        parts.append(f'"{t}"')
    if not parts:
        return None
    return " AND ".join(parts)


def _highlight_in_python(content, keyword):
    """
    Python 层关键词高亮：
    对原始 content 做 HTML 转义后，把命中的关键词用 <mark> 包裹
    """
    # 先 HTML 转义
    escaped = html.escape(content)

    # 对每个分词结果做高亮（大小写不敏感）
    tokens = list(jieba.cut_for_search(keyword))
    seen = set()
    for t in tokens:
        t = t.strip()
        if not t or t in seen:
            continue
        seen.add(t)
        # 大小写不敏感替换
        pattern = re.compile(re.escape(t), re.IGNORECASE)
        escaped = pattern.sub(f'<mark>{t}</mark>', escaped)

    return escaped


def search(keyword, source_type=None, page=1, per_page=20):
    """
    全文搜索（带分页）
    返回 (results, total)
    """
    match_expr = _build_fts_query(keyword)
    if not match_expr:
        return [], 0

    conn = get_db()

    # 先查总数
    count_sql = "SELECT COUNT(*) as c FROM chunks_fts WHERE chunks_fts MATCH ?"
    count_params = [match_expr]
    if source_type:
        count_sql += " AND source_type = ?"
        count_params.append(source_type)
    total = conn.execute(count_sql, count_params).fetchone()["c"]

    # 分页查询
    offset = (page - 1) * per_page
    sql = """
        SELECT 
            content,
            file_path,
            title,
            section_path,
            para_index,
            source_type,
            bm25(chunks_fts) as score
        FROM chunks_fts
        WHERE chunks_fts MATCH ?
    """
    params = [match_expr]
    if source_type:
        sql += " AND source_type = ?"
        params.append(source_type)
    sql += " ORDER BY score LIMIT ? OFFSET ?"
    params.extend([per_page, offset])

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    results = []
    for r in rows:
        raw_content = r["content"]
        highlighted = _highlight_in_python(raw_content, keyword)
        results.append({
            "content": raw_content,
            "highlighted": highlighted,
            "file_path": r["file_path"],
            "title": r["title"],
            "section_path": r["section_path"],
            "para_index": r["para_index"],
            "source_type": r["source_type"],
            "score": round(r["score"], 4),
        })
    return results, total