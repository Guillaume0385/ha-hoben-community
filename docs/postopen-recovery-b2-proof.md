# B2 — parcours post-open déjà passant, défaut non reproduit

[Consigne MANAGER B2](https://github.com/Guillaume0385/ha-hoben-community/issues/163#issuecomment-6549962264),
`HOBEN-163-B2-POSTOPEN-RECOVERY-004`. Code de production examiné et testé :
`12f70d77c20f3f2fab80fa4caef5980d21afff39`, HEAD experimental intégrant A1/A2/B1.
La branche de preuve ne modifie aucun fichier de production : seulement ce
rapport et `ha_tests/test_postopen_recovery_b2.py`. Aucune correction proposée,
aucune PR ouverte, aucun retry ajouté. Les causes historiques restent inconnues.

## Chemin suivi

| Fonction au SHA de base | Fait local |
| --- | --- |
| `V4Session._receive_experimental` (v4_session.py:1271) | CloseClient complet sous contrat existant → ExperimentalCloseClientError. Sous-code 3 = stove_connection_required, phase post_open ; ni EOF ni exclusivité serveur déduite. |
| `V4Session._receive_unproven_handoff`, `_request_v4_data` | Le waiter de lecture échoue ; un seul propriétaire RX et cleanup du transport courant, sans consommer le suffixe comme prochaine génération. |
| `V4Lifecycle._run` (v4_lifecycle.py:736) | Classement post-open, retrait de la génération, état reconnecting. Authentification permanente exclue. Nettoyage vérifié avant toute nouvelle tentative. |
| Même fonction (v4_lifecycle.py:827 puis :854) | Cleanup non confirmé interdit la reprise ; politique HA existante demande 60 s. Pas de second superviseur ni de reset de budget de campagne. |
| `HobenClient._refresh_once` (client.py:436) | Lifecycle créé une seule fois, wait_connected pour les appels suivants ; nouvelle acquisition acceptée seulement après réponse corrélée au witness de la nouvelle génération. |
| `HobenDataUpdateCoordinator._async_update_data`, `_async_update_once` | Même snapshot conservé en mémoire et date inchangée pendant l'échec ; polls d'attente sans nouvelle I/O. Une ouverture seule ne vaut jamais succès d'acquisition. |
| `async_setup_entry` (__init__.py:65) | Premier refresh échoué transitoirement : même client/coordinator en attente. Aucune entité avant première acquisition validée. |
| `SessionMonitor`, capteur A2 | Reconnecting durant backoff, connected à l'acceptation utilisable ; compteur de reconnexions incrémenté une fois, fraîcheur séparée. Phases B1 conservées. |

## Résultat de la tentative de reproduction

Les **13 nouveaux cas passent sans modification de production** sur le socle :

- Refresh après snapshot valide : 05 03 complet, fragmenté ou suivi d'une
  réponse/Ping dans le même suffixe ; 05 06 post-open ; EOF. Dans chacun des
  cinq cas : ancien transport fermé une fois, waiter/RX/TX nettoyés, une seule
  instance de lifecycle, pas d'ouverture à 59 s ; seconde session après les
  60 s demandées par le backoff. Pas de replay, ni traitement du vieux suffixe.
- Le capteur passe reconnecting → connected, compteur 0 → 1, mais snapshot,
  date et last_update_success ne deviennent frais qu'après la nouvelle lecture
  V4 corrélée. La nouvelle identité acceptée est persistée. Une lecture suivante
  réutilise cette seconde session ; unload puis temps virtuel supplémentaire
  ne créent aucune reconnexion ni fuite de tâche.
- Setup : 05 03 ou 05 06 durant la première lecture post-open, maintenance
  05 06 avant ouverture. Le même propriétaire attend et reprend après 60 s,
  puis les entités apparaissent seulement après lecture valide.
- Arrêt pendant backoff 05 03 : aucune réouverture tardive. Refus au setup
  05 03 avant acceptation, auth 05 02, certificat refusé ou profil inconnu :
  pas de retry. Ces contextes ne sont pas confondus avec 05 03 post-open.

Disponibilité : le contrat livré retire la disponibilité après une fermeture
de session/EOF jusqu'à une nouvelle acquisition, tout en gardant le snapshot en
mémoire. Les maintiens A1 pour protocole/timeout/modèle et DataUpdated restent
vérifiés par leurs tests existants. Le test ne transforme pas une exigence de
conservation en nouvelle politique d'affichage et ne présente pas cet arrêt de
disponibilité documenté comme une panne de reconnexion.

L'horloge et les transports sont synthétiques. Sous horloge UTC figée, une
première assertion imposant une exécution exactement à 60.000 s rencontrait la
précision flottante d'asyncio : le timer était à échéance, encore en file.
L'observation à 60.001 s respecte le minimum 60 s et passe sans toucher au
runtime. Cet échec du test n'est pas une preuve rouge d'un défaut de production.

Validation : 13 nouveaux cas HA et 392 tests unitaires ciblés PASS ; suite HA
complète **535 PASS**, Ruff check/format PASS (236 fichiers). Elle couvre aussi
les permanentes post-open, cleanup échoué, A1/A2/B1 et
DataUpdated invalide : même TLS, silence glissant 30 s, sonde unique, aucun faux
rafraîchissement. Aucun scénario C à trois cycles ni observation D développé.

Limite du diagnostic existant : un poll pendant l'attente peut produire
transport_unavailable dans last_error du coordinator, tandis que le capteur A2
conserve la catégorie/phase de l'erreur source. Ces projections n'ont pas la
même portée temporelle ; cela n'empêche pas la reprise observée. Le rapport ne
revendique pas un historique identique entre les deux ni une cause distante.

## Blocage de preuve, sans correction spéculative

Le test rouge exigé pour modifier la reprise ne peut pas être fourni avec les
scénarios examinés : ils passent déjà. Cela ne prouve pas l'absence de tout bug
ni la stabilité réelle du service. Tests réels **NOT RUN**. Les quatre CI d'une
nouvelle PR ne sont pas exécutées puisqu'aucune PR n'est créée ; ne pas attribuer
la CI passée de B1 à la branche de preuve.

Selon le point 4 de la consigne B2 : documenter les preuves, passer #163 de
state:in-progress à state:blocked et attendre MANAGER. Il faut un scénario local
manquant/reproductible, avec version réellement chargée et contexte expurgé,
ou une décision explicite sur le périmètre/suite de B2. Aucun test réel autorisé
par cette demande de preuve ; aucune nouvelle priorité auto-attribuée.
#126 reste waiting : seul MANAGER peut actualiser sa consigne canonique et
l'activer après arbitrage. Aucun label de #126 ni automatisation modifié.
