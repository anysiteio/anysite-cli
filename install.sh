#!/usr/bin/env bash
# install.sh — Anysite CLI installer
#
# One-line install (includes all extras by default):
#   curl -fsSL https://anysite.io/install.sh | bash
#
# Minimal install (no optional dependencies):
#   curl -fsSL https://anysite.io/install.sh | bash -s -- --extras none
#
# Upgrade:
#   curl -fsSL https://anysite.io/install.sh | bash -s -- --upgrade
#
# Uninstall:
#   curl -fsSL https://anysite.io/install.sh | bash -s -- --uninstall

set -euo pipefail

PACKAGE_NAME="anysite-cli"
COMMAND_NAME="anysite"
MIN_PYTHON="3.11"

# --- Colors (disabled when not a TTY) ---

if [[ -t 1 ]]; then
    BOLD='\033[1m'
    DIM='\033[2m'
    GREEN='\033[0;32m'
    BLUE='\033[0;34m'
    YELLOW='\033[1;33m'
    RED='\033[0;31m'
    NC='\033[0m'
else
    BOLD='' DIM='' GREEN='' BLUE='' YELLOW='' RED='' NC=''
fi

info()    { printf "${BLUE}${BOLD}==>${NC} ${BOLD}%s${NC}\n" "$1"; }
success() { printf "${GREEN}${BOLD}==>${NC} ${GREEN}${BOLD}%s${NC}\n" "$1"; }
warn()    { printf "${YELLOW}${BOLD}==>${NC} ${YELLOW}%s${NC}\n" "$1"; }
error()   { printf "${RED}${BOLD}==>${NC} ${RED}%s${NC}\n" "$1" >&2; }
dim()     { printf "    ${DIM}%s${NC}\n" "$1"; }

# --- Helpers ---

ensure_uv() {
    if command -v uv &>/dev/null; then
        info "Found uv $(uv version 2>/dev/null || echo "")"
        return 0
    fi

    info "Installing uv (fast Python package manager)..."
    echo ""

    local tmpfile
    tmpfile="$(mktemp)"
    if ! curl -LsSf https://astral.sh/uv/install.sh -o "$tmpfile"; then
        rm -f "$tmpfile"
        echo ""
        error "Failed to download uv installer"
        echo ""
        echo "  Install uv manually:"
        dim "https://docs.astral.sh/uv/getting-started/installation/"
        echo ""
        exit 1
    fi
    sh "$tmpfile"
    rm -f "$tmpfile"

    # Add uv to PATH for this session
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    if ! command -v uv &>/dev/null; then
        echo ""
        error "uv was installed but not found in PATH"
        echo ""
        echo "  Restart your terminal and run this script again."
        exit 1
    fi

    echo ""
    success "Installed uv $(uv version 2>/dev/null || echo "")"
}

build_package_spec() {
    local spec="$PACKAGE_NAME"

    if [[ -n "$EXTRAS" && "$EXTRAS" != "none" ]]; then
        spec="${spec}[${EXTRAS}]"
    fi

    if [[ -n "$VERSION" ]]; then
        spec="${spec}==${VERSION}"
    fi

    echo "$spec"
}

ensure_path() {
    local bin_dir="$HOME/.local/bin"

    # Already in PATH
    if echo "$PATH" | tr ':' '\n' | grep -qx "$bin_dir"; then
        return 0
    fi

    # Detect shell config file
    local shell_name
    shell_name="$(basename "${SHELL:-/bin/zsh}")"

    local rc_file=""
    case "$shell_name" in
        zsh)  rc_file="$HOME/.zshrc" ;;
        bash)
            if [[ -f "$HOME/.bash_profile" ]]; then
                rc_file="$HOME/.bash_profile"
            else
                rc_file="$HOME/.bashrc"
            fi
            ;;
        fish) rc_file="$HOME/.config/fish/config.fish" ;;
    esac

    if [[ -n "$rc_file" ]]; then
        # Check if already added
        if [[ -f "$rc_file" ]] && grep -q '.local/bin' "$rc_file" 2>/dev/null; then
            return 0
        fi

        echo "" >> "$rc_file"
        echo '# Added by anysite installer' >> "$rc_file"

        if [[ "$shell_name" == "fish" ]]; then
            echo "set -gx PATH \$HOME/.local/bin \$PATH" >> "$rc_file"
        else
            echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$rc_file"
        fi

        dim "Added ~/.local/bin to PATH in ${rc_file/$HOME/\~}"
    fi
}

# --- Setup (interactive API key configuration) ---

do_setup() {
    local config_file="$HOME/.anysite/config.yaml"
    local has_api_key="false"
    local has_llm_key="false"

    # Check existing config
    if [[ -f "$config_file" ]]; then
        if grep -q '^api_key:' "$config_file" 2>/dev/null; then
            has_api_key="true"
        fi
        if grep -q '^ *providers:' "$config_file" 2>/dev/null; then
            has_llm_key="true"
        fi
    fi

    # All keys already configured — skip setup entirely
    if [[ "$has_api_key" == "true" && "$has_llm_key" == "true" ]]; then
        echo ""
        echo "  Quick start:"
        dim "${COMMAND_NAME} api /api/linkedin/user user=satyanadella"
        dim "${COMMAND_NAME} --help"
        return 0
    fi

    # No TTY — show manual instructions
    if ! [[ -r /dev/tty ]]; then
        echo ""
        echo "  Quick start:"
        if [[ "$has_api_key" != "true" ]]; then
            dim "${COMMAND_NAME} auth login                              # log in via browser"
            dim "${COMMAND_NAME} config set api_key YOUR_API_KEY         # or paste key manually"
        fi
        dim "${COMMAND_NAME} api /api/linkedin/user user=satyanadella"
        dim "${COMMAND_NAME} --help"
        return 0
    fi

    echo ""
    info "Quick setup (press Enter to skip any step)"
    echo ""

    # Step 1: Anysite authentication (skip if already configured)
    if [[ "$has_api_key" == "true" ]]; then
        dim "Anysite API key: already configured"
    else
        printf "    ${BOLD}Authenticate${NC} — 1) Log in via browser  2) Paste API key  3) Skip: "
        local auth_choice=""
        read -r auth_choice < /dev/tty || true

        case "$auth_choice" in
            1)
                echo ""
                dim "Opening browser for authentication..."
                if "$COMMAND_NAME" auth login 2>/dev/null; then
                    dim "Authenticated"
                else
                    warn "Browser login failed. You can try later: ${COMMAND_NAME} auth login"
                fi
                ;;
            2)
                dim "Get your key at https://app.anysite.io"
                printf "    ${BOLD}Anysite API key${NC}: "
                local api_key=""
                read -r api_key < /dev/tty || true
                if [[ -n "$api_key" ]]; then
                    "$COMMAND_NAME" config set api_key "$api_key" &>/dev/null
                    dim "Saved"
                else
                    dim "Skipped"
                fi
                ;;
            *)
                dim "Skipped — authenticate later: ${COMMAND_NAME} auth login"
                ;;
        esac
    fi
    echo ""

    # Step 2: LLM provider choice + key (skip if already configured)
    if [[ "$has_llm_key" == "true" ]]; then
        dim "LLM provider: already configured"
    else
        dim "Keys: https://platform.openai.com/api-keys | https://console.anthropic.com/settings/keys"
        printf "    ${BOLD}LLM provider${NC} — 1) OpenAI  2) Anthropic  3) Skip: "
        local choice=""
        read -r choice < /dev/tty || true

        case "$choice" in
            1)
                printf "    ${BOLD}OpenAI API key${NC}: "
                local openai_key=""
                read -r openai_key < /dev/tty || true
                if [[ -n "$openai_key" ]]; then
                    "$COMMAND_NAME" config set llm.default_provider openai &>/dev/null
                    "$COMMAND_NAME" config set llm.providers.openai.provider openai &>/dev/null
                    "$COMMAND_NAME" config set llm.providers.openai.api_key "$openai_key" &>/dev/null
                    dim "Saved"
                else
                    dim "Skipped"
                fi
                ;;
            2)
                printf "    ${BOLD}Anthropic API key${NC}: "
                local anthropic_key=""
                read -r anthropic_key < /dev/tty || true
                if [[ -n "$anthropic_key" ]]; then
                    "$COMMAND_NAME" config set llm.default_provider anthropic &>/dev/null
                    "$COMMAND_NAME" config set llm.providers.anthropic.provider anthropic &>/dev/null
                    "$COMMAND_NAME" config set llm.providers.anthropic.api_key "$anthropic_key" &>/dev/null
                    dim "Saved"
                else
                    dim "Skipped"
                fi
                ;;
            *)
                dim "Skipped"
                ;;
        esac
    fi
    echo ""

    echo "  Next steps:"
    dim "${COMMAND_NAME} api /api/linkedin/user user=satyanadella"
    dim "${COMMAND_NAME} --help"
}

# --- Actions ---

do_install() {
    echo ""
    printf "  ${BOLD}Anysite CLI Installer${NC}\n"
    echo ""

    # Check OS
    local os
    os="$(uname -s)"
    case "$os" in
        Darwin|Linux) ;;
        *)
            error "Unsupported OS: $os"
            echo "  For Windows, use WSL: https://docs.anysite.io/cli"
            exit 1
            ;;
    esac

    # Step 1: Ensure uv is available
    ensure_uv

    # Step 2: Install anysite-cli
    local spec
    spec="$(build_package_spec)"

    echo ""
    info "Installing ${spec}..."
    echo ""

    if ! uv tool install "$spec" --python ">=${MIN_PYTHON}" --refresh; then
        echo ""
        error "Installation failed"
        echo ""
        echo "  If already installed, try:"
        dim "bash install.sh --upgrade"
        echo ""
        exit 1
    fi

    # Step 3: Ensure PATH is configured
    export PATH="$HOME/.local/bin:$PATH"
    ensure_path

    # Step 4: Verify and setup
    echo ""
    if command -v "$COMMAND_NAME" &>/dev/null; then
        local version
        version=$("$COMMAND_NAME" --version 2>/dev/null || echo "")
        success "anysite ${version} installed!"

        if [[ "$NO_SETUP" == "true" ]]; then
            echo ""
            echo "  Quick start:"
            dim "${COMMAND_NAME} auth login                              # log in via browser"
            dim "${COMMAND_NAME} config set api_key YOUR_API_KEY         # or paste key manually"
            dim "${COMMAND_NAME} api /api/linkedin/user user=satyanadella"
            dim "${COMMAND_NAME} --help"
        else
            do_setup
        fi
    else
        success "anysite installed!"
        echo ""
        warn "Restart your terminal to use the 'anysite' command."
    fi
    echo ""
}

do_upgrade() {
    echo ""
    printf "  ${BOLD}Anysite CLI Upgrade${NC}\n"
    echo ""

    ensure_uv

    local spec
    spec="$(build_package_spec)"

    echo ""
    info "Upgrading ${spec}..."
    echo ""

    uv tool install "$spec" --python ">=${MIN_PYTHON}" --force --refresh

    export PATH="$HOME/.local/bin:$PATH"

    echo ""
    if command -v "$COMMAND_NAME" &>/dev/null; then
        local version
        version=$("$COMMAND_NAME" --version 2>/dev/null || echo "")
        success "anysite ${version}"
    else
        success "Upgrade complete. Restart your terminal."
    fi
    echo ""
}

do_uninstall() {
    echo ""
    printf "  ${BOLD}Anysite CLI Uninstall${NC}\n"
    echo ""

    if command -v uv &>/dev/null; then
        info "Removing anysite-cli..."
        uv tool uninstall "$PACKAGE_NAME" || true
    else
        # Try removing the binary directly
        local bin="$HOME/.local/bin/$COMMAND_NAME"
        if [[ -f "$bin" || -L "$bin" ]]; then
            rm -f "$bin"
        fi
    fi

    echo ""
    success "anysite-cli removed"
    echo ""
    echo "  Config files are preserved at ~/.anysite/"
    dim "rm -rf ~/.anysite    # to remove config too"
    echo ""
}

usage() {
    cat <<EOF

  ${BOLD}Anysite CLI Installer${NC}

  ${BOLD}Usage:${NC}
    curl -fsSL https://anysite.io/install.sh | bash
    curl -fsSL https://anysite.io/install.sh | bash -s -- [options]

  ${BOLD}Options:${NC}
    --extras <name>   Extras to install: all (default), data, llm, db, none
    --version <ver>   Install specific version (e.g., 0.3.0)
    --no-setup        Skip interactive API key setup
    --upgrade         Upgrade to latest version
    --uninstall       Remove anysite CLI
    --help            Show this help

  ${BOLD}Examples:${NC}
    bash install.sh                        # Full install (all extras)
    bash install.sh --extras none          # Minimal install
    bash install.sh --extras data          # Only dataset pipelines
    bash install.sh --version 0.3.0        # Specific version
    bash install.sh --upgrade              # Upgrade existing install
    bash install.sh --uninstall            # Remove

EOF
}

# --- Main (stdin closed to prevent pipe conflicts with curl|bash) ---

main() {
    local ACTION="install"
    local EXTRAS="all"
    local VERSION=""
    local NO_SETUP="false"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --uninstall)  ACTION="uninstall"; shift ;;
            --upgrade)    ACTION="upgrade"; shift ;;
            --extras)     EXTRAS="${2:-}"; shift 2 ;;
            --version)    VERSION="${2:-}"; shift 2 ;;
            --no-setup)   NO_SETUP="true"; shift ;;
            --help|-h)    ACTION="help"; shift ;;
            *) error "Unknown option: $1"; exit 1 ;;
        esac
    done

    case "$ACTION" in
        install)    do_install ;;
        upgrade)    do_upgrade ;;
        uninstall)  do_uninstall ;;
        help)       usage ;;
    esac
}

main "$@" </dev/null
