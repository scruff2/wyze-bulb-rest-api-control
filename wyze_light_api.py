#!/usr/bin/env python3

import argparse
import json
import time
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
        pid=[],
        properties=[],
    )


class WyzeLightApiHandler(BaseHTTPRequestHandler):
    server_version = "WyzeLightApi/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/status"):
            self.handle_status()
            return
        if parsed.path == "/health":
            self.handle_health()
            return
        if parsed.path == "/capabilities":
            self.handle_capabilities()
            return
        if parsed.path == "/config/summary":
            self.handle_config_summary()
            return
        if parsed.path == "/devices":
            self.handle_devices()
            return
        if parsed.path == "/presets":
            self.handle_presets(parsed.query)
            return
        if parsed.path == "/state":
            self.handle_state_get(parsed.query)
            return
        if parsed.path == "/state/raw":
            self.handle_state_raw_get(parsed.query)
            return
        if parsed.path == "/groups":
            self.handle_groups()
            return
        if parsed.path == "/scenes":
            self.handle_scenes()
            return
        if parsed.path.startswith("/scene/"):
            self.handle_scene_get(parsed.path)
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
            if parsed.path == "/toggle":
                self.handle_toggle(device)
                return
            if parsed.path in ("/night", "/dim", "/bright"):
                preset_name = parsed.path.lstrip("/")
                brightness = self.get_preset_brightness_for_device(preset_name, device)
                self.handle_command("brightness", brightness, device, preset_name=preset_name)
                return
            if parsed.path == "/preset/run":
                preset_name = body.get("preset")
                if not isinstance(preset_name, str) or not preset_name:
                    raise ValueError("preset is required")
                brightness = self.get_preset_brightness_for_device(preset_name, device)
                self.handle_command("brightness", brightness, device, preset_name=preset_name)
                return
            if parsed.path == "/reload-config":
                self.handle_reload_config()
                return
            if parsed.path == "/state/query":
                self.handle_state_query_post(device, body)
                return
            if parsed.path in ("/group/on", "/group/off", "/group/brightness"):
                self.handle_group_post(parsed.query, body, parsed.path)
                return
            if parsed.path == "/group/toggle":
                self.handle_group_toggle(parsed.query, body)
                return
            if parsed.path == "/group/preset":
                self.handle_group_preset(parsed.query, body)
                return
            if parsed.path == "/group/state/apply":
                self.handle_group_state_apply(parsed.query, body)
                return
            if parsed.path in ("/scene/run", "/scene/evening", "/scene/off"):
                self.handle_scene_post(parsed.path, body)
                return
            if parsed.path == "/scene/validate":
                scene_config = body.get("scene")
                if not isinstance(scene_config, dict):
                    raise ValueError("scene must be an object")
                self.handle_scene_validate(scene_config)
                return
            if parsed.path == "/brightness":
                brightness = body.get("brightness")
                if not isinstance(brightness, int):
                    raise ValueError("brightness must be an integer between 1 and 100")
                self.handle_command("brightness", brightness, device)
                return
            if parsed.path == "/color-temperature":
                color_temperature = body.get("color_temperature")
                if not isinstance(color_temperature, int):
                    raise ValueError(
                        f"color_temperature must be an integer between {control.DEFAULT_COLOR_TEMPERATURE_MIN} and {control.DEFAULT_COLOR_TEMPERATURE_MAX}"
                    )
                self.handle_command("color-temperature", color_temperature, device)
                return
            if parsed.path == "/state/apply":
                self.handle_state_apply(device, body)
                return
            if parsed.path == "/transition":
                self.handle_transition(device, body)
                return
            if parsed.path == "/properties":
                properties = body.get("properties")
                if not isinstance(properties, list) or not properties:
                    raise ValueError("properties must be a non-empty list")
                self.handle_properties(device, properties)
                return
            self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
        except ValueError as exc:
            self.write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

    def handle_status(self) -> None:
        config = control.load_local_config(self.server.control_args.config)
        self.write_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "service": "wyze-light-api",
                "endpoints": {
                    "GET /status": "health check",
                    "GET /health": "local service health and config readiness",
                    "GET /capabilities": "list supported API capabilities",
                    "GET /config/summary": "safe view of loaded aliases, groups, scenes, and presets",
                    "GET /devices": "list configured device aliases",
                    "GET /groups": "list configured groups",
                    "GET /presets": "list effective presets",
                    "GET /scenes": "list configured scenes",
                    "GET /scene/<name>": "get a configured scene definition",
                    "GET /state": {"device": "device-alias", "pid": ["P3", "P1501"]},
                    "GET /state/raw": {"device": "device-alias", "pid": ["P3", "P1501"]},
                    "POST /on": {},
                    "POST /off": {},
                    "POST /toggle": {},
                    "POST /night": {},
                    "POST /dim": {},
                    "POST /bright": {},
                    "POST /preset/run": {"preset": "night", "device": "device-alias"},
                    "POST /reload-config": {},
                    "POST /state/query": {"device": "device-alias", "pid": ["P3", "P1501"]},
                    "POST /group/on": {"group": "group-alias"},
                    "POST /group/off": {"group": "group-alias"},
                    "POST /group/toggle": {"group": "group-alias"},
                    "POST /group/brightness": {"group": "group-alias", "brightness": "1-100"},
                    "POST /group/preset": {"group": "group-alias", "preset": "night"},
                    "POST /group/state/apply": {"group": "group-alias", "brightness": 40, "color_temperature": 2700},
                    "POST /scene/run": {"scene": "scene-alias"},
                    "POST /scene/evening": {},
                    "POST /scene/off": {},
                    "POST /scene/validate": {"scene": {"target": "all", "commands": [{"command": "off"}]}},
                    "POST /brightness": {"brightness": "1-100"},
                    "POST /color-temperature": {"color_temperature": "2700-6500"},
                    "POST /state/apply": {"power": "on", "brightness": 40, "color_temperature": 2700},
                    "POST /transition": {"brightness": {"from": 10, "to": 80}, "duration_ms": 3000, "steps": 6},
                    "POST /properties": {"properties": [{"pid": "P1502", "pvalue": "2700"}]},
                },
                "devices": sorted(list(config.get("devices", {}).keys())) if isinstance(config.get("devices"), dict) else [],
                "groups": sorted(list(config.get("groups", {}).keys())) if isinstance(config.get("groups"), dict) else [],
                "scenes": sorted(list(config.get("scenes", {}).keys())) if isinstance(config.get("scenes"), dict) else [],
                "default_device_alias": config.get("default_device_alias"),
                "presets": control.get_presets(config),
                "cloud_backed": True,
            },
        )

    def handle_health(self) -> None:
        config = control.load_local_config(self.server.control_args.config)
        try:
            settings, _ = control.resolve_runtime_settings(self.server.control_args)
            runtime_ready = bool(settings.get("device_mac") and settings.get("access_token") and settings.get("phone_id"))
        except Exception:
            runtime_ready = False
        self.write_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "service": "wyze-light-api",
                "config_exists": self.server.control_args.config.exists(),
                "default_device_alias": config.get("default_device_alias"),
                "runtime_ready": runtime_ready,
                "cloud_backed": True,
            },
        )

    def handle_config_summary(self) -> None:
        config = control.load_local_config(self.server.control_args.config)
        devices = config.get("devices", {})
        device_summary = {}
        if isinstance(devices, dict):
            for alias, entry in devices.items():
                if isinstance(alias, str) and isinstance(entry, dict):
                    device_summary[alias] = {
                        "device_model": entry.get("device_model", control.DEFAULT_DEVICE_MODEL),
                        "has_device_mac": bool(entry.get("device_mac")),
                        "presets": control.get_device_presets(config, alias),
                    }
        groups = config.get("groups", {})
        group_summary = {}
        if isinstance(groups, dict):
            for alias, entry in groups.items():
                if isinstance(alias, str) and isinstance(entry, dict):
                    members = entry.get("devices")
                    group_summary[alias] = members if isinstance(members, list) else []
        scenes = config.get("scenes", {})
        scene_summary = {}
        if isinstance(scenes, dict):
            for alias, entry in scenes.items():
                if isinstance(alias, str) and isinstance(entry, dict):
                    scene_summary[alias] = {
                        "target": entry.get("target"),
                        "command_count": len(entry.get("commands", [])) if isinstance(entry.get("commands"), list) else 0,
                    }
        self.write_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "default_device_alias": config.get("default_device_alias"),
                "devices": device_summary,
                "groups": group_summary,
                "scenes": scene_summary,
                "presets": control.get_presets(config),
                "has_access_token": bool(config.get("access_token")),
                "has_phone_id": bool(config.get("phone_id")),
            },
        )

    def handle_reload_config(self) -> None:
        config = control.load_local_config(self.server.control_args.config)
        self.write_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "reloaded": True,
                "config_path": str(self.server.control_args.config),
                "default_device_alias": config.get("default_device_alias"),
                "device_count": len(config.get("devices", {})) if isinstance(config.get("devices"), dict) else 0,
                "group_count": len(config.get("groups", {})) if isinstance(config.get("groups"), dict) else 0,
                "scene_count": len(config.get("scenes", {})) if isinstance(config.get("scenes"), dict) else 0,
            },
        )

    def handle_capabilities(self) -> None:
        self.write_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "capabilities": control.SUPPORTED_CAPABILITIES,
                "brightness_range": {"min": 1, "max": 100},
                "color_temperature_range": {
                    "min": control.DEFAULT_COLOR_TEMPERATURE_MIN,
                    "max": control.DEFAULT_COLOR_TEMPERATURE_MAX,
                },
                "cloud_backed": True,
            },
        )

    def handle_devices(self) -> None:
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

    def handle_presets(self, query: str) -> None:
        config = control.load_local_config(self.server.control_args.config)
        device = parse_qs(query).get("device", [None])[0]
        self.write_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "device": device,
                "presets": control.get_device_presets(config, device),
            },
        )

    def handle_state_get(self, query: str) -> None:
        query_params = parse_qs(query)
        device = query_params.get("device", [None])[0]
        pid_values = query_params.get("pid", [])
        target_pid_list: list[str] = []
        for item in pid_values:
            if isinstance(item, str):
                target_pid_list.extend(part.strip() for part in item.split(",") if part.strip())
        self.handle_state_query(device, target_pid_list)

    def handle_state_raw_get(self, query: str) -> None:
        query_params = parse_qs(query)
        device = query_params.get("device", [None])[0]
        pid_values = query_params.get("pid", [])
        target_pid_list: list[str] = []
        for item in pid_values:
            if isinstance(item, str):
                target_pid_list.extend(part.strip() for part in item.split(",") if part.strip())
        self.handle_state_query(device, target_pid_list, include_raw=True)

    def handle_groups(self) -> None:
        config = control.load_local_config(self.server.control_args.config)
        groups = config.get("groups", {})
        payload = {}
        if isinstance(groups, dict):
            for alias, entry in groups.items():
                if isinstance(alias, str) and isinstance(entry, dict):
                    members = entry.get("devices")
                    payload[alias] = members if isinstance(members, list) else []
        self.write_json(HTTPStatus.OK, {"ok": True, "groups": payload})

    def handle_scenes(self) -> None:
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

    def handle_scene_get(self, path: str) -> None:
        scene_name = path.removeprefix("/scene/")
        if scene_name in {"run", "evening", "off", "validate"} or not scene_name:
            self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return
        config = control.load_local_config(self.server.control_args.config)
        scene_config = control.get_scene_config(config, scene_name)
        if not scene_config:
            self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": f"scene '{scene_name}' is not configured"})
            return
        self.write_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "scene": scene_name,
                "definition": scene_config,
            },
        )

    def handle_group_post(self, query: str, body: dict, path: str) -> None:
        group = self.resolve_group_alias(query, body)
        if not group:
            raise ValueError("group is required")
        if path == "/group/on":
            self.handle_group_command(group, "on", None)
            return
        if path == "/group/off":
            self.handle_group_command(group, "off", None)
            return
        brightness = body.get("brightness")
        if not isinstance(brightness, int):
            raise ValueError("brightness must be an integer between 1 and 100")
        self.handle_group_command(group, "brightness", brightness)

    def handle_group_toggle(self, query: str, body: dict) -> None:
        group = self.resolve_group_alias(query, body)
        if not group:
            raise ValueError("group is required")
        config = control.load_local_config(self.server.control_args.config)
        members = control.get_group_members(config, group)
        results = []
        overall_ok = True
        for alias in members:
            try:
                current_power = self.fetch_power_state(alias)
                next_command = "off" if current_power == "1" else "on"
                result = self.execute_for_target(alias, next_command, None)
                result["command"] = next_command
            except Exception as exc:
                results.append({"device": alias, "ok": False, "error": str(exc)})
                overall_ok = False
                continue
            overall_ok = overall_ok and result.get("ok", False)
            results.append(result)
        self.write_json(
            HTTPStatus.OK if overall_ok else HTTPStatus.BAD_GATEWAY,
            {
                "ok": overall_ok,
                "group": group,
                "cloud_backed": True,
                "results": results,
            },
        )

    def handle_group_preset(self, query: str, body: dict) -> None:
        group = self.resolve_group_alias(query, body)
        if not group:
            raise ValueError("group is required")
        preset_name = body.get("preset")
        if not isinstance(preset_name, str) or not preset_name:
            raise ValueError("preset is required")
        config = control.load_local_config(self.server.control_args.config)
        members = control.get_group_members(config, group)
        results = []
        overall_ok = True
        for alias in members:
            brightness = self.get_preset_brightness_for_device(preset_name, alias)
            args = make_control_args(self.server.control_args, "brightness", brightness)
            args.device = alias
            try:
                status_code, response_text, payload = control.perform_command(args)
                response_json = json.loads(response_text)
            except json.JSONDecodeError:
                response_json = {"raw_response": response_text}
                status_code = 502
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
                    "preset": preset_name,
                    "value": brightness,
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
                "preset": preset_name,
                "cloud_backed": True,
                "results": results,
            },
        )

    def handle_group_state_apply(self, query: str, body: dict) -> None:
        group = self.resolve_group_alias(query, body)
        if not group:
            raise ValueError("group is required")
        config = control.load_local_config(self.server.control_args.config)
        members = control.get_group_members(config, group)
        properties = self.build_state_apply_properties(body)
        results = []
        overall_ok = True
        for alias in members:
            assignments = [{"pid": item["pid"], "pvalue": item["pvalue"]} for item in properties]
            try:
                result = self.execute_properties_for_target(alias, assignments)
            except Exception as exc:
                results.append({"device": alias, "ok": False, "error": str(exc)})
                overall_ok = False
                continue
            overall_ok = overall_ok and result.get("ok", False)
            results.append(result)
        self.write_json(
            HTTPStatus.OK if overall_ok else HTTPStatus.BAD_GATEWAY,
            {
                "ok": overall_ok,
                "group": group,
                "properties": properties,
                "cloud_backed": True,
                "results": results,
            },
        )

    def handle_scene_post(self, path: str, body: dict) -> None:
        scene = body.get("scene")
        if path == "/scene/evening":
            scene = "evening"
        if path == "/scene/off":
            scene = "off"
        if not isinstance(scene, str) or not scene:
            raise ValueError("scene is required")
        self.handle_scene(scene)

    def handle_state_query_post(self, device: str | None, body: dict) -> None:
        pid_values = body.get("pid", [])
        if pid_values is None:
            pid_values = []
        if not isinstance(pid_values, list):
            raise ValueError("pid must be a list of property IDs")
        target_pid_list = []
        for item in pid_values:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("pid entries must be non-empty strings")
            target_pid_list.append(item.strip())
        include_raw = bool(body.get("raw"))
        self.handle_state_query(device, target_pid_list, include_raw=include_raw)

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

    def get_preset_brightness_for_device(self, preset_name: str, device: str | None) -> int:
        config = control.load_local_config(self.server.control_args.config)
        effective_device = device or self.server.control_args.device
        presets = control.get_device_presets(config, effective_device)
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

    def handle_state_query(self, device: str | None, target_pid_list: list[str], include_raw: bool = False) -> None:
        args = make_control_args(self.server.control_args, "state")
        args.device = device or args.device
        args.pid = target_pid_list
        try:
            status_code, response_text, payload = control.perform_state_query(args)
            response_json = json.loads(response_text)
        except json.JSONDecodeError:
            response_json = {"raw_response": response_text}
        except Exception as exc:
            self.write_json(HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(exc)})
            return

        response_payload = {
            "ok": 200 <= status_code < 300,
            "device": args.device,
            "target_pid_list": target_pid_list or control.DEFAULT_TARGET_PID_LIST,
            "cloud_backed": True,
            "request": control.redact_payload(payload),
            "wyze_status": status_code,
            "wyze_response": response_json,
        }
        if include_raw:
            response_payload["raw_response"] = response_text
        self.write_json(
            HTTPStatus.OK if 200 <= status_code < 300 else HTTPStatus.BAD_GATEWAY,
            response_payload,
        )

    def handle_properties(self, device: str | None, properties: list[dict]) -> None:
        assignments: list[str] = []
        for item in properties:
            if not isinstance(item, dict):
                raise ValueError("each property entry must be an object")
            pid = item.get("pid")
            pvalue = item.get("pvalue")
            if not isinstance(pid, str) or not pid:
                raise ValueError("each property entry must include string pid")
            if pvalue is None:
                raise ValueError("each property entry must include pvalue")
            assignments.append(f"{pid}={pvalue}")

        args = make_control_args(self.server.control_args, "properties")
        args.device = device or args.device
        args.properties = assignments
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
                "command": "properties",
                "device": args.device,
                "properties": properties,
                "cloud_backed": True,
                "request": control.redact_payload(payload),
                "wyze_status": status_code,
                "wyze_response": response_json,
            },
        )

    def handle_state_apply(self, device: str | None, body: dict) -> None:
        self.handle_properties(device, self.build_state_apply_properties(body))

    def build_state_apply_properties(self, body: dict) -> list[dict[str, str]]:
        properties: list[dict[str, str]] = []
        power = body.get("power")
        brightness = body.get("brightness")
        color_temperature = body.get("color_temperature")
        if power is not None:
            if power not in ("on", "off", 1, 0, True, False):
                raise ValueError("power must be 'on' or 'off'")
            properties.append({"pid": "P3", "pvalue": "1" if power in ("on", 1, True) else "0"})
        if brightness is not None:
            if not isinstance(brightness, int) or not 1 <= brightness <= 100:
                raise ValueError("brightness must be an integer between 1 and 100")
            properties.append({"pid": "P3", "pvalue": "1"})
            properties.append({"pid": "P1501", "pvalue": str(brightness)})
        if color_temperature is not None:
            if (
                not isinstance(color_temperature, int)
                or not control.DEFAULT_COLOR_TEMPERATURE_MIN <= color_temperature <= control.DEFAULT_COLOR_TEMPERATURE_MAX
            ):
                raise ValueError(
                    f"color_temperature must be an integer between {control.DEFAULT_COLOR_TEMPERATURE_MIN} and {control.DEFAULT_COLOR_TEMPERATURE_MAX}"
                )
            properties.append({"pid": "P3", "pvalue": "1"})
            properties.append({"pid": "P1502", "pvalue": str(color_temperature)})
        if not properties:
            raise ValueError("state/apply requires at least one of power, brightness, or color_temperature")

        deduped: list[dict[str, str]] = []
        seen: dict[str, int] = {}
        for item in properties:
            pid = item["pid"]
            if pid in seen:
                deduped[seen[pid]] = item
            else:
                seen[pid] = len(deduped)
                deduped.append(item)
        return deduped

    def handle_toggle(self, device: str | None) -> None:
        try:
            current_power = self.fetch_power_state(device or self.server.control_args.device)
        except Exception as exc:
            self.write_json(HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(exc)})
            return
        next_command = "off" if current_power == "1" else "on"
        self.handle_command(next_command, None, device)

    def fetch_power_state(self, device: str | None) -> str | None:
        args = make_control_args(self.server.control_args, "state")
        args.device = device or args.device
        args.pid = ["P3"]
        status_code, response_text, _ = control.perform_state_query(args)
        try:
            response_json = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise ValueError("unable to parse current state") from exc
        if not 200 <= status_code < 300:
            raise ValueError("failed to read current power state")
        return self.extract_power_state(response_json)

    def extract_power_state(self, response_json: dict) -> str | None:
        data = response_json.get("data")
        if not isinstance(data, dict):
            return None
        property_list = data.get("property_list")
        if not isinstance(property_list, list):
            return None
        for item in property_list:
            if isinstance(item, dict) and item.get("pid") == "P3":
                pvalue = item.get("pvalue")
                if isinstance(pvalue, str):
                    return pvalue
        return None

    def handle_transition(self, device: str | None, body: dict) -> None:
        transition_type = None
        transition_body = None
        for key in ("brightness", "color_temperature"):
            value = body.get(key)
            if isinstance(value, dict):
                if transition_type is not None:
                    raise ValueError("transition supports only one of brightness or color_temperature")
                transition_type = key
                transition_body = value
        if transition_type is None or transition_body is None:
            raise ValueError("transition requires either brightness or color_temperature object")

        start_value = transition_body.get("from")
        end_value = transition_body.get("to")
        duration_ms = body.get("duration_ms", 2000)
        steps = body.get("steps", 5)
        if not isinstance(start_value, int) or not isinstance(end_value, int):
            raise ValueError("transition from/to values must be integers")
        if not isinstance(duration_ms, int) or duration_ms < 0:
            raise ValueError("duration_ms must be a non-negative integer")
        if not isinstance(steps, int) or steps < 1:
            raise ValueError("steps must be an integer >= 1")

        if transition_type == "brightness":
            if not 1 <= start_value <= 100 or not 1 <= end_value <= 100:
                raise ValueError("brightness transition values must be between 1 and 100")
            command = "brightness"
        else:
            if not control.DEFAULT_COLOR_TEMPERATURE_MIN <= start_value <= control.DEFAULT_COLOR_TEMPERATURE_MAX:
                raise ValueError(
                    f"color_temperature transition values must be between {control.DEFAULT_COLOR_TEMPERATURE_MIN} and {control.DEFAULT_COLOR_TEMPERATURE_MAX}"
                )
            if not control.DEFAULT_COLOR_TEMPERATURE_MIN <= end_value <= control.DEFAULT_COLOR_TEMPERATURE_MAX:
                raise ValueError(
                    f"color_temperature transition values must be between {control.DEFAULT_COLOR_TEMPERATURE_MIN} and {control.DEFAULT_COLOR_TEMPERATURE_MAX}"
                )
            command = "color-temperature"

        sleep_seconds = duration_ms / 1000 / steps if steps else 0
        results = []
        overall_ok = True
        for index in range(steps + 1):
            fraction = index / steps if steps else 1
            value = round(start_value + (end_value - start_value) * fraction)
            args = make_control_args(self.server.control_args, command, value)
            args.device = device or args.device
            try:
                status_code, response_text, payload = control.perform_command(args)
                response_json = json.loads(response_text)
            except json.JSONDecodeError:
                response_json = {"raw_response": response_text}
                status_code = 502
            except Exception as exc:
                results.append({"step": index, "value": value, "ok": False, "error": str(exc)})
                overall_ok = False
                continue
            item_ok = 200 <= status_code < 300 and response_json.get("msg") == "SUCCESS"
            overall_ok = overall_ok and item_ok
            results.append(
                {
                    "step": index,
                    "value": value,
                    "ok": item_ok,
                    "wyze_status": status_code,
                    "request": control.redact_payload(payload),
                    "wyze_response": response_json,
                }
            )
            if sleep_seconds > 0 and index < steps:
                time.sleep(sleep_seconds)

        self.write_json(
            HTTPStatus.OK if overall_ok else HTTPStatus.BAD_GATEWAY,
            {
                "ok": overall_ok,
                "device": device or self.server.control_args.device,
                "transition": transition_type,
                "from": start_value,
                "to": end_value,
                "duration_ms": duration_ms,
                "steps": steps,
                "cloud_backed": True,
                "results": results,
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

    def execute_properties_for_target(self, target: str, properties: list[dict]) -> dict:
        config = control.load_local_config(self.server.control_args.config)
        devices = config.get("devices", {})
        groups = config.get("groups", {})

        if isinstance(devices, dict) and target in devices:
            assignments = []
            for item in properties:
                if not isinstance(item, dict):
                    raise ValueError("each property entry must be an object")
                pid = item.get("pid")
                pvalue = item.get("pvalue")
                if not isinstance(pid, str) or not pid or pvalue is None:
                    raise ValueError("each property entry must include pid and pvalue")
                assignments.append(f"{pid}={pvalue}")
            args = make_control_args(self.server.control_args, "properties")
            args.device = target
            args.properties = assignments
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
                result = self.execute_properties_for_target(alias, properties)
                overall_ok = overall_ok and result.get("ok", False)
                results.append(result)
            return {"target_type": "group", "target": target, "ok": overall_ok, "results": results}

        raise ValueError(f"target '{target}' is not a configured device or group")

    def handle_scene(self, scene: str) -> None:
        config = control.load_local_config(self.server.control_args.config)
        scene_config = control.get_scene_config(config, scene)
        if not scene_config:
            raise ValueError(f"scene '{scene}' is not configured")
        control.validate_scene_definition(scene, scene_config)

        target = scene_config.get("target")
        commands = scene_config.get("commands")
        results = []
        overall_ok = True
        for item in commands:
            command = item.get("command")
            value = item.get("value")
            if command == "properties":
                result = self.execute_properties_for_target(target, item.get("properties"))
            else:
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

    def handle_scene_validate(self, scene_config: dict) -> None:
        control.validate_scene_definition("request", scene_config)
        self.write_json(HTTPStatus.OK, {"ok": True, "valid": True, "scene": scene_config})

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
