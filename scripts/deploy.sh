#!/bin/bash
# Quick environment bootstrap for Stage 1 and Stage 2 workflows.
# Target: Ubuntu 22.04 LTS x86_64
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log() { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
info() { echo -e "${CYAN}[INFO]${NC} $*"; }
err() { echo -e "${RED}[ERR]${NC} $*" >&2; exit 1; }

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/.venv}"
PYTHON="${PYTHON:-python3.11}"
SWE_SMITH_REF="${SWE_SMITH_REF:-$PROJECT_DIR/Reference/SWE-smith}"

info "coding-agent Stage 1/2 deployment"
info "Project: $PROJECT_DIR"

[[ "$(uname -s)" == "Linux" ]] || err "This script targets Linux/Ubuntu."

if [[ -f /etc/os-release ]]; then
    source /etc/os-release
    info "Detected: $NAME $VERSION_ID"
    [[ "${VERSION_ID:-}" =~ ^22 ]] || warn "Ubuntu 22.04 is the tested target; continuing anyway."
fi

info "Installing system packages"
sudo apt-get update -qq
REQUIRED_PKGS="python3.11 python3.11-venv python3.11-dev python3-pip git curl ca-certificates build-essential"
MISSING=""
for pkg in $REQUIRED_PKGS; do
    dpkg -s "$pkg" >/dev/null 2>&1 || MISSING="$MISSING $pkg"
done
if [[ -n "$MISSING" ]]; then
    sudo apt-get install -y -qq $MISSING
else
    log "System packages already installed"
fi

info "Checking Docker"
if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    warn "Docker installed. You may need to log out and back in for group permissions."
else
    log "Docker found: $(docker --version)"
fi

if ! docker info >/dev/null 2>&1; then
    sudo systemctl start docker
    sudo systemctl enable docker >/dev/null 2>&1 || true
    docker info >/dev/null 2>&1 || err "Docker daemon is not available."
fi
log "Docker daemon is running"

info "Creating Python environment"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    "$PYTHON" -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip -q
python -m pip install -e "$PROJECT_DIR" -q
python -m pip install swebench datasets docker ghapi GitPython chardet python-dotenv unidiff -q
log "Python dependencies installed"

info "Checking SWE-smith reference checkout"
if [[ -d "$SWE_SMITH_REF/swesmith/profiles" ]]; then
    log "SWE-smith reference found: $SWE_SMITH_REF"
else
    mkdir -p "$(dirname "$SWE_SMITH_REF")"
    git clone https://github.com/SWE-bench/SWE-smith.git "$SWE_SMITH_REF"
fi

info "Writing stage environment templates"
cat > "$PROJECT_DIR/.env.stage1.example" <<'ENV_STAGE1'
# Stage 1: local vLLM for Qwen2.5-Coder-7B-Instruct on SWE-Bench Lite.
PROVIDER=openai-compatible
MODEL=Qwen/Qwen2.5-Coder-7B-Instruct
API_KEY=EMPTY
BASE_URL=http://127.0.0.1:8000/v1

# Stage-specific aliases used by the config loader.
STAGE1_PROVIDER=openai-compatible
STAGE1_MODEL=Qwen/Qwen2.5-Coder-7B-Instruct
STAGE1_API_KEY=EMPTY
STAGE1_BASE_URL=http://127.0.0.1:8000/v1
ENV_STAGE1

cat > "$PROJECT_DIR/.env.stage2.example" <<'ENV_STAGE2'
# Stage 2: teacher model API for high-quality SWE-smith trajectories.
PROVIDER=deepseek
MODEL=deepseek-v4-pro
API_KEY=your-api-key
BASE_URL=https://api.deepseek.com

# Stage-specific aliases used by the config loader and scripts.
TEACHER_MODEL=deepseek-v4-pro
STAGE2_PROVIDER=deepseek
STAGE2_MODEL=deepseek-v4-pro
STAGE2_API_KEY=your-api-key
STAGE2_BASE_URL=https://api.deepseek.com
ENV_STAGE2

if [[ ! -f "$PROJECT_DIR/.env.stage1" ]]; then
    cp "$PROJECT_DIR/.env.stage1.example" "$PROJECT_DIR/.env.stage1"
    warn "Created .env.stage1 from example. Edit it if your local vLLM endpoint differs."
fi

if [[ ! -f "$PROJECT_DIR/.env.stage2" ]]; then
    cp "$PROJECT_DIR/.env.stage2.example" "$PROJECT_DIR/.env.stage2"
    warn "Created .env.stage2 from example. Add real teacher API credentials before Stage 2."
fi

chmod +x "$PROJECT_DIR/scripts/run_stage1_qwen_vllm.sh" \
    "$PROJECT_DIR/scripts/run_stage2_teacher_trajectories.sh" \
    "$PROJECT_DIR/scripts/run_sft_pipeline.sh"

echo ""
echo "Deployment complete"
echo ""
echo "Stage 1: local vLLM, SWE-Bench Lite, Qwen2.5-Coder-7B-Instruct"
echo "  1. Start vLLM separately, for example with Qwen/Qwen2.5-Coder-7B-Instruct on port 8000."
echo "  2. Edit .env.stage1 if needed."
echo "  3. DATASET=/path/to/swebench_lite.parquet ./scripts/run_stage1_qwen_vllm.sh"
echo ""
echo "Stage 2: teacher model API, SWE-smith trajectories"
echo "  1. Edit .env.stage2 with STAGE2_API_KEY, STAGE2_PROVIDER, STAGE2_BASE_URL, and TEACHER_MODEL."
echo "  2. ./scripts/run_stage2_teacher_trajectories.sh"
echo ""
echo "Compatibility wrapper:"
echo "  ./scripts/run_sft_pipeline.sh"
