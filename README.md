# Smart Proxy Forwarder

> **安全提示：** TLS 证书验证默认开启。如果代理服务器使用自签名证书，请加 `--insecure` 参数。

> **🌐 English version:** [README.en.md](README.en.md)

[![GitHub Release](https://img.shields.io/github/v/release/pocraft/smart-proxy-forwarder)](https://github.com/pocraft/smart-proxy-forwarder/releases)
[![Python](https://img.shields.io/badge/python-3.8+-blue)](https://github.com/pocraft/smart-proxy-forwarder)
[![License](https://img.shields.io/github/license/pocraft/smart-proxy-forwarder)](LICENSE)
[![CI](https://github.com/pocraft/smart-proxy-forwarder/actions/workflows/ci.yml/badge.svg)](https://github.com/pocraft/smart-proxy-forwarder/actions)

轻量级 DNS 防泄漏代理转发器。**国内直连、国际走远程代理**，自动分流，零依赖。同时支持 **SOCKS5** 和 **HTTP CONNECT** 客户端接入。

专为 WSL 用户设计——你在 Chrome 里用 VPN 插件能翻墙，但 WSL 终端里的 curl、git、npm、Python、AI agent 也能享受同样的能力，**且不泄漏 DNS 查询**。

---

## 功能总览

| 功能 | 说明 |
|------|------|
| ✅ **智能分流** | 域名白名单直连 / IP 查归属 / 其余默认走代理 |
| ✅ **双客户端协议** | **SOCKS5** + HTTP CONNECT 自动识别，无需配置 |
| ✅ **双上游协议** | HTTPS CONNECT（默认） + **SOCKS5** |
| ✅ **多上游/主备** | 逗号分隔多个代理，随机切换，一个挂了不影响 |
| ✅ **FanVPN 自动跟随** | 自动检测 Chrome 插件节点切换，15 秒内跟随 |
| ✅ **TLS 连接池** | 预建立 TLS 连接，减少握手延迟 |
| ✅ **Web 仪表盘** | `http://127.0.0.1:10809/` 实时状态，中英文切换 |
| ✅ **REST API** | `/stats` 返回 JSON，可对接监控系统 |
| ✅ **MCP 服务器** | 6 个 AI agent 管理工具（status/start/stop/restart/stats/logs） |
| ✅ **请求日志** | `--log-requests` 记录每次连接目标、路由、耗时 |
| ✅ **健康检查** | 每 30 秒真实测试代理功能，非仅 TCP 端口 |
| ✅ **连接统计** | 总连接数、活跃连接数、上下行流量、运行时长 |
| ✅ **自动更新检测** | `--check-update` 对比 GitHub release |
| ✅ **配置验证** | 启动时自动校验 config.json 字段合法性 |
| ✅ **配置备份** | `proxy-manager.sh export/import` |
| ✅ **DNS 防泄漏** | 路由判定从不本地解析域名 |
| ✅ **一键安装** | `bash setup.sh your-proxy.com 443` |
| ✅ **Docker + systemd** | 容器部署 + 系统服务管理 |

---

## 工作原理

```
你的程序（curl / git / npm / Python / agent-browser）
    │  http_proxy=http://127.0.0.1:10808
    │  或 socks5://127.0.0.1:10808
    ▼
┌─ proxy_forwarder.py ──────────────────────────────┐
│  自动检测客户端协议：SOCKS5 ↔ HTTP CONNECT          │
│                                                    │
│  域名在白名单？（百度/DeepSeek/B站等）               │
│    → 直连（快速）                                   │
│                                                    │
│  目标是纯 IP 地址？                                 │
│    → 查内置 44 个国内 IP 段 → 国内直连 / 国际代理    │
│                                                    │
│  其他域名                                           │
│    → 默认走远程代理（DNS 防泄漏）                    │
│      ├─ HTTPS CONNECT → TLS 隧道 → 代理 → 目标     │
│      └─ SOCKS5       → TCP + SOCKS5 握手 → 目标    │
└────────────────────────────────────────────────────┘
```

**没有 DNS 泄漏：** 路由判定从不进行本地 DNS 解析。只有代理服务器本身会在启动时通过系统 DNS 解析一次。

## 运行环境

- **Python 3.8+**（只用了标准库，无需 pip 安装任何依赖）
- **Linux / WSL2**（任何有 Python 的地方都能跑）
- **上游支持：** HTTPS CONNECT 代理 或 SOCKS5 代理
  - Chrome VPN 插件（FanVPN 等）
  - Shadowsocks / V2Ray / 机场订阅
  - SSH 隧道（`ssh -D 1080`）

---

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/pocraft/smart-proxy-forwarder.git
cd smart-proxy-forwarder

# 2. 一键安装
bash setup.sh your-proxy.example.com 443

# 如果代理使用自签名证书：
bash setup.sh your-proxy.example.com 443 true

# 3. 重新打开终端或执行 source
source ~/.bashrc

# 4. 验证
curl -v https://www.google.com    # → 应成功（走代理）
curl -v https://www.baidu.com     # → 也应成功（直连，更快）
```

---

## 手动安装

### 1. 启动转发器

```bash
# HTTPS CONNECT 上游（默认）
python3 proxy_forwarder.py \
    --remote-host your-proxy.example.com \
    --remote-port 443

# SOCKS5 上游
python3 proxy_forwarder.py \
    --upstream-type socks5 \
    --remote-host 127.0.0.1 \
    --remote-port 1080

# 多上游 + 连接池
python3 proxy_forwarder.py \
    --remote-host "proxy1.com:443,proxy2.com:8443" \
    --pool-size 8
```

或者通过 pip 安装后再运行：

```bash
pip install .
proxy-forwarder --remote-host your-proxy.example.com
```

### 2. 设置代理环境变量

```bash
export http_proxy=http://127.0.0.1:10808
export https_proxy=http://127.0.0.1:10808
export no_proxy="localhost,127.0.0.1,::1,api.deepseek.com,*.deepseek.com,\
*.baidu.com,*.qq.com,*.aliyun.com,*.taobao.com,*.jd.com,*.weixin.qq.com,\
*.zhihu.com,*.bilibili.com,*.tuna.tsinghua.edu.cn,*.ustc.edu.cn,\
10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
export NO_PROXY="$no_proxy"
```

### 3. （可选）配置 git 和 npm

```bash
git config --global http.proxy http://127.0.0.1:10808
npm config set proxy http://127.0.0.1:10808
npm config set https-proxy http://127.0.0.1:10808
```

### 4. 开机自启

运行 `setup.sh` 自动配置，或将 `bash-integration.sh` 内容追加到 `~/.bashrc` / `~/.zshrc`。

---

## 参数说明

### 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--listen-host` | `127.0.0.1` | 本地监听地址 |
| `--listen-port` | `10808` | 本地监听端口 |
| `--remote-host` | **必填** | 远程代理地址（逗号分隔实现多上游） |
| `--remote-port` | `443` | 远程代理端口 |
| `--upstream-type` | `connect` | 上游协议：`connect`（HTTPS CONNECT）/ `socks5` |
| `--pool-size` | `4` | TLS 连接池大小 |
| `--config` | `""` | JSON 配置文件路径 |
| `--insecure` / `-k` | `false` | 跳过 TLS 证书验证 |
| `--log-requests` | `false` | 记录每次 CONNECT 请求 |
| `--api-port` | `10809` | REST API / 仪表盘端口 |
| `--check-update` | - | 检查 GitHub 是否有新版本 |
| `--auto-detect-fanvpn` | `false` | 自动跟随 Chrome FanVPN 节点切换 |
| `--version` | - | 显示版本号 |

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PROXY_PORT` | `10808` | 覆盖所有脚本和配置中的端口号 |
| `PROXY_LOG` | `/tmp/proxy-forwarder.log` | 日志文件路径 |
| `XDG_CONFIG_HOME` | `~/.config` | 配置文件目录 |

### 配置文件 (`config.json`)

安装后位于 `~/.config/proxy-forwarder/config.json`：

```json
{
  "remote": { "host": "your-proxy.com", "port": 443 },
  "listen": { "host": "127.0.0.1", "port": 10808 },
  "insecure": false,
  "upstream_type": "connect",
  "pool_size": 4,
  "log_requests": false,
  "auto_detect_fanvpn": false,
  "china_ip_list_url": "",
  "direct_domains": ["*.my-corp.com"],
  "api_port": 10809
}
```

命令行参数优先级高于配置文件。

---

## 管理命令

```bash
bash ~/.config/proxy-forwarder/proxy-manager.sh status   # 运行状态
bash ~/.config/proxy-forwarder/proxy-manager.sh logs     # 查看日志
bash ~/.config/proxy-forwarder/proxy-manager.sh restart  # 重启
bash ~/.config/proxy-forwarder/proxy-manager.sh stop     # 停止
bash ~/.config/proxy-forwarder/proxy-manager.sh start    # 启动

# 切换端口
PROXY_PORT=9090 bash ~/.config/proxy-forwarder/proxy-manager.sh start
```

**状态输出示例：**

```
  Running
   PID:      11454
   Port:     10808
   RAM:      27MB
   Uptime:   1h23m
   Conns:    42 total, 0 active
   Traffic:  2343 KB (22 KB ↓ / 2321 KB ↑)
   Health:   ✅ alive
```

---

## Web 仪表盘

浏览器打开 `http://127.0.0.1:10809/`：

```
┌──────────────────────────────────────┐
│  🔄 代理转发器      [中文] [EN]     │
│                                      │
│  状态       正常                     │
│  运行时长   1h23m                    │
│  连接数     42 总 / 0 活跃           │
│  流量       2343 KB                  │
│  上游       fan.226278.xyz:443       │
│  类型       connect                  │
│  池大小     4                        │
│  版本       1.2.0                    │
└──────────────────────────────────────┘
```

每 5 秒自动刷新，右上角按钮切换中英文。

---

## REST API

```bash
curl http://127.0.0.1:10809/stats
# → {"uptime":"1h23m","total_connections":42,"health":"alive",
#     "upstream_type":"connect","pool_size":4,...}
```

---

## 请求日志

```bash
python3 proxy_forwarder.py --remote-host x.com --log-requests

# 输出示例：
# [14:00:01] www.google.com:443 → proxy (DNS-safe) 2.1s
# [14:00:02] www.baidu.com:443 → direct (direct-domain) 0.1s
# [14:00:03] github.com:443 → proxy (DNS-safe) → proxy1.com:443 2.5s
```

---

## 多上游 / 故障切换

```bash
# 逗号分隔，随机选择
python3 proxy_forwarder.py \
    --remote-host "hk-proxy.com:443,jp-proxy.com:8443,us-proxy.com:443"
```

健康检查同时测试所有上游，仪表盘显示当前活跃的上游。

---

## SOCKS5 上游

```bash
# SSH 隧道
ssh -D 1080 your-server
python3 proxy_forwarder.py --upstream-type socks5 --remote-host 127.0.0.1 --remote-port 1080

# 机场 SOCKS5 节点
python3 proxy_forwarder.py --upstream-type socks5 --remote-host node.example.com --remote-port 1080
```

---

## TLS 连接池

```bash
# 默认池大小 4
python3 proxy_forwarder.py --remote-host x.com --pool-size 4

# 高并发场景加大池
python3 proxy_forwarder.py --remote-host x.com --pool-size 16
```

连接 5 分钟自动回收，失效自动重连。仅对 HTTPS CONNECT 上游生效。

---

## DNS 泄漏防护

转发器的路由判定**永远不会进行本地 DNS 解析**：

1. 直连域名白名单 → 无需 DNS
2. 纯 IP 地址 → 查内置中国 IP 段
3. 其他域名 → **默认走代理**，不做本地解析

唯一会离开你机器的 DNS 查询是代理服务器本身（`--remote-host`）。

---

## 安全说明

- **TLS 证书验证默认开启。** 需跳过时加 `--insecure`/`-k`
  ```bash
  python3 proxy_forwarder.py --remote-host example.com --insecure
  ```
- `--insecure` 时代理服务器可进行中间人攻击，**仅用于你信任的代理**
- 流量内容端到端加密（你的工具 → 目标服务器）
- REST API 和代理端口只绑定 `127.0.0.1`，不暴露到局域网

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
sudo systemctl status proxy-forwarder
```

---

## 项目文件

| 文件 | 说明 |
|------|------|
| `proxy_forwarder.py` | 核心转发器（979 行，纯 Python 标准库） |
| `proxy-manager.sh` | 管理脚本（status/logs/start/stop/restart/export/import） |
| `setup.sh` | 一键安装脚本 |
| `bash-integration.sh` | Shell 集成片段 |
| `config.example.json` | 配置模板 |
| `deploy/proxy-forwarder.service` | systemd 服务单元 |
| `deploy/proxy_forwarder_mcp.py` | MCP 服务器（6 个 AI agent 工具） |
| `Dockerfile` | 容器构建 |
| `README.en.md` | 英文文档 |
| `CHANGELOG.md` | 变更记录 |
| `tests/` | **42 个测试**（单元 + 集成） |

兼容 HTTPS CONNECT 和 SOCKS5 代理。

---

## 开源协议

MIT
