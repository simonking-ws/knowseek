import os
import shutil
import sys

FROZEN = bool(getattr(sys, "frozen", False))
BASE_DIR = (
    os.path.dirname(os.path.abspath(sys.executable))
    if FROZEN
    else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
BUNDLE_DIR = getattr(sys, "_MEIPASS", BASE_DIR) if FROZEN else BASE_DIR
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "logs")
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")

DEFAULT_FILES = (
    "config.yaml",
    os.path.join("data", "kg_terms.txt"),
    os.path.join("data", "kg_stopwords.txt"),
    os.path.join("data", "kg_alias.json"),
)


def resource_path(*parts):
    return os.path.join(BUNDLE_DIR, *parts)


def ensure_runtime():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    for rel in DEFAULT_FILES:
        dst = os.path.join(BASE_DIR, rel)
        if os.path.exists(dst):
            continue
        src = os.path.join(BUNDLE_DIR, rel)
        if os.path.exists(src) and os.path.abspath(src) != os.path.abspath(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
