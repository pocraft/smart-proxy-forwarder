# Changelog

## v1.3 (2026-06-04)

### Added
- FanVPN auto-detect (`--auto-detect-fanvpn`) — follow Chrome extension node switches
- MCP server (`deploy/proxy_forwarder_mcp.py`) — 6 AI agent management tools
- Auto-update detection (`--check-update`) — compares against GitHub release
- Config validation — validates config.json fields on startup
- `proxy-manager.sh export/import` — config backup and restore
- Health check now tests real proxy functionality, not just TCP port

### Changed
- FanVPN Chrome extension path auto-detects Windows username (removed hardcoded path)
- SOCKS5 health check now performs real SOCKS5 handshake
- README updated to include all 17 features
- Code quality: removed unused variables, fixed exception handling

### Fixed
- auto_detect_fanvpn now reads last active node, not first
- port_match regex now properly extracts port with DOTALL flag
- flake8 lint issues (line length, F541, E302)

## v1.2 (2026-05-30)

### Added
- Web dashboard (`http://127.0.0.1:10809/`) — live status page, refreshes every 5s
- Multi-upstream failover — comma-separated `--remote-host "a.com,b.com"`
- TLS connection pool (`--pool-size`) — reuses connections, reduces handshake latency
- SOCKS5 upstream support (`--upstream-type socks5`)
- Bilingual dashboard (Chinese / English toggle)
- `proxy-manager.sh logs` command — quick log viewing

### Changed
- Dashboard shows upstream type, pool size, active upstream
- Stats JSON includes `upstream_type` and `pool_size` fields

### Fixed
- Connection pool no longer returns consumed connections to pool
- Pool acquire uses `getpeername()` instead of sending test data
- All tests pass without ResourceWarning

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
