# ESPHome Files

This folder contains ESPHome display configurations for ESP Host Bridge.

## Included Files

- `host-key.yaml`  
  Reference firmware for the Waveshare ESP32-S3 Touch AMOLED 1.64 display module.

- `host-key-sq.yaml`  
  Scaled-down square-layout variant of `host-key.yaml`. It uses a left-aligned `302x280` active UI area on the `456x280` display, with the unused right-side area masked out. It is intended for a compact square-style layout, but it may still have some page-specific alignment issues depending on the screen and content being shown.

## Navigation Gestures

The gesture behavior in `host-key.yaml` is page-specific.

### HOME

- Tap the four main icons to open:
  - `Docker`
  - `Network`
  - `VMs`
  - `Settings`
- Long-press the center button to open the screensaver.
- `HOME` does not use swipe navigation.

### Docker and VMs

- Swipe down to return to `HOME`.
- Long-press the page header to return to `HOME`.
- Long-press a row to open its detail overlay.

`Docker` and `VMs` use `swipe down` for the home gesture because both pages are built around vertically scrollable lists. Using `swipe up` there would conflict more easily with normal list scrolling.

### Settings

- `Settings 1`
  - Swipe up to return to `HOME`.
  - Swipe left or right to open `Settings 2`.
- `Settings 2`
  - Swipe up to return to `HOME`.
  - Swipe left or right to open `Settings 1`.
- Long-press the header on either settings page to return to `HOME`.

### Info Pages

The info pages are arranged in a loop:

`Network -> System -> CPU Temp -> Disk Temp -> Disk Usage -> GPU -> Uptime -> Host Name -> Network`

On these pages:

- Swipe up to return to `HOME`.
- Swipe left to move to the next info page.
- Swipe right to move to the previous info page.
- Long-press the page header to return to `HOME`.

### Screensaver and Sleep

- The screensaver can be opened manually by long-pressing the center button on `HOME`.
- It can also start automatically after the configured idle timeout.
- Tap the screensaver to restore the last active page.
- If the display has gone to sleep, double-tap to wake it and restore the last active page.

### Boot Screen

- A boot screen is shown during startup.
- Long-press the boot screen to hide it immediately.
- It will also hide automatically once host serial traffic is detected.

### Host Offline Screen

- If host serial data stops for several seconds, a host offline screen is shown.
- A normal tap dismisses it when the offline state is being treated as temporary.
- A long-press also dismisses it.
- This screen is meant to cover temporary host shutdown or restart periods without dropping straight back to the normal UI.

### Notes

- The first touch also dismisses the swipe-hint labels shown on several pages.
- Some controls, such as sliders and list interactions, temporarily take priority over page gestures while they are active.

## Flashing

Validate a YAML before flashing:

```bash
esphome config Esphome/host-key.yaml
```

Flash over OTA:

```bash
esphome run Esphome/host-key.yaml --device <device-ip>
```

These YAMLs depend on the local font files in `Esphome/fonts/`. Do not move or copy the YAMLs without the `fonts` folder.

Replace the YAML path with `Esphome/host-key-sq.yaml` if you want the square-layout variant.

### USB Flashing Note

These YAMLs use the `usb_cdc_acm` component for normal runtime communication. Because of that, direct USB flashing is not always available in the normal running state.

If OTA is not available, you may need to put the ESP32-S3 into boot mode first, then flash over USB from the bootloader port.

## secrets.yaml

These YAMLs expect a local `secrets.yaml` file with your real values.

Example:

```yaml
wifi_ssid: "YOUR_WIFI_NAME"
wifi_password: "YOUR_WIFI_PASSWORD"
esp_host_bridge_api_key: "YOUR_API_KEY"
```

The `secrets.yaml` file should live in the same ESPHome working directory you use when running `esphome`.

Do not leave placeholder values in `secrets.yaml`, or Wi-Fi and API connections will fail after flashing.
