"""重建索引并测试 v2"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import indexer, sync

indexer.init_db()
print("[1/3] DB init OK")

dirs = [r"C:\Users\shuai.wang\Desktop"]
exts = [".docx", ".txt", ".md", ".pdf", ".xlsx"]
a, u, s, r, e = sync.scan_and_index(dirs, exts)
print(f"[2/3] Index: added={a} updated={u} skipped={s} removed={r}")
if e:
    print(f"  Errors ({len(e)}): {e[:3]}")

st = indexer.get_stats()
print(f"[3/3] Stats: {st}")

# 测试高亮
results, total = indexer.search("部署", page=1, per_page=5)
print(f"\nSearch '部署': {total} results, showing {len(results)}")
for r in results[:2]:
    has_mark = "<mark>" in r["highlighted"]
    print(f"  has_mark={has_mark} | {r['title']} | src={r['source_type']}")
    print(f"  preview: {r['highlighted'][:120]}")
    print()

# 测试文件列表
files, ftotal = indexer.get_doc_list(page=1, per_page=5)
print(f"File list: {ftotal} total, showing {len(files)}")
for f in files:
    print(f"  {f['title']} | {f['source_type']} | chunks={f['chunk_count']}")