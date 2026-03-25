# ESPHome Files

This folder contains ESPHome display configurations for ESP Host Bridge.

## Included Files

- `host-key.yaml`  
  Reference firmware for the Waveshare ESP32-S3 Touch AMOLED 1.64 display module.

- `Host-key-sq.yaml`  
  Scaled-down square-layout variant of `host-key.yaml`. It uses a left-aligned `302x280` active UI area on the `456x280` display, with the unused right-side area masked out. It is intended for a compact square-style layout, but it may still have some page-specific alignment issues depending on the screen and content being shown.

## Flashing

Validate a YAML before flashing:

```bash
esphome config Esphome/host-key.yaml
```

Flash over OTA:

```bash
esphome run Esphome/host-key.yaml --device <device-ip>
```

Replace the YAML path with `Esphome/Host-key-sq.yaml` if you want the square-layout variant.

### USB Flashing Note

These YAMLs use the `usb_cdc_acm` component for normal runtime communication. Because of that, direct USB flashing is not always available in the normal running state.

If OTA is not available, you may need to put the ESP32-S3 into boot mode first, then flash over USB from the bootloader port.

## secrets.yaml

These YAMLs expect a local `secrets.yaml` file with your real values.

Example:

```yaml
wifi_ssid: "YOUR_WIFI_NAME"
wifi_password: "YOUR_WIFI_PASSWORD"
esp_host_bridge_api_key: "YOUR_BASE64_API_KEY"
```

The `secrets.yaml` file should live in the same ESPHome working directory you use when running `esphome`.

Do not leave placeholder values in `secrets.yaml`, or Wi-Fi and API connections will fail after flashing.
