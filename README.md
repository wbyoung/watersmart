# WaterSmart for Home Assistant

[![HACS](https://img.shields.io/badge/default-grey?logo=homeassistantcommunitystore&logoColor=white)][hacs-repo]
[![HACS installs](https://img.shields.io/github/downloads/wbyoung/watersmart/latest/total?label=installs&color=blue)][hacs-repo]
[![Version](https://img.shields.io/github/v/release/wbyoung/watersmart)][releases]
![Downloads](https://img.shields.io/github/downloads/wbyoung/watersmart/total)
![Build](https://img.shields.io/github/actions/workflow/status/wbyoung/watersmart/pytest.yml
)

This integration pulls data from water utilities that use [WaterSmart by VertexOne][vertexone].
It scrapes data from the web interface and provides a few [sensors](#sensors) with that data.

_Note: data will not be updated frequenly because the water utilities do not always update
this data continuously._

## Features

- **Automatic Multi-Meter Detection**: Automatically detects and creates separate devices for each water meter on your account (e.g., residential and irrigation meters)
- **Individual Meter Tracking**: Each meter gets its own set of sensors for independent monitoring
- **Backward Compatible**: Works seamlessly with single-meter accounts
- **Universal HTML Support**: Compatible with all WaterSmart portal variations

## Installation

### HACS

Installation through [HACS][hacs] is the preferred installation method.

[![Open the WaterSmart integration in HACS][hacs-badge]][hacs-open]

1. Click the button above or go to HACS &rarr; Integrations &rarr; search for
   "WaterSmart" &rarr; select it.
1. Press _DOWNLOAD_.
1. Select the version (it will auto select the latest) &rarr; press _DOWNLOAD_.
1. Restart Home Assistant then continue to [the setup section](#setup).

### Manual Download

1. Go to the [release page][releases] and download the `watersmart.zip` attached
   to the latest release.
1. Unpack the zip file and move `custom_components/watersmart` to the following
   directory of your Home Assistant configuration: `/config/custom_components/`.
1. Restart Home Assistant then continue to [the setup section](#setup).

## Setup

Open your Home Assistant instance and start setting up by following these steps:

1. Navigate to "Settings" &rarr; "Devices & Services"
1. Click "+ Add Integration"
1. Search for and select &rarr; "WaterSmart"

Or you can use the My Home Assistant Button below.

[![Add Integration](https://my.home-assistant.io/badges/config_flow_start.svg)][config-flow-start]

Follow the instructions to configure the integration.

### Configuration Settings

* _Host_: The subdomain used to access your water utility information. For instance
  `bendoregon`  for `https://bendoregon.watersmart.com/`.
* _Username_: Your email address used to log in.
* _Password_: Your password used to log in.

## Sensors

The integration creates the following sensors **for each meter** on your account:

### `sensor.watersmart_<host>_<username>_<meter_id>_gallons_for_most_recent_full_day`

Gallons of water used on the most recent full day of data available.

#### Attributes

* `related`: List of related objects with `start` and `gallons` covering the day of data.


### `sensor.watersmart_<host>_<username>_<meter_id>_gallons_for_most_recent_hour`

Gallons of water used on the most recent hour of data available.

#### Attributes

* `start`: The start of the hour of water usage
* `related`: List of related objects with `start` and `gallons` starting from the most recent
  hour.

### Multi-Meter Example

If you have two meters (e.g., "4531 Rheims Place, SFR" and "4531 Rheims Place, Irrigation-Only"), you'll see:

**Device 1: WaterSmart (4531 Rheims Place, SFR)**
- `sensor.watersmart_hptx_user_email_com_7176_11498_gallons_for_most_recent_hour`
- `sensor.watersmart_hptx_user_email_com_7176_11498_gallons_for_most_recent_full_day`

**Device 2: WaterSmart (4531 Rheims Place, Irrigation-Only)**
- `sensor.watersmart_hptx_user_email_com_13089_11499_gallons_for_most_recent_hour`
- `sensor.watersmart_hptx_user_email_com_13089_11499_gallons_for_most_recent_full_day`

Each meter is tracked independently with its own device and sensors.

## Services

### `watersmart.get_hourly_history`

Fetches hourly water usage. The `config_entry` value be found using the _Services_ tab in the _Developer Tools_, selecting the desired entity and then switching to YAML.

#### Service Data Attributes

* `config_entry`: **required** Config entry to use. Example: `1b4a46c6cba0677bbfb5a8c53e8618b0`.
* `meter_id`: Specific meter ID to query (e.g., `7176_11498`). If not specified, returns data from the first available meter. This is useful when you have multiple meters.
* `cached`: Accept data from the integration cache instead of re-fetching. Defaults to `false`.
* `start`: Start time to history. Example: `2024-06-19T19:30:00-07:00`.
* `end`: End time to history. Example: `2024-06-19T21:30:00-07:00`.

#### Multi-Meter Service Example

To get history for a specific meter when you have multiple:

```yaml
service: watersmart.get_hourly_history
data:
  config_entry: 1b4a46c6cba0677bbfb5a8c53e8618b0
  meter_id: "7176_11498"  # Irrigation meter
  start: "2024-06-19T00:00:00-07:00"
  end: "2024-06-19T23:59:59-07:00"
```


## Credits

Icon designed by [bsd studio][bsd-attribution].

[bsd-attribution]: https://thenounproject.com/creator/nesterenko.ruslan
[config-flow-start]: https://my.home-assistant.io/redirect/config_flow_start/?domain=watersmart
[hacs]: https://hacs.xyz/
[hacs-repo]: https://github.com/hacs/integration
[hacs-badge]: https://my.home-assistant.io/badges/hacs_repository.svg
[hacs-open]: https://my.home-assistant.io/redirect/hacs_repository/?owner=wbyoung&repository=watersmart&category=integration
[releases]: https://github.com/wbyoung/watersmart/releases
[vertexone]: https://www.vertexone.net/
