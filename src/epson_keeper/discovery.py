"""打印机发现 — mDNS 自动发现 + 手动 IP fallback"""

import logging
import socket
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

TCP_PORT = 9100
TCP_TIMEOUT = 3  # seconds
MDNS_TIMEOUT = 10  # seconds
MDNS_SERVICE_TYPE = "_ipp._tcp.local."


@dataclass
class DiscoveredPrinter:
    ip: str
    name: str  # mDNS 服务名；手动 IP 时为 "manual"
    model_hint: Optional[str] = None  # txt record 中的型号提示


def _check_tcp(ip: str, port: int = TCP_PORT, timeout: int = TCP_TIMEOUT) -> bool:
    """TCP connect 探测打印机端口是否可达。"""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def _get_prop(properties: dict, key: str) -> str:
    """从 properties dict 获取值，兼容 bytes/string key。"""
    val = properties.get(key) or properties.get(key.encode())
    if val is None:
        return ""
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="ignore")
    return str(val)


def _is_epson(properties: dict) -> bool:
    """判断 mDNS txt record 是否为 EPSON 打印机。"""
    for key in ("ty", "usb_MFG", "usb_MDL"):
        val = _get_prop(properties, key)
        if "EPSON" in val.upper():
            return True
    return False


def _model_from_properties(properties: dict) -> Optional[str]:
    """从 txt record 提取型号提示。"""
    for key in ("ty", "usb_MDL"):
        val = _get_prop(properties, key)
        if val:
            return val
    return None


def _mdns_discover() -> DiscoveredPrinter:
    """通过 mDNS 浏览 _ipp._tcp.local. 发现 EPSON 打印机。"""
    from zeroconf import ServiceBrowser, ServiceInfo, ServiceStateChange, Zeroconf

    logger.info("mDNS 开始扫描 (超时 %ds)...", MDNS_TIMEOUT)
    found: list[ServiceInfo] = []
    zc = Zeroconf()

    def on_service(*args, **kwargs):
        # zeroconf 0.130+ 传 keyword args；只处理 Added 事件
        state = kwargs.get("state_change")
        if state is not None and state != ServiceStateChange.Added:
            return
        zc_ref = kwargs.get("zeroconf") or (args[0] if args else None)
        name = kwargs.get("name") or (args[2] if len(args) > 2 else "")
        stype = kwargs.get("service_type") or (args[1] if len(args) > 1 else "")
        if zc_ref is None:
            return
        info = zc_ref.get_service_info(stype, name)
        if info and _is_epson(info.properties):
            ip = socket.inet_ntoa(info.addresses[0]) if info.addresses else "?"
            logger.info("发现 EPSON 设备: %s (%s)", name, ip)
            found.append(info)

    try:
        browser = ServiceBrowser(zc, MDNS_SERVICE_TYPE, handlers=[on_service])
        import time

        time.sleep(MDNS_TIMEOUT)
        browser.cancel()
    finally:
        zc.close()
    logger.info("mDNS 扫描完成，发现 %d 台 EPSON 设备", len(found))

    if len(found) == 0:
        raise SystemExit(
            "mDNS 未发现 EPSON 打印机。\n"
            "请检查打印机电源/网络连接，或在 config.yaml 中手动配置 printer.ip"
        )
    if len(found) > 1:
        names = []
        for info in found:
            ip = socket.inet_ntoa(info.addresses[0]) if info.addresses else "?"
            name = info.name or "?"
            names.append(f"  - {name} ({ip})")
        raise SystemExit(
            f"mDNS 发现 {len(found)} 台打印机，请在 config.yaml 中配置 printer.ip 选择:\n"
            + "\n".join(names)
        )

    info = found[0]
    ip = socket.inet_ntoa(info.addresses[0])
    return DiscoveredPrinter(
        ip=ip,
        name=info.name,
        model_hint=_model_from_properties(info.properties),
    )


def discover_printer(config_ip: Optional[str] = None) -> DiscoveredPrinter:
    """发现打印机：手动 IP 优先，mDNS 兜底。"""
    if config_ip:
        logger.info("使用手动配置 IP: %s", config_ip)
        logger.info("TCP 探测 %s:%d ...", config_ip, TCP_PORT)
        if not _check_tcp(config_ip):
            logger.error("TCP 探测失败: %s:%d 不可达", config_ip, TCP_PORT)
            raise SystemExit(
                f"打印机 {config_ip} 不可达（TCP:{TCP_PORT}）。\n"
                "请检查: IP 是否正确、打印机是否开机、网络是否连通"
            )
        logger.info("TCP 探测成功: %s:%d 可达", config_ip, TCP_PORT)
        return DiscoveredPrinter(ip=config_ip, name="manual")

    logger.info("未配置 printer.ip，尝试 mDNS 自动发现...")
    return _mdns_discover()


def save_printer_ip(ip: str):
    """将发现的打印机 IP 保存到 config.yaml，避免下次再做 mDNS 扫描。"""
    from epson_keeper.config import CONFIG_PATH, load_config

    import yaml

    cfg = load_config()
    cfg.setdefault("printer", {})["ip"] = ip
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
    logger.info("已保存打印机 IP 到配置: %s → %s", ip, CONFIG_PATH)
