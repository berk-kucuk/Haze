#!/usr/bin/env bash
# build/build_appimage.sh
#
# Builds a self-contained Haze AppImage.
#
# Runtime: astral-sh/python-build-standalone (Python 3.11, glibc, install_only)
#   — a complete Python prefix with relative RPATH; runs on any x86_64 Linux
#     with glibc >= 2.17 (Ubuntu 18.04, Fedora 30, Arch, Debian 10, etc.)
# Qt: PyQt6 ships its own Qt6 libraries, so no system Qt is needed.
#
# Bundled dependencies:
#   PyQt6, stem, cryptography, python-socks, aiohttp, qrcode,
#   sounddevice, numpy
#
# Host requirements: curl, tar, python3 (any version, for the URL resolver)
# End-user requirement: tor binary in PATH
#
# Usage:  bash build/build_appimage.sh
# Output: Haze-x86_64.AppImage  (project root)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$SCRIPT_DIR"
APPDIR="$BUILD_DIR/AppDir"
OUTPUT="$PROJECT_DIR/Haze-x86_64.AppImage"

APPIMAGETOOL="$BUILD_DIR/appimagetool-x86_64.AppImage"
APPIMAGETOOL_URL="https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"

C='\033[0;36m'; G='\033[0;32m'; R='\033[0;31m'; N='\033[0m'

cd "$BUILD_DIR"

# ── 1. resolve the latest Python 3.11 standalone URL ──────────────────────────
echo -e "${C}==> Resolving Python 3.11 standalone runtime...${N}"
PYTHON_URL=$(curl -sL \
    "https://api.github.com/repos/astral-sh/python-build-standalone/releases?per_page=5" \
    | python3 -c "
import sys, json
releases = json.load(sys.stdin)
for r in releases:
    for a in r.get('assets', []):
        n = a['name']
        # exact variant: 3.11, plain x86_64 (not v2/v3/v4), gnu (not musl), not stripped
        if ('cpython-3.11' in n
                and '-x86_64-unknown-linux-gnu-install_only.tar.gz' in n
                and '_v2' not in n and '_v3' not in n and '_v4' not in n
                and '_stripped' not in n):
            print(a['browser_download_url'])
            sys.exit(0)
sys.exit(1)
")

if [ -z "$PYTHON_URL" ]; then
    echo -e "${R}Error: could not find a Python 3.11 standalone build in the latest releases.${N}"
    exit 1
fi

# GitHub encodes '+' as '%2B' in the URL; decode it for the local filename
PYTHON_TAR="$(basename "$PYTHON_URL" | sed 's/%2B/+/g')"
echo "    $PYTHON_TAR"

# ── 2. download tools (cached between runs) ────────────────────────────────────
if [ ! -f "$PYTHON_TAR" ]; then
    echo -e "${C}==> Downloading Python 3.11 runtime (~40 MB)...${N}"
    curl -L --progress-bar -o "$PYTHON_TAR" "$PYTHON_URL"
fi

if [ ! -f "$APPIMAGETOOL" ]; then
    echo -e "${C}==> Downloading appimagetool...${N}"
    curl -L --progress-bar -o "$APPIMAGETOOL" "$APPIMAGETOOL_URL"
fi
chmod +x "$APPIMAGETOOL"

# ── 3. create AppDir from Python runtime ──────────────────────────────────────
echo -e "${C}==> Extracting Python runtime...${N}"
rm -rf "$APPDIR" _py_extract
mkdir -p _py_extract
tar -xf "$PYTHON_TAR" -C _py_extract

# tarball extracts to python/ → relocate into AppDir/usr/
mkdir -p "$APPDIR/usr"
mv _py_extract/python/* "$APPDIR/usr/"
rm -rf _py_extract

PYTHON="$APPDIR/usr/bin/python3.11"

# ── 4. install Python dependencies into the bundled runtime ───────────────────
echo -e "${C}==> Installing dependencies into bundled runtime...${N}"
"$PYTHON" -m pip install --upgrade pip --quiet
"$PYTHON" -m pip install \
    "PyQt6>=6.6.0" \
    "stem>=1.8.2" \
    "cryptography>=42.0.0" \
    "python-socks[asyncio]>=2.4.4" \
    "aiohttp>=3.9" \
    "qrcode>=8.0" \
    "sounddevice>=0.4.6" \
    "numpy>=1.26" \
    --quiet
echo "    Installing haze..."
"$PYTHON" -m pip install "$PROJECT_DIR" --quiet

# ── 5. AppRun ──────────────────────────────────────────────────────────────────
echo -e "${C}==> Writing AppRun...${N}"
cat > "$APPDIR/AppRun" << 'APPRUN'
#!/usr/bin/env bash
SELF="$(readlink -f "$0")"
HERE="${SELF%/*}"

# Point Python at the bundled runtime prefix
export PYTHONHOME="$HERE/usr"
export PYTHONPATH="$HERE/usr/lib/python3.11/site-packages"

# Bundled runtime libs (libpython, openssl, etc. from python-build-standalone)
export LD_LIBRARY_PATH="$HERE/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# Qt6 libraries bundled inside PyQt6 — no system Qt needed
QT_BASE="$HERE/usr/lib/python3.11/site-packages/PyQt6/Qt6"
export QT_PLUGIN_PATH="$QT_BASE/plugins"
export QT_QPA_PLATFORM_PLUGIN_PATH="$QT_BASE/plugins/platforms"
export LD_LIBRARY_PATH="$QT_BASE/lib:$LD_LIBRARY_PATH"

exec "$HERE/usr/bin/python3.11" -m haze "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# ── 6. icon ────────────────────────────────────────────────────────────────────
echo -e "${C}==> Copying icon...${N}"
cp "$PROJECT_DIR/logo.png" "$APPDIR/haze.png"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp "$PROJECT_DIR/logo.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/haze.png"

# ── 7. desktop entry ───────────────────────────────────────────────────────────
echo -e "${C}==> Writing desktop entry...${N}"
cat > "$APPDIR/haze.desktop" << 'DESKTOP'
[Desktop Entry]
Name=Haze
GenericName=Anonymous Chat
Comment=Anonymous encrypted P2P chat over Tor
Exec=haze
Icon=haze
Type=Application
Terminal=false
Categories=Network;Chat;Security;
Keywords=anonymous;tor;chat;encrypted;privacy;
DESKTOP

mkdir -p "$APPDIR/usr/share/applications"
cp "$APPDIR/haze.desktop" "$APPDIR/usr/share/applications/haze.desktop"

# ── 8. build AppImage ──────────────────────────────────────────────────────────
echo -e "${C}==> Building AppImage...${N}"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 \
    "$APPIMAGETOOL" "$APPDIR" "$OUTPUT" 2>&1

echo ""
echo -e "${G}Done → $OUTPUT${N}"
echo "Run:  chmod +x Haze-x86_64.AppImage && ./Haze-x86_64.AppImage"
