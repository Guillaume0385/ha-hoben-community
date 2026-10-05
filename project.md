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

## Documentation roles and precedence

The three root Markdown files have distinct responsibilities:

- `project.md` is the source of truth for **project scope, roadmap, release sequencing and architecture decisions**;
- `protocol.md` is the source of truth for **reverse-engineered MyHOBEN/Hoben protocol facts, packet formats, registers and confidence levels**;
- `AGENTS.md` defines **development, testing, safety, documentation and contribution rules** for coding agents and contributors.

If these documents appear inconsistent about architecture, scope, feature timing or version planning, **`project.md` takes precedence**. Protocol facts should not be changed merely to match the roadmap; instead, implementation timing must follow `project.md`, while `protocol.md` continues to document what is technically known.

---

# Version roadmap

The version roadmap is intentionally incremental. Protocol and safety validation takes priority over feature count.

## v0.1.0 — Read-only foundation

Goal: prove stable communication and make the integration useful without sending stove-control commands.

Planned functionality:

- HACS-installable custom integration skeleton;
- UI-based Home Assistant `config_flow`;
- Identifiant HOBEN input, normalized to the 32-character MyHOBEN User GUID sent without dashes;
- client Device GUID lifecycle matching MyHOBEN: 32 zero characters before first assignment, then persistence of the server-provided DeviceGuid from `OpenedClient`;
- pairing/authorization flow using `DeviceAuthReq` / `DeviceAuthRes` when required by the server, with explicit handling of documented `CloseClient` rejection states;
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

- select the profile dynamically: the reference Osmose was confirmed as V4 on
  2026-10-04, without generalizing to all Osmose units;
- the raw V4 application read is already validated; implement the statically
  recovered 1024..1043 semantic decoder in a dedicated, tested profile layer;
- confirm on one sanitized live sample that the documented V4 temperature
  conversion (Int16 / 10 °C) matches the simultaneous MyHOBEN display;
- confirm the documented V4 packed state/power, mode and ventilation decoding
  against one real raw sample;
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
- additional V4 models/variants and edge cases beyond the reference Osmose;
- V6/V6v16 mapping refinements and support where sufficiently validated;
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

### Current increment — typed V4 decoder and first read entities (validation pending)

The issue #26 candidate implements a **Home Assistant-independent V4 semantic
decoder** above the unchanged raw `RawStoveSnapshot` API. `v4_state.py` exposes
`decode_v4_snapshot(snapshot) -> V4StoveState` and `decode_v4_temperature(raw)`.
The state is frozen/hashable and the decoder requires V4 and exactly 20 UInt16.
It performs no I/O and does not mutate the snapshot or move transport/session
concerns into the profile layer. Implementation and offline tests do **not**
mark this milestone DONE: exact-HEAD MANAGER validation and private simultaneous
raw/UI comparison on the reference Osmose are still pending before merge.

This increment must at minimum:

- decode V4 temperatures as signed Int16 values with the documented **/10 °C**
  conversion and handle the `0x0FFF` unavailable sentinel;
- decode register 1024 as packed mode + OnOff;
- decode register 1030 as packed power + V4 operation state;
- decode register 1028 ventilation as Normal / Silence / Boost;
- expose the established derogation values/units while keeping write/control
  behavior out of scope;
- leave warnings, combustion-fault labels, date/time packing, PVI and other
  partially established fields raw/partial until their mappings are complete;
- add deterministic unit tests for every implemented conversion and boundary;
- remain independent from Home Assistant entities so the decoder can later move
  cleanly into `pyhoben`.

`HobenCoordinatorData(raw, state)` combines raw metadata and semantic values from
one client refresh every 60 seconds. Decoding runs before successful DeviceGuid
rotation persistence; a decoding failure keeps the previous data and is sanitized
through the existing protocol error mapping. Entities use `CoordinatorEntity`
availability and read memory only. Setup forwards `sensor` and `binary_sensor`;
real entity listeners replace the artificial no-op subscriber. Partial setup
failure unloads platforms, shuts down polling, closes the client and discards
runtime_data. Normal unload removes listeners before shutdown; reload preserves
entity/device identities and uses the persisted DeviceGuid.

The candidate includes six core sensors (ambient/target temperature, power %, V4
state/mode, ventilation), diagnostic smoke/combustion-air temperatures, diagnostic
wired/RF ambient temperatures disabled by default, three derogation value sensors
and active/scheduled binary flags. A third binary sensor explicitly names the
controller OnOff request/read-back, without implying current combustion or using
RUNNING. Inactive derogation numeric values are unknown. Setpoints have no
measurement state class; enum sensors declare known snake_case options. Stable
unique IDs append an entity key to the config entry's non-secret fingerprint.
All attach to the existing stove and use EN/FR entity/state translations.

The fixed MANAGER probe now decodes both existing client refreshes and reports
only `v4_decode_count: 2` alongside prior sanitized metadata/counts. It adds no
session/read/retry and publishes no raw/decoded household values; the trusted
workflow is unchanged. This execution check cannot replace the private UI
comparison.

The separate manual `--live-v4-validation-values` CLI mode supports that private
comparison with one `HobenClient.async_refresh()` and no retry. It refuses
`GITHUB_ACTIONS=true` before credentials, client construction or network I/O and
is never invoked by a workflow. Its sole JSON includes a UTC timestamp, twenty
UInt16 words explicitly addressed 1024–1043, and the sixteen entity keys with
raw codes, decoded values and effective HA properties. Inactive derogation
numeric values remain in the raw/model fields while their HA values are null.
Unknown codes retain their raw value with null semantics. The export excludes
identifiers and tracebacks; it contains household values and must stay out of
public logs, artifacts and PR comments. Sharing with MANAGER is voluntary and
only through private chat during validation. Offline tests compare all sixteen
exported HA values with the real entity properties and protect the unchanged
public pre-merge report.

Before any physical-value entities enter main, MANAGER must review
the exact HEAD after green offline CI, pass the authenticated gate, and compare
ambient/target temperatures, operation mode, ventilation, OnOff and observable
state/power simultaneously with MyHOBEN. Record only compared fields, pass/fail
and timestamp in the PR. Stop and fix protocol evidence/tests on contradiction.
This increment remains strictly **read-only**, open for that review/validation.
Adding the private capture tool changes HEAD: a previous SHA's approval/live
result cannot approve this candidate; fresh review and an exact-HEAD gate are
required before the private comparison.

Next protocol gaps remain separate: warning-bit and fault-label tables,
date/time packing, PVI's reliable V4 meaning, unknown information bits and
DataUpdated metadata/framing. They have no ordinary HA entities in this candidate.

### DONE — Home Assistant config flow and raw coordinator

Issue #23 adds the first functional HA runtime layer over the completed client.
The UI accepts one sensitive **Identifiant HOBEN**, validates it with the existing
normalizer and performs exactly one `HobenClient.async_refresh()` before entry
creation. The temporary client closes on success, error and cancellation. Only
a successful V4 raw refresh with a nonzero server-assigned DeviceGuid can create
an entry. No pairing response is implemented; authorization requests show a
translated error with an opportunity to retry later.

`ConfigEntry.data` stores normalized `user_guid` and assigned `device_guid`, both
sensitive. A full SHA-256 fingerprint with fixed `hoben:user_guid:` domain prefix
provides the duplicate-resistant unique ID and device identifier. Titles, names,
errors and logs never expose the GUIDs. English/French custom-component texts
live directly in `translations/`, without a Core strings.json dependency.

`async_setup_entry()` constructs the client from persisted identity, awaits the
first refresh and stores typed client/coordinator objects in `entry.runtime_data`.
The `HobenDataUpdateCoordinator` keeps `RawStoveSnapshot` data and polls every
**60 seconds**. An entry-owned subscriber enables polling even before any entity
exists. Successful identity rotations update only `device_guid` through HA's
config-entry API; unchanged values do not update storage. Transport failures map
to `UpdateFailed`/setup retry, authentication failures stop polling with
`ConfigEntryAuthFailed`, and protocol/Modbus/unsupported profiles fail setup with
sanitized `ConfigEntryError`. Only HobenClient owns network retries. Unload stops
the timers and closes the client; HA discards runtime data, and reload reconstructs
the client with the persisted identity.

Authentication failures start an entry-bound `SOURCE_REAUTH` confirmation. It
accepts no identifiers and retries one client refresh using the entry's current
persisted UserGuid/DeviceGuid. The fingerprint must still match the existing
entry. Success updates only a newly assigned DeviceGuid and uses HA's
update/reload/abort helper to resume polling, even when the identity is unchanged.
Failure keeps the confirmation open with a sanitized translated error, without
changing storage or creating another entry. No DeviceAuthRes is sent. A different
HOBEN identity requires an explicitly new configuration, not a silent reauth
identity change.

One device is registered with a neutral name, manufacturer Hoben, safe protocol
profile and OpenedClient software version. No commercial Osmose model is inferred.
No semantic entity, permanent connection, DataUpdated, diagnostics, pairing,
reconfiguration or write/control path belongs to this increment.
**Validating the semantic mapping of the 20 raw V4 registers is the next protocol
milestone**, before any sensor values or physical units are exposed.

HA orchestration is tested offline using the separately pinned
`pytest-homeassistant-custom-component==0.13.367` / HA 2026.9.4 / Python 3.14.2+
environment and new `ha-tests` CI job. The existing Python 3.12 protocol suite
stays HA-independent. The trusted MANAGER authenticated exact-HEAD gate is retained
unchanged; the existing live suite validates the underlying client path.
HA tests also cover reauth initiation, confirmation, failure/retry, identity
rotation, reload and resumed polling. Scripted transport tests use the real client
to prove that reauth authorization requests never cause a pairing response.

### DONE — stateful read-only HobenClient and DeviceGuid lifecycle

`client.py` implements the intended protocol API for the Home Assistant
coordinator: `HobenClient(user_guid, device_guid=None)`, `async_refresh()` and
idempotent `async_close()`. It contains no HA objects/imports and stays inside
`custom_components/hoben/` until a later extraction to `pyhoben`.

`DEFAULT_BUILD` (34) and `DEFAULT_DEVICE_INFO` are defined once in `client.py`
and shared with the exploratory probes. The default DeviceInfo retains the
documented historical community `GitHubActions` descriptor. The fixed live suite
does not pass build/DeviceInfo overrides, so it exercises the same defaults the
HA caller uses. Offline regressions pin the documented default packet
and forbid the live suite from substituting exploratory probe settings.

The client owns a private normalized UserGuid and a private, in-memory,
persistable DeviceGuid. Without a persisted identity it starts with
`INITIAL_DEVICE_GUID` (32 ASCII zeroes). A supplied identity is validated before
any network I/O: only the proven 32-byte ASCII constraint is enforced, without
inventing a hex/GUID format. After an unambiguous supported V4 OpenedClient, the
returned DeviceGuid is validated and adopted immediately, before the read. It
survives subsequent read failures and is automatically reused on every later
refresh or transport retry. Unsupported/ambiguous openings do not update it.
The deliberately sensitive `device_guid_for_persistence` accessor is the sole
identity export; the client writes no storage. HA code explicitly
persists it in ConfigEntry storage. `has_assigned_device_guid` is non-sensitive.

Each refresh attempt uses a fresh verified `myhoben.fr:465` TLS transport:
OpenClient with current identity → OpenedClient/profile/boundary checks → adopt
identity → one raw application read → validate response → close. Only V4 is
implemented: FFFF, unit 1, function 04, address 1024, quantity 20. UNKNOWN and
other profiles fail with typed errors. `RawStoveSnapshot` is immutable and holds
exactly 20 raw UInt16 registers plus public product/software/profile metadata,
with no GUID, raw packet or session object. The **client still exposes raw values
by design**, while `protocol.md` now documents the V4 1024..1043 semantics and
formatting recovered from MyHOBEN. A dedicated V4 semantic decoder is the next
protocol layer; the raw transport/client model must not be overloaded with UI
conversion logic.

The client shares `_open_session()` and the V4 exchange primitives instead of
duplicating frames. Existing `open_session_once()` and
`open_and_read_v4_once()` remain available for exploratory tools/tests. Leading
Ping gets Pong; buffered unclassified OpenedClient suffixes and trailing response
bytes are rejected without reframing. The complete OpenedClient length remains
unresolved, including possible suffixes arriving in a later TLS read. A permanent
socket, receive loop, background reconnect worker and DataUpdated handling are
deferred until framing is sufficiently established.

The default transport retry policy is two total attempts: immediate first
attempt, close/discard on a transport failure, one nonblocking 1-second backoff,
then a fresh transport using the current identity. Configuration permits 1..2
total attempts and 0..30 seconds of backoff. Protocol/authentication errors,
DeviceAuthReq, CloseClient, unsupported profiles and Modbus exceptions never
retry. Cancellation propagates and closes the transport. An async lock serializes
refreshes including backoff and identity updates. `async_close()` permanently
closes the client, cancels its active refresh, waits for cleanup and prevents
queued/new refreshes. The caller provides recurring scheduling.

`exceptions.py` exposes distinct input, invalid-credential, authorization,
documented server-closure, unsupported-profile, protocol, Modbus, transport,
timeout, retry-exhaustion and closed-client failures. Repr, diagnostics and
errors never contain identities, caller descriptions or server payloads. The
last accepted profile and last successful snapshot are retained in memory.
No pairing, file persistence, HA semantic entities or control belongs to this
completed client increment. Static V4 semantics are now documented separately;
their implementation belongs to the next dedicated decoder increment.

The opt-in probe keeps TLS-only, session-open, synthetic negative and exploratory
`read-v4-state` modes. The fixed MANAGER-approved `--live-premerge` path now uses
HobenClient itself: two sequential refreshes on one instance, initial zero
DeviceGuid then automatic assigned-identity reuse, each with a fresh session and
one V4 read. Live retries are disabled so success means exactly two sessions and
two reads. Only public metadata/counts and validated reuse are exported; the
credential remains the sole input. Offline CI precedes exact-HEAD MANAGER review.
The MANAGER run for PR #22 confirmed identity reuse across two fresh TLS sessions
and two successful 20-register raw V4 reads on the reference Osmose on 2026-10-04.
The lifecycle is **DONE**; `protocol.md` records the reviewed SHA and sanitized
successful run. This live run did not itself establish V4 register semantics; those semantics
were subsequently recovered statically from MyHOBEN and are documented in
`protocol.md`. A real raw/display comparison is still required before treating
the decoder as dynamically validated. This does not establish all-model support.

### Layer 1 — transport

Responsibilities:

- async TLS socket connection;
- certificate verification;
- one bounded connection per transport (client orchestrates retry/backoff);
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

Current responsibilities:

- own normalized private UserGuid and in-memory/persistable DeviceGuid;
- request one raw profile-specific refresh through a bounded TLS session;
- serialize refreshes and apply finite transport retry/backoff;
- expose an immutable raw snapshot and public profile metadata;
- surface clear exceptions.

Scheduling belongs to the HA coordinator/caller. Long-lived reception and
`DataUpdated` merging await proven framing; command serialization/read-back
belong to later control releases.

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

- first-client `OpenClient` inputs with a normalized 32-character UserGuid and an initial DeviceGuid of 32 zeros;
- `DeviceAuthReq` / `DeviceAuthRes` association exchanges and documented `CloseClient` rejection codes;
- persistence/reuse of the DeviceGuid returned by a successful `OpenedClient`;
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

Validation has four separate layers:

1. **Offline deterministic CI:** pytest/Ruff, HACS and Hassfest; no Hoben network
   access or credential. Offline simulations remain reproducible and mandatory.
2. **Secret-free protocol smoke:** optional TLS-only and synthetic-identity
   diagnostics; these observations never establish authenticated success.
3. **MANAGER-gated authenticated pre-merge validation:** required before each
   merge, after review of the exact candidate HEAD, using a trusted main workflow
   and the fixed read-only live suite on that SHA.
4. **Manual exploratory live validation on main:** the existing dispatch modes
   for reviewed protocol research and diagnostics, separate from merge approval.

The Hoben Osmose remains an opt-in environment for the live lanes; normal pytest
and `Validate` never require it. Opt-in here means explicit MANAGER authorization
after review, not permission to skip the authenticated merge requirement.

### MANAGER-gated authenticated candidate validation

`.github/workflows/manager-live-hoben.yml` must be installed on protected `main`.
Only `pull_request_target: labeled`, the exact label `manager-live-hoben`, exact
actor `Guillaume0385`, a non-draft PR targeting `main` and the exact same head
repository `Guillaume0385/ha-hoben-community` can authorize execution. Forks,
automatic events, already-present labels and workflow reruns do not authorize it.
The trusted script rechecks case-sensitive identities and the current PR HEAD
before accepting a queued approval.

> Adding `manager-live-hoben` means the MANAGER has reviewed the exact candidate HEAD and explicitly trusts that code to run with the Hoben live credential.

Before labeling, MANAGER inspects the entire diff, checks AGENTS/project/protocol
compliance, rejects secret exfiltration/logging and unauthorized control paths,
verifies offline CI and records the full reviewed HEAD SHA. The trusted workflow
then checks out exactly `github.event.pull_request.head.sha` with
`persist-credentials: false`. `hoben-live` must retain its independent exact
protected-main branch policy; its sole `HOBEN_USER_GUID` secret is injected only
into the fixed candidate probe step. No candidate dependency is installed and
the status-writing token is kept on separate trusted runners.

`python scripts/probe_hoben_connection.py --live-premerge` requires two sequential
refreshes on the same HobenClient. The first starts with zero DeviceGuid and
adopts an assigned identity; the second automatically reuses it. Each opens a
fresh verified TLS connection, requires authenticated dynamic V4 without a
buffered unclassified suffix, makes exactly one function 04 read (transaction
FFFF, unit 1, address 1024, quantity 20), validates 20 correlated UInt16 values,
then closes. Success does not depend on exact register contents, product revision
or software version. Pairing, writes, controls, polling and live retries are
excluded. Client transport retries are tested deterministically offline.

Trusted jobs publish `pending`, then `success` only for full live success or
`failure` otherwise, using the stable commit status `live-hoben-authenticated`
on the event's exact candidate SHA. MANAGER verifies that SHA and the sanitized
report, confirms success, removes the label and merges only while HEAD still
matches. New commits require new review and label removal/re-addition.

After the first successful live validation, MANAGER must manually update
**Settings → Branches → main → Require status checks to pass before merging**
and add **`live-hoben-authenticated`**, alongside `tests`, `ha-tests`, `hacs`, `hassfest`.
Only effective branch protection makes this status enforceable for every new
SHA; a base-context Actions result or an older candidate success is insufficient.

The first installation needs a separate MANAGER decision: a trusted workflow
cannot run while it exists only in a candidate PR. Install its reviewed
definition on protected main before labeling the implementation PR. Leave that
PR open pending installation, review and authenticated validation; never obtain
the credential by running its candidate YAML as a bootstrap workaround.

Future v0.1 PRs adding safe real-testable read-only mechanisms must extend the
fixed bounded suite (for example persistent sessions, Ping/Pong, reconnect,
documented reads or DataUpdated). Future real writes require a separate safety
decision under AGENTS/project/protocol; write code alone never authorizes a test.

### Existing exploratory and secret-free workflow

The dedicated `Live Validation` GitHub Actions workflow is explicitly opt-in:
`workflow_dispatch` offers `tls-only`, real `session-open` or `read-v4-state`,
the latter two only on
`refs/heads/main` with the `hoben-live` environment. Before adding its sole Hoben
secret `HOBEN_USER_GUID`, mandatory PR review must protect main and the environment
must independently allow exactly Branch `main`, without other branches or tags.
README documents the separate verification of effective GitHub settings; a YAML
condition alone cannot protect a secret from code on an unreviewed branch.

Adding the exact `live-validation` label to a PR opts into TLS-only; adding
`live-session-negative` opts into a separate synthetic/unassigned UserGuid probe
with no secret or environment. Only `pull_request: labeled` is eligible. Existing
labels never authorize runs on new commits, push or synchronize; removing and
re-adding the chosen label requests another observation. The negative probe
classifies the actual response without requiring any particular server outcome.
Neither PR label can reach `read-v4-state`. All live modes remain opt-in, with
no automatic trigger or retry for the V4 read. These lanes stay separate from
deterministic/offline `Validate` CI. HA persistence and raw polling are established;
the current semantic candidate requires the exact-HEAD authenticated gate and
private raw/UI comparison above. Further pairing and protocol gaps require
separate reviews.

Real-device validation is important for the remaining unknown or statically
derived protocol semantics, especially:

- first-association behavior with a real HOBEN identifier and an initial zero DeviceGuid;
- origin/presentation of the authentication code and the live `0x2F → 0x30 → 0x04` sequence;
- reuse of the server-assigned DeviceGuid on a subsequent connection: **confirmed
  on the reference Osmose** (2026-10-04, `protocol.md` §4); **other models
  unconfirmed**;
- one simultaneous raw V4/UI comparison to validate the documented /10 °C,
  packed state/power, mode and ventilation mappings;
- exact V4 warning/information bits and combustion-fault code labels;
- packing of V4 date/time fields and practical meaning of 1033/1042;
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

Development follows a staged multi-agent workflow with independent review before MANAGER approval.

The canonical state machine is:

```text
MANAGER creates/specifies issue
        ↓
      ready
        ↓
    CODEX DEV
        ↓
   in progress
        ↓
      review
        ↓
   CODEX REVIEW
        ↓
     validate
        ↓
 MANAGER final review
        ↓
authenticated Hoben validation when required
        ↓
   merge / close
```

`blocked` is reserved for work that cannot safely continue without an external decision, missing protocol fact, permission, or other required input.

## Task preparation — MANAGER

The MANAGER selects one small roadmap item and turns it into a precise GitHub issue containing the objective, requirements, architecture constraints, protocol constraints, tests, validation steps, documentation impact, and acceptance criteria.

Only a MANAGER-reviewed issue may receive `ready`. Because the repository is public, an arbitrary issue created by a contributor is never sufficient authorization for autonomous development.

Avoid multiple large concurrent development tasks unless there is a clear need.

## Implementation — CODEX DEV

CODEX DEV first completes an existing `in progress` task or outstanding review corrections. Only when no such work exists may it take a `ready` issue.

For a new task, CODEX DEV:

1. reads `AGENTS.md` first and `project.md` / `protocol.md` when relevant;
2. moves `ready` to `in progress`;
3. creates a dedicated branch/worktree;
4. implements only the requested scope;
5. adds or updates deterministic tests;
6. updates documentation when required;
7. runs the applicable tests and repository validation;
8. opens or updates one PR linked to the issue;
9. moves the task to `review`.

CODEX DEV leaves implementation PRs open and never self-approves, adds `validate`, authorizes privileged live validation, or merges.

## Independent review — CODEX REVIEW

CODEX REVIEW works from `review` and independently verifies the current PR HEAD rather than trusting the developer summary.

The review covers, as applicable:

- issue requirements and acceptance criteria;
- complete diff against `main`;
- `AGENTS.md`, `project.md`, and `protocol.md` compliance;
- protocol correctness and explicit handling of unknowns;
- Home Assistant architecture and async behavior;
- security and secret redaction;
- tests, regression coverage, and CI;
- documentation and maintainability;
- all previous CODEX REVIEW and MANAGER remarks.

If corrections are required, CODEX REVIEW leaves precise comments or requests changes on the existing PR and moves the task back to `in progress`.

If the current HEAD satisfies the issue and every actionable review remark has been resolved, CODEX REVIEW approves it and moves the task to `validate`.

CODEX REVIEW never performs privileged authenticated Hoben validation and never merges.

## Final review and live validation — MANAGER

The MANAGER reviews a task in `validate` only after CODEX REVIEW has approved the exact current HEAD.

The MANAGER performs the broader project-level review: scope, roadmap, safety, architecture, complete diff, tests, CI, documentation, unresolved review threads, and exact HEAD SHA.

If the MANAGER requests any correction, it leaves the remarks on the same PR and moves the task back to `in progress`. CODEX DEV must address every actionable remark. The corrected PR then returns to `review` and must be independently revalidated by CODEX REVIEW before returning to the MANAGER.

Only after the code review and offline CI are satisfactory may the MANAGER authorize the authenticated Hoben validation defined in `AGENTS.md`, including the existing exact-HEAD `manager-live-hoben` gate where applicable.

The MANAGER merges only when every required check and required authenticated validation succeeds on the exact reviewed HEAD.

## Review loop invariant

Every review remark must be considered and answered. Every actionable remark requesting a change must be corrected before the task can advance.

Any commit after an approval invalidates that approval for workflow purposes. Therefore every correction follows:

```text
CODEX REVIEW or MANAGER remarks
            ↓
       in progress
            ↓
      CODEX DEV fixes
            ↓
          review
            ↓
      CODEX REVIEW
            ↓
        validate
            ↓
         MANAGER
```

There is no direct CODEX DEV → MANAGER correction path.

Review history stays on the same PR. Do not create a replacement PR merely to discard requested changes or unresolved review history.

## Source-of-truth boundaries

Use `AGENTS.md` as the persistent development, testing, safety, contribution, and workflow rules.

Use `project.md` for project scope, architecture, roadmap, and release sequencing.

Use `protocol.md` for protocol facts and confidence levels. Neither CODEX DEV nor CODEX REVIEW may invent missing protocol behavior to satisfy an issue.

Work/ChatGPT in the MANAGER role can be used for:

- deeper protocol reverse engineering;
- roadmap and architecture decisions;
- issue preparation and prioritization;
- final PR review;
- review of sanitized diagnostics from real stoves;
- authorization and interpretation of opt-in real-device validation;
- preparation and maintenance of protocol/project documentation.

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
