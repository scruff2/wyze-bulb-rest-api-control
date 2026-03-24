#!/usr/bin/env python3

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import wyze_light_control as control


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Expose a small local HTTP API for Wyze bulb control."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host. Default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=8787, help="Bind port. Default: 8787")
    parser.add_argument("--config", type=control.Path, default=control.DEFAULT_CONFIG_PATH)
    parser.add_argument("--hook-log", type=control.Path, default=control.DEFAULT_HOOK_LOG)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--access-token")
    parser.add_argument("--phone-id")
    parser.add_argument("--device")
    parser.add_argument("--device-mac")
    parser.add_argument("--device-model")
    parser.add_argument("--app-name")
    parser.add_argument("--app-version")
    parser.add_argument("--phone-system-type")
    parser.add_argument("--sc")
    parser.add_argument("--sv")
    return parser.parse_args()


def make_control_args(server_args: argparse.Namespace, command: str, value: int | None = None) -> argparse.Namespace:
    return argparse.Namespace(
        command=command,
        value=value,
        hook_log=server_args.hook_log,
        config=server_args.config,
        access_token=server_args.access_token,
        phone_id=server_args.phone_id,
        device=server_args.device,
        device_mac=server_args.device_mac,
        device_model=server_args.device_model,
        app_name=server_args.app_name,
        app_version=server_args.app_version,
        phone_system_type=server_args.phone_system_type,
        sc=server_args.sc,
        sv=server_args.sv,
        timeout=server_args.timeout,
        dry_run=False,
    )


class WyzeLightApiHandler(BaseHTTPRequestHandler):
    server_version = "WyzeLightApi/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/status":
            config = control.load_local_config(self.server.control_args.config)
            self.write_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "wyze-light-api",
                    "endpoints": {
                        "GET /status": "health check",
                        "GET /devices": "list configured device aliases",
                        "GET /groups": "list configured groups",
                        "GET /scenes": "list configured scenes",
                        "POST /on": {},
                        "POST /off": {},
                        "POST /night": {},
                        "POST /dim": {},
                        "POST /bright": {},
                        "POST /group/on": {"group": "group-alias"},
                        "POST /group/off": {"group": "group-alias"},
                        "POST /group/brightness": {"group": "group-alias", "brightness": "1-100"},
                        "POST /scene/run": {"scene": "scene-alias"},
                        "POST /scene/evening": {},
                        "POST /scene/off": {},
                        "POST /brightness": {"brightness": "1-100"},
                    },
                    "devices": sorted(list(config.get("devices", {}).keys())) if isinstance(config.get("devices"), dict) else [],
                    "groups": sorted(list(config.get("groups", {}).keys())) if isinstance(config.get("groups"), dict) else [],
                    "scenes": sorted(list(config.get("scenes", {}).keys())) if isinstance(config.get("scenes"), dict) else [],
                    "default_device_alias": config.get("default_device_alias"),
                    "presets": control.get_presets(config),
                    "cloud_backed": True,
                },
            )
            return
        if parsed.path == "/devices":
            config = control.load_local_config(self.server.control_args.config)
            devices = config.get("devices", {})
            aliases = {}
            if isinstance(devices, dict):
                for alias, entry in devices.items():
                    if isinstance(alias, str) and isinstance(entry, dict):
                        aliases[alias] = {
                            "device_model": entry.get("device_model", control.DEFAULT_DEVICE_MODEL),
                            "has_device_mac": bool(entry.get("device_mac")),
                        }
            self.write_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "devices": aliases,
                    "default_device_alias": config.get("default_device_alias"),
                },
            )
            return
        if parsed.path == "/groups":
            config = control.load_local_config(self.server.control_args.config)
            groups = config.get("groups", {})
            payload = {}
            if isinstance(groups, dict):
                for alias, entry in groups.items():
                    if isinstance(alias, str) and isinstance(entry, dict):
                        members = entry.get("devices")
                        payload[alias] = members if isinstance(members, list) else []
            self.write_json(HTTPStatus.OK, {"ok": True, "groups": payload})
            return
        if parsed.path == "/scenes":
            config = control.load_local_config(self.server.control_args.config)
            scenes = config.get("scenes", {})
            payload = {}
            if isinstance(scenes, dict):
                for alias, entry in scenes.items():
                    if isinstance(alias, str) and isinstance(entry, dict):
                        payload[alias] = {
                            "target": entry.get("target"),
                            "command_count": len(entry.get("commands", [])) if isinstance(entry.get("commands"), list) else 0,
                        }
            self.write_json(HTTPStatus.OK, {"ok": True, "scenes": payload})
            return
        self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            body = self.read_json_body()
            device = self.resolve_device_alias(parsed.query, body)
            if parsed.path == "/on":
                self.handle_command("on", None, device)
                return
            if parsed.path == "/off":
                self.handle_command("off", None, device)
                return
            if parsed.path in ("/night", "/dim", "/bright"):
                preset_name = parsed.path.lstrip("/")
                brightness = self.get_preset_brightness(preset_name)
                self.handle_command("brightness", brightness, device, preset_name=preset_name)
                return
            if parsed.path in ("/group/on", "/group/off", "/group/brightness"):
                group = self.resolve_group_alias(parsed.query, body)
                if not group:
                    raise ValueError("group is required")
                if parsed.path == "/group/on":
                    self.handle_group_command(group, "on", None)
                    return
                if parsed.path == "/group/off":
                    self.handle_group_command(group, "off", None)
                    return
                brightness = body.get("brightness")
                if not isinstance(brightness, int):
                    raise ValueError("brightness must be an integer between 1 and 100")
                self.handle_group_command(group, "brightness", brightness)
                return
            if parsed.path in ("/scene/run", "/scene/evening", "/scene/off"):
                scene = body.get("scene")
                if parsed.path == "/scene/evening":
                    scene = "evening"
                if parsed.path == "/scene/off":
                    scene = "off"
                if not isinstance(scene, str) or not scene:
                    raise ValueError("scene is required")
                self.handle_scene(scene)
                return
            if parsed.path == "/brightness":
                brightness = body.get("brightness")
                if not isinstance(brightness, int):
                    raise ValueError("brightness must be an integer between 1 and 100")
                self.handle_command("brightness", brightness, device)
                return
            self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
        except ValueError as exc:
            self.write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

    def read_json_body(self) -> dict:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length == 0:
            return {}
        raw_body = self.rfile.read(content_length)
        try:
            return json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("request body must be valid JSON") from exc

    def resolve_device_alias(self, query: str, body: dict) -> str | None:
        query_params = parse_qs(query)
        query_device = query_params.get("device", [None])[0]
        body_device = body.get("device")
        if isinstance(body_device, str) and body_device:
            return body_device
        if isinstance(query_device, str) and query_device:
            return query_device
        return None

    def resolve_group_alias(self, query: str, body: dict) -> str | None:
        query_params = parse_qs(query)
        query_group = query_params.get("group", [None])[0]
        body_group = body.get("group")
        if isinstance(body_group, str) and body_group:
            return body_group
        if isinstance(query_group, str) and query_group:
            return query_group
        return None

    def get_preset_brightness(self, preset_name: str) -> int:
        config = control.load_local_config(self.server.control_args.config)
        presets = control.get_device_presets(config, self.server.control_args.device)
        brightness = presets.get(preset_name)
        if not isinstance(brightness, int):
            raise ValueError(f"preset '{preset_name}' is not configured")
        return brightness

    def handle_command(
        self,
        command: str,
        value: int | None,
        device: str | None,
        preset_name: str | None = None,
    ) -> None:
        args = make_control_args(self.server.control_args, command, value)
        args.device = device or args.device
        try:
            status_code, response_text, payload = control.perform_command(args)
            response_json = json.loads(response_text)
        except json.JSONDecodeError:
            response_json = {"raw_response": response_text}
        except Exception as exc:
            self.write_json(HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(exc)})
            return

        self.write_json(
            HTTPStatus.OK if 200 <= status_code < 300 else HTTPStatus.BAD_GATEWAY,
            {
                "ok": 200 <= status_code < 300,
                "command": command,
                "value": value,
                "device": args.device,
                "preset": preset_name,
                "cloud_backed": True,
                "request": control.redact_payload(payload),
                "wyze_status": status_code,
                "wyze_response": response_json,
            },
        )

    def handle_group_command(self, group: str, command: str, value: int | None) -> None:
        config = control.load_local_config(self.server.control_args.config)
        members = control.get_group_members(config, group)
        results = []
        overall_ok = True

        for alias in members:
            args = make_control_args(self.server.control_args, command, value)
            args.device = alias
            try:
                status_code, response_text, payload = control.perform_command(args)
                response_json = json.loads(response_text)
            except json.JSONDecodeError:
                response_json = {"raw_response": response_text}
                status_code = 502
                overall_ok = False
            except Exception as exc:
                results.append({"device": alias, "ok": False, "error": str(exc)})
                overall_ok = False
                continue

            item_ok = 200 <= status_code < 300 and response_json.get("msg") == "SUCCESS"
            overall_ok = overall_ok and item_ok
            results.append(
                {
                    "device": alias,
                    "ok": item_ok,
                    "wyze_status": status_code,
                    "request": control.redact_payload(payload),
                    "wyze_response": response_json,
                }
            )

        self.write_json(
            HTTPStatus.OK if overall_ok else HTTPStatus.BAD_GATEWAY,
            {
                "ok": overall_ok,
                "group": group,
                "command": command,
                "value": value,
                "cloud_backed": True,
                "results": results,
            },
        )

    def write_json(self, status: HTTPStatus, payload: dict) -> None:
        encoded = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def execute_for_target(self, target: str, command: str, value: int | None) -> dict:
        config = control.load_local_config(self.server.control_args.config)
        devices = config.get("devices", {})
        groups = config.get("groups", {})

        if isinstance(devices, dict) and target in devices:
            args = make_control_args(self.server.control_args, command, value)
            args.device = target
            status_code, response_text, payload = control.perform_command(args)
            response_json = json.loads(response_text)
            item_ok = 200 <= status_code < 300 and response_json.get("msg") == "SUCCESS"
            return {
                "target_type": "device",
                "target": target,
                "ok": item_ok,
                "wyze_status": status_code,
                "request": control.redact_payload(payload),
                "wyze_response": response_json,
            }

        if isinstance(groups, dict) and target in groups:
            members = control.get_group_members(config, target)
            results = []
            overall_ok = True
            for alias in members:
                args = make_control_args(self.server.control_args, command, value)
                args.device = alias
                status_code, response_text, payload = control.perform_command(args)
                response_json = json.loads(response_text)
                item_ok = 200 <= status_code < 300 and response_json.get("msg") == "SUCCESS"
                overall_ok = overall_ok and item_ok
                results.append(
                    {
                        "device": alias,
                        "ok": item_ok,
                        "wyze_status": status_code,
                        "request": control.redact_payload(payload),
                        "wyze_response": response_json,
                    }
                )
            return {
                "target_type": "group",
                "target": target,
                "ok": overall_ok,
                "results": results,
            }

        raise ValueError(f"target '{target}' is not a configured device or group")

    def handle_scene(self, scene: str) -> None:
        config = control.load_local_config(self.server.control_args.config)
        scene_config = control.get_scene_config(config, scene)
        if not scene_config:
            raise ValueError(f"scene '{scene}' is not configured")

        target = scene_config.get("target")
        commands = scene_config.get("commands")
        if not isinstance(target, str) or not target:
            raise ValueError(f"scene '{scene}' is missing target")
        if not isinstance(commands, list) or not commands:
            raise ValueError(f"scene '{scene}' has no commands")

        results = []
        overall_ok = True
        for item in commands:
            if not isinstance(item, dict):
                raise ValueError(f"scene '{scene}' contains an invalid command entry")
            command = item.get("command")
            value = item.get("value")
            if command not in ("on", "off", "brightness"):
                raise ValueError(f"scene '{scene}' contains unsupported command '{command}'")
            if command == "brightness" and not isinstance(value, int):
                raise ValueError(f"scene '{scene}' brightness command requires integer value")
            result = self.execute_for_target(target, command, value if isinstance(value, int) else None)
            overall_ok = overall_ok and result.get("ok", False)
            result["command"] = command
            result["value"] = value
            results.append(result)

        self.write_json(
            HTTPStatus.OK if overall_ok else HTTPStatus.BAD_GATEWAY,
            {
                "ok": overall_ok,
                "scene": scene,
                "target": target,
                "cloud_backed": True,
                "results": results,
            },
        )

    def log_message(self, format: str, *args) -> None:
        return


def main() -> int:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), WyzeLightApiHandler)
    server.control_args = args
    print(f"Listening on http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
