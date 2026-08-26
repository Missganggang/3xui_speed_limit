#!/usr/bin/env python3
"""3x-ui Port Speed Limiter — Backend (Flask)"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

# ── Bootstrap ─────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
STATIC_DIR = BASE_DIR / "static"

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")
CORS(app)

DEFAULT_CONFIG = {
    "interface": "",
    "xui_url": "http://127.0.0.1:2053",
    "xui_token": "",
    "xui_base_path": "/",
    "rules": {},
}

# ── Config helpers ─────────────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                data = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                data.setdefault(k, v)
            return data
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(config: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def is_configured() -> bool:
    c = load_config()
    return bool(c.get("interface") and c.get("xui_token"))

def validate_interface(iface: str) -> bool:
    return bool(iface and re.fullmatch(r"[a-zA-Z0-9_.:-]+", iface))

# ── Shell / tc helpers ─────────────────────────────────────────────────────────

def run(cmd: str) -> tuple[int, str, str]:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr

def ensure_clsact(iface: str) -> None:
    _, out, _ = run(f"tc qdisc show dev {iface}")
    if "clsact" not in out:
        run(f"tc qdisc add dev {iface} clsact")

def clear_port(iface: str, port: int) -> None:
    for proto in ("ip", "ipv6"):
        for direction in ("ingress", "egress"):
            run(
                f"tc filter del dev {iface} {direction} "
                f"protocol {proto} pref {port} 2>/dev/null || true"
            )

def apply_rule(
    iface: str,
    port: int,
    rate,
    rate_unit: str,
    burst,
    burst_unit: str,
    protocol: str = "both",
    direction: str = "both",
    ip_family: str = "ipv4",
) -> list[str]:
    ensure_clsact(iface)
    clear_port(iface, port)

    protos = []
    if protocol in ("tcp", "both"):
        protos.append("tcp")
    if protocol in ("udp", "both"):
        protos.append("udp")

    families = [("ip",)]
    if ip_family == "both":
        families.append(("ipv6",))

    rate_s = f"{rate}{rate_unit}"
    burst_s = f"{burst}{burst_unit}"
    errors: list[str] = []

    for (tc_proto,) in families:
        for p in protos:
            if direction in ("upload", "both"):
                rc, _, err = run(
                    f"tc filter add dev {iface} ingress protocol {tc_proto} "
                    f"pref {port} flower ip_proto {p} dst_port {port} "
                    f"action police rate {rate_s} burst {burst_s} conform-exceed drop"
                )
                if rc != 0:
                    errors.append(err.strip())

            if direction in ("download", "both"):
                rc, _, err = run(
                    f"tc filter add dev {iface} egress protocol {tc_proto} "
                    f"pref {port} flower ip_proto {p} src_port {port} "
                    f"action police rate {rate_s} burst {burst_s} conform-exceed drop"
                )
                if rc != 0:
                    errors.append(err.strip())

    return errors

def get_active_prefs(iface: str) -> set[int]:
    prefs: set[int] = set()
    for direction in ("ingress", "egress"):
        _, out, _ = run(f"tc filter show dev {iface} {direction}")
        for m in re.finditer(r"pref\s+(\d+)", out):
            prefs.add(int(m.group(1)))
    return prefs

# ── 3x-ui API ─────────────────────────────────────────────────────────────────

def xui_inbounds(config: dict) -> list[dict]:
    base = config["xui_url"].rstrip("/")
    bpath = config.get("xui_base_path", "/").rstrip("/")
    url = f"{base}{bpath}/panel/api/inbounds/options"
    headers = {"Authorization": f"Bearer {config['xui_token']}"}
    r = requests.get(url, headers=headers, timeout=10, verify=False)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "obj" in data:
        return data["obj"] or []
    if isinstance(data, list):
        return data
    return []

# ── Startup rule restore ───────────────────────────────────────────────────────

def reload_all_rules() -> dict:
    config = load_config()
    if not config.get("interface"):
        return {"applied": 0, "errors": {}}
    iface = config["interface"]
    rules = config.get("rules", {})
    errors: dict = {}
    for port_str, rule in rules.items():
        errs = apply_rule(
            iface,
            int(port_str),
            rule.get("rate", 10),
            rule.get("rate_unit", "mbit"),
            rule.get("burst", 1),
            rule.get("burst_unit", "mb"),
            rule.get("protocol", "both"),
            rule.get("direction", "both"),
            rule.get("ip_family", "ipv4"),
        )
        if errs:
            errors[port_str] = errs
    return {"applied": len(rules), "errors": errors}

# ── Routes — setup ────────────────────────────────────────────────────────────

@app.route("/")
def root():
    return app.send_static_file("index.html")

@app.route("/api/setup", methods=["GET"])
def setup_status():
    return jsonify({"configured": is_configured()})

@app.route("/api/setup", methods=["POST"])
def setup_save():
    data = request.json or {}
    iface = data.get("interface", "").strip()
    if not validate_interface(iface):
        return jsonify({"error": "网卡名称格式不正确"}), 400
    xui_url = data.get("xui_url", "").strip().rstrip("/")
    if not xui_url:
        return jsonify({"error": "3x-ui 地址不能为空"}), 400
    token = data.get("xui_token", "").strip()
    if not token:
        return jsonify({"error": "API Token 不能为空"}), 400

    config = load_config()
    config["interface"] = iface
    config["xui_url"] = xui_url
    config["xui_token"] = token
    config["xui_base_path"] = data.get("xui_base_path", "/").strip() or "/"
    save_config(config)
    return jsonify({"ok": True})

@app.route("/api/settings", methods=["GET"])
def settings_get():
    c = load_config()
    return jsonify({
        "interface": c.get("interface", ""),
        "xui_url": c.get("xui_url", ""),
        "xui_base_path": c.get("xui_base_path", "/"),
        "has_token": bool(c.get("xui_token")),
    })

@app.route("/api/settings", methods=["POST"])
def settings_update():
    data = request.json or {}
    config = load_config()
    if "interface" in data:
        iface = data["interface"].strip()
        if not validate_interface(iface):
            return jsonify({"error": "网卡名称格式不正确"}), 400
        config["interface"] = iface
    if "xui_url" in data:
        config["xui_url"] = data["xui_url"].strip().rstrip("/")
    if data.get("xui_token", "").strip():
        config["xui_token"] = data["xui_token"].strip()
    if "xui_base_path" in data:
        config["xui_base_path"] = data["xui_base_path"].strip() or "/"
    save_config(config)
    return jsonify({"ok": True})

# ── Routes — inbounds ─────────────────────────────────────────────────────────

@app.route("/api/inbounds", methods=["GET"])
def inbounds_list():
    if not is_configured():
        return jsonify({"error": "未配置"}), 400
    config = load_config()
    try:
        inbounds = xui_inbounds(config)
    except Exception as e:
        return jsonify({"error": f"无法连接 3x-ui: {e}"}), 502

    rules = config.get("rules", {})
    active = get_active_prefs(config["interface"])
    xui_ports: set[str] = set()
    result = []

    for ib in inbounds:
        port = ib.get("port")
        ps = str(port)
        xui_ports.add(ps)
        result.append({
            "id": ib.get("id"),
            "remark": ib.get("remark", ""),
            "protocol": ib.get("protocol", ""),
            "port": port,
            "rule": rules.get(ps),
            "tc_active": port in active,
        })

    orphans = [
        {
            "id": None,
            "remark": "[已删除入站]",
            "protocol": "",
            "port": int(ps),
            "rule": rule,
            "tc_active": int(ps) in active,
            "orphan": True,
        }
        for ps, rule in rules.items()
        if ps not in xui_ports
    ]

    return jsonify({
        "inbounds": result,
        "orphans": orphans,
        "interface": config["interface"],
    })

# ── Routes — rules ────────────────────────────────────────────────────────────

def _parse_rule(data: dict) -> tuple[dict, str | None]:
    rate = data.get("rate")
    burst = data.get("burst")
    if not isinstance(rate, (int, float)) or rate <= 0:
        return {}, "rate 参数无效"
    if not isinstance(burst, (int, float)) or burst <= 0:
        return {}, "burst 参数无效"
    return {
        "rate": rate,
        "rate_unit": data.get("rate_unit", "mbit"),
        "burst": burst,
        "burst_unit": data.get("burst_unit", "mb"),
        "protocol": data.get("protocol", "both"),
        "direction": data.get("direction", "both"),
        "ip_family": data.get("ip_family", "ipv4"),
    }, None

@app.route("/api/rules/<int:port>", methods=["POST"])
def rule_set(port: int):
    if not is_configured():
        return jsonify({"error": "未配置"}), 400
    rule, err = _parse_rule(request.json or {})
    if err:
        return jsonify({"error": err}), 400
    config = load_config()
    errors = apply_rule(config["interface"], port, **rule)
    config.setdefault("rules", {})[str(port)] = rule
    save_config(config)
    return jsonify({"ok": True, "errors": errors, "rule": rule})

@app.route("/api/rules/<int:port>", methods=["DELETE"])
def rule_delete(port: int):
    if not is_configured():
        return jsonify({"error": "未配置"}), 400
    config = load_config()
    clear_port(config["interface"], port)
    config.setdefault("rules", {}).pop(str(port), None)
    save_config(config)
    return jsonify({"ok": True})

@app.route("/api/rules/batch", methods=["POST"])
def rule_batch():
    if not is_configured():
        return jsonify({"error": "未配置"}), 400
    data = request.json or {}
    ports = data.get("ports", [])
    rule, err = _parse_rule(data.get("rule", {}))
    if err:
        return jsonify({"error": err}), 400
    config = load_config()
    iface = config["interface"]
    results: dict = {}
    config.setdefault("rules", {})
    for port in ports:
        errs = apply_rule(iface, int(port), **rule)
        config["rules"][str(port)] = rule
        results[str(port)] = {"errors": errs}
    save_config(config)
    return jsonify({"ok": True, "results": results})

# ── Routes — tc control ───────────────────────────────────────────────────────

@app.route("/api/tc/reload", methods=["POST"])
def tc_reload():
    result = reload_all_rules()
    return jsonify({"ok": True, **result})

@app.route("/api/tc/status", methods=["GET"])
def tc_status():
    config = load_config()
    iface = config.get("interface", "")
    if not iface:
        return jsonify({"error": "未配置网卡"}), 400
    _, ingress, _ = run(f"tc -s filter show dev {iface} ingress")
    _, egress, _ = run(f"tc -s filter show dev {iface} egress")
    return jsonify({"ingress": ingress, "egress": egress})

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--reload" in sys.argv:
        result = reload_all_rules()
        print(f"Applied {result['applied']} rule(s). Errors: {result['errors']}")
        sys.exit(0)

    print("Restoring saved tc rules...")
    r = reload_all_rules()
    print(f"  Applied {r['applied']} rule(s).")

    port = int(os.environ.get("PORT", 7788))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting on http://{host}:{port}")
    app.run(host=host, port=port, debug=False)
