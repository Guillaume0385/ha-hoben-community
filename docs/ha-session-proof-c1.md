# Étape 8 C1 — preuve HA exclusivement hors ligne

Consigne : [#112, première section MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/112#issuecomment-6395141200).
**Actualisation propriétaire du 25/10 :** C2a/C2b hoben-live n'exigent plus de
quota RX. Le [contrat C2a](ha-session-runtime-c2a.md) prévaut pour cette fondation ;
les valeurs RX de ce document/schéma C1 restent historiques, sans application
à hoben-live. H1/H2 et session-300 conservent leurs budgets.

A (#123) et B (#124) sont fusionnées ; base C1
`35e8bf96a6c9223706a0741344f7add7aed222ce`. C1 prépare un contrat et un
collecteur de fixtures, sans point d'entrée live. C2 reste une attribution
distincte après revue/fusion C1. Aucun résultat ci-dessous ne valide le poêle.

## Observation publique minimale

`HobenClient.session_observation` et `V4Lifecycle.session_observation` retournent
un `SessionObservation` typé, figé, de taille constante. La lecture n'effectue
aucune I/O, n'adopte pas d'identité, ne crée pas de lifecycle, ne change ni
handshake, framer, retry, polling, corrélation ni nettoyage. Aucun GUID,
DeviceInfo, registre, message d'exception ou payload n'est exposé.

Les tentatives comptent aussi les ouvertures échouées. Une génération est un
ordinal local d'ouverture **acceptée**, jamais un identifiant réseau. La séquence
de lecture appartient à sa génération et avance seulement après réponse V4
corrélée. Une réouverture réinitialise ce témoin de lecture, pas les retries.
Le dernier événement `transport` exige le témoin de perte déjà produit par le
gestionnaire ; il ne distingue pas EOF et erreur TLS, et **n'affirme aucun EOF**.
`close_client` exige le message expérimental complet et conserve son UInt8.
Timeout, protocole, annulation et stop local n'inventent aucun de ces événements.
Le dernier cleanup de génération réussi reste visible ; un échec est mémorisé
sans effacement. `stopped` exige le détachement et la fin du propriétaire.

## Collecteur et critères

`ha_tests/ha_session_collector.py` reçoit un **nouveau** vrai HobenClient et
HobenDataUpdateCoordinator déjà construits par les fixtures HA isolées, dont
les sockets sont interdits. Il appelle `coordinator.async_refresh()` : lecture,
snapshot, décodage HA et persistance existants. Il ne lit aucun attribut privé,
ne remplace pas la logique métier et ne crée pas de client, d'instance HA ou de
transport. Aucun CLI, lecteur de secret, workflow, admission, claim ou upload.

Six slots fixes à 0/50/100/150/200/250 s, horloge/sommeil injectés pour les tests.
La cadence HA installée de 60 s n'est pas modifiée. Un snapshot conservé après
erreur ne compte pas comme décodage neuf. L'annulation est propagée après la
tentative de cleanup ; le rapport partiel reste disponible dans `report`.

| Critère | SUCCESS | Sinon |
| --- | --- | --- |
| collection | Six slots terminés dans la fenêtre | FAILURE si interrompu ; NOT RUN si aucun slot attesté |
| tls_reuse | Deux décodages consécutifs, même génération, séquence corrélée +1 | FAILURE si six slots insuffisants ; INCONCLUSIVE si interrompu ; NOT RUN sans slot |
| reconnection | Perte observée, cleanup attesté, nouvelle génération puis nouveau décodage corrélé | INCONCLUSIVE, notamment sans perte ; NOT RUN sans slot |
| cleanup | Close terminé, propriétaire arrêté, dernière génération nettoyée, aucun échec mémorisé | FAILURE |

L'issue globale est FAILURE si un critère échoue, NOT RUN si la collection n'est
pas attestée, SUCCESS seulement si tous réussissent, INCONCLUSIVE sinon.
L'absence de perte ne peut donc jamais produire un succès global de reconnexion.
Les pertes sont simulées uniquement dans ces tests ; un futur live C2 ne devra
induire ni perte, inhibition, timeout serveur ou CloseClient.

## Rapport fermé et limites

`scripts/ha_session_proof.py` projette explicitement les champs ; le validateur
indépendant `scripts/ha-session-proof.cjs` recalcule les quatre critères et
l'issue. Schéma 1, scénario `ha-persistent-c1`, **execution=offline**,
**system_enforcement=NOT RUN**, **boundary_proven=false** obligatoires.
Provenance SHA/PR/run/attempt fournie par la fixture, sans attestation GitHub.
C2 devra attester séparément la provenance réelle ; changer `offline` en `live`
est refusé. Les validateurs imposent types stricts, clés exactes, générations,
séquences et pertes/cleanup non régressifs ; JSON canonique sans doublons.
Les deux validateurs testent les rapports du vrai chemin HA, pas seulement des
objets de démonstration. Aucun brut, stdout/stderr, fichier privé ou mesure.

| Borne fixe C1 | Valeur |
| --- | --- |
| Fenêtre utile absolue | 300 s maximum |
| Futur superviseur externe, cleanup et kill/reaping compris | 360 s maximum |
| Cleanup coopératif du collecteur | 10 s réservées |
| Rafraîchissements / tentatives d'ouverture | 6 / 2 maximum |
| Connexion TLS / fermeture transport | 10 s / 5 s |
| Handshake / lecture / unique backoff B | 30 s / 30 s / 1 s |
| RX cumulé / enveloppe mémoire C2 | 1 Mio / 1 Gio |
| Rapport canonique / rétention future | 8192 octets / 7 jours maximum |

Deux connexions TLS/handshakes/fermetures + six lectures + un backoff
représentent 271 s d'I/O ; le
dernier slot sain finit avant 280 s. Une récupération tardive peut dépasser la
fenêtre : le cutoff absolu gagne, sans prolongation, nouvelle tentative ou replay.
`elapsed_ms` mesure la fenêtre utile, plafonnée à 300000, hors cleanup ; le
critère collection reste FAILURE si le cutoff interrompt les slots.
Les fixtures construisent le client avec les paramètres B ci-dessus.

**Les limites système ne sont pas appliquées par C1.** Les timeouts asyncio sont
coopératifs. RX/mémoire, arrêt des processus/descendants résistants et délai
total dur relèvent du superviseur externe C2. Aucun compteur RX artificiel ni
preuve de supervision réelle n'est publié ici. C2 devra appliquer ces plafonds,
installer ses dépendances hors secrets, attester l'admission `hoben-live`, la
revue/SHA/PR/CI, les approbations, l'anti-rejeu, le mutex et le recheck, puis
publier sur un runner isolé. Les quatre scénarios manuels existants et leurs
gates/budgets restent intacts. Main, workflow, environnement et live : NOT RUN.
