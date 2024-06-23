# WaterSmart for Home Assistant

[![HACS](https://img.shields.io/badge/hacs-default-orange)][hacs-repo]
[![Version](https://img.shields.io/github/v/release/wbyoung/watersmart)][releases]
![Downloads](https://img.shields.io/github/downloads/wbyoung/watersmart/total)
![Build](https://img.shields.io/github/actions/workflow/status/wbyoung/watersmart/pytest.yml
)

This integration pulls data from water utilities that use [WaterSmart by VertexOne][vertexone].
It scrapes data from the web interface and provides a few [sensors](#sensors) with that data.

_Note: data will not be updated frequenly because the water utilities do not always update
this data continuously._

## Installation

### HACS

Installation through [HACS][hacs] is the preferred installation method.

1. Go to HACS
1. Click on Integrations
1. Search for "WaterSmart" and click "Download this Repository with HACS"
1. Select the version (it will auto select the latest)
1. Restart Home Assistant then continue to [the setup section](#setup)

### Manual Download

1. Go to the [release page][releases] and download the `watersmart.zip` attached to the latest
   release.
1. Unpack the file and move the folder it contains called `watersmart` to the following
   directory of your Home Assistant configuration: `/config/custom_components/`.
1. Restart Home Assistant then continue to [the setup section](#setup).

## Setup

Open your Home Assistant instance and start setting up by following these steps:

1. Navigate to "Settings" &rarr; "Devices & Services"
1. Click "+ Add Integration"
1. Search for and select &rarr; "UI Lovelace Minimalist"

Or you can use the My Home Assistant Button below.

[![Add Integration](https://my.home-assistant.io/badges/config_flow_start.svg)][config-flow-start]

Follow the instructions to configure the integration.

### Configuration Settings

* _Host_: The subdomain used to access your water utility information. For instance
  `bendoregon`  for `https://bendoregon.watersmart.com/`.
* _Username_: Your email address used to log in.
* _Password_: Your password used to log in.

## Sensors

### `sensor.watersmart_<host>_most_recent_full_day_usage`

Gallons of water used on the most recent full day of data available.

#### Attributes

* `related`: List of related objects with `start` and `gallons` covering the day of data.


### `sensor.watersmart_<host>_most_recent_hour_usage`

Gallons of water used on the most recent hour of data available.

#### Attributes

* `start`: The start of the hour of water usage
* `related`: List of related objects with `start` and `gallons` starting from the most recent
  hour.

## Credits

Icon designed by [bsd studio][bsd-attribution].

[bsd-attribution]: https://thenounproject.com/creator/nesterenko.ruslan
[config-flow-start]: https://my.home-assistant.io/redirect/config_flow_start/?domain=watersmart
[hacs]: https://hacs.xyz/
[hacs-repo]: https://github.com/hacs/integration
[releases]: https://github.com/wbyoung/watersmart/releases
[vertexone]: https://www.vertexone.net/
