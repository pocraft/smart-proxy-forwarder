# Smart Proxy Forwarder

> **安全提示：** TLS 证书验证默认开启。如果代理服务器使用自签名证书，请加 `--insecure` 参数。

[![PyPI](https://img.shields.io/pypi/v/smart-proxy-forwarder)](https://pypi.org/project/smart-proxy-forwarder/)
[![Python](https://img.shields.io/pypi/pyversions/smart-proxy-forwarder)](https://pypi.org/project/smart-proxy-forwarder/)
[![License](https://img.shields.io/github/license/601494530-create/smart-proxy-forwarder)](LICENSE)
[![CI](https://github.com/601494530-create/smart-proxy-forwarder/actions/workflows/ci.yml/badge.svg)](https://github.com/601494530-create/smart-proxy-forwarder/actions)

轻量级 DNS 防泄漏 CONNECT 代理转发器。**国内直连、国际走远程 HTTPS 代理**，自动分流。

专为 WSL 用户设计——你在 Chrome 里用 VPN 插件/代理能翻墙，但 WSL 终端里的 curl、git、npm、Python、AI agent 等工具也能享受同样的能力，**且不泄漏 DNS 查询**。

---

## 工作原理

```
你的程序（curl / git / npm / Python / agent-browser）
    │  http_proxy=http://127.0.0.1:10808
    ▼
┌─ proxy_forwarder.py ──────────────────────────────┐
│                                                    │
│  域名在白名单？（百度/DeepSeek/B站等）               │
│    → 直连（快速）                                   │
│                                                    │
│  目标是纯 IP 地址？                                 │
│    → 查国内 IP 段 → 国内直连 / 国际代理              │
│                                                    │
│  其他域名                                           │
│    → 默认走远程代理（DNS 防泄漏）                    │
│      └─ TLS 隧道 → 你的代理服务器 → 国际互联网       │
└────────────────────────────────────────────────────┘
```

**没有 DNS 泄漏：** 路由判定从不进行本地 DNS 解析。只有代理服务器本身会在启动时通过系统 DNS 解析一次 —— 这是任何 VPN/代理都不可避免的。

---

## 运行环境

- **Python 3.8+**（只用了标准库，无需 pip 安装任何依赖）
- **Linux / WSL2**（实际上任何有 Python 的地方都能跑）
- 一个 **HTTPS CONNECT 代理服务器**（比如 Chrome VPN 插件的上游服务器、VPS 上搭的 squid/caddy 等）

---

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/601494530-create/smart-proxy-forwarder.git
cd smart-proxy-forwarder

# 2. 一键安装（填你的代理服务器地址）
bash setup.sh your-proxy.example.com 443

# 2a. 如果代理使用自签名证书，加第三个参数：
bash setup.sh your-proxy.example.com 443 true

# 3. 重新打开终端或执行 source
source ~/.bashrc
# 如果用的是 zsh： source ~/.zshrc

# 4. 验证
curl -v https://www.google.com    # → 应成功（走代理）
curl -v https://www.baidu.com     # → 也应成功（直连，更快）
```

---

## 手动安装

### 1. 启动转发器

```bash
python3 proxy_forwarder.py \
    --remote-host your-proxy.example.com \
    --remote-port 443 \
    --listen-port 10808
```

或者通过 pip 安装后再运行：
```bash
pip install .
proxy-forwarder --remote-host your-proxy.example.com --remote-port 443
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
| `--remote-host` | **必填** | 远程 HTTPS CONNECT 代理地址 |
| `--remote-port` | `443` | 远程代理端口 |
| `--config` | `""` | JSON 配置文件路径 |
| `--insecure` / `-k` | `false` | 跳过 TLS 证书验证 |
| `--version` | - | 显示版本号 |

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PROXY_PORT` | `10808` | 覆盖所有脚本和配置中的端口号 |
| `PROXY_LOG` | `/tmp/proxy-forwarder.log` | 日志文件路径 |
| `XDG_CONFIG_HOME` | `~/.config` | 配置文件目录 |

### 配置文件 (`config.json`)

安装后配置文件位于 `~/.config/proxy-forwarder/config.json`：

```json
{
  "remote": { "host": "your-proxy.com", "port": 443 },
  "listen": { "host": "127.0.0.1", "port": 10808 },
  "insecure": false,
  "china_ip_list_url": "",
  "direct_domains": ["*.my-corp.com"]
}
```

命令行参数优先级高于配置文件。

---

## 管理命令

```bash
bash ~/.config/proxy-forwarder/proxy-manager.sh status   # 查看运行状态
bash ~/.config/proxy-forwarder/proxy-manager.sh restart  # 重启
bash ~/.config/proxy-forwarder/proxy-manager.sh stop     # 停止
bash ~/.config/proxy-forwarder/proxy-manager.sh start    # 启动

# 切换到不同端口
PROXY_PORT=9090 bash ~/.config/proxy-forwarder/proxy-manager.sh start
```

---

## DNS 泄漏防护

转发器的路由判定**永远不会进行本地 DNS 解析**：

1. 直连域名白名单 → 无需 DNS
2. 纯 IP 地址 → 查内置中国 IP 段
3. 其他域名 → **默认走代理**，不做本地解析

唯一会离开你机器的 DNS 查询是代理服务器本身（`--remote-host`） —— 一次不可避免的连接。

---

## 安全说明

- **TLS 证书验证默认开启。** 如果代理服务器使用自签名或证书不匹配的证书，需加 `--insecure`/`-k` 参数
  ```bash
  python3 proxy_forwarder.py --remote-host example.com --insecure
  ```
- 使用 `--insecure` 时，远程代理服务器可以对你进行中间人攻击
- 仅在**你信任的代理服务器**上使用 `--insecure`
- 实际流量内容仍是端到端加密的（你的工具 → 目标服务器之间的 TLS），代理只能看到你访问了哪个域名
- 监听的本地端口（默认 10808）只绑定到 127.0.0.1，不会暴露到局域网

---

## 常见问题

### 转发器启动失败怎么办？

检查日志：
```bash
cat /tmp/proxy-forwarder.log
```

常见原因：
- `--remote-host` 未设置或为空 → 启动日志会显示 ERROR
- 远程代理服务器不可达 → 检查网络连接
- Python 版本过低 → 需要 3.8+
- 端口被占用 → 换端口：`PROXY_PORT=9090 bash setup.sh ...`

### Google/GitHub 能访问，但百度/国内站很慢？

说明国内站走了代理。正常应该直连（百度应 < 0.2s）。检查：
- 白名单是否覆盖了该域名？
- 如果是未覆盖的国内站，提交 Issue 补充白名单

### 国内站能访问，但 Google/GitHub 打不开？

转发器可能没启动，或者远程代理服务器不可用。检查：
```bash
bash ~/.config/proxy-forwarder/proxy-manager.sh status
```
如果显示 "Running"，检查 `/tmp/proxy-forwarder.log` 看是否有连接错误。

### 如何更换代理服务器？

编辑配置文件：
```bash
vim ~/.config/proxy-forwarder/config.json
# 修改 remote.host 和 remote.port
bash ~/.config/proxy-forwarder/proxy-manager.sh restart
```

### 如何更改端口？

所有脚本都支持 `PROXY_PORT` 环境变量：
```bash
PROXY_PORT=9090 bash setup.sh your-proxy.com 443
PROXY_PORT=9090 bash ~/.config/proxy-forwarder/proxy-manager.sh start
export PROXY_PORT=9090  # 永久设置
```

### macOS 能用吗？

代码层面可以（纯 Python），但 `setup.sh` 和 `proxy-manager.sh` 是针对 Linux 的。macOS 用户可以：
```bash
pip install .
proxy-forwarder --remote-host your-proxy.com --insecure
```

### 为什么要 `--insecure`？

多数 Chrome VPN 插件的代理服务器使用自签名证书或 IP 地址直连，系统证书链无法验证。这是常见的，**只要代理服务器是你自己的**（或你信任的），加 `--insecure` 是安全的。

---

## 项目文件结构

安装后文件位于 `~/.config/proxy-forwarder/`：

| 文件 | 说明 |
|------|------|
| `proxy_forwarder.py` | 核心转发器 |
| `proxy-manager.sh` | 管理脚本 |
| `bash-integration.sh` | Shell 集成片段（供手动安装用） |
| `config.json` | 配置文件（由 setup.sh 创建） |

兼容任何 HTTPS CONNECT 代理（Chrome VPN 插件、Squid、Caddy、mitmproxy 等）。

---

## 开源协议

MIT
