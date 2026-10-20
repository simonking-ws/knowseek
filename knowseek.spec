# -*- mode: python ; coding: utf-8 -*-

datas = [
    ("config.yaml", "."),
    ("static/echarts.min.js", "static"),
    ("data/kg_terms.txt", "data"),
    ("data/kg_stopwords.txt", "data"),
    ("data/kg_alias.json", "data"),
]

hiddenimports = [
    "win32com",
    "win32com.client",
    "pythoncom",
    "pywintypes",
    "win32api",
    "win32timezone",
    "pdfplumber",
    "pdfminer",
    "pdfminer.high_level",
    "pdfminer.layout",
    "docx",
    "openpyxl",
    "xlrd",
    "lxml",
    "lxml.etree",
    "yaml",
    "jieba",
    "jieba.posseg",
]

excludes = [
    "PIL",
    "pypdfium2",
    "numpy",
    "torch",
    "torchvision",
    "cv2",
    "matplotlib",
    "pandas",
    "scipy",
    "IPython",
    "pytest",
    "PyQt5",
    "tkinter",
    "setuptools",
    "pip",
]

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KnowSeek",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="KnowSeek",
)
