# #186-C — scénario Info hors ligne et contrat de résultat

Tâche `HOBEN-186-INFO-MANUAL-SCENARIO-OFFLINE-003`, base
`1689a47ed2731157e5f43fe76f2d64aa15daafd4`, consigne
[MANAGER #6713923452](https://github.com/Guillaume0385/ha-hoben-community/issues/186#issuecomment-6713923452).
Cette tranche prépare un contrat expérimental ; aucun lancement réel n'est
raccordé ni autorisé par ce document. Hoben/HA résidentiel : **NOT RUN**.
Le cleanup réel de #192 reste **non résolu**, `state:waiting`.

## Propriétaires et preuves

`scripts/info_delivery_scenario.py` observe un vrai `V4Session(PERSISTENT)` et
un journal scalaire lié à un transport mémoire explicitement injecté. Il ne
connecte pas, ne lit pas, n'écrit pas, ne lance pas de tâche et n'instancie pas
la capacité privée. Il n'a ni CLI, ni entrée réseau, ni horloge implicite.

Seule `tests/info_delivery_fixture_186.py` pilote le scénario : elle réutilise
la fixture `owner()` de #186-B, son faux transport `Stream`, les vecteurs
synthétiques indépendants de #186-A et l'horloge asyncio simulée. L'opt-in est
fourni exclusivement par cette fixture. Les wrappers enregistrent les tailles
des véritables retours de `Stream.read`, les TX terminées et le close terminé,
sans conserver ces octets dans le journal. Un unique RX de la vraie session
effectue le parsing, les Pong et la corrélation V4 ; le scénario n'ajoute aucun
reader concurrent. Aucune socket Hoben/HA n'est ouverte.

L'observateur compare le compteur effectif de drops de la capacité privée et
`verified_read_sequence` aux événements de la fixture. Il conserve l'identité
objet de session, transport et tâche RX en mémoire, sans la publier. Une
tentative d'ouverture supplémentaire est refusée : le test correspondant
injecte un événement contradictoire sans ouvrir réellement un second transport.
Une lecture en cache ou obtenue avant le dernier drop ne prouve pas une nouvelle
acquisition.

La séquence de succès exigée, après le **dernier** drop observé, est :

1. Ouverture acceptée par le chemin existant ; livraison synthétique commençant
   par `0x0C` effectivement jetée par l'opt-in de #186-B.
2. Livraison Ping distincte, puis écriture Pong achevée.
3. Nouvelle demande V4 lecture seule et TX achevée, puis incrément du témoin de
   décodage/corrélation réel de `V4Session`.
4. Même session/transport/RX, une seule ouverture et aucune reconnexion.
5. Cleanup final : `cleanup_succeeded`, session CLOSED, RX terminé, aucune TX
   active, aucun read du transport actif et close mémoire achevé exactement une
   fois. Un simple abort demandé ne suffit pas.

Le scénario ne prouve pas la sémantique wire d'Info. Le
[comparatif #186-A](tls-read-candidate-offline-186.md) et le
[prototype privé #186-B](info-delivery-drop-experiment-186.md) restent les sources
de ses limites. RE PR #4 est épinglée à
`e2f88b0dfcd130b9b9f9e52d69a900d8ded48b6e`.

## Rapport fermé

Les seules clés acceptées par `validate_report`/`encode_report` sont :

| Champs | Contrat |
| --- | --- |
| `schema`, `scenario`, `mode` | `1`, `info-delivery-0x0C`, `offline` |
| `experimental_hypothesis`, `boundary_proven`, `info_framing` | `true`, `false`, `INCONCLUSIVE`, invariants |
| `limits` | Constantes de fixture ci-dessous, types entiers stricts |
| `started`, `opened_validated`, `same_session` | Booléens issus des observations de la fixture/session |
| `openings`, `reconnections` | Tentatives d'ouverture du transport ; toute seconde tentative interdit SUCCESS |
| `info_discarded`, `info_delivery_bytes` | Drops observés et tailles des livraisons réellement retournées ; jamais tailles de message Info |
| `pings_after_drop`, `pongs_after_drop` | Comptages scalaires postérieurs au dernier drop |
| `requests_after_drop`, `reads_after_drop` | Demande neuve et lecture réellement décodée/corrélée, au plus une chacune |
| `steps` | Indices bornés `drop/ping/pong/request/read`, ou null ; ordre strict pour SUCCESS |
| `rx_reaped`, `cleanup_attested` | Fin du RX et conjonction des preuves de nettoyage |
| `first_error` | Première catégorie fermée, jamais texte d'exception |
| `elapsed_ms`, `collection_ms`, `cleanup_ms` | Durées monotones de la fixture, sans remise à zéro du budget |
| `result`, `reason` | Verdict recalculé et raison fermée ; verdict fourni incohérent refusé |

Les catégories sont `none`, `protocol`, `transport`, `authentication`, `internal`,
`timeout`, `cancelled`, `closed`, `cleanup_unproven`, `cleanup_timeout`, `clock`,
`budget`, `multiple_sessions`, `evidence_gap`. La raison peut aussi être
`not_started`, `info_absent`, `insufficient_evidence` ou
`post_drop_read_verified`. Aucun champ libre, sous-code Info, fingerprint,
identifiant, GUID, RX/header/payload, valeur de registre ou exception n'est
exporté. Le premier incident reste distinct du refus final de cleanup.

| Résultat | Condition |
| --- | --- |
| SUCCESS | Toute la chaîne réelle ci-dessus est prouvée, sans erreur et cleanup attesté |
| INCONCLUSIVE | Info absent, aucune erreur et cleanup attesté, même avec une V4 valide |
| FAILURE | Incident, preuve insuffisante/contradictoire, session supplémentaire ou cleanup non attesté |
| NOT RUN | Aucune tentative de connexion et aucun incident observé |

Un rapport hors schéma, hors bornes, portant un marqueur privé ou un verdict
falsifié est **rejeté**, jamais réparé en SUCCESS. Sans drop, les compteurs et
indices post-drop doivent être absents/nuls. Le validateur prouve la cohérence
d'un rapport, pas l'authenticité de données externes entièrement fabriquées :
les événements scalaires proviennent ici de la fixture de confiance. Ce contrat
ne constitue pas une attestation de superviseur live ou de provenance GitHub.

## Budgets de fixture et limites

| Limite | Valeur |
| --- | --- |
| Collecte | 30 s simulées, timeout absolu de la fixture |
| Nouvelle demande V4 | 5 s simulées ; les drops ne réarment pas ce délai |
| Cleanup | 5 s simulées réservées après collecte |
| Total | 35 s simulées ; garde de boucle finie à pas de 50 ms, rejet si aucune terminaison |
| Drops | 1..16 pour la capacité ; plafond cumulatif sans recharge après lecture |
| Journal | 128 événements scalaires maximum ; livraison 4096 octets maximum |
| Rapport | 8192 octets JSON UTF-8 maximum ; nombres/types/listes strictement bornés |

Le driver de test avance l'horloge et réape sa tâche en sortie. Un dépassement
ou une perte de preuve produit FAILURE ou un rejet fermé de rapport. Une petite
surélévation d'une durée de phase peut être représentée honnêtement dans les
35 s globales avec un incident ; aucun temps n'est tronqué pour valider un succès.
Ces limites ne sont **pas** un budget live ni un superviseur de processus.

Une livraison ReadAsync n'est pas une frontière applicative garantie. Le drop
abandonne **toute** la livraison ; Ping/0E concaténés sont perdus et ne sont pas
crédités. Un fragment Info isolé peut laisser un suffixe non classifiable et
échouer. Les tests exigent une nouvelle réponse corrélée, sans saut de deux
octets, scan de suffixe ou longueur Info inventée. `boundary_proven=false` et
Info framing INCONCLUSIVE restent vrais même pour le SUCCESS fonctionnel
**synthétique**. Le défaut-off HA reste inchangé ; aucune conclusion sur la
reprise cleanup résidentielle #192 n'est tirée de ce transport mémoire.

## Validation hors ligne

Le test RED initial montre qu'un rapport sans Info acceptait des compteurs
post-drop contradictoires. GREEN refuse cette contradiction ; le scénario
contrôlé et Info absent sont testés indépendamment. Les cas négatifs couvrent
fragment/concaténation, réponse spontanée ou corrélation incorrecte, MBAP,
EOF/TLS/auth, CloseClient, timeout non réarmé, annulation, close échoué/retardé,
plafonds, rollback d'horloge, valeurs privées et falsification du rapport.
Un second RED/GREEN vérifie qu'un recul d'horloge inférieur à 1 ms ne peut pas
être accepté par l'arrondi des durées du rapport.
Un troisième impose le cleanup même si l'observateur rejette sa propre preuve :
le défaut du rapport n'autorise jamais l'abandon de la ressource de fixture.

```sh
python -m pytest tests/test_info_delivery_scenario_186.py
python -m pytest tests/test_info_delivery_drop_186.py tests/test_tls_read_candidate_186.py
python -m pytest
python -m pytest -c ha_tests/pytest.ini ha_tests
python -m ruff check .
python -m ruff format --check .
```

La suite HA existante `ha_tests/test_tls_read_candidate_186.py` vérifie le vrai
client/coordinator par défaut-off. Les suites #192, B4/B7/B8 et DataUpdated font
partie des régressions complètes. CHANGELOG non modifié : aucun comportement
distribué ni entrée manuelle livrable n'est changé, uniquement ce banc offline.

## #186-D : raccordement futur, non implémenté

Après fusion de C, **MANAGER seul** prépare la prochaine tâche. La voie de
[Tests Hoben manuels](hoben-manual-workflow.md) nécessitera au minimum :

| Fichiers/dépendances futurs | Travail à préparer et prouver séparément |
| --- | --- |
| `.github/workflows/hoben-manual.yml` | Un choix manuel unique `info-delivery`, exclu de `all`, aucun déclenchement automatique |
| `.github/scripts/manual-hoben-gate.cjs` | Admission fermée du choix ; propriétaire, experimental protégé, SHA exact/PR fusionnée/revue/4 CI, tentative 1 et claim anti-rejeu |
| `scripts/manual_hoben_context.py` | Contexte strict du choix et provenance, jamais activation HA générique ou durée/destination libre |
| `scripts/launch_manual_hoben.py` | Superviseur parent, budget global dur, réserve cleanup et arrêt/réapage du groupe, limites de sortie |
| `scripts/run_manual_hoben.py` et futur adaptateur isolé | Raccordement explicitement autorisé de la capacité privée, une session/un RX ; jamais modèle fixture présenté comme attestation live |
| `.github/scripts/manual-hoben-report.cjs` | Projection/validation Node fermée, parité Python, preuve de provenance/supervision et aucun SUCCESS sans Info + acquisition post-drop même génération + cleanup |
| `tests/test_manual_hoben_runtime.py`, `tests/js/manual-hoben.test.cjs` et tests du futur adaptateur | Gates adversariaux, timeouts/annulation/reaping/cleanup, falsification et default refusal |

Préserver le mutex `hoben-read-only-observation`, les protections et approbations
réelles `hoben-experimental`, recheck post-approbation avant secrets, claim
consommé même après échec, attestations de SHA et CI, confidentialité et tous
les scénarios/budgets historiques. Le choix doit rester **refusé par défaut**
tant que gate, superviseur et rapport ne sont pas tous prouvés hors ligne.
Les limites et l'accès à une capacité privée pour ce seul worker devront être
arbitrés explicitement, pas déduits de la présence de ce module.

Aucun de ces fichiers de raccordement n'est modifié en C. Aucun workflow,
automation, fournisseur opt-in HA/config/lifecycle/campagne, CLI live ou accès
serveur n'est ajouté. MANAGER traite tout blocage avant D ; CODEX DEV ne se
l'attribue pas. Un éventuel lancement ultérieur demeure manuel par le
propriétaire avec les gates effectifs, jamais un test DEV/CI.
