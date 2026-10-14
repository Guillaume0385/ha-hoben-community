# Fonctionnalités futures — hors développement V4 actif

Ce document conserve les pistes différées, sans autoriser de commandes au poêle ni de promotion sur main.

## Roadmap des contrôles futurs

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
- Other-version support deferred; historical documentation: [archive](archive-autres-versions.md).
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


## Architecture cible et bibliothèque indépendante

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

The extensible architecture preserves profile differences without authorizing
new non-V4 development. Historical/future profiles include:

- V4;
- V6 (historical, deferred);
- V6v16 (historical, deferred);
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

Current transitional responsibilities:

- own normalized private UserGuid and in-memory/persistable DeviceGuid;
- request one raw profile-specific refresh through a bounded TLS session;
- serialize refreshes and apply finite transport retry/backoff;
- expose an immutable raw snapshot and public profile metadata;
- surface clear exceptions.

Target v0.1 responsibilities defined by the
[active six-task series](../project.md#critères-de-développement-actifs--session-persistante-v4):

- retain one accepted post-OpenedClient TLS session while healthy;
- own one central post-open receive loop and deterministic frame dispatch;
- answer Ping with Pong immediately;
- serialize/correlate read-only Modbus requests and responses;
- receive spontaneous DataUpdated without inventing metadata semantics;
- close/cancel cleanly on unload;
- reconnect only after actual session/transport loss, reusing the persisted
  DeviceGuid through the existing frozen OpenClient path.

Scheduling remains owned by the HA coordinator/caller. Stove-control command
serialization/read-back belongs to later releases.

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
│   ├── v6.py  # legacy implementation, out of active V4 scope
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


## Fonctionnalités et entités HA différées

### v0.2.x — température et contrôles utilisateur validés

Après validation réelle :

- commande de température/dérogation ;
- durée de dérogation si son unité et sa sémantique sont validées ;
- `select` ventilation 0/1/2 ;
- `select` mode parmi les modes utilisateur pertinents ;
- confirmation par lecture après écriture ;
- limitation de fréquence et gestion des commandes rejetées.

Une entité `climate` peut être introduite pendant cette phase seulement lorsque les points suivants sont validés :

- échelle exacte des températures ;
- mode qui correspond à la consigne utilisée ;
- plage min/max autorisée ;
- comportement de la dérogation ;
- retour d'état après écriture.

### v0.3.x — marche/arrêt normal du contrôleur

Après validation dédiée du registre 1280 :

- commande ON via le contrôleur HOBEN ;
- commande OFF via le contrôleur HOBEN en conservant son cycle normal d'arrêt ;
- confirmation d'état après commande ;
- gestion des timeouts/rejets sans boucle de retry agressive.

Le registre 1280 est documenté dans [protocol.md](../protocol.md) pour
l’interopérabilité ; son exposition appartient à cette phase, conformément à
[project.md](../project.md).

---
