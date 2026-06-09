# Epson Printer Auto-Discovery on Local Network (Python)

Research document for epson-keeper project -- covering four approaches to
discover Epson printers (especially the L416x EcoTank series) on a home or
small-office LAN.

---

## 1. SNMP-Based Discovery

### How It Works

SNMP (Simple Network Management Protocol) runs on UDP port 161. There is no
native "broadcast discovery" -- you must probe each IP in a subnet. Query a
well-known OID (`sysDescr`) and check whether the response contains an Epson
identifier.

### Key OIDs for Epson Identification

| OID | Name | What It Returns |
|-----|------|-----------------|
| `1.3.6.1.2.1.1.1.0` | sysDescr | Full description string, e.g. `"EPSON ET-4760..."` |
| `1.3.6.1.2.1.1.5.0` | sysName | Hostname, often `"EPSON_L4160_Series"` |
| `1.3.6.1.2.1.1.2.0` | sysObjectID | Vendor-specific OID tree |
| `1.3.6.1.2.1.43.11.1.1.6` | prtMarkerSuppliesDescription | Ink cartridge names |
| `1.3.6.1.2.1.43.11.1.1.8` | prtMarkerSuppliesMaxCapacity | Max ink capacity |
| `1.3.6.1.2.1.43.11.1.1.9` | prtMarkerSuppliesLevel | Current ink levels |

The Printer MIB subtree `1.3.6.1.2.1.43` is standardised (RFC 3805) and
supported by virtually all Epson network printers.

### Python Libraries

| Library | Install | Notes |
|---------|---------|-------|
| **pysnmp** | `pip install pysnmp` | Full-featured, heavy (C deps via asn1). Async via `pysnmp.hlapi.asyncio`. |
| **puresnmp** | `pip install puresnmp` | Pure Python, lightweight, asyncio-native (`puresnmp.aio`). Better for scanning. |
| **easysnmp** | `pip install easysnmp` | Thin wrapper around net-snmp C lib. No async. |

**Recommendation**: `puresnmp` for scanning (lighter, async), `pysnmp` if you
need the full MIB browser or SNMPv3 with all auth/priv options.

### Code Example -- Async Subnet Scanner with puresnmp

```python
import asyncio
import ipaddress
from puresnmp.aio import Client
from puresnmp.credentials import V2C

async def check_host(ip: str, sem: asyncio.Semaphore) -> dict | None:
    """Probe a single host via SNMP. Return printer info or None."""
    async with sem:
        try:
            creds = V2C("public")
            async with Client(ip, creds) as client:
                sys_descr = await client.get("1.3.6.1.2.1.1.1.0", timeout=2)
                descr = str(sys_descr)
                if "epson" in descr.lower():
                    sys_name = await client.get("1.3.6.1.2.1.1.5.0", timeout=2)
                    return {
                        "ip": ip,
                        "description": descr,
                        "name": str(sys_name),
                        "method": "snmp",
                    }
        except Exception:
            pass
    return None

async def discover_printers(subnet: str = "192.168.1.0/24") -> list[dict]:
    """Scan entire subnet for Epson printers via SNMP."""
    sem = asyncio.Semaphore(50)  # limit concurrency
    hosts = [str(ip) for ip in ipaddress.IPv4Network(subnet, strict=False)]
    tasks = [check_host(h, sem) for h in hosts]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]

if __name__ == "__main__":
    printers = asyncio.run(discover_printers())
    for p in printers:
        print(f"Found: {p['ip']} -- {p['name']}")
```

### Code Example -- Ink Level Query

```python
import asyncio
from puresnmp.aio import Client
from puresnmp.credentials import V2C

INK_LEVEL_OID = "1.3.6.1.2.1.43.11.1.1.9"
INK_DESC_OID  = "1.3.6.1.2.1.43.11.1.1.6"

async def get_ink_levels(ip: str):
    async with Client(ip, V2C("public")) as client:
        levels = {str(oid): int(val) async for oid, val in client.walk(INK_LEVEL_OID)}
        descs  = {str(oid): str(val) async for oid, val in client.walk(INK_DESC_OID)}
        return descs, levels

descs, levels = asyncio.run(get_ink_levels("192.168.1.50"))
for oid, name in descs.items():
    # Walk returns table-indexed OIDs; match by index
    idx = oid.split(".")[-1]
    level = levels.get(INK_LEVEL_OID + "." + idx, "?")
    print(f"  {name}: {level}")
```

### Pros

- Works even if mDNS is disabled or the printer does not support Bonjour.
- Rich device information (ink levels, page counts, serial number).
- Epson L416x series supports SNMPv1/v2c with community `"public"` out of the box.
- No special driver or OS integration needed -- pure UDP.

### Cons

- Requires iterating over every IP in the subnet (no native broadcast).
- Scanning a /24 with 50 concurrent requests takes roughly 5-15 seconds.
- Printer must have SNMP enabled (it is by default on Epson, but can be
  disabled in the web config page).
- pysnmp is a heavy dependency; puresnmp is lighter but less mature.

### Reliability for Epson L416x

**HIGH.** Epson L4160/L4161/L4163 all ship with SNMP enabled, community
`"public"`, responding on UDP 161. The `sysDescr` OID reliably contains
`"EPSON"` and the model name. Ink levels are accessible through the standard
Printer MIB.

---

## 2. mDNS / Bonjour / Zeroconf Discovery

### How It Works

Epson printers with Wi-Fi enabled advertise themselves via Multicast DNS
(mDNS, RFC 6762) and DNS-Based Service Discovery (DNS-SD, RFC 6763) on
the multicast address `224.0.0.251:5353`. A client listens for service
announcements or actively queries for specific service types. This is the
same mechanism Apple calls "Bonjour" and Linux calls "Avahi."

### Service Types Epson Printers Advertise

| Service Type | Purpose | Epson Support |
|---|---|---|
| `_ipp._tcp.local.` | Internet Printing Protocol | Yes |
| `_ipps._tcp.local.` | IPP over TLS | Some models |
| `_pdl-datastream._tcp.local.` | Raw print data (port 9100) | Yes |
| `_printer._tcp.local.` | Legacy LPD | Yes |
| `_uscan._tcp.local.` | eSCL scanning | Yes (L416x series) |
| `_scanner._tcp.local.` | Legacy scanning | Some models |

### TXT Record Fields (from Epson `_ipp._tcp`)

| Field | Example | Description |
|---|---|---|
| `rp` | `ipp/print` | IPP queue path |
| `ty` | `EPSON L4160 Series` | Printer model / type |
| `pdl` | `application/pdf,image/urf` | Page description languages |
| `usb_MFG` | `EPSON` | Manufacturer string |
| `usb_MDL` | `L4160 Series` | Model string |
| `adminurl` | `http://192.168.1.50:80/` | Web admin URL |
| `txtvers` | `1` | TXT record version |
| `qtotal` | `1` | Number of queues |
| `note` | (empty) | Location note |
| `priority` | `0` | Print priority |

### Python Library

**`zeroconf`** (by `python-zeroconf` on PyPI)

```bash
pip install zeroconf
```

### Code Example

```python
import socket
from zeroconf import Zeroconf, ServiceBrowser, ServiceStateChange

class EpsonPrinterListener:
    """Listen for Epson printers advertising via mDNS."""

    def __init__(self):
        self.printers: list[dict] = []

    def on_service_state_change(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        if state_change is not ServiceStateChange.Added:
            return

        info = zeroconf.get_service_info(service_type, name)
        if info is None:
            return

        # Filter for Epson devices
        server = (info.server or "").lower()
        props = info.properties or {}

        # Decode TXT record fields
        manufacturer = props.get(b"usb_MFG", b"").decode("utf-8", errors="ignore").lower()
        model = props.get(b"usb_MDL", b"").decode("utf-8", errors="ignore")
        ty = props.get(b"ty", b"").decode("utf-8", errors="ignore")

        is_epson = (
            "epson" in server
            or "epson" in manufacturer
            or "epson" in ty.lower()
            or "epson" in name.lower()
        )

        if is_epson:
            addresses = [socket.inet_ntoa(addr) for addr in info.addresses]
            printer = {
                "name": name,
                "server": info.server,
                "addresses": addresses,
                "port": info.port,
                "service_type": service_type,
                "model": model or ty,
                "manufacturer": manufacturer or "epson",
                "properties": {k.decode(): v.decode() for k, v in props.items()},
            }
            self.printers.append(printer)
            print(f"[mDNS] Epson printer found: {name}")
            print(f"  IP: {addresses}")
            print(f"  Port: {info.port}")
            print(f"  Model: {model or ty}")

def discover_epson_printers(timeout_sec: float = 5.0) -> list[dict]:
    """Discover Epson printers on the LAN via mDNS."""
    zc = Zeroconf()
    listener = EpsonPrinterListener()

    # Browse multiple service types simultaneously
    service_types = [
        "_ipp._tcp.local.",
        "_ipps._tcp.local.",
        "_pdl-datastream._tcp.local.",
        "_printer._tcp.local.",
    ]

    browsers = [
        ServiceBrowser(zc, stype, handlers=[listener.on_service_state_change])
        for stype in service_types
    ]

    import time
    time.sleep(timeout_sec)

    # Cleanup
    zc.close()
    return listener.printers

if __name__ == "__main__":
    printers = discover_epson_printers(timeout_sec=5)
    print(f"\nFound {len(printers)} Epson printer(s)")
    for p in printers:
        print(f"  {p['addresses']} - {p['model']}")
```

### Async Version

```python
import asyncio
from zeroconf.asyncio import AsyncZeroconf, AsyncServiceBrowser
from zeroconf import ServiceStateChange
import socket

async def discover_epson_async(timeout: float = 5.0) -> list[dict]:
    azc = AsyncZeroconf()
    results = []

    def on_change(zc, stype, name, state_change):
        if state_change is not ServiceStateChange.Added:
            return
        info = zc.get_service_info(stype, name)
        if info and ("epson" in (info.server or "").lower()
                     or "epson" in name.lower()):
            addrs = [socket.inet_ntoa(a) for a in info.addresses]
            results.append({"ip": addrs[0], "name": name, "port": info.port})

    await azc.async_register_service(...)  # or just browse
    browser = AsyncServiceBrowser(
        azc.zeroconf,
        ["_ipp._tcp.local.", "_pdl-datastream._tcp.local."],
        handlers=[on_change],
    )
    await asyncio.sleep(timeout)
    await browser.async_cancel()
    await azc.async_close()
    return results
```

### Pros

- Truly zero-configuration -- no need to know the subnet or scan IPs.
- Fast: typically discovers all printers within 1-3 seconds.
- Returns rich metadata (model, manufacturer, supported languages, admin URL).
- Works seamlessly on any LAN segment where mDNS multicast is not blocked.
- Async version available (`AsyncZeroconf`).

### Cons

- Requires mDNS to be enabled on the printer (it is on by default for Epson
  Wi-Fi, but can be disabled).
- Will not work across subnets/VLANs without an mDNS reflector (e.g., Avahi
  reflector or `avahi-daemon` with `enable-reflector=yes`).
- If the printer was set up with a static IP and mDNS is off, this method
  will not find it.
- The `zeroconf` library is well-maintained but can occasionally miss
  devices if they haven't recently announced.

### Reliability for Epson L416x

**VERY HIGH.** The Epson L416x series supports Bonjour/mDNS natively. When
Wi-Fi is connected, the printer advertises `_ipp._tcp` and `_pdl-datastream._tcp`
with `usb_MFG=EPSON` in the TXT record. This is the same discovery mechanism
that Epson's own "EpsonNet Config" tool and macOS AirPrint use.

---

## 3. IPP Discovery

### How It Works

The Internet Printing Protocol (IPP, RFC 8011) runs on port 631 (HTTP) or
443 (HTTPS). Once you know a printer's IP, you can query its attributes via
`Get-Printer-Attributes`. IPP itself does not provide a discovery mechanism --
discovery relies on mDNS (approach 2) or knowing the IP beforehand.

However, some CUPS setups support `CUPSGetPrinters` or browsing, and the
`pyipp` library can query a known printer for its capabilities.

### Python Libraries

| Library | Install | Notes |
|---------|---------|-------|
| **pyipp** | `pip install pyipp` | Modern async IPP client. Good for querying attributes. |
| **python-ipp** | `pip install python-ipp` | Alternative IPP client. |

```bash
pip install pyipp
```

### Code Example -- Query Printer Attributes

```python
import asyncio
from pyipp import IPP

async def query_printer(ip: str):
    """Query an Epson printer's IPP attributes."""
    printer = IPP(f"ipp://{ip}/ipp/print")

    attrs = await printer.get_printer_attributes()

    # Attributes from the response
    info = attrs.get("printer-attributes-tag", {})
    print(f"Name:        {info.get('printer-name')}")
    print(f"State:       {info.get('printer-state')}")
    print(f"Make/Model:  {info.get('printer-make-and-model')}")
    print(f"URIs:        {info.get('printer-uri-supported')}")
    print(f"Location:    {info.get('printer-location')}")
    print(f"Info:        {info.get('printer-info')}")
    print(f"Media:       {info.get('media-supported')}")
    return info

asyncio.run(query_printer("192.168.1.50"))
```

### Code Example -- IPP + mDNS Combined Discovery

```python
import asyncio
from zeroconf.asyncio import AsyncZeroconf, AsyncServiceBrowser
from zeroconf import ServiceStateChange
from pyipp import IPP
import socket

async def discover_and_query(timeout: float = 5.0):
    """Discover printers via mDNS, then query them via IPP."""
    azc = AsyncZeroconf()
    discovered = {}

    def on_change(zc, stype, name, state_change):
        if state_change is ServiceStateChange.Added:
            info = zc.get_service_info(stype, name)
            if info and "epson" in (info.server or "").lower():
                for addr in info.addresses:
                    ip = socket.inet_ntoa(addr)
                    rp = info.properties.get(b"rp", b"ipp/print").decode()
                    discovered[ip] = {"name": name, "path": rp}

    browser = AsyncServiceBrowser(
        azc.zeroconf,
        ["_ipp._tcp.local."],
        handlers=[on_change],
    )
    await asyncio.sleep(timeout)
    await browser.async_cancel()
    await azc.async_close()

    # Query each discovered printer
    for ip, meta in discovered.items():
        uri = f"ipp://{ip}/{meta['path']}"
        try:
            printer = IPP(uri)
            attrs = await printer.get_printer_attributes()
            tag = attrs.get("printer-attributes-tag", {})
            print(f"{ip}: {tag.get('printer-make-and-model', 'unknown')}")
        except Exception as e:
            print(f"{ip}: IPP query failed -- {e}")

asyncio.run(discover_and_query())
```

### Pros

- Retrieves detailed capability information (supported media, formats, state).
- IPP is the modern standard -- all Epson L416x printers support it.
- Useful for both discovery verification and ongoing status monitoring.

### Cons

- IPP is not a discovery protocol by itself -- you need an IP address first
  (from mDNS, SNMP, or network scan).
- The Epson L416x uses the IPP path `/ipp/print` (confirmed via mDNS TXT
  record `rp` field). Other Epson models may use different paths.
- Requires port 631 to be open (it usually is on Epson printers).

### Reliability for Epson L416x

**HIGH** when combined with mDNS discovery. The L416x fully supports IPP 1.1
and advertises the service. Once you have the IP from mDNS, IPP queries are
reliable and return rich metadata.

---

## 4. Network Scanning (Port-Based Discovery)

### How It Works

Scan a subnet for hosts that have printer-related ports open:

| Port | Protocol | What It Indicates |
|------|----------|-------------------|
| **9100** | Raw/JetDirect (PDL datastream) | Almost certainly a printer |
| **631** | IPP | Printer or CUPS server |
| **515** | LPD | Printer or print server |
| **161** | SNMP | Network device (router, printer, etc.) |
| **80** | HTTP | Embedded web server (could be printer, router, anything) |

Port 9100 is the strongest signal -- virtually every network printer listens
on it for raw print jobs.

### Python Libraries / Approaches

| Approach | Library | Notes |
|----------|---------|-------|
| **Socket connect** | `asyncio.open_connection()` | Lightweight, no dependencies |
| **python-nmap** | `pip install python-nmap` | Wrapper around `nmap` CLI |
| **Scapy** | `pip install scapy` | Craft raw packets (SYN scans) |

### Code Example -- Pure Socket Scan

```python
import asyncio
import ipaddress

PRINTER_PORTS = [9100, 631, 515]

async def check_port(ip: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a TCP port is open."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
        return False

async def check_host(ip: str, sem: asyncio.Semaphore) -> dict | None:
    """Check if a host has printer ports open."""
    async with sem:
        tasks = [check_port(ip, port) for port in PRINTER_PORTS]
        results = await asyncio.gather(*tasks)
        open_ports = [p for p, is_open in zip(PRINTER_PORTS, results) if is_open]

        if 9100 in open_ports:  # Strong signal -- definitely a printer
            return {
                "ip": ip,
                "open_ports": open_ports,
                "likely_printer": True,
                "method": "port_scan",
            }
    return None

async def scan_for_printers(subnet: str = "192.168.1.0/24") -> list[dict]:
    """Scan a subnet for likely printers by checking common ports."""
    sem = asyncio.Semaphore(100)
    hosts = [str(ip) for ip in ipaddress.IPv4Network(subnet, strict=False)]
    tasks = [check_host(h, sem) for h in hosts]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]

if __name__ == "__main__":
    printers = asyncio.run(scan_for_printers())
    for p in printers:
        print(f"Printer at {p['ip']} -- ports open: {p['open_ports']}")
```

### Code Example -- python-nmap Approach

```python
import nmap

def scan_with_nmap(subnet: str = "192.168.1.0/24") -> list[dict]:
    """Use nmap to find hosts with printer ports open."""
    scanner = nmap.PortScanner()
    scanner.scan(hosts=subnet, ports="9100,631,515,161", arguments="-T4 --open")

    printers = []
    for host in scanner.all_hosts():
        open_ports = []
        for proto in scanner[host].all_protocols():
            open_ports.extend(scanner[host][proto].keys())

        if 9100 in open_ports:
            printers.append({
                "ip": host,
                "hostname": scanner[host].hostname(),
                "open_ports": open_ports,
            })

    return printers

printers = scan_with_nmap()
for p in printers:
    print(f"{p['ip']} ({p['hostname']}) -- ports: {p['open_ports']}")
```

### Pros

- Works regardless of printer configuration (SNMP disabled, mDNS off, etc.).
  As long as the printer accepts connections on port 9100, you will find it.
- Port 9100 is an extremely reliable indicator of a network printer.
- Pure socket approach has zero dependencies.
- Fast: a /24 scan with 100 concurrent connections completes in 2-5 seconds.

### Cons

- Returns minimal information -- just an IP and open ports. You still need
  SNMP or IPP to get model/make details.
- Cannot distinguish between two printers on the same subnet without further
  queries.
- Port scanning may trigger network security alerts in corporate environments
  (fine for home LAN).
- `python-nmap` requires `nmap` to be installed on the system.

### Reliability for Epson L416x

**VERY HIGH** for detection. The Epson L416x listens on port 9100 for raw
printing by default. This is the most "fire-and-forget" detection method.
However, you need a second step (SNMP query or mDNS) to confirm it is an
Epson printer specifically.

---

## Comparison Matrix

| Criterion | SNMP | mDNS/Zeroconf | IPP | Port Scan |
|-----------|------|---------------|-----|-----------|
| **Discovery speed** | 5-15s (scanning) | 1-3s (passive) | N/A (needs IP) | 2-5s (scanning) |
| **Info richness** | Very high (ink levels!) | High (model, caps) | High (caps, state) | Low (IP + ports only) |
| **Dependencies** | puresnmp or pysnmp | zeroconf | pyipp | None (stdlib) |
| **Works if mDNS is off** | Yes | No | Needs IP | Yes |
| **Works if SNMP is off** | No | Yes | Needs IP | Yes |
| **Cross-subnet** | Yes (if routed) | No (needs reflector) | Needs IP | Yes |
| **Identifies Epson** | Yes (sysDescr) | Yes (TXT record) | Yes (make/model) | No (just finds printer) |
| **Epson L416x support** | Full | Full | Full | Full |
| **Ongoing monitoring** | Yes (ink, pages) | No | Yes (state) | No |

---

## Recommendation for epson-keeper (Home / Small Office LAN)

### Primary Method: mDNS/Zeroconf

Use mDNS as the primary discovery mechanism. It is the fastest, requires no
subnet knowledge, returns rich metadata, and is exactly how Epson's own tools
and AirPrint discover printers. On a home LAN where the printer is already
configured and connected to Wi-Fi, mDNS will find it within 1-3 seconds.

### Fallback: SNMP Subnet Scan

If mDNS fails (printer is on a wired connection without mDNS, or mDNS was
disabled), fall back to an SNMP scan of the local subnet. This also gives
you ink level monitoring for free.

### Verification: Port 9100 Check

As a lightweight verification step, confirm the printer is reachable on port
9100 before attempting to send print jobs. This costs one TCP connect and
takes under 1 second.

### Suggested Discovery Pipeline

```
1. Try mDNS (5-second timeout)
   -> Found Epson printer? Use it. Extract IP, model, capabilities.
   -> Continue to step 2 as well (SNMP gives ink levels).

2. SNMP probe of discovered IPs
   -> Get ink levels, page count, serial number.
   -> Cache for monitoring.

3. If mDNS found nothing, scan local subnet via SNMP (fallback)
   -> Check sysDescr for "EPSON".
   -> Get ink levels.

4. Verify port 9100 is open before accepting print jobs.

5. Cache discovered printer info (IP, model, capabilities) to avoid
   re-scanning on every invocation.
```

### Dependencies to Add to the Project

```toml
[project.dependencies]
zeroconf = ">=0.131.0"       # mDNS discovery
puresnmp = ">=3.0.0"         # SNMP queries (ink levels, model)
# pyipp = ">=0.17.0"         # Optional: IPP capability queries
```

### Quick-Start Discovery Function

```python
import asyncio
from epson_keeper.discovery import discover_printer  # your module

async def main():
    printer = await discover_printer()
    # printer.ip        = "192.168.1.50"
    # printer.model     = "EPSON L4160 Series"
    # printer.ink_levels = {"K": 85, "C": 60, "M": 70, "Y": 55}
    # printer.port      = 9100
    print(f"Using {printer.model} at {printer.ip}")
```
