# Changelog

## v1.1 (2026-05-30)

### Added
- Request logging (`--log-requests`) — per-request target, route, timing
- REST API (`http://127.0.0.1:10809/stats`) — real-time JSON stats
- Connection statistics — total/active connections, traffic volume, uptime
- Health checking — background thread tests remote proxy every 30s
- `deploy/proxy-forwarder.service` — systemd service file
- Dockerfile — container support

### Changed
- Install path: `~/.hermes/` → `~/.config/proxy-forwarder/` (XDG standard)
- Shell support: auto-detect `.bashrc` / `.zshrc`
- Port configuration unified via `$PROXY_PORT` env var
- `proxy-manager.sh` now displays stats, health, traffic
- `relay_traffic` polls shutdown_event every 1s (was 300s timeout)
- Domain whitelist: `*.aliyun.com` covers subdomains

### Fixed
- TLS certificate verification defaults to ON (`--insecure` to disable)
- ChinaIPSet cache duplication when URL download fails
- Proxy-manager.sh fails gracefully without config file
- CI flake8 invalid ignore code E24 → E241

## v1.0.0 (2026-05-30)

### Added
- Initial release
- CONNECT proxy with China IP auto-routing
- DNS leak-free routing (no local DNS for routing decisions)
- Built-in China CIDR set (44 ranges) + domain whitelist (60 rules)
- Bidirectional TCP relay with 5-min idle timeout
- One-click setup script (`setup.sh`)
- Bash integration (auto-start + env vars)
- pip install support (pyproject.toml)
- 16 unit tests
- GitHub Actions CI
