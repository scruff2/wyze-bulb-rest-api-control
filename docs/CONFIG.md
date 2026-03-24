# Configuration Guide

This guide explains how to populate `local_config.json` for `wyze-bulb-rest-api-control`.

If you are testing the API from Windows:

- use `Invoke-RestMethod` in PowerShell when possible
- if you use `curl` from `cmd.exe`, JSON bodies must use escaped double quotes, not single quotes

## Start From The Example

Create your local file:

```powershell
Copy-Item .\local_config.example.json .\local_config.json
```

`local_config.json` is ignored by git and should stay local.

## Required Practical Values

For a working setup you usually need:

- `devices.<alias>.device_mac`
- `devices.<alias>.device_model`
- `access_token`
- `phone_id`

Everything else is either already defaulted or is your own local convenience structure.

## Finding `device_mac`

This is the bulb MAC address without separators.

Examples:

- `AABBCCDDEEFF`
- not `AA-BB-CC-DD-EE-FF`

Ways to find it:

1. Router or AP client list
2. Windows ARP / neighbor table
3. Existing Wyze request logs, if you already captured them

Windows examples:

```powershell
Get-NetNeighbor | Where-Object { $_.IPAddress -like '10.*' }
arp -a
```

If your bulb IP is known, match that IP to the corresponding MAC entry.

## Finding `device_model`

For the original white Wyze Bulb used in this project, use:

- `WLPA19`

If you have a different Wyze light model, the correct model string may differ.

Ways to find it:

1. instrumented Wyze app request logs
2. device metadata from the app or backend responses
3. reverse-engineering notes for your specific model

## Finding `access_token`

This comes from an authenticated Wyze mobile app session.

In this project, it was recovered by:

1. extracting the Wyze Android APK
2. patching it to log final outbound request bodies
3. triggering a real light-control action
4. copying `access_token` from the logged JSON body

If you already have a compatible hook log, you do not necessarily need to paste the token into config.

The tools can fall back to a hook log when provided explicitly.

## Finding `phone_id`

`phone_id` comes from the same logged request body as `access_token`.

If you already captured a Wyze hook log, look for a JSON body containing:

- `access_token`
- `phone_id`
- `device_mac`
- `device_model`

## Optional Local Structures

These are not secret Wyze values. They are your own local naming layer.

### `devices`

Maps a human-friendly alias to a bulb:

```json
{
  "devices": {
    "living-room": {
      "device_mac": "AABBCCDDEEFF",
      "device_model": "WLPA19"
    }
  }
}
```

### `groups`

Maps a group name to one or more aliases:

```json
{
  "groups": {
    "all": {
      "devices": ["living-room", "desk-lamp"]
    }
  }
}
```

### `presets`

Defines shared brightness shortcuts:

```json
{
  "presets": {
    "night": 5,
    "dim": 15,
    "bright": 85
  }
}
```

### Per-device `presets`

Override presets for a specific alias:

```json
{
  "devices": {
    "living-room": {
      "device_mac": "AABBCCDDEEFF",
      "device_model": "WLPA19",
      "presets": {
        "night": 3,
        "dim": 12,
        "bright": 90
      }
    }
  }
}
```

### `scenes`

Bundle one or more commands against a device or group:

```json
{
  "scenes": {
    "evening": {
      "target": "all",
      "commands": [
        { "command": "brightness", "value": 25 }
      ]
    },
    "off": {
      "target": "all",
      "commands": [
        { "command": "off" }
      ]
    }
  }
}
```

## Minimal Example

```json
{
  "default_device_alias": "living-room",
  "devices": {
    "living-room": {
      "device_mac": "AABBCCDDEEFF",
      "device_model": "WLPA19"
    }
  },
  "access_token": "replace-with-your-live-token",
  "phone_id": "replace-with-your-phone-id"
}
```

## Security Notes

Treat these as sensitive:

- `device_mac`
- `access_token`
- `phone_id`
- raw hook logs

Do not commit `local_config.json` or raw request logs to a public repository.
