
# 知识库搜索 - 本地轻量版

> 纯本地全文检索，不依赖任何大模型。SQLite FTS5 + jieba 分词 + Flask。

## 安装

```bash
pip install -r requirements.txt
```

## 启动

```bash
python run.py
```

浏览器访问 http://127.0.0.1:9876

## 功能

- **关键词搜索**：输入关键词，BM25 相关性排序返回结果
- **关键词高亮**：命中的关键词用 `<mark>` 标签高亮
- **定位出处**：每条结果显示 文件路径 + 章节路径 + 段落号/行号
- **元数据过滤**：按来源类型（Word/文本/飞书/语雀/Jenkins）过滤
- **增量同步**：后台定时扫描，MD5 hash 变了才重新索引
- **支持格式**：.docx / .txt / .md

## 配置

编辑 `config.yaml`：

```yaml
scan_dirs:          # 文档扫描目录
  - "C:\\Users\\xxx\\Desktop"
extensions:          # 支持的扩展名
  - ".docx"
  - ".txt"
  - ".md"
sync_interval: 300   # 同步间隔（秒）
max_results: 50      # 最大返回条数
port: 9876           # 服务端口
```

## 架构

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│ 文档扫描     │ ──→ │ jieba 分词    │ ──→ │ SQLite FTS5 │
│ .docx/.txt  │     │ 预分词+空格拼接│     │ BM25 + 高亮  │
└─────────────┘     └──────────────┘     └─────┬───────┘
                                                │
                                          ┌─────▼───────┐
                                          │ Flask API   │
                                          │ 搜索界面     │
                                          └─────────────┘
```

## 扩展数据源

- **飞书**：调飞书 API 导出 DOCX → 走 Word 解析
- **语雀**：调语雀 API 取 Markdown → 走文本解析
- **Jenkins**：调 REST API 取构建日志 → 按行切块

## 可选

- 自定义词典：在 `data/custom_dict.txt` 里一行一个词，配置 `config.yaml` 的 `custom_dict`