#!/bin/bash
# ==============================================================================
# UYAP Dosya Maskeleme (YPro) — macOS Universal Launcher
# ==============================================================================
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
RESOURCES_DIR="$DIR/../Resources"

# macOS ortamında Türkçe karakter ve UTF-8 güvenliği
export LC_ALL="en_US.UTF-8"
export LANG="en_US.UTF-8"
export PYTHONIOENCODING="utf-8"

# Python 3 tespit listesi (Öncelik: Apple Silicon Homebrew, Anaconda/Miniconda, Python.org, Intel Homebrew, Pyenv, Sistem)
CANDIDATES=(
    "/opt/homebrew/bin/python3"
    "/opt/anaconda3/bin/python3"
    "$HOME/opt/anaconda3/bin/python3"
    "$HOME/anaconda3/bin/python3"
    "$HOME/miniconda3/bin/python3"
    "$HOME/.pyenv/shims/python3"
    "/Library/Frameworks/Python.framework/Versions/Current/bin/python3"
    "/usr/local/bin/python3"
    "/usr/bin/python3"
)

PYTHON_BIN=""

for CANDIDATE in "${CANDIDATES[@]}"; do
    if [ -x "$CANDIDATE" ]; then
        if "$CANDIDATE" -c "import tkinter" >/dev/null 2>&1; then
            PYTHON_BIN="$CANDIDATE"
            break
        fi
    fi
done

# Eğer aday listesinde bulunamadıysa aktif PATH üzerindeki python3'ü kontrol et
if [ -z "$PYTHON_BIN" ]; then
    SYS_PY="$(command -v python3 2>/dev/null || true)"
    if [ -n "$SYS_PY" ] && [ -x "$SYS_PY" ]; then
        if "$SYS_PY" -c "import tkinter" >/dev/null 2>&1; then
            PYTHON_BIN="$SYS_PY"
        fi
    fi
fi

if [ -z "$PYTHON_BIN" ]; then
    osascript -e 'display alert "Python 3 Bulunamadı" message "UYAP Maskeleme uygulamasını çalıştırmak için sisteminizde Tkinter kütüphanesine sahip bir Python 3 ortamı bulunamadı. Lütfen Homebrew veya Python.org üzerinden Python 3 kurun."'
    exit 1
fi

cd "$RESOURCES_DIR"
exec "$PYTHON_BIN" "$RESOURCES_DIR/gui.py"
