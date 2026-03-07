#!/bin/bash
# ============================================================================
# AIChat Setup Script for Ubuntu/Debian
# Extended Features by Lee Ostadi (https://github.com/lostadi)
# ============================================================================
#
# This script sets up AIChat with all extended features:
# - Web Search (SearXNG integration)
# - Deep Search (RAG pipeline with Ollama)
# - Daemon Mode
# - Enhanced Shell Execution
# - Multi-Agent Arena
#
# Usage: ./setup_ubuntu.sh
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo "AIChat Setup for Ubuntu/Debian"
echo "Extended Features by Lee Ostadi"
echo "========================================"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Check if running on Ubuntu/Debian
if ! command -v apt &> /dev/null; then
    error "This script is designed for Ubuntu/Debian systems with apt package manager."
fi

# Step 1: Install system dependencies
info "Installing system dependencies..."
sudo apt update
sudo apt install -y \
    build-essential \
    curl \
    git \
    jq \
    python3 \
    python3-pip \
    python3-venv \
    docker.io \
    docker-compose-v2 || sudo apt install -y docker-compose

# Step 2: Setup Docker permissions and enable service
info "Setting up Docker permissions..."
sudo systemctl enable docker
sudo systemctl start docker
if ! groups | grep -q docker; then
    sudo usermod -aG docker "$USER"
    warn "Added $USER to docker group. You may need to log out and back in for this to take effect."
fi

# Step 3: Check/Install Rust
if ! command -v cargo &> /dev/null; then
    info "Installing Rust..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    source "$HOME/.cargo/env"
else
    info "Rust is already installed: $(cargo --version)"
fi

# Step 4: Build AIChat
info "Building AIChat (release mode)..."
cargo build --release

# Step 5: Install Python dependencies
info "Installing Python dependencies for Deep Search..."
pip3 install --user -r aichat_py_root/web_search_rag/requirements.txt

# Step 6: Make scripts executable
info "Making scripts executable..."
chmod +x functions/bin/web_search 2>/dev/null || true
chmod +x functions/bin/execute_shell_command 2>/dev/null || true
chmod +x scripts/searxng/manage_searxng.sh 2>/dev/null || true

# Step 7: Install Ollama (optional but recommended)
if ! command -v ollama &> /dev/null; then
    info "Installing Ollama for local LLM support..."
    curl -fsSL https://ollama.com/install.sh | sh
    
    info "Pulling embedding model..."
    ollama pull nomic-embed-text
    
    info "Pulling a default chat model..."
    ollama pull llama3.2:1b
else
    info "Ollama is already installed: $(ollama --version 2>/dev/null || echo 'version unknown')"
fi

# Step 8: Setup config
CONFIG_DIR="$HOME/.config/aichat"
if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
    info "Creating default configuration..."
    mkdir -p "$CONFIG_DIR"
    cat > "$CONFIG_DIR/config.yaml" << 'EOF'
# AIChat Configuration
# Extended Features by Lee Ostadi
# 
# Add your API keys below. Available providers:
# - Gemini: Set GEMINI_API_KEY environment variable or add api_key here
# - OpenRouter: Set OPENROUTER_API_KEY or add api_key here
# - Ollama: No API key needed (local)

# Default model - uses Ollama (local, no API key needed)
model: ollama:llama3.2:1b

# ---- function-calling ----
function_calling: true
use_tools: web_search

clients:
  # Ollama - Local models (no API key required)
  - type: openai-compatible
    name: ollama
    api_base: http://localhost:11434/v1
    models:
      - name: llama3.2:1b
        max_input_tokens: 8192
      - name: llama3.2:3b
        max_input_tokens: 8192
      - name: nomic-embed-text:latest
        type: embedding
        max_input_tokens: 8192

  # Gemini - Google AI (free tier available)
  # Get API key from: https://aistudio.google.com/apikey
  - type: gemini
    # api_key: YOUR_GEMINI_API_KEY_HERE
    models:
      - name: gemini-2.0-flash-exp
        max_input_tokens: 1048576
      - name: gemini-1.5-flash
        max_input_tokens: 1048576

  # OpenRouter - Access multiple models with one API key
  # Get API key from: https://openrouter.ai/keys
  - type: openai-compatible
    name: openrouter
    api_base: https://openrouter.ai/api/v1
    # api_key: YOUR_OPENROUTER_API_KEY_HERE
    models:
      - name: google/gemma-3-27b-it:free
        max_input_tokens: 131072
      - name: meta-llama/llama-3.3-70b-instruct:free
        max_input_tokens: 131072
EOF
    info "Config created at $CONFIG_DIR/config.yaml"
    warn "Edit this file to add your API keys for cloud providers."
else
    info "Config already exists at $CONFIG_DIR/config.yaml"
fi

# Step 9: Install binary
info "Installing aichat to ~/.local/bin..."
mkdir -p "$HOME/.local/bin"
cp target/release/aichat "$HOME/.local/bin/aichat"
chmod +x "$HOME/.local/bin/aichat"

# Add to PATH if not already
if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
    export PATH="$HOME/.local/bin:$PATH"
    info "Added ~/.local/bin to PATH in ~/.bashrc"
fi

# Step 10: Start SearXNG (for web search)
info "Starting SearXNG container for web search..."
if command -v docker &> /dev/null; then
    # Use sg to activate the docker group in this session without requiring re-login
    sg docker -c "docker compose -f '$SCRIPT_DIR/scripts/searxng/docker-compose.yml' up -d" 2>/dev/null \
        || warn "Could not start SearXNG. Run './scripts/searxng/manage_searxng.sh start' after logging out and back in."
fi

echo ""
echo "========================================"
echo -e "${GREEN}Setup Complete!${NC}"
echo "========================================"
echo ""
echo "Extended Features by Lee Ostadi:"
echo "  • Web Search:    aichat --search \"query\""
echo "  • Deep Search:   aichat --deep-search \"query\""
echo "  • Shell Execute: aichat --exec \"command\""
echo "  • Daemon Mode:   aichat --daemon"
echo "  • REPL Mode:     aichat  (then use .help)"
echo ""
echo "Configuration: ~/.config/aichat/config.yaml"
echo ""
echo "Quick test commands:"
echo "  aichat --help"
echo "  aichat --search \"hello world\""
echo "  aichat \"What is 2+2?\""
echo ""
if ! groups | grep -q docker; then
    warn "NOTE: Log out and back in, or run 'newgrp docker' to use Docker features."
fi
echo "========================================"
