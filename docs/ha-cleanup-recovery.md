# B6 — nettoyage HA après timeout

Tâche exclusive [HOBEN-163-B6-HA-CLEANUP-FAILED-009](https://github.com/Guillaume0385/ha-hoben-community/issues/163#issuecomment-6640524954),
base `experimental` `59b33e04413d9c8b748d49bb3186ae9dd465a686`, après B5/#178.
La campagne #126 reste suspendue ; cette correction ne la modifie pas.

## Incident réel et limite d'attribution

Le [rapport passif #6637780437](https://github.com/Guillaume0385/ha-hoben-community/issues/163#issuecomment-6637780437)
établit un timeout puis `cleanup_failed` et un état durablement déconnecté.
Le SHA chargé sur HA et l'opération exacte qui échoue ne sont pas authentifiés.
Il ne prouve ni CloseClient, ni politique serveur, ni course particulière.
Le correctif ci-dessous traite un défaut local reproduit ; il ne démontre pas
qu'il explique cet incident réel ou tous les échecs de fermeture TLS.

## Course locale démontrée rouge puis verte

1. Le vrai chemin de récupération #160 reçoit un DataUpdated invalide, conserve
   TLS et attend ses 30 secondes de silence avant une unique sonde V4.
2. Le transport de test injecte un timeout d'écriture de cette sonde. C'est un
   défaut I/O indépendant : l'anomalie DataUpdated seule ne ferme toujours pas TLS.
3. La sonde termine son waiter, signale `HobenTimeoutError`, entre dans `_close`
   et attend RX, qui ferme le transport et attend le `wait_closed` borné existant.
4. Le superviseur reçoit la perte et appelle `abort`/`close`. Avant B6, il annule
   la sonde, y compris quand elle a déjà commencé ce nettoyage. Sa nouvelle
   annulation est transmise à RX et interrompt le shutdown TLS. Le résultat
   `cleanup_failed` interdit alors correctement toute réouverture.
5. B6 marque seulement la sonde déjà engagée dans `_close` avec un booléen privé,
   effacé dans son `finally`. Un nettoyage ordinaire attend cette même tâche au
   lieu de l'annuler. Une sonde encore active est toujours annulée ; une annulation
   explicite du propriétaire garde son chemin d'interruption et d'échec fermé.

Le marqueur n'est ni une attestation de réussite, ni une tâche de fermeture
supplémentaire. Il ne modifie aucun parseur, codec, timeout, silence #160, Pong,
classification B4/B5, politique de retry ou superviseur. Les chemins client,
coordinator, transport TLS et lifecycle conservent leurs contrats publics.

## Preuves et refus de succès

`tests/test_cleanup_b6.py` reproduit la course sur les vrais V4Session et
V4Lifecycle avec transports/horloge synthétiques : trois pertes successives,
nettoyage complet, un propriétaire, aucune ouverture à 59 s, nouvelle génération
à 60 s puis lecture V4 corrélée. Le timeout ordinaire sans réponse sert de témoin.

`ha_tests/test_cleanup_b6.py` conserve HobenClient, coordinator, V4Lifecycle,
V4Session et **AsyncTlsTransport**, en remplaçant seulement les streams et le temps.
Les paramètres certificat/hostname/SNI sont vérifiés sans connexion réseau.
Les tests couvrent attente de réponse, timeout d'écriture, TX Pong concurrente,
sonde en TX ou RX, `wait_closed` retardé, doubles close/abort, vraie erreur de close
ou wait_closed, expiration, annulation et unload. Ils vérifient :

- aucune nouvelle TLS ni backoff avant retour du close existant et réapage des
  tâches ; RX fini, TX/opérations vides, waiter et deadline libérés ;
- `cleanup_succeeded` et `cleaned_generation` seulement après cette fin, un seul
  close transport, une seule nouvelle génération après les 60 s existantes ;
- snapshot/date d'acquisition conservés, âge croissant, absence de fausse
  acquisition pendant la panne ; reconnexion comptée puis lecture corrélée ;
- cause timeout conservée dans l'ancienne session et le diagnostic causal du
  lifecycle ; `cleanup_failed` secondaire distinct lorsque le close échoue,
  jamais effacé par un close idempotent ultérieur ;
- aucun réessai après cleanup non prouvé, refus d'identité/certificat, erreur
  interne générique ou arrêt ; aucun octet privé ni exception libre journalisé.

Un poll pendant le backoff peut présenter `transport_unavailable` en attente de
reprise ; il n'est pas une nouvelle acquisition ni une nouvelle cause serveur.
Les diagnostics précédents conservent le timeout. Un échec réel de fermeture
reste terminal, y compris si l'abort TLS a été demandé : B6 ne fabrique pas une
preuve de shutdown après échec ou annulation.

Les régressions officielles incluent #160, B4, B5, #171, CloseClient/EOF, TLS,
annulations, snapshots et capteur A2. Les suites et quatre checks PR doivent
être rapportés sur le HEAD exact ; une CI en attente ne vaut pas réussite.

Validation réelle **NOT RUN**. Aucun accès Hoben/HA résidentiel, workflow live,
dispatch/rerun, commande poêle, écriture Modbus, nouveau secret, publication de
GUID/RX brut/donnée domestique ou modification d'automatisation. V4 lecture seule
et TLS certificat/hostname vérifiés conservés. Revue/fusion réservées à MANAGER ;
aucune reprise de C1/D ni relais automatique vers #126.
