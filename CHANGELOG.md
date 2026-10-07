# Changelog

## v0.1.0-beta1 — First public beta

First HACS-testable beta of the unofficial community Hoben integration.

### Included

- UI configuration with private HOBEN identifier handling.
- MyHOBEN association flow using the reviewed `DeviceAuthReq → DeviceAuthRes → OpenedClient` client path.
- Persisted DeviceGuid lifecycle and reauthentication support.
- Read-only V4 polling through the shared coordinator.
- V4 sensors/binary sensors for the currently established read-only state.
- English and French translations.
- Privacy-safe Home Assistant diagnostics built from an explicit allowlist.
- Deterministic protocol and Home Assistant test suites, HACS validation and Hassfest.
- MANAGER-gated authenticated read-only live validation for runtime changes.

### Known limitations

- Beta quality: this release is intended for early community testing, not a stable deployment guarantee.
- Real-device validation is centered on the reference Hoben Osmose using protocol profile V4.
- V6/V6v16 and other Hoben models are not yet guaranteed.
- No stove-control write command is exposed: no start/stop, target-temperature change or ventilation control.
- Warning/fault mappings, PVI meaning, DataUpdated details and other unresolved protocol fields remain intentionally incomplete where `protocol.md` does not establish them.
- The project is unofficial and is not affiliated with Hoben, Inovalp, Home Assistant or HACS.
