#!/bin/bash
# Smart Proxy Forwarder — management script
PORT="${PROXY_PORT:-10808}"
LOG_FILE="${PROXY_LOG:-/tmp/proxy-forwarder.log}"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/proxy-forwarder"
CONFIG_FILE="$CONFIG_DIR/config.json"
PID_FILE="/tmp/proxy-forwarder.pid"

forwarder_pid() {
    pgrep -f "^python3.*proxy_forwarder\.py" | head -1
}

_port_check() {
    if command -v ss &>/dev/null; then
        ss -tlnp 2>/dev/null | grep -q ":$PORT "
    elif [ -f /proc/net/tcp ]; then
        local hex_port=$(printf "%04X" "$PORT")
        grep -q ":$hex_port " /proc/net/tcp 2>/dev/null
    else
        # curl-based check as last resort
        curl -s -o /dev/null --connect-timeout 1 http://127.0.0.1:$PORT/ 2>/dev/null
        return $?
    fi
}

start() {
    local pid=$(forwarder_pid)
    if [ -n "$pid" ]; then
        echo "  Forwarder already running (PID $pid, port $PORT)"
        return 0
    fi

    if [ -f "$CONFIG_FILE" ]; then
        nohup python3 -u "$CONFIG_DIR/proxy_forwarder.py" \
            --config "$CONFIG_FILE" > "$LOG_FILE" 2>&1 &
    else
        echo "  ⚠ No config file found at $CONFIG_FILE"
        echo "  Run setup.sh first, or create the config manually:"
        echo "    bash setup.sh your-proxy.example.com 443"
        echo "    # or:"
        echo "    python3 $CONFIG_DIR/proxy_forwarder.py --remote-host your-proxy.example.com"
        return 1
    fi
    local new_pid=$!
    echo $new_pid > "$PID_FILE"

    for i in $(seq 1 10); do
        if _port_check; then break; fi
        sleep 0.5
    done

    if _port_check; then
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
        rm -f "$PID_FILE"
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
        echo "   PID:      $pid"
        echo "   Port:     $PORT"
        echo "   RAM:      ${mem}MB"
        echo "   Log:      $LOG_FILE"
        echo "   Conf:     $CONFIG_FILE"
        # Show stats from stats file
        if [ -f "/tmp/proxy-forwarder-stats.json" ]; then
            python3 -c "
import json
with open('/tmp/proxy-forwarder-stats.json') as f:
    s = json.load(f)
print(f'   Uptime:   {s[\"uptime\"]}')
print(f'   Conns:    {s[\"total_connections\"]} total, {s[\"active_connections\"]} active')
print(f'   Traffic:  {s[\"bytes_total\"]/1024:.0f} KB ({s[\"bytes_recv\"]/1024:.0f} KB ↓ / {s[\"bytes_sent\"]/1024:.0f} KB ↑)')
health = s['health']
icon = '✅' if health == 'alive' else ('❌' if health == 'dead' else '❓')
print(f'   Health:   {icon} {health}')
" 2>/dev/null
        fi
    else
        echo "  Stopped"
    fi
}

case "${1:-status}" in
    start) start ;;
    stop) stop ;;
    restart) stop; sleep 1; start ;;
    status) status ;;
    logs) tail -50 "$LOG_FILE" 2>/dev/null || echo "No log file at $LOG_FILE" ;;
    *) echo "Usage: $0 {start|stop|restart|status|logs}" ;;
esac
