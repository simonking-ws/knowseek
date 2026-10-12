"""
知识图谱模块（L0 结构图谱）

节点：目录(dir) / 文档(file) / 章节(section)
边  ：contains（包含）
定位：kg_mentions 用 file_path + para_index 对齐 chunks_fts，
      所以图谱里点"提及"可以直接复用现有"查看原文"弹窗。

不依赖任何外部服务与大模型，数据落在同一个 SQLite（data/knowseek.db）。
"""

import itertools
import json
import os
import re
from datetime import datetime

import yaml

try:
    import jieba
    import jieba.posseg as pseg
except ImportError:  # 分词不可用时自动退化为纯结构图谱
    jieba = None
    pseg = None

from .indexer import get_db

# 每个实体最多保留的提及条数（控制表体积）
MENTION_LIMIT = 30
VIRTUAL_PREFIX = "upload://"   # 上传件虚拟路径：只留索引，磁盘上没有原文件
# 单个片段参与共现计算的最大实体数（控制边数量）
MAX_ENTITIES_PER_CHUNK = 8

# jieba 词性 -> 实体类型：nr 人名 / nt 机构名 / nz 其他专名
_POS_MAP = {"nr": "person", "nt": "system", "nz": "term"}

_STOP = {
    "的", "了", "是", "在", "和", "与", "及", "为", "对", "从", "到", "等", "中", "上", "下",
    "这", "那", "我", "你", "他", "它", "我们", "你们", "他们", "可以", "需要", "进行", "通过",
    "由于", "因此", "但是", "如果", "因为", "所以", "并且", "或者", "一个", "没有", "什么",
    "相关", "说明", "内容", "情况", "问题", "方式", "方法", "时间", "系统", "数据", "信息",
}

_EN_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "into", "are", "was", "were",
    "can", "not", "all", "use", "used", "using", "pdf", "doc", "docx", "http", "https",
    "com", "www", "txt", "png", "jpg", "get", "set", "new", "name", "type", "data",
}

# 形如 xx系统 / xx平台 / xx模块 的正则抽取
_REGEX_RULES = [
    (re.compile(r"[\u4e00-\u9fa5A-Za-z0-9]{2,20}(?:系统|平台|子系统|模块|服务|引擎|框架|数据库|接口|中心)"), "system"),
]

_USER_DICT_LOADED = False
USER_TERMS = {}
_STOPWORDS_LOADED = False

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT_DIR, "config.yaml")


def _cfg():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _ensure_dict():
    """加载自定义领域词典 data/kg_terms.txt（格式：词 [词频] [词性]）"""
    global _USER_DICT_LOADED
    if _USER_DICT_LOADED or jieba is None:
        return
    _USER_DICT_LOADED = True
    path = (_cfg().get("kg") or {}).get("term_dict") or "data/kg_terms.txt"
    if not os.path.isabs(path):
        path = os.path.join(ROOT_DIR, path)
    if not os.path.exists(path):
        return
    jieba.load_userdict(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                USER_TERMS[parts[0]] = parts[2] if len(parts) > 2 else "nz"
    except OSError:
        pass


def _load_stopwords():
    """加载噪声词表 data/kg_stopwords.txt（一行一个词）"""
    global _STOPWORDS_LOADED
    if _STOPWORDS_LOADED:
        return
    _STOPWORDS_LOADED = True
    path = (_cfg().get("kg") or {}).get("stopwords") or "data/kg_stopwords.txt"
    if not os.path.isabs(path):
        path = os.path.join(ROOT_DIR, path)
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                w = line.strip()
                if w and not w.startswith("#"):
                    _STOP.add(w)
    except OSError:
        pass


def _is_ascii_term(w):
    """英文/数字术语：全大写缩写、含数字，或首字母大写且长度 >= 4"""
    if not w.isascii() or len(w) < 3:
        return False
    if w.lower() in _EN_STOP:
        return False
    return w.isupper() or any(c.isdigit() for c in w) or (w[0].isupper() and len(w) >= 4)


def _extract_candidates(text):
    """从文本中抽取候选实体：自定义词典 + jieba 词性 + 正则模板"""
    if not text or pseg is None:
        return []
    _ensure_dict()
    _load_stopwords()

    out = []
    for tok, flag in pseg.cut(text):
        w = (tok or "").strip()
        if len(w) < 2 or len(w) > 10 or w in _STOP or w.isdigit():
            continue
        if w in USER_TERMS:
            out.append((w, _POS_MAP.get(USER_TERMS[w], "term")))
        elif flag in _POS_MAP:
            # 人名限制 2-4 字，过长基本是误判
            if flag == "nr" and len(w) > 4:
                continue
            out.append((w, _POS_MAP[flag]))
        elif flag == "eng" and _is_ascii_term(w):
            out.append((w, "term"))

    for pattern, etype in _REGEX_RULES:
        for m in pattern.findall(text):
            m = m.strip()
            if 3 <= len(m) <= 10 and m not in _STOP:
                out.append((m, etype))

    seen, result = set(), []
    for name, etype in out:
        key = (name.lower() if name.isascii() else name, etype)
        if key not in seen:
            seen.add(key)
            result.append((name, etype))
    return result


# ==================== 建表 ====================

def init_tables():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS kg_entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            normalized TEXT NOT NULL,
            type TEXT NOT NULL,
            mention_count INTEGER DEFAULT 0,
            doc_count INTEGER DEFAULT 0,
            UNIQUE(normalized, type)
        );

        CREATE TABLE IF NOT EXISTS kg_mentions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            para_index INTEGER NOT NULL,
            section_path TEXT,
            snippet TEXT,
            source TEXT DEFAULT 'structure'
        );

        CREATE TABLE IF NOT EXISTS kg_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            src_id INTEGER NOT NULL,
            dst_id INTEGER NOT NULL,
            predicate TEXT NOT NULL DEFAULT 'contains',
            weight REAL DEFAULT 1.0,
            evidence TEXT DEFAULT '',
            source TEXT DEFAULT 'structure',
            UNIQUE(src_id, dst_id, predicate)
        );

        CREATE TABLE IF NOT EXISTS kg_state (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_kgm_entity ON kg_mentions(entity_id);
        CREATE INDEX IF NOT EXISTS idx_kgm_file ON kg_mentions(file_path, para_index);
        CREATE INDEX IF NOT EXISTS idx_kgr_src ON kg_relations(src_id);
        CREATE INDEX IF NOT EXISTS idx_kgr_dst ON kg_relations(dst_id);
    """)
    conn.commit()
    conn.close()


def _set_state(key, value):
    conn = get_db()
    conn.execute(
        "INSERT INTO kg_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def _get_state(key, default=""):
    conn = get_db()
    row = conn.execute("SELECT value FROM kg_state WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


# ==================== 内部工具 ====================

def _escape_like(s):
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _norm_file_path(file_path):
    """真实路径转绝对路径；虚拟路径（upload://，只留索引不留文件）原样返回"""
    p = file_path or ""
    return p if p.startswith(VIRTUAL_PREFIX) else os.path.abspath(p)


def _dir_chain(directory):
    """E:\\a\\b\\c  ->  ['E:\\', 'E:\\a', 'E:\\a\\b', 'E:\\a\\b\\c']"""
    d = os.path.abspath(directory)
    drive, tail = os.path.splitdrive(d)
    parts = [p for p in tail.split(os.sep) if p]
    chain = []
    cur = (drive + os.sep) if drive else os.sep
    if parts:
        chain.append(cur.rstrip(os.sep) or cur)
    for p in parts:
        cur = os.path.join(cur, p)
        chain.append(cur)
    return chain


def _upsert_entity(conn, name, etype, normalized):
    row = conn.execute(
        "SELECT id FROM kg_entities WHERE normalized = ? AND type = ?", (normalized, etype)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO kg_entities (name, normalized, type) VALUES (?, ?, ?)",
        (name, normalized, etype),
    )
    return cur.lastrowid


def _upsert_entity_by_name(conn, name, etype, normalized):
    """L1 实体按名称唯一：同名只保留一行，避免 term / system 各存一份"""
    row = conn.execute("SELECT id FROM kg_entities WHERE normalized = ?", (normalized,)).fetchone()
    if row:
        return row["id"]
    return _upsert_entity(conn, name, etype, normalized)


def _add_relation(conn, src_id, dst_id, predicate="contains", weight=1.0,
                  evidence="", source="structure"):
    conn.execute(
        "INSERT OR IGNORE INTO kg_relations (src_id, dst_id, predicate, weight, evidence, source) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (src_id, dst_id, predicate, weight, evidence, source),
    )


def _bump_relation(conn, src_id, dst_id, predicate="related_to", weight=1.0,
                   evidence="", source="cooccurrence"):
    """共现边：重复出现则累加权重"""
    conn.execute(
        "INSERT INTO kg_relations (src_id, dst_id, predicate, weight, evidence, source) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(src_id, dst_id, predicate) DO UPDATE SET weight = weight + excluded.weight",
        (src_id, dst_id, predicate, weight, evidence, source),
    )


def _add_mention(conn, entity_id, file_path, para_index, section_path, snippet):
    if entity_id is None:
        return
    cnt = conn.execute(
        "SELECT COUNT(*) AS c FROM kg_mentions WHERE entity_id = ?", (entity_id,)
    ).fetchone()["c"]
    if cnt >= MENTION_LIMIT:
        return
    conn.execute(
        "INSERT INTO kg_mentions (entity_id, file_path, para_index, section_path, snippet) "
        "VALUES (?, ?, ?, ?, ?)",
        (entity_id, file_path, para_index, section_path, (snippet or "")[:300]),
    )


def _refresh_counts(conn, entity_ids):
    for eid in set(entity_ids):
        conn.execute(
            "UPDATE kg_entities SET mention_count = "
            "(SELECT COUNT(*) FROM kg_mentions WHERE entity_id = ?), "
            "doc_count = (SELECT COUNT(DISTINCT file_path) FROM kg_mentions WHERE entity_id = ?) "
            "WHERE id = ?",
            (eid, eid, eid),
        )


# ==================== 抽取 ====================

def remove_file(file_path, conn=None):
    """删除某文档在图谱中的章节节点、提及与关系（目录节点保留复用）"""
    own = conn is None
    if own:
        conn = get_db()
    fp = _norm_file_path(file_path)
    like = _escape_like(fp) + "::%"
    rows = conn.execute(
        "SELECT id FROM kg_entities WHERE (type = 'file' AND normalized = ?) "
        "OR (type = 'section' AND normalized LIKE ? ESCAPE '\\')",
        (fp, like),
    ).fetchall()
    ids = [r["id"] for r in rows]
    if ids:
        q = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM kg_relations WHERE src_id IN ({q}) OR dst_id IN ({q})", ids + ids)
        conn.execute(f"DELETE FROM kg_mentions WHERE entity_id IN ({q})", ids)
        conn.execute(f"DELETE FROM kg_entities WHERE id IN ({q})", ids)
    conn.execute("DELETE FROM kg_mentions WHERE file_path = ?", (fp,))

    # 递归清理空目录节点，以及已无任何提及的实体节点
    for _ in range(10):
        orphan = conn.execute(
            "SELECT e.id FROM kg_entities e WHERE "
            "(e.type = 'dir' AND NOT EXISTS "
            " (SELECT 1 FROM kg_relations r WHERE r.src_id = e.id)) "
            "OR (e.type IN ('person','system','term') AND NOT EXISTS "
            " (SELECT 1 FROM kg_mentions m WHERE m.entity_id = e.id))"
        ).fetchall()
        if not orphan:
            break
        oids = [r["id"] for r in orphan]
        q = ",".join("?" * len(oids))
        conn.execute(f"DELETE FROM kg_relations WHERE src_id IN ({q}) OR dst_id IN ({q})", oids + oids)
        conn.execute(f"DELETE FROM kg_entities WHERE id IN ({q})", oids)

    if own:
        conn.commit()
        conn.close()


def extract_file(chunks):
    """
    从某文档的全部 chunk 构建结构图谱：目录链 -> 文档 -> 章节树
    chunks 需含 file_path / section_path / para_index / content
    """
    if not chunks:
        return 0

    init_tables()
    conn = get_db()
    try:
        file_path = _norm_file_path(chunks[0]["file_path"])
        virtual = file_path.startswith(VIRTUAL_PREFIX)
        remove_file(file_path, conn=conn)

        touched = []

        # 1) 目录链（虚拟路径没有磁盘层级，跳过）
        parent_id = None
        if not virtual:
            for d in _dir_chain(os.path.dirname(file_path)):
                name = os.path.basename(d.rstrip(os.sep)) or d
                did = _upsert_entity(conn, name, "dir", d)
                touched.append(did)
                if parent_id is not None:
                    _add_relation(conn, parent_id, did, "contains")
                parent_id = did

        # 2) 文档节点
        fname = file_path[len(VIRTUAL_PREFIX):] if virtual else os.path.basename(file_path)
        file_id = _upsert_entity(conn, fname, "file", file_path)
        touched.append(file_id)
        if parent_id is not None:
            _add_relation(conn, parent_id, file_id, "contains")

        # 3) 章节树（按 " / " 逐级建父子节点）
        section_ids = {}
        for ch in chunks:
            sp = (ch.get("section_path") or "").strip()
            para = ch.get("para_index", 0)
            content = ch.get("content", "") or ""

            # ---- 章节树（L0）----
            leaf = None
            if sp:
                parts = [p.strip() for p in re.split(r"\s*/\s*", sp) if p.strip()]
                parent = file_id
                leaf = None
                for i, part in enumerate(parts):
                    norm = file_path + "::" + " / ".join(parts[: i + 1])
                    sid = section_ids.get(norm)
                    if sid is None:
                        sid = _upsert_entity(conn, part, "section", norm)
                        section_ids[norm] = sid
                        touched.append(sid)
                        _add_relation(conn, parent, sid, "contains")
                    parent = sid
                    leaf = sid
                if leaf is not None:
                    _add_mention(conn, leaf, file_path, para, sp, content)

            # ---- 实体抽取（L1）+ 段内共现 ----
            ids_in_chunk = []
            for raw_name, etype in _extract_candidates(content):
                name = canonical_name(raw_name)          # 别名 -> 规范名
                if _is_stopword(name):                   # 剥完只剩泛词则丢弃
                    continue
                norm = _norm_key(name)
                eid = _upsert_entity_by_name(conn, name, etype, norm)
                touched.append(eid)
                _add_mention(conn, eid, file_path, para, sp, content[:200])
                # 结构锚点：实体挂到所在章节（无章节则挂文档），让实体与文档树连通
                _bump_relation(conn, leaf if leaf is not None else file_id, eid,
                               "mentions", 1.0, "", "mention")
                if eid not in ids_in_chunk:
                    ids_in_chunk.append(eid)

            for a, b in itertools.combinations(ids_in_chunk[:MAX_ENTITIES_PER_CHUNK], 2):
                _bump_relation(conn, a, b, "related_to", 1.0, "", "cooccurrence")

        _refresh_counts(conn, touched)
        conn.commit()
        return len(touched)
    finally:
        conn.close()


def _load_chunks(conn, file_path):
    rows = conn.execute(
        "SELECT content, file_path, title, section_path, para_index, source_type "
        "FROM chunks_fts WHERE file_path = ? ORDER BY para_index",
        (file_path,),
    ).fetchall()
    return [dict(r) for r in rows]


def rebuild_file(file_path):
    init_tables()
    conn = get_db()
    chunks = _load_chunks(conn, file_path)
    conn.close()
    return extract_file(chunks)


def prune_relations(max_per_node=10):
    """每个节点最多保留权重最高的 max_per_node 条共现边（防止边爆炸）"""
    conn = get_db()
    conn.execute(
        """
        DELETE FROM kg_relations WHERE predicate = 'related_to' AND id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY node, predicate ORDER BY weight DESC, id
                ) AS rn FROM (
                    SELECT id, src_id AS node, predicate, weight FROM kg_relations WHERE predicate = 'related_to'
                    UNION ALL
                    SELECT id, dst_id AS node, predicate, weight FROM kg_relations WHERE predicate = 'related_to'
                )
            ) WHERE rn > ?
        )
        """,
        (max_per_node,),
    )
    conn.commit()
    conn.close()


def prune_entities(min_doc=2, min_mention=3):
    """清理低频实体：只出现在 1 篇文档且提及极少的，多半是分词噪声"""
    conn = get_db()
    rows = conn.execute(
        "SELECT id FROM kg_entities WHERE type IN ('person','system','term') "
        "AND doc_count < ? AND mention_count < ?",
        (min_doc, min_mention),
    ).fetchall()
    ids = [r["id"] for r in rows]
    if ids:
        q = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM kg_relations WHERE src_id IN ({q}) OR dst_id IN ({q})", ids + ids)
        conn.execute(f"DELETE FROM kg_mentions WHERE entity_id IN ({q})", ids)
        conn.execute(f"DELETE FROM kg_entities WHERE id IN ({q})", ids)
    conn.commit()
    conn.close()
    return len(ids)


def rebuild_all():
    """全量重建：清空图谱表后按现有索引重建（不重新解析文件）"""
    init_tables()
    conn = get_db()
    conn.executescript(
        "DELETE FROM kg_relations; DELETE FROM kg_mentions; DELETE FROM kg_entities;"
    )
    conn.commit()
    rows = conn.execute("SELECT file_path FROM documents").fetchall()
    conn.close()

    for r in rows:
        rebuild_file(r["file_path"])

    # 去重/降噪：共现边按权重裁剪，低频实体清理（仅全量重建时做）
    cfg = _cfg().get("kg") or {}
    prune_relations(int(cfg.get("topk_edges", 10)))
    pruned = prune_entities(int(cfg.get("min_doc", 2)), int(cfg.get("min_mention", 3)))
    _set_state("last_build", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    conn = get_db()
    entity_count = conn.execute("SELECT COUNT(*) AS c FROM kg_entities").fetchone()["c"]
    relation_count = conn.execute("SELECT COUNT(*) AS c FROM kg_relations").fetchone()["c"]
    conn.close()
    return {"files": len(rows), "entities": entity_count,
            "relations": relation_count, "pruned": pruned}


# ==================== 查询 ====================

def stats():
    init_tables()
    conn = get_db()
    by_type = {}
    for r in conn.execute("SELECT type, COUNT(*) AS c FROM kg_entities GROUP BY type"):
        by_type[r["type"]] = r["c"]
    entity_count = sum(by_type.values())
    relation_count = conn.execute("SELECT COUNT(*) AS c FROM kg_relations").fetchone()["c"]
    mention_count = conn.execute("SELECT COUNT(*) AS c FROM kg_mentions").fetchone()["c"]
    conn.close()
    return {
        "entity_count": entity_count,
        "relation_count": relation_count,
        "mention_count": mention_count,
        "by_type": by_type,
        "last_build": _get_state("last_build", "尚未构建"),
    }


def search_entities(q="", etype="", limit=50, offset=0):
    init_tables()
    conn = get_db()
    sql = "SELECT id, name, type, normalized, mention_count, doc_count FROM kg_entities"
    where, params = [], []
    if q:
        where.append("name LIKE ? ESCAPE '\\'")
        params.append("%" + _escape_like(q) + "%")
    if etype:
        where.append("type = ?")
        params.append(etype)
    if where:
        sql += " WHERE " + " AND ".join(where)
    total = conn.execute(
        "SELECT COUNT(*) AS c FROM kg_entities" + (" WHERE " + " AND ".join(where) if where else ""),
        params,
    ).fetchone()["c"]
    sql += " ORDER BY mention_count DESC, id LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows], total


def entity_detail(entity_id):
    init_tables()
    conn = get_db()
    ent = conn.execute(
        "SELECT id, name, type, normalized, mention_count, doc_count FROM kg_entities WHERE id = ?",
        (entity_id,),
    ).fetchone()
    if not ent:
        conn.close()
        return None

    mentions = conn.execute(
        "SELECT file_path, para_index, section_path, snippet FROM kg_mentions "
        "WHERE entity_id = ? ORDER BY para_index LIMIT ?",
        (entity_id, MENTION_LIMIT),
    ).fetchall()

    def _enrich(rows):
        out = []
        for r in rows:
            e = conn.execute(
                "SELECT id, name, type FROM kg_entities WHERE id = ?", (r["other_id"],)
            ).fetchone()
            if e:
                out.append({"id": e["id"], "name": e["name"], "type": e["type"],
                            "predicate": r["predicate"]})
        return out

    parents = conn.execute(
        "SELECT src_id AS other_id, predicate FROM kg_relations WHERE dst_id = ?", (entity_id,)
    ).fetchall()
    children = conn.execute(
        "SELECT dst_id AS other_id, predicate, weight FROM kg_relations WHERE src_id = ?",
        (entity_id,),
    ).fetchall()

    related = []
    for r in conn.execute(
        "SELECT src_id, dst_id, weight FROM kg_relations "
        "WHERE predicate = 'related_to' AND (src_id = ? OR dst_id = ?) "
        "ORDER BY weight DESC LIMIT 20",
        (entity_id, entity_id),
    ).fetchall():
        other = r["dst_id"] if r["src_id"] == entity_id else r["src_id"]
        e = conn.execute("SELECT id, name, type FROM kg_entities WHERE id = ?", (other,)).fetchone()
        if e:
            related.append({"id": e["id"], "name": e["name"], "type": e["type"],
                            "weight": r["weight"]})

    result = {
        "entity": dict(ent),
        "mentions": [dict(m) for m in mentions],
        "parents": _enrich(parents),
        "children": _enrich(children),
        "related": related,
        "alias": alias_info(ent["name"]),
    }
    conn.close()
    return result


def neighbors(entity_id, depth=1, limit=60):
    """BFS 取邻居子图（双向遍历），返回 nodes + edges"""
    init_tables()
    conn = get_db()
    visited = {int(entity_id)}
    frontier = {int(entity_id)}
    edges = []
    for _ in range(max(1, min(depth, 3))):
        if not frontier or len(visited) > limit:
            break
        q = ",".join("?" * len(frontier))
        rows = conn.execute(
            f"SELECT src_id, dst_id, predicate, weight FROM kg_relations "
            f"WHERE src_id IN ({q}) OR dst_id IN ({q})",
            list(frontier) + list(frontier),
        ).fetchall()
        nxt = set()
        for r in rows:
            key = (r["src_id"], r["dst_id"], r["predicate"])
            edges.append({"source": r["src_id"], "target": r["dst_id"],
                          "predicate": r["predicate"], "weight": r["weight"]})
            for nid in (r["src_id"], r["dst_id"]):
                if nid not in visited:
                    nxt.add(nid)
        visited |= nxt
        frontier = nxt

    ids = list(visited)[:limit]
    q = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT id, name, type, mention_count FROM kg_entities WHERE id IN ({q})", ids
    ).fetchall()
    conn.close()
    return {"nodes": [dict(r) for r in rows], "edges": edges}


def graph(top=200, etype="", q="", types=None):
    """
    全局概览图：按类型配额取节点（避免 dir/file 因提及数为 0 被挤掉），
    名额没用完时再按提及数补齐；只保留两端都在集合内的边
    """
    init_tables()
    conn = get_db()
    type_list = [etype] if etype else list(types or ["dir", "file", "section", "person", "system", "term"])
    per_type = max(1, top // max(1, len(type_list)))

    nodes, seen = [], set()

    def _query(etype_, limit, exclude):
        sql = "SELECT id, name, type, normalized, mention_count FROM kg_entities WHERE type = ?"
        params = [etype_]
        if q:
            sql += " AND name LIKE ? ESCAPE '\\'"
            params.append("%" + _escape_like(q) + "%")
        if exclude:
            sql += " AND id NOT IN (%s)" % ",".join("?" * len(exclude))
            params.extend(exclude)
        sql += " ORDER BY mention_count DESC, id LIMIT ?"
        params.append(limit)
        return conn.execute(sql, params).fetchall()

    for t in type_list:
        for r in _query(t, per_type, []):
            if r["id"] not in seen:
                seen.add(r["id"])
                nodes.append(dict(r))

    # 名额未用满：按提及数从全库补齐（指定单一类型时不跨类型补）
    if len(nodes) < top and not etype:
        sql = "SELECT id, name, type, normalized, mention_count FROM kg_entities"
        params = []
        where = []
        if q:
            where.append("name LIKE ? ESCAPE '\\'")
            params.append("%" + _escape_like(q) + "%")
        if seen:
            where.append("id NOT IN (%s)" % ",".join("?" * len(seen)))
            params.extend(seen)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY mention_count DESC, id LIMIT ?"
        params.append(top - len(nodes))
        for r in conn.execute(sql, params).fetchall():
            if r["id"] not in seen:
                seen.add(r["id"])
                nodes.append(dict(r))

    ids = [n["id"] for n in nodes]
    edges = []
    if ids:
        q = ",".join("?" * len(ids))
        edges = [
            {"source": r["src_id"], "target": r["dst_id"], "predicate": r["predicate"]}
            for r in conn.execute(
                f"SELECT src_id, dst_id, predicate FROM kg_relations "
                f"WHERE src_id IN ({q}) AND dst_id IN ({q})",
                ids + ids,
            ).fetchall()
        ]
    conn.close()
    return {"nodes": nodes, "edges": edges}


# ==================== 路径查询 ====================

def shortest_path(src_id, dst_id, max_depth=4):
    """无向 BFS 最短路径，返回路径上的节点与边"""
    init_tables()
    conn = get_db()
    adj = {}
    for r in conn.execute("SELECT src_id, dst_id, predicate FROM kg_relations").fetchall():
        adj.setdefault(r["src_id"], []).append((r["dst_id"], r["predicate"]))
        adj.setdefault(r["dst_id"], []).append((r["src_id"], r["predicate"]))
    conn.close()

    if src_id == dst_id:
        conn = get_db()
        e = conn.execute("SELECT id, name, type FROM kg_entities WHERE id = ?", (src_id,)).fetchone()
        conn.close()
        return {"found": True, "nodes": [dict(e)] if e else [], "edges": []}

    prev = {src_id: None}
    frontier = [src_id]
    for _ in range(max(1, max_depth)):
        nxt, found = [], False
        for u in frontier:
            for v, pred in adj.get(u, []):
                if v in prev:
                    continue
                prev[v] = (u, pred)
                if v == dst_id:
                    found = True
                    break
                nxt.append(v)
            if found:
                break
        if found or not nxt:
            break
        frontier = nxt

    if dst_id not in prev:
        return {"found": False, "nodes": [], "edges": []}

    chain = [dst_id]
    while chain[-1] != src_id:
        chain.append(prev[chain[-1]][0])
    chain.reverse()

    conn = get_db()
    q = ",".join("?" * len(chain))
    rows = {r["id"]: dict(r) for r in conn.execute(
        f"SELECT id, name, type FROM kg_entities WHERE id IN ({q})", chain).fetchall()}
    conn.close()
    nodes = [rows[i] for i in chain if i in rows]
    edges = [{"source": chain[i], "target": chain[i + 1],
              "predicate": prev[chain[i + 1]][1]} for i in range(len(chain) - 1)]
    return {"found": True, "nodes": nodes, "edges": edges}


# ---------- 实体别名合并 ----------

_ALIAS_LOADED = False
ALIAS_MAP = {}       # 别名 -> 规范名
ALIAS_REVERSE = {}   # 规范名 -> [别名]


def _norm_key(name):
    n = (name or "").strip()
    return n.lower() if n.isascii() else n


def _load_alias():
    """加载别名表 data/kg_alias.json：{"规范名": ["别名", ...]}"""
    global _ALIAS_LOADED
    if _ALIAS_LOADED:
        return
    _ALIAS_LOADED = True
    path = (_cfg().get("kg") or {}).get("alias_file") or "data/kg_alias.json"
    if not os.path.isabs(path):
        path = os.path.join(ROOT_DIR, path)
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except (OSError, ValueError):
        return
    for canon, aliases in data.items():
        if not isinstance(aliases, list):
            continue
        ALIAS_MAP[_norm_key(canon)] = canon
        ALIAS_REVERSE.setdefault(canon, [])
        for a in aliases:
            if not a or _norm_key(a) == _norm_key(canon):
                continue
            ALIAS_MAP[_norm_key(a)] = canon
            ALIAS_REVERSE[canon].append(a)


# 中文专利/公文里常见的句首粘连词（只收 >=2 字的，单字如「对/从/在」本身是词的一部分，不能剥）
_NOISE_PREFIX = tuple(sorted((
    "而未通过", "可以通过", "用于查询", "以使所述", "核查所述", "所述", "一种",
    "通过", "用于", "包括", "以及", "并且", "获取", "当前", "接收", "结合", "保证",
), key=len, reverse=True))

# 剥完只剩这些光杆词说明剥过头了，保留原样
_BARE_WORD = {"系统", "子系统", "平台", "模块", "服务", "引擎", "框架", "数据库", "接口", "中心"}


def strip_prefix(name):
    """剥离句首粘连词：「所述对账系统」「一种对账系统」->「对账系统」"""
    for _ in range(3):
        for p in _NOISE_PREFIX:
            if name.startswith(p):
                rest = name[len(p):]
                if len(rest) >= 2 and rest not in _BARE_WORD:
                    name = rest
                    break
        else:
            break
    return name


def _is_stopword(name):
    """剥离/映射之后的兜底过滤：光杆泛词（系统 / 服务 / 模块 …）不算实体"""
    _load_stopwords()
    return (name or "") in _STOP or (name or "") in _BARE_WORD


def canonical_name(name):
    """别名/前缀噪声 -> 规范名（未命中则原样返回）"""
    _load_alias()
    name = ALIAS_MAP.get(_norm_key(name), name)
    name = strip_prefix(name)
    return ALIAS_MAP.get(_norm_key(name), name)


def alias_info(name):
    """返回某实体名的规范名与其别名列表"""
    _load_alias()
    canon = ALIAS_MAP.get(_norm_key(name), name)
    return {"canonical": canon, "aliases": list(ALIAS_REVERSE.get(canon, []))}


def find_entity(name):
    """按名称查实体（自动处理别名），按提及数倒序"""
    init_tables()
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, type, mention_count FROM kg_entities "
        "WHERE normalized = ? OR name = ? ORDER BY mention_count DESC, id",
        (_norm_key(canonical_name(name)), (name or "").strip()),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def merge_entities(keep_id, merge_ids):
    """把 merge_ids 合并进 keep_id：迁移提及与关系、重算计数、删除被合并节点"""
    init_tables()
    conn = get_db()
    if not conn.execute("SELECT 1 FROM kg_entities WHERE id = ?", (keep_id,)).fetchone():
        conn.close()
        return {"ok": False, "error": "保留实体不存在"}

    merged = 0
    for mid in merge_ids:
        try:
            mid = int(mid)
        except (TypeError, ValueError):
            continue
        if mid == keep_id:
            continue
        if not conn.execute("SELECT 1 FROM kg_entities WHERE id = ?", (mid,)).fetchone():
            continue

        # 提及：去重迁移
        conn.execute(
            "INSERT INTO kg_mentions (entity_id, file_path, para_index, section_path, snippet) "
            "SELECT ?, m.file_path, m.para_index, m.section_path, m.snippet FROM kg_mentions m "
            "WHERE m.entity_id = ? AND NOT EXISTS ("
            "  SELECT 1 FROM kg_mentions x WHERE x.entity_id = ? "
            "  AND x.file_path = m.file_path AND x.para_index = m.para_index)",
            (keep_id, mid, keep_id),
        )
        # 关系：端点改指向保留节点，冲突则累加权重
        for r in conn.execute(
            "SELECT src_id, dst_id, predicate, weight FROM kg_relations WHERE src_id = ? OR dst_id = ?",
            (mid, mid),
        ).fetchall():
            src = keep_id if r["src_id"] == mid else r["src_id"]
            dst = keep_id if r["dst_id"] == mid else r["dst_id"]
            if src == dst:
                continue
            _bump_relation(conn, src, dst, r["predicate"], r["weight"] or 1.0, "", "merge")

        conn.execute("DELETE FROM kg_relations WHERE src_id = ? OR dst_id = ?", (mid, mid))
        conn.execute("DELETE FROM kg_mentions WHERE entity_id = ?", (mid,))
        conn.execute("DELETE FROM kg_entities WHERE id = ?", (mid,))
        merged += 1

    _refresh_counts(conn, [keep_id])
    conn.commit()
    conn.close()
    return {"ok": True, "keep_id": keep_id, "merged": merged}


def apply_aliases():
    """按 data/kg_alias.json 把库内已有的别名实体合并到规范实体（无需重建图谱）"""
    _load_alias()
    if not ALIAS_MAP:
        return {"ok": True, "merged": 0, "groups": 0, "note": "未配置别名（kg.alias_file）"}

    init_tables()
    merged = groups = 0
    for canon, aliases in ALIAS_REVERSE.items():
        rows = []
        for a in aliases:
            rows.extend(find_entity(a))
        if not rows:
            continue

        keep = find_entity(canon)
        if keep:
            keep_row = keep[0]
        else:
            # 规范实体还不存在：把提及最多的那个改名为规范名
            rows.sort(key=lambda r: r["mention_count"], reverse=True)
            keep_row = rows[0]
            conn = get_db()
            try:
                conn.execute("UPDATE kg_entities SET name = ?, normalized = ? WHERE id = ?",
                             (canon, _norm_key(canon), keep_row["id"]))
                conn.commit()
            except Exception:
                pass
            conn.close()

        ids = [r["id"] for r in rows if r["id"] != keep_row["id"]]
        if not ids:
            continue
        res = merge_entities(keep_row["id"], ids)
        merged += res.get("merged", 0)
        groups += 1
    return {"ok": True, "merged": merged, "groups": groups, "aliases": len(ALIAS_MAP)}


# ---------- 搜索结果 -> 命中实体 ----------

ENTITY_TYPES = ("person", "system", "term")


def entities_for_chunks(chunks, limit=12):
    """给定 (file_path, para_index) 片段列表，返回其中出现最多的实体"""
    init_tables()
    pairs = []
    for c in chunks or []:
        fp = c.get("file_path")
        if fp:
            pairs.append((_norm_file_path(fp), c.get("para_index", 0)))
    if not pairs:
        return []
    pairs = pairs[:200]

    conn = get_db()
    cond = " OR ".join(["(m.file_path = ? AND m.para_index = ?)"] * len(pairs))
    params = []
    for fp, pi in pairs:
        params.extend([fp, pi])
    params.extend(ENTITY_TYPES)
    params.append(limit)
    q = ",".join("?" * len(ENTITY_TYPES))
    rows = conn.execute(
        f"SELECT e.id, e.name, e.type, COUNT(*) AS c FROM kg_mentions m "
        f"JOIN kg_entities e ON e.id = m.entity_id "
        f"WHERE ({cond}) AND e.type IN ({q}) "
        f"GROUP BY e.id ORDER BY c DESC, e.id LIMIT ?",
        params,
    ).fetchall()
    conn.close()
    return [{"id": r["id"], "name": r["name"], "type": r["type"], "count": r["c"]} for r in rows]



