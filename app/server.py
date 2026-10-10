"""
Flask Web 服务 - 搜索界面 + 索引管理 API
功能：仪表盘Tab、搜索（分页+高亮+点击跳转）、文件列表（批量移除+点击打开）、批量上传文件夹
"""

import os
import threading
import time
import subprocess
import sys
import json
from flask import Flask, request, jsonify, render_template_string, send_file
from . import indexer, sync
from .parser import parse_file, compute_file_hash

import yaml

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}

config = load_config()
app = Flask(__name__)

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

SUPPORTED_EXTS = {".docx", ".txt", ".md", ".pdf", ".xlsx", ".xls"}


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>知识库搜索</title>
<style>
:root {
  --bg: #f0f2f5; --card: #fff; --primary: #4a6fa5; --primary-dark: #3a5a8e;
  --text: #1a1a2e; --text-2: #666; --border: #e0e0e0;
  --mark: #fff3a0; --radius: 10px; --shadow: 0 2px 8px rgba(0,0,0,.06);
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text)}

.header{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;padding:16px 24px}
.header-content{max-width:1200px;margin:0 auto;display:flex;align-items:center;justify-content:space-between}
.header h1{font-size:22px;font-weight:600}.header h1 .icon{margin-right:8px}
.header .stats{font-size:13px;color:rgba(255,255,255,.6)}

.nav-tabs{max-width:1200px;margin:0 auto;display:flex;gap:0;background:var(--card);border-bottom:1px solid var(--border)}
.nav-tab{padding:12px 24px;font-size:14px;color:var(--text-2);cursor:pointer;border:none;background:none;border-bottom:2px solid transparent;transition:all .2s}
.nav-tab:hover{color:var(--primary)}
.nav-tab.active{color:var(--primary);border-bottom-color:var(--primary);font-weight:500}
.tab-badge{display:inline-block;margin-left:4px;min-width:16px;height:16px;line-height:16px;text-align:center;font-size:10px;font-weight:600;border-radius:8px;padding:0 4px}
.tab-badge.zero{display:none}

.container{max-width:1200px;margin:0 auto;padding:24px 20px 48px}

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
.upload-progress{margin-bottom:12px}
.upload-progress-bar{background:#e0e0e0;border-radius:4px;height:6px;overflow:hidden}
.upload-progress-fill{background:var(--primary);height:100%;transition:width .3s}

.empty{text-align:center;padding:48px 20px;color:#999}.empty .icon{font-size:40px;margin-bottom:10px}
.actions-bar{display:flex;gap:8px;margin-bottom:16px;align-items:center}
.file-stats{margin-left:auto;font-size:13px;color:var(--text-2);white-space:nowrap}
.action-btn{padding:6px 14px;font-size:13px;border:1px solid var(--border);background:var(--card);border-radius:6px;cursor:pointer;color:var(--text-2)}
.action-btn:hover{background:#f5f5f5}
.action-btn.danger{color:#e53935;border-color:#ffcdd2}
.action-btn.danger:hover{background:#ffebee}

.toast{position:fixed;top:20px;right:20px;background:#333;color:#fff;padding:12px 20px;border-radius:8px;font-size:14px;z-index:9999;opacity:0;transition:opacity .3s;max-width:400px}
.toast.show{opacity:1}.toast.error{background:#c62828}.toast.success{background:#2e7d32}

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
    <h1><span class="icon">📚</span>知识库搜索</h1>
  </div>
</div>

<div class="nav-tabs" id="nav-tabs">
  <button class="nav-tab active" data-tab="dashboard">📊 仪表盘</button>
  <button class="nav-tab" data-tab="search">🔍 搜索</button>
  <button class="nav-tab" data-tab="files">📁 文件列表</button>
  <button class="nav-tab" data-tab="upload">📤 上传文件</button>
</div>

<div class="container">

  <!-- ===== Dashboard Tab ===== -->
  <div id="tab-dashboard">
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
        <div class="upload-text" style="margin-top:8px;font-size:12px;color:#aaa">支持 .docx .pdf .xlsx .txt .md</div>
      </div>
      <div class="upload-buttons">
        <button class="action-btn" onclick="document.getElementById('file-input').click()">📋 选择文件</button>
        <button class="action-btn" onclick="document.getElementById('folder-input').click()">📂 选择文件夹</button>
      </div>
    </div>
    <input type="file" id="file-input" multiple accept=".docx,.txt,.md,.doc,.pdf,.xlsx,.xls">
    <input type="file" id="folder-input" webkitdirectory directory multiple>
    <div id="upload-results"></div>
  </div>

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

// ===== Tab 切换 =====
document.getElementById('nav-tabs').addEventListener('click', e => {
  let btn = e.target.closest('.nav-tab');
  if (!btn) return;
  let tab = btn.dataset.tab;
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  ['dashboard','search','files','upload'].forEach(t => {
    document.getElementById('tab-'+t).style.display = t === tab ? '' : 'none';
  });
  if (tab === 'files') loadFiles(1);
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

// ===== Dashboard =====
async function loadDashboard() {
  let resp = await fetch('/api/stats');
  let data = await resp.json();

  let grid = document.getElementById('dash-grid');
  let cards = [
    {icon:'📄', num:data.doc_count, label:'文档总数', filter:''},
    {icon:'📝', num:data.chunk_count, label:'片段总数', filter:''},
  ];
  if (data.by_source) {
    for (let [k,v] of Object.entries(data.by_source)) {
      cards.push({icon:SOURCE_ICONS[k]||'📋', num:v, label:SOURCE_LABELS[k]||k, filter:k});
    }
  }
  grid.innerHTML = cards.map(c =>
    `<div class="dash-card" ${c.filter?`onclick="dashFilter('${c.filter}')"`:''}>
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
  currentFilter = type;
  renderFilters();
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

  renderResults(data.results, kw);
  renderPagination('pagination', data.total, page, PER_PAGE, 'doSearch');
}

function renderResults(results, kw) {
  let c = document.getElementById('search-results');
  if (!results.length) {
    c.innerHTML = '<div class="empty"><div class="icon">😔</div><div>没有找到匹配结果</div></div>';
    return;
  }
  c.innerHTML = results.map(r => {
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
        <span class="file-path" title="${escJS(r.file_path)}">${esc(r.file_path)}</span>
        <span>·</span><span style="white-space:nowrap">${esc(loc)}</span>
        <span class="result-score">BM25: ${r.score}</span>
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
    statsEl.textContent = `📄 ${statsData.doc_count} 文档`;
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
        <td class="col-cb"><input type="checkbox" data-path="${escJS(f.file_path)}" onchange="toggleSelect(this)"></td>
        <td class="col-name file-title" title="${escJS(f.title||'')}" onclick="openFileViewer('${escJS(f.file_path)}',0,'')">${fname}</td>
        <td class="col-source"><span class="source-tag ${sc}">${label}</span></td>
        <td class="col-chunks">${f.chunk_count}</td>
        <td class="col-time" title="${escJS(f.indexed_at||'')}">${esc(f.indexed_at||'')}</td>
        <td class="col-path file-path" title="${escJS(f.file_path)}">${esc(f.file_path)}</td>
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
  if (!confirm(`确定移除 ${selectedFiles.size} 个文件的索引？`)) return;
  let resp = await fetch('/api/files/batch', {
    method: 'DELETE', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({file_paths: [...selectedFiles]})
  });
  let data = await resp.json();
  if (data.ok) { showToast(`已移除 ${data.removed} 个文件`, 'success'); loadFiles(currentFilePage); showStats(); }
  else showToast('移除失败', 'error');
}

async function removeFile(filePath) {
  if (!confirm('确定移除该文件的索引？')) return;
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

async function handleFiles(fileList) {
  let files = Array.from(fileList).filter(f => {
    let ext = '.' + f.name.split('.').pop().toLowerCase();
    return ['.docx','.txt','.md','.doc','.pdf','.xlsx','.xls'].includes(ext);
  });

  if (!files.length) { showToast('未找到支持的文件', 'error'); return; }

  let results = document.getElementById('upload-results');
  results.innerHTML = `<div class="upload-progress">
    <div style="font-size:13px;color:#666;margin-bottom:6px">上传中 0/${files.length}...</div>
    <div class="upload-progress-bar"><div class="upload-progress-fill" id="prog-fill" style="width:0%"></div></div>
  </div>`;

  let ok = 0, fail = 0;
  for (let i = 0; i < files.length; i++) {
    let formData = new FormData();
    formData.append('file', files[i]);
    try {
      let resp = await fetch('/api/upload', {method:'POST', body: formData});
      let data = await resp.json();
      if (data.error) { fail++; results.innerHTML += `<div style="color:#c62828;padding:4px;">❌ ${esc(files[i].name)}: ${esc(data.error)}</div>`; }
      else { ok++; results.innerHTML += `<div style="color:#2e7d32;padding:4px;">✅ ${esc(files[i].name)}: ${data.indexed} 片段</div>`; }
    } catch(err) { fail++; results.innerHTML += `<div style="color:#c62828;padding:4px;">❌ ${esc(files[i].name)}</div>`; }
    let pct = Math.round((i+1)/files.length*100);
    document.getElementById('prog-fill').style.width = pct + '%';
    results.querySelector('div > div:first-child').textContent = `上传 ${i+1}/${files.length} (✅${ok} ❌${fail})`;
  }
  showToast(`上传完成: ${ok} 成功, ${fail} 失败`, ok ? 'success' : 'error');
  showStats();
}

// ===== 同步 =====
async function syncIndex() {
  showToast('正在同步...');
  let resp = await fetch('/api/sync', {method:'POST'});
  let data = await resp.json();
  showToast(`新增 ${data.added} | 更新 ${data.updated} | 跳过 ${data.skipped} | 删除 ${data.removed}`, 'success');
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
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/search")
def api_search():
    keyword = request.args.get("q", "").strip()
    source_type = request.args.get("source_type", "").strip() or None
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    if not keyword:
        return jsonify({"results": [], "total": 0})
    results, total = indexer.search(keyword, source_type=source_type,page=page, per_page=per_page)
    return jsonify({"results": results, "total": total, "count": len(results), "page": page, "per_page": per_page})


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
    if os.path.isfile(file_path) and UPLOAD_DIR in file_path:
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
        if os.path.isfile(p) and UPLOAD_DIR in p:
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

    # 保留原始文件夹结构（如果来自文件夹上传）
    # webkitdirectory 上传时 filename 可能含路径
    filename = file.filename.replace("\\", "/").split("/")[-1]
    save_path = os.path.join(UPLOAD_DIR, filename)
    file.save(save_path)

    try:
        chunks = parse_file(save_path)
        count = indexer.index_chunks(chunks)
        return jsonify({"ok": True, "indexed": count, "filename": filename})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
    dirs = config.get("scan_dirs", [])
    exts = config.get("extensions", list(SUPPORTED_EXTS))
    added, updated, skipped, removed, errors = sync.scan_and_index(dirs, exts)
    return jsonify({"added": added, "updated": updated, "skipped": skipped, "removed": removed, "errors": errors})


@app.route("/api/stats")
def api_stats():
    return jsonify(indexer.get_stats())


@app.route("/api/download")
def api_download():
    file_path = request.args.get("path", "").strip()
    if not file_path or not os.path.isfile(file_path):
        return jsonify({"error": "文件不存在"}), 404
    return send_file(file_path, as_attachment=False)


# ==================== 后台自动同步 ====================

def background_sync():
    interval = config.get("sync_interval", 300)
    while True:
        time.sleep(interval)
        try:
            dirs = config.get("scan_dirs", [])
            exts = config.get("extensions", list(SUPPORTED_EXTS))
            sync.scan_and_index(dirs, exts)
        except Exception:
            pass


def start_app():
    indexer.init_db()
    custom_dict = config.get("custom_dict")
    if custom_dict:
        indexer.load_custom_dict(custom_dict)
    t = threading.Thread(target=background_sync, daemon=True)
    t.start()
    port = config.get("port", 9876)
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    start_app()