# Changelog

## v1.2.2 (2026-06-22)

### Added
- `*.cnb.cool` 加入直连白名单 — 国内代码托管镜像站不再走代理
- `direct_domains` 配置项 — 用户可通过 config.json 自定义直连域名
- 连接类型统计 — stats JSON 新增 `socks5_connections` 和 `connect_connections` 字段

### Changed
- TLS 连接池 4 → 8 — 减少 Chrome 多路 Google 请求排队

### Fixed
- 移除未使用的 `log_prefix` 变量 — 修复 Flake8 F841 告警
- CI action 版本升级（actions/checkout@v5, actions/setup-python@v6, actions/upload-artifact@v5）— 适配 GitHub Runner Node.js 24

## v1.2.1 (2026-06-21)

### Added
- **SOCKS5 客户端支持** — 转发器自动检测 SOCKS5 和 HTTP CONNECT 客户端，无需任何配置
- **连接统计** — stats JSON 新增 `socks5_connections` 和 `connect_connections` 字段

### Fixed
- SOCKS5 客户端在代理失败时收到正确的 SOCKS5 错误帧（而非 HTTP 502）

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
