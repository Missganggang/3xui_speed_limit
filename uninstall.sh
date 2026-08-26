#!/bin/bash
#
# 3x-ui 端口限速 卸载脚本
#
#   bash <(curl -Ls https://raw.githubusercontent.com/Missganggang/3xui_speed_limit/main/uninstall.sh)
#
# 流程：先取消所有 tc 限速规则 → 停止禁用服务 → 删除文件。
# 可选：KEEP_CONFIG=1 保留 config.json（含 Token 和限速规则）备份，便于以后重装。
#
set -e

INSTALL_DIR="/opt/3xui-speed"
SERVICE_FILE="/etc/systemd/system/3xui-speed.service"
CONFIG="$INSTALL_DIR/config.json"

echo "=========================================="
echo "   3x-ui 端口限速 卸载"
echo "=========================================="

if [ "$EUID" -ne 0 ]; then
    echo "✗ 请使用 root 运行此脚本"
    exit 1
fi

# ── 1. 取消所有 tc 限速规则 ─────────────────────────────────────────────────
echo "[1/4] 取消所有 tc 限速规则..."
IFACE=""
if [ -f "$CONFIG" ]; then
    IFACE=$(python3 -c "import json;print(json.load(open('$CONFIG')).get('interface',''))" 2>/dev/null || true)
fi

if [ -n "$IFACE" ]; then
    echo "    网卡: $IFACE"
    PORTS=$(python3 -c "import json;print(' '.join(json.load(open('$CONFIG')).get('rules',{}).keys()))" 2>/dev/null || true)
    for p in $PORTS; do
        for proto in ip ipv6; do
            for dir in ingress egress; do
                tc filter del dev "$IFACE" $dir protocol $proto pref "$p" 2>/dev/null || true
            done
        done
        echo "    已删除端口 $p 的限速规则"
    done
    # 彻底清掉本程序在该网卡创建的 clsact（连带所有残留 filter）
    tc qdisc del dev "$IFACE" clsact 2>/dev/null || true
    echo "    已移除 $IFACE 上的 clsact qdisc"
else
    echo "    未找到网卡配置，跳过"
    echo "    如仍有残留可手动执行: tc qdisc del dev <你的网卡> clsact"
fi

# ── 2. 停止并禁用服务 ───────────────────────────────────────────────────────
echo "[2/4] 停止并禁用 systemd 服务..."
systemctl stop 3xui-speed 2>/dev/null || true
systemctl disable 3xui-speed 2>/dev/null || true

# ── 3. 删除 systemd 单元 ────────────────────────────────────────────────────
echo "[3/4] 删除 systemd 单元..."
rm -f "$SERVICE_FILE"
systemctl daemon-reload
systemctl reset-failed 3xui-speed 2>/dev/null || true

# ── 4. 删除程序文件 ─────────────────────────────────────────────────────────
echo "[4/4] 删除程序文件..."
if [ "${KEEP_CONFIG:-0}" = "1" ] && [ -f "$CONFIG" ]; then
    cp "$CONFIG" /tmp/3xui-speed-config.json.bak
    echo "    已备份配置到: /tmp/3xui-speed-config.json.bak"
fi
rm -rf "$INSTALL_DIR"

echo ""
echo "=========================================="
echo "  卸载完成，所有限速规则已取消。"
echo "=========================================="
