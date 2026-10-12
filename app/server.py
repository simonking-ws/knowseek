"""
Flask Web 服务 - 搜索界面 + 索引管理 API
功能：仪表盘Tab、搜索（分页+高亮+点击跳转）、文件列表（批量移除+点击打开）、批量上传文件夹
"""

import os
import shutil
import tempfile
import threading
import subprocess
import sys
import json
from flask import Flask, request, jsonify, render_template_string, send_file, make_response
from . import indexer, sync, kg
from .parser import parse_file, compute_file_hash

import yaml

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")
CONFIG_EXAMPLE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.example.yaml")

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}

config = load_config()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
os.makedirs(STATIC_DIR, exist_ok=True)
# 静态资源指向项目根 static/（离线内置 ECharts，不走 CDN）
app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")

# 上传件只保留索引，不保留原文件：入库后用虚拟路径 upload://文件名 标识
UPLOAD_PREFIX = "upload://"

SUPPORTED_EXTS = {".docx", ".doc", ".txt", ".md", ".pdf", ".xlsx", ".xls"}


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>知寻 KnowSeek · 本地知识库全文检索</title>
<style>
:root {
  --bg: #f0f2f5; --card: #fff; --primary: #4a6fa5; --primary-dark: #3a5a8e;
  --text: #1a1a2e; --text-2: #666; --border: #e0e0e0;
  --mark: #fff3a0; --radius: 10px; --shadow: 0 2px 8px rgba(0,0,0,.06);
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text)}

.header{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;padding:16px 24px}
.header-content{max-width:1200px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}
.header h1{font-size:22px;font-weight:600;line-height:1.35}.header h1 .icon{margin-right:8px}
.header .stats{font-size:13px;color:rgba(255,255,255,.6)}
.header .brand{display:flex;flex-direction:column;gap:6px;min-width:0}
.header .brand h1 .en{font-size:13px;font-weight:400;color:rgba(255,255,255,.45);margin-left:8px;letter-spacing:.5px}
.header .subtitle{font-size:12.5px;color:rgba(255,255,255,.62);line-height:1.6}
.header .tagline{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.header .tagline .tag{display:inline-flex;align-items:center;line-height:1.5;border:1px solid rgba(255,255,255,.2);border-radius:4px;padding:1px 7px;font-size:11.5px;color:rgba(255,255,255,.78);white-space:nowrap}
.header .tagline .muted{font-size:11.5px;color:rgba(255,255,255,.45);margin-left:2px}
@media(max-width:640px){.header{padding:14px 16px}.header h1{font-size:19px}.header .subtitle{font-size:12px}}

.nav-tabs{max-width:1200px;margin:0 auto;display:flex;gap:0;background:var(--card);border-bottom:1px solid var(--border)}
.nav-tab{padding:12px 24px;font-size:14px;color:var(--text-2);cursor:pointer;border:none;background:none;border-bottom:2px solid transparent;transition:all .2s}
.nav-tab:hover{color:var(--primary)}
.nav-tab.active{color:var(--primary);border-bottom-color:var(--primary);font-weight:500}
.tab-badge{display:inline-block;margin-left:4px;min-width:16px;height:16px;line-height:16px;text-align:center;font-size:10px;font-weight:600;border-radius:8px;padding:0 4px}
.tab-badge.zero{display:none}

.container{max-width:1200px;margin:0 auto;padding:24px 20px 48px}
.about-card{background:var(--card);border-radius:var(--radius);box-shadow:var(--shadow);padding:16px 20px;margin-bottom:16px;font-size:13px;color:var(--text-2);line-height:1.8}
.about-card b{color:var(--text);font-weight:600}
.about-card .about-tag{display:inline-block;background:#f0f2f5;border-radius:4px;padding:2px 8px;margin-right:6px;font-size:12px;color:#555}

.search-bar{display:flex;gap:10px;margin-bottom:16px}
.search-bar input{flex:1;padding:11px 16px;font-size:15px;border:2px solid var(--border);border-radius:var(--radius);outline:none}
.search-bar input:focus{border-color:var(--primary)}
.search-bar button{padding:11px 28px;font-size:15px;background:var(--primary);color:#fff;border:none;border-radius:var(--radius);cursor:pointer}
.search-bar button:hover{background:var(--primary-dark)}

.filters{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}
.filter-btn{padding:5px 14px;font-size:13px;border:1px solid var(--border);background:var(--card);border-radius:16px;cursor:pointer;color:var(--text-2)}
.filter-btn:hover{border-color:var(--primary);color:var(--primary)}
.filter-btn.active{background:var(--primary);color:#fff;border-color:var(--primary)}
.filter-count{margin-left:4px;font-size:11px;opacity:.7}

.result-card{background:var(--card);border-radius:var(--radius);padding:16px 20px;margin-bottom:12px;box-shadow:var(--shadow);cursor:pointer;transition:box-shadow .2s}
.result-card:hover{box-shadow:0 4px 16px rgba(0,0,0,.1)}
.result-meta{font-size:13px;color:var(--text-2);margin-bottom:8px;display:flex;align-items:center;gap:8px;flex-wrap:nowrap;overflow:hidden}
.source-tag{padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;white-space:nowrap;background:#e3e7f0;color:var(--primary)}
.source-tag.jenkins{background:#ffe0e0;color:#c62828}
.source-tag.feishu{background:#e0e0ff;color:#3333aa}
.source-tag.yuque{background:#e0f5e0;color:#2a7a2a}
.source-tag.text{background:#fff3e0;color:#e65100}
.source-tag.pdf{background:#fce4ec;color:#c62828}
.source-tag.excel{background:#e8f5e9;color:#2e7d32}
.result-meta .file-path{color:#999;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.result-content{font-size:14px;line-height:1.7;color:#333;background:#fafbfc;border-radius:6px;padding:10px 14px;border-left:3px solid var(--primary);white-space:pre-wrap;word-break:break-word;max-height:200px;overflow-y:auto}
.result-content mark{background:var(--mark);padding:1px 3px;border-radius:2px;font-weight:500}
.result-score{font-size:11px;color:#bbb;white-space:nowrap}

.pagination{display:flex;justify-content:center;align-items:center;gap:6px;margin-top:24px}
.page-btn{padding:6px 12px;font-size:13px;border:1px solid var(--border);background:var(--card);border-radius:6px;cursor:pointer}
.page-btn:hover:not(:disabled){border-color:var(--primary);color:var(--primary)}
.page-btn.active{background:var(--primary);color:#fff;border-color:var(--primary)}
.page-btn:disabled{opacity:.4;cursor:not-allowed}
.page-info{font-size:13px;color:var(--text-2);margin:0 8px;white-space:nowrap}

/* ===== Dashboard ===== */
.dash-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:16px;margin-bottom:24px}
.dash-card{background:var(--card);border-radius:var(--radius);padding:20px;text-align:center;box-shadow:var(--shadow);cursor:pointer;transition:all .2s}
.dash-card:hover{transform:translateY(-2px);box-shadow:0 4px 16px rgba(0,0,0,.1)}
.dash-card .dash-icon{font-size:32px;margin-bottom:8px}
.dash-card .dash-num{font-size:28px;font-weight:700;color:var(--primary)}
.dash-card .dash-label{font-size:13px;color:var(--text-2);margin-top:4px}

/* ===== File Table ===== */
.file-table{width:100%;border-collapse:collapse;background:var(--card);border-radius:var(--radius);overflow:hidden;box-shadow:var(--shadow);table-layout:fixed}
.file-table th{background:#f5f6f8;padding:10px 12px;text-align:left;font-size:13px;color:var(--text-2);font-weight:600;border-bottom:1px solid var(--border);white-space:nowrap}
.file-table td{padding:8px 12px;font-size:13px;border-bottom:1px solid #f0f0f0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.file-table tr:hover{background:#fafbfc}
.file-table .col-cb{width:5%;text-align:center}.file-table .col-name{width:25%}.file-table .col-source{width:9%}
.file-table .col-chunks{width:7%}.file-table .col-time{width:14%}.file-table .col-path{width:30%}.file-table .col-action{width:10%}
.file-table .file-title{font-weight:500;color:var(--primary);cursor:pointer}
.file-table .remove-btn{color:#e53935;cursor:pointer;border:1px solid #ffcdd2;background:#fff;border-radius:4px;font-size:12px;padding:3px 10px;transition:all .2s}
.file-table .remove-btn:hover{background:#e53935;color:#fff;border-color:#e53935}
/* 进度条旁的「终止」按钮（上传 / 索引目录共用） */
.cancel-btn{color:#e53935;cursor:pointer;border:1px solid #ffcdd2;background:#fff;border-radius:4px;font-size:12px;padding:3px 10px;transition:all .2s;white-space:nowrap}
.cancel-btn:hover:not(:disabled){background:#e53935;color:#fff;border-color:#e53935}
.cancel-btn:disabled{opacity:.6;cursor:default}
.file-table tr.selected{background:#eef2ff}
.file-table .col-cb input[type=checkbox]{cursor:pointer}

/* ===== Upload ===== */
.upload-card{background:var(--card);border-radius:var(--radius);box-shadow:var(--shadow);padding:24px;margin-bottom:16px}
.upload-area{border:2px dashed var(--border);border-radius:var(--radius);padding:36px;text-align:center;cursor:pointer;transition:all .2s}
.upload-area:hover{border-color:var(--primary);background:#f8faff}
.upload-area .upload-icon{font-size:36px;margin-bottom:8px}
.upload-area .upload-text{font-size:14px;color:var(--text-2)}
.upload-area.dragover{border-color:var(--primary);background:#eef2ff}
#file-input,#folder-input{display:none}
.upload-buttons{display:flex;gap:10px;justify-content:center;margin-top:16px}
.upload-buttons .action-btn{padding:8px 20px;font-size:14px}
.local-dir-row{display:flex;gap:8px;justify-content:center;align-items:center;margin-top:14px;flex-wrap:wrap}
.local-dir-input{width:min(420px,100%);padding:8px 12px;border:1px solid var(--border);border-radius:6px;font-size:13px;outline:none;transition:border-color .2s}
.local-dir-input:focus{border-color:var(--primary)}
.local-dir-row .action-btn{padding:8px 18px;font-size:14px;white-space:nowrap}
.local-dir-tip{text-align:center;font-size:12px;color:#aaa;margin-top:8px;line-height:1.6}

/* ===== 知识图谱 ===== */
.kg-card{background:var(--card);border-radius:var(--radius);box-shadow:var(--shadow);padding:16px 20px;margin-bottom:16px}
.kg-toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.kg-view-switch{display:flex;border:1px solid var(--border);border-radius:6px;overflow:hidden;flex:none}
.kg-view{padding:7px 14px;font-size:13px;border:none;background:#fff;color:var(--text-2);cursor:pointer;white-space:nowrap}
.kg-view.active{background:var(--primary);color:#fff}
.kg-graph-card{background:var(--card);border-radius:var(--radius);box-shadow:var(--shadow);padding:12px 14px;margin-bottom:16px}
.kg-graph-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:13px;color:var(--text);margin-bottom:8px}
.kg-legend{margin-left:auto;display:flex;gap:10px;flex-wrap:wrap}
.kg-legend span{display:inline-flex;align-items:center;gap:4px;font-size:12px;color:var(--text-2)}
.kg-legend i{width:9px;height:9px;border-radius:50%;display:inline-block}
#kg-graph{width:100%;height:460px;background:#fbfcfe;border:1px solid var(--border);border-radius:8px}
.kg-path-bar{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:8px;font-size:12px;color:var(--text-2)}
.kg-path-bar .action-btn{padding:5px 12px;font-size:12px}
.kg-path-arrow{color:#aaa}
.kg-hit-box{display:flex;align-items:center;gap:6px;flex-wrap:wrap;background:#f7f9fc;border:1px solid var(--border);border-radius:8px;padding:8px 12px;margin-bottom:12px}
.kg-hit-title{font-size:12px;color:var(--text-2);white-space:nowrap;margin-right:2px}
.kg-merge-box{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px}
.kg-merge-box .kg-input{flex:1;min-width:120px}
@media(max-width:900px){div#kg-graph{height:360px}.kg-legend{margin-left:0}}
.kg-input{flex:1;min-width:220px;padding:8px 12px;border:1px solid var(--border);border-radius:6px;font-size:13px;outline:none}
.kg-input:focus{border-color:var(--primary)}
.kg-select{padding:8px 10px;border:1px solid var(--border);border-radius:6px;font-size:13px;background:#fff}
.kg-stats{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.kg-stat{background:#f7f9fc;border:1px solid var(--border);border-radius:8px;padding:5px 11px;font-size:12.5px;color:var(--text-2);white-space:nowrap}
.kg-stat b{color:var(--text);font-size:14px;margin-right:3px}
.kg-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;align-items:start}
@media(max-width:900px){.kg-layout{grid-template-columns:1fr}}
.kg-panel{background:var(--card);border-radius:var(--radius);box-shadow:var(--shadow);padding:14px 16px;display:flex;flex-direction:column;max-height:calc(100vh - 300px)}
@media(max-width:900px){.kg-panel{max-height:none}}
.kg-panel-title{flex:none;font-size:14px;font-weight:600;color:var(--text);padding-bottom:10px;border-bottom:1px solid var(--border);margin-bottom:0;display:flex;align-items:center;gap:6px}
.kg-scroll{flex:1;overflow-y:auto;min-height:160px;padding-top:6px}
.kg-panel .pagination{flex:none;margin-top:10px;padding-top:10px;border-top:1px solid var(--border)}
.kg-item{padding:8px 6px;border-bottom:1px solid #f0f0f0;cursor:pointer;display:flex;align-items:center;gap:8px;font-size:13px;border-radius:6px}
.kg-item:hover{background:#f5f8ff}
.kg-item.active{background:#eef2ff}
.kg-item .kg-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.kg-tag{font-size:11px;border-radius:4px;padding:1px 6px;background:#e8eefb;color:var(--primary);white-space:nowrap;flex:none}
.kg-tag.type-dir{background:#eef1f6;color:#5a6b85}
.kg-tag.type-file{background:#e3e7f0;color:var(--primary)}
.kg-tag.type-section{background:#e8f5e9;color:#2e7d32}
.kg-tag.type-person{background:#ffe9e6;color:#c62828}
.kg-tag.type-system{background:#e6e0ff;color:#4a3fa5}
.kg-tag.type-term{background:#fff3e0;color:#e65100}
.kg-meta{font-size:12px;color:#999;white-space:nowrap;flex:none}
.kg-detail{font-size:13px;color:var(--text-2);line-height:1.8;word-break:break-all}
.kg-empty{text-align:center;color:#aaa;font-size:13px;padding:28px 12px;line-height:1.8}
.kg-empty .icon{font-size:26px;display:block;margin-bottom:6px}
.kg-chip{display:inline-flex;align-items:center;gap:4px;background:#f4f6fa;border:1px solid var(--border);border-radius:14px;padding:2px 10px;margin:0 6px 6px 0;font-size:12px;color:var(--text-2)}
.kg-chip b{color:var(--primary);font-weight:600}
.kg-detail .kg-sub{font-weight:600;color:var(--text);margin:10px 0 4px;font-size:12.5px}
.kg-link{color:var(--primary);cursor:pointer;text-decoration:underline}
.kg-mention{padding:6px 0;border-bottom:1px dashed #eee;cursor:pointer}
.kg-mention:hover{background:#fafbff}
.upload-progress{margin-bottom:12px}
.upload-progress-bar{background:#e0e0e0;border-radius:4px;height:6px;overflow:hidden}
.upload-progress-fill{background:var(--primary);height:100%;transition:width .3s}

.empty{text-align:center;padding:48px 20px;color:#999}.empty .icon{font-size:40px;margin-bottom:10px}
.site-footer{max-width:1200px;margin:0 auto;padding:14px 20px 28px;text-align:center;color:#8a94a6;font-size:12px;border-top:1px solid var(--border)}
.site-footer a{color:var(--primary);text-decoration:none}
.site-footer a:hover{text-decoration:underline}
.actions-bar{display:flex;gap:8px;margin-bottom:16px;align-items:center}
.file-stats{margin-left:auto;font-size:13px;color:var(--text-2);white-space:nowrap}
.action-btn{padding:6px 14px;font-size:13px;border:1px solid var(--border);background:var(--card);border-radius:6px;cursor:pointer;color:var(--text-2)}
.action-btn:hover{background:#f5f5f5}
.action-btn.danger{color:#e53935;border-color:#ffcdd2}
.action-btn.danger:hover{background:#ffebee}

.toast{position:fixed;top:20px;right:20px;background:#333;color:#fff;padding:12px 20px;border-radius:8px;font-size:14px;z-index:9999;opacity:0;transition:opacity .3s;max-width:400px}
.toast.show{opacity:1}.toast.error{background:#c62828}.toast.success{background:#2e7d32}
.confirm-overlay{position:fixed;inset:0;background:rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;z-index:10000;opacity:0;transition:opacity .2s;pointer-events:none}
.confirm-overlay.show{opacity:1;pointer-events:auto}
.confirm-box{background:var(--card);border-radius:12px;padding:28px 32px;min-width:320px;max-width:440px;box-shadow:0 8px 32px rgba(0,0,0,.15);transform:scale(.9);transition:transform .2s}
.confirm-overlay.show .confirm-box{transform:scale(1)}
.confirm-box .confirm-msg{font-size:15px;color:var(--text-1);line-height:1.6;margin-bottom:24px;text-align:center}
.confirm-box .confirm-btns{display:flex;gap:12px;justify-content:center}
.confirm-box .confirm-btn{padding:8px 24px;border-radius:8px;border:none;font-size:14px;cursor:pointer;transition:all .15s}
.confirm-box .btn-cancel{background:#e8e8e8;color:var(--text-2)}
.confirm-box .btn-cancel:hover{background:#ddd}
.confirm-box .btn-ok{background:var(--primary);color:#fff}
.confirm-box .btn-ok:hover{opacity:.9}

.modal-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.5);z-index:9998;display:none;justify-content:center;align-items:center}
.modal-overlay.show{display:flex !important}
.modal{background:#fff;border-radius:12px;width:80%;max-width:800px;max-height:80vh;display:flex;flex-direction:column;overflow:hidden}
.modal-header{padding:16px 20px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center}
.modal-header h3{font-size:16px;font-weight:500}
.modal-close{cursor:pointer;font-size:20px;color:#999;border:none;background:none}
.modal-body{padding:20px;overflow-y:auto;flex:1;white-space:pre-wrap;font-size:14px;line-height:1.8;color:#333}
.modal-body mark{background:var(--mark);padding:1px 3px;border-radius:2px}
.modal-actions{padding:12px 20px;border-top:1px solid var(--border);display:flex;gap:8px}
</style>
</head>
<body>

<div class="header">
  <div class="header-content">
    <div class="brand">
      <h1><span class="icon">📚</span>知寻<span class="en">KnowSeek</span></h1>
      <div class="subtitle">纯本地文档全文检索 · 支持 Word / PDF / Excel / 文本 / Markdown</div>
      <div class="tagline">
        <span class="tag">SQLite FTS5</span><span class="tag">jieba 分词</span><span class="tag">BM25 排序</span><span class="tag">知识图谱</span>
        <span class="muted">不联网 · 不依赖大模型 · 数据只留在本机</span>
      </div>
    </div>
  </div>
</div>

<div class="nav-tabs" id="nav-tabs">
  <button class="nav-tab active" data-tab="dashboard">📊 仪表盘</button>
  <button class="nav-tab" data-tab="search">🔍 搜索</button>
  <button class="nav-tab" data-tab="kg">🕸 知识图谱</button>
  <button class="nav-tab" data-tab="files">📁 文件列表</button>
  <button class="nav-tab" data-tab="upload">📤 上传文件</button>
</div>

<div class="container">

  <!-- ===== Dashboard Tab ===== -->
  <div id="tab-dashboard">
    <div class="about-card">
      <div><b>知寻（KnowSeek）</b>是一个纯本地的文档全文检索工具：索引本机目录下的 Word / PDF / Excel / 文本 / Markdown，输入关键词即可秒级定位到文档出处，并可直接打开原文件。</div>
      <div style="margin-top:6px">
        <span class="about-tag">SQLite FTS5 全文索引</span><span class="about-tag">jieba 中文分词</span><span class="about-tag">BM25 相关性排序</span><span class="about-tag">MD5 增量同步</span>
        全部数据保存在本机，不联网、不依赖大模型。
      </div>
    </div>
    <div class="dash-grid" id="dash-grid"></div>
    <div id="dash-recent"></div>
  </div>

  <!-- ===== Search Tab ===== -->
  <div id="tab-search" style="display:none">
    <div class="search-bar">
      <input type="text" id="keyword" placeholder="输入关键词搜索，点击结果可查看原文..." onkeydown="if(event.key==='Enter')doSearch(1)">
      <button onclick="doSearch(1)">搜索</button>
      <button class="action-btn" onclick="resetSearch()" style="white-space:nowrap">重置</button>
    </div>
    <div class="filters" id="filter-bar"></div>
    <div id="search-results">
      <div class="empty"><div class="icon">🔍</div><div>输入关键词开始搜索</div></div>
    </div>
    <div id="pagination" class="pagination"></div>
  </div>

  <!-- ===== Files Tab ===== -->
  <div id="tab-files" style="display:none">
    <div class="actions-bar">
      <button class="action-btn" onclick="loadFiles(currentFilePage)">🔄 刷新</button>
      <button class="action-btn" onclick="syncIndex()">⚡ 同步索引</button>
      <button class="action-btn danger" onclick="batchRemove()" id="batch-remove-btn" style="display:none">🗑 批量移除 (<span id="sel-count">0</span>)</button>
      <span class="file-stats" id="file-stats"></span>
    </div>
    <table class="file-table">
      <thead>
        <tr>
          <th class="col-cb"><input type="checkbox" id="select-all" onchange="toggleAll(this)"></th>
          <th class="col-name">文件名</th>
          <th class="col-source">来源</th>
          <th class="col-chunks">片段</th>
          <th class="col-time">索引时间</th>
          <th class="col-path">路径</th>
          <th class="col-action">操作</th>
        </tr>
      </thead>
      <tbody id="file-list-body"></tbody>
    </table>
    <div id="file-pagination" class="pagination"></div>
  </div>

  <!-- ===== Upload Tab ===== -->
  <div id="tab-upload" style="display:none">
    <div class="upload-card">
      <div class="upload-area" id="upload-area">
        <div class="upload-icon">📎</div>
        <div class="upload-text">点击选择文件或拖拽到此处</div>
        <div class="upload-text" style="margin-top:8px;font-size:12px;color:#aaa">支持 .doc .docx .pdf .xlsx .txt .md</div>
      </div>
      <div class="upload-buttons">
        <button class="action-btn" onclick="document.getElementById('file-input').click()">📋 选择文件</button>
        <button class="action-btn" onclick="document.getElementById('folder-input').click()">📂 选择文件夹</button>
      </div>
      <div class="local-dir-row">
        <input type="text" id="local-dir-path" class="local-dir-input"
               placeholder="本机目录绝对路径，如 D:\docs（回车即可索引）">
        <button class="action-btn" id="local-dir-btn" onclick="indexLocalDir()">🚀 索引该目录</button>
      </div>
      <div class="local-dir-tip">推荐：直接索引本机目录，由服务端扫描，不上传、不复制文件，也不会出现"上传该目录下所有文件"的确认弹窗</div>
    </div>
    <input type="file" id="file-input" multiple accept=".docx,.txt,.md,.doc,.pdf,.xlsx,.xls">
    <input type="file" id="folder-input" webkitdirectory directory multiple>
    <div id="upload-results"></div>
  </div>

  <!-- ===== 知识图谱 Tab ===== -->
  <div id="tab-kg" style="display:none">
    <div class="kg-card">
      <div class="kg-toolbar">
        <div class="kg-view-switch">
          <button class="kg-view active" id="kg-view-list" onclick="setKgView('list')">🗂 列表视图</button>
          <button class="kg-view" id="kg-view-graph" onclick="setKgView('graph')">🕸 图视图</button>
        </div>
        <input type="text" id="kg-q" class="kg-input" placeholder="搜索实体名称（目录 / 文档 / 章节 / 人物 / 系统 / 术语）"
               onkeydown="if(event.key==='Enter')loadKgView()">
        <select id="kg-type" class="kg-select" onchange="loadKgView()">
          <option value="">全部类型</option>
          <option value="dir">目录</option>
          <option value="file">文档</option>
          <option value="section">章节</option>
          <option value="person">人物</option>
          <option value="system">系统 / 机构</option>
          <option value="term">术语 / 专名</option>
        </select>
        <select id="kg-top" class="kg-select" onchange="loadKgView()">
          <option value="60">Top 60</option>
          <option value="120" selected>Top 120</option>
          <option value="200">Top 200</option>
          <option value="300">Top 300</option>
        </select>
        <button class="action-btn" onclick="loadKgView()">🔍 搜索</button>
        <button class="action-btn" onclick="applyKgAlias()">🔀 应用别名</button>
        <button class="action-btn" onclick="rebuildKg()">🛠 重建图谱</button>
      </div>
      <div id="kg-stats" class="kg-stats"></div>
    </div>

    <div class="kg-graph-card" id="kg-graph-card" style="display:none">
      <div class="kg-graph-head">
        <span>🕸 关系图（滚轮缩放 · 拖拽布局 · 点击节点看详情）</span>
        <div class="kg-legend" id="kg-legend"></div>
      </div>
      <div id="kg-graph"></div>
      <div class="kg-path-bar" id="kg-path-bar"></div>
    </div>

    <div class="kg-layout">
      <div class="kg-panel">
        <div class="kg-panel-title">🗂 实体列表</div>
        <div class="kg-scroll" id="kg-list"></div>
        <div id="kg-pagination" class="pagination"></div>
      </div>
      <div class="kg-panel">
        <div class="kg-panel-title">🔎 实体详情</div>
        <div class="kg-scroll kg-detail" id="kg-detail"></div>
      </div>
    </div>
  </div>

</div>

<div class="site-footer">
  🐙 项目托管：<a href="https://github.com/simonking-ws/knowseek" target="_blank" rel="noopener">https://github.com/simonking-ws/knowseek</a>
</div>

<div class="modal-overlay" id="modal-overlay">
  <div class="modal">
    <div class="modal-header"><h3 id="modal-title">文件查看</h3><button class="modal-close" onclick="closeModal()">✕</button></div>
    <div class="modal-body" id="modal-body"></div>
    <div class="modal-actions" id="modal-actions" style="display:none">
      <button class="action-btn" onclick="openNativeFile()">📁 在系统中打开</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>
<div class="confirm-overlay" id="confirm-overlay">
  <div class="confirm-box" id="confirm-box">
    <div class="confirm-msg" id="confirm-msg"></div>
    <div class="confirm-btns">
      <button class="confirm-btn btn-cancel" id="confirm-cancel-btn" onclick="resolveDialog(false)">取消</button>
      <button class="confirm-btn btn-ok" id="confirm-ok-btn" onclick="resolveDialog(true)">确定</button>
    </div>
  </div>
</div>

<script src="/static/echarts.min.js"></script>
<script>
const SOURCE_LABELS = {word:'Word', text:'TXT/MD', feishu:'飞书', yuque:'语雀', jenkins:'Jenkins', pdf:'PDF', excel:'Excel'};
const SOURCE_ICONS = {word:'📘', text:'📝', feishu:'🐦', yuque:'🌿', jenkins:'🤖', pdf:'📕', excel:'📗'};

let currentFilter = '';
let currentPage = 1;
let currentKeyword = '';
let currentFilePage = 1;
let selectedFiles = new Set();
let modalFilePath = '';
const PER_PAGE = 10;
const UPLOAD_PREFIX = 'upload://';   // 上传件：只有索引、磁盘上没有原文件
function prettyPath(p) {
  let s = p || '';
  return s.startsWith(UPLOAD_PREFIX) ? '☁ ' + s.slice(UPLOAD_PREFIX.length) : s;
}

// ===== Tab 切换 =====
document.getElementById('nav-tabs').addEventListener('click', e => {
  let btn = e.target.closest('.nav-tab');
  if (!btn) return;
  let tab = btn.dataset.tab;
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  ['dashboard','search','files','upload','kg'].forEach(t => {
    document.getElementById('tab-'+t).style.display = t === tab ? '' : 'none';
  });
  if (tab === 'files') loadFiles(1);
  if (tab === 'kg') loadKgView();
  if (tab === 'dashboard') loadDashboard();
  if (tab === 'search') document.getElementById('keyword').focus();
});

// ===== Toast =====
function showToast(msg, type='') {
  let t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show ' + type;
  setTimeout(() => t.className = 'toast ' + type, 3000);
}

// ===== Confirm / Alert =====
let _dialogResolve = null;
let _dialogMode = 'confirm';
function showConfirm(msg) {
  return new Promise(resolve => {
    _dialogResolve = resolve;
    _dialogMode = 'confirm';
    document.getElementById('confirm-msg').textContent = msg;
    document.getElementById('confirm-cancel-btn').style.display = '';
    document.getElementById('confirm-ok-btn').textContent = '确定';
    document.getElementById('confirm-overlay').classList.add('show');
  });
}
function showAlert(msg) {
  return new Promise(resolve => {
    _dialogResolve = resolve;
    _dialogMode = 'alert';
    document.getElementById('confirm-msg').textContent = msg;
    document.getElementById('confirm-cancel-btn').style.display = 'none';
    document.getElementById('confirm-ok-btn').textContent = '知道了';
    document.getElementById('confirm-overlay').classList.add('show');
  });
}
function resolveDialog(ok) {
  document.getElementById('confirm-overlay').classList.remove('show');
  if (_dialogResolve) {
    if (_dialogMode === 'alert') _dialogResolve();
    else _dialogResolve(ok);
    _dialogResolve = null;
  }
}

// ===== Dashboard =====
async function loadDashboard() {
  let resp = await fetch('/api/stats');
  let data = await resp.json();

  let grid = document.getElementById('dash-grid');
  let cards = [
    {icon:'📄', num:data.doc_count, label:'文档总数', filter:'', tab:'files'},
    {icon:'📝', num:data.chunk_count, label:'片段总数', filter:'', tab:''},
  ];
  if (data.by_source) {
    for (let [k,v] of Object.entries(data.by_source)) {
      cards.push({icon:SOURCE_ICONS[k]||'📋', num:v, label:SOURCE_LABELS[k]||k, filter:k, tab:''});
    }
  }
  grid.innerHTML = cards.map(c =>
    `<div class="dash-card" ${c.tab==='files'?'onclick="switchToFiles()"':c.filter?`onclick="dashFilter('${c.filter}')"`:''} ${!c.tab && !c.filter?'style="cursor:default"':''}>
      <div class="dash-icon">${c.icon}</div>
      <div class="dash-num">${c.num}</div>
      <div class="dash-label">${c.label}</div>
    </div>`
  ).join('');

  // 最近索引文件
  let fresp = await fetch('/api/files?page=1&per_page=5');
  let fdata = await fresp.json();
  let recent = document.getElementById('dash-recent');
  if (fdata.files && fdata.files.length) {
    recent.innerHTML = `<h3 style="font-size:15px;margin-bottom:12px;color:var(--text-2)">最近索引</h3>` +
      fdata.files.map(f => {
        let sc = f.source_type || 'word';
        let label = SOURCE_LABELS[f.source_type] || f.source_type;
        return `<div style="background:var(--card);border-radius:8px;padding:10px 14px;margin-bottom:8px;display:flex;align-items:center;gap:10px;box-shadow:var(--shadow)">
          <span class="source-tag ${sc}">${label}</span>
          <span style="flex:1;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer;color:var(--primary)" onclick="openFileViewer('${escJS(f.file_path)}',0,'')" title="${escJS(f.file_path)}">${esc(f.title)}</span>
          <span style="font-size:12px;color:#999;white-space:nowrap">${f.chunk_count} 片段</span>
        </div>`;
      }).join('');
  }

  // 更新 tab badge（已移除）
}

function dashFilter(type) {
  // 切换到搜索 tab 并设置过滤器
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.querySelector('[data-tab="search"]').classList.add('active');
  document.getElementById('tab-dashboard').style.display = 'none';
  document.getElementById('tab-search').style.display = '';
  document.getElementById('tab-files').style.display = 'none';
  document.getElementById('tab-upload').style.display = 'none';
  document.getElementById('tab-kg').style.display = 'none';
  currentFilter = type;
  renderFilters();
}

function switchToFiles() {
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.querySelector('[data-tab="files"]').classList.add('active');
  document.getElementById('tab-dashboard').style.display = 'none';
  document.getElementById('tab-search').style.display = 'none';
  document.getElementById('tab-files').style.display = '';
  document.getElementById('tab-upload').style.display = 'none';
  document.getElementById('tab-kg').style.display = 'none';
  loadFiles(1);
}

// ===== 筛选 =====
function renderFilters() {
  let bar = document.getElementById('filter-bar');
  let types = [
    {v:'', l:'全部'},
    {v:'word', l:'Word'},
    {v:'pdf', l:'PDF'},
    {v:'excel', l:'Excel'},
    {v:'text', l:'文本/MD'},
    {v:'feishu', l:'飞书'},
    {v:'yuque', l:'语雀'},
    {v:'jenkins', l:'Jenkins'},
  ];
  bar.innerHTML = types.map(t =>
    `<button class="filter-btn ${currentFilter===t.v?'active':''}" onclick="setFilter('${t.v}')">${t.l}</button>`
  ).join('');
}

function setFilter(type) {
  currentFilter = type;
  renderFilters();
  if (currentKeyword) doSearch(1);
}

// ===== 搜索 =====
function resetSearch() {
  document.getElementById('keyword').value = '';
  currentKeyword = '';
  currentFilter = '';
  currentPage = 1;
  renderFilters();
  document.getElementById('search-results').innerHTML = '<div class="empty"><div class="icon">🔍</div><div>输入关键词开始搜索</div></div>';
  document.getElementById('pagination').innerHTML = '';
  document.getElementById('keyword').focus();
}

async function doSearch(page) {
  currentPage = page;
  let kw = document.getElementById('keyword').value.trim();
  if (!kw) return;
  currentKeyword = kw;

  let url = `/api/search?q=${encodeURIComponent(kw)}&page=${page}&per_page=${PER_PAGE}`;
  if (currentFilter) url += `&source_type=${currentFilter}`;

  let resp = await fetch(url);
  let data = await resp.json();

  renderResults(data.results, kw, data.entities || []);
  renderPagination('pagination', data.total, page, PER_PAGE, 'doSearch');
}

function renderResults(results, kw, entities) {
  let c = document.getElementById('search-results');
  if (!results.length) {
    c.innerHTML = '<div class="empty"><div class="icon">😔</div><div>没有找到匹配结果</div></div>';
    return;
  }
  let head = '';
  if (entities && entities.length) {
    head = '<div class="kg-hit-box"><span class="kg-hit-title">🕸 命中实体</span>'
      + entities.map(e =>
          `<span class="kg-chip" title="${esc(KG_LABEL[e.type] || e.type)} · 命中 ${e.count} 次">`
          + `<span class="kg-link" onclick="focusKgEntity(${e.id}, '${escJS(e.name)}')">${esc(e.name)}</span>`
          + ` <b>${e.count}</b></span>`).join('')
      + '</div>';
  }
  c.innerHTML = head + results.map(r => {
    let sc = r.source_type || 'word';
    let label = SOURCE_LABELS[r.source_type] || r.source_type;
    let loc = r.section_path ? `${r.section_path} · 段落 ${r.para_index}` : `段落 ${r.para_index}`;
    return `<div class="result-card" onclick="openFileViewer('${escJS(r.file_path)}',${r.para_index},'${escJS(kw)}')">
      <div class="result-meta">
        <span class="source-tag ${sc}">${label}</span>
        <strong>${esc(r.title)}</strong>
      </div>
      <div class="result-content">${r.highlighted}</div>
      <div class="result-meta" style="margin-top:6px">
        <span class="file-path" title="${escJS(r.file_path)}">${esc(prettyPath(r.file_path))}</span>
        <span>·</span><span style="white-space:nowrap">${esc(loc)}</span>
        <span class="result-score">BM25: ${r.score}</span>
        <span class="kg-link" title="在知识图谱中查看该文档" onclick="event.stopPropagation();focusInKg('${escJS(r.file_path)}')">🕸 图谱</span>
      </div>
    </div>`;
  }).join('');
}

// ===== File Viewer Modal =====
async function openFileViewer(filePath, paraIndex, keyword) {
  let modal = document.getElementById('modal-overlay');
  let title = document.getElementById('modal-title');
  let body = document.getElementById('modal-body');
  let actions = document.getElementById('modal-actions');

  let fname = filePath.split(/[\\/]/).pop();
  title.textContent = '📄 ' + fname;
  body.innerHTML = '<div style="text-align:center;color:#999;padding:20px">加载中...</div>';
  modal.classList.add('show');
  modalFilePath = filePath;

  let url = `/api/file_content?path=${encodeURIComponent(filePath)}&para=${paraIndex}`;
  if (keyword) url += `&keyword=${encodeURIComponent(keyword)}`;

  try {
    let resp = await fetch(url);
    let data = await resp.json();
    if (data.error) {
      body.innerHTML = `<div style="color:#c62828;padding:12px">${esc(data.error)}</div>`;
      actions.style.display = '';
    } else {
      body.innerHTML = data.html || esc(data.content || '');
      actions.style.display = '';
    }
  } catch(e) {
    body.innerHTML = `<div style="color:#c62828">加载失败: ${esc(e.message)}</div>`;
    actions.style.display = '';
  }
}

function openNativeFile() {
  if (modalFilePath) {
    fetch('/api/open_file', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path: modalFilePath})})
    .then(r => r.json()).then(d => {
      if (!d.ok) showToast('打开失败: ' + (d.error||''), 'error');
    });
  }
}

function closeModal() { document.getElementById('modal-overlay').classList.remove('show'); }

document.getElementById('modal-overlay').addEventListener('click', e => { if (e.target === e.currentTarget) closeModal(); });

// ===== 分页 =====
function renderPagination(containerId, total, page, perPage, callback) {
  let c = document.getElementById(containerId);
  let tp = Math.ceil(total / perPage);
  if (tp <= 1) { c.innerHTML = `<span class="page-info">共 ${total} 条</span>`; return; }
  let html = `<button class="page-btn" ${page<=1?'disabled':''} onclick="${callback}(${page-1})">上一页</button>`;
  let s = Math.max(1,page-2), e = Math.min(tp,page+2);
  if (s>1){html+=`<button class="page-btn" onclick="${callback}(1)">1</button>`;if(s>2)html+='<span class="page-info">...</span>';}
  for(let i=s;i<=e;i++) html+=`<button class="page-btn ${i===page?'active':''}" onclick="${callback}(${i})">${i}</button>`;
  if(e<tp){if(e<tp-1)html+='<span class="page-info">...</span>';html+=`<button class="page-btn" onclick="${callback}(${tp})">${tp}</button>`;}
  html += `<button class="page-btn" ${page>=tp?'disabled':''} onclick="${callback}(${page+1})">下一页</button>`;
  html += `<span class="page-info">${total} 条 / ${tp} 页</span>`;
  c.innerHTML = html;
}

// ===== 文件列表 =====
async function loadFiles(page) {
  currentFilePage = page;
  selectedFiles.clear();
  updateBatchBtn();

  let url = `/api/files?page=${page}&per_page=${PER_PAGE}`;
  if (currentFilter) url += `&source_type=${currentFilter}`;

  let resp = await fetch(url);
  let data = await resp.json();

  // 更新统计信息（居右展示，仅总文档数）
  let statsResp = await fetch('/api/stats');
  let statsData = await statsResp.json();
  let statsEl = document.getElementById('file-stats');
  if (statsEl) {
    statsEl.textContent = `📄 ${statsData.doc_count} 文档 · 📝 ${statsData.chunk_count} 片段`;
  }

  let tbody = document.getElementById('file-list-body');
  if (!data.files.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#999;padding:24px">暂无索引文档</td></tr>';
  } else {
    tbody.innerHTML = data.files.map(f => {
      let sc = f.source_type || 'word';
      let label = SOURCE_LABELS[f.source_type] || f.source_type;
      let fname = esc(f.title || f.file_path.split(/[\\/]/).pop());
      return `<tr id="file-row-${f.id}">
        <td class="col-cb"><input type="checkbox" data-path="${esc(f.file_path)}" onchange="toggleSelect(this)"></td>
        <td class="col-name file-title" title="${escJS(f.title||'')}" onclick="openFileViewer('${escJS(f.file_path)}',0,'')">${fname}</td>
        <td class="col-source"><span class="source-tag ${sc}">${label}</span></td>
        <td class="col-chunks">${f.chunk_count}</td>
        <td class="col-time" title="${escJS(f.indexed_at||'')}">${esc(f.indexed_at||'')}</td>
        <td class="col-path file-path" title="${escJS(f.file_path)}">${esc(prettyPath(f.file_path))}</td>
        <td class="col-action"><button class="remove-btn" onclick="event.stopPropagation();removeFile('${escJS(f.file_path)}')">移除</button></td>
      </tr>`;
    }).join('');
  }
  renderPagination('file-pagination', data.total, page, PER_PAGE, 'loadFiles');
}

function toggleSelect(cb) {
  if (cb.checked) selectedFiles.add(cb.dataset.path);
  else selectedFiles.delete(cb.dataset.path);
  cb.closest('tr').classList.toggle('selected', cb.checked);
  syncSelectAll();
}

function toggleAll(selectAll) {
  let cbs = document.querySelectorAll('#file-list-body input[type=checkbox]');
  cbs.forEach(cb => {
    cb.checked = selectAll.checked;
    if (selectAll.checked) selectedFiles.add(cb.dataset.path);
    else selectedFiles.delete(cb.dataset.path);
    cb.closest('tr').classList.toggle('selected', cb.checked);
  });
  updateBatchBtn();
}

function syncSelectAll() {
  let cbs = document.querySelectorAll('#file-list-body input[type=checkbox]');
  let all = cbs.length > 0;
  cbs.forEach(cb => { if (!cb.checked) all = false; });
  document.getElementById('select-all').checked = all;
  updateBatchBtn();
}

function updateBatchBtn() {
  let btn = document.getElementById('batch-remove-btn');
  let count = document.getElementById('sel-count');
  if (selectedFiles.size > 0) { btn.style.display = ''; count.textContent = selectedFiles.size; }
  else btn.style.display = 'none';
}

async function batchRemove() {
  if (!selectedFiles.size) return;
  if (!await showConfirm(`确定移除 ${selectedFiles.size} 个文件的索引？`)) return;
  let resp = await fetch('/api/files/batch', {
    method: 'DELETE', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({file_paths: [...selectedFiles]})
  });
  let data = await resp.json();
  if (data.ok) { showToast(`已移除 ${data.removed} 个文件`, 'success'); loadFiles(currentFilePage); showStats(); }
  else showToast('移除失败', 'error');
}

async function removeFile(filePath) {
  if (!await showConfirm('确定移除该文件的索引？')) return;
  let resp = await fetch('/api/files', {method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({file_path:filePath})});
  let data = await resp.json();
  if (data.ok) { showToast('已移除', 'success'); loadFiles(currentFilePage); showStats(); }
  else showToast('移除失败: '+(data.error||''), 'error');
}

// ===== 上传 =====
const uploadArea = document.getElementById('upload-area');
const fileInput = document.getElementById('file-input');
const folderInput = document.getElementById('folder-input');

['dragover','dragenter'].forEach(e => uploadArea.addEventListener(e, ev => { ev.preventDefault(); uploadArea.classList.add('dragover'); }));
['dragleave','drop'].forEach(e => uploadArea.addEventListener(e, ev => { ev.preventDefault(); uploadArea.classList.remove('dragover'); }));
uploadArea.addEventListener('drop', ev => handleFiles(ev.dataTransfer.files));
fileInput.addEventListener('change', ev => { handleFiles(ev.target.files); fileInput.value = ''; });
folderInput.addEventListener('change', ev => { handleFiles(ev.target.files); folderInput.value = ''; });

// ===== 索引本机目录（服务端直接扫描，不经浏览器上传）=====
const localDirInput = document.getElementById('local-dir-path');
const localDirBtn = document.getElementById('local-dir-btn');
if (localDirInput) {
  localDirInput.addEventListener('keydown', ev => { if (ev.key === 'Enter') indexLocalDir(); });
}

async function indexLocalDir() {
  const p = (localDirInput.value || '').trim();
  if (!p) { showToast('请先填写本机目录路径', 'error'); localDirInput.focus(); return; }
  localDirBtn.disabled = true;
  try {
    // 预检：目录下没有可索引的文件时直接终止，不再解析入库
    localDirBtn.textContent = '🔍 检查中...';
    let pv = await fetch('/api/scan_preview', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({path: p})
    }).then(r => r.json());
    if (pv.error) { showToast(pv.error, 'error'); return; }
    if (!pv.count) {
      showToast('该目录下没有可索引的文件，已终止', 'error');
      let r0 = document.getElementById('upload-results');
      r0.innerHTML = '';
      let tip = document.createElement('div');
      tip.style.cssText = 'color:#c62828;padding:8px 4px;font-size:13px;line-height:1.6;word-break:break-all';
      tip.textContent = '⛔ ' + pv.path + ' 下没有找到可索引的文件（支持 .doc .docx .pdf .xlsx .xls .txt .md），未执行索引';
      r0.appendChild(tip);
      return;
    }

    localDirBtn.textContent = '⏳ 索引中...';
    showToast('发现 ' + pv.count + ' 个可索引文件，开始索引...');
    let resp = await fetch('/api/index_dir', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({path: p})
    });
    let d = await resp.json();
    if (d.error) { showToast('索引失败: ' + d.error, 'error'); return; }

    // 进度条：服务端后台线程索引，前端每 500ms 拉一次进度
    let results = document.getElementById('upload-results');
    results.innerHTML = '';
    let progWrap = document.createElement('div');
    progWrap.className = 'upload-progress';
    progWrap.innerHTML = `<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
        <div style="flex:1;font-size:13px;color:#666;word-break:break-all" id="dir-prog-text">准备索引 ${pv.count} 个文件...</div>
        <button class="cancel-btn" id="dir-cancel-btn" onclick="cancelIndexDir()">⛔ 终止</button>
      </div>
      <div class="upload-progress-bar"><div class="upload-progress-fill" id="dir-prog-fill" style="width:0%"></div></div>`;
    results.appendChild(progWrap);

    await new Promise(resolve => {
      let timer = setInterval(async () => {
        let prog = await fetch('/api/index_progress').then(r => r.json());
        let pct = prog.total ? Math.round(prog.done / prog.total * 100) : (prog.finished ? 100 : 0);
        let fill = document.getElementById('dir-prog-fill');
        let text = document.getElementById('dir-prog-text');
        let cbtn = document.getElementById('dir-cancel-btn');
        if (fill) fill.style.width = pct + '%';
        if (text) {
          text.textContent = (prog.cancelling ? '正在终止... ' : '索引中 ')
            + `${prog.done}/${prog.total}（${pct}%）· 新增 ${prog.added} / 更新 ${prog.updated} / 未变更 ${prog.skipped}`
            + (prog.current ? ` — ${prog.current}` : '');
        }
        if (cbtn && prog.cancelling) { cbtn.disabled = true; cbtn.textContent = '⏹ 终止中'; }
        if (!prog.running) {
          clearInterval(timer);
          if (cbtn) cbtn.remove();
          finishIndexDir(prog, results);
          resolve();
        }
      }, 500);
    });
  } catch (err) {
    showToast('索引失败: ' + err, 'error');
  } finally {
    localDirBtn.disabled = false;
    localDirBtn.textContent = '🚀 索引该目录';
  }
}

async function cancelIndexDir() {
  let btn = document.getElementById('dir-cancel-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏹ 终止中'; }
  let d = await fetch('/api/index_cancel', {method:'POST'}).then(r => r.json());
  showToast(d.note || '已请求终止', 'error');
}

function finishIndexDir(d, results) {
  results.innerHTML = '';
  let div = document.createElement('div');
  div.style.cssText = 'color:#2e7d32;padding:8px 4px;font-size:13px;line-height:1.6;word-break:break-all';
  if (d.cancelled) {
    div.style.color = '#ef6c00';
    div.textContent = `⛔ 已终止索引: ${d.path || ''}（已处理 ${d.done}/${d.total}：新增 ${d.added} / 更新 ${d.updated} / 未变更 ${d.skipped}，已入库的会保留）`;
  } else {
    div.textContent = '✅ 已索引目录: ' + (d.path || '') + '（共 ' + d.total + ' 个文件：新增 ' + d.added + ' / 更新 ' + d.updated + ' / 未变更 ' + d.skipped + '）';
  }
  results.appendChild(div);

  let dirTip = document.createElement('div');
  dirTip.style.cssText = 'color:#666;padding:4px 4px 8px;font-size:12px;line-height:1.6;word-break:break-all';
  dirTip.textContent = '📌 该目录已写入 config.yaml 的 scan_dirs，后续点「🔄 同步」会自动增量更新；列表/搜索结果里显示的就是文件在本机的真实路径，可直接「📁 在系统中打开」。';
  results.appendChild(dirTip);

  let errs = d.errors || [];
  if (errs.length) {
    let eDiv = document.createElement('div');
    eDiv.style.cssText = 'color:#c62828;padding:8px 4px;font-size:13px;line-height:1.6;word-break:break-all';
    eDiv.textContent = '⚠️ 部分文件解析失败: ' + errs.slice(0, 10).join('; ') + (errs.length > 10 ? ('（共 ' + errs.length + ' 条）') : '');
    results.appendChild(eDiv);
  }
  showToast(d.cancelled
    ? `已终止: 已处理 ${d.done}/${d.total}，新增 ${d.added} | 更新 ${d.updated} | 跳过 ${d.skipped}`
    : `索引完成: 新增 ${d.added} | 更新 ${d.updated} | 跳过 ${d.skipped}`,
    d.cancelled ? 'error' : 'success');
  showStats();
}

async function handleFiles(fileList) {
  let allFiles = Array.from(fileList);
  if (!allFiles.length) { await showAlert('未选择任何文件'); return; }

  let files = allFiles.filter(f => {
    let ext = '.' + f.name.split('.').pop().toLowerCase();
    return ['.docx','.txt','.md','.doc','.pdf','.xlsx','.xls'].includes(ext);
  });

  let skipped = allFiles.length - files.length;

  // 没有可索引的文件：直接终止，不再弹统计框、不再建进度条
  if (!files.length) {
    await showAlert('没有需要索引的文件：选中的 ' + allFiles.length + ' 个文件均不是受支持的格式（.doc .docx .pdf .xlsx .xls .txt .md），已终止');
    return;
  }

  let results = document.getElementById('upload-results');
  let summary = skipped > 0 ? `（跳过 ${skipped} 个不支持的文件）` : '';
  results.innerHTML = '';
  let progWrap = document.createElement('div');
  progWrap.className = 'upload-progress';
  progWrap.innerHTML = `<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
      <div style="flex:1;font-size:13px;color:#666" id="prog-text">上传中 0/${files.length}${summary}...</div>
      <button class="cancel-btn" id="upload-cancel-btn" onclick="cancelUpload()">⛔ 终止</button>
    </div>
    <div class="upload-progress-bar"><div class="upload-progress-fill" id="prog-fill" style="width:0%"></div></div>`;
  results.appendChild(progWrap);
  let resultList = document.createElement('div');
  resultList.id = 'upload-result-list';
  results.appendChild(resultList);

  let progText = document.getElementById('prog-text');
  let progFill = document.getElementById('prog-fill');
  let cancelBtn = document.getElementById('upload-cancel-btn');

  uploadCancelled = false;
  uploadAbort = null;
  let ok = 0, fail = 0, dup = 0, done = 0;
  for (let i = 0; i < files.length; i++) {
    if (uploadCancelled) break;
    let formData = new FormData();
    formData.append('file', files[i]);
    progText.textContent = `上传 ${i+1}/${files.length}${summary} (✅${ok} 🔄${dup} ❌${fail}) - ${files[i].name}`;
    uploadAbort = new AbortController();
    try {
      let resp = await fetch('/api/upload', {method:'POST', body: formData, signal: uploadAbort.signal});
      let data = await resp.json();
      if (data.error) { fail++; appendResult(resultList, '❌', files[i].name, data.error, '#c62828'); }
      else if (data.duplicate) { dup++; appendResult(resultList, '🔄', files[i].name, '已存在，跳过', '#1565c0'); }
      else { ok++; appendResult(resultList, '✅', files[i].name, data.indexed + ' 片段', '#2e7d32'); }
    } catch(err) {
      if (uploadCancelled) break;                 // 用户主动终止：当前这个不再计入失败
      fail++; appendResult(resultList, '❌', files[i].name, '上传失败', '#c62828');
    }
    done = i + 1;
    progFill.style.width = Math.round(done / files.length * 100) + '%';
    progText.textContent = `上传 ${done}/${files.length}${summary} (✅${ok} 🔄${dup} ❌${fail})`;
    await new Promise(r => setTimeout(r, 0));
  }
  uploadAbort = null;
  if (cancelBtn) cancelBtn.remove();
  let tail = uploadCancelled ? `已终止 ${done}/${files.length}` : `上传完成 ${done}/${files.length}`;
  progText.textContent = `${tail}${summary} (✅${ok} 🔄${dup} ❌${fail})`;
  if (!uploadCancelled) progFill.style.width = '100%';
  showToast(uploadCancelled
    ? `已终止上传: 已完成 ${done}/${files.length}（${ok} 新增, ${dup} 跳过, ${fail} 失败）`
    : `上传完成: ${ok} 新增, ${dup} 跳过, ${fail} 失败`, uploadCancelled ? 'error' : (ok ? 'success' : 'error'));
  showStats();
}

let uploadCancelled = false;    // 用户点了「终止」
let uploadAbort = null;         // 当前上传请求的 AbortController
function cancelUpload() {
  uploadCancelled = true;
  if (uploadAbort) uploadAbort.abort();
  let btn = document.getElementById('upload-cancel-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏹ 终止中'; }
  showToast('已请求终止，当前文件传完即停止', 'error');
}

function appendResult(container, icon, filename, status, color) {
  let div = document.createElement('div');
  div.style.cssText = `color:${color};padding:8px 4px;border-bottom:1px solid #f0f0f0;display:flex;align-items:center;gap:10px;line-height:1.5;`;
  let iconSpan = document.createElement('span');
  iconSpan.textContent = icon;
  iconSpan.style.cssText = 'font-size:15px;flex-shrink:0;';
  let nameSpan = document.createElement('span');
  nameSpan.textContent = filename;
  nameSpan.style.cssText = 'flex:1;word-break:break-all;';
  let statusSpan = document.createElement('span');
  statusSpan.textContent = status;
  statusSpan.style.cssText = 'flex-shrink:0;font-size:13px;opacity:0.85;';
  div.appendChild(iconSpan);
  div.appendChild(nameSpan);
  div.appendChild(statusSpan);
  container.appendChild(div);
}

// ===== 知识图谱 =====
const KG_LABEL = {dir:'目录', file:'文档', section:'章节', person:'人物', system:'系统', term:'术语'};
const KG_COLOR = {dir:'#8a94a6', file:'#4a6fa5', section:'#2e7d32', person:'#c62828', system:'#6b5bd2', term:'#ef6c00'};
const KG_PRED = {contains:'包含', mentions:'提及', related_to:'共现'};
const KG_PER_PAGE = 10;     // 实体列表每页条数，超过即分页
let kgPage = 1;
let kgView = 'list';         // 默认列表视图
let kgChart = null;

function setKgView(v) {
  kgView = v;
  document.getElementById('kg-view-graph').classList.toggle('active', v === 'graph');
  document.getElementById('kg-view-list').classList.toggle('active', v === 'list');
  document.getElementById('kg-graph-card').style.display = v === 'graph' ? '' : 'none';
  loadKgView();
}

function loadKgView() {
  loadKgStats();
  loadKgEntities(1);          // 列表始终加载：图视图下右侧详情/列表不再空白
  if (kgView === 'graph') loadKgGraph();
}

async function loadKgGraph() {
  let box = document.getElementById('kg-graph');
  if (typeof echarts === 'undefined') {
    box.innerHTML = '<div class="kg-empty"><span class="icon">📦</span>未找到 ECharts（static/echarts.min.js）<br>请切到「🗂 列表视图」</div>';
    return;
  }
  let q = (document.getElementById('kg-q').value || '').trim();
  let t = document.getElementById('kg-type').value;
  let top = document.getElementById('kg-top').value;
  let url = '/api/kg/graph?top=' + encodeURIComponent(top)
          + '&type=' + encodeURIComponent(t) + '&q=' + encodeURIComponent(q);
  let d = await fetch(url).then(r => r.json());
  renderKgGraph(d.nodes || [], d.edges || []);
}

function renderKgGraph(nodes, edges) {
  let el = document.getElementById('kg-graph');
  if (!nodes.length) {
    if (kgChart) { kgChart.dispose(); kgChart = null; }
    el.innerHTML = '<div class="kg-empty"><span class="icon">🕸</span>没有可展示的实体<br>点右上角"🛠 重建图谱"生成</div>';
    document.getElementById('kg-legend').innerHTML = '';
    return;
  }
  if (!kgChart || kgChart.getDom() !== el) kgChart = echarts.init(el);

  let data = nodes.map(n => ({
    id: n.id, name: n.name, type: n.type, value: n.mention_count,
    symbolSize: Math.max(10, Math.min(46, 10 + Math.sqrt(n.mention_count || 1) * 6)),
    itemStyle: {color: KG_COLOR[n.type] || '#4a6fa5'}
  }));
  let links = edges.map(e => ({
    source: e.source, target: e.target, predicate: e.predicate,
    lineStyle: e.predicate === 'related_to'
      ? {color: '#c9ced8', width: 1, type: 'dashed'}
      : (e.predicate === 'mentions' ? {color: '#d5dde8', width: 1} : {color: '#b9c7dd', width: 1.4})
  }));

  kgChart.setOption({
    tooltip: {
      confine: true,
      formatter: p => p.dataType === 'edge'
        ? '关系：' + (KG_PRED[p.data.predicate] || p.data.predicate || '包含')
        : (KG_LABEL[p.data.type] || p.data.type) + ' · ' + p.data.name + '<br/>提及 ' + (p.data.value || 0)
    },
    series: [{
      type: 'graph', layout: 'force', roam: true, draggable: true,
      data: data, links: links,
      force: {repulsion: 140, edgeLength: [40, 130], gravity: 0.06, layoutAnimation: true},
      label: {show: nodes.length <= 120, position: 'right', fontSize: 11, color: '#444', formatter: '{b}'},
      emphasis: {focus: 'adjacency', scale: 1.15, label: {show: true, fontWeight: 'bold'}},
      lineStyle: {opacity: .55, curveness: .08}
    }]
  }, true);

  kgChart.off('click');
  kgChart.on('click', p => { if (p.dataType === 'node') showKgEntity(p.data.id); });
  renderKgLegend(nodes);
}

function renderKgLegend(nodes) {
  let types = {};
  nodes.forEach(n => types[n.type] = (types[n.type] || 0) + 1);
  document.getElementById('kg-legend').innerHTML = Object.keys(types).map(k =>
    '<span><i style="background:' + (KG_COLOR[k] || '#4a6fa5') + '"></i>'
    + (KG_LABEL[k] || k) + ' ' + types[k] + '</span>').join('');
}

// ===== 最短路径 =====
let kgPath = {from: null, to: null};

function setKgPath(role, id, name) {
  kgPath[role] = {id: id, name: name};
  showToast((role === 'from' ? '已设起点: ' : '已设终点: ') + name, 'success');
  renderKgPathBar();
}

function renderKgPathBar() {
  let box = document.getElementById('kg-path-bar');
  if (!box) return;
  if (!kgPath.from && !kgPath.to) { box.innerHTML = ''; return; }
  box.innerHTML =
      '<span class="kg-chip">🔗 起点 ' + (kgPath.from ? esc(kgPath.from.name) : '未设置') + '</span>'
    + '<span class="kg-chip">🎯 终点 ' + (kgPath.to ? esc(kgPath.to.name) : '未设置') + '</span>'
    + '<button class="action-btn" onclick="calcKgPath()">🧭 计算最短路径</button>'
    + '<button class="action-btn" onclick="clearKgPath()">清空</button>'
    + '<span id="kg-path-result"></span>';
}

async function calcKgPath() {
  if (!kgPath.from || !kgPath.to) { showToast('请先设置起点和终点', 'error'); return; }
  let res = document.getElementById('kg-path-result');
  if (!res) return;
  res.innerHTML = '<span style="color:#999">计算中...</span>';
  let d = await fetch('/api/kg/path?from=' + kgPath.from.id + '&to=' + kgPath.to.id + '&depth=4')
            .then(r => r.json());
  if (!d.found) { res.innerHTML = '<span style="color:#c62828">4 跳内没有路径</span>'; return; }
  res.innerHTML = d.nodes.map((n, i) =>
      '<span class="kg-chip"><span class="kg-link" onclick="showKgEntity(' + n.id + ')">' + esc(n.name) + '</span></span>'
      + (i < d.nodes.length - 1 ? '<span class="kg-path-arrow">→</span>' : '')
    ).join('');
}

function clearKgPath() {
  kgPath = {from: null, to: null};
  renderKgPathBar();
  showToast('已清空路径起终点');
}

// ===== 实体合并 / 别名 =====
async function mergeKgEntity(keepId) {
  let input = document.getElementById('kg-merge-input');
  let name = (input && input.value || '').trim();
  if (!name) { showToast('请输入要合并进来的实体名', 'error'); return; }
  try {
    let d = await fetch('/api/kg/merge', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({keep: keepId, names: [name]})
    }).then(r => r.json());
    if (d.error) { showToast(d.error, 'error'); return; }
    showToast('已合并 ' + d.merged + ' 个实体', 'success');
    await loadKgView();
    showKgEntity(d.keep_id);
  } catch (e) { showToast('合并失败: ' + e, 'error'); }
}

// 当前实体名是别名 -> 合并到规范名（保留方为规范实体）
async function mergeKgToCanonical(canonical, entityId) {
  try {
    let d = await fetch('/api/kg/merge', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({keep: canonical, ids: [entityId]})
    }).then(r => r.json());
    if (d.error) { showToast(d.error, 'error'); return; }
    showToast('已合并到「' + canonical + '」', 'success');
    await loadKgView();
    showKgEntity(d.keep_id);
  } catch (e) { showToast('合并失败: ' + e, 'error'); }
}

async function applyKgAlias() {
  showToast('正在按别名表合并实体...');
  try {
    let d = await fetch('/api/kg/apply_alias', {method: 'POST'}).then(r => r.json());
    if (d.error) { showToast(d.error, 'error'); return; }
    if (!d.merged) {
      showToast(d.note || '没有需要合并的实体', 'error');
      return;
    }
    showToast('合并完成：' + d.merged + ' 个实体并入 ' + d.groups + ' 个规范实体', 'success');
    await loadKgView();
  } catch (e) { showToast('合并失败: ' + e, 'error'); }
}

// 命中实体 chip -> 图谱：切 Tab 并打开该实体详情
function focusKgEntity(id, name) {
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.querySelector('[data-tab="kg"]').classList.add('active');
  ['dashboard','search','files','upload','kg'].forEach(t => {
    document.getElementById('tab-' + t).style.display = t === 'kg' ? '' : 'none';
  });
  document.getElementById('kg-q').value = name;
  document.getElementById('kg-type').value = '';
  setKgView('graph');
  showKgEntity(id);
}

// 搜索结果 -> 图谱：切到图谱 Tab 并聚焦该文件
function focusInKg(filePath) {
  let name = ((filePath || '').split(/[\\/]/).pop() || '').replace(/\.[^.]+$/, '');
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.querySelector('[data-tab="kg"]').classList.add('active');
  ['dashboard','search','files','upload','kg'].forEach(t => {
    document.getElementById('tab-' + t).style.display = t === 'kg' ? '' : 'none';
  });
  document.getElementById('kg-q').value = name;
  document.getElementById('kg-type').value = '';
  setKgView('graph');
}

// 图谱节点 -> 搜索：切到搜索 Tab 并以实体名检索
function searchKgEntity(name) {
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.querySelector('[data-tab="search"]').classList.add('active');
  ['dashboard','search','files','upload','kg'].forEach(t => {
    document.getElementById('tab-' + t).style.display = t === 'search' ? '' : 'none';
  });
  document.getElementById('keyword').value = name;
  doSearch(1);
}

window.addEventListener('resize', () => { if (kgChart) kgChart.resize(); });

async function loadKgStats() {
  try {
    let d = await fetch('/api/kg/stats').then(r => r.json());
    let t = d.by_type || {};
    let chips = [
      `<div class="kg-stat"><b>${d.entity_count}</b>实体</div>`,
      `<div class="kg-stat"><b>${d.relation_count}</b>关系</div>`,
      `<div class="kg-stat"><b>${d.mention_count}</b>提及</div>`
    ];
    ['dir','file','section','person','system','term'].forEach(k => {
      if (t[k]) chips.push(`<div class="kg-stat">${KG_LABEL[k]} <b>${t[k]}</b></div>`);
    });
    chips.push(`<div class="kg-stat">构建 <b>${esc(d.last_build||'-')}</b></div>`);
    document.getElementById('kg-stats').innerHTML = chips.join('');
  } catch(e) { /* ignore */ }
}

async function loadKgEntities(page) {
  kgPage = page || 1;
  let q = (document.getElementById('kg-q').value || '').trim();
  let t = document.getElementById('kg-type').value;
  let url = '/api/kg/entities?q=' + encodeURIComponent(q) + '&type=' + encodeURIComponent(t) + '&page=' + kgPage + '&per_page=' + KG_PER_PAGE;
  let d = await fetch(url).then(r => r.json());
  let list = document.getElementById('kg-list');
  if (!d.items || !d.items.length) {
    list.innerHTML = '<div class="kg-empty"><span class="icon">🕸</span>暂无实体<br>点右上角"🛠 重建图谱"生成</div>';
    document.getElementById('kg-pagination').innerHTML = '';
    loadKgStats();
    return;
  }
  list.innerHTML = d.items.map(it =>
    `<div class="kg-item" onclick="showKgEntity(${it.id}, this)" title="${esc(it.name)}">
       <span class="kg-tag type-${it.type}">${KG_LABEL[it.type] || it.type}</span>
       <span class="kg-name">${esc(it.name)}</span>
       <span class="kg-meta">${it.doc_count} 文档 · ${it.mention_count} 提及</span>
     </div>`).join('');
  renderPagination('kg-pagination', d.total, kgPage, d.per_page, 'loadKgEntities');
  loadKgStats();
}

async function showKgEntity(id, el) {
  document.querySelectorAll('.kg-item').forEach(n => n.classList.remove('active'));
  if (el) el.classList.add('active');
  let d = await fetch('/api/kg/node/' + id).then(r => r.json());
  let box = document.getElementById('kg-detail');
  if (d.error) { box.innerHTML = '<div style="color:#c62828">' + esc(d.error) + '</div>'; return; }

  let e = d.entity;
  let html = `<div><b>${esc(e.name)}</b> <span class="kg-tag type-${e.type}">${KG_LABEL[e.type] || e.type}</span></div>
              <div class="kg-meta">${esc(e.normalized)}</div>`;

  if (d.parents && d.parents.length) {
    html += '<div class="kg-sub">上级</div>' + d.parents.map(p =>
      `<div><span class="kg-link" onclick="showKgEntity(${p.id})">${esc(p.name)}</span> <span class="kg-meta">${KG_LABEL[p.type]||p.type}</span></div>`).join('');
  }

  let al = d.alias || {};
  if (al.canonical && al.canonical !== e.name) {
    html += '<div class="kg-sub">规范名</div><div><span class="kg-link" onclick="mergeKgToCanonical(\''
         + escJS(al.canonical) + '\', ' + e.id + ')">' + esc(al.canonical) + '</span>'
         + ' <span class="kg-meta">点击合并到规范名</span></div>';
  }
  if (al.aliases && al.aliases.length) {
    html += '<div class="kg-sub">别名</div>' + al.aliases.map(a =>
      `<span class="kg-chip">${esc(a)}</span>`).join('');
  }

  if (d.related && d.related.length) {
    html += '<div class="kg-sub">共现实体</div>' + d.related.map(r =>
      `<span class="kg-chip"><span class="kg-link" onclick="showKgEntity(${r.id})">${esc(r.name)}</span> <b>${r.weight}</b></span>`).join('');
  }
  if (d.children && d.children.length) {
    html += '<div class="kg-sub">下级（' + d.children.length + '）</div>' + d.children.slice(0, 50).map(c =>
      `<div><span class="kg-link" onclick="showKgEntity(${c.id})">${esc(c.name)}</span> <span class="kg-meta">${KG_LABEL[c.type]||c.type}</span></div>`).join('');
  }
  if (d.mentions && d.mentions.length) {
    html += '<div class="kg-sub">原文出处（点击定位到段落）</div>' + d.mentions.map(m =>
      `<div class="kg-mention" onclick="openFileViewer('${escJS(m.file_path)}', ${m.para_index})">
         <div class="kg-meta">${esc(m.section_path || '文档')} · 片段 #${m.para_index}</div>
         <div>${esc((m.snippet || '').slice(0, 100))}</div>
       </div>`).join('');
  }
  html += `<div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
             <button class="action-btn" onclick="searchKgEntity('${escJS(e.name)}')">🔍 搜索该实体</button>
             <button class="action-btn" onclick="setKgPath('from', ${e.id}, '${escJS(e.name)}')">🔗 设为起点</button>
             <button class="action-btn" onclick="setKgPath('to', ${e.id}, '${escJS(e.name)}')">🎯 设为终点</button>`;
  if (e.type === 'file') {
    html += `<button class="action-btn" onclick="openFileViewer('${escJS(e.normalized)}', 0)">📄 查看原文</button>`;
  }
  html += '</div>';

  // 合并重复实体：输入另一个实体名，合并进当前实体
  html += `<div class="kg-sub">合并重复实体（如「支付宝系统」并入「支付宝」）</div>
           <div class="kg-merge-box">
             <input id="kg-merge-input" class="kg-input" placeholder="输入要并入「${esc(e.name)}」的实体名">
             <button class="action-btn" onclick="mergeKgEntity(${e.id})">🔀 合并</button>
           </div>`;
  box.innerHTML = html;
}

async function rebuildKg() {
  showToast('正在重建知识图谱...');
  try {
    let d = await fetch('/api/kg/rebuild', {method: 'POST'}).then(r => r.json());
    if (d.error) { showToast('重建失败: ' + d.error, 'error'); return; }
    showToast('图谱重建完成：' + d.files + ' 个文档 / ' + d.entities + ' 实体 / ' + d.relations + ' 关系', 'success');
    document.getElementById('kg-detail').innerHTML = '';
    await loadKgView();
  } catch(e) { showToast('重建失败: ' + e, 'error'); }
}

// ===== 同步 =====
async function syncIndex() {
  showToast('正在同步...');
  let resp = await fetch('/api/sync', {method:'POST'});
  let data = await resp.json();
  let errs = data.errors || [];
  if (errs.length) {
    showToast(`新增 ${data.added} | 更新 ${data.updated} | 跳过 ${data.skipped} | 删除 ${data.removed} — ${errs[0]}`, 'error');
  } else {
    showToast(`新增 ${data.added} | 更新 ${data.updated} | 跳过 ${data.skipped} | 删除 ${data.removed}`, 'success');
  }
  showStats();
}

async function showStats() {
}

function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function escJS(s) {
  if (!s) return '';
  return String(s).replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/"/g,'&quot;');
}

renderFilters();
showStats();
loadDashboard();
</script>
</body>
</html>
"""


# ==================== API 路由 ====================

@app.route("/")
def index_page():
    resp = make_response(render_template_string(HTML_TEMPLATE))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp


@app.route("/api/search")
def api_search():
    keyword = request.args.get("q", "").strip()
    source_type = request.args.get("source_type", "").strip() or None
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    if not keyword:
        return jsonify({"results": [], "total": 0})
    results, total = indexer.search(keyword, source_type=source_type,page=page, per_page=per_page)

    # 结果页图谱增强：这批片段里出现最多的实体
    entities = []
    try:
        entities = kg.entities_for_chunks(results, limit=12)
    except Exception as e:
        app.logger.warning("kg entities_for_chunks failed: %s", e)

    return jsonify({"results": results, "total": total, "count": len(results),
                    "page": page, "per_page": per_page, "entities": entities})


@app.route("/api/files")
def api_files():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    source_type = request.args.get("source_type", "").strip() or None
    files, total = indexer.get_doc_list(page=page, per_page=per_page, source_type=source_type)
    return jsonify({"files": files, "total": total, "page": page, "per_page": per_page})


@app.route("/api/files", methods=["DELETE"])
def api_remove_file():
    data = request.json or {}
    file_path = data.get("file_path", "").strip()
    if not file_path:
        return jsonify({"error": "file_path 必填"}), 400
    indexer.remove_doc(file_path)
    # 上传件只有索引没有原文件；其余按存在性删除
    if not file_path.startswith(UPLOAD_PREFIX) and os.path.isfile(file_path):
        try: os.remove(file_path)
        except OSError: pass
    return jsonify({"ok": True, "file_path": file_path})


@app.route("/api/files/batch", methods=["DELETE"])
def api_batch_remove():
    data = request.json or {}
    paths = data.get("file_paths", [])
    if not paths:
        return jsonify({"error": "file_paths 必填"}), 400
    removed = 0
    for p in paths:
        indexer.remove_doc(p)
        if not p.startswith(UPLOAD_PREFIX) and os.path.isfile(p):
            try: os.remove(p)
            except OSError: pass
        removed += 1
    return jsonify({"ok": True, "removed": removed})


@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "未上传文件"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "文件名为空"}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in SUPPORTED_EXTS:
        return jsonify({"error": f"不支持的格式: {ext}"}), 400

    # webkitdirectory 上传时 filename 可能含路径，只取文件名
    filename = file.filename.replace("\\", "/").split("/")[-1]
    virtual_path = UPLOAD_PREFIX + filename      # 只留索引，不留原文件

    # 解析用临时文件，入库后立刻删除
    tmp_dir = tempfile.mkdtemp(prefix="ks_upload_")
    tmp_path = os.path.join(tmp_dir, filename)
    try:
        file.save(tmp_path)
        chunks = parse_file(tmp_path)
        for c in chunks:
            c["file_path"] = virtual_path
        count = indexer.index_chunks(chunks)
        try:
            kg.rebuild_file(virtual_path)        # 同步图谱（读 chunks_fts，不碰原文件）
        except Exception:
            pass
        if count == 0:
            return jsonify({"ok": True, "indexed": 0, "filename": filename, "duplicate": True})
        return jsonify({"ok": True, "indexed": count, "filename": filename, "duplicate": False})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.route("/api/file_content")
def api_file_content():
    """获取文件内容——直接查 SQLite，不重新解析文件"""
    import html as html_mod
    import re as re_mod

    file_path = request.args.get("path", "").strip()
    para_index = request.args.get("para", 0, type=int)
    keyword = request.args.get("keyword", "").strip()

    if not file_path:
        return jsonify({"error": "path 必填"})

    target, relevant = indexer.get_chunks_by_file(file_path, para_index=para_index, context=2)

    if not relevant:
        if not os.path.isfile(file_path):
            return jsonify({"error": f"文件不存在且无索引: {file_path}"})
        return jsonify({"error": "文件未被索引，请先同步"})

    html_parts = []

    if target:
        target_idx = None
        for i, c in enumerate(relevant):
            if c["para_index"] == para_index:
                target_idx = i
                break

        context_before = relevant[:target_idx] if target_idx is not None else []
        context_after = relevant[target_idx+1:] if target_idx is not None else []

        for c in context_before:
            html_parts.append(f'<div style="color:#999;font-size:13px;padding:4px 0;border-left:2px solid #ddd;padding-left:10px;margin-bottom:4px">{html_mod.escape(c["content"][:200])}{"..." if len(c["content"])>200 else ""}</div>')

        content_html = html_mod.escape(target["content"])
        if keyword:
            import jieba
            tokens = list(jieba.cut_for_search(keyword))
            seen = set()
            for t in tokens:
                t = t.strip()
                if not t or t in seen: continue
                seen.add(t)
                content_html = re_mod.sub(f'({re_mod.escape(t)})', r'<mark>\1</mark>', content_html, flags=re_mod.IGNORECASE)

        html_parts.append(f'<div style="background:#fff3a0;padding:12px;border-radius:6px;border-left:3px solid #4a6fa5;margin:8px 0;font-size:14px;line-height:1.8">{content_html}</div>')

        for c in context_after:
            html_parts.append(f'<div style="color:#999;font-size:13px;padding:4px 0;border-left:2px solid #ddd;padding-left:10px;margin-top:4px">{html_mod.escape(c["content"][:200])}{"..." if len(c["content"])>200 else ""}</div>')

        html_parts.append(f'<div style="margin-top:16px;padding-top:12px;border-top:1px solid #e0e0e0;color:#999;font-size:12px">📍 {html_mod.escape(target.get("section_path",""))} · 段落 {para_index} · {html_mod.escape(file_path)}</div>')
    else:
        for c in relevant[:5]:
            html_parts.append(f'<div style="padding:4px 0">{html_mod.escape(c["content"][:200])}</div>')

    return jsonify({"html": "\n".join(html_parts), "content": ""})


@app.route("/api/open_file", methods=["POST"])
def api_open_file():
    """在系统默认程序中打开文件"""
    data = request.json or {}
    file_path = data.get("path", "").strip()
    if not file_path or not os.path.isfile(file_path):
        return jsonify({"error": "文件不存在"}), 404
    try:
        if sys.platform == "win32":
            os.startfile(file_path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", file_path])
        else:
            subprocess.Popen(["xdg-open", file_path])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sync", methods=["POST"])
def api_sync():
    exts = config.get("extensions", list(SUPPORTED_EXTS))
    configured = _scan_dirs_from_config()
    dirs = [d for d in configured if os.path.isdir(d)]
    missing = [d for d in configured if not os.path.isdir(d)]

    if not dirs:
        # 没有可用目录时绝不 prune：否则会把所有磁盘文档判成"已删除"
        return jsonify({"added": 0, "updated": 0, "skipped": 0, "removed": 0,
                        "errors": ["未配置有效的 scan_dirs（config.yaml），已跳过同步以免误删索引"]})

    if missing:
        # 部分目录不可达（如移动硬盘未接）时同样不清理，避免误删
        added, updated, skipped, _, errors = sync.scan_and_index(dirs, exts, prune=False)
        errors = list(errors) + [f"目录不可达，已跳过清理: {d}" for d in missing]
        return jsonify({"added": added, "updated": updated, "skipped": skipped,
                        "removed": 0, "errors": errors})

    added, updated, skipped, removed, errors = sync.scan_and_index(dirs, exts, prune=True)
    return jsonify({"added": added, "updated": updated, "skipped": skipped, "removed": removed, "errors": errors})


@app.route("/api/scan_preview", methods=["POST"])
def api_scan_preview():
    """预检：只统计目录下受支持的文件数量与总大小，不解析、不入库"""
    data = request.json or {}
    dir_path = (data.get("path") or "").strip().strip('"').strip("'")
    if not dir_path:
        return jsonify({"error": "目录路径不能为空"}), 400
    if not os.path.isdir(dir_path):
        return jsonify({"error": f"目录不存在: {dir_path}"}), 400

    exts = set(str(e).lower() for e in (config.get("extensions") or list(SUPPORTED_EXTS)))
    count = 0
    total_size = 0
    for root, dirs, fnames in os.walk(dir_path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in fnames:
            if os.path.splitext(fname)[1].lower() in exts:
                count += 1
                try:
                    total_size += os.path.getsize(os.path.join(root, fname))
                except OSError:
                    pass
    return jsonify({"path": dir_path, "count": count, "total_size": total_size})


def _scan_dirs_from_config():
    dirs = config.get("scan_dirs") or []
    if isinstance(dirs, str):
        dirs = [d.strip() for d in dirs.split(",") if d.strip()]
    return [str(d) for d in dirs if str(d).strip()]


def _insert_scan_dir_line(text, dir_path):
    """在保留注释的前提下把目录插进 config.yaml 的 scan_dirs 列表；无法定位则返回 None"""
    lines = text.splitlines()
    idx = None
    for i, ln in enumerate(lines):
        if ln.split("#", 1)[0].strip().startswith("scan_dirs:"):
            idx = i
            break
    if idx is None:
        return None

    item = "  - " + json.dumps(dir_path, ensure_ascii=False)
    last = idx
    j = idx + 1
    while j < len(lines):
        s = lines[j].strip()
        if s.startswith("- "):
            last = j
        elif s == "" or s.startswith("#"):
            pass
        else:
            break
        j += 1

    if last == idx:
        lines[idx] = "scan_dirs:\n" + item      # 原为空列表/单行写法
    else:
        lines.insert(last + 1, item)
    return "\n".join(lines) + "\n"


def _persist_scan_dir(dir_path):
    """把索引过的目录写入 config.yaml 的 scan_dirs，后续「同步」会自动覆盖它"""
    dirs = _scan_dirs_from_config()
    key = os.path.normcase(os.path.abspath(dir_path))
    if any(os.path.normcase(os.path.abspath(d)) == key for d in dirs):
        return dirs                              # 已配置过，不重复写文件
    dirs.append(dir_path)

    written = False
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                text = f.read()
            new_text = _insert_scan_dir_line(text, dir_path)
            if new_text:
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    f.write(new_text)
                written = True
        except OSError as e:
            app.logger.warning("更新 config.yaml 失败: %s", e)

    if not written:                              # 无 config.yaml 或没有 scan_dirs 键：按模板生成
        cfg = {}
        if os.path.exists(CONFIG_EXAMPLE_PATH):
            try:
                with open(CONFIG_EXAMPLE_PATH, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
            except Exception:
                cfg = {}
        cfg["scan_dirs"] = dirs
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        except OSError as e:
            app.logger.warning("写入 config.yaml 失败: %s", e)
    config["scan_dirs"] = dirs
    return dirs
    config["scan_dirs"] = dirs
    return dirs


# 目录索引进度：后台线程写入，前端轮询 /api/index_progress 展示进度条
_INDEX_LOCK = threading.Lock()
_INDEX_CANCEL = threading.Event()          # 前端点「终止」时置位
_INDEX_PROGRESS = {"running": False, "finished": False, "cancelled": False, "path": "",
                   "done": 0, "total": 0, "current": "",
                   "added": 0, "updated": 0, "skipped": 0, "errors": []}


def _index_dir_worker(dir_path, exts):
    def on_progress(done, total, current):
        with _INDEX_LOCK:
            _INDEX_PROGRESS.update({"done": done, "total": total, "current": current})
        return not _INDEX_CANCEL.is_set()   # 返回 False → sync 立即停止

    try:
        # prune=False：只增量索引该目录，不影响 uploads / 其它 scan_dirs 的索引
        added, updated, skipped, _, errors = sync.scan_and_index(
            [dir_path], exts, prune=False, progress_cb=on_progress)
        with _INDEX_LOCK:
            _INDEX_PROGRESS.update({"added": added, "updated": updated, "skipped": skipped,
                                    "errors": list(errors), "finished": True,
                                    "cancelled": _INDEX_CANCEL.is_set()})
    except Exception as e:
        with _INDEX_LOCK:
            _INDEX_PROGRESS.update({"errors": [str(e)], "finished": True,
                                    "cancelled": _INDEX_CANCEL.is_set()})
    finally:
        with _INDEX_LOCK:
            _INDEX_PROGRESS["running"] = False
            _INDEX_PROGRESS["current"] = ""


@app.route("/api/index_dir", methods=["POST"])
def api_index_dir():
    """索引本机目录：服务端直接扫描（不经浏览器上传）；后台线程执行，进度走 /api/index_progress"""
    data = request.json or {}
    dir_path = (data.get("path") or "").strip().strip('"').strip("'")
    if not dir_path:
        return jsonify({"error": "目录路径不能为空"}), 400
    if not os.path.isdir(dir_path):
        return jsonify({"error": f"目录不存在: {dir_path}"}), 400

    with _INDEX_LOCK:
        if _INDEX_PROGRESS["running"]:
            return jsonify({"error": "已有索引任务在进行中，请等它跑完或先点「终止」"}), 409
        _INDEX_PROGRESS.update({"running": True, "finished": False, "cancelled": False,
                                "path": dir_path, "done": 0, "total": 0, "current": "",
                                "added": 0, "updated": 0, "skipped": 0, "errors": []})
    _INDEX_CANCEL.clear()

    exts = config.get("extensions", list(SUPPORTED_EXTS))
    scan_dirs = _persist_scan_dir(dir_path)
    threading.Thread(target=_index_dir_worker, args=(dir_path, exts), daemon=True).start()
    return jsonify({"started": True, "path": dir_path, "scan_dirs": scan_dirs})


@app.route("/api/index_progress")
def api_index_progress():
    """目录索引进度（done/total/current + 计数 + 错误 + 是否已终止）"""
    with _INDEX_LOCK:
        snap = dict(_INDEX_PROGRESS)
        snap["errors"] = list(snap.get("errors") or [])
    snap["cancelling"] = snap["running"] and _INDEX_CANCEL.is_set()
    return jsonify(snap)


@app.route("/api/index_cancel", methods=["POST"])
def api_index_cancel():
    """终止正在进行的目录索引：已入库的文件保留，未处理的文件不再继续"""
    with _INDEX_LOCK:
        running = _INDEX_PROGRESS["running"]
    if not running:
        return jsonify({"ok": True, "running": False, "note": "当前没有正在进行的索引任务"})
    _INDEX_CANCEL.set()
    return jsonify({"ok": True, "running": True, "note": "已请求终止，正在收尾"})


# ==================== 知识图谱 API（L0 结构图谱） ====================

@app.route("/api/kg/stats")
def api_kg_stats():
    return jsonify(kg.stats())


@app.route("/api/kg/entities")
def api_kg_entities():
    q = request.args.get("q", "").strip()
    etype = request.args.get("type", "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    per_page = max(1, min(request.args.get("per_page", 20, type=int), 100))
    rows, total = kg.search_entities(q=q, etype=etype, limit=per_page, offset=(page - 1) * per_page)
    return jsonify({"items": rows, "total": total, "page": page, "per_page": per_page})


@app.route("/api/kg/node/<int:entity_id>")
def api_kg_node(entity_id):
    detail = kg.entity_detail(entity_id)
    if not detail:
        return jsonify({"error": "实体不存在"}), 404
    return jsonify(detail)


@app.route("/api/kg/neighbors/<int:entity_id>")
def api_kg_neighbors(entity_id):
    depth = max(1, min(request.args.get("depth", 1, type=int), 3))
    limit = max(1, min(request.args.get("limit", 60, type=int), 300))
    return jsonify(kg.neighbors(entity_id, depth=depth, limit=limit))


@app.route("/api/kg/graph")
def api_kg_graph():
    top = max(1, min(request.args.get("top", 200, type=int), 1000))
    etype = request.args.get("type", "").strip()
    q = request.args.get("q", "").strip()
    return jsonify(kg.graph(top=top, etype=etype, q=q))


@app.route("/api/kg/path")
def api_kg_path():
    """两实体间最短路径（无向 BFS）"""
    src = request.args.get("from", type=int)
    dst = request.args.get("to", type=int)
    if not src or not dst:
        return jsonify({"error": "缺少 from / to 参数"}), 400
    depth = max(1, min(request.args.get("depth", 4, type=int), 6))
    return jsonify(kg.shortest_path(src, dst, max_depth=depth))


@app.route("/api/kg/merge", methods=["POST"])
def api_kg_merge():
    """合并重复实体：body {keep: id|名称, names: [名称], ids: [id]}"""
    body = request.json or {}
    keep = body.get("keep")
    ids = [i for i in (body.get("ids") or []) if str(i).isdigit()]

    keep_id = None
    if str(keep).isdigit():
        keep_id = int(keep)
    else:
        found = kg.find_entity(str(keep or "").strip())
        if not found:
            return jsonify({"error": "保留实体不存在：" + str(keep)}), 400
        keep_id = found[0]["id"]

    # 待合并：ids + 按名称解析
    for name in body.get("names") or []:
        for e in kg.find_entity(name):
            ids.append(e["id"])
    ids = [i for i in dict.fromkeys(ids) if i != keep_id]
    if not ids:
        return jsonify({"error": "没有找到要合并的实体"}), 400

    result = kg.merge_entities(keep_id, ids)
    if not result.get("ok"):
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/kg/apply_alias", methods=["POST"])
def api_kg_apply_alias():
    """按 data/kg_alias.json 批量合并已有实体（无需重建）"""
    result = kg.apply_aliases()
    if result.get("merged"):
        kg_stats = kg.stats()
        result["entities"] = kg_stats["entity_count"]
    return jsonify(result)


@app.route("/api/kg/rebuild", methods=["POST"])
def api_kg_rebuild():
    try:
        result = kg.rebuild_all()
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stats")
def api_stats():
    return jsonify(indexer.get_stats())


@app.route("/api/download")
def api_download():
    file_path = request.args.get("path", "").strip()
    if not file_path or not os.path.isfile(file_path):
        return jsonify({"error": "文件不存在"}), 404
    return send_file(file_path, as_attachment=False)


# ==================== 后台自动同步（已禁用，统一从上传处理） ====================

def start_app():
    indexer.init_db()
    custom_dict = config.get("custom_dict")
    if custom_dict:
        indexer.load_custom_dict(custom_dict)
    port = config.get("port", 9876)
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    start_app()