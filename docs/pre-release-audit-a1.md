# Audit pré-release A1 — workflows et scripts

Audit documentaire du 05/11/2026, tâche
`HOBEN-189-A1-WORKFLOW-SCRIPTS-AUDIT-001`, selon la
[consigne MANAGER #6670244564](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-6670244564).
**Aucune suppression ni modification de comportement n'est autorisée par ce document.**
Les propositions B/C/D ci-dessous nécessitent une tâche distincte de MANAGER.

## Périmètre et faits vérifiés

- Arbre audité : `experimental` au SHA
  `c81b79643485e8b148695c6e4fc0e2a9a50f2a87`, après fusion de R5/#188.
- Comparaison de branche : `main` au SHA
  `1ec61b40615b481fe5da1b6e2b2c7590b4ff86e3`. Les conclusions sur main portent
  sur ce snapshot, pas sur une promotion future.
- Cinq workflows installés ; **88 fichiers** sous `scripts/` et `.github/scripts/`
  inventoriés ci-dessous, plus leurs supports, tests et références documentaires.
  Ce n'est pas l'audit exhaustif de chaque fonction du plugin prévu par les lots futurs.
- Les cinq documents obligatoires de cette base sont identiques aux versions déjà
  lues intégralement : AGENTS.md, project.md, protocol.md,
  docs/experimental-protocol-workflow.md, docs/manager-dev-workflow.md.
- Au démarrage : #189 ready et attribuée à CODEX_DEV ; aucune PR ouverte ni tâche
  in-progress concurrente. #126 porte encore review, mais R5 est explicitement
  DONE dans [#6667089990](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6667089990)
  et #188 est fusionnée. #163 et #186 restent waiting ; aucune réactivation.

| Preuve GitHub existante, consultée en lecture seule | Conclusion permise |
| --- | --- |
| [PR #188](https://github.com/Guillaume0385/ha-hoben-community/pull/188), candidat `a3987798741ef96e7bda4cb61f6162338d67acff` ; [Validate #42085559065](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/42085559065) | Quatre CI SUCCESS sur **ce candidat** : tests 8945, ha-tests 792, hacs, hassfest. Ce n'est pas une nouvelle CI au SHA de fusion ni une validation live. |
| [HA #42112267116](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/42112267116), SHA audité | admission SUCCESS, collect SUCCESS, result FAILURE, run FAILURE. Une collecte réussie ne valide pas le rapport ni la stabilité. Cause fonctionnelle non déterminée par cet audit. |
| [Protocole #42112360198](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/42112360198), même SHA | admission, collect, result et run SUCCESS. Ne compense pas le FAIL HA et ne prouve pas une frontière universelle OpenedClient. |

Ces deux runs ont été lancés antérieurement par le propriétaire. Tests réels A1 :
**NOT RUN** ; aucun dispatch/rerun ni accès Hoben/HA résidentiel. La promotion main,
le changement de version, le tag et la release restent **non autorisés**.

## Méthode et reproductibilité

Lecture des cinq YAML complets, de leurs commandes/JavaScript embarqué, des imports
Python/Node et des points d'entrée référencés. L'analyse AST relève aussi les
imports locaux à une fonction ; la recherche textuelle complète les appels
conditionnels, subprocess, imports dynamiques, listes de copie et références
docs/tests. L'analyse du graphe n'importe ni n'exécute le code audité ; les tests
existants utilisent leurs doubles hors ligne. Aucun lancement réel de collecteur.

Commandes de vérification depuis un checkout de la base, sans donnée privée :

```sh
git rev-parse HEAD
git ls-tree -r --name-only c81b79643485e8b148695c6e4fc0e2a9a50f2a87 .github/workflows scripts .github/scripts
rg -n 'run:|require|environment:|permissions:|concurrency:|timeout-minutes:' .github/workflows
rg -n 'from scripts|import scripts|import_module|SourceBundle|subprocess|session_suite_v3_contract' scripts .github/scripts
rg -n 'scripts/|scripts\.|hoben-manual|publish-release' tests ha_tests docs README.md custom_components
git ls-tree -r --name-only 1ec61b40615b481fe5da1b6e2b2c7590b4ff86e3 .github/workflows scripts .github/scripts
git show 1ec61b40615b481fe5da1b6e2b2c7590b4ff86e3:.github/workflows/hoben-ha-manual.yml
git show 1ec61b40615b481fe5da1b6e2b2c7590b4ff86e3:.github/workflows/hoben-protocol-manual.yml
git diff --stat 1ec61b40615b481fe5da1b6e2b2c7590b4ff86e3 c81b79643485e8b148695c6e4fc0e2a9a50f2a87 -- .github scripts
```

Une référence dans un plan, une fixture ou une doc n'est pas un appel live. Une
fermeture transitive de tous les imports conditionnels surestime volontairement
les chemins exécutés : le même parent sélectionne HA **ou** protocole ; les listes
de fichiers SourceBundle ne signifient pas que toutes les fonctions sont appelées.
Inversement, zéro occurrence/import entrant ne prouve pas qu'un fichier est mort.
L'audit ne prouve pas l'absence d'utilisateurs externes, de commandes locales ou
d'anciens artefacts. Il ne lit aucun secret ni réglage privé d'environnement.

## Décision par workflow

| Workflow | Entrées et consommateurs vérifiés | Garanties et limites | Décision A1 / régressions |
| --- | --- | --- | --- |
| [validate.yml](../.github/workflows/validate.yml) | push main/chore/**, toute PR, dispatch et cron hebdomadaire ; pytest tests + Ruff, pytest HA séparé, HACS et hassfest | permissions globales vides, contents:read par job ; Python 3.12/dev et 3.14/ha-test selon [pyproject.toml](../pyproject.toml). Pas de campagne Hoben réelle. | **Conserver** les quatre checks. CI consomme scripts et fixtures même lorsqu'aucun YAML manuel ne les appelle. |
| [hoben-ha-manual.yml](../.github/workflows/hoben-ha-manual.yml) | dispatch propriétaire ; `run_campaign.py ha`, image HA, `campaign-report.cjs prepare/publish` | admission sans secret, collect sous hoben-live, checkout github.sha ; sept scénarios de all et option dual séparée ; pas de CI/PR/merge exigée à l'admission moderne | **Conserver** ; T1/T3. Ne pas retirer un helper de rapport ou de confinement sous prétexte d'absence d'appel YAML direct. |
| [hoben-protocol-manual.yml](../.github/workflows/hoben-protocol-manual.yml) | dispatch propriétaire ; `run_campaign.py protocol`, même publication indépendante | hoben-experimental ; six scénarios + all, bornes propres ; V4 lecture seule, hypothèses H1/H2 conservées | **Conserver** ; T1/T2. Le succès expérimental ne vaut pas validation HA/release. |
| [publish-release.yml](../.github/workflows/publish-release.yml) | dispatch sur main ; JavaScript embarqué utilisant l'API GitHub, manifest et CHANGELOG ; aucun script Python/Node externe | acteur/sender/triggering_actor propriétaire, tentative 1, confirmation RELEASE, main exact, version et notes, tag réservé atomiquement, draft vérifié avant publication | **Conserver** ; T7. Ce gate ne réalise pas de test HA/live et ne remplace pas l'autorisation de promotion. |
| [hoben-manual.yml](../.github/workflows/hoben-manual.yml) | dispatch historique, main explicitement refusée ; gates/recheck, collecteurs protocolaires et voie hoben-live distincte | contents:write au preflight pour claim, preuve PR/CI, politique/approbation effective, tentative 1 ; même mutex que les campagnes modernes | **Suspect / candidat à retirer après validation**, pas supprimable en A1 : README, main, helpers, tests et contrats encore consommateurs. T4/T5. Équivalence complète non démontrée. |

Les deux campagnes modernes vérifient repo, acteur **et** triggering_actor, événement
workflow_dispatch, sélection fermée et ref experimental/main. Elles permettent les
reruns natifs ; ne pas leur reconnecter silencieusement les anciennes gates PR/CI,
claims ou tentative unique. Leur mutex, comme celui de la voie historique, est
`hoben-read-only-observation`, `cancel-in-progress: false`, `queue: max`.

Le YAML déclare `environment: hoben-live` / `hoben-experimental`. La présence de ce
champ ne prouve pas que les règles natives et approbateurs sont effectivement
configurés ; leur validation reste à MANAGER. Les anciens helpers vérifient aussi
la politique et l'approbation via API ; aucune règle native n'est modifiée ici.

## Chaînes exécutables et dépendances indirectes

| Racine | Chaîne / points d'entrée vérifiables | Motif de conservation |
| --- | --- | --- |
| Campagnes modernes | [run_campaign.py:execute/run](../scripts/run_campaign.py#L80) → subprocess `python -I campaign_worker.py` → [campaign_worker.py:main](../scripts/campaign_worker.py#L14) | Identité par pipe, READY/ACK après armement de deadline, stdout/stderr privés supprimés, arrêt/réapage et répertoire privé supprimé avant retour. |
| Protocole | [protocol_campaign_collect.py:collect/h1h2](../scripts/protocol_campaign_collect.py#L51) → `boundary_capture.run_campaign` pour H1/H2 ; `run_session_300.observe` et `session_suite._observe_reconnect` pour les sessions ; vrais V4Lifecycle/V4Session/NoPongAfter120 | Même moteur partagé ; conserver analyses/timelines et parsers des schémas historiques, pas seulement les lanceurs YAML. |
| HA | [ha_session_supervisor.py:SourceBundle](../scripts/ha_session_supervisor.py#L91) et `supervise_campaign` → Docker → [ha_session_guard.py:run](../scripts/ha_session_guard.py#L110) → choix du fichier worker → [ha_campaign_worker.py:main](../scripts/ha_campaign_worker.py#L14) → `ha_session_live_worker.collect` → `ha_campaign_observer.observe` | Copie explicite de modules **sans import direct par le host**, manifest et glob des modules du plugin. Worker HA non privilégié ; vrai HobenClient/coordinator. Retirer un fichier de la liste peut casser le conteneur seulement à l'exécution. |
| Preuve HA | `ha_campaign_evidence` → `ha_live_proof` / `ha_session_evidence`, HA-F1 et R5 ; imports conditionnels dual ; `ha_session_observer` pour hoben-live | Les noms/docstrings « inactive » et « offline » décrivent certaines enveloppes, pas l'inutilité des validateurs réutilisés. Le snapshot B7 disponible ne doit pas devenir une lecture fraîche. |
| Publication moderne | [campaign-report.cjs](../.github/scripts/campaign-report.cjs#L4) → `scripts/ha-session-evidence.cjs`, `ha-live-proof.cjs`, `ha-incident-evidence.cjs`, `ha-reconnect-proof.cjs`, dual conditionnel, `experimental-report-file.cjs` | Node revalide indépendamment Python, la provenance et les statuts avant sorties/artefact. Deux langages ne sont pas des doublons à fusionner en une seule source de verdict. |
| Manuel historique, gate | [manual-hoben-gate.cjs:verify](../.github/scripts/manual-hoben-gate.cjs#L70) → exports de `experimental-lab-gate` / `experimental-live-gate` → push-preflight/native-rerun + JSON de politique | Des helpers nommés d'après des workflows retirés sont encore réellement appelés. `verify` relit PR/CI, réserve un claim puis vérifie à nouveau avant secret. |
| Manuel historique, protocole | `launch_manual_hoben.supervise` → subprocess `run_manual_hoben.py` → `run_experimental_boundary.collect`, `run_session_300.observe`, `session_suite.observe_suite/_observe_reconnect` ; exports via `manual-hoben-report.cjs` → experimental-exports/session-300-report/session-suite-report → session-suite-v3 conditionnel | Couverture commune aux campagnes modernes, mais enveloppes, all et résultat H1/H2 distincts. JSON v3 et anciens lecteurs restent des dépendances de compatibilité. |
| Import dynamique avéré | [run_experimental_boundary.py:collect](../scripts/run_experimental_boundary.py#L447) fait `importlib.import_module("scripts.probe_opened_client_boundary")` → boundary_capture et boundary_archive | L'absence de `from ... import` aurait donné un faux orphelin. La voie manuelle appelle cette bibliothèque même si son ancien workflow autonome a disparu. |
| Manuel historique, HA | `launch_ha_manual_live` → `ha_manual_live_report` + `ha_session_supervisor.supervise_live` → même guardian et worker HA, puis baseline observer ; `ha-manual-live-report.cjs` → `ha-live-proof.cjs` | Socle partagé, contrat C2b lié à une identité persistée et aux preuves PR/CI/claim. Ce n'est pas le même mode d'admission que #126. |
| CI / chargements indirects | Tests Python lancent Node, notamment [test_ha_session_proof.py](../tests/test_ha_session_proof.py#L85) → `ha-session-proof.cjs` ; tests/fixtures/ha_session_worker.py via guardian ; `tests/experimental_simulated_server.py` charge une entrée par spec_from_file_location | Une simple fermeture des imports Python manquerait ces consommateurs. Les fixtures simulent transport/API/horloge, sans autoriser des tests réels. |

`campaign_runtime_contract.py` importe réellement `CHOICES` depuis les anciens
`ha_campaign_plan.py` et `protocol_campaign_plan.py`. Leurs références textuelles
à une sonde ou à `session_natural_900.py` ne signifient pas qu'elles sont exécutées ;
en revanche, supprimer les modules de plan casserait le catalogue courant.

## Inventaire par fichier et couverture

**K = conserver**, dépendance active/partagée ou preuve de compatibilité utile.
**C = à confirmer**, candidat à analyse ultérieure, **conservé en attendant**.
Aucun C ne signifie « code mort prouvé ». La colonne main indique seulement la
présence au SHA comparé, jamais identité de contenu, activation ni preuve live.
Les tests cités par famille sont des exemples de consommateurs/régressions ;
leur présence ne prouve pas à elle seule une couverture exhaustive.

### Node : rapports courants et utilitaire partagé

| Fichier | État | Consommateur / raison vérifiable | Tests | main |
| --- | --- | --- | --- | --- |
| [campaign-report.cjs](../.github/scripts/campaign-report.cjs) | K | HA/protocole YAML ; prepare, publish et validateStage | T1/T3 | absent |
| [experimental-report-file.cjs](../.github/scripts/experimental-report-file.cjs) | K | campagne et anciens exports ; lecture sûre de fichier | T1/T4/T5 | présent |
| [ha-dual-evidence.cjs](../.github/scripts/ha-dual-evidence.cjs) | K | require conditionnel de campaign-report ; option hors all | T1/T3 | absent |
| [ha-incident-evidence.cjs](../.github/scripts/ha-incident-evidence.cjs) | K | campaign-report et dual ; preuve HA-F1 | T3 | absent |
| [ha-reconnect-proof.cjs](../.github/scripts/ha-reconnect-proof.cjs) | K | campaign-report ; preuve R5 par génération | T3 | absent |

### Node : voie manuelle historique encore installée

| Fichier | État | Consommateur / raison vérifiable | Tests | main |
| --- | --- | --- | --- | --- |
| [manual-hoben-gate.cjs](../.github/scripts/manual-hoben-gate.cjs) | K | hoben-manual preflight/recheck ; verify | T4 | présent |
| [manual-hoben-report.cjs](../.github/scripts/manual-hoben-report.cjs) | K | hoben-manual prepare/publish/result ; enveloppe H1/sessions | T4 | présent |
| [ha-manual-live-report.cjs](../.github/scripts/ha-manual-live-report.cjs) | K | hoben-manual exports/result HA ; contrat C2b | T4 | présent |
| [experimental-lab-gate.cjs](../.github/scripts/experimental-lab-gate.cjs) | K | manual-hoben-gate importe ses helpers CI/environnement | T4/T5 | présent |
| [experimental-live-gate.cjs](../.github/scripts/experimental-live-gate.cjs) | K | manual-hoben-gate ; politique/approbation hoben-live | T4/T5 | présent |
| [experimental-push-preflight.cjs](../.github/scripts/experimental-push-preflight.cjs) | K | require des deux gates ; son nom ne prouve pas un abandon | T4/T5 | présent |
| [experimental-native-rerun.cjs](../.github/scripts/experimental-native-rerun.cjs) | K | gates lab/live/session-300 ; preuves et refus historiques | T4/T5 | présent |
| [experimental-exports.cjs](../.github/scripts/experimental-exports.cjs) | K | manual-hoben-report ; validation H1/H2 | T4/T5 | présent |
| [experimental-timeline.cjs](../.github/scripts/experimental-timeline.cjs) | K | experimental-exports ; allowlist de timeline | T2/T4 | présent |
| [session-300-report.cjs](../.github/scripts/session-300-report.cjs) | K | manual-hoben-report et session-suite-report | T2/T4 | présent |
| [session-suite-report.cjs](../.github/scripts/session-suite-report.cjs) | K | manual-hoben-report ; schémas/états de session | T2/T4 | présent |
| [session-suite-v3.cjs](../.github/scripts/session-suite-v3.cjs) | K | require conditionnel schema 3 dans session-suite-report | T2 | présent |

### Node : anciens canaux, tests et compatibilité à examiner

| Fichier | État | Consommateur / raison vérifiable | Tests | main |
| --- | --- | --- | --- | --- |
| [experimental-ciphertext.cjs](../.github/scripts/experimental-ciphertext.cjs) | C | tests crypto/ancien canal ; pas de racine dans les cinq YAML | T5 | présent |
| [experimental-handoff-check.cjs](../.github/scripts/experimental-handoff-check.cjs) | C | tests/js et ancienne définition en fixture | T5 | présent |
| [experimental-live-report.cjs](../.github/scripts/experimental-live-report.cjs) | C | tests de l’ancien rapport live ; artefacts historiques | T5 | présent |
| [opened-client-boundary-gate.cjs](../.github/scripts/opened-client-boundary-gate.cjs) | C | fixture retirée opened-client-boundary et tests de gate | T5 | présent |
| [session-300-gate.cjs](../.github/scripts/session-300-gate.cjs) | C | session-suite-gate, tests et workflow retiré | T5 | présent |
| [session-suite-contract.cjs](../.github/scripts/session-suite-contract.cjs) | C | require de session-300-gate/session-suite-gate | T5 | présent |
| [session-suite-gate.cjs](../.github/scripts/session-suite-gate.cjs) | C | tests et ancienne voie hoben-session-300 | T5 | présent |

### Python : orchestration moderne et catalogues

| Fichier | État | Consommateur / raison vérifiable | Tests | main |
| --- | --- | --- | --- | --- |
| [run_campaign.py](../scripts/run_campaign.py) | K | deux YAML modernes ; context/execute/run/main | T1 | absent |
| [campaign_worker.py](../scripts/campaign_worker.py) | K | subprocess de run_campaign.execute ; ACK puis sélection | T1 | absent |
| [campaign_runtime_contract.py](../scripts/campaign_runtime_contract.py) | K | parents/workers/projecteurs ; budgets/verdicts/continuation | T1 | absent |
| [protocol_campaign_collect.py](../scripts/protocol_campaign_collect.py) | K | campaign_worker branche protocol ; collect/h1h2 | T2 | absent |
| [ha_campaign_plan.py](../scripts/ha_campaign_plan.py) | K | CHOICES/OPTIONAL_CHOICES importés par runtime_contract | T1/T6 | absent |
| [protocol_campaign_plan.py](../scripts/protocol_campaign_plan.py) | K | CHOICES importé par runtime_contract ; autres références inertes | T1/T6 | absent |

### Python : véritable chemin HA, supervision et preuves

| Fichier | État | Consommateur / raison vérifiable | Tests | main |
| --- | --- | --- | --- | --- |
| [ha_session_supervisor.py](../scripts/ha_session_supervisor.py) | K | campaign_worker et launch_ha_manual_live ; SourceBundle/Engine | T3/T4 | présent |
| [ha_session_guard.py](../scripts/ha_session_guard.py) | K | Entrypoint Docker, copie de bundle ; sélection du worker | T3 | présent |
| [ha_campaign_worker.py](../scripts/ha_campaign_worker.py) | K | fichier choisi par guardian ; observe/collect réels | T3 | absent |
| [ha_session_live_worker.py](../scripts/ha_session_live_worker.py) | K | collect appelé par ha_campaign_worker et ancien worker C2b | T3/T4 | présent |
| [ha_campaign_observer.py](../scripts/ha_campaign_observer.py) | K | ha_campaign_worker ; dispatch des scénarios et Recorder | T3 | absent |
| [ha_campaign_evidence.py](../scripts/ha_campaign_evidence.py) | K | worker/parent/guardian ; projection fermée et verdicts | T1/T3 | absent |
| [ha_session_observer.py](../scripts/ha_session_observer.py) | K | baseline hoben-live moderne et ancien C2b ; copie de bundle | T3/T4 | présent |
| [ha_live_proof.py](../scripts/ha_live_proof.py) | K | supervisor/guardian/campaign_evidence ; contrat logique partagé | T3/T4 | présent |
| [ha_session_evidence.py](../scripts/ha_session_evidence.py) | K | projecteurs et observateurs ; observation/progress/criteria | T3/T4 | présent |
| [ha_manual_live_report.py](../scripts/ha_manual_live_report.py) | K | supervise_live/launch_ha_manual_live ; ancienne enveloppe | T4 | présent |
| [ha_incident_observer.py](../scripts/ha_incident_observer.py) | K | Recorder/SessionMetadata depuis campaign_observer | T3 | absent |
| [ha_incident_evidence.py](../scripts/ha_incident_evidence.py) | K | campaign_evidence et dual ; validation F1 | T3 | absent |
| [ha_pong_injection.py](../scripts/ha_pong_injection.py) | K | reconnect_observer ; instrumentation de test seulement | T3 | absent |
| [ha_reconnect_observer.py](../scripts/ha_reconnect_observer.py) | K | dispatch session-reconnect ; vraie acquisition et cleanup | T3 | absent |
| [ha_reconnect_proof.py](../scripts/ha_reconnect_proof.py) | K | campaign_evidence ; preuve R5 et copie du bundle | T3 | absent |
| [ha_dual_observer.py](../scripts/ha_dual_observer.py) | K | import conditionnel campaign_observer ; option séparée | T3 | absent |
| [ha_dual_instrumentation.py](../scripts/ha_dual_instrumentation.py) | K | dual_observer ; Tracker/TrackedSession/TrackedTransport | T3 | absent |
| [ha_dual_evidence.py](../scripts/ha_dual_evidence.py) | K | dual_observer et projecteur ; branches de schéma historiques | T3 | absent |
| [ha_session_runtime/Dockerfile](../scripts/ha_session_runtime/Dockerfile) | K | build déclaré dans les deux voies HA ; base épinglée | T3/T4 | présent |
| [ha_session_runtime/requirements.txt](../scripts/ha_session_runtime/requirements.txt) | K | COPY/RUN du Dockerfile ; HA et dépendances épinglés | T3/T4 | présent |

### Node partagé dans scripts et preuve C1

| Fichier | État | Consommateur / raison vérifiable | Tests | main |
| --- | --- | --- | --- | --- |
| [ha-live-proof.cjs](../scripts/ha-live-proof.cjs) | K | campaign-report et ha-manual-live-report ; oracle logique Node | T3/T4 | présent |
| [ha-session-evidence.cjs](../scripts/ha-session-evidence.cjs) | K | ha-live-proof et validateurs F1/R5/dual/C1 | T3/T4/T5 | présent |
| [ha-session-proof.cjs](../scripts/ha-session-proof.cjs) | C | require embarqué dans test_ha_session_proof.py ; doc C1 | T5 | présent |

### Bibliothèques de protocole et lecteurs historiques

| Fichier | État | Consommateur / raison vérifiable | Tests | main |
| --- | --- | --- | --- | --- |
| [boundary_capture.py](../scripts/boundary_capture.py) | K | protocol_campaign_collect.h1h2 et sonde historique | T2/T5 | présent |
| [boundary_analysis.py](../scripts/boundary_analysis.py) | K | boundary_capture ; annotations H1/H2 hors production | T2/T5 | présent |
| [boundary_timeline.py](../scripts/boundary_timeline.py) | K | boundary_capture ; projection de journaux privés en métadonnées | T2/T5 | présent |
| [boundary_public_timeline.py](../scripts/boundary_public_timeline.py) | K | run_experimental_boundary.safe_report ; allowlist indépendante | T2/T5 | présent |
| [boundary_archive.py](../scripts/boundary_archive.py) | K | import par probe_opened_client_boundary, lui-même dynamique | T5 | présent |
| [run_experimental_boundary.py](../scripts/run_experimental_boundary.py) | K | run_manual_hoben.h1h2 appelle collect/safe_report | T2/T4/T5 | présent |
| [probe_opened_client_boundary.py](../scripts/probe_opened_client_boundary.py) | K | importlib.import_module depuis run_experimental_boundary.collect | T4/T5 | présent |
| [run_session_300.py](../scripts/run_session_300.py) | K | collecte moderne + session_suite + voie historique | T2/T4 | présent |
| [session_suite.py](../scripts/session_suite.py) | K | protocol_campaign_collect et run_manual_hoben ; moteur partagé | T2/T4 | présent |
| [session_suite_v3.py](../scripts/session_suite_v3.py) | K | import par session_suite ; compatibilité de rapports | T2 | présent |
| [session_suite_v3_contract.json](../scripts/session_suite_v3_contract.json) | K | donnée lue par Python et require Node session-suite-v3 | T2 | présent |

### Lanceurs propres à la voie manuelle installée

| Fichier | État | Consommateur / raison vérifiable | Tests | main |
| --- | --- | --- | --- | --- |
| [launch_manual_hoben.py](../scripts/launch_manual_hoben.py) | K | commande YAML hoben-manual ; subprocess isolé | T4 | présent |
| [run_manual_hoben.py](../scripts/run_manual_hoben.py) | K | fichier construit et lancé par launch_manual_hoben | T4 | présent |
| [manual_hoben_context.py](../scripts/manual_hoben_context.py) | K | imports des deux lanceurs/collecteurs historiques ; provenance | T4 | présent |
| [launch_ha_manual_live.py](../scripts/launch_ha_manual_live.py) | K | commande collect-ha de hoben-manual ; supervise_live | T4 | présent |

### Autres lanceurs, outils et contrats historiques : usage à confirmer

| Fichier | État | Consommateur / raison vérifiable | Tests | main |
| --- | --- | --- | --- | --- |
| [launch_experimental_boundary.py](../scripts/launch_experimental_boundary.py) | C | fixture hoben-experimental, tests et docs ; ancien lancement | T5 | présent |
| [launch_live_ha_parity.py](https://github.com/Guillaume0385/ha-hoben-community/blob/c81b79643485e8b148695c6e4fc0e2a9a50f2a87/scripts/launch_live_ha_parity.py) | C | fixture hoben-live-experimental, tests et ancien contrat | T5 | présent |
| [run_live_ha_parity.py](https://github.com/Guillaume0385/ha-hoben-community/blob/c81b79643485e8b148695c6e4fc0e2a9a50f2a87/scripts/run_live_ha_parity.py) | C | subprocess du lanceur parity ; pas le coordinator actuel | T5 | présent |
| [launch_session_300.py](https://github.com/Guillaume0385/ha-hoben-community/blob/c81b79643485e8b148695c6e4fc0e2a9a50f2a87/scripts/launch_session_300.py) | C | ancienne fixture, tests ; lance run_session_300, moteur partagé | T2/T5 | présent |
| [launch_session_suite.py](../scripts/launch_session_suite.py) | C | ancienne fixture/tests ; subprocess run_session_suite | T2/T5 | présent |
| [run_session_suite.py](../scripts/run_session_suite.py) | C | launch_session_suite ; conservé en compatibilité/test | T2/T5 | présent |
| [probe_hoben_connection.py](../scripts/probe_hoben_connection.py) | C | CLI documentée et tests ; références des plans non exécutables | T2/T5 | présent |
| [v4_validation_values.py](../scripts/v4_validation_values.py) | C | import par probe_hoben_connection ; export privé manuel historique | T5 | présent |
| [replay_opened_client_boundary.py](../scripts/replay_opened_client_boundary.py) | C | outil de replay offline documenté et testé ; pas un collecteur live | T5 | présent |
| [session_natural_900.py](https://github.com/Guillaume0385/ha-hoben-community/blob/c81b79643485e8b148695c6e4fc0e2a9a50f2a87/scripts/session_natural_900.py) | C | tests et référence de plan ; aucune nouvelle admission autorisée | T2 | présent |
| [ha_session_proof.py](../scripts/ha_session_proof.py) | C | contrat C1 importé par ses tests ; distinct du contrat live C2 | T5 | présent |
| [campaign_shell_semantics.py](../scripts/campaign_shell_semantics.py) | C | tests/fixtures des shells inertes ; pas admission des collecteurs | T6 | absent |
| [manual_campaign_contract.py](../scripts/manual_campaign_contract.py) | C | modèle offline et tests ; pas de caller live des cinq workflows | T6 | absent |

### Preuves GitHub partielles : CI et documentation, pas gates live

| Fichier | État | Consommateur / raison vérifiable | Tests | main |
| --- | --- | --- | --- | --- |
| [github_campaign_evidence.py](../scripts/github_campaign_evidence.py) | C | modèles/tests ; lecture injectée sans autorité d’admission | T6 | absent |
| [github_campaign_transport.py](../scripts/github_campaign_transport.py) | C | lecteurs de preuves/tests ; GET bornés, pas dispatch | T6 | absent |
| [github_campaign_dispatch_evidence.py](../scripts/github_campaign_dispatch_evidence.py) | C | tests et doc provenance ; faits partiels de dispatch | T6 | absent |
| [github_campaign_branch_evidence.py](../scripts/github_campaign_branch_evidence.py) | C | tests et doc ; HEAD de branche sans autorité d’exécution | T6 | absent |
| [github_campaign_workflow_tree.py](../scripts/github_campaign_workflow_tree.py) | C | tests et doc ; identité d’arbre des shells | T6 | absent |
| [github_campaign_workflow_blob.py](https://github.com/Guillaume0385/ha-hoben-community/blob/c81b79643485e8b148695c6e4fc0e2a9a50f2a87/scripts/github_campaign_workflow_blob.py) | C | tests et doc ; identité des octets Git, pas sémantique YAML | T6 | absent |
| [github_campaign_actions_registry.py](https://github.com/Guillaume0385/ha-hoben-community/blob/c81b79643485e8b148695c6e4fc0e2a9a50f2a87/scripts/github_campaign_actions_registry.py) | C | tests et doc ; métadonnées partielles du registre Actions | T6 | absent |

### Supports hors des 88 scripts

| Chemin | Consommateur constaté / décision |
| --- | --- |
| [.github/config/hoben-experimental.json](../.github/config/hoben-experimental.json), [hoben-live.json](../.github/config/hoben-live.json) | require par experimental-lab-gate / experimental-live-gate, eux-mêmes utilisés par manual-hoben-gate : **conserver** tant que cette voie existe. Ces fichiers ne prouvent pas la configuration GitHub effective. |
| [.github/config/hoben-experimental-recipient.pem](../.github/config/hoben-experimental-recipient.pem) | Certificat public du canal historique et tests crypto ; usage à confirmer avant retrait du canal, jamais déduire qu'un helper/certificat est orphelin parce que l'ancien YAML est en fixture. Aucun matériau privé lu dans A1. |
| [tests/fixtures/ha_session_worker.py](../tests/fixtures/ha_session_worker.py), [campaign_parent_worker.py](../tests/fixtures/campaign_parent_worker.py) | Fichiers worker choisis par chemin/subprocess pour les scénarios CI synthétiques ; **conserver**. |
| [tests/experimental_simulated_server.py](../tests/experimental_simulated_server.py), [session_suite_v3_cases.json](../tests/fixtures/session_suite_v3_cases.json), tests/js | Chargement de code par spec_from_file_location, injections réseau synthétiques et oracles Node ; ne pas retirer une régression sur la seule base d'un import AST absent. |
| [pyproject.toml](../pyproject.toml), [ha_tests/pytest.ini](../ha_tests/pytest.ini), conftest des deux suites | Dépendances, découverte pytest, stubs/fixtures et interdiction de réseau réel ; quatre jobs CI distincts à préserver. |
| [manifest.json](../custom_components/hoben/manifest.json), [hacs.json](../hacs.json), [CHANGELOG.md](../CHANGELOG.md) | HACS/HA chargent le plugin, Hassfest/HACS le valident ; le publisher lit version et notes. Le chargement dynamique HA des plateformes ne permet aucune conclusion de code mort dans custom_components. |

### Familles de tests et de documentation

| Code | Consommateurs / scénarios à préserver avant tout retrait |
| --- | --- |
| T1 | [test_campaign_runtime.py](../tests/test_campaign_runtime.py), [test_campaign_publication.py](../tests/test_campaign_publication.py), [test_campaign_preflight.py](../tests/test_campaign_preflight.py), [test_campaign_consolidation.py](../tests/test_campaign_consolidation.py), [test_campaign_all_r4.py](../tests/test_campaign_all_r4.py) : admission minimale, verdicts, reports fermés, tampering et continuation sûre. |
| T2 | [test_protocol_campaign_collect.py](../tests/test_protocol_campaign_collect.py), [test_session_suite.py](../tests/test_session_suite.py), [test_session_suite_v3.py](../tests/test_session_suite_v3.py), [test_session_300_runtime.py](../tests/test_session_300_runtime.py), [test_boundary_campaign_regressions.py](../tests/test_boundary_campaign_regressions.py) et tests boundary/phase/process : budgets, H1/H2, fragmentation, fermeture et preuve historique. |
| T3 | [test_ha_session_supervisor.py](../tests/test_ha_session_supervisor.py), [test_ha_live_proof.py](../tests/test_ha_live_proof.py), [test_ha_incident_f1.py](../tests/test_ha_incident_f1.py), [test_ha_reconnect_multi_r5.py](../tests/test_ha_reconnect_multi_r5.py), [test_manual_campaign_observer.py](../ha_tests/test_manual_campaign_observer.py), [test_reconnect_multi_r5.py](../ha_tests/test_reconnect_multi_r5.py) : confinement/réapage, vrai HA synthétique, F1/R5 et refus de faux succès. |
| T4 | [test_manual_hoben_runtime.py](../tests/test_manual_hoben_runtime.py), [manual-hoben.test.cjs](../tests/js/manual-hoben.test.cjs), [test_ha_manual_live.py](../tests/test_ha_manual_live.py), [test_ha_manual_live_diagnostics.py](../tests/test_ha_manual_live_diagnostics.py) : ancien gate, recheck/claim, exports et isolation. |
| T5 | [test_experimental_lab_workflow.py](../tests/test_experimental_lab_workflow.py), [test_experimental_live_workflow.py](../tests/test_experimental_live_workflow.py), [test_experimental_boundary_capture.py](../tests/test_experimental_boundary_capture.py), [test_ha_session_proof.py](../tests/test_ha_session_proof.py), [test_boundary_archive.py](../tests/test_boundary_archive.py), tests/js et rapports historiques : contrats négatifs, crypto simulée, confidentialité, schémas et traces synthétiques. |
| T6 | [test_manual_campaign_contract.py](../tests/test_manual_campaign_contract.py), [test_campaign_shell_semantics.py](../tests/test_campaign_shell_semantics.py), [test_github_campaign_evidence.py](../tests/test_github_campaign_evidence.py) et test_github_campaign_* associés, tests des deux plans : modèles sans autorité d'exécution, GET bornés et refus sûrs. |
| T7 | [test_release_workflow.py](../tests/test_release_workflow.py) : JavaScript embarqué évalué avec API simulée ; acteur/ref/tentative, version/notes, collisions, course main, draft, rollback sûr et réponse de publication perdue. |

Références documentaires consommant ces chemins :
[guide courant](manual-test-campaign-guide.md), [runtime et budgets](manual-test-campaign-runtime.md),
[voie historique](hoben-manual-workflow.md), [ancien inventaire](manual-test-campaign-inventory.md),
[preuve C1](ha-session-proof-c1.md), [runtime C2a](ha-session-runtime-c2a.md),
[live C2b](ha-session-live-c2b.md), [provenance GitHub](github-campaign-evidence.md),
[frontière H1/H2](opened-client-boundary-campaign.md), [contrat R5](ha-controlled-reconnect.md),
README.md sections tests manuels/publication, project.md et protocol.md.
Les sept [workflows retirés en fixtures](../tests/fixtures/retired_workflows/README.md),
les fixtures `campaign_shells_013` / `campaign_admission_014` et les cas JSON v3
ne sont pas installés dans Actions. Les supprimer supprimerait des régressions,
pas seulement de l'outillage de lancement.

## Redondances prouvées, différences et risques de retrait

| Observation | Preuve / limite | Conséquence pour une future PR |
| --- | --- | --- |
| Recouvrement des moteurs de session | La voie M et le protocole moderne réutilisent run_session_300.observe et session_suite._observe_reconnect ; le HA partage supervisor/worker/coordinator. | Réduire éventuellement les lanceurs/enveloppes exclusifs, **jamais supprimer le moteur partagé** avec le YAML ancien. |
| Ancien all ≠ all modernes | manual-hoben-report.PLANS.all ne contient que h1h2/session-300/session-reconnect ; modernes : six protocole, sept HA, ordre fermé. Le H1/H2 historique est rendu INCONCLUSIVE, tout en étant admis par completed ; le moderne distingue SUCCESS opérationnel 12/12 et hypothèse boundary_proven=false. | Un nom identique n'est pas une preuve d'équivalence des critères, statuts, gates ou enveloppes. Comparaison champ par champ requise. |
| Admissions non équivalentes | Ancien : experimental protégé, PR fusionnée/arbre identique/CI, identité persistée pour HA, tentative 1, claim et recheck ; moderne : dispatch propriétaire, ref choisie, environnements natifs, reruns permis, identité initiale documentée sans association. | Retrait de la voie ancienne soumis à décision propriétaire ; ne pas transplanter ses exigences dans les nouvelles campagnes ni alléger silencieusement ses garanties. |
| Consommateurs hors du YAML ancien | README.md recommande encore Tests Hoben manuels ; hoben-manual.yml et ses helpers existent aussi sur main ; CI utilise les imports, fixtures et validateurs. | **Absence d'orphelin démontré.** L'audit seul ne justifie ni suppression ni fusion des tests. |
| Crypto/exports apparemment doublés | boundary_archive, experimental-ciphertext et helpers de run_experimental_boundary ont des historiques et consommateurs de tests différents. | Comparaison des formats, bornes, erreurs et preuves de non-fuite manquante ; C, pas retrait automatique. Ne lire/exporter aucun capture ou matériau privé. |
| Dual présent mais non bloquant | Option YAML distincte, OPTIONAL_CHOICES hors all ; modules copiés/importés conditionnellement et validateurs encore présents. R3 annulée et décision propriétaire distincte. | Ne pas le relancer, le fiabiliser ou le supprimer dans A1 ; éventuel retrait séparé avec preuves de non-régression du catalogue all. |
| Commentaires historiques trompeurs | « inactive », noms push/preflight et anciens plans peuvent masquer un helper actif ; anciennes docs ont des plafonds/voies remplacés. | D : clarifier portée/historique et conserver les faits protocolaires, pas effacer un fichier sur son titre. |

### Branches, publication et invariants de sûreté

Sur le main comparé, les deux workflows modernes sont des **registration-only**
avec unique job `not-activated`, sans checkout, secret ni environnement, puis
`exit 1` :
[HA sur main](https://github.com/Guillaume0385/ha-hoben-community/blob/1ec61b40615b481fe5da1b6e2b2c7590b4ff86e3/.github/workflows/hoben-ha-manual.yml),
[protocole sur main](https://github.com/Guillaume0385/ha-hoben-community/blob/1ec61b40615b481fe5da1b6e2b2c7590b4ff86e3/.github/workflows/hoben-protocol-manual.yml).
Ces shells sont destinés à enregistrer les formulaires ; leur présence dans Git
ne prouve pas l'état de l'interface native ni une collecte main.
Les scripts modernes ne sont pas tous présents sur ce main ; copier un YAML seul
ne suffit donc pas. L'admission moderne autorisant main dans le code experimental
est une compatibilité déclarée, pas une activation du shell main ni un test de
l'interface native, des approbations ou de la release. Les trois autres YAML
(validate, publish-release, hoben-manual) sont identiques entre les deux arbres
comparés ; 58 des 88 fichiers d'outillage sont présents sur main, pas nécessairement
au même contenu. L'ancien hoben-manual
refuse main explicitement. **Aucune promotion/écriture main dans A1.**

Invariants à conserver lors de chaque lot ultérieur :

- Contrats Python/Node indépendants, sélection allowlistée, statuts fidèles,
  cleanup/réapage avant nouvelle session/étape ; un échec de collecte/result ou
  une preuve manquante ne donne pas SUCCESS. Ne pas créditer le cache B7 ni
  déduire un EOF ou une causalité serveur. #163 et #186 restent des suivis distincts.
- Protocole : maxima 15/30/45/1800/360/600 s, all 3000 s ; HA :
  360/90/120/180/600/60/120 s, all 1800 s, 15 ouvertures/42 refreshs ; R5 trois
  ouvertures au plus et 120 s depuis la dernière acceptation. Dual : 900 s séparées,
  jamais ajouté au all. Les timeouts de job ne prouvent pas la durée utile.
- HA : 1 Gio/128 PID, image/requirements épinglés, bundle public en lecture seule,
  guardian/worker séparés, cgroup, canal privé et deadlines externes. Hors ligne
  network=none ; aucune suppression de test Docker justifiée par son coût.
- Rapports allowlistés : HA ≤8192 octets par détail, worker ≤16384, enveloppe
  moderne ≤64 Kio ; lecture sûre des fichiers, revalidation avant transfert,
  artefact JSON public seulement, rétention sept jours. Les formats historiques
  ont leurs propres bornes ; ne pas les confondre avec une capture RX.
- V4 lecture seule, TLS certificat/hostname vérifiés myhoben.fr:465, aucune écriture
  Modbus 06/16/22/23 ni commande poêle, aucun GUID/secret/RX brut/header privé,
  valeur domestique ou exception libre dans les rapports. Aucun test réel DEV/CI.
- Publication : [gate inline](../.github/workflows/publish-release.yml#L45) sur
  main exact et autorisation propriétaire fraîche ; manifest.version, suffixe
  prerelease et section CHANGELOG non vide concordants ; tag absent réservé
  atomiquement, main relu, draft/ref vérifiés avant publication. Avant tentative
  de publication, rollback de ses propres ressources vérifiées ; après tentative,
  conserver les ressources ambiguës et ne jamais effacer une release possiblement
  publique. Pas d'environnement de release déclaré dans ce YAML ; ne pas inventer
  un gate natif ni une validation HA qu'il n'effectue pas.
- Les règles natives d'environnement, protections de branche et usages externes
  ne sont pas démontrés par cet audit statique. Versions flottantes des actions
  CI (`@main`, `@master`, tags de version majeure) : reproductibilité à examiner
  séparément, sans les modifier ni les présenter comme épinglées par SHA.

Le [manifest](../custom_components/hoben/manifest.json) déclare un unique domaine
Hoben, config_flow et requirements vides ; [hacs.json](../hacs.json) désigne cette
intégration. Aucun import de scripts n'a été relevé dans le plugin distribué.
Cela n'autorise pas à retirer le dossier scripts : les workflows, tests, bundles,
archives source et commandes documentées restent ses consommateurs.

## Lots futurs proposés, non réservés

| Lot proposé | Petite décision / preuve à obtenir avant changement | Sortie attendue, limites |
| --- | --- | --- |
| B1 — lanceurs historiques exclusifs | Choisir **un** couple, par exemple launch_live_ha_parity/run_live_ha_parity ; confirmer usages docs/main/fixtures et différences avec le vrai coordinator, puis décision propriétaire. | Retrait ou archivage ciblé seulement après équivalence des régressions pertinentes ; préserver les preuves utiles à #163/#186. Aucun fichier déclaré supprimable par A1. |
| C1 — voie hoben-manual | Faire accepter la matrice de non-équivalence, décider le retrait du formulaire ancien et la stratégie main/README ; séparer définition workflow, consommateurs exclusifs et bibliothèques partagées. | Une petite PR de retrait du YAML seulement si autorisée, avec tests de non-réactivation et mutex/gates conservés ; aucune suppression en cascade. Claims/tags historiques à traiter explicitement, sans nettoyage GitHub automatique. |
| B2/C2 — helpers après décision C1 | Nouveau graphe après retrait effectif, inspecter chaque export/import dynamique/copie/lecteur de schéma et consumer main/CI ; comparer les négatifs avant toute fusion de tests. | Un seul sous-ensemble prouvé à la fois ; conserver les contrats indépendants Node/Python et les modèles historiques encore utiles. |
| D1 — clarté documentaire | Actualiser la recommandation README et les docstrings devenues ambiguës ; distinguer actuel, historique et non installé, sans effacer les incertitudes protocolaires. | Commentaires ciblés sur invariants, catalogue et limites ; pas de changement fonctionnel déguisé. |
| E — pré-release, plus tard | Analyser le FAIL HA existant dans le bon suivi, obtenir les autres validations/observations et la décision propriétaire ; réexaminer main et tous les gates au nouveau SHA. | Aucun READY release, promotion main, version, tag ou publication déduit du seul audit/protocole SUCCESS. |

MANAGER choisit la suite ; aucun A2/B/C/D n'est démarré ou réservé par DEV.

## Validation et limites A1

Diff A1 attendu : **ce nouveau document uniquement**. Pas de mise à jour de
CHANGELOG : inventaire interne sans changement de livrable HACS, code, API,
workflow, test, dépendance ou version ; justification conforme à AGENTS.md et à
la consigne A1. Les checks documentaires vérifient les chemins/liens et la
couverture des 88 entrées ; les tests existants utiles restent hors ligne.

Les quatre CI tests/ha-tests/hacs/hassfest sont requises sur le HEAD exact de la
PR A1 ; leurs résultats seront consignés dans la PR et #189, sans confondre le
SHA source de cet audit avec le SHA de livraison. Aucun nouveau test ajouté pour
miroiter un changement de code inexistant. Validation Hoben/HA réelle A1 :
**NOT RUN**. Arrêt DEV à state:review, sans fusion ni modification d'automatisation.

## Annexe B1 — retrait du couple HA-parity historique (20/11/2026)

Tâche `HOBEN-189-B1-LEGACY-HA-PARITY-REMOVAL-003`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Base examinée : `experimental` à `17a09888d5e77f7f4f720d6d3e2207517cf3a881` ;
`main` lu seulement à `1ec61b40615b481fe5da1b6e2b2c7590b4ff86e3`.
Les constats A1 ci-dessus restent ceux du 05/11, pas un inventaire après retrait.
Les liens des deux scripts y sont épinglés à la base A1 ; ceux de l'inventaire
du 27/10 sont épinglés à sa propre base pour conserver les preuves accessibles.

### Graphe de consommateurs et décision

| Fichier/symbole | Consommateur et preuve à la base B1 | Décision / régression conservée |
| --- | --- | --- |
| `launch_live_ha_parity.py:main/child_environment` | Seule commande entrante : ligne `run` de `tests/fixtures/retired_workflows/hoben-live-experimental.yml`. Aucun des cinq YAML installés sur les deux branches ne l'appelle. | Retirer le lanceur ; conserver la fixture et ses assertions de permissions, secrets après recheck, publication séparée, rétention et refus d'admission. |
| `run_live_ha_parity.py:observe/main/context_valid/write_report` | Seul appel opérationnel potentiel : subprocess fixe du lanceur retiré. Son contexte exige `push` et l'ancien chemin Actions absent. Le vrai client est importé par ce script ; aucun import inverse depuis le plugin. | Retirer ce collecteur one-shot historique et son schéma 1 ; aucune preuve HA persistante actuelle n'en dépend. Ne pas modifier les clients, décodeurs ni rapports maintenus. |
| Imports Python des deux scripts | Parcours AST de tous les modules `scripts/` et `custom_components/` sur les deux SHA : aucun import entrant. Les seuls imports entrants du dépôt sont dans `tests/test_experimental_live_workflow.py`. | Retirer ces deux imports et les tests strictement dépendants ; garde de non-réactivation ajouté. |
| Chargement dynamique / copie de sources | Seul `import_module` des modules examinés : `scripts.probe_opened_client_boundary`. `SourceBundle` copie les modules du plugin et une liste fermée de workers/helpers HA, jamais le couple parity. Les subprocess sélectionnent des chemins fixes. | Conserver tous les moteurs partagés et leurs tests ; aucune extension d'allowlist ni substitution de worker. |
| Campagnes HA/protocole actuelles | YAML → `run_campaign.py` → `campaign_worker.py` → `ha_session_supervisor.py`/`ha_session_guard.py` → `ha_campaign_worker.py` et vrais client/coordinator ; protocole → `protocol_campaign_collect.py`. | Chemins inchangés ; tests de supervision, publication et HA réels sur transports simulés conservés. |
| Voie manuelle #119 | YAML installé → `launch_manual_hoben.py` ; route Info → `launch_info_manual.py`. Sur le main examiné, les deux formulaires modernes sont des shells inertes ; aucune entrée parity installée. | Conserver YAML, gates, scripts partagés et tests négatifs, y compris Node `experimental-live-gate` / `experimental-live-report`. Aucune modification main. |
| Publication / HACS | `publish-release.yml` lit manifest/CHANGELOG via API, sans exécuter ces scripts. HACS charge `custom_components/hoben/`, qui n'importe pas le couple. Une archive Git peut contenir du code sans le consommer à l'exécution. | Publication, manifeste, version et plugin inchangés ; tests de publication conservés. |
| Documentation / fixtures | Les liens exacts des deux scripts figurent dans les inventaires datés A1 et 27/10 ; l'ancienne procédure et les noms de rapports sont historiques, pas des commandes courantes. La fixture retirée n'est pas un workflow installé. | Conserver les preuves, épingler les liens de code aux SHA audités ; aucune suppression de fixture ni modification des contrats historiques. |

Cette conclusion combine appels des YAML, imports, subprocess, copies et
chargements dynamiques ; elle ne repose pas sur une absence de texte seule.
Elle porte sur les deux arbres examinés, pas sur d'éventuels usages privés
externes non observables. Le retrait n'active aucune autre voie et n'allège
aucune admission ou publication maintenue.

### Tests retirés et garanties maintenues

Dans `tests/test_experimental_live_workflow.py`, **neuf cas** sont devenus sans
objet : inspection du collecteur supprimé (1), deux appels sur son FakeClient
(3), refus de contexte et écriture exclusive de son rapport (1), allowlist de
son lanceur (1), provenance de son `main` aux tentatives 1/2/3 (3).
Le FakeClient, ses imports et fixtures locales sans autre usage sont retirés.
Ces tests ne couvraient pas le coordinator actuel : ils ne sont pas présentés
comme équivalents à une preuve de session persistante.

Les garanties autonomes restent couvertes sans changement par :

- les assertions du YAML en fixture et les deux suites Node de gate/rapport,
  conservées dans le même fichier ;
- `test_manual_hoben_runtime.py` : refus de chaque champ avant identité,
  environnement enfant sans token/fichiers Actions et rapport révalidé ;
- `test_campaign_runtime.py`, `test_campaign_consolidation.py` et
  `test_campaign_publication.py` : contexte natif, identité, provenance,
  projections privées refusées et fichier de rapport dangereux refusé ;
- `test_ha_session_supervisor.py`, `test_ha_manual_live.py` et
  `ha_tests/test_manual_campaign_observer.py` : sources fermées, identité privée,
  cleanup, vrais client/coordinator, lecture/erreur/décodage sur pairs simulés.

Le garde B1 vérifie que la fixture existe, que son YAML n'est pas réinstallé,
que les deux scripts sont absents et qu'aucun module ou YAML opérationnel ne
les référence : RED avant retrait, GREEN après. Les suites complètes et les
quatre CI sont consignées au HEAD exact dans la PR et #189.

Pas de modification CHANGELOG : retrait d'outillage historique inaccessible,
hors livrable HACS, sans changement d'API, version ou comportement du plugin.
Tests Hoben/HA réels **NOT RUN** ; aucune connexion, commande, écriture Modbus,
modification de gate ou promotion main. Aucun lot suivant lancé par CODEX DEV.

## Annexe B2 — consommateurs des candidats session-300 (20/11/2026)

Tâche `HOBEN-189-B2-LEGACY-SESSION300-REACHABILITY-004`, selon la
[consigne canonique MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Base `experimental` : `3ed9ce9a51ac1eae82d9147691e5e3149457bd45` ;
`main` examiné en lecture seule : `1ec61b40615b481fe5da1b6e2b2c7590b4ff86e3`.
L'audit A1 et l'annexe B1 restent des constats datés à leurs bases respectives.

**Décision B2 : conserver les deux scripts, aucune suppression ni adaptation de
tests.** `run_session_300.py` est un moteur partagé effectivement appelé.
Le retrait du couple est bloqué par ces consommateurs positifs, pas seulement
par une incertitude de recherche. Aucun autre candidat n'est examiné dans B2.

### Matrice symbole → consommateur → preuve → décision → régression

| Symbole / candidat | Consommateur et preuve à la base B2 | Décision / tests conservés |
| --- | --- | --- |
| `run_session_300.observe` | [Workflow protocole](../.github/workflows/hoben-protocol-manual.yml) → `run_campaign.py protocol` → `campaign_worker.py` → [protocol_campaign_collect.collect](../scripts/protocol_campaign_collect.py#L149) : import local puis `await observe(...)` dans le choix `session-300`. Le scénario existe aussi dans `all`. | **Conserver**, chemin actuel ; `test_protocol_campaign_collect.py` exécute le vrai collecteur/lifecycle/framer sur flux et horloge simulés, dont trois fragmentations pour session-300. |
| `observe`, `validate_report`, `valid_close_client`, `valid_ignored_messages` | [session_suite.py](../scripts/session_suite.py#L26) importe ces symboles ; `observe_suite` appelle `observe_300` avant la seconde observation et revalide le rapport. Imports également présents au SHA main examiné. | **Conserver**, moteur et validateurs partagés ; `test_session_suite.py`, `test_session_close_client.py`, `test_session_ignored_rx.py`. Aucun retrait de session_suite. |
| `valid_ignored_messages` | [campaign_runtime_contract.validate_stage](../scripts/campaign_runtime_contract.py#L425) importe ce validateur si un détail protocole contient `ignored_messages`. | **Conserver**, contrat de rapport actuel ; tests de schémas fermés et métadonnées bornées. L'import local conditionnel est un consommateur, même absent des imports de tête de fichier. |
| `observe`, `write_report` | [run_manual_hoben.sessions/save](../scripts/run_manual_hoben.py#L27) les importe et les appelle ; [launch_manual_hoben](../scripts/launch_manual_hoben.py#L17) importe aussi `write_report`. Le YAML manuel installé appelle ce lanceur, sans utiliser `launch_session_300.py`. Même dépendance du chemin manuel dans l'arbre main examiné. | **Conserver**, observation et publication privée partagées ; `test_manual_hoben_runtime.py` et `test_session_300_report_writer.py` couvrent contexte, export, permissions, refus de liens/fichiers existants et nettoyage d'écriture échouée. |
| `context_proof`, `require`, `write_report` | [run_session_suite.py](../scripts/run_session_suite.py#L24) importe les helpers du module. La [fixture retirée hoben-session-300](../tests/fixtures/retired_workflows/hoben-session-300.yml#L135) appelle `launch_session_suite.py`, qui lance ce runner. | **Conserver** les helpers et fixtures ; tests de suite/processus et de contexte. La fixture n'est pas un workflow installé ni un appel direct de `launch_session_300.py`. |
| `launch_session_300.collector_environment/main` | Aucun appel trouvé dans les cinq YAML installés des deux branches, ni import entrant dans les modules opérationnels examinés. Appel interne fixe de `run_session_300.py` ; [test_session_300_probe.py](https://github.com/Guillaume0385/ha-hoben-community/blob/3ed9ce9a51ac1eae82d9147691e5e3149457bd45/tests/test_session_300_probe.py#L162) vérifie son isolation, son plafond 360 s et ses sorties privées. | **Conserver dans B2** : lanceur historique candidat, distinct du moteur actif et du lanceur de suite. Aucun dossier autonome de remplacement de ses régressions n'est établi ici ; ne pas conclure que le couple est supprimable à partir de son seul statut. |
| Chargements dynamiques / SourceBundle | Parcours AST des modules scripts/plugin sur les deux SHA : les imports ci-dessus sont réels ; seul `import_module` observé = `scripts.probe_opened_client_boundary`. [SourceBundle](../scripts/ha_session_supervisor.py#L91) copie le plugin et une liste de helpers HA sans ces deux scripts. | Aucune suppression déduite de cette absence dans le bundle HA : la collecte protocole est exécutée sur le host et possède ses propres dépendances. |
| CI, HACS, publication, documentation | `validate.yml` collecte les tests cités ; le plugin HACS n'importe pas les deux scripts et le publisher ne les exécute pas. Les [instructions courantes](manual-test-campaign-runtime.md#correspondance-des-collecteurs-et-preuve) désignent positivement `run_session_300.observe`. Les définitions modernes sur main sont des shells inertes ; le manuel y refuse une collecte sur main. | Conserver tous les contrats et liens ; absence d'import depuis le plugin ou de commande du publisher ne prouve pas l'absence d'usage par les campagnes protocolaires. Aucune activation main déduite de l'inspection. |

### Vérifications reproductibles et limites

Depuis la base B2, examiner les occurrences puis les imports AST, branches de
sélection, appels et copies de fichiers ; une occurrence seule ne prouve pas
l'exécution et une absence seule ne prouve pas le code mort :

```sh
git grep -n -E 'launch_session_300|run_session_300' 3ed9ce9a51ac1eae82d9147691e5e3149457bd45 -- .github scripts tests ha_tests docs README.md custom_components
git grep -n -E 'launch_session_300|run_session_300' 1ec61b40615b481fe5da1b6e2b2c7590b4ff86e3 -- .github scripts tests docs README.md custom_components
rg -n 'run_campaign|launch_manual_hoben|launch_session_suite' .github/workflows tests/fixtures/retired_workflows
```

Les imports de bibliothèque n'exécutent pas le `main` protégé de l'ancien
runner : son contexte `push`/ancien workflow ne rend pas inaccessibles les
fonctions partagées importées par les voies manuelles actuelles. Les tests
existants prouvent des appels sur doubles hors ligne, pas une validation live.
Aucune équivalence de couverture autorisant une suppression n'est revendiquée.

Validation B2 : annexe seule, liens/symboles vérifiés, tests ciblés existants,
Ruff et `git diff --check` ; quatre CI requises au HEAD exact, résultats dans la
PR et #189. Aucun RED/GREEN de suppression : aucune suppression effectuée.
Tous les scripts, tests, fixtures, workflows et fichiers du plugin sont
byte-identiques à la base. Pas de CHANGELOG : audit interne sans impact sur le
livrable HACS ou son comportement.

Le volume initial reste saturé en inodes ; l'audit utilise un checkout isolé
sous `/tmp` sans modifier le dépôt initial. Tests Hoben/HA réels **NOT RUN** ;
aucun dispatch/rerun live, secret, donnée privée, commande ou écriture Modbus,
modification de protection, main, tag/release ou fusion DEV. Livrer les preuves
pour revue MANAGER, sans changer de candidat ni lancer le lot suivant.

## Annexe B3 — retrait du seul lanceur session-300 (20/11/2026)

Tâche `HOBEN-189-B3-LEGACY-SESSION300-LAUNCHER-ISOLATION-005`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Base `experimental` : `913236636e1db8ce0d66d0d97f51117b3fe115db` ;
`main` examiné seulement en lecture : `1ec61b40615b481fe5da1b6e2b2c7590b4ff86e3`.
**Retirer uniquement `scripts/launch_session_300.py` ; conserver le moteur
partagé `scripts/run_session_300.py` à l'octet.** B2 reste le constat antérieur ;
les liens de l'ancien lanceur A1 et de ses assertions B2 sont épinglés à leurs
SHA respectifs, sans effacer ces décisions historiques.

### Preuve par fonction et consommateur

| Fonction / entrée | Consommateurs examinés et preuve indépendante | Décision |
| --- | --- | --- |
| `collector_environment` | Parcours AST de tous les modules scripts/plugin aux deux SHA : aucun import entrant. Seul consommateur dans l'arbre maintenu : portion du test `test_session_300_probe.py` appelant directement cette fonction. Aucun export de package ni point d'entrée déclaré dans pyproject. | Retirer avec le lanceur ; protections équivalentes sur les parents maintenus ci-dessous. |
| `main` / CLI du fichier | Commande historique introduite dans [3b1336d](https://github.com/Guillaume0385/ha-hoben-community/blob/3b1336d7951743e02ff3783abb9d3c221f078dcf/.github/workflows/hoben-session-300.yml), remplacée par `launch_session_suite.py` dans [dc3872e](https://github.com/Guillaume0385/ha-hoben-community/blob/dc3872e495f9a26e1e31affd217e4d0bf48d0005/.github/workflows/hoben-session-300.yml). Les cinq YAML installés, fixtures retirées et commandes documentées des deux arbres ne l'appellent plus. Son `__main__` est une entrée directe au fichier, sans consommateur CLI maintenu. | Retirer ce point d'entrée historique, pas le lanceur de suite ni ses contrats. |
| Import dynamique / subprocess / SourceBundle | Seul import_module des modules examinés : `scripts.probe_opened_client_boundary`. Subprocess à chemins fixes et liste SourceBundle sans le lanceur ; aucun parcours chargeant arbitrairement les scripts. | Aucun chemin opérationnel reconstruit vers ce lanceur ; pas de substitution ou d'élargissement d'admission. |
| Campagnes, HACS, publication | Protocole → run_campaign/campaign_worker ; manuel → launch_manual_hoben ; fixture session-300 → launch_session_suite. Le plugin n'importe pas ce lanceur ; le publisher n'exécute pas ce fichier. Les imports positifs de run_session_300 établis en B2 restent présents. | Conserver tous les moteurs, YAML, gates, rapports et fixtures. Main reste inchangé, y compris son exemplaire historique et ses tests. |

### Équivalence des protections et adaptation minimale des tests

| Protection testée sur l'ancien lanceur | Preuve maintenue sur les voies actuelles | Adaptation B3 |
| --- | --- | --- |
| Environnement allowlisté, tokens/fichiers Actions/PYTHONPATH exclus | [test_manual_hoben_runtime.py](../tests/test_manual_hoben_runtime.py), `test_child_environment_has_no_runner_tokens_or_arbitrary_mode` : clé inconnue refusée, ensemble exact de l'allowlist. Dans [test_campaign_supervision.py](../tests/test_campaign_supervision.py), les quatre capacités de l'ancien test sont injectées dans l'environnement parent et leur absence est vérifiée sur le vrai Popen ; worker synthétique sans tokens/identité en environnement. | Déplacer les garanties sur le parent actif, retirer les seuls appels à collector_environment de l'ancien lanceur. |
| Budget dur 360 s / exécution isolée | `test_child_environment_has_no_runner_tokens_or_arbitrary_mode` vérifie `session-300: 360` ; [test_campaign_runtime.py](../tests/test_campaign_runtime.py), `test_design_budgets_are_exact_and_legacy_ha_limit_is_not_extended`, fige le même plafond moderne. Tests des parents : délais armés avant ACK, transition tardive refusée, SIGKILL/réapage d'un groupe résistant ; `-I` désormais vérifié explicitement avant le vrai Popen moderne. | Retirer le stub qui vérifiait le champ timeout=360 de l'ancien subprocess, sans changer les budgets actuels ni leurs tests. |
| stdout/stderr privés, aucune identité publiée | `test_actual_parent_ack_bounds_projection_and_reaping` vérifie DEVNULL sur les deux sorties d'un vrai subprocess synthétique, rapports privés refusés et dossier privé supprimé. Les régressions de publication et de confidentialité session-300 restent conservées. | Retirer uniquement les assertions DEVNULL sur le stub de l'ancien lanceur. |
| Contexte exact du moteur partagé | [test_session_300_probe.py](../tests/test_session_300_probe.py), désormais `test_live_context_is_exact` : contexte positif et mutation de chaque champ toujours refusée ; observe, validate_report et tests d'écriture sécurisée inchangés. | Conserver le test autonome ; supprimer son import du lanceur et la portion devenue sans objet. Aucun cas de contexte supprimé. |

Ces équivalences portent sur les garanties de sécurité maintenues, pas sur
l'identité des APIs des lanceurs ni une autorisation de collecter. Le nouveau
garde vérifie l'absence du fichier, des références opérationnelles et d'entrée
pyproject, tout en exigeant la présence du moteur partagé : RED avant retrait,
GREEN après. Aucun autre test ni fixture retiré ; un cas de garde ajouté.

Reproduction : `git grep -n launch_session_300 <SHA> -- .github scripts tests docs
README.md pyproject.toml`, complété par AST, inspection des subprocess/copies,
historique `git log -G launch_session_300 -- .github/workflows` et tests offline.
Les conclusions portent sur les consommateurs maintenus des deux arbres ; des
usages privés externes non observables ne sont pas déclarés connus.

Diff B3 limité au lanceur, à son fichier de tests, au renforcement des assertions
du parent actif dans test_campaign_supervision.py et à ce document. Le moteur,
runtime HA, gates/YAML, fixtures, manifest et version restent byte-identiques.
Résultats ciblés, suites complètes locales et quatre CI au HEAD exact consignés
dans la PR/#189, avec les limites d'inodes locales. Ruff, liens et diff-check
requis. Pas de CHANGELOG : ancien outillage inaccessible, hors livrable HACS,
sans changement d'API ni de comportement du plugin. Tests réels Hoben/HA
**NOT RUN** ; aucun dispatch/rerun live, secret, donnée domestique, commande,
écriture Modbus, main, tag/release ou fusion DEV. Aucun lot suivant engagé.

## Annexe B4 — audit du lanceur experimental-boundary (20/11/2026)

Tâche `HOBEN-189-B4-LEGACY-EXPERIMENTAL-BOUNDARY-AUDIT-006`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Base `experimental` : `ac15cf88dad2a5e5ef58d1d36d9e8bed645926d9` ;
`main` lu seulement à `1ec61b40615b481fe5da1b6e2b2c7590b4ff86e3`.
**Conserver `scripts/launch_experimental_boundary.py` et tous ses tests dans B4.**
Aucun appel opérationnel courant n'est constaté, mais l'équivalence complète
des régressions intégrées ci-dessous n'est pas établie. Aucun autre candidat
examiné ; annexe documentaire seule, sans suppression ou réorganisation de tests.

| Symbole / consommateur | Preuve examinée aux deux SHA | Tests / décision |
| --- | --- | --- |
| `collector_environment` / imports | Parcours AST scripts/plugin/tests : seuls imports directs dans [test_experimental_lab_workflow.py](../tests/test_experimental_lab_workflow.py#L12) et [test_experimental_phase_diagnostics.py](../tests/test_experimental_phase_diagnostics.py#L16). Aucun export de packaging ou appel CLI courant documenté. | Conserver : environnement réellement transmis à un subprocess et helper zero_environment des simulations du vrai collecteur, pas seulement une assertion de présence de fichier. |
| `main`, contexte/refus, sortie privée | [Tests de phase](../tests/test_experimental_phase_diagnostics.py#L144) : vrais checkouts locaux, vrai collecteur isolé en `-I`, refus contexte/identité avant réseau ; simulations H1/H2 avec validation Node indépendante et absence de sortie privée. | Conserver les tests du collecteur et leurs fixtures ; retirer leur dépendance au lanceur demanderait une équivalence démontrée, non réalisée dans B4. |
| `CHILD_PHASES` / diagnostic parent | [Lanceur](../scripts/launch_experimental_boundary.py#L35) : codes 10..16 seuls admis, autre code/signal/timeout sans phase prouvée. [Test adversarial](../tests/test_experimental_phase_diagnostics.py#L399) : sorties privées jetées, child_exit distinct de unavailable. | Conserver ce contrat de diagnostic fermé ; les parents actuels exposent d'autres schémas, pas une preuve de remplacement de ces assertions. |
| `main` / nettoyage | Timeout enfant 1800 s, nettoyage du staging privé même après interruption ; échec de nettoyage refusé même après succès enfant, diagnostic fixe de provenance parent. [Régression](../tests/test_experimental_phase_diagnostics.py#L422) avec exception synthétique non publiée. | Conserver, ne pas effacer le refus autonome pour faire disparaître un import de test. |
| Fixture / garde de séparation H1/H2 et session-300 | Le YAML hoben-experimental a été déplacé R100 en [fixture](../tests/fixtures/retired_workflows/hoben-experimental.yml#L125) par #121 (`3969c02375603d94f331ca5f721dd476ce3408ae`). [test_session_300_workflow.py](../tests/test_session_300_workflow.py#L144) lit aussi l'AST du lanceur et suit le vrai collecteur/sonde pour interdire une fausse équivalence H1/H2-V4. | Conserver fixture et garde croisé ; sa valeur indépendante ne disparaît pas avec le seul statut historique du YAML. |
| Dynamique / subprocess / SourceBundle / HACS / publication | Aucun import opérationnel du lanceur ; seul import_module observé = `scripts.probe_opened_client_boundary`. Entrées courantes : run_campaign/campaign_worker, launch_manual_hoben et route Info ; chemins fixes, bundle HA sans ce lanceur. Plugin et publisher ne l'appellent pas. | Absence d'appel courant étayée ; ne pas la confondre avec une preuve que ses tests de sécurité sont devenus inutiles. Main et tous les chemins actuels restent inchangés. |

Les parents actuels ont leurs propres protections d'isolation, de budget et de
nettoyage : [run_campaign.execute](../scripts/run_campaign.py#L187) produit des
raisons fermées et utilise un canal de rapport, tandis que
[launch_manual_hoben](../scripts/launch_manual_hoben.py#L115) supervise le groupe
et son staging. Leurs tests passent sans démontrer le remplacement des sorties
phase_source=child_exit/unavailable/parent, du helper de simulation et du garde
AST historique. Une absence d'appel dans les YAML ne suffit donc pas à autoriser
la suppression de ces dépendances de test ou à déclarer la couverture équivalente.

Vérification reproductible : `git grep -n launch_experimental_boundary <SHA> --
.github scripts tests docs README.md pyproject.toml`, complétée par AST de tous
les modules, inspection des appels/copies et `git log --name-status --
.github/workflows/hoben-experimental.yml tests/fixtures/retired_workflows/hoben-experimental.yml`.
Les tests ciblés exécutent les vrais parents/collecteurs sur transports et
horloges simulés ; aucune preuve live ni connaissance d'usages privés externes
n'en est déduite. Résultats, liens, Ruff, diff-check et quatre CI au HEAD exact
consignés dans la PR/#189. Pas de RED/GREEN de retrait : aucun retrait effectué.

Tous les fichiers hors cette annexe sont byte-identiques à la base, y compris
tests, scripts, moteurs, runtime, fixtures et gates. Pas de CHANGELOG : audit
interne sans impact HACS/plugin. Checkout temporaire sous /tmp, limite d'inodes
du volume initial conservée et documentée. Tests Hoben/HA réels **NOT RUN** ;
aucun dispatch/rerun live, commande/écriture Modbus, donnée privée, main,
tag/release/version ou fusion DEV. Livrer pour revue MANAGER puis arrêter B4.

## Annexe B5 — retrait de la fondation natural-900 (20/11/2026)

Tâche `HOBEN-189-B5-LEGACY-SCRIPT-CANDIDATE-INVENTORY-007`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Candidat unique choisi dans A1 : `scripts/session_natural_900.py`, distinct des
scripts conservés B2/B4. Base `experimental` :
`d7fe6b3ec38deba1da2a9b48d8b1ab15295fdeec` ; main examiné seulement en lecture :
`1ec61b40615b481fe5da1b6e2b2c7590b4ff86e3`.
**Retirer ce seul module et son test entièrement dédié ; conserver les moteurs,
les gardes de refus de fausse reconnexion et les exclusions de scénario.**

| Symbole / consommateur | Preuve aux deux SHA | Décision / couverture |
| --- | --- | --- |
| `observe_natural`, `validate_natural` | Parcours AST de tous les modules scripts/plugin/tests : seul import entrant dans test_session_natural_900.py. Module sans CLI, point d'entrée de packaging, constructeur live ou admission. Aucun YAML installé ni fixture ne l'appelle. | Retirer la fondation introduite par #110 (`9452af15318f43ee037560a977424963d1623a24`) et ses 24 cas strictement liés. Aucun helper partagé dans ce test n'est importé ailleurs. |
| Imports dynamiques, subprocess, SourceBundle | Seul import_module des scripts/plugin = probe_opened_client_boundary. Entrées modernes et historiques à chemins fixes ; bundle HA avec liste de scripts fermée, sans natural900. Plugin HACS et publisher sans dépendance. | Absence d'usage établie par graphe/imports/appels, pas seulement par recherche textuelle ; main reste inchangé. |
| `protocol_campaign_plan.excluded_references` | Chaîne historique dans une liste explicitement exclue ; dataclass de citations, jamais importée ni lancée. Le scénario session-natural-900 est rejeté par le catalogue fermé ; aucun appel à observe_natural dans le runtime. | Conserver la chaîne et son test négatif. Les références actives et les autres exclusions doivent toujours exister ; seul ce chemin retiré doit désormais être absent. Aucune règle d'admission modifiée. |
| Documents A1 / inventaire / plan | Références à la fondation historique non autorisée, pas une commande courante. Les liens de code/test sont épinglés aux bases respectives des documents. | Conserver l'historique accessible. Le plafond 900 s retiré n'est transféré à aucune campagne ; le budget HA dual de 900000 ms est indépendant et inchangé. |

### Garanties équivalentes conservées sur les chemins actuels

| Garantie de l'ancien test dédié | Régression indépendante maintenue / renforcée |
| --- | --- |
| Silence sans reconnexion fabriquée ; réouverture seule insuffisante | [test_v4_lifecycle.py](../tests/test_v4_lifecycle.py) : quiet_session_and_consumed_modbus_exception_never_reconnect conservé à 601 s et étendu à 901 s simulées. natural_witness_causality_generation_and_correlated_read exige perte horodatée, génération et lecture réellement corrélée ; une réouverture réinitialise le témoin, une ancienne réponse ne le rétablit pas. |
| Pas de perte/reprise inventée sur arrêt local ou ouverture refusée | Même suite : natural_witness_has_no_loss_on_local_shutdown_or_unproven_opening, natural_loss_timestamp_survives_delayed_lifecycle_wakeup. [test_protocol_campaign_collect.py](../tests/test_protocol_campaign_collect.py) vérifie le refus d'une perte antérieure au seuil et les générations corrélées, sans présenter l'inhibition expérimentale Pong comme perte naturelle. |
| Schéma fermé, aucun champ privé ni fausse promotion SUCCESS | [test_campaign_runtime.py](../tests/test_campaign_runtime.py) : reconnection_without_natural_loss_never_succeeds, private_unknown_keys_refuse_in_every_public_layer et absolute_stage_limits_fail_closed, avec validateurs Python/Node. L'ancien schéma natural900 n'a plus de producteur ou consommateur maintenu ; il n'est pas remplacé par un faux rapport. |
| Nettoyage, annulation, ouverture en erreur et budget borné | Tests lifecycle : close_during_each_phase_has_no_late_reconnect_or_orphan, cancel_initial_connect_closes_opening_and_does_not_retry, ordered_backoff_and_strict_lifetime_budget et invalid_configuration_rejected_before_factory. Tests de [session_suite](../tests/test_session_suite.py) : annulation/délai réel ferme le propriétaire partagé. Aucun changement de factory/runtime. |
| Aucune admission de la fondation 900 s | [test_protocol_campaign_plan.py](../tests/test_protocol_campaign_plan.py) : refus du choix session-natural-900, exclusion explicite conservée ; nouveau garde d'absence du fichier, des imports opérationnels et des entrées YAML/packaging. |

Les 24 cas supprimés testaient exclusivement les deux fonctions retirées :
4 rapports admis, 13 rapports refusés, 1 champ privé refusé, 6 observations sur
lifecycle simulé. Les tests indépendants et leurs fixtures restent conservés.
L'équivalence porte sur les garanties maintenues, pas sur la création d'une
nouvelle campagne de 900 s ou la compatibilité d'un schéma historique inutilisé.

Vérifications : `git grep -n -E 'session_natural_900|observe_natural|validate_natural'
<SHA> -- .github scripts tests ha_tests docs README.md pyproject.toml`, AST,
inspection de SourceBundle/subprocess/packaging et historique du candidat.
Garde RED avant retrait puis GREEN ; deux anciennes assertions de présence de
référence exclue adaptées à cette seule suppression, contrôles des références
actives/immutabilité inchangés. Tests ciblés, suites complètes, Ruff, liens,
diff-check et quatre CI au HEAD exact sont consignés dans la PR/#189.

Tous les scripts B2/B4, moteurs, runtime HA, workflows/gates, manifest/version
restent byte-identiques. Pas de CHANGELOG : fondation non raccordée hors
livrable HACS, sans changement du comportement/API du plugin. Limite d'inodes
locale et résultats non verts éventuels rapportés honnêtement ; checkout sous
/tmp. Tests réels Hoben/HA **NOT RUN** ; aucun dispatch/rerun live, commande,
écriture Modbus, donnée privée, main, release/tag ni fusion DEV. Aucun autre
candidat examiné ou lot suivant engagé.

## Annexe B6 — retrait du lecteur de registre Actions

Tâche `HOBEN-189-B6-LEGACY-SCRIPT-SINGLE-CANDIDATE-008`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Candidat unique A1 : `scripts/github_campaign_actions_registry.py`, hors B2/B4
et natural900. Base `experimental` : `64383c9524adab10a0be3a4c8d8002fe200913d0` ;
main lu seulement à `1ec61b40615b481fe5da1b6e2b2c7590b4ff86e3`.
**Retirer uniquement ce lecteur sans consommateur opérationnel ; conserver
toutes les protections du transport GET et des admissions maintenues.**

| Symbole / consommateur | Preuve examinée | Décision / couverture |
| --- | --- | --- |
| `validate_registry`, `read_registry`, modèles Fact/Observation | AST de tous les modules scripts/plugin/tests : seul import dans test_github_campaign_actions_registry.py. Aucun import des helpers de ce test ailleurs. Source absente de main. Aucune CLI utile, backend HTTP ou recherche de token ; exécution directe refusée. | Retirer le modèle introduit en `5df31d7d51239adace6466922257a96898cb7591`, pas le transport. Aucun producteur/consommateur maintenu de ses observations ne dépend de son API. |
| Workflows, dynamique, subprocess, SourceBundle, packaging | Aucun appel installé/historique en YAML/fixture/CLI documentée, aucun import opérationnel. Seul import_module des scripts/plugin = probe_opened_client_boundary ; entrées à chemins fixes et bundle HA sans le lecteur. HACS/publisher sans dépendance. | Pas de raccordement ou activation retirés ; main, gates et scripts B2/B4 inchangés. Absence établie par graphe et inspection, pas par recherche textuelle seule. |
| 30 cas de tests du transport partagé | Deux routes fixes, 18 routes interdites, 6 refus de pagination/query, 3 JSON/token refusés, 1 redirection refusée. Ces cas ne deviennent pas inutiles avec le lecteur. | **Conserver les 30 cas** dans [test_github_campaign_actions_registry.py](../tests/test_github_campaign_actions_registry.py), sans importer le lecteur supprimé. Appeler directement GitHubGETTransport et vérifier erreurs typées/fermeture/absence de fuite. |
| 112 autres cas du même fichier | Projection enum/ID/path/state, bornes et binding des seules observations retirées, recheck et ancien garde de source/CLI. Aucun helper exporté ou consommateur tiers. | Retirer ces seuls cas dépendants ; ajouter un garde d'absence du module/imports opérationnels/entrée YAML/packaging. Fichier de tests conservé : 142 cas avant, 31 après. |
| Preuves documentaires / limite d'accès historique | A1 et [section registre](github-campaign-evidence.md) décrivent le lecteur non raccordé et le refus du connecteur observé le 27/10. Liens source/test épinglés aux SHA antérieurs, contrat historique conservé. | Ne pas inférer qu'un workflow est actif ou approuvé ; aucun nouvel appel GitHub réel ni contournement du refus historique. |

### Garanties indépendantes maintenues

- [test_github_campaign_transport.py](../tests/test_github_campaign_transport.py) :
  GET allowlisté, TLS vérifié, token injecté sans découverte d'environnement,
  refus HTTP/403, timeout/tailles, redirections, pagination hostile, JSON ambigu
  et écho de secret ; fermeture des streams et erreurs sans contexte privé.
  Les 30 cas propres aux routes de workflow restent en plus testés directement.
- [test_github_campaign_evidence.py](../tests/test_github_campaign_evidence.py) :
  faits partiels sans autorité, can_start=false, immutabilité, incohérences,
  recheck, erreurs/pagination et champs privés refusés.
- [test_campaign_minimal_admission.py](../tests/test_campaign_minimal_admission.py)
  et les régressions des campagnes maintenues : contexte fermé et propriétaire,
  choix, refus et environnements ; aucune entrée registry active n'est assimilée
  à une autorisation. Les workflows/gates eux-mêmes restent byte-identiques.

Il n'y a pas de remplacement permissif du parseur d'observations : cette API
inutilisée disparaît. Sa borne de métadonnées 16 Kio n'est transférée à aucun
rapport ; transport existant (2 Mio/10 s), budgets Hoben et routes restent
inchangés. Le booléen false du modèle retiré n'est pas remplacé par un succès
ou une approbation inventée. Les schémas d'observations maintenus et les contrôles
d'admission continuent d'être testés indépendamment.

Reproduction : `git grep -n -E 'github_campaign_actions_registry|read_registry|validate_registry'
<SHA> -- .github scripts tests ha_tests docs README.md pyproject.toml`, AST,
inspection des entrées/copies et historique du candidat. Garde RED avant retrait,
GREEN après ; suites ciblées avant/après, Python/HA complètes, Ruff, liens,
diff-check et quatre CI au HEAD exact consignés dans la PR/#189. Les usages
privés externes non observables ne sont pas déclarés connus.

Diff B6 : ce seul script, son fichier de tests conservé/adapté et deux documents
de preuves. Aucun runtime, transport, moteur partagé, gate/workflow, fixture,
manifest/version ou script B2/B4 changé. Pas de CHANGELOG : modèle interne
non raccordé hors livrable HACS, sans changement du comportement du plugin.
Limites d'inodes/Docker locales rapportées, checkout sous /tmp. Tests réels
Hoben/HA **NOT RUN**, aucun dispatch/rerun live, secret/donnée privée, commande,
écriture Modbus, main/release/tag ni fusion DEV. Aucun autre candidat ou lot.

## Annexe B7 — retrait du lecteur de contenu Git Blob

Tâche `HOBEN-189-B7-REMAINING-LEGACY-CANDIDATE-AUDIT-009`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Candidat unique A1 : `scripts/github_campaign_workflow_blob.py`, hors B2/B4
et suppressions précédentes. Base `experimental` :
`e72aabcc4771ddaff52265cac793053d88206958` ; main lu seulement à
`1ec61b40615b481fe5da1b6e2b2c7590b4ff86e3`.
**Retirer ce seul modèle non raccordé ; conserver le transport, le lecteur
d'arbre et les contrôles d'intégrité/admission maintenus.**

| Symbole / consommateur | Preuve examinée | Décision / couverture |
| --- | --- | --- |
| `validate_workflow_blob`, `read_workflow_blob`, Expected/Observation | AST scripts/plugin/tests aux deux SHA : seul import dans test_github_campaign_workflow_blob.py, aucun helper de test importé ailleurs. Source absente de main ; pas de backend, token d'environnement ou CLI utile. | Retirer l'API de preuve de bytes introduite par #144 (`2a19df8f05fbea245b011ccef182df65f2f1c566`), sans producteur/consommateur opérationnel. |
| Dépendance envers workflow_tree | Le lecteur Blob importe le lecteur d'arbre et consomme sa projection, pas l'inverse. Les imports/appels d'arbre dans les tests restent conservés. | Source du lecteur d'arbre inchangée ; son test de non-raccordement perd seulement l'ancienne exception pour le consommateur Blob supprimé, ce qui resserre le garde. |
| Dynamique, subprocess, SourceBundle, YAML/fixtures, CLI/packaging, HACS/publication | Aucun appel opérationnel ou historique dans les points d'entrée ; seul import_module scripts/plugin = probe_opened_client_boundary. Processus à chemins fixes et bundle HA sans le lecteur. | Aucun autre script candidat examiné ou modifié. Absence fondée sur graphe et inspection, pas sur recherche textuelle seule. |
| 25 cas indépendants du transport/arbre | Deux campagnes avec vraie traversée d'arbre sur FakeHTTP puis GET du seul SHA sélectionné ; 17 routes refusées, 3 queries refusées, 3 JSON/token refusés. | **Conserver les 25 cas** dans [test_github_campaign_workflow_blob.py](../tests/test_github_campaign_workflow_blob.py), sans importer l'API retirée. Erreurs JSON/SECRET typées vérifiées directement, streams fermés ; preuve d'arbre toujours sans autorité. |
| 111 cas propres au modèle Blob | Enveloppe/base64, hash Git, pins, binding, double lecture/recheck et ancien garde source/CLI exclusivement de l'API retirée. Aucun helper partagé. | Retirer ces seuls cas ; nouveau garde d'absence du fichier/imports opérationnels/entrée YAML/packaging. Fichier conservé : 136 cas avant, 26 après (25 + garde). |
| Documents / preuves historiques | A1 et [section Blob](github-campaign-evidence.md) décrivent une preuve partielle d'identité des octets, sans sémantique YAML ou autorisation. Liens source/test épinglés avant retrait. | Contrat historique conservé comme archive, sans déclaration de workflow chargé, approuvé ou disponible sur main. |

### Garanties indépendantes maintenues

- [test_github_campaign_workflow_tree.py](../tests/test_github_campaign_workflow_tree.py) :
  chaîne commit/arbres/SHA, mauvais pins/ref/chemins refusés, recheck, projection
  figée, absence d'autorité/YAML chargé ; backend et source inchangés.
- [test_github_campaign_transport.py](../tests/test_github_campaign_transport.py) :
  GET allowlisté et TLS vérifié, token injecté, HTTP/403/redirect, pagination,
  tailles/délais, JSON tronqué/dupliqué, secret et contexte privé refusés.
  Les 25 cas spécifiques ci-dessus continuent de tester la route Git Blob.
- [test_github_campaign_evidence.py](../tests/test_github_campaign_evidence.py) et
  [test_campaign_minimal_admission.py](../tests/test_campaign_minimal_admission.py) :
  faits partiels sans can_start, observations cohérentes, contexte fermé et
  propriétaire ; aucune identité de bytes ne devient une autorisation.
- [test_info_manual_route_186.py](../tests/test_info_manual_route_186.py) :
  intégrité/provenance et refus de falsification des chemins actifs ; sources,
  manifestes d'intégrité et gates inchangés. Les protections HA #220/#212,
  0x0C, Ping/Pong, #160/#192 ne sont pas modifiées.

L'API inutilisée de preuve Git SHA-1/base64 n'est pas remplacée par une
attestation permissive. Le GET direct des tests reste une réponse opaque du
transport, pas une preuve de bytes/YAML chargés ou d'approbation. Sa borne
16 Kio/24 Kio base64 n'est transférée à aucun chemin ; transport existant
2 Mio/10 s et tous les budgets Hoben restent inchangés.

Reproduction : `git grep -n -E 'github_campaign_workflow_blob|read_workflow_blob|validate_workflow_blob'
<SHA> -- .github scripts tests ha_tests docs README.md pyproject.toml`, AST,
inspection des entrées/copies et historique du candidat. Garde RED avant
retrait puis GREEN, ciblés avant/après, suites Python/HA, Ruff, liens, diff-check
et quatre CI au HEAD exact consignés dans la PR/#189. Les usages privés
externes non observables ne sont pas déclarés connus.

Diff B7 limité à ce script, deux fichiers de tests et deux documents de preuves.
Sources du transport/arbre, moteurs, scripts B2/B4, runtime HA, gates/YAML,
fixtures, manifest/version inchangés. Pas de CHANGELOG : modèle interne non
raccordé hors livrable HACS, sans changement du comportement du plugin.
Limites d'inodes/Docker locales rapportées, checkout sous /tmp. Tests réels
Hoben/HA **NOT RUN** ; aucun dispatch/rerun live, donnée privée, commande,
écriture Modbus, main/release/tag/version ou fusion DEV. Aucun autre lot.
