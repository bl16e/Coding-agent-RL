#!/bin/bash
# =============================================================================
# SWE-smith SFT Pipeline - One-Click Server Deployment
# Target: Ubuntu 22.04 LTS (x86_64)
# Usage: chmod +x deploy.sh && ./deploy.sh
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
NC='\033[0m'
log()  { echo -e "${GREEN}[OK]${NC}  $*"; }
warn() { echo -e "${YELLOW}[>>]${NC} $*"; }
err()  { echo -e "${RED}[!!]${NC} $*"; exit 1; }
info() { echo -e "${CYAN}[==]${NC} $*"; }

# ── Configurable paths ─────────────────────────────────────────────────────
PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/.venv}"
PYTHON="${PYTHON:-python3.11}"
SWE_SMITH_REF="${SWE_SMITH_REF:-$PROJECT_DIR/Reference/SWE-smith}"

# ── Phase 0: OS checks ─────────────────────────────────────────────────────
echo ""
info "SWE-smith SFT Pipeline Deployment"
info "Project dir : $PROJECT_DIR"
echo ""

[[ "$(uname -s)" == "Linux" ]] || err "This script targets Ubuntu 22.04 LTS only"

if [[ -f /etc/os-release ]]; then
    source /etc/os-release
    info "Detected  : $NAME $VERSION_ID"
    [[ "$VERSION_ID" =~ ^22 ]] || warn "Tested on 22.04; other versions may work but are untested"
fi

# ── Phase 1: System packages ────────────────────────────────────────────────
info "Phase 1/6: System packages..."

sudo apt-get update -qq

REQUIRED_PKGS="python3.11 python3.11-venv python3.11-dev python3-pip git curl ca-certificates build-essential"
MISSING=""
for pkg in $REQUIRED_PKGS; do
    dpkg -s "$pkg" &>/dev/null || MISSING="$MISSING $pkg"
done

if [[ -n "$MISSING" ]]; then
    warn "Installing:$MISSING"
    sudo apt-get install -y -qq $MISSING
else
    log "All system packages present"
fi

# ── Phase 2: Docker ─────────────────────────────────────────────────────────
info "Phase 2/6: Docker..."

if ! command -v docker &>/dev/null; then
    warn "Installing Docker CE..."
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    log "Docker installed (re-login may be needed for non-root use)"
else
    log "Docker $(docker --version | awk '{print $3}' | tr -d ',')"
fi

if docker info &>/dev/null 2>&1; then
    log "Docker daemon is running"
else
    warn "Starting Docker daemon..."
    sudo systemctl start docker
    sudo systemctl enable docker
    sleep 2
    docker info &>/dev/null || err "Cannot start Docker daemon"
    log "Docker daemon started"
fi

# ── Phase 3: Python environment ─────────────────────────────────────────────
info "Phase 3/6: Python virtual environment..."

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    $PYTHON -m venv "$VENV_DIR"
    log "Created venv at $VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
log "Python $(python --version)"

pip install --upgrade pip -q 2>&1 | tail -1

# ── Phase 4: Python dependencies ────────────────────────────────────────────
info "Phase 4/6: Python dependencies..."

# coding-agent itself (core)
pip install -e "$PROJECT_DIR" -q 2>&1 | tail -1

# Full dependency set for SWE-smith pipeline
PIP_DEPS=(
    swebench
    datasets
    docker
    ghapi
    GitPython
    chardet
    python-dotenv
    unidiff
)

for dep in "${PIP_DEPS[@]}"; do
    pip install "$dep" -q 2>&1 | tail -1
done

log "All Python packages installed"

# ── Phase 5: SWE-smith reference checkout ───────────────────────────────────
info "Phase 5/6: SWE-smith reference..."

if [[ -d "$SWE_SMITH_REF/swesmith/profiles" ]]; then
    log "SWE-smith reference found"
else
    warn "Cloning SWE-smith..."
    git clone https://github.com/SWE-bench/SWE-smith.git "$SWE_SMITH_REF"
    log "SWE-smith cloned to $SWE_SMITH_REF"
fi

# Count Python repos available
PYTHON_REPO_COUNT=$(python -c "
import sys; sys.path.insert(0, '$PROJECT_DIR/src')
from coding_agent.swesmith.dataset import _get_language_repo_ids
print(len(_get_language_repo_ids(['python'], reference_path='$SWE_SMITH_REF')))
" 2>/dev/null || echo "?")
info "Python repos available: $PYTHON_REPO_COUNT"

# ── Phase 6: Model config ───────────────────────────────────────────────────
info "Phase 6/6: Model configuration..."

if [[ -f "$PROJECT_DIR/.env" ]]; then
    log ".env found"
    # Show masked values
    while IFS='=' read -r key value; do
        [[ -z "$key" || "$key" == \#* ]] && continue
        masked="${value:0:4}****${value: -4}"
        info "  $key=$masked"
    done < "$PROJECT_DIR/.env"
else
    warn "Creating .env template..."
    cat > "$PROJECT_DIR/.env" <<'ENVEOF'
PROVIDER=openai
MODEL=your-model-name-here
API_KEY=your-api-key-here
BASE_URL=https://api.openai.com/v1
ENVEOF
    warn "EDIT $PROJECT_DIR/.env with your real credentials!"
fi

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "=============================================="
echo "  Deployment Complete"
echo "=============================================="
echo ""
echo "  Project   : $PROJECT_DIR"
echo "  Python    : $(python --version | awk '{print $2}')"
echo "  Docker    : $(docker --version | awk '{print $3}' | tr -d ',')"
echo "  SWE-smith : $SWE_SMITH_REF"
echo "  Python repos: $PYTHON_REPO_COUNT"
echo ""
echo "  Next steps:"
echo "    1. source $VENV_DIR/bin/activate"
echo "    2. (once) docker login"
echo "    3. ./scripts/run_sft_pipeline.sh"
echo ""
echo "  Or quick start:"
echo "    source .venv/bin/activate"
echo "    ./scripts/run_sft_pipeline.sh"
