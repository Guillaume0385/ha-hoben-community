# Changelog

## Unreleased — recherche experimental

- Issue #81, tranche 7/8-C : correction de la création exclusive du rapport
  `session-300` en mode 0600, avec nettoyage du fichier partiel et fermeture du
  descripteur en cas d'erreur. Tests hors ligne du writer et de son appel réel
  depuis `main()` ; aucun changement de protocole, budget, gate ou autorisation.
  Le run 38729755965 reste **NOT RUN / résultat non vérifiable**.
- Issue #81, tranche 7/8-B : framing Ping/DataResponse opt-in sous hypothèse
  `session-300`, avec sonde réutilisant le gestionnaire V4 partagé et voie GitHub
  dédiée soumise aux gates MANAGER. Budgets 300 s utiles / 360 s globales,
  trois ouvertures, 1 Mio RX et six lectures fixes au maximum.
- Rapport à compteurs/catégories stricts, publication isolée et absence de replay.
  Aucun changement du client HA, des voies H1/H2 ou HA parity ni des commandes.
  Validation réelle 300 s : **NOT RUN** ; frontière OpenedClient non prouvée.

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


## Historique technique — fusions vérifiées

Les descriptions ci-dessous proviennent de l'ancienne roadmap. Les fusions
suivantes ont été vérifiées via l'API GitHub le 14 octobre 2026 ; une fusion
sur `main` ne prouve pas à elle seule une publication de release ou un test réel.
Les limites de validation de chaque description restent applicables.

| PR | Date de fusion (UTC) | Base | SHA de fusion |
| --- | --- | --- | --- |
| [#22](https://github.com/Guillaume0385/ha-hoben-community/pull/22) | 2026-10-04 | `main` | `24208ac9b494311f2a06279f2aba5a916c701a25` |
| [#24](https://github.com/Guillaume0385/ha-hoben-community/pull/24) | 2026-10-04 | `main` | `5e27ba08458885a20b91b08e5758ccd487f12874` |
| [#27](https://github.com/Guillaume0385/ha-hoben-community/pull/27) | 2026-10-05 | `main` | `65e7984934a93fbc4a87fd99c7ec303ed980655a` |
| [#33](https://github.com/Guillaume0385/ha-hoben-community/pull/33) | 2026-10-06 | `main` | `0addba7f7c9e9c1e13be96947a5f56fb37e02cb7` |
| [#35](https://github.com/Guillaume0385/ha-hoben-community/pull/35) | 2026-10-06 | `main` | `ad9b45b06fdcbff7b837137a0c22953aa2d78e1d` |
| [#37](https://github.com/Guillaume0385/ha-hoben-community/pull/37) | 2026-10-07 | `main` | `39364830151310c00eaa5dd82aec44d84ae863f0` |
| [#45](https://github.com/Guillaume0385/ha-hoben-community/pull/45) | 2026-10-07 | `main` | `18b60c13fe12deaa0578787c139df9d4fe02c1e6` |

### Diagnostics HA — Issue #36 / PR #37, complétés par #45

`diagnostics.async_get_config_entry_diagnostics` implements the standard HA
config-entry download API using existing in-memory runtime state only. The
integration-owned JSON is an explicit allowlist, intended for public GitHub
support issues. HA wraps it with its standard system/integration metadata.
No ConfigEntry data/options, entry ID/title, private identity fingerprint, entity
state or decoded household value is read by the adapter. No transport, refresh,
reconnect, association, Modbus operation or background task is started; no client,
coordinator, registry, entity or ConfigEntry state is mutated.

The payload schema contains the public domain, entry lifecycle/schema versions
and `runtime_available`. With a runtime, it selects bounded primitive fields from
`HobenClient.safe_report()` (state, neutral profile, assigned-DeviceGuid boolean)
and `RawStoveSnapshot.safe_report()` (profile, public product/revision/software/
application metadata and register count). Coordinator metadata contains last
update success, the fixed 60-second polling interval, snapshot availability and
a sanitized last-error category. A retained snapshot describes the last accepted
read, not current connectivity. Without runtime, only the lifecycle/static
metadata is returned; without a successful snapshot, `snapshot` is null.

The HA error boundary (#43) preserves typed Hoben categories through a real
coordinator failure. The shared HA-only `safe_reports.py` validates and copies
existing safe-report codes/reasons and limited numeric metadata into the existing
HA exception class. Its message suffix lets HA's existing failure log distinguish
those same categories without a new logger, traceback or event journal. This
includes the existing decoder's `invalid_v4_snapshot` category when it rejects a
local V4 snapshot, without exposing registers or attributing the failure to the
server. HA keeps its normal logging/deduplication lifecycle. Diagnostics revalidate
the copied primitives using the same allowlist, without retaining a source
exception for export. Unannotated HA wrappers retain fixed authentication/update/config-entry
categories; arbitrary errors or unusable Hoben error contracts use
`unexpected_error`. No exception text, arguments, traceback or chains are
inspected to reconstruct a cause. Unknown keys, malformed report contracts,
non-primitive values and fields outside approved value ranges are omitted.
After a successful refresh, `last_error` is null even if HA retains its previous
`last_exception`: this is current status, without error history or counters.
Error classes, authentication polling stop, availability, the 60-second interval,
client retries/backoff, accepted data, identity persistence and cleanup are retained.
GUIDs, authorization codes, credentials, raw frames/register values, private
fingerprints, household measurements and derogation/entity states are excluded.
Unresolved warnings/fault labels, information bits, date/time, PVI and DataUpdated
remain unresolved in `protocol.md`; no mapping or unsafe raw field is added.

Offline HA regressions cover the real diagnostics HTTP download, loaded and
unloaded entries, missing runtime/snapshot, failed updates, typed/unexpected
errors and future or malformed safe-report extensions. Synthetic private inputs
are recursively excluded from keys and values, including the complete HA JSON
download. Tests enforce JSON bounds, deterministic output, no new I/O/tasks and
unchanged runtime/storage/registry state. Existing protocol/client, config-flow,
entity, translation and trusted live code is unchanged. This completes only the
sanitized-diagnostics implementation item; other v0.1 roadmap gaps remain.
This runtime addition requires independent CODEX REVIEW and MANAGER exact-HEAD
authenticated validation before merge under the existing policy. The trusted
fixed read-only gate remains a regression gate and does not export diagnostics.

The #43 regressions use real coordinator refreshes, scripted synthetic TLS
responses, normal HA polling timers and full HTTP diagnostics downloads to cover
typed categories, failure/recovery, deduplication, bounds, privacy and unchanged
I/O/storage. They establish the observability defect and its correction only;
the cause of the historical outages and the then-installed commit remain unknown.
A future passive report needs the actual installed public ref, typed category,
reliably observed recurrence/window, categorical availability and recovery.
Deduplicated HA log counts do not establish the number of failed refreshes.

### Home Assistant authorization pairing (offline, #34 / PR #35)

Issue #34 connects the reviewed association API to the initial config flow and
entry-bound reauthentication. The existing normalized private identifier,
fingerprint duplicate check and refresh path remain the entry point. An already
authorized V4 read succeeds without requesting a code. Authorization-required
closes the temporary client before showing a password-only authorization form;
no TLS connection, protocol task or code provider waits between forms. Only the
initial flow keeps its normalized identifier privately between steps. Reauth
reads the current ConfigEntry.data at each attempt and checks its fingerprint.

Each explicit code submission locally converts decimal text to UInt16, opens a
fresh client and calls async_associate exactly once. The client alone owns the
handshake and decides whether a provider is needed. There is no automatic resend,
retry, protocol duplication or Modbus read/write on this submission path. Only a
supported, unambiguous V4 opening with nonzero DeviceGuid is committed; subsequent
reading belongs to normal setup/coordinator operation. Reauth updates only the
successful DeviceGuid assignment and reloads the same entry, preserving its ID,
unique ID, title and options. Concurrent identity changes cannot adopt a stale
assignment. Failures and cancellation close the client without altering storage.

The authorization code stays local to the active submission and is never stored
in ConfigEntry data/options, flow attributes/context, logs, exceptions or form
defaults. English/French forms expose fixed errors for invalid identifiers,
authorization-required/rejected/timed-out, stove connection required, maintenance,
transport and unsupported/protocol responses. Retry requires another submission.
UInt16 is a wire representation constraint, not a server code range, digit-count
or lifetime claim. Code source/presentation and first real association remain
unknown pending MANAGER evidence.

Offline HA regressions exercise real form lifecycles, cancellation and cleanup,
authoritative entry data, identity/duplicate protections, storage and privacy,
plus real typed-client wire sequences on scripted TLS transports. This runtime
config-flow change requires independent CODEX REVIEW and the existing exact-HEAD
MANAGER authenticated gate before merge. The privileged fixed read-only suite,
live workflows and credential policy are unchanged and do not submit a code.

### Protocol foundation — DeviceAuth association (offline, #32 / PR #33)

Issue #32 adds `HobenClient.async_associate(*, authorization_code_provider=None)`
to the existing HA-independent client. The async zero-argument provider returns
an int representable as UInt16 and is awaited only after DeviceAuthReq, at most
once. The MANAGER's 2026-10-06 static analysis establishes the one-byte `2F`
marker for this interoperability path (`protocol.md` §5). The shared handshake
retains coalesced bytes, accumulates fragmented prefixes, answers leading Ping
and sends the pure encoder's `30 + UInt16-LE(code)` before awaiting OpenedClient
or a documented CloseClient. A repeated request after submission fails without
resending. Existing OpenedClient suffix/profile checks still apply; its complete
length and later-arriving suffixes remain unknown.

Association performs one fresh verified TLS attempt, with no Modbus read/write
and no automatic retry, regardless of the refresh retry settings. The existing
finite handshake_timeout includes provider waiting; this local budget is not an
inferred code lifetime. Successful supported V4 opening adopts DeviceGuid using
the existing sensitive persistence accessor. `AssociationResult` contains only
public opening metadata, without identifiers, code, provider or household data.
Missing provider surfaces authorization-required; invalid/failed provider gets
`HobenAuthorizationCodeError`, without arbitrary exception text. Documented
server closures and transport/protocol failures retain distinct typed errors.
No credential is written to storage. Association preserves last_snapshot and
shares the refresh lock; async_close cancels either operation and cleans up.

Offline regressions cover the wire sequence, all two-part receive splits,
byte-at-a-time reads, coalescence, Ping/Pong, closure/rejection, invalid inputs,
unsupported/ambiguous openings, timeouts, cancellation, serialization, identity
reuse, confidentiality and absence of Modbus/control requests. Existing refresh
and probes do not supply a code and keep their observation-only path. The HA
form above uses this API only on explicit authorization submission. The first real
association, code presentation and server timing still require MANAGER evidence;
no authenticated validation is triggered by development or ordinary CI.

### Décodeur V4 et premières entités — PR #27 (Osmose de référence)

Issue #26 / PR #27 implements a **Home Assistant-independent V4 semantic
decoder** above the unchanged raw `RawStoveSnapshot` API. `v4_state.py` exposes
`decode_v4_snapshot(snapshot) -> V4StoveState` and `decode_v4_temperature(raw)`.
The state is frozen/hashable and the decoder requires V4 and exactly 20 UInt16.
It performs no I/O and does not mutate the snapshot or move transport/session
concerns into the profile layer. The milestone was validated by MANAGER and
merged on **2026-10-05**, on exact HEAD
`288d6408d376dcec875ea09135eab800e5563b4f`.
The [MANAGER PASS report](https://github.com/Guillaume0385/ha-hoben-community/pull/27#issuecomment-6001144860)
records authenticated validation, successful HA setup and a private simultaneous
comparison with MyHOBEN. It applies to the reference Osmose and observed
situations only, not all models or every possible state.

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

The increment includes six core sensors (ambient/target temperature, power %, V4
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

The final MANAGER validation passed the exact-HEAD authenticated gate and
confirmed ambient/target temperatures, operation mode, ventilation, OnOff and
observable state/power against MyHOBEN, plus the observed derogation behavior.
Only compared fields, pass/fail and date were published; no household values or
identifiers were disclosed. This completed increment remains strictly
**read-only**. Future changes require fresh exact-HEAD review and the applicable
MANAGER validation; an earlier SHA's approval/live result cannot approve them.

Next protocol gaps remain separate: warning-bit and fault-label tables,
date/time packing, PVI's reliable V4 meaning, unknown information bits and
DataUpdated metadata/framing. They have no ordinary HA entities in this increment.

### Config flow et coordinator brut — PR #24

Issue #23 adds the first functional HA runtime layer over the completed client.
The UI accepts one sensitive **Identifiant HOBEN**, validates it with the existing
normalizer and performs exactly one `HobenClient.async_refresh()` before entry
creation. The temporary client closes on success, error and cancellation. Only
a successful V4 raw refresh with a nonzero server-assigned DeviceGuid can create
an entry on the original path. The later #34 increment above adds an explicit
authorization form and an association-only opening path.

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
changing storage or creating another entry. The #34 increment transitions an
authorization request to a separate code form; only a subsequent explicit
submission can send DeviceAuthRes. A different
HOBEN identity requires an explicitly new configuration, not a silent reauth
identity change.

One device is registered with a neutral name, manufacturer Hoben, safe protocol
profile and OpenedClient software version. No commercial Osmose model is inferred.
No semantic entity, permanent connection, DataUpdated, diagnostics,
reconfiguration or write/control path belongs to this increment.
The subsequent V4 decoder/entities milestone (#26 / PR #27) completed that
semantic layer and was validated on the reference Osmose on 2026-10-05.
Explicit pairing is added separately by #34 above.

HA orchestration is tested offline using the separately pinned
`pytest-homeassistant-custom-component==0.13.367` / HA 2026.9.4 / Python 3.14.2+
environment and new `ha-tests` CI job. The existing Python 3.12 protocol suite
stays HA-independent. The trusted MANAGER authenticated exact-HEAD gate is retained
unchanged; the existing live suite validates the underlying client path.
HA tests also cover reauth initiation, confirmation, failure/retry, identity
rotation, reload and resumed polling. Scripted transport tests use the real client
to prove that initial reauth requests never send a pairing response automatically.
The later #34 tests cover the response only after explicit code submission.

### Client lecture seule et cycle DeviceGuid — PR #22

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
formatting recovered from MyHOBEN. The dedicated V4 semantic decoder described
above implements the next layer; the raw transport/client model must not be
overloaded with UI conversion logic.

The client shares `_open_session()` and the V4 exchange primitives instead of
duplicating frames. Existing `open_session_once()` and
`open_and_read_v4_once()` remain available for exploratory tools/tests. Leading
Ping gets Pong; buffered unclassified OpenedClient suffixes and trailing response
bytes are rejected without reframing. The complete OpenedClient length remains
unresolved, including possible suffixes arriving in a later TLS read.

The current fresh-session-per-refresh lifecycle is now explicitly transitional.
The [active v0.1 series](project.md#critères-de-développement-actifs--session-persistante-v4) targets a persistent session **only after** the
existing strict opening path has accepted OpenedClient and Task 1 has established
a safe reference-Osmose handoff to post-open reception. The persistent work must
not resolve the unknown universal OpenedClient boundary by assumption. If the
handoff remains ambiguous, persistent reception stays blocked.

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
completed client increment. V4 semantics and read entities belong to the
subsequent completed decoder increment described above.

The opt-in probe keeps TLS-only, session-open, synthetic negative and exploratory
`read-v4-state` modes. The fixed MANAGER-approved `--live-premerge` path now uses
HobenClient itself: two sequential refreshes on one instance, initial zero
DeviceGuid then automatic assigned-identity reuse, each with a fresh session and
one V4 read. Live retries are disabled so success means exactly two sessions and
two reads. Only public metadata/counts and validated reuse are exported; the
credential remains the sole input. Offline CI precedes exact-HEAD MANAGER review.
The MANAGER run for PR #22 confirmed identity reuse across two fresh TLS sessions
and two successful 20-register raw V4 reads on the reference Osmose on 2026-10-04.
The one-shot lifecycle was merged in PR #22; `protocol.md` records the reviewed SHA and sanitized
successful run. This live run did not itself establish V4 register semantics; those semantics
were subsequently recovered statically from MyHOBEN and are documented in
`protocol.md` and validated dynamically by MANAGER on 2026-10-05 in PR #27.
Neither validation establishes all-model support.



## Règle de tenue du changelog

Toute PR documente les modifications réellement livrées, avec date, numéro de PR, SHA de fusion et tests. MANAGER vérifie l'entrée ou une justification d'absence d'impact à chaque revue.


### Documentation — synchronisation vers `main` par PR #78 (en attente de fusion)

Nettoyage des documents actifs, sécurité et gouvernance expérimentale. Ces changements proviennent de la documentation préparée sur `experimental`
(notamment la PR #77, fusionnée sur `experimental` le 14 octobre 2026, commit de fusion `fd4453e9bd229d9c33c91c0c63ccdc31acbd528c`) ; la PR #78 propose leur synchronisation documentaire
vers `main` sans importer de code, tests, scripts ni workflows expérimentaux.
**Tant que la PR #78 n'est pas fusionnée, cette entrée décrit une livraison
proposée et non réalisée ; le SHA de fusion et les tests de livraison restent
à compléter après fusion.**

Corrections documentaires du 14 octobre 2026 : contrats d'admission/recheck et
limites des reruns restaurés depuis les gates installés ; statut de #75 vérifié ;
archivage des sections non V4 complètes avec provenance ; cartographie V4,
critères des six tâches actives et distinctions faits/hypothèses conservés ;
liens et renvois corrigés ; observations H1/H2 reliées à leurs sources.
Les vérifications des sources expérimentales sont consignées dans la PR #77 ;
les vérifications propres à la livraison documentaire sont celles de la PR #78.
Aucun code exécutable, test live ni commande poêle n'est inclus. La fusion de
#78, si autorisée, sera une livraison **documentaire uniquement** sur `main`.
