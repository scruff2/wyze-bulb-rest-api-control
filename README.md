# wyze-bulb-rest-api-control

Local REST API and CLI wrapper for controlling an original Wyze Bulb from a computer.

What this project does:

- exposes a simple local HTTP API
- exposes a direct CLI
- lets scripts and automations control the bulb without using the Wyze mobile app UI

What this project does not do:

- it does not provide cloudless control
- it still depends on Wyze cloud service and a valid Wyze session

This project is best understood as a local automation bridge:

- your automations talk to a local REST API
- this tool translates those requests into Wyze cloud-backed bulb commands

## Current Capability

Validated bulb controls:

- on
- off
- brightness

Validated local REST endpoints:

- `GET /status`
- `GET /devices`
- `GET /groups`
- `GET /scenes`
- `POST /on`
- `POST /off`
- `POST /night`
- `POST /dim`
- `POST /bright`
- `POST /group/on`
- `POST /group/off`
- `POST /group/brightness`
- `POST /scene/run`
- `POST /scene/evening`
- `POST /scene/off`
- `POST /brightness`

Default local bind:

- `http://127.0.0.1:8787`

## Files

- `wyze_light_api.py`
  - local REST API server
- `wyze_light_control.py`
  - direct CLI client and shared control logic
- `local_config.example.json`
  - safe template for local untracked config
- `start_api.ps1`
  - start the API in the foreground
- `start_api_background.ps1`
  - start the API in the background
- `stop_api.ps1`
  - stop the background API process for this project
- `install_startup_task.ps1`
  - install a Windows scheduled task to start the API at logon
- `uninstall_startup_task.ps1`
  - remove the scheduled task
- `openapi.yaml`
  - minimal OpenAPI description of the local HTTP API

## Setup

### 1. Create your local config

```powershell
Copy-Item .\local_config.example.json .\local_config.json
```

Then edit `local_config.json` with your real values.

Recommended fields:

- `default_device_alias`
- `devices`
- `groups`
- `presets`
- `access_token`
- `phone_id`

The file `local_config.json` is ignored by git.

### How to find the required values

You need three categories of data:

1. device alias and model information
2. Wyze session information
3. optional groups / presets / scenes

#### `devices.<alias>.device_mac`

This is the bulb MAC without separators.

Ways to find it:

- from your router's DHCP or client list
- from a local ARP / neighbor table after the bulb is online
- from a previously captured Wyze hook log if you already instrumented the app

Windows examples:

```powershell
Get-NetNeighbor | Where-Object { $_.IPAddress -like '10.*' }
arp -a
```

Use the bulb's MAC in `AABBCCDDEEFF` form, not `AA-BB-CC-DD-EE-FF`.

#### `devices.<alias>.device_model`

For the original white Wyze Bulb used in this project, the model is:

- `WLPA19`

If you are using a different Wyze bulb model, you must discover the matching model string from your own app traffic or device metadata.

#### `access_token`

This comes from the authenticated Wyze mobile app session.

Most practical path used in this project:

1. extract the Wyze Android APK
2. patch it to log outbound request bodies
3. capture a control action
4. copy the `access_token` from the logged JSON body

Fallback for users who already have a captured hook log:

- place the log somewhere local and pass `--hook-log`
- the tool can extract `access_token` from `E WYZE_HOOK: BODY=...` lines automatically

If you paste `access_token` directly into `local_config.json`, treat that file as sensitive.

#### `phone_id`

This also comes from the logged Wyze request body.

It appears in the same JSON object as `access_token`.

Fallback behavior:

- if `phone_id` is not present in `local_config.json`
- and a compatible hook log is provided
- the tool can extract it automatically

#### `app_name`, `app_version`, `phone_system_type`, `sc`, `sv`

Defaults are already included in the example config and code for the validated original-bulb path.

You usually only need to change them if:

- Wyze changes the app/API behavior
- you are targeting a different product/app path

#### `groups`

This is just your own local naming layer.

Example:

```json
{
  "groups": {
    "all": {
      "devices": ["living-room", "desk-lamp"]
    }
  }
}
```

#### `presets`

These are your own local brightness shortcuts.

Example:

```json
{
  "presets": {
    "night": 5,
    "dim": 15,
    "bright": 85
  }
}
```

#### `scenes`

These are your own local command bundles.

Example:

```json
{
  "scenes": {
    "evening": {
      "target": "all",
      "commands": [
        { "command": "brightness", "value": 25 }
      ]
    }
  }
}
```

### 2. Start the local API

```powershell
python .\wyze_light_api.py
```

Foreground PowerShell helper:

```powershell
.\start_api.ps1
```

Background helper:

```powershell
.\start_api_background.ps1
```

Stop the background process:

```powershell
.\stop_api.ps1
```

### 3. Test the API

Health:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8787/status | Select-Object -ExpandProperty Content
```

`curl` health example:

```bash
curl http://127.0.0.1:8787/status
```

On:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8787/on
```

```bash
curl -X POST http://127.0.0.1:8787/on
```

Off:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8787/off
```

Preset brightness:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8787/night
Invoke-RestMethod -Method Post http://127.0.0.1:8787/dim
Invoke-RestMethod -Method Post http://127.0.0.1:8787/bright
```

Brightness:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8787/brightness -ContentType 'application/json' -Body '{"brightness":40}'
```

```bash
curl -X POST http://127.0.0.1:8787/brightness \
  -H "Content-Type: application/json" \
  -d '{"brightness":40}'
```

List configured aliases:

```powershell
Invoke-RestMethod -Method Get http://127.0.0.1:8787/devices
```

Target a specific alias:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8787/on -ContentType 'application/json' -Body '{"device":"living-room"}'
Invoke-RestMethod -Method Post http://127.0.0.1:8787/bright -ContentType 'application/json' -Body '{"device":"living-room"}'
Invoke-RestMethod -Method Post http://127.0.0.1:8787/brightness -ContentType 'application/json' -Body '{"device":"living-room","brightness":40}'
```

List configured groups:

```powershell
Invoke-RestMethod -Method Get http://127.0.0.1:8787/groups
```

List configured scenes:

```powershell
Invoke-RestMethod -Method Get http://127.0.0.1:8787/scenes
```

Run a group action:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8787/group/off -ContentType 'application/json' -Body '{"group":"all"}'
Invoke-RestMethod -Method Post http://127.0.0.1:8787/group/brightness -ContentType 'application/json' -Body '{"group":"all","brightness":25}'
```

Run a scene:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8787/scene/evening
Invoke-RestMethod -Method Post http://127.0.0.1:8787/scene/off
Invoke-RestMethod -Method Post http://127.0.0.1:8787/scene/run -ContentType 'application/json' -Body '{"scene":"evening"}'
```

## Start At Logon

If you want the API available after Windows sign-in:

```powershell
.\install_startup_task.ps1
```

Remove it later:

```powershell
.\uninstall_startup_task.ps1
```

This uses a Windows scheduled task and expects `local_config.json` to exist in the project folder.

## CLI Usage

On:

```powershell
python .\wyze_light_control.py on
```

Off:

```powershell
python .\wyze_light_control.py off
```

Brightness:

```powershell
python .\wyze_light_control.py brightness 40
```

Dry run:

```powershell
python .\wyze_light_control.py on --dry-run
```

Target a named alias from config:

```powershell
python .\wyze_light_control.py on --device living-room
python .\wyze_light_control.py brightness 40 --device living-room
```

## Configuration Resolution Order

The control code resolves values in this order:

1. CLI arguments
2. environment variables
3. `local_config.json`
4. captured hook log, for fallback values if available

## Aliases, Groups, And Presets

`local_config.json` can define:

- `devices`
  - named aliases like `living-room`
- `groups`
  - named collections like `all`
- `scenes`
  - named collections of commands applied to a configured device or group
- `presets`
  - shared defaults for `night`, `dim`, `bright`

Each device can also override presets locally:

```json
{
  "devices": {
    "living-room": {
      "device_mac": "A1B2C3D4E5F6",
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

Scenes look like this:

```json
{
  "scenes": {
    "evening": {
      "target": "all",
      "commands": [
        {
          "command": "brightness",
          "value": 25
        }
      ]
    },
    "off": {
      "target": "all",
      "commands": [
        {
          "command": "off"
        }
      ]
    }
  }
}
```

Supported environment variables:

- `WYZE_DEVICE_MAC`
- `WYZE_DEVICE_MODEL`
- `WYZE_ACCESS_TOKEN`
- `WYZE_PHONE_ID`
- `WYZE_APP_NAME`
- `WYZE_APP_VERSION`
- `WYZE_PHONE_SYSTEM_TYPE`
- `WYZE_SC`
- `WYZE_SV`

## Security Notes

Do not publish:

- real `device_mac`
- `access_token`
- `phone_id`
- raw hook logs containing live request bodies

Keep local-only values in:

- `local_config.json`

If you use a captured hook log for fallback, treat it as sensitive.

## API Description

For tooling and external integration, see:

- `openapi.yaml`

## Limitation

This project gives you a local control surface on your computer, but the backend command path is still Wyze cloud-backed.

So:

- local computer control: yes
- app-free control: yes
- cloudless outage-proof control: not yet
