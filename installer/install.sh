#!/usr/bin/env bash
# Haze Installer
# Usage: bash install.sh [--uninstall]

set -euo pipefail

APP="haze"
INSTALL_DIR="$HOME/.local/share/haze"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
PIXMAP_DIR="$HOME/.local/share/pixmaps"
HICOLOR_DIR="$HOME/.local/share/icons/hicolor"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# ── Refresh all icon caches ──────────────────────────────────────────
refresh_icon_cache() {
    # GTK / hicolor theme cache
    gtk-update-icon-cache -f -t "$HICOLOR_DIR" 2>/dev/null || true
    # XDG generic
    xdg-icon-resource forceupdate --theme hicolor 2>/dev/null || true
    # KDE Plasma 6 / 5
    kbuildsycoca6 --noincremental 2>/dev/null \
        || kbuildsycoca5 --noincremental 2>/dev/null \
        || true
    # Desktop database
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
}

# ── Uninstall ────────────────────────────────────────────────────────
uninstall() {
    echo -e "${CYAN}Removing Haze...${NC}"
    rm -rf "$INSTALL_DIR"
    rm -f  "$BIN_DIR/$APP"
    rm -f  "$DESKTOP_DIR/$APP.desktop"
    rm -f  "$PIXMAP_DIR/$APP.png"
    for size in 16 22 32 48 64 128 256; do
        rm -f "$HICOLOR_DIR/${size}x${size}/apps/$APP.png"
    done
    echo -e "${CYAN}Refreshing icon caches...${NC}"
    refresh_icon_cache
    echo -e "${GREEN}Haze has been removed.${NC}"
    exit 0
}

[[ "${1:-}" == "--uninstall" ]] && uninstall

# ── Banner ───────────────────────────────────────────────────────────
echo -e "${BOLD}${CYAN}"
echo "  ██╗  ██╗ █████╗ ███████╗███████╗"
echo "  ██║  ██║██╔══██╗╚══███╔╝██╔════╝"
echo "  ███████║███████║  ███╔╝ █████╗  "
echo "  ██╔══██║██╔══██║ ███╔╝  ██╔══╝  "
echo "  ██║  ██║██║  ██║███████╗███████╗"
echo "  ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚══════╝"
echo -e "${NC}"
echo -e "${BOLD}Anonymous · Encrypted · No Trace — Haze Protocol${NC}"
echo -e "  E2E encrypted · Tor hidden services · Session passwords"
echo -e "  Web access · Circuit renewal · Multi-session · Secret Vault"
echo ""

# ── Dependency checks ────────────────────────────────────────────────
echo -e "${CYAN}Checking dependencies...${NC}"

if ! command -v python3 &>/dev/null; then
    echo -e "${RED}Error: python3 not found. Please install Python 3.11+.${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"; then
    echo -e "  Python $PYTHON_VERSION ${GREEN}✓${NC}"
else
    echo -e "${RED}Error: Python 3.11+ required (found: $PYTHON_VERSION)${NC}"
    exit 1
fi

if ! command -v tor &>/dev/null; then
    echo -e "${RED}Warning: 'tor' not found.${NC}"
    echo "  Ubuntu/Debian : sudo apt install tor"
    echo "  Arch Linux    : sudo pacman -S tor"
    echo "  Fedora        : sudo dnf install tor"
    echo ""
    read -rp "Continue installation without Tor? [y/N] " answer
    [[ "${answer,,}" != "y" ]] && exit 1
else
    echo -e "  tor ${GREEN}✓${NC}"
fi

# ── Directories ──────────────────────────────────────────────────────
echo -e "\n${CYAN}Creating directories...${NC}"
mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$PIXMAP_DIR"
for size in 16 22 32 48 64 128 256; do
    mkdir -p "$HICOLOR_DIR/${size}x${size}/apps"
done

# ── Python environment ───────────────────────────────────────────────
echo -e "${CYAN}Setting up Python virtual environment...${NC}"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -e "$PROJECT_DIR"
echo -e "${GREEN}Python packages installed.${NC}"

# ── Launcher script ──────────────────────────────────────────────────
cat > "$BIN_DIR/$APP" <<EOF
#!/usr/bin/env bash
exec "$INSTALL_DIR/venv/bin/python" -m haze.main "\$@"
EOF
chmod +x "$BIN_DIR/$APP"

# ── Icon installation ────────────────────────────────────────────────
# Install to every standard size + pixmaps so DE always finds it,
# then force-refresh all caches so no stale copy is shown.
ICON_SRC="$PROJECT_DIR/src/haze/assets/logo.png"
if [[ -f "$ICON_SRC" ]]; then
    echo -e "${CYAN}Installing icon...${NC}"
    # pixmaps — many DEs read this without any cache
    cp "$ICON_SRC" "$PIXMAP_DIR/$APP.png"
    # hicolor at all common sizes
    for size in 16 22 32 48 64 128 256; do
        cp "$ICON_SRC" "$HICOLOR_DIR/${size}x${size}/apps/$APP.png"
    done
    echo -e "  icon ${GREEN}✓${NC}"
else
    echo -e "  icon not found — skipping"
fi

# ── Desktop entry ────────────────────────────────────────────────────
# Use absolute path to logo.png so the DE reads the file directly —
# no icon theme cache lookup, always shows the current file on disk.
ICON_PATH="$PIXMAP_DIR/$APP.png"
[[ ! -f "$ICON_PATH" ]] && ICON_PATH="$PROJECT_DIR/src/haze/assets/logo.png"

cat > "$DESKTOP_DIR/$APP.desktop" <<DESKTOP_EOF
[Desktop Entry]
Name=Haze
Comment=Anonymous encrypted P2P chat over Tor — E2E encrypted, no logs
Exec=$BIN_DIR/$APP
Icon=$ICON_PATH
Terminal=false
Type=Application
Categories=Network;Chat;Security;
StartupWMClass=Haze
Keywords=tor;anonymous;chat;encrypted;p2p;privacy;security;haze;
DESKTOP_EOF

# ── Refresh all caches ───────────────────────────────────────────────
echo -e "${CYAN}Refreshing icon and desktop caches...${NC}"
refresh_icon_cache
echo -e "  caches ${GREEN}✓${NC}"

# ── Done ─────────────────────────────────────────────────────────────
echo -e "\n${GREEN}${BOLD}Haze installed successfully!${NC}"
echo ""
echo -e "  Launch    : ${BOLD}haze${NC}"
echo -e "  (or open 'Haze' from your application menu)"
echo ""
echo -e "  Uninstall : ${BOLD}bash $SCRIPT_DIR/install.sh --uninstall${NC}"

if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo ""
    echo -e "${RED}Note:${NC} ~/.local/bin is not in your PATH."
    echo "  Add this to your shell config:"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi
