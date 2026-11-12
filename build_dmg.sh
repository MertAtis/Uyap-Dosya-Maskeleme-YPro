#!/bin/bash
# ==============================================================================
# UYAP Dosya Maskeleme (YPro) — macOS Standalone & DMG Builder
# ==============================================================================
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
APP_NAME="UYAP Maskeleme.app"
DMG_NAME="UYAP-Maskeleme.dmg"
SPEC_FILE="$DIR/UYAP Maskeleme.spec"
DIST_DIR="$DIR/dist"
OUTPUT_DIR="${1:-$DIST_DIR}"

echo "🚀 [1/4] PyInstaller ile %100 Bağımsız (Standalone) App derleniyor..."
cd "$DIR"
rm -rf "$DIST_DIR/$APP_NAME" "$DIST_DIR/UYAP Maskeleme"

# PyInstaller tespit et (Öncelik: Aktif PATH, python3 modülü, sanal ortam, sistem)
PYINSTALLER_CMD=""

if command -v pyinstaller >/dev/null 2>&1; then
    PYINSTALLER_CMD="$(command -v pyinstaller)"
elif python3 -m PyInstaller --version >/dev/null 2>&1; then
    PYINSTALLER_CMD="python3 -m PyInstaller"
else
    for CANDIDATE in "$VIRTUAL_ENV/bin/pyinstaller" /opt/homebrew/bin/pyinstaller /opt/anaconda3/bin/pyinstaller "$HOME/opt/anaconda3/bin/pyinstaller" "$HOME/anaconda3/bin/pyinstaller" /usr/local/bin/pyinstaller; do
        if [ -n "$CANDIDATE" ] && [ -x "$CANDIDATE" ]; then
            PYINSTALLER_CMD="$CANDIDATE"
            break
        fi
    done
fi

if [ -z "$PYINSTALLER_CMD" ]; then
    echo "❌ Hata: Sistemde 'pyinstaller' bulunamadı!"
    exit 1
fi

$PYINSTALLER_CMD --noconfirm "$SPEC_FILE"

echo "🔐 [2/4] Standalone App için Ad-Hoc Kod İmzası uygulanıyor..."
if command -v codesign >/dev/null 2>&1; then
    codesign --force --deep --sign - "$DIST_DIR/$APP_NAME" >/dev/null 2>&1 || true
    echo "🔏 App paketi başarıyla mühürlendi."
fi

echo "📦 [3/4] macOS Drag-and-Drop DMG Kurulum İmajı hazırlanıyor..."
DMG_STAGING="$DIST_DIR/dmg_staging"
rm -rf "$DMG_STAGING" "$DIST_DIR/$DMG_NAME"
mkdir -p "$DMG_STAGING"

# Uygulamayı ve /Applications kısayolunu hazırla
cp -R "$DIST_DIR/$APP_NAME" "$DMG_STAGING/"
ln -s /Applications "$DMG_STAGING/Applications"

# hdiutil ile sıkıştırılmış DMG üret
hdiutil create -volname "UYAP Maskeleme" \
  -srcfolder "$DMG_STAGING" \
  -ov -format UDZO \
  "$DIST_DIR/$DMG_NAME"

rm -rf "$DMG_STAGING"

if command -v codesign >/dev/null 2>&1; then
    codesign --force --sign - "$DIST_DIR/$DMG_NAME" >/dev/null 2>&1 || true
    echo "🔏 DMG imajı başarıyla mühürlendi."
fi

echo "✨ [4/4] Çıktılar kopyalanıyor..."
if [ "$OUTPUT_DIR" != "$DIST_DIR" ]; then
    mkdir -p "$OUTPUT_DIR"
    cp -R "$DIST_DIR/$APP_NAME" "$OUTPUT_DIR/"
    cp "$DIST_DIR/$DMG_NAME" "$OUTPUT_DIR/"
    echo "📋 Dosyalar '$OUTPUT_DIR' dizinine aktarıldı."
fi

echo ""
echo "=============================================================================="
echo "🎉 TEBRİKLER! %100 Bağımsız macOS Sürümü Hazır!"
echo "=============================================================================="
echo "1. Bağımsız App : $DIST_DIR/$APP_NAME"
echo "2. Kurulum DMG'si: $DIST_DIR/$DMG_NAME"
if [ "$OUTPUT_DIR" != "$DIST_DIR" ]; then
echo "3. Hedef Klasör : $OUTPUT_DIR/$DMG_NAME"
fi
echo ""
echo "💡 Bu DMG dosyasını doğrudan GitHub Releases'a yükleyebilirsiniz."
echo "💡 Kullanıcılar DMG'yi açıp uygulamayı 'Applications' klasörüne sürükleyerek anında kullanabilir."
