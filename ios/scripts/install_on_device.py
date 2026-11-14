"""Build, install, and launch Hologram using Xcode's command line tools."""

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit, urlunsplit


IOS = Path(__file__).resolve().parents[1]
ROOT = IOS.parent
SETTING_KEYS = {"APPLE_TEAM_ID", "DEPLOY_WEB_URL", "DEPLOY_API_URL", "WEB_URL", "API_URL", "BUNDLE_ID"}


def read_settings(path, allowed):
    """Read whitelisted literal assignments; never source .env as shell code."""
    if not path.exists():
        return {}
    settings = {}
    for line in path.read_text().splitlines():
        match = re.match(r"\s*(?:export\s+)?([A-Z_]+)\s*=\s*(.*?)\s*$", line)
        if match and match[1] in allowed:
            parts = shlex.split(match[2], comments=True)
            settings[match[1]] = " ".join(parts)
    return settings


def settings():
    values = read_settings(ROOT / ".env", SETTING_KEYS)
    values.update({key: os.environ[key] for key in SETTING_KEYS if os.environ.get(key)})
    local = read_settings(IOS / "Config/Local.xcconfig", {"DEVELOPMENT_TEAM"})
    team = os.environ.get("APPLE_TEAM_ID") or local.get("DEVELOPMENT_TEAM") or values.get("APPLE_TEAM_ID", "")
    if team and not re.fullmatch(r"[A-Z0-9]{10}", team):
        raise ValueError("Invalid development team; set APPLE_TEAM_ID or Config/Local.xcconfig DEVELOPMENT_TEAM.")
    bundle = values.get("BUNDLE_ID") or "com.teamrs3.hologram"
    if not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", bundle):
        raise ValueError("BUNDLE_ID must be a reverse DNS identifier, such as com.teamrs3.hologram.")
    web = values.get("WEB_URL") or values.get("DEPLOY_WEB_URL")
    if not web:
        address = subprocess.run(["ipconfig", "getifaddr", "en0"], capture_output=True, text=True)
        host = address.stdout.strip()
        if address.returncode or not host:
            # Discovery/dry-run and a generic signed build do not need a LAN URL.
            return team, bundle, None, values.get("API_URL") or values.get("DEPLOY_API_URL")
        web = f"http://{host}:4173"
    parts = urlsplit(web)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("WEB_URL must be an HTTP(S) URL without credentials.")
    # Match AppConfiguration's default API routing for local development.
    host = parts.hostname
    local_host = (host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local")
                  or host.startswith(("192.168.", "10."))
                  or (host.startswith("172.") and host.split(".")[1].isdigit()
                      and 16 <= int(host.split(".")[1]) <= 31)
                  or parts.port in {4173, 5173})
    authority = f"[{host}]" if ":" in host else host
    api = (values.get("API_URL") or values.get("DEPLOY_API_URL")
           or urlunsplit((parts.scheme, f"{authority}:8000" if local_host else parts.netloc, "", "", "")))
    parsed_api = urlsplit(api)
    if parsed_api.scheme not in {"http", "https"} or not parsed_api.hostname or parsed_api.username or parsed_api.password:
        raise ValueError("API_URL must be an HTTP(S) URL without credentials.")
    return team, bundle, web, api


def connected_iphones(payload):
    """Select physical iPhones, including paired Wi-Fi devices without an open tunnel."""
    selected = []
    for device in payload.get("result", {}).get("devices", []):
        properties = device.get("properties", {})
        hardware = properties.get("hardware") or device.get("hardwareProperties", {})
        connection = properties.get("connection") or device.get("connectionProperties", {})
        details = properties.get("device") or device.get("deviceProperties", {})
        state = properties.get("state", {})
        availability = state.get("availability", "").lower()
        kind = hardware.get("deviceType") or hardware.get("productType", "")
        platform = hardware.get("platform", "").lower()
        reality = hardware.get("reality", "").lower()
        if reality and reality != "physical":
            continue
        if platform and platform != "ios":
            continue
        if not (kind.startswith("iPhone") or (not kind and platform == "ios" and reality == "physical")):
            continue
        paired = (connection.get("pairingState") == "paired"
                  or availability == "available (paired)")
        # A paired physical device need not have a CoreDevice tunnel open yet.
        # In the legacy JSON there is no availability field; pairing is the
        # available signal. Explicit unavailable/offline state still excludes it.
        available = (availability in {"available", "available (paired)", "connected"}
                     or state.get("connectionState") == "connected"
                     or connection.get("tunnelState") == "connected"
                     or (not availability and connection.get("tunnelState") in {None, "disconnected"}))
        if availability in {"unavailable", "disconnected", "offline", "shutdown"}:
            available = False
        udid = hardware.get("udid")
        if paired and available and udid:
            selected.append((udid, details.get("name", "iPhone")))
    return sorted(selected)


def discover_device():
    with tempfile.TemporaryDirectory(prefix="hologram-devices-") as directory:
        output = Path(directory) / "devices.json"
        result = subprocess.run(["xcrun", "devicectl", "list", "devices", "--timeout", "15",
                                 "--json-output", str(output)], capture_output=True, text=True)
        if result.returncode:
            print("Device discovery failed:", file=sys.stderr)
            print((result.stderr or result.stdout).strip(), file=sys.stderr)
            return [], False
        return connected_iphones(json.loads(output.read_text())), True


def run(command):
    subprocess.run([str(part) for part in command], check=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print settings and discover devices; do not build/install/launch.")
    parser.add_argument("--build-only", action="store_true", help="Try a signed generic iOS build without requiring a phone.")
    parser.add_argument("--device", help="Choose a connected paired iPhone by its UDID when several are present.")
    args = parser.parse_args(argv)
    team, bundle, web, api = settings()
    print(f"Signing: Automatic; DEVELOPMENT_TEAM={team or '(missing)'}", flush=True)
    print(f"Bundle ID: {bundle}\nWEB_URL: {web or '(no LAN IP on en0; set WEB_URL)'}\nAPI_URL: {api or '(requires WEB_URL or API_URL)'}", flush=True)
    print("LAN reminder: the Mac's Vite preview must listen on 0.0.0.0 (--host 0.0.0.0), port 4173; API on 8000.", flush=True)
    destination = "generic/platform=iOS"
    if not args.build_only:
        devices, discovery_ok = discover_device()
        if args.device:
            devices = [device for device in devices if device[0] == args.device]
        if not devices:
            print("no device connected" + (" (or CoreDevice unavailable)" if not discovery_ok else "")
                  + ": unlock and pair an iPhone, trust this Mac, enable Developer Mode, then rerun.", flush=True)
            return 0 if args.dry_run else 1
        if len(devices) > 1:
            for udid, name in devices:
                print(f"  {name}: {udid}")
            raise ValueError("Several paired iPhones are connected; select one with --device <UDID>.")
        udid, name = devices[0]
        print(f"Connected paired iPhone: {name} ({udid})", flush=True)
        destination = f"id={udid}"
    print(f"Destination: {destination}\nDerivedData: {IOS / 'build/DerivedData'}", flush=True)
    if args.dry_run:
        print("Dry run complete; no build, install, or launch performed.")
        return 0
    if not team:
        raise ValueError("Missing signing team: set APPLE_TEAM_ID in .env or DEVELOPMENT_TEAM in ios/Config/Local.xcconfig.")
    if not args.build_only and not web:
        raise ValueError("No LAN IP on en0. Connect Wi-Fi or set WEB_URL=http://<Mac-LAN-IP>:4173.")
    run(["xcodegen", "generate", "--spec", IOS / "project.yml"])
    run(["bash", ROOT / "scripts/heavy.sh", "xcodebuild", "-project", IOS / "Hologram.xcodeproj",
         "-scheme", "Hologram", "-configuration", "Debug", "-allowProvisioningUpdates",
         "-allowProvisioningDeviceRegistration", "-destination", destination,
         "-derivedDataPath", IOS / "build/DerivedData", "CODE_SIGN_STYLE=Automatic",
         f"DEVELOPMENT_TEAM={team}", f"PRODUCT_BUNDLE_IDENTIFIER={bundle}",
         *([f"HOLOGRAM_WEB_URL={web}", f"HOLOGRAM_API_URL={api or ''}"] if web else []),
         f"HOLOGRAM_AR_DEMO={'YES' if os.environ.get('AR_DEMO') == '1' else 'NO'}", "build"])
    if args.build_only:
        print("Signed generic iOS build succeeded; install and AR still require the iPhone.")
        return 0
    app = IOS / "build/DerivedData/Build/Products/Debug-iphoneos/Hologram.app"
    if not app.is_dir():
        raise ValueError(f"Build completed but the app bundle is missing: {app}")
    run(["xcrun", "devicectl", "device", "install", "app", "--device", udid, app])
    run(["xcrun", "devicectl", "device", "process", "launch", "--device", udid,
         "--terminate-existing", bundle, "--", "-WEB_URL", web, "-API_URL", api])
    print("Installed and launched Hologram. Allow local network and camera access on the iPhone.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as error:
        print(f"Command failed (exit {error.returncode}). See ios/README.md for signing, pairing, and launch fixes.", file=sys.stderr)
        sys.exit(error.returncode)
