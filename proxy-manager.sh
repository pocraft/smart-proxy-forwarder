#!/bin/bash
# Smart Proxy Forwarder — management script
PORT=10808
LOG_FILE="/tmp/proxy-forwarder.log"
CONFIG_FILE="$HOME/.hermes/scripts/proxy-config.json"

forwarder_pid() {
    # Match only the exact Python script, not grep or other processes
    pgrep -f "^python3.*proxy-forwarder\.py" | head -1
}

_ss_check() {
    # Use ss if available, fall back to /proc/net/tcp
    if command -v ss &>/dev/null; then
        ss -tlnp 2>/dev/null | grep -q ":$PORT "
    else
        # Check /proc/net/tcp for listening port (hex format)
        local hex_port=$(printf "%04X" "$PORT")
        grep -q ":$hex_port " /proc/net/tcp 2>/dev/null
    fi
}

start() {
    local pid=$(forwarder_pid)
    if [ -n "$pid" ]; then
        echo "  Forwarder already running (PID $pid, port $PORT)"
        return 0
    fi

    # Build and run command
    if [ -f "$CONFIG_FILE" ]; then
        nohup python3 -u "$HOME/.hermes/scripts/proxy_forwarder.py" \
            --config "$CONFIG_FILE" > "$LOG_FILE" 2>&1 &
    else
        echo "  ⚠ No config file found at $CONFIG_FILE"
        echo "  Run setup.sh first, or create the config manually:"
        echo "    bash setup.sh your-proxy.example.com 443"
        echo "    # or:"
        echo "    python3 $HOME/.hermes/scripts/proxy_forwarder.py --remote-host your-proxy.example.com"
        return 1
    fi
    local new_pid=$!

    for i in $(seq 1 10); do
        if _ss_check; then break; fi
        sleep 0.5
    done

    if _ss_check; then
        echo "  Forwarder started (PID $new_pid, port $PORT)"
    else
        echo "  Start failed, check: $LOG_FILE"
        tail -5 "$LOG_FILE" 2>/dev/null
    fi
}

stop() {
    local pid=$(forwarder_pid)
    if [ -n "$pid" ]; then
        kill "$pid" 2>/dev/null
        echo "Stopped (PID $pid)"
    else
        echo "Not running"
    fi
}

status() {
    local pid=$(forwarder_pid)
    if [ -n "$pid" ]; then
        local rss=$(ps -o rss= -p "$pid" 2>/dev/null | tr -d ' ')
        local mem=$((rss / 1024))
        echo "  Running"
        echo "   PID:   $pid"
        echo "   Port:  $PORT"
        echo "   RAM:   ${mem}MB"
        echo "   Log:   $LOG_FILE"
        echo "   Conf:  $CONFIG_FILE"
    else
        echo "  Stopped"
    fi
}

case "${1:-status}" in
    start) start ;;
    stop) stop ;;
    restart) stop; sleep 1; start ;;
    status) status ;;
    *) echo "Usage: $0 {start|stop|restart|status}" ;;
esac
