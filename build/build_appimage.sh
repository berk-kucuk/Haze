#!/usr/bin/env bash
# Haze AppImage builder
# Requires: appimagetool, python3
#
# Usage: bash build/build_appimage.sh
# Output: Haze-x86_64.AppImage

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
APPDIR="$SCRIPT_DIR/Haze.AppDir"
ARCH="$(uname -m)"
OUTPUT="$PROJECT_DIR/Haze-$ARCH.AppImage"

CYAN='\033[0;36m'
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}Haze AppImage build başlıyor...${NC}"

if ! command -v appimagetool &>/dev/null; then
    echo -e "${RED}appimagetool bulunamadı. İndir:${NC}"
    echo "  wget https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
    echo "  chmod +x appimagetool-x86_64.AppImage"
    echo "  sudo mv appimagetool-x86_64.AppImage /usr/local/bin/appimagetool"
    exit 1
fi

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" \
         "$APPDIR/usr/lib" \
         "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/64x64/apps"

echo -e "${CYAN}Python ortamı oluşturuluyor...${NC}"
python3 -m venv "$APPDIR/usr/venv"
"$APPDIR/usr/venv/bin/pip" install --quiet --upgrade pip
"$APPDIR/usr/venv/bin/pip" install --quiet "$PROJECT_DIR"

cat > "$APPDIR/AppRun" <<'APPRUN'
#!/usr/bin/env bash
SELF="$(readlink -f "$0")"
HERE="$(dirname "$SELF")"
export PATH="$HERE/usr/bin:$PATH"
exec "$HERE/usr/venv/bin/python" -m haze.main "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/haze.desktop" <<'DESKTOP'
[Desktop Entry]
Version=1.0
Type=Application
Name=Haze
Comment=Anonymous encrypted P2P chat — Haze Protocol
Exec=AppRun
Icon=haze
Terminal=false
Categories=Network;Chat;Security;
DESKTOP

cp "$APPDIR/haze.desktop" "$APPDIR/usr/share/applications/"

ICON_SRC="$PROJECT_DIR/logo.png"
ICON_DEST="$APPDIR/haze.png"
if [[ -f "$ICON_SRC" ]]; then
    cp "$ICON_SRC" "$ICON_DEST"
    cp "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/64x64/apps/haze.png"
else
    echo -e "${CYAN}İkon oluşturuluyor...${NC}"
    ICON_OUT="$ICON_DEST" "$APPDIR/usr/venv/bin/python" - <<'PYEOF'
import os, sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPixmap, QPainter, QColor
from PyQt6.QtCore import Qt
app = QApplication(sys.argv)
px = QPixmap(64, 64)
px.fill(Qt.GlobalColor.transparent)
p = QPainter(px)
p.setRenderHint(QPainter.RenderHint.Antialiasing)
p.setBrush(QColor("#7c3aed"))
p.setPen(Qt.PenStyle.NoPen)
p.drawEllipse(8, 8, 48, 48)
p.end()
px.save(os.environ.get("ICON_OUT", "haze.png"))
PYEOF
    cp "$ICON_DEST" "$APPDIR/usr/share/icons/hicolor/64x64/apps/haze.png"
fi

echo -e "${CYAN}AppImage oluşturuluyor...${NC}"
ARCH="$ARCH" appimagetool "$APPDIR" "$OUTPUT"

echo -e "\n${GREEN}Build tamamlandı: $OUTPUT${NC}"
echo -e "Çalıştırmak için: ${GREEN}chmod +x $OUTPUT && $OUTPUT${NC}"
