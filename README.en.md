# Smart Proxy Forwarder

A lightweight, DNS-leak-free CONNECT proxy with automatic China IP routing.
**Domestic → direct | International → via remote HTTPS proxy.**

Designed for WSL users behind China's firewall who want their terminal tools
(curl, git, npm, Python, AI agents) to enjoy the same connectivity as their
browser VPN, **without leaking DNS queries**.

---

## How It Works

```
Your apps (curl / git / npm / Python / agent-browser)
    │  http_proxy=http://127.0.0.1:10808
    ▼
┌─ proxy_forwarder.py ──────────────────────────────┐
│                                                    │
│  Domain in the whitelist? (Baidu, DeepSeek, etc.)  │
│    → Direct connection (fast)                      │
│                                                    │
│  Raw IP address?                                   │
│    → Check China CIDR set → Direct / Proxy         │
│                                                    │
│  Other hostnames                                   │
│    → Default to proxy (DNS-safe, no leak)          │
│      └─ TLS tunnel → your proxy → internet         │
└────────────────────────────────────────────────────┘
```

**No DNS leak:** routing decisions never resolve hostnames locally.
Only the proxy server itself is resolved once per session via system DNS
— unavoidable, just like any VPN.

---

## Requirements

- **Python 3.8+** (stdlib only — no pip dependencies)
- **Linux / WSL2**
- An **HTTPS CONNECT proxy server** (e.g., your Chrome VPN extension's
  upstream server, a VPS running squid/caddy, etc.)

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/601494530-create/smart-proxy-forwarder.git
cd smart-proxy-forwarder

# 2. One-click install (provide your proxy server)
bash setup.sh your-proxy.example.com 443

# 2a. If your proxy uses a self-signed cert, add a 3rd argument:
bash setup.sh your-proxy.example.com 443 true

# 3. Restart terminal or source
source ~/.bashrc
# If using zsh: source ~/.zshrc

# 4. Verify
curl -v https://www.google.com    # → should work (via proxy)
curl -v https://www.baidu.com     # → should also work (direct, faster)
```

---

## Manual Setup

### 1. Start the forwarder

```bash
python3 proxy_forwarder.py \
    --remote-host your-proxy.example.com \
    --remote-port 443 \
    --listen-port 10808
```

Or via pip:
```bash
pip install .
proxy-forwarder --remote-host your-proxy.example.com --remote-port 443
```

### 2. Set proxy env vars

```bash
export http_proxy=http://127.0.0.1:10808
export https_proxy=http://127.0.0.1:10808
export no_proxy="localhost,127.0.0.1,::1,api.deepseek.com,*.deepseek.com,\
*.baidu.com,*.qq.com,*.aliyun.com,*.taobao.com,*.jd.com,*.weixin.qq.com,\
10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
```

### 3. (Optional) Configure git & npm

```bash
git config --global http.proxy http://127.0.0.1:10808
npm config set proxy http://127.0.0.1:10808
npm config set https-proxy http://127.0.0.1:10808
```

### 4. Auto-start

Run `setup.sh` to auto-configure, or append `bash-integration.sh` to `~/.bashrc` / `~/.zshrc`.

---

## CLI Reference

| Argument | Default | Description |
|----------|---------|-------------|
| `--listen-host` | `127.0.0.1` | Local listen address |
| `--listen-port` | `10808` | Local listen port |
| `--remote-host` | **(required)** | Remote HTTPS CONNECT proxy host |
| `--remote-port` | `443` | Remote proxy port |
| `--config` | `""` | Path to JSON config file |
| `--insecure` / `-k` | `false` | Skip TLS certificate verification |
| `--log-requests` | `false` | Log each CONNECT target, route, timing |
| `--api-port` | `10809` | REST API port for live stats |
| `--version` | - | Show version |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PROXY_PORT` | `10808` | Override port in all scripts |
| `PROXY_LOG` | `/tmp/proxy-forwarder.log` | Log file path |
| `XDG_CONFIG_HOME` | `~/.config` | Config directory base |

### Config file (`config.json`)

Installed at `~/.config/proxy-forwarder/config.json`:

```json
{
  "remote": { "host": "your-proxy.com", "port": 443 },
  "listen": { "host": "127.0.0.1", "port": 10808 },
  "insecure": false,
  "log_requests": false,
  "china_ip_list_url": "",
  "direct_domains": ["*.my-corp.com"]
}
```

CLI args override config file values.

---

## Management

```bash
bash ~/.config/proxy-forwarder/proxy-manager.sh status
bash ~/.config/proxy-forwarder/proxy-manager.sh restart
bash ~/.config/proxy-forwarder/proxy-manager.sh stop
bash ~/.config/proxy-forwarder/proxy-manager.sh start

# Switch port
PROXY_PORT=9090 bash ~/.config/proxy-forwarder/proxy-manager.sh start
```

### Sample output:
```
  Running
   PID:      7808
   Port:     10808
   RAM:      27MB
   Uptime:   1h23m
   Conns:    42 total, 0 active
   Traffic:  2343 KB (22 KB ↓ / 2321 KB ↑)
   Health:   ✅ alive
```

---

## REST API

```bash
curl http://127.0.0.1:10809/stats
# → {"uptime": "1h23m", "connections": 42, "health": "alive", ...}
```

---

## Request Logging

```bash
python3 proxy_forwarder.py --remote-host x.com --log-requests
# [14:00:01] www.google.com:443 → proxy (DNS-safe) 2.1s
# [14:00:02] www.baidu.com:443 → direct (direct-domain) 0.1s
```

---

## DNS Leak Protection

The forwarder **never performs local DNS resolution** for routing decisions:

1. Direct domain whitelist → no DNS needed
2. Raw IP address → checked against built-in China CIDR set
3. Other hostnames → **default to proxy** without resolving locally

The only DNS query leaving your machine is for the proxy server
itself (`--remote-host`) — a single, unavoidable lookup.

---

## Security

- **TLS certificate verification is ON by default.** Use `--insecure`/`-k` if
  your proxy uses a self-signed cert:
  ```bash
  python3 proxy_forwarder.py --remote-host example.com --insecure
  ```
- `--insecure` exposes you to MITM attacks — only use with **trusted proxies**
- Actual traffic content is end-to-end encrypted (your tool → target server)
- REST API and proxy port bind to `127.0.0.1` only (not exposed to LAN)

---

## Docker

```bash
docker build -t proxy-forwarder .
docker run -d --restart unless-stopped --name proxy \
  -p 10808:10808 \
  -e REMOTE_HOST=your-proxy.com \
  proxy-forwarder
```

---

## systemd

```bash
sudo cp deploy/proxy-forwarder.service /etc/systemd/system/
sudo systemctl enable proxy-forwarder
sudo systemctl start proxy-forwarder
```

---

## Project Files

| File | Description |
|------|-------------|
| `proxy_forwarder.py` | Core forwarder (533 lines, pure Python stdlib) |
| `proxy-manager.sh` | Management script |
| `setup.sh` | One-click install |
| `bash-integration.sh` | Shell integration snippet |
| `config.example.json` | Config template |
| `deploy/proxy-forwarder.service` | systemd service unit |
| `Dockerfile` | Container build |
| `tests/` | 42 unit + integration tests |

Compatible with any HTTPS CONNECT proxy (Chrome VPN extensions, Squid,
Caddy, mitmproxy, etc.).

---

## License

MIT
