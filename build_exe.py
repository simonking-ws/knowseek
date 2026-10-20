import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist" / "KnowSeek"
DEFAULT_FILES = (
    "config.yaml",
    "data/kg_terms.txt",
    "data/kg_stopwords.txt",
    "data/kg_alias.json",
)


def backup_portable_data(backup_root):
    for name in ("config.yaml", "data", "logs"):
        src = DIST / name
        if not src.exists():
            continue
        dst = backup_root / name
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def restore_portable_data(backup_root):
    for name in ("config.yaml", "data", "logs"):
        src = backup_root / name
        if not src.exists():
            continue
        dst = DIST / name
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def copy_defaults():
    for rel in DEFAULT_FILES:
        src = ROOT / rel
        dst = DIST / rel
        if dst.exists() or not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def copy_database():
    src_path = ROOT / "data" / "knowseek.db"
    dst_path = DIST / "data" / "knowseek.db"
    if dst_path.exists() or not src_path.exists():
        return
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(src_path))
    dst = sqlite3.connect(str(dst_path))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def main():
    backup_root = Path(tempfile.mkdtemp(prefix="knowseek-dist-"))
    try:
        backup_portable_data(backup_root)
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "knowseek.spec"],
            cwd=str(ROOT),
            check=True,
        )
        DIST.mkdir(parents=True, exist_ok=True)
        (DIST / "data").mkdir(exist_ok=True)
        (DIST / "logs").mkdir(exist_ok=True)
        restore_portable_data(backup_root)
        copy_defaults()
        copy_database()
    finally:
        shutil.rmtree(backup_root, ignore_errors=True)
    print(f"[OK] {DIST / 'KnowSeek.exe'}")


if __name__ == "__main__":
    main()
