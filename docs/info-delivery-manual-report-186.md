# #186-D1 — contrat Node offline, aucune provenance live

Tâche `HOBEN-186-MANUAL-REPORT-OFFLINE-004`,
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/186#issuecomment-6713923452),
base `e97b236e38db2e5550a8587bea08fe491ae1cd33`.
Le [rapport #186-C](info-delivery-scenario-offline-186.md) reste la source du
schéma 1 : champs scalaires fermés, tailles de **livraisons**, compteurs bornés,
Info framing **INCONCLUSIVE**, `boundary_proven=false`. Aucun RX, GUID,
identifiant privé, valeur domestique, sous-code Info ou exception libre.

`.github/scripts/info-delivery-manual-report.cjs` est un module pur, non raccordé.
Il ne lit ni environnement ni fichier, n'importe aucun runtime/gate et ne réalise
aucune I/O, activation, connexion, requête ou publication. Son API est :

| Fonction | Garantie et limite |
| --- | --- |
| `validateOffline(report)` | Vérifie intégralement le schéma C et recalcule le verdict ; retourne une copie détachée avec `mode=offline` |
| `parseOffline(stringOrBuffer)` | Au plus 8192 octets UTF-8 valides ; JSON compact sans clés dupliquées ni encodages ambigus, puis même validation |
| `validateForLivePublication(...)` | Refus **inconditionnel** `info_live_provenance_not_proven`, quels que soient rapport, drapeaux ou attestation fournis |

Les rejets offline utilisent seulement `invalid_offline_info_report`, sans
reprendre la donnée reçue ni la cause d'une exception. Les clés invisibles,
symboles, accesseurs, objets à prototype personnalisé, champs `toJSON` et tableaux
troués sont refusés avant sérialisation. `parseOffline` accepte la sortie compacte
de `scripts/info_delivery_scenario.py::encode_report` ; espaces supplémentaires,
doublons, nombres réencodés et suffixes sont rejetés. Il s'agit d'un format de
transport volontairement plus strict que la validation d'un dictionnaire Python.

Verdicts C conservés : **SUCCESS synthétique** seulement après le dernier drop
effectif, Ping/Pong, demande neuve puis acquisition V4 décodée/corrélée dans la
même session, sans reconnexion et avec cleanup attesté. Sans Info, **INCONCLUSIVE**
si les autres garanties tiennent ; un incident ou cleanup non prouvé reste
**FAILURE**. Aucun démarrage/incident donne **NOT RUN**. La première cause reste
distincte de l'échec final de cleanup. Une chronologie insuffisante peut décrire
un échec fidèle ; elle ne peut pas être requalifiée en succès. Les budgets de
fixture C (30 s collecte + 5 s cleanup, 16 drops, 128 événements) sont inchangés.
Le lecteur Node refuse aussi toute revendication de drop, RX réapé ou cleanup
sans démarrage : un NOT RUN contradictoire n'est pas une preuve admissible.
Ce durcissement de lecture ne modifie pas le producteur Python C.

**Authentification/provenance/supervision live : NON PROUVÉES.** Un schéma
cohérent n'authentifie pas son émetteur ; un rapport entièrement fabriqué peut
imiter une fixture. Aucun champ de ce schéma ne vaut preuve de worker réel,
de gate, d'approbation, de réapage de processus ou d'observation réseau. Même
un SUCCESS offline valide est refusé par l'API de publication live. Changer
`mode`, ajouter une attestation, ou remplacer les budgets par une heure ne
constitue jamais une voie d'admission. Aucun export/publish live n'existe ici.

Validation : 171 tests Node adversariaux, dont trois RED/GREEN sur NOT RUN,
exécution de cette suite par pytest
dans la CI existante, comparaison Python/Node de 20 rapports issus du vrai
V4Session sur transport mémoire et de rapports altérés ; régressions #186-A/B/C,
#192 et B4/B7/B8/DataUpdated. Les tests VM exécutent le module avec I/O et accès
environnement interdits. Commandes hors ligne :

```sh
node tests/js/info-delivery-manual-report.test.cjs
python -m pytest tests/test_info_delivery_manual_report_186.py
python -m pytest tests/test_tls_read_candidate_186.py tests/test_info_delivery_drop_186.py tests/test_info_delivery_scenario_186.py
python -m ruff check .
python -m ruff format --check .
```

MANAGER seul prépare la suite D2/D3. Le futur essai reste une **observation
passive réelle**, déclenchée manuellement par le propriétaire après gates et
approbations : 3600 s maximum **cleanup réservé inclus**, attente d'un Info réel,
absence d'Info INCONCLUSIVE. La limite `collect: timeout-minutes: 50` actuelle
devra être traitée spécifiquement dans une tâche ultérieure, avec supervision
indépendante et preuve d'origine ; aucun budget historique ne doit être élargi.
Aucun workflow/gate/claim/runtime/HA/campagne n'est modifié par D1. Test réel
**NOT RUN**, lancement manuel **pas encore prêt**, cleanup #192 non résolu.
CHANGELOG non modifié : contrat et tests offline uniquement, sans changement
livrable du plugin ni du chemin de lancement/publication manuel existant.
