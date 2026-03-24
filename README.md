# wyze-bulb-rest-api-control

Local REST API and CLI wrapper for controlling an original Wyze Bulb from a computer.

What this project does:

- exposes a simple local HTTP API
- exposes a direct CLI
- lets scripts and automations control the bulb without using the Wyze mobile app UI

What this project does not do:

- it does not provide cloudless control
- it still depends on Wyze cloud service and a valid Wyze session

## Current Capability

Validated bulb controls:

- on
- off
- brightness

Validated local REST endpoints:

- `GET /status`
- `GET /devices`
- `GET /groups`
- `POST /on`
- `POST /off`
- `POST /night`
- `POST /dim`
- `POST /bright`
- `POST /group/on`
- `POST /group/off`
- `POST /group/brightness`
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

On:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8787/on
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

Run a group action:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8787/group/off -ContentType 'application/json' -Body '{"group":"all"}'
Invoke-RestMethod -Method Post http://127.0.0.1:8787/group/brightness -ContentType 'application/json' -Body '{"group":"all","brightness":25}'
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

## Limitation

This project gives you a local control surface on your computer, but the backend command path is still Wyze cloud-backed.

So:

- local computer control: yes
- app-free control: yes
- cloudless outage-proof control: not yet
