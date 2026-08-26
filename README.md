# 3x-ui 端口限速管理

基于 Linux `tc clsact + flower + police` 的 3x-ui 端口限速 Web 管理面板。

## 功能

- 自动读取 3x-ui API，展示所有入站端口
- 一键设置/修改/取消单个端口限速
- 批量设置多个端口
- 速率预设（5/10/15/20/30/50 Mbps）
- 孤立规则检测（tc 有规则但 3x-ui 已删除的端口）
- Debian 重启自动恢复 tc 规则（systemd）

## 一键部署

在 Debian 服务器上以 root 执行：

```bash
bash <(curl -Ls https://raw.githubusercontent.com/Missganggang/3xui_speed_limit/main/install.sh)
```

装完后访问 `http://服务器IP:7788`。

自定义监听端口：

```bash
PORT=8899 bash <(curl -Ls https://raw.githubusercontent.com/Missganggang/3xui_speed_limit/main/install.sh)
```

> 脚本会自动：安装依赖 → 从 GitHub 下载项目 → 建虚拟环境 → 注册 systemd 开机自启。
> 重复执行即可升级到最新版本，已有的 `config.json`（含限速规则和 Token）会保留。

## 首次配置

打开面板后填写：

| 字段 | 说明 |
|------|------|
| 公网网卡 | 执行 `ip route` 查看，如 `ens17` |
| 3x-ui 地址 | 限速程序与 3x-ui 同机时用 `http://127.0.0.1:2053` |
| Web Base Path | 默认 `/`，如有修改按实际填写 |
| Bearer API Token | 在 3x-ui 面板 → API 设置中生成 |

## API Token 获取

3x-ui 面板 → 面板设置 → API → 生成 Token。

**不要**将 Token 暴露给公网，限速程序与 3x-ui 同机部署时 API 不需要经过公网。

## 服务管理

```bash
systemctl status 3xui-speed      # 查看状态
systemctl restart 3xui-speed     # 重启
journalctl -u 3xui-speed -f      # 实时日志
```

## 修改监听端口

编辑 `/etc/systemd/system/3xui-speed.service`，修改 `PORT=7788`，然后：

```bash
systemctl daemon-reload
systemctl restart 3xui-speed
```

## 工作原理

```
浏览器
  │
  ▼
Flask 后端（:7788）
  │
  ├── GET  /api/inbounds       调用 3x-ui API 读取入站列表
  ├── POST /api/rules/:port    执行 tc filter add ...
  ├── DEL  /api/rules/:port    执行 tc filter del ...
  └── POST /api/tc/reload      开机恢复规则（systemd ExecStartPre）
```

tc 规则示例（下载方向 IPv4 TCP+UDP 10 Mbps）：

```bash
tc qdisc add dev ens17 clsact
tc filter add dev ens17 egress protocol ip pref 12514 flower \
    ip_proto tcp src_port 12514 \
    action police rate 10mbit burst 1mb conform-exceed drop
```

## 配置文件

规则保存在 `/opt/3xui-speed/config.json`：

```json
{
  "interface": "ens17",
  "xui_url": "http://127.0.0.1:2053",
  "xui_base_path": "/",
  "xui_token": "...",
  "rules": {
    "12514": {
      "rate": 10, "rate_unit": "mbit",
      "burst": 1, "burst_unit": "mb",
      "protocol": "both", "direction": "both", "ip_family": "ipv4"
    }
  }
}
```

## 注意事项

- 需要 root 权限（tc 命令）
- Debian 11/12 均已测试
- 一个入站端口对应一条 tc 规则；同端口多用户共享该限速
- `pref` 直接使用端口号，便于定位和删除
