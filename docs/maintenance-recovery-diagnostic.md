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

## Défaut reproduit et correction

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

## Malformed response et coexistence

`HobenProtocolError` peut provenir du framing, d’une réponse malformée/non
corrélée ou d’un contrôle de cohérence du client. Son seul code public ne permet
pas de localiser la trame réelle fautive. Les simulations d’identifiant de
transaction erroné, type inconnu et réponse concaténée à un type inconnu restent
terminales : `ConfigEntryError`, ancien snapshot conservé, aucune réouverture
ni lecture rejouée. Aucun octet ambigu n’est ignoré, aucun parseur n’est modifié.

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
persistée, nettoyage, erreurs permanentes et diagnostics expurgés. Trois tests
de classification étaient rouges avant correction (deux setup, un refresh).

Le harnais HA épinglé utilise 2026.9.4 ; le système rapporté était 2026.10.2.
La CI offline ne vaut pas validation sur cette installation. Les quatre checks
sont attestés au HEAD exact dans la PR. Tests réels **NOT RUN**.

Pour départager l’incident malformed_response, une tâche distincte pourrait
définir des catégories bornées par phase (framing/corrélation/validation) et des
compteurs de transitions. Aucun diagnostic libre, RX brut, identifiant ou donnée
domestique ne serait admissible. Cette instrumentation et tout test réel restent
hors de cette petite correction ; aucune hypothèse de frontière n’est levée.
