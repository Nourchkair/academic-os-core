#!/bin/sh
set -eu

fail() {
    printf 'Academia OS installer: %s\n' "$1" >&2
    exit 1
}

info() {
    printf 'Academia OS installer: %s\n' "$1"
}

REPOSITORY_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON_BIN=${PYTHON_BIN:-python3}
NPM_BIN=${NPM_BIN:-npm}
VENV_DIR=${ACADEMIA_OS_VENV:-"$REPOSITORY_ROOT/.venv"}
BIN_DIR=${ACADEMIA_OS_BIN_DIR:-"$HOME/.local/bin"}
ZSHRC=${ACADEMIA_OS_ZSHRC:-"$HOME/.zshrc"}

case "$VENV_DIR" in
    /*) ;;
    *) VENV_DIR="$REPOSITORY_ROOT/$VENV_DIR" ;;
esac
case "$BIN_DIR" in
    /*) ;;
    *) BIN_DIR="$HOME/$BIN_DIR" ;;
esac
case "$ZSHRC" in
    /*) ;;
    *) ZSHRC="$HOME/$ZSHRC" ;;
esac

[ -f "$REPOSITORY_ROOT/pyproject.toml" ] || fail "run this script from an Academia OS repository checkout"
[ -f "$REPOSITORY_ROOT/frontend/package-lock.json" ] || fail "frontend/package-lock.json is missing"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "Python 3.11+ is required; install Python and try again"
command -v "$NPM_BIN" >/dev/null 2>&1 || fail "npm is required to build the dashboard; install Node.js and try again"
"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' || fail "Python 3.11+ is required"

info "creating or updating the local Python environment"
"$PYTHON_BIN" -m venv "$VENV_DIR"
[ -x "$VENV_DIR/bin/python" ] || fail "the Python environment was not created at $VENV_DIR"
info "installing Academia OS"
"$VENV_DIR/bin/python" -m pip install -e "$REPOSITORY_ROOT"

info "installing locked frontend dependencies"
(
    cd "$REPOSITORY_ROOT/frontend"
    "$NPM_BIN" ci
    info "building the browser dashboard"
    "$NPM_BIN" run build
)

TARGET="$VENV_DIR/bin/academia"
[ -x "$TARGET" ] || fail "the Academia OS launcher was not created at $TARGET"
mkdir -p "$BIN_DIR"
LAUNCHER="$BIN_DIR/academia"
if [ -L "$LAUNCHER" ]; then
    CURRENT_TARGET=$(readlink "$LAUNCHER")
    [ "$CURRENT_TARGET" = "$TARGET" ] || fail "$LAUNCHER already points to a different command; refusing to replace it"
elif [ -e "$LAUNCHER" ]; then
    fail "$LAUNCHER already exists and is not an Academia OS launcher; refusing to replace it"
else
    ln -s "$TARGET" "$LAUNCHER"
fi

PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
PATH_CONFIGURED=0
if [ -f "$ZSHRC" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        if [ "$line" = "$PATH_LINE" ]; then
            PATH_CONFIGURED=1
            break
        fi
    done < "$ZSHRC"
fi
if [ "$PATH_CONFIGURED" -eq 0 ]; then
    {
        printf '\n# Academia OS local launcher\n'
        printf '%s\n' "$PATH_LINE"
    } >> "$ZSHRC"
fi

printf '\nAcademia OS is ready.\n'
printf 'Launcher: %s\n' "$LAUNCHER"
printf 'Open a new Terminal, or run: source %s\n' "$ZSHRC"
printf 'Then type: academia\n'
