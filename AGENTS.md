# AGENTS.md — ha-hoben-community

## Mission

This repository contains a **community-maintained, unofficial Home Assistant integration for Hoben pellet stoves** using the MyHOBEN communication protocol.

The project must never present itself as an official Hoben, Inovalp, Home Assistant, or HACS product. It is intended to be understandable, testable, safe, maintainable, and useful to the Home Assistant community.

The primary target device during early development is a **Hoben Osmose**, while the protocol layer must remain designed to support other Hoben stove profiles discovered in MyHOBEN (V4, V6, V6v16 and future variants where possible).

---

## Non-negotiable engineering principles

1. **Safety first.** A pellet stove is a heating appliance. Never implement any behavior that bypasses the Hoben controller's own safety logic, cuts mains power, writes installer/factory combustion parameters, or exposes technical test registers to normal Home Assistant users.
2. **Read-only first.** New protocol support must be proven in read-only mode before write commands are enabled.
3. **Protocol correctness over feature speed.** If a register meaning, scale, state, timing unit, or command behavior is uncertain, mark it as unknown and add a test or diagnostic path. Do not guess silently.
4. **Home Assistant conventions first.** Prefer standard Home Assistant entities, config entries, coordinators, diagnostics, translations, device/entity metadata and async I/O patterns.
5. **HACS compatibility from the start.** Repository structure, manifest metadata, releases, documentation and GitHub Actions must remain compatible with current HACS requirements.
6. **Community readability.** The code must be easy for another Home Assistant developer to understand without having access to the original MyHOBEN APK.
7. **No secrets in source or logs.** Never commit or log full MyHOBEN User GUIDs, Device GUIDs, authorization codes, private test captures containing identifiers, credentials, or other user-specific secrets.
8. **No proprietary binaries.** Do not commit MyHOBEN APKs, reconstructed DLLs, AOT binaries or other proprietary application assets. Only commit independently written source code and protocol documentation required for interoperability.

---

## Repository and package architecture

Keep the Home Assistant integration under exactly one HACS integration directory:

```text
custom_components/hoben/
```

The repository should evolve toward this structure:

```text
ha-hoben-community/
├── custom_components/
│   └── hoben/
│       ├── __init__.py
│       ├── manifest.json
│       ├── config_flow.py
│       ├── const.py
│       ├── coordinator.py
│       ├── sensor.py
│       ├── binary_sensor.py
│       ├── select.py
│       ├── switch.py
│       ├── climate.py
│       ├── diagnostics.py
│       ├── strings.json
│       └── translations/
│           ├── en.json
│           └── fr.json
├── tests/
│   ├── fixtures/
│   ├── test_config_flow.py
│   ├── test_protocol.py
│   ├── test_profiles.py
│   ├── test_coordinator.py
│   └── test_entities.py
├── docs/
│   └── protocol.md
├── .github/
│   └── workflows/
├── AGENTS.md
├── project.md
├── hacs.json
├── README.md
├── LICENSE
└── pyproject.toml
```

### Preferred separation of protocol and Home Assistant code

The protocol implementation should be designed so it can ultimately live in an independent Python library, tentatively named **`pyhoben`**.

The desired long-term dependency direction is:

```text
MyHOBEN TLS protocol
        ↓
      pyhoben
        ↓
Home Assistant integration
```

The Home Assistant integration should not become the canonical location for low-level binary parsing if that parsing can be cleanly isolated. During early prototyping, protocol code may live inside the repository, but keep boundaries clean enough to extract it later without a rewrite.

Do not make Home Assistant entity code responsible for parsing TCP frames, Modbus MBAP headers, Hoben message types, or register maps.

---

## Home Assistant implementation rules

Follow the current Home Assistant developer documentation and integration quality rules.

At minimum:

- Configure the integration through the **UI using `config_flow.py`**.
- Store connection/authentication data in `ConfigEntry.data` and non-essential user options in `ConfigEntry.options`.
- Validate the connection during setup.
- Prevent duplicate setup of the same stove/account identifier.
- Provide reauthentication/reconfiguration flows when they become applicable.
- Use async networking; never block Home Assistant's event loop.
- Use a coordinator or equivalent shared update mechanism rather than making every entity poll independently.
- Create a Home Assistant device representing the stove and attach entities to it.
- Use proper entity classes, device classes, units, state classes and entity categories where applicable.
- Mark technical values as diagnostic entities when appropriate.
- Expose only user-meaningful modes and commands. Never expose factory/test/installer controls.
- Implement diagnostics that redact GUIDs, authorization codes and other sensitive identifiers.
- Provide English and French translations from the beginning.
- Keep entity unique IDs stable across upgrades.
- Handle unavailable/disconnected state cleanly and recover automatically when the server reconnects.

Before merging features, check the current official Home Assistant rules rather than relying on an old local copy of these instructions:

- https://developers.home-assistant.io/docs/creating_integration_manifest/
- https://developers.home-assistant.io/docs/core/integration/config_flow/
- https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/

---

## HACS rules

The project is intended for public HACS distribution.

Continuously verify current HACS publishing requirements. At minimum, preserve these properties:

- public GitHub repository;
- one integration under `custom_components/hoben/`;
- all runtime integration files inside that integration directory;
- valid `custom_components/hoben/manifest.json`;
- root `hacs.json`;
- root README with installation and usage instructions;
- brand assets when required;
- GitHub releases for stable versions;
- HACS validation GitHub Action;
- Hassfest or equivalent Home Assistant validation.

Reference:

- https://www.hacs.xyz/docs/publish/start/
- https://www.hacs.xyz/docs/publish/integration/

Do not merge a release candidate while HACS validation or Home Assistant validation is failing.

---

# Testing strategy — highest priority

Testing is a core requirement of this project, not a later cleanup task.

Every protocol feature and every Home Assistant feature should be developed together with its tests. A feature without meaningful tests is incomplete.

The test strategy has **two primary targets**:

1. correctness and stability of the Hoben/MyHOBEN protocol implementation;
2. correctness and stability inside the Home Assistant runtime model.

## 1. Hoben protocol tests

### Default: deterministic simulation

The main automated test suite **must not depend on a real stove or the live Hoben server**. CI must be reproducible and safe.

Use deterministic fixtures and protocol simulations for:

- TLS client state-machine behavior where practical;
- `OpenClient` serialization;
- `OpenedClient` parsing;
- stove profile selection (V4/V6/V6v16);
- Ping/Pong;
- Hoben message framing;
- fragmented TCP/TLS reads;
- multiple frames received in one read;
- malformed/truncated frames;
- Modbus MBAP parsing;
- Modbus function 03/04 reads;
- function 06 writes;
- function 16 multi-register writes when implemented;
- function 22 mask-write when implemented;
- `DataResponseClient` parsing;
- `DataUpdated` parsing;
- signed temperature/register conversions;
- state/mode/ventilation enum decoding;
- reconnects, timeouts and server disconnects;
- unknown message types and unknown product profiles;
- Modbus exception responses;
- confirmation reads after a write command.

Create sanitized binary fixtures from observed traffic when needed. Fixtures must contain no real User GUID, Device GUID or authorization code.

### Real-stove validation

A real Hoben Osmose is extremely useful, but **real-stove tests must be opt-in/manual and never required by normal CI**.

Use the real stove for:

- validating the actual stove profile returned by `OpenedClient`;
- confirming temperature scale and units;
- confirming derogation timing units;
- validating `DataUpdated` metadata;
- validating that write commands produce the expected user-visible result;
- checking reconnection behavior against the real service;
- collecting sanitized reference fixtures.

Real-device testing must proceed in stages:

1. connection only;
2. read-only queries;
3. compare raw values with MyHOBEN display;
4. one safe write command at a time;
5. read-back confirmation;
6. only then expose the feature through Home Assistant.

Never run destructive, factory, combustion, motor-test or installer-register experiments on a real stove.

### Protocol regression tests

Once a real behavior has been confirmed, add a fixture-based regression test so it no longer depends on the real stove for future validation.

For every protocol bug fixed, add a regression test that fails before the fix and passes after it.

Aim for very high coverage of the protocol package, especially framing, parsing, register maps and command serialization.

---

## 2. Home Assistant environment tests

Use Home Assistant's recommended pytest fixtures and test patterns.

Required areas include:

- **100% config-flow branch coverage** where practical, including recovery from errors;
- successful initial setup;
- invalid GUID/input handling;
- authorization/pairing flow;
- duplicate-device prevention;
- connection failure and recovery;
- config-entry unload/reload;
- coordinator refresh behavior;
- entity creation and unique IDs;
- availability transitions;
- correct units/device classes/state classes;
- translation keys;
- diagnostics redaction;
- service/entity command forwarding;
- no unsupported write entities created when control is disabled;
- persistence/migration of config entries across versions;
- multiple supported stove profiles;
- behavior with unknown/unsupported profiles.

Tests must prove that Home Assistant remains responsive when the Hoben server is slow or unreachable.

No network operation should block the event loop.

### CI gates

Pull requests should eventually be required to pass:

- unit tests;
- Home Assistant integration tests;
- protocol tests;
- formatting;
- linting;
- type checking where adopted;
- Hassfest/Home Assistant validation;
- HACS validation.

Do not weaken or delete a failing test merely to make CI green. Fix the implementation or explicitly update the test because the documented behavior has changed.

---

## Code readability and documentation

This is a community project based on a non-public protocol. Therefore the source code must explain **why** it behaves as it does.

### Comments and docstrings

Use extensive but useful comments and docstrings, especially around:

- binary frame layouts;
- offsets;
- endianness;
- register addresses;
- enum mappings;
- signed/unsigned conversions;
- safety restrictions;
- reconnection logic;
- unusual Home Assistant lifecycle behavior;
- behavior discovered through reverse engineering;
- assumptions that still need real-device validation.

For protocol functions, include enough information that a contributor can understand the packet format without reopening the APK analysis.

Prefer comments such as:

```python
# MyHOBEN wraps a standard Modbus/TCP frame with one leading message-type byte.
# 0x0D means DataRequestClient. The Modbus MBAP header starts immediately after it.
packet = bytes([MessageType.DATA_REQUEST_CLIENT]) + modbus_frame
```

over comments that simply restate syntax.

Public classes, protocol parsers and non-obvious helpers should have docstrings.

### Naming

Prefer descriptive names matching both Home Assistant terminology and the protocol documentation.

Examples:

- `user_guid`, not `id1`;
- `device_guid`, not `token` unless it is proven to be a token;
- `transaction_id`;
- `register_address`;
- `operation_state`;
- `temperature_derogation_raw` when unit conversion is not yet proven.

Do not hide uncertainty by giving an unverified field an overly specific name.

### Small modules

Keep modules focused. Avoid large files that mix:

- transport;
- authentication;
- Modbus codec;
- register maps;
- Home Assistant entities.

Favor dataclasses/enums/constants for protocol structures and immutable register maps where appropriate.

---

## Protocol source of truth

`protocol.md` is the human-readable source of truth for the reverse-engineered protocol.

When protocol behavior changes:

1. update tests;
2. update the implementation;
3. update `protocol.md` in the same pull request;
4. clearly mark behavior as **confirmed**, **observed**, or **to validate**.

Do not silently convert a hypothesis into a confirmed fact.

---

## Write-command safety policy

Only explicitly whitelisted user-level registers may ever be writable through the integration.

For V6/V6v16, candidate user-facing writes currently include:

- 1280: normal controller ON/OFF request;
- 1283: derogation temperature;
- 1284: derogation start/timing;
- 1285: derogation duration;
- 1286: ventilation mode;
- 1792: operation mode;
- 1798: manual-mode temperature;
- 1799: manual-mode max power;
- 1801: selected user bits using mask-write.

Do **not** expose registers 1287-1293 (technical/motor/test) or the installer/factory area beginning around 2304.

Before enabling a writable feature:

- protocol bytes must be covered by tests;
- real-device behavior must be validated if practical;
- valid input range must be known;
- command rate must be limited;
- a read-back confirmation should be performed;
- error responses must be handled without retry loops.

---

## Logging and diagnostics

Debug logs are important for community troubleshooting, but must be safe to share publicly.

Never log full:

- User GUID;
- Device GUID;
- authorization/pairing code;
- credentials;
- unredacted raw frames containing these values.

Provide a helper for consistent redaction rather than relying on every log statement to redact manually.

Diagnostic exports should be designed so users can attach them to GitHub issues safely.

---

## Version and feature discipline

Follow the project roadmap in `project.md`.

Do not implement later-phase control features prematurely just because register addresses are known. Stable read-only behavior is more valuable than a larger unstable feature set.

Prefer small pull requests with tests and documentation over one very large change.

---

## Definition of done for a feature

A feature is complete only when:

- implementation follows async Home Assistant patterns;
- protocol behavior is documented if relevant;
- unit/regression tests exist;
- Home Assistant behavior is tested;
- sensitive information is redacted;
- user-facing text is translated at least in English and French where applicable;
- failure/disconnection paths are handled;
- HACS/Home Assistant validation still passes;
- code is documented well enough for an external contributor to maintain it.