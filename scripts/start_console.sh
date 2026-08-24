#!/usr/bin/env bash
#
# One-shot setup + launch for the Candidate Sourcing Console (FastAPI + React).
# Designed for a non-technical user on macOS: installs everything that's
# missing (Homebrew, Python 3.11, Node, Python/npm packages, Playwright's
# Chromium), then starts the backend and frontend and opens the app in the
# browser. Safe to re-run any time - it skips anything already installed.
#
# Usage: double-click "Start Console.command" at the repo root, or run:
#   bash scripts/start_console.sh

set -euo pipefail
set -m # job control, so `kill %1 %2` on exit also kills child processes (e.g. vite under npm)

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOGDIR="$ROOT/.logs"
mkdir -p "$LOGDIR"

BOLD="\033[1m"; GREEN="\033[32m"; YELLOW="\033[33m"; RED="\033[31m"; RESET="\033[0m"
info()  { echo -e "${BOLD}==>${RESET} $1"; }
ok()    { echo -e "${GREEN}✓${RESET} $1"; }
warn()  { echo -e "${YELLOW}!${RESET} $1"; }
fail()  { echo -e "${RED}✗ $1${RESET}"; exit 1; }

BACKEND_PID=""
FRONTEND_PID=""
cleanup() {
    echo
    info "Shutting down..."
    kill %1 %2 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

free_port() {
    local port="$1"
    local pids
    pids="$(lsof -ti "tcp:$port" 2>/dev/null || true)"
    if [ -n "$pids" ]; then
        warn "Port $port is already in use (probably a previous run) - stopping it."
        kill $pids 2>/dev/null || true
        sleep 1
    fi
}

wait_for_url() {
    local url="$1" name="$2" logfile="$3"
    local tries=60
    while [ $tries -gt 0 ]; do
        if curl -fsS "$url" -o /dev/null 2>/dev/null; then
            ok "$name is up."
            return 0
        fi
        sleep 1
        tries=$((tries - 1))
    done
    fail "$name didn't start in time. Last 30 lines of its log ($logfile):\n$(tail -n 30 "$logfile" 2>/dev/null)"
}

echo -e "${BOLD}Candidate Sourcing Console - setup & launch${RESET}"
echo "This will install anything missing, then start the app."
echo

# ---------------------------------------------------------------------------
# 1. Homebrew
# ---------------------------------------------------------------------------
info "Checking for Homebrew..."
if ! command -v brew >/dev/null 2>&1; then
    info "Homebrew not found - installing it (you may be asked for your Mac password)..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    if [ -x /opt/homebrew/bin/brew ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [ -x /usr/local/bin/brew ]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
fi
command -v brew >/dev/null 2>&1 || fail "Homebrew install failed - please install it manually from https://brew.sh and re-run this script."
ok "Homebrew ready."

# ---------------------------------------------------------------------------
# 2. git (needed to pull updates; usually already present via Xcode CLT)
# ---------------------------------------------------------------------------
info "Checking for git..."
if ! command -v git >/dev/null 2>&1; then
    brew install git
fi
ok "git ready."

# ---------------------------------------------------------------------------
# 3. Python 3.11
# ---------------------------------------------------------------------------
info "Checking for Python 3.11..."
brew list python@3.11 >/dev/null 2>&1 || brew install python@3.11
PYTHON_BIN="$(brew --prefix python@3.11)/bin/python3.11"
[ -x "$PYTHON_BIN" ] || fail "Could not find Python 3.11 after installing it via Homebrew."
ok "Python ready ($("$PYTHON_BIN" --version))."

# ---------------------------------------------------------------------------
# 4. Node.js (for the frontend)
# ---------------------------------------------------------------------------
info "Checking for Node.js..."
brew list node >/dev/null 2>&1 || brew install node
command -v npm >/dev/null 2>&1 || fail "npm not found after installing Node via Homebrew."
ok "Node ready ($(node --version))."

# ---------------------------------------------------------------------------
# 5. Python virtual environment + backend dependencies
# ---------------------------------------------------------------------------
info "Setting up the Python environment..."
if [ ! -d "$ROOT/venv" ]; then
    "$PYTHON_BIN" -m venv "$ROOT/venv"
fi
"$ROOT/venv/bin/pip" install --upgrade pip >/dev/null
info "Installing backend dependencies (this can take a few minutes the first time)..."
"$ROOT/venv/bin/pip" install -e "$ROOT[web,crew,export]"
ok "Backend dependencies installed."

info "Installing the browser used for LinkedIn scraping (Chromium)..."
"$ROOT/venv/bin/playwright" install chromium
ok "Chromium ready."

# ---------------------------------------------------------------------------
# 6. .env (API keys / credentials)
# ---------------------------------------------------------------------------
if [ ! -f "$ROOT/.env" ]; then
    info "No .env file found - creating one from the template."
    cp "$ROOT/.env.example" "$ROOT/.env"
    warn "A text file called .env just opened. Fill in whichever keys you have"
    warn "(LinkedIn login, GITHUB_TOKEN, ANTHROPIC_API_KEY, SERPER_API_KEY),"
    warn "save the file, then come back here."
    open -e "$ROOT/.env" 2>/dev/null || true
    read -r -p "Press Enter once you've saved .env (or just press Enter to skip for now)... "
else
    ok "Found an existing .env - leaving it as is."
fi

# ---------------------------------------------------------------------------
# 7. Frontend dependencies
# ---------------------------------------------------------------------------
info "Installing frontend dependencies (this can take a minute)..."
(cd "$ROOT/frontend" && npm install --no-fund --no-audit)
ok "Frontend dependencies installed."

# ---------------------------------------------------------------------------
# 8. Launch backend + frontend
# ---------------------------------------------------------------------------
free_port 8000
free_port 5173

info "Starting the backend..."
(cd "$ROOT" && exec "$ROOT/venv/bin/uvicorn" backend.main:app --port 8000) > "$LOGDIR/backend.log" 2>&1 &
BACKEND_PID=$!
wait_for_url "http://127.0.0.1:8000/api/health" "Backend" "$LOGDIR/backend.log"

info "Starting the frontend..."
(cd "$ROOT/frontend" && exec npm run dev) > "$LOGDIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
wait_for_url "http://localhost:5173" "Frontend" "$LOGDIR/frontend.log"

echo
ok "Everything is running."
info "Opening the app in your browser..."
open "http://localhost:5173"

echo
echo -e "${BOLD}The console is running at http://localhost:5173${RESET}"
echo "Leave this window open while you use it. Press Ctrl+C here (or close this window) to stop it."
echo

wait
