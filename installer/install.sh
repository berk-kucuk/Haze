#!/usr/bin/env bash
# Haze Installer
# Usage: bash install.sh [--uninstall] [--yes] [--no-deps]
#   --uninstall   remove Haze
#   --yes, -y     don't prompt; auto-confirm system package installation
#   --no-deps     skip system package manager step (Python-only install)

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

ASSUME_YES=false
SKIP_DEPS=false
DO_UNINSTALL=false

for arg in "$@"; do
    case "$arg" in
        --uninstall) DO_UNINSTALL=true ;;
        --yes|-y)    ASSUME_YES=true ;;
        --no-deps)   SKIP_DEPS=true ;;
        *) echo -e "${RED}Unknown option: $arg${NC}"; exit 1 ;;
    esac
done

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

[[ "$DO_UNINSTALL" == true ]] && uninstall

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

# ── Privilege helper ─────────────────────────────────────────────────
if [[ "$EUID" -eq 0 ]]; then
    SUDO=""
elif command -v sudo &>/dev/null; then
    SUDO="sudo"
else
    SUDO=""
fi

# ── Distro / package manager detection ───────────────────────────────
# Logical dependency set installed on every distro we know how to drive:
#   python3, venv+pip support, tor, portaudio (sounddevice), and the base
#   Qt6/xcb runtime libraries PyQt6 needs on a minimal or headless system.
PKG_MANAGER=""
if command -v apt-get &>/dev/null; then
    PKG_MANAGER="apt"
elif command -v pacman &>/dev/null; then
    PKG_MANAGER="pacman"
elif command -v dnf &>/dev/null; then
    PKG_MANAGER="dnf"
elif command -v zypper &>/dev/null; then
    PKG_MANAGER="zypper"
elif command -v apk &>/dev/null; then
    PKG_MANAGER="apk"
fi

install_system_deps() {
    local pkgs=()
    case "$PKG_MANAGER" in
        apt)
            pkgs=(python3 python3-venv python3-pip tor libportaudio2 \
                  libxcb-cursor0 libxkbcommon-x11-0 libdbus-1-3 libgl1 fontconfig)
            echo -e "${CYAN}Installing system packages via apt...${NC}"
            $SUDO apt-get update -y
            $SUDO apt-get install -y "${pkgs[@]}"
            ;;
        pacman)
            pkgs=(python tor portaudio libxcb libxkbcommon-x11 dbus mesa fontconfig)
            echo -e "${CYAN}Installing system packages via pacman...${NC}"
            $SUDO pacman -Sy --needed --noconfirm "${pkgs[@]}"
            ;;
        dnf)
            pkgs=(python3 python3-pip tor portaudio libxcb libxkbcommon-x11 \
                  dbus-libs mesa-libGL fontconfig)
            echo -e "${CYAN}Installing system packages via dnf...${NC}"
            $SUDO dnf install -y "${pkgs[@]}"
            ;;
        zypper)
            pkgs=(python3 python3-pip tor portaudio libxcb1 libxkbcommon-x11-0 \
                  dbus-1 Mesa-libGL1 fontconfig)
            echo -e "${CYAN}Installing system packages via zypper...${NC}"
            $SUDO zypper --non-interactive install "${pkgs[@]}"
            ;;
        apk)
            pkgs=(python3 py3-pip tor portaudio libxcb libxkbcommon dbus-libs mesa-gl fontconfig)
            echo -e "${CYAN}Installing system packages via apk...${NC}"
            $SUDO apk add --no-cache "${pkgs[@]}"
            ;;
        *)
            return 1
            ;;
    esac
}

echo -e "${CYAN}Checking dependencies...${NC}"

if [[ "$SKIP_DEPS" == true ]]; then
    echo "  Skipping system package installation (--no-deps)"
elif [[ -z "$PKG_MANAGER" ]]; then
    echo -e "${RED}Warning: no supported package manager found (apt/pacman/dnf/zypper/apk).${NC}"
    echo "  Please manually ensure these are installed: python3 (>=3.11), tor, portaudio,"
    echo "  and Qt6 runtime libraries (libxcb-cursor, libxkbcommon-x11, dbus, mesa/GL, fontconfig)."
else
    proceed=true
    if [[ "$ASSUME_YES" != true ]]; then
        echo -e "  Package manager detected: ${BOLD}$PKG_MANAGER${NC}"
        read -rp "  Install/update required system packages now (needs sudo)? [Y/n] " answer
        [[ "${answer,,}" == "n" ]] && proceed=false
    fi
    if [[ "$proceed" == true ]]; then
        if ! install_system_deps; then
            echo -e "${RED}Warning: automatic system package installation failed.${NC}"
            echo "  Continuing — Python packages may still install correctly if the"
            echo "  underlying libraries are already present."
        fi
    fi
fi

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
    echo "  openSUSE      : sudo zypper install tor"
    echo "  Alpine        : sudo apk add tor"
    echo ""
    if [[ "$ASSUME_YES" == true ]]; then
        echo "  --yes given, continuing without Tor."
    else
        read -rp "Continue installation without Tor? [y/N] " answer
        [[ "${answer,,}" != "y" ]] && exit 1
    fi
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
# mktemp, not a fixed /tmp name: a predictable path in a world-writable
# directory can be pre-created as a symlink by any other local account, and
# this redirect would then write through it.
VENV_ERR="$(mktemp -t haze-venv-err.XXXXXXXX)"
trap 'rm -f "$VENV_ERR"' EXIT
if ! python3 -m venv "$INSTALL_DIR/venv" 2>"$VENV_ERR"; then
    cat "$VENV_ERR" >&2
    echo -e "${RED}Error: failed to create the virtual environment.${NC}"
    echo "  This usually means the 'venv' module is missing (Debian/Ubuntu ship it"
    echo "  in a separate 'python3-venv' package). Install it and re-run this script."
    exit 1
fi
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
Comment=Anonymous encrypted P2P chat over Tor — E2E encrypted, no logs — for Maze Linux
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
