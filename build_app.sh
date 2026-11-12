#!/bin/bash
# ==============================================================================
# UYAP Dosya Maskeleme (YPro) — macOS Geliştirici Test Paketi (Dev Wrapper)
# NOT: Bu betik yerel geliştirici testleri içindir. Dağıtılabilir %100 bağımsız
# standalone sürüm için 'build_dmg.sh' kullanılmalıdır.
# ==============================================================================
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
APP_NAME="UYAP Maskeleme.app"
OUTPUT_DIR="${1:-$DIR/dist_dev}"

# dist/ içindeki gerçek standalone ikilinin kazara ezilmesini önle
if [ -d "$OUTPUT_DIR/$APP_NAME/Contents/Frameworks" ] || ([ -f "$OUTPUT_DIR/$APP_NAME/Contents/MacOS/UYAP Maskeleme" ] && file "$OUTPUT_DIR/$APP_NAME/Contents/MacOS/UYAP Maskeleme" 2>/dev/null | grep -q "Mach-O"); then
    echo "⚠️ HATA: '$OUTPUT_DIR/$APP_NAME' bağımsız bir PyInstaller ikilisi içeriyor!"
    echo "Gerçek standalone ikiliyi ezmemek için işlem durduruldu. Lütfen 'dist_dev' kullanın veya farklı bir hedef dizin belirtin."
    exit 1
fi

echo "🔨 [1/4] Geliştirici derleme dizini hazırlanıyor: $OUTPUT_DIR/$APP_NAME"
mkdir -p "$OUTPUT_DIR/$APP_NAME/Contents/MacOS"
mkdir -p "$OUTPUT_DIR/$APP_NAME/Contents/Resources"

echo "📦 [2/4] Kaynak dosyalar kopyalanıyor..."
cp "$DIR/gui.py" "$OUTPUT_DIR/$APP_NAME/Contents/Resources/"
cp "$DIR/uyap_redactor.py" "$OUTPUT_DIR/$APP_NAME/Contents/Resources/"

echo "🎨 [3/4] Bundle ayarları ve ikonlar ekleniyor..."
cp "$DIR/bundle/Info.plist" "$OUTPUT_DIR/$APP_NAME/Contents/"
cp "$DIR/bundle/app.icns" "$OUTPUT_DIR/$APP_NAME/Contents/Resources/"
cp "$DIR/bundle/launcher.sh" "$OUTPUT_DIR/$APP_NAME/Contents/MacOS/UYAP Maskeleme"

echo "🔐 [4/4] İzinler ve Ad-Hoc Kod İmzası ayarlanıyor..."
chmod +x "$OUTPUT_DIR/$APP_NAME/Contents/MacOS/UYAP Maskeleme"
chmod +x "$OUTPUT_DIR/$APP_NAME/Contents/Resources/gui.py"
chmod +x "$OUTPUT_DIR/$APP_NAME/Contents/Resources/uyap_redactor.py"

if command -v codesign >/dev/null 2>&1; then
    codesign --force --deep --sign - "$OUTPUT_DIR/$APP_NAME" >/dev/null 2>&1 || true
    echo "🔏 macOS Ad-Hoc kod imzası başarıyla uygulandı."
fi

echo "✅ Başarılı! '$OUTPUT_DIR/$APP_NAME' hazır."
echo "💡 Çalıştırmak için: open '$OUTPUT_DIR/$APP_NAME'"
