# #186-D2 — modèle de supervision offline

Tâche `HOBEN-186-MANUAL-SUPERVISOR-OFFLINE-005`,
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/186#issuecomment-6713923452),
base `f173de8bb5d44f640d900dc142554dd98129fbe8`.
`scripts/info_delivery_supervisor.py` fournit une **politique pure** : horloge
entière en millisecondes et événements synthétiques explicitement injectés.
Il ne lance, signale, ferme ou réape aucun processus/transport, n'installe aucun
timer et n'active aucun fournisseur d'opt-in. Aucun chemin réseau/CLI/HA.

## Budget et transitions

| Borne fixe du modèle D2 | Valeur |
| --- | --- |
| Observation | 3 540 000 ms (59 min) |
| Réserve cleanup | 60 000 ms (1 min) |
| Plafond global | 3 600 000 ms (1 h), cleanup inclus |
| Journal d'appels | 64 entrées maximum ; la dernière est réservée au refus de budget |
| Rapport | 8192 octets JSON maximum |

La réserve de 60 s est un choix de ce modèle offline à relire par MANAGER ; elle
ne change aucun budget existant ni n'autorise le futur lancement réel.
Le compteur global démarre uniquement à `start()` : construire le modèle ou
attendre une admission fictive ne consomme pas cette fenêtre. L'origine absolue
de l'horloge n'est pas exportée. Les temps sont relatifs, entiers stricts et
bornés à l'entier sûr JSON ; horloge invalide, recul ou exception sont irréversibles.

```text
NEW --start--> OBSERVING --preuve SUCCESS / incident--> CLEANING
                  |                                     |
                  +--fin de fenêtre à 3540 s-------------+
                                                        |
                    confirmations fermeture + RX + worker --> STOPPED
                    timeout / preuve incomplète / clôture --> STOPPED (FAILURE)
```

Le délai cleanup est `min(début_cleanup + 60 s, 3600 s)`. Son début est figé dès
le premier arrêt demandé ; annulation répétée et incidents suivants ne le
réarment pas. Pour l'expiration normale de l'observation, il est **3540 s**, même
si `tick()` arrive en retard. Les égalités de deadline refusent toute preuve
tardive : confirmations avant le délai, jamais après/à 3600 s. Un dépassement
observé reste visible dans `elapsed_ms`, sans le tronquer à une heure.

Le modèle n'avance qu'aux appels explicites ; un caller qui ne l'appelle pas
n'est pas surveillé en temps réel. `tick()` n'attend ni ne boucle. Le plafond de
64 appels borne aussi les ticks : épuisement = FAILURE et intentions d'arrêt,
pas un timer relancé. Une fois STOPPED, la preuve reste figée ; aucun redémarrage
ou nouvelle génération n'est accepté. La publication ultérieure ne réarme rien.

## Preuves et résultats synthétiques

`observe(report)` prend une copie du rapport fermé
[#186-C](info-delivery-scenario-offline-186.md), validé par son vrai validateur
Python. Un rapport NOT RUN, malformé ou provenant d'un temps futur n'est pas une
preuve. Il n'est pas possible de remplacer un premier candidat par un second
pour masquer un incident. Les tests fournissent les vrais rapports de la fixture
C avec V4Session persistant et transport mémoire, sans ouvrir de socket.

- SUCCESS exige le résultat C valide (drop, Ping/Pong, demande neuve et lecture
  décodée/corrélée sur même session), puis trois confirmations **distinctes** :
  `transport_closed`, `rx_reaped`, `worker_reaped`, ce dernier après les deux autres.
- Info absent : le rapport C INCONCLUSIVE n'écourte pas la fenêtre ; après
  3540 s et cleanup confirmé, résultat INCONCLUSIVE. Une preuve absente donne
  FAILURE, pas « Info absent ».
- `cancel`, `worker_failed`, `cleanup_failed`, horloge défaillante et preuves
  incomplètes donnent FAILURE. La première cause est conservée séparément de
  `stop_reason` (par exemple worker_failed puis cleanup_timeout). Un cleanup
  défaillant dans C ne peut pas être réparé par des confirmations positives.
- Avant démarrage : NOT RUN ; annulation avant démarrage ou horloge initiale
  invalide : FAILURE, sans prétendre qu'un worker ou un RX a existé.

Les champs `stop_requested`, `abort_requested`, `reap_requested` sont uniquement
des **intentions scalaires**. `worker_reaped` et `cleanup_attested` décrivent les
confirmations du modèle, jamais un waitpid/close TLS réel. Ni abort demandé ni
simple fin du délai n'attestent le nettoyage. Un worker réapé avant la preuve de
fermeture/RX est refusé ; le modèle s'arrête avec cleanup non prouvé.

Le rapport porte `mode=offline`, `proof_scope=synthetic_events`,
`live_provenance=not_proven`, Info framing INCONCLUSIVE et `boundary_proven=false`.
Clés/types/valeurs sont fermés : constantes/bornes, phase STOPPED, journal
`event/at_ms`, rapport C fermé ou null, temps relatifs, catégories fermées,
intentions et confirmations booléennes, résultat et raison. Son validateur
**rejoue le journal** et compare toutes les projections : verdict, délais,
confirmations ou observation altérés sont rejetés. Erreur unique expurgée :
`invalid_offline_info_supervision`. Aucun texte d'exception, RX, GUID, valeur
domestique ou identité n'est retenu. L'épuisement de journal produit une entrée
finale `event_budget`, sans gonfler le rapport ni oublier la preuve manquante.

## Limites et validation

Un journal entièrement fabriqué peut imiter une simulation cohérente : ce
contrat **n'authentifie pas** ses événements. Le refus live de
[D1](info-delivery-manual-report-186.md) reste inconditionnel et inchangé, y
compris pour un rapport D2 synthétique réussi. Aucune isolation de processus,
supervision indépendante, admission, approbation ou fermeture réelle n'est
prouvée ici. Le futur worker devra traduire ses résultats/annulations en événements
et démontrer ces garanties dans une tâche MANAGER séparée ; pas de réutilisation
des événements synthétiques comme attestation live.

Tests offline : frontières 3540/3600 s et réserve anticipée, polls tardifs,
annulations, erreurs de clock, preuves manquantes/dupliquées/futures, échec de
cleanup C, ordre/omission des confirmations, anti-boucle et falsification de
rapport ; régressions A/B/C/D1 et suite HA. `pytest` et Ruff requis, quatre CI
sur HEAD exact avant remise à MANAGER. CHANGELOG non modifié : modèle/tests
offline non raccordés, aucun comportement distribué ou lancement actif changé.

Test réel NOT RUN ; lancement manuel pas encore prêt. Le collect à 50 min,
gates/anti-rejeu/mutex/approbations et raccordement restent à la suite autorisée
par MANAGER. Aucun workflow, launcher, HA, TLS ou ancien budget modifié. #192
cleanup S1/S2 et V1–V6 demeure non résolu. CODEX ne prépare ni ne s'attribue D3.
