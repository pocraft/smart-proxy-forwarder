#!/bin/bash
# ============================================================================
# Smart Proxy Forwarder — One-Click Setup
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FORWARDER_SRC="$SCRIPT_DIR/proxy_forwarder.py"
MANAGER_SRC="$SCRIPT_DIR/proxy-manager.sh"

echo "========================================"
echo "  Smart Proxy Forwarder — Setup"
echo "========================================"

# ── 1. Copy files to ~/.hermes/scripts ──
echo ""
echo "[1/5] Installing scripts..."
mkdir -p "$HOME/.hermes/scripts"
cp "$FORWARDER_SRC" "$HOME/.hermes/scripts/proxy_forwarder.py"
cp "$MANAGER_SRC" "$HOME/.hermes/scripts/proxy-manager.sh"
chmod +x "$HOME/.hermes/scripts/proxy_forwarder.py"
chmod +x "$HOME/.hermes/scripts/proxy-manager.sh"
cp "$SCRIPT_DIR/bash-integration.sh" "$HOME/.hermes/scripts/bash-integration.sh"
echo "  → $HOME/.hermes/scripts/proxy_forwarder.py"
echo "  → $HOME/.hermes/scripts/proxy-manager.sh"

# ── 2. Configure remote proxy ──
echo ""
echo "[2/5] Remote proxy server..."
REMOTE_HOST=""
REMOTE_PORT="443"
if [ $# -ge 1 ]; then
    REMOTE_HOST="$1"
    REMOTE_PORT="${2:-443}"
    echo "  Using: $REMOTE_HOST:$REMOTE_PORT"
else
    echo "  ⚠ No proxy host provided."
    echo "  Usage: bash setup.sh <remote-host> [remote-port] [insecure]"
    echo "  Example: bash setup.sh your-proxy.example.com 443 true"
    echo ""
    echo "  Setup will continue without a proxy server."
    echo "  You can set it later by editing:"
    echo "    $HOME/.hermes/scripts/proxy-config.json"
fi

# Save config (allow empty host — forwarder will fail with clear message)
INSECURE="${3:-false}"
cat > "$HOME/.hermes/scripts/proxy-config.json" << CONFIGEOF
{
  "remote": { "host": "$REMOTE_HOST", "port": $REMOTE_PORT },
  "listen": { "host": "127.0.0.1", "port": 10808 },
  "insecure": $INSECURE
}
CONFIGEOF
echo "  Config saved to ~/.hermes/scripts/proxy-config.json (insecure: $INSECURE)"

# ── 3. Add bash integration ──
echo ""
echo "[3/5] Adding bash integration..."
# Use a marker to detect previous install (more reliable than grep)
BASH_MARKER="# --- Smart Proxy Forwarder ---"
if grep -qF "$BASH_MARKER" "$HOME/.bashrc" 2>/dev/null; then
    echo "  Bash integration already present in ~/.bashrc (skipped)"
else
    cat >> "$HOME/.bashrc" << 'BASHEOF'

# --- Smart Proxy Forwarder ---
PROXY_SCRIPT="$HOME/.hermes/scripts/proxy_forwarder.py"
PROXY_CONFIG="$HOME/.hermes/scripts/proxy-config.json"
PROXY_LOG="/tmp/proxy-forwarder.log"

_start_proxy_forwarder() {
    if ss -tlnp 2>/dev/null | grep -q ":10808 "; then return 0; fi
    nohup python3 -u "$PROXY_SCRIPT" --config "$PROXY_CONFIG" > "$PROXY_LOG" 2>&1 &
    for i in $(seq 1 10); do
        if ss -tlnp 2>/dev/null | grep -q ":10808 "; then break; fi
        sleep 0.5
    done
}
if ! pgrep -f "proxy_forwarder.py" >/dev/null 2>&1; then
    _start_proxy_forwarder
fi

export http_proxy=http://127.0.0.1:10808
export https_proxy=http://127.0.0.1:10808
export no_proxy="localhost,127.0.0.1,::1,api.deepseek.com,*.deepseek.com,*.baidu.com,*.qq.com,*.aliyun.com,*.taobao.com,*.jd.com,*.weixin.qq.com,*.zhihu.com,*.bilibili.com,*.tuna.tsinghua.edu.cn,*.ustc.edu.cn,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
export NO_PROXY="$no_proxy"
BASHEOF
    echo "  ✓ Appended to ~/.bashrc"
fi

# ── 4. Configure git & npm proxy ──
echo ""
echo "[4/5] Configuring git & npm..."
git config --global http.proxy http://127.0.0.1:10808 2>/dev/null && echo "  ✓ git proxy set" || echo "  - git not found, skipping"
npm config set proxy http://127.0.0.1:10808 2>/dev/null && npm config set https-proxy http://127.0.0.1:10808 2>/dev/null && echo "  ✓ npm proxy set" || echo "  - npm not found, skipping"

# ── 5. Install agent-browser (optional) ──
echo ""
echo "[5/5] Optional: agent-browser for AI agents..."
if command -v agent-browser &>/dev/null; then
    echo "  ✓ agent-browser already installed"
else
    echo "  Installing agent-browser (this may take a while)..."
    if npm install -g agent-browser > /tmp/agent-browser-install.log 2>&1; then
        echo "  ✓ agent-browser installed, installing browser..."
        agent-browser install 2>&1 | tail -3 || echo "  ⚠ Browser install skipped (run 'agent-browser install' later)"
    else
        echo "  ⚠ agent-browser install failed (npm issue). You can install later with:"
        echo "    npm install -g agent-browser && agent-browser install"
    fi
fi

# ── Start ──
echo ""
echo "========================================"
echo "  Starting forwarder..."
bash "$HOME/.hermes/scripts/proxy-manager.sh" start

echo ""
echo "  ✅ Setup complete!"
echo "  Open a new terminal or run: source ~/.bashrc"
echo "  Manage with:  bash ~/.hermes/scripts/proxy-manager.sh status"
echo "========================================"
