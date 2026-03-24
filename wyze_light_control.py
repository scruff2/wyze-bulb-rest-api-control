#!/usr/bin/env python3

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


SET_PROPERTY_LIST_URL = "https://app.wyzecam.com/app/v2/device_list/set_property_list"
GET_PROPERTY_LIST_URL = "https://app.wyzecam.com/app/v2/device/get_property_list"
DEFAULT_HOOK_LOG = Path("captures/android/logcat/wyze_hook_20260323-192300.txt")
DEFAULT_CONFIG_PATH = Path("local_config.json")
EXAMPLE_DEVICE_MAC = "A1B2C3D4E5F6"
DEFAULT_DEVICE_MODEL = "WLPA19"
DEFAULT_APP_NAME = "com.hualai"
DEFAULT_APP_VERSION = "3.10.6.753"
DEFAULT_PHONE_SYSTEM_TYPE = "2"
DEFAULT_SC = "a626948714654991afd3c0dbd7cdb901"
DEFAULT_SV_SET_PROPERTY_LIST = "ddb9baef0d7f44379cd6bfaa8698e682"
DEFAULT_SV_GET_PROPERTY_LIST = "1df2807c63254e16a06213323fe8dec8"
DEFAULT_COLOR_TEMPERATURE_MIN = 2700
DEFAULT_COLOR_TEMPERATURE_MAX = 6500
DEFAULT_PRESETS = {
    "night": 5,
    "dim": 15,
    "bright": 85,
}
DEFAULT_TARGET_PID_LIST = [
    "P3",
    "P5",
    "P1501",
    "P1502",
    "P1507",
    "P1508",
]
SUPPORTED_CAPABILITIES = {
    "power": True,
    "brightness": True,
    "color_temperature": True,
    "state_read": True,
    "generic_properties": True,
    "presets": True,
    "groups": True,
    "group_presets": True,
    "group_state_apply": True,
    "scenes": True,
    "toggle": True,
    "transition": True,
    "config_summary": True,
    "config_reload": True,
}
PLACEHOLDER_PREFIXES = (
    "replace-with-",
    "replace-with-your-",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send basic Wyze bulb control commands using the captured cloud request shape."
    )
    parser.add_argument(
        "command",
        choices=["on", "off", "brightness", "color-temperature", "state", "properties"],
        help="Light command to send.",
    )
    parser.add_argument(
        "value",
        nargs="?",
        type=int,
        help="Brightness level 1-100, or color temperature in Kelvin 2700-6500.",
    )
    parser.add_argument(
        "--hook-log",
        type=Path,
        default=DEFAULT_HOOK_LOG,
        help=f"Path to the captured WYZE_HOOK log. Default: {DEFAULT_HOOK_LOG}",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Local JSON config file. Default: {DEFAULT_CONFIG_PATH}",
    )
    parser.add_argument("--access-token", help="Override access token.")
    parser.add_argument("--phone-id", help="Override phone_id.")
    parser.add_argument("--device", help="Named device alias from local config.")
    parser.add_argument("--device-mac", help="Target device MAC without separators.")
    parser.add_argument("--device-model", help="Target device model.")
    parser.add_argument("--app-name", help="App package name.")
    parser.add_argument("--app-version", help="App version string.")
    parser.add_argument(
        "--phone-system-type",
        help="Phone system type used by the app wrapper.",
    )
    parser.add_argument("--sc", help="Wyze API sc value.")
    parser.add_argument("--sv", help="Wyze API sv value for device_list/set_property_list.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the request body without sending it.",
    )
    parser.add_argument(
        "--pid",
        action="append",
        default=[],
        help="Target PID for state reads, or PID to set when command is 'properties'. Repeat as needed.",
    )
    parser.add_argument(
        "--property",
        dest="properties",
        action="append",
        default=[],
        help="Property assignment in PID=VALUE form for command 'properties'. Repeat as needed.",
    )
    return parser.parse_args()


def extract_bodies(log_path: Path) -> list[dict]:
    if not log_path.exists():
        raise FileNotFoundError(f"Hook log not found: {log_path}")

    bodies: list[dict] = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        marker = "E WYZE_HOOK: BODY="
        if marker not in line:
            continue
        raw_json = line.split(marker, 1)[1].strip()
        try:
            bodies.append(json.loads(raw_json))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse JSON from hook log line: {line}") from exc
    if not bodies:
        raise ValueError(f"No WYZE_HOOK BODY lines found in: {log_path}")
    return bodies


def find_session_values(bodies: list[dict]) -> tuple[str, str]:
    for body in reversed(bodies):
        access_token = body.get("access_token")
        phone_id = body.get("phone_id")
        if access_token and phone_id:
            return access_token, phone_id
    raise ValueError("No access_token/phone_id pair found in the hook log.")


def find_device_values(bodies: list[dict]) -> tuple[str | None, str | None]:
    for body in reversed(bodies):
        device_list = body.get("device_list")
        if isinstance(device_list, list) and device_list:
            first = device_list[0]
            if isinstance(first, dict):
                device_mac = first.get("device_mac")
                device_model = first.get("device_model")
                if isinstance(device_mac, str) or isinstance(device_model, str):
                    return device_mac, device_model
        device_mac = body.get("device_mac")
        device_model = body.get("device_model")
        if isinstance(device_mac, str) or isinstance(device_model, str):
            return device_mac, device_model
    return None, None


def load_local_config(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse config JSON: {config_path}") from exc


def resolve_setting(
    cli_value: str | None,
    env_name: str,
    config: dict,
    config_key: str,
    default: str | None = None,
) -> str | None:
    if (
        isinstance(cli_value, str)
        and cli_value
        and cli_value != EXAMPLE_DEVICE_MAC
        and not cli_value.startswith(PLACEHOLDER_PREFIXES)
    ):
        return cli_value
    env_value = os.getenv(env_name)
    if (
        env_value
        and env_value != EXAMPLE_DEVICE_MAC
        and not env_value.startswith(PLACEHOLDER_PREFIXES)
    ):
        return env_value
    config_value = config.get(config_key)
    if (
        isinstance(config_value, str)
        and config_value
        and config_value != EXAMPLE_DEVICE_MAC
        and not config_value.startswith(PLACEHOLDER_PREFIXES)
    ):
        return config_value
    return default


def is_placeholder_value(value: str | None) -> bool:
    return (
        not value
        or value == EXAMPLE_DEVICE_MAC
        or value.startswith(PLACEHOLDER_PREFIXES)
    )


def get_device_config(config: dict, alias: str | None) -> dict:
    devices = config.get("devices")
    if not isinstance(devices, dict):
        return {}
    if alias and isinstance(devices.get(alias), dict):
        return devices[alias]
    return {}


def get_default_device_alias(config: dict) -> str | None:
    alias = config.get("default_device_alias")
    if isinstance(alias, str) and alias:
        return alias
    return None


def get_group_config(config: dict, alias: str | None) -> dict:
    groups = config.get("groups")
    if not isinstance(groups, dict):
        return {}
    if alias and isinstance(groups.get(alias), dict):
        return groups[alias]
    return {}


def get_presets(config: dict) -> dict:
    presets = dict(DEFAULT_PRESETS)
    configured = config.get("presets")
    if isinstance(configured, dict):
        for key, value in configured.items():
            if isinstance(key, str) and isinstance(value, int) and 1 <= value <= 100:
                presets[key] = value
    return presets


def get_device_presets(config: dict, alias: str | None) -> dict:
    presets = get_presets(config)
    if not alias:
        return presets
    device_config = get_device_config(config, alias)
    configured = device_config.get("presets")
    if isinstance(configured, dict):
        for key, value in configured.items():
            if isinstance(key, str) and isinstance(value, int) and 1 <= value <= 100:
                presets[key] = value
    return presets


def build_property_list(
    command: str,
    brightness: int | None,
    properties: list[str] | None = None,
) -> list[dict[str, str]]:
    if command == "on":
        return [{"pid": "P3", "pvalue": "1"}]
    if command == "off":
        return [{"pid": "P3", "pvalue": "0"}]
    if command == "color-temperature":
        if brightness is None:
            raise ValueError("color-temperature command requires a value.")
        if not DEFAULT_COLOR_TEMPERATURE_MIN <= brightness <= DEFAULT_COLOR_TEMPERATURE_MAX:
            raise ValueError(
                f"color-temperature must be between {DEFAULT_COLOR_TEMPERATURE_MIN} and {DEFAULT_COLOR_TEMPERATURE_MAX}."
            )
        return [
            {"pid": "P3", "pvalue": "1"},
            {"pid": "P1502", "pvalue": str(brightness)},
        ]
    if command == "properties":
        parsed = parse_property_assignments(properties or [])
        if not parsed:
            raise ValueError("properties command requires at least one --property PID=VALUE assignment.")
        return parsed
    if brightness is None:
        raise ValueError("Brightness command requires a value.")
    if not 1 <= brightness <= 100:
        raise ValueError("Brightness must be between 1 and 100.")
    return [
        {"pid": "P3", "pvalue": "1"},
        {"pid": "P1501", "pvalue": str(brightness)},
    ]


def parse_property_assignments(items: list[str]) -> list[dict[str, str]]:
    property_list: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, str) or "=" not in item:
            raise ValueError(f"Invalid property assignment '{item}'. Expected PID=VALUE.")
        pid, value = item.split("=", 1)
        pid = pid.strip()
        value = value.strip()
        if not pid or not value:
            raise ValueError(f"Invalid property assignment '{item}'. Expected PID=VALUE.")
        property_list.append({"pid": pid, "pvalue": value})
    return property_list


def build_set_property_payload(
    args: argparse.Namespace,
    access_token: str,
    phone_id: str,
    property_list: list[dict[str, str]] | None = None,
) -> dict:
    property_list = property_list or build_property_list(args.command, args.value, getattr(args, "properties", None))
    if not args.device_mac:
        raise ValueError("device_mac is required via --device-mac, environment, or local config")
    return {
        "access_token": access_token,
        "app_name": args.app_name,
        "app_ver": f"{args.app_name}___{args.app_version}",
        "app_version": args.app_version,
        "device_list": [
            {
                "device_mac": args.device_mac,
                "device_model": args.device_model,
                "property_list": property_list,
            }
        ],
        "phone_id": phone_id,
        "phone_system_type": args.phone_system_type,
        "sc": args.sc,
        "sv": args.sv,
        "ts": int(time.time() * 1000),
    }


def build_get_property_payload(
    args: argparse.Namespace,
    access_token: str,
    phone_id: str,
    target_pid_list: list[str] | None = None,
) -> dict:
    if not args.device_mac:
        raise ValueError("device_mac is required via --device-mac, environment, or local config")
    normalized = target_pid_list or DEFAULT_TARGET_PID_LIST
    return {
        "access_token": access_token,
        "app_name": args.app_name,
        "app_ver": f"{args.app_name}___{args.app_version}",
        "app_version": args.app_version,
        "device_mac": args.device_mac,
        "device_model": args.device_model,
        "phone_id": phone_id,
        "phone_system_type": args.phone_system_type,
        "sc": args.sc,
        "sv": args.sv,
        "target_pid_list": normalized,
        "ts": int(time.time() * 1000),
    }


def resolve_runtime_settings(args: argparse.Namespace) -> tuple[dict, dict]:
    config = load_local_config(args.config)
    selected_alias = getattr(args, "device", None) or get_default_device_alias(config)
    device_config = get_device_config(config, selected_alias)

    settings = {
        "device": selected_alias,
        "device_mac": resolve_setting(args.device_mac, "WYZE_DEVICE_MAC", config, "device_mac"),
        "device_model": resolve_setting(
            args.device_model,
            "WYZE_DEVICE_MODEL",
            config,
            "device_model",
            DEFAULT_DEVICE_MODEL,
        ),
        "app_name": resolve_setting(
            args.app_name,
            "WYZE_APP_NAME",
            config,
            "app_name",
            DEFAULT_APP_NAME,
        ),
        "app_version": resolve_setting(
            args.app_version,
            "WYZE_APP_VERSION",
            config,
            "app_version",
            DEFAULT_APP_VERSION,
        ),
        "phone_system_type": resolve_setting(
            args.phone_system_type,
            "WYZE_PHONE_SYSTEM_TYPE",
            config,
            "phone_system_type",
            DEFAULT_PHONE_SYSTEM_TYPE,
        ),
        "sc": resolve_setting(args.sc, "WYZE_SC", config, "sc", DEFAULT_SC),
        "sv": resolve_setting(args.sv, "WYZE_SV", config, "sv", DEFAULT_SV_SET_PROPERTY_LIST),
        "access_token": resolve_setting(args.access_token, "WYZE_ACCESS_TOKEN", config, "access_token"),
        "phone_id": resolve_setting(args.phone_id, "WYZE_PHONE_ID", config, "phone_id"),
    }

    configured_device_mac = device_config.get("device_mac")
    if isinstance(configured_device_mac, str) and not is_placeholder_value(configured_device_mac):
        settings["device_mac"] = settings["device_mac"] or configured_device_mac

    configured_device_model = device_config.get("device_model")
    if isinstance(configured_device_model, str) and configured_device_model:
        settings["device_model"] = settings["device_model"] or configured_device_model

    needs_hook_lookup = (
        not settings["access_token"]
        or not settings["phone_id"]
        or not settings["device_mac"]
        or not settings["device_model"]
    )
    if needs_hook_lookup:
        bodies = extract_bodies(args.hook_log)
        if not settings["access_token"] or not settings["phone_id"]:
            logged_token, logged_phone_id = find_session_values(bodies)
            settings["access_token"] = settings["access_token"] or logged_token
            settings["phone_id"] = settings["phone_id"] or logged_phone_id
        if not settings["device_mac"] or not settings["device_model"]:
            logged_device_mac, logged_device_model = find_device_values(bodies)
            settings["device_mac"] = settings["device_mac"] or logged_device_mac
            settings["device_model"] = settings["device_model"] or logged_device_model

    if not settings["device_mac"]:
        raise ValueError("device_mac is required via --device-mac, environment, or local config")

    return settings, config


def make_runtime_args(
    base_args: argparse.Namespace,
    command: str,
    value: int | None = None,
    pid: list[str] | None = None,
    properties: list[str] | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        command=command,
        value=value,
        hook_log=base_args.hook_log,
        config=base_args.config,
        access_token=base_args.access_token,
        phone_id=base_args.phone_id,
        device=getattr(base_args, "device", None),
        device_mac=base_args.device_mac,
        device_model=base_args.device_model,
        app_name=base_args.app_name,
        app_version=base_args.app_version,
        phone_system_type=base_args.phone_system_type,
        sc=base_args.sc,
        sv=base_args.sv,
        timeout=base_args.timeout,
        dry_run=base_args.dry_run,
        pid=list(pid or []),
        properties=list(properties or []),
    )


def perform_command(args: argparse.Namespace) -> tuple[int, str, dict]:
    settings, _ = resolve_runtime_settings(args)

    runtime_args = make_runtime_args(
        args,
        args.command,
        args.value,
        getattr(args, "pid", []),
        getattr(args, "properties", []),
    )
    runtime_args.device = settings["device"]
    runtime_args.device_mac = settings["device_mac"]
    runtime_args.device_model = settings["device_model"]
    runtime_args.app_name = settings["app_name"]
    runtime_args.app_version = settings["app_version"]
    runtime_args.phone_system_type = settings["phone_system_type"]
    runtime_args.sc = settings["sc"]
    runtime_args.sv = settings["sv"] or DEFAULT_SV_SET_PROPERTY_LIST

    payload = build_set_property_payload(runtime_args, settings["access_token"], settings["phone_id"])
    status_code, response_text = send_request(SET_PROPERTY_LIST_URL, payload, args.timeout)
    return status_code, response_text, payload


def perform_state_query(args: argparse.Namespace) -> tuple[int, str, dict]:
    settings, _ = resolve_runtime_settings(args)

    runtime_args = make_runtime_args(
        args,
        "state",
        None,
        getattr(args, "pid", []),
        [],
    )
    runtime_args.device = settings["device"]
    runtime_args.device_mac = settings["device_mac"]
    runtime_args.device_model = settings["device_model"]
    runtime_args.app_name = settings["app_name"]
    runtime_args.app_version = settings["app_version"]
    runtime_args.phone_system_type = settings["phone_system_type"]
    runtime_args.sc = settings["sc"]
    runtime_args.sv = DEFAULT_SV_GET_PROPERTY_LIST

    target_pid_list = runtime_args.pid or DEFAULT_TARGET_PID_LIST
    payload = build_get_property_payload(
        runtime_args,
        settings["access_token"],
        settings["phone_id"],
        target_pid_list,
    )
    status_code, response_text = send_request(GET_PROPERTY_LIST_URL, payload, args.timeout)
    return status_code, response_text, payload


def get_group_members(config: dict, alias: str) -> list[str]:
    group_config = get_group_config(config, alias)
    members = group_config.get("devices")
    if not isinstance(members, list):
        raise ValueError(f"group '{alias}' is not configured")
    normalized = [item for item in members if isinstance(item, str) and item]
    if not normalized:
        raise ValueError(f"group '{alias}' has no devices")
    return normalized


def get_scene_config(config: dict, alias: str | None) -> dict:
    scenes = config.get("scenes")
    if not isinstance(scenes, dict):
        return {}
    if alias and isinstance(scenes.get(alias), dict):
        return scenes[alias]
    return {}


def validate_scene_definition(scene_name: str, scene_config: dict) -> None:
    target = scene_config.get("target")
    commands = scene_config.get("commands")
    if not isinstance(target, str) or not target:
        raise ValueError(f"scene '{scene_name}' is missing target")
    if not isinstance(commands, list) or not commands:
        raise ValueError(f"scene '{scene_name}' has no commands")
    for item in commands:
        if not isinstance(item, dict):
            raise ValueError(f"scene '{scene_name}' contains an invalid command entry")
        command = item.get("command")
        value = item.get("value")
        if command not in ("on", "off", "brightness", "color-temperature", "properties"):
            raise ValueError(f"scene '{scene_name}' contains unsupported command '{command}'")
        if command in ("brightness", "color-temperature") and not isinstance(value, int):
            raise ValueError(f"scene '{scene_name}' command '{command}' requires integer value")
        if command == "brightness" and not 1 <= value <= 100:
            raise ValueError(f"scene '{scene_name}' brightness value must be between 1 and 100")
        if command == "color-temperature" and not DEFAULT_COLOR_TEMPERATURE_MIN <= value <= DEFAULT_COLOR_TEMPERATURE_MAX:
            raise ValueError(
                f"scene '{scene_name}' color-temperature value must be between {DEFAULT_COLOR_TEMPERATURE_MIN} and {DEFAULT_COLOR_TEMPERATURE_MAX}"
            )
        if command == "properties":
            properties = item.get("properties")
            if not isinstance(properties, list) or not properties:
                raise ValueError(f"scene '{scene_name}' properties command requires non-empty properties list")


def send_request(url: str, payload: dict, timeout: float) -> tuple[int, str]:
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": "WyzeLightControl/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.getcode(), response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body


def redact_payload(payload: dict) -> dict:
    redacted = json.loads(json.dumps(payload))
    token = redacted.get("access_token")
    if isinstance(token, str) and token:
        redacted["access_token"] = f"{token[:12]}...{token[-8:]}"
    return redacted


def main() -> int:
    args = parse_args()

    value_commands = {"brightness", "color-temperature"}
    if args.command in value_commands and args.value is None:
        if args.command == "color-temperature":
            print(
                f"{args.command} requires a numeric Kelvin value between {DEFAULT_COLOR_TEMPERATURE_MIN} and {DEFAULT_COLOR_TEMPERATURE_MAX}",
                file=sys.stderr,
            )
        else:
            print(f"{args.command} requires a numeric value between 1 and 100", file=sys.stderr)
        return 2
    if args.command not in value_commands and args.value is not None:
        print(f"{args.command} does not accept a numeric value", file=sys.stderr)
        return 2
    if args.command == "properties" and not args.properties:
        print("properties requires at least one --property PID=VALUE assignment", file=sys.stderr)
        return 2
    if args.command != "properties" and args.properties:
        print("--property is only valid with the properties command", file=sys.stderr)
        return 2
    if args.command != "state" and args.pid:
        print("--pid is only valid with the state command", file=sys.stderr)
        return 2

    try:
        settings, _ = resolve_runtime_settings(args)
        args.device_mac = settings["device_mac"]
        args.device_model = settings["device_model"]
        args.app_name = settings["app_name"]
        args.app_version = settings["app_version"]
        args.phone_system_type = settings["phone_system_type"]
        args.sc = settings["sc"]
        if args.command == "state":
            args.sv = DEFAULT_SV_GET_PROPERTY_LIST
            payload = build_get_property_payload(
                args,
                settings["access_token"],
                settings["phone_id"],
                args.pid or DEFAULT_TARGET_PID_LIST,
            )
        else:
            args.sv = settings["sv"] or DEFAULT_SV_SET_PROPERTY_LIST
            payload = build_set_property_payload(args, settings["access_token"], settings["phone_id"])
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.dry_run:
        print(json.dumps(redact_payload(payload), indent=2))
        return 0

    try:
        if args.command == "state":
            status_code, response_text, _ = perform_state_query(args)
        else:
            status_code, response_text, _ = perform_command(args)
    except (urllib.error.URLError, FileNotFoundError, ValueError) as exc:
        print(f"request failed: {exc}", file=sys.stderr)
        return 1

    print(f"HTTP {status_code}")
    try:
        parsed = json.loads(response_text)
        print(json.dumps(parsed, indent=2))
    except json.JSONDecodeError:
        print(response_text)

    return 0 if 200 <= status_code < 300 else 1


if __name__ == "__main__":
    raise SystemExit(main())
