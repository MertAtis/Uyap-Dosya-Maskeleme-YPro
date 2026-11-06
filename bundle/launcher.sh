#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
RESOURCES_DIR="$DIR/../Resources"

# Detect working python3 with tkinter support
PYTHON_BIN=""
for CANDIDATE in /opt/anaconda3/bin/python3 /usr/local/bin/python3 /usr/bin/python3 $(which python3 2>/dev/null); do
    if [ -x "$CANDIDATE" ]; then
        if "$CANDIDATE" -c "import tkinter" >/dev/null 2>&1; then
            PYTHON_BIN="$CANDIDATE"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    osascript -e 'display alert "Python 3 Bulunamadı" message "UYAP Maskeleme uygulamasını çalıştırmak için sisteminizde Tkinter kütüphanesine sahip bir Python 3 ortamı bulunamadı."'
    exit 1
fi

cd "$RESOURCES_DIR"
exec "$PYTHON_BIN" "$RESOURCES_DIR/gui.py"
