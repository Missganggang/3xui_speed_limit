#!/bin/bash
#
# 3x-ui 端口限速 一键安装脚本
#
#   bash <(curl -Ls https://raw.githubusercontent.com/Missganggang/3xui_speed_limit/main/install.sh)
#
set -e

# ── 可覆盖变量 ──────────────────────────────────────────────────────────────
REPO="Missganggang/3xui_speed_limit"
BRANCH="${BRANCH:-main}"
INSTALL_DIR="/opt/3xui-speed"
SERVICE_FILE="/etc/systemd/system/3xui-speed.service"
PORT="${PORT:-7788}"
TARBALL="https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz"

echo "=========================================="
echo "   3x-ui 端口限速 一键安装"
echo "=========================================="

# ── 1. root 检查 ────────────────────────────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
    echo "✗ 请使用 root 运行此脚本"
    exit 1
fi

# ── 2. 依赖 ─────────────────────────────────────────────────────────────────
echo "[1/6] 安装系统依赖..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip iproute2 curl tar

# ── 3. 下载并解压项目 ───────────────────────────────────────────────────────
echo "[2/6] 下载项目 (${REPO}@${BRANCH})..."
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if ! curl -Ls "$TARBALL" -o "$TMP/src.tar.gz"; then
    echo "✗ 下载失败，检查网络或仓库是否公开"
    exit 1
fi

tar -xzf "$TMP/src.tar.gz" -C "$TMP"
SRC="$(find "$TMP" -maxdepth 1 -type d -name '*3xui_speed_limit*' | head -n1)"
if [ -z "$SRC" ]; then
    echo "✗ 解压后未找到项目目录"
    exit 1
fi

# ── 4. 复制文件（保留已有 config.json） ─────────────────────────────────────
echo "[3/6] 安装到 ${INSTALL_DIR}..."
mkdir -p "$INSTALL_DIR/static"
cp "$SRC/app.py"           "$INSTALL_DIR/"
cp "$SRC/requirements.txt" "$INSTALL_DIR/"
cp -r "$SRC/static/."      "$INSTALL_DIR/static/"

# ── 5. Python 虚拟环境 ──────────────────────────────────────────────────────
echo "[4/6] 创建 Python 虚拟环境..."
if [ ! -d "$INSTALL_DIR/venv" ]; then
    python3 -m venv "$INSTALL_DIR/venv"
fi
"$INSTALL_DIR/venv/bin/pip" install -q --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

# ── 6. systemd 服务 ─────────────────────────────────────────────────────────
echo "[5/6] 安装 systemd 服务..."
sed "s|/opt/3xui-speed|$INSTALL_DIR|g; s|PORT=7788|PORT=$PORT|g" \
    "$SRC/3xui-speed.service" > "$SERVICE_FILE"

systemctl daemon-reload
systemctl enable 3xui-speed >/dev/null 2>&1
systemctl restart 3xui-speed

echo "[6/6] 完成！"
echo ""
echo "=========================================="
SERVER_IP="$(curl -Ls4 ifconfig.me 2>/dev/null || echo '<服务器IP>')"
echo "  管理面板: http://${SERVER_IP}:${PORT}"
echo "  服务状态: systemctl status 3xui-speed"
echo "  查看日志: journalctl -u 3xui-speed -f"
echo ""
echo "  请确保防火墙 / 云安全组已放行 ${PORT} 端口"
echo "=========================================="
