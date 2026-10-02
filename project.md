# Project plan — ha-hoben-community

## Project identity

**Repository name:** `ha-hoben-community`  
**Home Assistant domain:** `hoben`  
**Displayed integration name:** `Hoben`  
**Distribution target:** HACS custom integration  
**Status:** unofficial community project

Suggested public description:

> Unofficial community Home Assistant integration for Hoben pellet stoves using the MyHOBEN communication protocol.

The README should contain a visible disclaimer:

> This project is an unofficial community integration. It is not affiliated with, endorsed by, or maintained by Hoben, Inovalp, Home Assistant, or HACS.

---

## Goals

The project aims to provide a stable Home Assistant integration for Hoben pellet stoves that communicates through the same remote service used by MyHOBEN, without requiring hardware modification or a contact relay.

The project should:

- read stove state and operating data;
- integrate cleanly with Home Assistant devices/entities;
- support safe user-level controls after validation;
- remain understandable and maintainable by the community;
- support HACS installation;
- progressively support several Hoben protocol profiles/models;
- never expose installer/factory combustion controls.

The first real validation target is a **Hoben Osmose**.

---

# Version roadmap

The version roadmap is intentionally incremental. Protocol and safety validation takes priority over feature count.

## v0.1.0 — Read-only foundation

Goal: prove stable communication and make the integration useful without sending stove-control commands.

Planned functionality:

- HACS-installable custom integration skeleton;
- UI-based Home Assistant `config_flow`;
- MyHOBEN User GUID input;
- client Device GUID creation/persistence;
- pairing/authorization flow if required by the server;
- TLS connection to `myhoben.fr:465`;
- `OpenClient` / `OpenedClient` handling;
- dynamic stove profile detection;
- Ping/Pong keepalive;
- automatic reconnect with backoff;
- safe buffering of fragmented/coalesced TCP/TLS frames;
- Modbus/TCP response parsing;
- read-only polling and spontaneous `DataUpdated` support;
- Home Assistant device registration;
- ambient temperature;
- smoke temperature where supported;
- combustion-air temperature where useful/supported;
- current target/derogation temperature read-back;
- power/power level;
- operation state;
- operation mode;
- ventilation mode;
- connection/availability state;
- warnings and fault diagnostics;
- Wi-Fi/technical diagnostics where useful;
- sanitized diagnostics export;
- French and English translations;
- full protocol unit tests and Home Assistant setup/entity tests.

Validation objectives on the real Osmose:

- identify V6 vs V6v16 profile;
- confirm raw-to-physical temperature conversion;
- confirm main state/power decoding;
- observe and document `DataUpdated` metadata;
- generate sanitized regression fixtures.

No Home Assistant control entity should send stove commands in this release.

---

## v0.2.0 — User-level temperature and operating controls

Goal: add the safest validated user controls after the read-only foundation is stable.

Planned functionality after real-device validation:

- write-command framework with strict register whitelist;
- optional explicit setting to enable control if considered useful;
- temperature/derogation command;
- ventilation mode selection: Normal / Silence / Boost;
- supported user operation modes;
- read-back confirmation after writes;
- command rate limiting;
- clear error handling for rejected Modbus/server commands;
- tests for every generated command frame;
- tests confirming that unsupported/technical modes are not exposed.

Do not expose `Magasin` or `ManuelTest` as normal user modes.

---

## v0.3.0 — Safe start/stop and richer Home Assistant control

Goal: provide normal day-to-day stove control while preserving Hoben's own shutdown and safety logic.

Planned functionality:

- normal controller ON request;
- normal controller OFF request through Hoben register 1280;
- state confirmation after command;
- timeout and rejection handling;
- no retry storm;
- Home Assistant-friendly control entities;
- automation-ready actions/entities;
- expanded tests around state transitions and unavailable states.

Important safety rule:

- OFF means requesting the Hoben controller's normal shutdown sequence;
- the integration must never cut mains power.

---

## v0.4.0 — Community hardening and multi-model support

Goal: move from a personal working integration to a community-quality HACS project.

Planned functionality:

- additional Hoben models/profiles based on community diagnostics;
- V4 support where sufficiently validated;
- V6/V6v16 mapping refinements;
- graceful unknown-profile diagnostics;
- expanded fault/warning decoding;
- historical counters/statistics where useful;
- documentation for contributors;
- issue templates requesting sanitized diagnostics;
- stronger translations;
- compatibility testing against supported Home Assistant versions;
- improved release automation;
- broader regression fixture set from multiple stove models.

---

## v1.0.0 — Stable community release

Goal: declare the integration stable enough for broad community use.

Requirements before v1.0.0:

- stable config flow and pairing path;
- robust reconnect behavior;
- no known unsafe write paths;
- all exposed write commands validated;
- comprehensive protocol regression tests;
- comprehensive Home Assistant tests;
- HACS validation passes;
- Home Assistant/Hassfest validation passes;
- documented installation, configuration, troubleshooting and diagnostics;
- stable entity IDs/unique IDs and migration strategy;
- multiple community testers if possible;
- published GitHub release with release notes.

After stability is demonstrated, consider applying for inclusion in HACS default repositories if the project meets the current requirements.

---

# Architecture

## High-level architecture

```text
Hoben stove
    │
    │ Hoben cloud connection
    ▼
myhoben.fr
    ▲
    │ TLS/TCP :465
    │ MyHOBEN framing + Modbus/TCP payloads
    │
Python protocol client (future pyhoben)
    ▲
    │ typed stove state / commands
    │
Home Assistant custom integration
    ▲
    │ entities / config flow / diagnostics
    │
Home Assistant user
```

---

## Recommended code layers

### Layer 1 — transport

Responsibilities:

- async TLS socket connection;
- certificate verification;
- reconnect/backoff;
- receive buffering;
- write serialization;
- timeouts;
- keepalive transport behavior.

This layer must not know about Home Assistant entities.

### Layer 2 — MyHOBEN framing

Responsibilities:

- message type encode/decode;
- `OpenClient`;
- `OpenedClient`;
- Ping/Pong;
- pairing/authorization messages;
- `DataRequestClient`;
- `DataResponseClient`;
- `DataUpdated`;
- safe extraction of the embedded Modbus/TCP frame.

### Layer 3 — Modbus/TCP codec

Responsibilities:

- MBAP encode/decode;
- function 03/04 reads;
- function 06 writes;
- function 16 writes when needed;
- function 22 mask writes when needed;
- exception responses;
- transaction IDs;
- signed/unsigned conversion helpers.

### Layer 4 — Hoben stove profiles

Profiles should define differences between:

- V4;
- V6;
- V6v16;
- future discovered profiles.

Responsibilities:

- register maps;
- state/mode enum mapping;
- value conversion;
- capability declarations;
- whitelisted user commands;
- validation ranges.

The profile must be selected dynamically from `OpenedClient` data.

### Layer 5 — stateful protocol client

Responsibilities:

- maintain current stove state;
- schedule/request refreshes;
- merge spontaneous `DataUpdated` messages;
- expose typed state to callers;
- serialize commands;
- confirm commands by read-back;
- surface clear exceptions.

### Layer 6 — Home Assistant integration

Responsibilities:

- config flow;
- coordinator/lifecycle;
- device registry;
- entities;
- diagnostics;
- translations;
- options/reconfiguration;
- mapping protocol exceptions to Home Assistant behavior.

Home Assistant code should consume a clean Python API rather than manipulate raw Hoben frames.

---

# Dedicated Python library recommendation

A dedicated protocol library is strongly recommended once the first protocol implementation is stable.

Suggested name:

```text
pyhoben
```

Possible repository/package split later:

```text
pyhoben
├── transport.py
├── protocol.py
├── messages.py
├── modbus.py
├── models.py
├── exceptions.py
├── profiles/
│   ├── base.py
│   ├── v4.py
│   ├── v6.py
│   └── v6v16.py
└── client.py
```

Benefits:

- protocol can be tested independently from Home Assistant;
- reusable by other Python projects;
- easier binary fixture testing;
- Home Assistant integration becomes smaller and easier to review;
- protocol releases can be versioned separately;
- failures can be isolated to protocol vs Home Assistant layers;
- future contributors do not need Home Assistant internals to improve protocol decoding.

### When to extract

Do not block v0.1 prototyping on publishing a separate package if that creates unnecessary overhead.

Recommended sequence:

1. keep strict internal module boundaries from day one;
2. reach stable read-only parsing with strong tests;
3. extract the protocol code into `pyhoben` before or during the control-feature phase;
4. publish a pinned library version;
5. declare that library in `manifest.json` requirements.

---

# Testing architecture

Testing is a first-class project workstream.

## Protocol simulation

CI should use a fake/simulated MyHOBEN server or transport abstraction plus sanitized binary fixtures.

This simulation should reproduce:

- normal `OpenedClient` responses;
- V4/V6/V6v16 profile responses;
- Modbus read responses;
- fragmented reads;
- coalesced messages;
- Ping/Pong;
- DataUpdated frames;
- write acknowledgements;
- Modbus exceptions;
- disconnects/timeouts;
- invalid packets.

The simulator is preferred over a live stove for CI because it is deterministic, safe and does not require secrets.

## Real stove

The Hoben Osmose should be used as an opt-in validation environment, not a CI dependency.

Real-device validation is important for unknown protocol semantics, especially:

- temperature scaling;
- timing units;
- profile identity;
- DataUpdated metadata;
- exact visible effect of writes;
- real reconnection behavior.

Once confirmed, convert observations into sanitized fixtures and regression tests.

## Home Assistant test environment

Use Home Assistant's pytest test infrastructure to validate:

- config flow;
- config entries;
- coordinator;
- entity setup;
- unload/reload;
- availability;
- diagnostics;
- redaction;
- commands;
- translations;
- migration.

Config-flow logic should have complete branch coverage, including error recovery and duplicate prevention.

---

# HACS and Home Assistant compliance strategy

The integration should be built toward current Home Assistant quality expectations even though it is initially a custom integration.

Key expectations:

- UI setup through config flow;
- connection test during setup;
- unique config entry/device handling;
- async I/O;
- diagnostics;
- sensible polling/update behavior;
- translations;
- automated tests;
- clear documentation;
- stable code ownership and issue tracker metadata.

For HACS:

- repository must remain public;
- only one integration under `custom_components/`;
- runtime files inside `custom_components/hoben/`;
- `manifest.json` with required metadata;
- root `hacs.json`;
- README;
- repository description and topics;
- brand asset(s);
- HACS validation action;
- GitHub releases for stable versions.

Requirements change over time, so release preparation must always re-check current official documentation.

---

# Development workflow with Codex

Codex should be used as the main coding agent for the repository.

Recommended workflow:

1. select one small roadmap item;
2. create a branch;
3. implement tests first or alongside implementation;
4. implement the feature;
5. update protocol/project documentation when relevant;
6. run all tests and validation locally/in the Codex environment;
7. open a pull request;
8. inspect CI results;
9. fix failures rather than bypassing checks;
10. merge only once tests and documentation are complete.

Use `AGENTS.md` as persistent project instructions for Codex.

Work/ChatGPT can be used for:

- deeper protocol reverse engineering;
- web research;
- design discussions;
- roadmap decisions;
- review of diagnostics from real stoves;
- preparation of protocol documentation.

---

# Initial repository milestones

Before writing the first functional client, establish:

- `AGENTS.md`;
- `protocol.md`;
- `project.md`;
- `README.md`;
- `LICENSE`;
- `hacs.json`;
- integration `manifest.json`;
- basic package structure;
- pytest setup;
- GitHub Actions for tests, HACS and Hassfest.

Then start v0.1.0 with the lowest-level protocol codec tests.

---

# Security and privacy

Never commit:

- real User GUIDs;
- real Device GUIDs;
- pairing codes;
- MyHOBEN APKs;
- reconstructed proprietary DLLs;
- raw unredacted captures;
- access credentials.

Where a real capture is needed for testing, sanitize identifiers before committing it and document the sanitization process.

---

# Definition of project success

The project is successful when a user can install it through HACS, configure a Hoben stove from the Home Assistant UI, obtain stable telemetry and safe controls, and provide useful sanitized diagnostics when something fails — while another community developer can understand the protocol and contribute without relying on private reverse-engineering artifacts.