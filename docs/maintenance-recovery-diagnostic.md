# Diagnostic et correction ciblée — #152

## Preuves et périmètre

Les incidents des 28 et 29 octobre 2026 sont des observations rapportées dans
#152 : `server_closed/server_maintenance`, puis `malformed_response` pendant un
usage simultané déclaré de MyHOBEN. Ni la durée d’indisponibilité ni cette
concomitance ne démontrent une cause serveur, réseau ou application concurrente.
Aucun horodatage applicatif MyHOBEN ni type de message fautif n’est disponible.

Comparaison du code installé `a62b73529a38cd9a663ecee75ee5d911ad381f78` à la base
experimental `4323d635dcaf2ded76b75047ea1dc125cf810915` : aucun diff dans
`custom_components/hoben`. La lecture GitHub de main confirme aussi les mêmes
blobs pour client.py, coordinator.py et __init__.py. Le diagnostic porte donc
sur ces chemins effectifs, sans attribuer l’incident à une ancienne architecture.

## Première correction — PR #155

- `V4Session.connect()` convertit un CloseClient pendant l’ouverture en
  `HobenClosedError`, ou en refus d’identifiant typé pour sa raison dédiée.
- `HobenDataUpdateCoordinator._async_update_data()` classait la maintenance en
  `ConfigEntryError`. Le premier refresh propageait cette erreur : HA enregistrait
  `SETUP_ERROR`, sans programmer la relance habituelle du setup.
- Seule la raison documentée `CloseClientReason.SERVER_MAINTENANCE` devient
  `UpdateFailed`. Le premier refresh HA la transforme en `ConfigEntryNotReady` ;
  `async_setup_entry()` nettoie toujours client/coordinator, puis HA possède
  temporisation et nouvelle tentative. Aucun nouveau timer ni retry applicatif.
- Après ouverture, le CloseClient cadré par le framer existant reste distinct
  de EOF : `ExperimentalCloseClientError`, nettoyage puis backoff borné du
  `V4Lifecycle`. Une ouverture récupérée ne rend pas les entités disponibles
  avant une nouvelle lecture corrélée. Le budget courant reste inchangé : deux
  ouvertures au maximum ; son épuisement demande toujours un rechargement explicite.

La mauvaise classification au setup est démontrée, pas son rôle dans les longues
indisponibilités réelles. En session, la récupération CloseClient existait déjà ;
ce correctif ne prétend pas introduire une nouvelle récupération générale.

## Reprise bornée — HOBEN-152-RECOVERY-002

La tâche MANAGER du 29/10 (commentaire #6498620755) autorise désormais une reprise
de communication ; elle remplace le caractère terminal de `malformed_response`
dans le vrai chemin HA décrit par la première livraison. Les tests rouges de
cette tâche reproduisent trois erreurs en session et le premier refresh laissé
en `SETUP_ERROR`. Le correctif conserve le parseur et ses refus : il change
uniquement la politique de récupération, jamais la validité des octets.

`HobenClient` active explicitement `V4Lifecycle(recover_acquisition=True)` en mode
persistant. Après ouverture, seules les classes exactes `HobenProtocolError` et
`HobenTimeoutError` rejoignent la récupération transport existante. La session
rejetée est fermée ; RX, waiters, TX et framer sont nettoyés avant le backoff.
Un nettoyage non confirmé interdit toute ouverture. La nouvelle génération a
son propre transport/framer et ne reprend aucun octet ni échange de l'ancienne.
Le refresh échoué retourne à HA ; il n'est jamais rejoué automatiquement.
L'ouverture suivante ne produit aucune lecture ni disponibilité : le prochain
refresh doit recevoir une réponse complète corrélée et décoder un nouveau snapshot.

Le budget du client reste **deux ouvertures sur sa durée de vie**, avec le délai
asynchrone existant (1 s par défaut, configuration 0–30 s). Un succès ne le
réinitialise pas ; les autres erreurs ne créent pas un nouveau lifecycle. Après
épuisement, un reload explicite reste nécessaire : pas de guérison illimitée.
Les campagnes conservatrices/quarantaine gardent leur politique par défaut,
sans récupération des erreurs protocole. Aucun budget de campagne n'est changé.

Au setup, `UpdateFailed` devient `ConfigEntryNotReady` via HA ; le cleanup existant
annule toute récupération en cours. HA possède le délai et le prochain setup
(nouveau client), sans timer supplémentaire. Les tests ne voient aucune nouvelle
ouverture avant 2 s et prouvent la relance native après avance de l'horloge.
Au refresh, HA conserve le précédent snapshot, marque les entités indisponibles
et réessaie à sa cadence normale (~60 s). Deux appelants restent sérialisés par
les verrous existants. Un unload annule aussi un refresh attendant le backoff.

| Erreur | Politique du vrai chemin HA |
| --- | --- |
| Transport, EOF, négociation TLS | Récupération existante, fermeture/délai/budget inchangés ; aucune preuve d'EOF inventée. |
| Timeout d'ouverture | `UpdateFailed`, relance native du setup ; pas de retry interne de handshake. |
| Timeout d'acquisition après ouverture | `UpdateFailed`, nouvelle session après cleanup et même budget ; aucune preuve de perte naturelle. |
| Réponse malformée, MBAP invalide, mauvaise corrélation, type inconnu non documenté | Refus `malformed_response`, fermeture ; récupération opt-in après ouverture, relance HA au setup. Aucun resync ni frontière ajoutée. |
| CloseClient post-open hors refus d'authentification | Reprise bornée existante, distincte d'EOF, y compris sous-code inconnu sans lui attribuer de signification. Maintenance au setup : politique de #155 conservée. |
| Identifiant refusé, autorisation rejetée/expirée/requise | `ConfigEntryAuthFailed`, aucun retry de session ni réponse d'association. |
| Configuration/profil invalides, CloseClient inconnu à l'ouverture, type connu non pris en charge après ouverture | Erreur explicite, aucun retry de session. Le type connu garde son erreur spécialisée et sa frontière inconnue. |
| Vérification du certificat/hostname TLS | `tls_verification_failed`, erreur permanente ; aucun fallback, nouveau transport ou retry HA natif. |
| Exception de programmation/contrat interne | `internal_failure` distinct, permanent ; jamais converti en acquisition récupérable. |
| Décodage métier HA invalide, erreur Modbus corrélée | Politique explicite existante conservée ; pas de nouvelle reconnexion universelle. |
| Annulation, arrêt, nettoyage échoué ou budget épuisé | Pas de nouvelle ouverture. L'épuisement conserve le code de la dernière erreur, pas une cause transport fabriquée. |

Les exceptions internes étaient parfois ramenées au même `HobenProtocolError` ;
elles reçoivent maintenant un sous-type distinct exclu du test de classe exacte.
La revue MANAGER #6500290135 a aussi identifié une conversion abusive de
`HobenInvalidInputError` lors de l'ouverture. Seul `SessionProtocolError` est
traduit en refus protocolaire ; les gardes d'entrée/identité et de destination
conservent `invalid_client_inputs`, permanent. Des tests sur le vrai V4Session
dans les deux modes, puis sur le vrai chemin HA, refusent hôte, port et les deux
avant toute connexion/écriture/lecture TLS, confirment le cleanup et `SETUP_ERROR`
sans nouvelle tentative même après 15 minutes d'horloge simulée.
Le refus de certificat a sa catégorie fixe, séparée de la négociation TLS.
Les diagnostics restent une allowlist sans historique, octets, identités, valeurs
domestiques ni texte d'exception libre. Un échec pendant le handoff est conservé
par le lifecycle, y compris avant l'enregistrement du prochain waiter.

## Malformed response et coexistence

`malformed_response` peut provenir du framing ou d'une réponse malformée/non
corrélée. Son seul code public ne permet pas de localiser la trame réelle fautive.
Les simulations de transaction erronée, type inconnu, MBAP invalide et réponse
concaténée à un type inconnu refusent toujours l'acquisition ; elles vérifient
maintenant `UpdateFailed`, ancien snapshot conservé, cleanup, backoff et une
nouvelle lecture sur une session neuve. Aucun octet ambigu n'est ignoré pour
continuer l'ancienne session ; aucun parseur n'est modifié.

`HobenClient.safe_report().state == ready` signifie que l’objet client n’a pas
été explicitement fermé ; cela ne prouve pas que le lifecycle est connecté ni
qu’un refresh a réussi. `last_update_success=false` et entités indisponibles
restent donc compatibles avec cette valeur, reproduite par les tests.

Le second acteur logique simulé sélectionne un CloseClient documenté pendant
une lecture HA en attente. Il n’invente aucune commande MyHOBEN ni règle
d’exclusivité du service. Ce test prouve seulement la réaction HA à cet événement,
pas que l’application l’a causé dans l’incident réel.

## Validation et limites

Tests déterministes avec vrais client, lifecycle, coordinator et entrées HA sur
transports mémoire : setup/relance native et retour des entités, refus fragmenté,
annulation d’un setup en attente, refresh/cadence normale, fermeture concurrente
simulée et nouvelle lecture fragmentée/coalescée avec Ping, identité adoptée et
persistée, nettoyage, erreurs permanentes et diagnostics expurgés. La première
livraison avait trois régressions rouges ; la tâche RECOVERY-002 en ajoute quatre
(trois réponses refusées au refresh, un setup malformé).

Le harnais HA épinglé utilise 2026.9.4 ; le système rapporté était 2026.10.2.
La CI offline ne vaut pas validation sur cette installation. Les quatre checks
sont attestés au HEAD exact dans la PR. Tests réels **NOT RUN**.

Pour départager l’incident malformed_response, une tâche distincte pourrait
définir des catégories bornées par phase (framing/corrélation/validation) et des
compteurs de transitions. Aucun diagnostic libre, RX brut, identifiant ou donnée
domestique ne serait admissible. Cette instrumentation et tout test réel restent
hors de cette petite correction ; aucune hypothèse de frontière n’est levée.
