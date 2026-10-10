# 📚 知识库搜索

> 纯本地全文检索系统，不依赖任何大模型。输入关键词，秒级定位到文档出处。
>
> 技术栈：SQLite FTS5 + jieba 分词 + BM25 相关性排序 + Flask

---

## ✨ 核心能力

| 能力 | 说明 |
|------|------|
| **关键词搜索** | BM25 相关性排序，支持中文分词（jieba 搜索引擎模式） |
| **关键词高亮** | 命中的关键词用黄色 `<mark>` 高亮，大小写不敏感 |
| **定位出处** | 每条结果显示 文件路径 + 章节路径 + 段落号/行号，点击可查看原文上下文 |
| **多格式支持** | Word (.docx) / PDF / Excel (.xlsx) / 文本 / Markdown |
| **来源过滤** | 按文档类型筛选搜索结果 |
| **增量同步** | 后台定时扫描目录，MD5 hash 变化才重新索引 |
| **批量上传** | 拖拽或选择文件/文件夹批量上传并自动索引 |
| **文件管理** | 文件列表查看、批量移除、点击打开原文件 |

---

## 📁 项目结构

```
Knowledge/
├── app/
│   ├── __init__.py        # 包初始化
│   ├── parser.py          # 文档解析（Word/PDF/Excel/TXT/MD → chunks）
│   ├── indexer.py         # SQLite FTS5 索引 + 搜索 + 统计
│   ├── sync.py            # 增量同步（扫描目录 → hash 对比 → 索引）
│   └── server.py          # Flask Web 服务 + 全部前端界面
├── data/
│   └── knowseek.db         # SQLite 数据库（自动创建）
├── uploads/                # 上传文件存储目录（自动创建）
├── config.yaml             # 配置文件
├── requirements.txt        # Python 依赖
├── run.py                  # 启动入口
├── test_search.py          # 搜索测试脚本
├── test_rebuild.py         # 重建索引测试脚本
└── 启动知寻.bat            # Windows 一键启动
```

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

> 国内网络建议使用清华镜像：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`

### 2. 配置

编辑 `config.yaml`：

```yaml
# 文档扫描目录（支持多个）
scan_dirs:
  - "C:\\Users\\xxx\\Desktop"

# 支持的文件扩展名
extensions:
  - ".docx"
  - ".txt"
  - ".md"
  - ".pdf"
  - ".xlsx"

sync_interval: 300   # 增量同步间隔（秒）
max_results: 50      # 最大返回条数
port: 9876            # 服务端口
```

### 3. 启动

```bash
python run.py
```

浏览器访问 **http://127.0.0.1:9876**

Windows 也可双击 `启动知寻.bat`。

---

## 🖥️ 界面功能

### 📊 仪表盘（首页）
- 文档总数、片段总数、各来源分类数量
- 点击来源卡片可快速跳转搜索该类型
- 最近索引文件列表

### 🔍 搜索
- 输入关键词 → BM25 排序返回结果
- 结果卡片显示：来源标签、文件名、高亮内容、章节定位、BM25 分数
- 点击结果卡片 → 弹窗查看原文（目标段落黄底高亮，前后各 2 段灰色上下文）
- 来源过滤器（全部 / Word / PDF / Excel / 文本/MD / 飞书 / 语雀 / Jenkins）
- **重置按钮**：清空关键词、过滤器、结果，恢复初始状态
- 分页（每页 10 条）

### 📁 文件列表
- 全部已索引文件列表（文件名、来源、片段数、索引时间、路径）
- 表头复选框：全选/取消全选（联动选中样式）
- 单行勾选：选中行高亮
- 批量移除：选中后一键移除索引
- 点击文件名：弹窗查看文件内容
- 分页（每页 10 条）

### 📤 上传文件
- 拖拽上传 / 点击选择文件
- 选择文件夹批量上传
- 支持 .docx / .pdf / .xlsx / .txt / .md
- 上传进度条与结果反馈

---

## 🏗️ 架构原理

```
┌───────────────┐     ┌────────────────┐     ┌──────────────────┐
│  文档扫描      │ ──→ │  jieba 分词     │ ──→ │  SQLite FTS5     │
│  .docx/.pdf   │     │  搜索引擎模式    │     │  BM25 + UNINDEXED │
│  .xlsx/.txt   │     │  空格拼接 tokenize│     │  原文存储          │
│  .md          │     └────────────────┘     └────────┬─────────┘
└───────────────┘                                       │
                                                        │ SQL 查询
┌───────────────┐                                       │
│  增量同步      │ ←── MD5 hash 对比 ──────────────────────┘
│  定时扫描      │
└───────────────┘
                                                        │
                                          ┌─────────────▼──────────────┐
                                          │  Flask API + Web UI        │
                                          │  搜索 / 高亮 / 文件查看     │
                                          │  上传 / 管理 / 仪表盘       │
                                          └────────────────────────────┘
```

### 文档解析流程

| 格式 | 解析方式 | 切块策略 | 定位信息 |
|------|----------|----------|----------|
| Word (.docx) | python-docx 按段落 | 每个段落 = 1 chunk | 文件路径 + Heading 路径 + 段落序号 |
| PDF (.pdf) | pdfplumber 按页 | 每页文本 = 1 chunk | 文件路径 + "第 N 页" + 页号 |
| Excel (.xlsx) | openpyxl 按 Sheet | 每行 = 1 chunk | 文件路径 + Sheet 名 + 行号 |
| 文本/MD | 逐行读取 | 每 3 行 = 1 chunk | 文件路径 + 行号范围 |

### 搜索流程

1. 用户输入关键词 → jieba `cut_for_search` 分词
2. 构建 FTS5 MATCH 表达式（AND 语义）
3. SQLite `bm25()` 函数排序
4. Python 层对结果做关键词高亮
5. 点击结果 → 从数据库按 `file_path + para_index` 取目标 chunk + 上下文（毫秒级）

---

## 🔌 扩展数据源

当前支持本地文件（Word/PDF/Excel/TXT/MD），后续可扩展对接外部平台：

| 数据源 | 对接方式 | 切块策略 |
|--------|----------|----------|
| **飞书** | 飞书开放 API 导出 DOCX → 走 Word 解析 | 同 Word |
| **语雀** | 语雀 Open API v2 取 Markdown | 同文本 |
| **Jenkins** | REST API 取构建日志 → 按行切分 | 同文本 |

每个数据源封装为独立 Connector，实现统一接口（拉文档 / 取内容 / 监听变更 / 构建跳转 URL），新增数据源仅需加 Connector。

---

## ⚙️ 高级配置

### 自定义词典

在 `data/custom_dict.txt` 里一行一个词，然后在 `config.yaml` 取消注释：

```yaml
custom_dict: "data/custom_dict.txt"
```

### 性能说明

- 索引 41 篇文档（3976 片段）< 5 秒
- 搜索响应 < 1 秒（含 jieba 分词 + FTS5 查询 + 高亮）
- 文件内容查看 < 100ms（直接查 SQLite，不重新解析文件）
- 内存占用 < 100MB
- 适合 1 万篇文档以内

---

## 📦 依赖清单

| 依赖 | 用途 |
|------|------|
| jieba | 中文分词 |
| python-docx | Word 文档解析 |
| pdfplumber | PDF 文档解析 |
| openpyxl | Excel 文档解析 |
| flask | Web 服务 |
| watchdog | 文件监听（增量同步） |
| requests | HTTP 请求（扩展数据源） |
| PyYAML | 配置文件解析 |

---