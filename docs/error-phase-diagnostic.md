# Diagnostic de phase V4 — #163 B1

[Consigne MANAGER B1](https://github.com/Guillaume0385/ha-hoben-community/issues/163#issuecomment-6549535105).
Socle examiné : `5526407283e182e3979f815bba43c093c849b95c` (A1/A2 intégrées).
B1 ajoute une provenance locale fermée aux erreurs, sans correction de retry.
Les incidents réels #152/#160 restent de cause inconnue ; les tests ci-dessous
reproduisent le manque local de phase, pas leur cause serveur ni leur version HA.

## Chemins et preuves locales

| Origine / fonction | Catégorie conservée et phase prouvable |
| --- | --- |
| `v4_session.py::connect` → `_open_session` | Refus initial `HobenClosedError` → `server_closed`, raison documentée ; `05 02` → `invalid_credentials`, certificat refusé → `tls_verification_failed`. Phase `opening` : l'opération globale est connue, pas sa sous-étape DNS/TCP/TLS. |
| `v4_session.py::_read_framed_delivery`, `_receive_unproven_handoff` | Exception issue de `transport.read` ou retour EOF vide → phase `tls_read`. `TransportEOF` et `TransportTlsError` suivent des chemins d'entrée distincts mais gardent `transport_unavailable` ; certificat refusé garde `tls_verification_failed`, timeout garde `timeout`. Ni erreur TLS précise ni cause distante inférée. |
| `v4_session.py::_receive_experimental` → `ExperimentalV4Framer.feed` | Rejet déjà structuré : phases `message_classification` / `frame_boundary` inchangées. Exception locale imprévue du framing : `internal_failure`, `frame_boundary`. Aucun nouveau cadrage. |
| `v4_experiment.py::ExperimentalV4Framer.feed` → `modbus_tcp_frame_size` | Exception imprévue de ce seul appel : `internal_failure`, `mbap_header`. Un en-tête invalidé normalement conserve son diagnostic malformed_response existant. |
| Construction de `DelimitedV4DataResponse` dans `_receive_experimental` | Exception imprévue : `internal_failure`, `message_type` (contrat de livraison du message seulement). Ne prouve aucun sens d'un type inconnu. |
| `v4_session.py::_handle_delimited_data_response` → codecs existants | Exception imprévue des appels de décodage : `internal_failure`, `pdu_decode`. Un rejet normal conserve `malformed_response` et sa phase `response_validation` / `request_correlation` ; une exception Modbus corrélée conserve `modbus_exception`, phase `pdu_decode`. |
| `coordinator.py::_async_update_once` → `decode_v4_snapshot` | `V4DecodeError` garde `invalid_v4_snapshot` et le maintien A1 ; exception locale imprévue garde `unexpected_error`. Phase `model_decode`, sans lecture de registres dans le diagnostic. |
| Même fonction → `_persist_identity` | Échec de stockage imprévu : `unexpected_error`, phase `identity_storage`, sans faux succès ni date avancée. Lors d'une acquisition déjà échouée, un échec secondaire de persistance est logué par cette phase mais ne remplace pas l'erreur primaire. |
| `v4_session.py::_release_transport`, `v4_lifecycle.py::_cleanup` | Phase `cleanup` pour un nettoyage défaillant. Les catégories/sécurités antérieures restent : erreur de fermeture transport, ou `cleanup_failed` quand le lifecycle HA constate le cleanup non confirmé. |
| Toute autre exception, witness client, TX Pong, attente ou code non instrumenté | Pas d'étape précise inventée : `unknown` pour unexpected_error / conversion générique instrumentée ; attribut A2 `None` si aucune métadonnée typée n'existe. Ces deux formes signifient absence de preuve. |

`05 03` après ouverture suit un autre chemin : framer →
`ExperimentalCloseClientError` → `V4Lifecycle._run` → `HobenClient._refresh_once`
→ coordinator. Son code `experimental_close_client`, sa raison
`stove_connection_required` et la phase `post_open` restent inchangés. C'est un
événement protocolaire, pas un EOF ni une preuve d'exclusivité MyHOBEN/HA.
`server_closed` à l'ouverture et ce refus post-ouverture ne sont pas confondus.

Les exceptions imprévues RX sont déjà converties en `HobenInternalError` par
`V4Session._receive_unproven_handoff` / `_handle_delimited_data_response`, puis
en `ConfigEntryError` par le coordinator. Les exceptions imprévues restantes de
`V4Lifecycle._run` gardent `internal_failure`, phase `unknown` sans marqueur.
Une exception imprévue qui atteint directement `_async_update_once` devient
`ConfigEntryError` via `wrap_error`, avec code `unexpected_error` et phase connue
ou `unknown`. B1 conserve ces classes et ce routage : aucune nouvelle exception
récupérable, aucune causalité historique déduite de la seule catégorie.

## Propagation et confidentialité

`error_phases.py` ne transporte qu'une chaîne d'une liste fermée sur l'exception
existante. Les frontières imbriquées conservent la preuve la plus interne ; les
diagnostics malformed_response déjà précis et `post_open` restent prioritaires.
Pas de texte, traceback, chemin privé, cause, contexte, note ou attribut métier
inspecté. Le marqueur est revalidé à l'export ; une métadonnée invalide est omise.
Le gestionnaire de contexte ne lit/modifie pas le traceback et ne retient pas
l'erreur ; annulation et identité/type de l'exception restent inchangés.

`HobenError.safe_report` → `safe_reports.safe_error_report` / `wrap_error` copie
les scalaires approuvés dans l'exception HA ; `diagnostics.py` revalide ce rapport.
Le canal de `SessionMonitor` revalide la même liste de phases pour le capteur A2.
Les logs inattendus de `helpers.log_unexpected_error` donnent uniquement une
catégorie/phase fixe ; les emplacements de pile sont retirés, sans I/O source.
Les logs de tentative HA ajoutent cette phase sans changer leur temporisation.

Au setup, le client/lifecycle sont identiques à ceux du refresh. L'entité A2
n'existe qu'après première acquisition valide ; le monitor observe déjà les
erreurs. Maintenance temporaire : même propriétaire en backoff >=60 s ; refus
permanent : mêmes wrappers HA et cleanup ; annulation du setup : aucune entité,
timer ou tâche orpheline. Au refresh, aucune phase ne vaut un succès de lecture.

DataUpdated invalide garde `malformed_response`, phase `mbap_header` dans A2,
silence RX glissant 30 s et une sonde sur le même TLS. Aucun changement de
framing, limite, rejet, politique de reprise, disponibilité A1 ou poll réseau.
Les seules erreurs testées sont injectées hors ligne ; **tests réels NOT RUN**.

## Validation et suite B2

Régressions rouges sur le socle (phase absente), vertes sur vrais composants
HA/client/lifecycle/session : huit frontières, catégories de fermeture/EOF/TLS,
setup et refresh, modèle informatif A1, stockage, unknown, DataUpdated, wrappers
hostiles, annulation/unload et absence de faux rafraîchissement. Suite complète
unitaires/HA et quatre checks requis au HEAD candidat dans la PR.

B2 exige une consigne MANAGER distincte et une reproduction minimale qui prouve
quel chemin de reprise manque, à partir du code réellement chargé. Une phase
localise une opération, pas la cause racine ni la bonne politique de retry.
Les catégories permanentes, l'ownership unique et le contrat DataUpdated devront
rester vérifiés. B1 ne prépare aucun retry supplémentaire, scénario C ou collecte D.
