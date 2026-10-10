"""测试搜索"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import indexer

indexer.init_db()

for kw in ["知识库", "搜索", "部署", "文档", "Python"]:
    results = indexer.search(kw, max_results=5)
    print(f"\n=== 搜索 '{kw}': {len(results)} 条结果 ===")
    for r in results[:3]:
        print(f"  [{r['source_type']}] {r['title']}")
        print(f"    位置: {r['section_path']} | 段落 {r['para_index']} | BM25: {r['score']}")
        # 去掉 HTML 标签显示纯文本
        import re
        clean = re.sub(r'<[^>]+>', '', r['highlighted'])
        print(f"    内容: {clean[:100]}")
        print()