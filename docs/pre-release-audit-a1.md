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

## Annexe C1 — coût et redondance du contrat de preuve HA offline

Tâche `HOBEN-189-C1-CI-TEST-REDUNDANCY-AUDIT-010`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Base `experimental` : `ea8ceb52db75703379e208546f6724a381c3a000`.
Famille unique : [tests/test_ha_session_proof.py](../tests/test_ha_session_proof.py),
neuf fonctions / **55 cas pytest**. Le nom historique `ha-persistent-c1`
désigne le schéma offline, distinct de cette tâche C1 de nettoyage #189.
**Conserver les 55 cas et leurs helpers : aucune équivalence permettant un
retrait n'est établie.** Audit documentaire uniquement, sans autre candidat.

### Matrice scénarios / assertions / décision

| Fonction test_* (suffixe) | Cas pytest / appels Node | Assertions distinctes conservées |
| --- | --- | --- |
| independent_validator_accepts_bounded_synthetic_evidence | 3 / 3 | Absence de perte, perte transport, CloseClient ; round-trip Python, acceptation Node indépendante, reconnexion SUCCESS/INCONCLUSIVE et absence de champs privés. |
| python_and_node_reject_malformed_or_forged_proof | 38 / 38 | Chaque tuple path/key/value est différent : clés privées, schéma/types, provenance/tentative, budgets, génération/séquence/perte/cleanup et critères falsifiés. Refus Python et Node, erreur fixe. |
| opening_alone_stale_read_and_unconfirmed_cleanup_never_prove_recovery | 1 / 2 | Deux preuves recevables mais INCONCLUSIVE : ouverture sans lecture décodée et cleanup non attesté ; recalcul des critères, acceptation du rapport honnête par Node. |
| not_run_and_partial_failure_are_separate_from_recovery_success | 1 / 2 | Aucune collection = NOT RUN ; collection interrompue = FAILURE même avec reprise prouvée. Deux rapports distincts, pas deux succès de reconnexion. |
| input_limits_and_errors_do_not_echo_rejected_content | 6 / 6 | Objet incomplet, liste, null, JSON tronqué, texte privé synthétique, entrée de 8193 octets ; erreurs fixes des deux parseurs. |
| canonical_encoding_rejects_duplicate_keys_and_noncanonical_numbers | 1 / 3 | Espace initial, clé dupliquée, nombre 1.0 : trois formes wire distinctes rejetées en Python et Node. |
| unknown_numeric_close_subcodes_remain_payload_free | 2 / 2 | Bornes UInt8 0 et 255 recevables sans inventer une signification au sous-code. |
| terminal_evidence_cannot_be_erased_in_later_samples | 2 / 2 | Deux témoins terminaux différents, cleanup_failed et stopped, ne peuvent disparaître dans un échantillon ultérieur. |
| six_report_slots_and_budget_reserve_are_bounded | 1 / 1 | Septième slot refusé ; six échéances uniques/ordonnées et réserves connexion/lecture/cleanup sous les plafonds Python. |

Les **59 entrées Node sont byte-distinctes** dans chaque mesure ; aucun doublon
exact de corps AST entre les neuf fonctions n'est relevé. Cela ne prouve pas
que chaque cas est indispensable : des entrées différentes peuvent exercer
une même branche. L'inspection n'établit cependant pas de remplacement
conservant toutes les assertions, bornes, erreurs et indépendances ci-dessus.
Les assertions Python/Node ne sont pas interchangeables :
[ha_session_proof.py](../scripts/ha_session_proof.py) et
[ha-session-proof.cjs](../scripts/ha-session-proof.cjs) sont deux validateurs
distincts, chacun utilisant sa bibliothèque de preuves dans son langage.
Un verdict identique n'est pas une preuve de duplication d'implémentation.

### Consommateurs et chemins de découverte

AST des modules scripts/plugin/tests/ha_tests et inspection des appels :
[test_ha_live_proof.py](../tests/test_ha_live_proof.py) importe ROOT/proof ;
[ha_tests/test_ha_session_proof.py](../ha_tests/test_ha_session_proof.py) importe
node_accepts ; [ha_session_collector.py](../ha_tests/ha_session_collector.py)
consomme LIMITS/REFRESH_AT_MS/build_report/project_observation. Le test HA
soumet les rapports du vrai client/coordinator sur transports simulés ; il
ne remplace pas les mutations de schéma synthétiques de cette famille.
Le contrat C2a testé dans test_ha_live_proof possède un autre schéma et refuse
les rapports C1, et réciproquement : aucun remplacement global prouvé.

Le `require('./scripts/ha-session-proof.cjs')` embarqué dans `node -e` est un
consommateur dynamique réel, invisible à un graphe d'imports Python seul.
Subprocess reçoit uniquement le rapport synthétique par stdin, capture les
sorties et exige un vocabulaire d'erreur fixe. Le validateur Node et ses
imports font de la validation JSON, sans réseau, CLI live ou accès Actions.
`tests/conftest.py` interdit les connexions/DNS Python. La découverte reste
`pyproject.toml` → tests ; le job HA collecte séparément ha_tests avec ses
fixtures d'isolation. Les quatre jobs de validate.yml restent inchangés.

### Mesures reproductibles et limites

Hôte local, checkout sous /tmp, Python **3.12.14**, Node **v24.19.0** ; cache
pytest désactivé, bytecode désactivé. Trois processus Python frais par série,
sans suite concurrente ; caches OS non purgés. Le profil temporaire entoure
subprocess.run sans modifier ses arguments, entrées, sorties ou verdicts :
temps monotone autour du vrai appel et SHA256 en mémoire de chaque stdin,
aucun rapport/valeur publié. Chaque run : 55 PASS, 59 appels, 59 entrées uniques.

| Série | Temps mural Python, secondes (3 runs) | Somme des appels Node, secondes | Médiane murale |
| --- | --- | --- | --- |
| Avant annexe | 2.151 / 2.135 / 2.160 | 1.956 / 1.962 / 1.994 | 2.151 s |
| Après annexe | 2.075 / 2.203 / 2.167 | 1.899 / 2.038 / 2.007 | 2.167 s |

Les appels Node mesurent ensemble lancement, chargement, parsing, validation
et échange stdin/stdout ; ce n'est pas une mesure du démarrage Node isolé.
Le résultat ne permet aucune extrapolation au runner CI ni au coût total des
quatre jobs. Aucune accélération n'est revendiquée : tests inchangés ; les
écarts avant/après relèvent d'une mesure locale sans changement exécutable.
Batcher les rapports ou partager un processus Node changerait l'isolation
actuelle ; aucune équivalence ni modification de helper proposée dans C1.

Reproduction du ciblé standard, à répéter trois fois avant/après :

```sh
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider --durations=10 tests/test_ha_session_proof.py
```

Pour compter et chronométrer les vrais appels sans afficher leur contenu,
exécuter dans le même environnement depuis la racine (un processus par run) :

```python
import hashlib
import subprocess
import time
from unittest.mock import patch
import pytest

calls = []
original = subprocess.run


def measure(*args, **kwargs):
    command = args[0] if args else kwargs.get("args", [])
    if not command or command[0] != "node":
        return original(*args, **kwargs)
    start = time.perf_counter()
    result = original(*args, **kwargs)
    calls.append(
        (time.perf_counter() - start, hashlib.sha256(kwargs["input"].encode()).digest())
    )
    return result


start = time.perf_counter()
with patch.object(subprocess, "run", measure):
    status = pytest.main(
        [
            "-q",
            "-p",
            "no:cacheprovider",
            "--durations=10",
            "tests/test_ha_session_proof.py",
        ]
    )
print(
    status,
    time.perf_counter() - start,
    len(calls),
    sum(t for t, _ in calls),
    len({h for _, h in calls}),
)
raise SystemExit(status)
```

Vérifications complémentaires : imports AST, rg ha_session_proof/ha-session-proof
sur scripts/plugin/tests/ha_tests/YAML/fixtures, inspection du contrat C1 et de
ses consommateurs cités. Aucun autre groupe audité ni supprimé. Ciblés de
compatibilité, suites Python/HA, Ruff, liens, diff-check et quatre CI au HEAD
exact consignés dans la PR/#189 ; limites Docker/inodes locales rapportées.
Pas de RED/GREEN de retrait : aucun retrait. Pas de nouveau test miroir.
Tous les fichiers exécutables/tests/fixtures/gates/workflows restent
byte-identiques à la base, notamment #220/#212/0x0C/Ping-Pong/#160/#192/#186.
Pas de CHANGELOG : audit interne sans impact livrable HACS/API/comportement.
Tests réels Hoben/HA **NOT RUN** ; aucun dispatch/rerun live, donnée privée,
commande/écriture Modbus, main/release/tag/version ou fusion DEV. Revue MANAGER,
puis arrêt ; aucune deuxième famille ou tâche auto-attribuée.

## Annexe C2 — coût et redondance du validateur de preuve HA inactive

Tâche `HOBEN-189-C2-CI-LIVE-PROOF-OFFLINE-REDUNDANCY-AUDIT-011`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Base `experimental` : `300be14aa67652d6d7f08bf5f11896550e9a5c6b`.
Famille unique : [tests/test_ha_live_proof.py](../tests/test_ha_live_proof.py),
neuf fonctions / **54 cas pytest**, entièrement synthétiques malgré « live »
dans le nom. **Conserver les 54 cas et tous les helpers** : aucune équivalence
complète permettant un retrait démontrée. Aucun autre groupe audité.

### Matrice scénarios / assertions / décision

| Fonction test_* (suffixe) | Cas pytest / appels Node | Assertions distinctes conservées |
| --- | --- | --- |
| actual_evidence_contract_is_distinct_from_c1_and_never_admitted | 2 / 2 | Avec/sans reprise : round-trip Python et acceptation Node du schéma C2a, issue FAILURE/INCONCLUSIVE ; rejet Python croisé des schémas C1/C2a. |
| local_stop_cannot_claim_natural_reconnection | 5 / 5 | cancelled/timeout/memory/processes/worker_failure : le reçu externe d'arrêt local empêche un succès de reconnexion, même avec preuve de reprise antérieure. |
| missing_confinement_is_not_run_without_invented_cleanup | 1 / 1 | Aucun démarrage/réapage : tous les critères et l'issue restent NOT RUN, sans inventer de cleanup. |
| forged_private_or_inconsistent_reports_are_rejected | 27 / 27 | Tuples path/key/value distincts : enveloppe/admission/provenance, mémoire/PID/délais/réseau/réapage, générations/séquences/cleanup, sous-code et critères falsifiés. Refus Python/Node à erreur fixe. |
| invalid_input_is_bounded_and_never_echoed | 5 / 5 | Objet incomplet, null, liste, texte privé synthétique et 8193 octets : refus borné des deux parseurs sans écho du contenu. |
| canonical_encoding_and_evidence_cannot_override_parent_receipt | 1 / 2 | Espace initial et clé dupliquée refusés par Python/Node ; build_report refuse en plus une preuve enfant qui tente d'injecter supervisor. |
| final_timestamp_cannot_forge_completion | 4 / 4 | 250000/299999 ms sous la fenêtre utile, 330000/360000 ms à/au-delà de sa limite de collecte : refus de completed en Python/Node. |
| final_witness_and_clock_are_independently_validated | 8 / 8 | Horloge live/monotonic sans reçu cohérent, durée booléenne, témoin absent/inactif/régressif, sixième slot trop tôt et premier slot décalé. |
| monotonic_window_needs_corresponding_parent_duration | 1 / 1 | Contrôle positif distinct : fenêtre monotone recevable avec durée externe 309000 ms, contrairement au reçu de 1000 ms du cas négatif. |

Les 55 entrées Node sont byte-distinctes dans chaque passage ; neuf corps de
fonctions AST distincts, sans doublon strict relevé. Ce comptage ne démontre
pas que chaque branche est indépendante ou chaque cas indispensable. Les
refus identiques ne prouvent pas l'équivalence des contraintes qui les causent.
Aucun remplacement conservant toutes les assertions de la matrice n'est établi.

### Helpers, consommateurs et distinction du contrat C1

AST scripts/plugin/tests/ha_tests : receipt/report/PROVENANCE/node_accepts sont
importés par six modules Python de tests (campagnes, dual, récupération,
manuel, sandbox, supervision) et quatre modules HA (dual, observer, campagne
manuelle, [rapport #212](../ha_tests/test_three_request_report_212.py)).
Le [test HA observer](../ha_tests/test_ha_live_observer.py) soumet aussi les
rapports issus du vrai client/coordinator sur transports simulés. Ces scénarios
ne remplacent pas la matrice de mutations du schéma synthétique ; aucun helper
déplacé, aucun consommateur supprimé.

Les fixtures de cette famille réutilisent proof/ROOT du test C1 conservé, mais
le schéma 2 ajoute reçu externe, at_ms/window, continuous_300s et supervision.
Le schéma C1 n'atteste pas ces garanties. Les deux cas de rejet croisé testent
explicitement leur incompatibilité en Python, sans revendiquer une admission
GitHub ni un résultat réel.

[ha_live_proof.py](../scripts/ha_live_proof.py) et
[ha-live-proof.cjs](../scripts/ha-live-proof.cjs) recalculent séparément les
critères dans chaque langage. Le require embarqué dans node -e est un vrai
consommateur dynamique, avec stdin synthétique et sorties/erreur fixes.
Le module Python est utilisé par supervisor/guard/observer/worker,
ha_manual_live_report et ha_campaign_evidence, et copié par SourceBundle.
Les rapports [moderne](../.github/scripts/campaign-report.cjs) et
[historique](../.github/scripts/ha-manual-live-report.cjs) importent le validateur
Node : validateObservation et validateReport
ont des responsabilités différentes ; « inactive » ne signifie pas inutilisé.
Inspection seulement de ces dépendances, sans autre famille candidate ni
exécution de campagne. Découverte pytest, conftest et quatre jobs inchangés.

### Mesures locales reproductibles, aucune accélération revendiquée

Même méthode temporaire que l'annexe C1 : vrais appels subprocess.run entourés
d'un chronomètre monotone et de SHA256 des stdin en mémoire, sans publication
du contenu ni modification des verdicts. Python **3.12.14**, Node **v24.19.0**,
checkout sous /tmp ; bytecode/cache pytest désactivés ; trois processus frais
par série, sans suite concurrente, caches OS non purgés. Chaque passage :
54 PASS, 55 appels Node et 55 entrées uniques.

| Série | Temps mural Python, secondes (3 runs) | Somme des appels Node, secondes | Médiane murale |
| --- | --- | --- | --- |
| Avant annexe | 2.057 / 1.975 / 2.069 | 1.868 / 1.795 / 1.882 | 2.057 s |
| Après annexe | 2.018 / 2.155 / 2.020 | 1.834 / 1.944 / 1.852 | 2.020 s |

Reproduction du ciblé :

```sh
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider --durations=10 tests/test_ha_live_proof.py
```

Pour les mesures instrumentées, reprendre l'extrait Python de l'annexe C1 avec
le seul argument de sélection remplacé par tests/test_ha_live_proof.py, trois
fois avant/après. La somme Node inclut lancement, chargement, parsing,
validation et échanges ; ce n'est pas une mesure du démarrage seul ni un coût
CI isolé. Tests inchangés : les écarts ne démontrent aucun gain. Aucun batching,
cache de verdict ou partage de processus Node proposé sans équivalence.

Diff C2 : cette annexe seulement ; audit antérieur intact, tous tests/helpers,
fixtures, scripts de preuve/runtime, protocole/TLS, gates/workflows/permissions,
manifest/version byte-identiques à la base. Suites ciblées et Python/HA,
Ruff/diff-check, liens et quatre CI au HEAD exact consignés dans la PR/#189,
avec les limites Docker/inodes locales. Aucun RED/GREEN de retrait : aucun
retrait, aucun test miroir ajouté. Pas de CHANGELOG : audit interne sans impact
livrable HACS/API/comportement. Tests réels Hoben/HA **NOT RUN** ; aucun
dispatch/rerun live, donnée privée, commande/écriture Modbus, main/release/tag
ou fusion DEV. Revue MANAGER puis arrêt, aucune autre tâche auto-attribuée.

## Annexe C3 — réexamen de la famille déjà auditée C1

Tâche `HOBEN-189-C3-CI-HA-SESSION-PROOF-REDUNDANCY-AUDIT-012`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Base `experimental` : `1d759d6b4d36bf2b6d50e02fda236dbf00edd115`.
Famille unique : [tests/test_ha_session_proof.py](../tests/test_ha_session_proof.py).
**Même famille que C1 ; conserver ses 55 cas et tous ses helpers.**

Depuis la base C1 `ea8ceb52db75703379e208546f6724a381c3a000`, le seul fichier
modifié est ce document d'audit. Le test a toujours le blob Git
`6522a619a6cb3352442d339d13dffe5142917964` ; validateurs Python/Node,
bibliothèques de preuves, collecteur et test HA consommateurs inchangés.
La matrice des neuf fonctions / 55 cas / 59 appels de l'annexe C1 reste
applicable ; elle n'est pas recopiée comme un nouveau résultat de couverture.

Réexamen AST actuel : neuf corps de fonctions distincts et 38 tuples INVALID
distincts. proof/ROOT restent importés par test_ha_live_proof ; node_accepts
par le test HA ; ha_session_collector consomme encore le contrat Python.
Le require embarqué charge ha-session-proof.cjs puis ha-session-evidence.cjs,
sans entrée live ni appel Actions. Le garde réseau Python et les assertions
de sorties/erreur fixes restent en place ; mesures limitées aux fixtures
synthétiques, sans publication des stdin, données ou exceptions rejetées.

Python et Node valident séparément schéma/provenance/budgets, causalité de
reprise, cleanup, critères et JSON canonique. L'acceptation d'une preuve
INCONCLUSIVE honnête ne remplace pas le refus d'une preuve falsifiée. Des
tuples/entrées distincts ne prouvent pas des branches indépendantes ; aucune
équivalence complète de couverture autorisant un retrait n'est établie ici.
Les limites de preuve et la décision de conservation C1 sont maintenues.

Nouvelles mesures C3, Python **3.12.14** / Node **v24.19.0**, checkout recréé
sous /tmp après disparition du précédent : reproducteur de l'annexe C1,
bytecode/cache pytest désactivés, trois processus frais par série sans suite
concurrente, caches OS non purgés. Chaque passage : **55 PASS, 59 appels Node
et 59 entrées byte-distinctes**. Temps monotone et SHA256 en mémoire ; vrais
appels/verdicts inchangés, aucun rapport affiché.

| Série C3 | Temps mural Python, secondes (3 runs) | Somme des appels Node, secondes | Médiane murale |
| --- | --- | --- | --- |
| Avant annexe | 1.959 / 2.143 / 1.949 | 1.783 / 1.960 / 1.765 | 1.959 s |
| Après annexe | 2.150 / 1.957 / 2.134 | 1.921 / 1.793 / 1.975 | 2.134 s |

Reproduction : même commande et extrait Python que C1, sélection exacte
tests/test_ha_session_proof.py. Les temps Node incluent lancement, chargement,
parsing, validation et échanges, sans coût de démarrage isolé ni extrapolation
CI. Aucun gain revendiqué, aucun batching/cache ou changement d'isolation.

Diff C3 limité à cette annexe ; aucune autre famille ni suppression. Tous
tests/helpers/fixtures, contrats de preuve, runtime/V4/TLS, workflows/gates,
permissions, manifest/version inchangés. Ciblés, suites Python/HA, Ruff,
liens/diff-check et quatre CI au HEAD exact consignés dans la PR/#189, avec
les limites Docker/inodes locales. Aucun RED/GREEN de retrait : aucun retrait ;
aucun test miroir. Pas de CHANGELOG : audit interne sans impact HACS/API ou
comportement. Tests réels Hoben/HA **NOT RUN** ; aucun dispatch/rerun live,
commande/écriture Modbus, secret/GUID/RX/donnée privée, main/release/tag/version
ou fusion DEV. Revue MANAGER puis arrêt ; aucune autre tâche auto-attribuée.

## Annexe C4 — preuves produites par le vrai chemin HA synthétique

Tâche `HOBEN-189-C4-CI-HA-SESSION-OFFLINE-REDUNDANCY-AUDIT-013`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Base `experimental` : `f742530926193782a3be76a99d67b2f2c6a5c072`.
Famille unique : [ha_tests/test_ha_session_proof.py](../ha_tests/test_ha_session_proof.py),
**sept fonctions async / 12 cas HA**, distincte du test de parseur audité C1/C3.
**Conserver les 12 cas et tous les helpers** : aucune équivalence complète
autorisant un retrait établie. Aucun autre groupe audité ou supprimé.

### Matrice scénarios / assertions / couverture conservée

| Fonction test_* (suffixe) | Cas HA / appels Node | Garanties exercées sur les vrais objets HA/client/coordinator |
| --- | --- | --- |
| healthy_real_ha_path_one_tls_no_reconnection_claim | 1 / 1 | Observation initiale sans I/O, immuabilité, six lectures corrélées sur une seule session, vrai décodage HA, génération/séquence, pas de faux succès de reconnexion. |
| observed_loss_cleanup_new_generation_and_correlated_ha_read | 3 / 3 | CloseClient fragmenté, TransportEOF, TransportTlsError ; cleanup de la génération perdue, deuxième ouverture puis vraie lecture décodée ; type de perte/sous-code et émissions allowlistées. |
| cancel_propagates_after_cleanup_with_partial_failure_proof | 4 / 4 | Annulation pendant opening/TX/RX/backoff, propagation de CancelledError après cleanup, rapport partiel FAILURE/INCONCLUSIVE, aucune réouverture ou tâche orpheline. |
| read_timeout_recovery_is_not_natural_loss_evidence | 1 / 1 | Expiration déterministe du vrai timeout à un await ; fermeture et backoff contrôlés, cinq nouvelles lectures décodées sans fabriquer de perte naturelle ni succès de reconnexion. |
| cleanup_error_cannot_be_reported_success | 1 / 1 | Erreur réelle de fermeture sur double transport : cleanup_failed et critère FAILURE, pas de faux cleanup réussi. |
| correlated_wire_read_without_ha_decode_is_not_success | 1 / 1 | Décodeur HA qui refuse : séquence de lecture avance mais aucune data publiée/décodée ; réutilisation et issue restent FAILURE. |
| absolute_window_cuts_off_before_next_slot_without_more_io | 1 / 1 | Horloge synthétique à 300 s : un seul slot, aucun refresh supplémentaire, collection FAILURE et cleanup attesté. |

Chaque cas conserve aussi le round-trip Python et le validateur Node indépendant,
la borne 8192 octets, l'absence d'identifiants/contenus synthétiques privés dans
rapport et caplog, execution=offline/system_enforcement=NOT RUN/boundary_proven=false.
assert_stopped vérifie fermeture unique, identité acceptée effacée et absence
de tâches lifecycle/RX encore actives. Les sept corps AST sont distincts.

### Rapports répétés ne signifiant pas tests interchangeables

Chaque mesure relève **12 appels Node / 10 stdin distincts** (SHA256 en mémoire).
Les seuls groupes répétés, dans chacun des six passages :

- loss1/loss2 : EOF et erreur TLS produisent la même projection publique
  catégorielle transport ; les exceptions injectées restent différentes ;
- tx/rx : le même rapport partiel suit une annulation pendant deux attentes
  différentes, write bloqué et lecteur RX bloqué.

Ces répétitions portent sur les octets du rapport transmis au parseur, pas sur
le chemin async, les effets HA ou le cleanup vérifiés avant/après. Supprimer un
cas entier retirerait l'une des injections/attentes. Les autres suites de
parseur ne construisent pas ce chemin HA ni ce collecteur. Un cache de verdict
ou un processus Node partagé changerait l'isolation actuelle ; aucune telle
modification ni accélération n'est proposée sans équivalence démontrée.

### Fixtures et dépendances vérifiées

[ha_session_collector.py](../ha_tests/ha_session_collector.py) reçoit de vrais
HobenClient/HobenDataUpdateCoordinator frais, appelle async_refresh et projette
SessionObservation ; clock/sleep injectés accélèrent six slots, pas 300 s réelles.
Le collecteur possède son cutoff/cleanup et son rapport partiel, que les seuls
tests de schéma C1/C2 ne remplacent pas.
AST et recherche d'appels : ce fichier de test est son seul importeur dans le
dépôt ; aucun import entrant des helpers de la famille C4. Cela ne prouve pas
que ces tests ou ce collecteur sont inutiles : pytest les découvre directement.

Fixtures importées depuis [test_persistent_client.py](../ha_tests/test_persistent_client.py) :
peers construit les vrais propriétaires avec transport en mémoire et backoff
contrôlé ; assert_stopped est partagé et reste intact. Ce chemin de régression
historique garde ha_fast_reconnect=false dans la fixture, sans changer la
politique de production. [Conftest HA](../ha_tests/conftest.py) interdit un
transport Hoben réel et utilise le blocage sockets/DNS du harness, identités
inventées et nettoyage HA. [pytest.ini](../ha_tests/pytest.ini) définit la
découverte/asyncio HA séparée. Le require Node est celui du helper C1 importé,
pas une campagne live. Aucun changement de fixture, collecteur ou runtime.

### Coût local reproductible et limites

Python HA **3.14.7**, Node **v24.19.0**, même environnement et checkout sous /tmp,
trois processus Python frais par série sans suite concurrente ; bytecode/cache
pytest désactivés, caches OS non purgés. Chaque passage : **12 PASS**. Profil
temporaire autour des vrais subprocess.run Node, chronomètre monotone, hash en
mémoire ; appels/arguments/rapports/verdicts inchangés, aucun contenu publié.

| Série | Temps autour de pytest.main, secondes (3 runs) | Somme des appels Node, secondes | Médiane murale |
| --- | --- | --- | --- |
| Avant annexe | 5.878 / 4.896 / 5.186 | 0.458 / 0.399 / 0.432 | 5.186 s |
| Après annexe | 5.360 / 4.991 / 4.884 | 0.428 / 0.412 / 0.368 | 4.991 s |

Reproduction depuis la racine dans l'environnement HA :

```sh
PYTHONDONTWRITEBYTECODE=1 python -m pytest -c ha_tests/pytest.ini -q -p no:cacheprovider --durations=10 ha_tests/test_ha_session_proof.py
```

Le reproducteur Python C1 s'adapte uniquement en sélectionnant ce fichier avec
-c ha_tests/pytest.ini et l'interpréteur HA ; un hook pytest_runtest_setup relève
le nodeid courant pour grouper les hashes égaux sans afficher les stdin.
Temps autour de pytest.main incluant chargement des plugins, collecte,
fixtures/setup/tests/teardown HA, hors démarrage de l'interpréteur et import
initial de pytest ; somme Node incluant lancement/chargement/parsing/validation/
échanges. Ce ne sont pas des mesures isolées de démarrage, de chaque fixture
ou du coût CI. Aucun gain
revendiqué : code inchangé, répétitions de rapports conservées et expliquées.

Diff limité à cette annexe ; audit antérieur, tous tests/helpers/fixtures,
contrats, runtime/V4/TLS, workflows/gates/permissions, manifest/version inchangés.
Ciblés, suites Python/HA, Ruff, liens/diff-check et quatre CI au HEAD exact
consignés dans la PR/#189, avec limites locales. Aucun RED/GREEN de retrait :
aucun retrait ; aucun test miroir. Pas de CHANGELOG : audit interne sans impact
HACS/API/comportement. Tests réels Hoben/HA **NOT RUN** ; aucun dispatch/rerun
live, commande/écriture Modbus, secret/GUID/RX/donnée privée, main/release/tag
ou fusion DEV. Revue MANAGER puis arrêt ; aucune autre tâche auto-attribuée.

## Annexe C5 — coût observé du workflow Validate, préparation et caches

Tâche `HOBEN-189-C5-CI-OFFLINE-WORKFLOW-DURATION-AUDIT-014`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Base `experimental` : `73a96f2f072a3b09aea1d2414c73ddd24c84832d`.
Périmètre unique : [Validate](../.github/workflows/validate.yml), sa préparation,
ses actions et [groupes de dépendances](../pyproject.toml), sans réaudit C1–C4.
**Conserver le workflow et les quatre jobs : aucun gain sûr mesuré justifiant
un changement de préparation/cache ou la suppression d'un contrôle.**

### Exécutions existantes et méthode

Quatre runs pull_request, tentative 1, quatre jobs SUCCESS chacun, consultés
sans dispatch/rerun. Les contenus Validate et pyproject sont identiques aux
quatre HEAD sources et à la base ; blobs Git respectifs
`5f038c01c6be41dd8eb4a72c6cc78e77e6f7f473` et
`9f09dc7dee61904656e1bbc69aa01febe93d9b95`.
Les PR sont documentaires ; runner, versions résolues et réseau ne sont pas
contrôlés comme dans une expérience comparative de cache.

Durées en secondes, timestamps REST started_at/completed_at des jobs/étapes :

| Run / HEAD source abrégé | tests | ha-tests | hacs | hassfest | Fenêtre des quatre jobs | Somme des durées jobs |
| --- | --- | --- | --- | --- | --- | --- |
| [44854425100](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/44854425100) / d1536e6 | 222 | 202 | 33 | 17 | 223 | 474 |
| [44858023072](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/44858023072) / 4cfd3cb | 257 | 182 | 33 | 16 | 257 | 488 |
| [44860403780](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/44860403780) / 9c03094 | 281 | 342 | 32 | 18 | 343 | 673 |
| [44864460143](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/44864460143) / 3a86973 | 184 | 320 | 37 | 15 | 320 | 556 |

Fenêtre = dernier completed_at moins premier started_at des quatre jobs,
hors attente initiale de runner ; médiane **288,5 s**, somme médiane **522 s**.
Les jobs sont indépendants/parallèles, pas quatre étapes séquentielles.
La somme n'est ni une latence, ni du CPU, ni une facture GitHub. Les timestamps
à la seconde et les intervalles entre étapes expliquent des écarts avec leurs
sommes ou le temps interne affiché par pytest ; un 0 s n'est pas un travail nul.

| Étape / job | Min / médiane / max, secondes |
| --- | --- |
| pip install --upgrade pip / tests | 1 / 3 / 6 |
| pip install --group dev / tests | 2 / 4 / 5 |
| python -m pytest / tests | 177 / 221,5 / 268 |
| pip install --upgrade pip / ha-tests | 1 / 3,5 / 5 |
| pip install --group ha-test / ha-tests | 39 / 49 / 78 |
| pytest HA / ha-tests | 136 / 199,5 / 256 |

setup-python prend 0–1 s, checkout 1–6 s et chaque Ruff 0–1 s dans cet
échantillon. Pull HACS : 16–24 s ; action Hassfest : 11–14 s. Ni HACS ni
Hassfest n'est le dernier job terminé ici. Les tests dominent les jobs Python ;
l'installation HA est le plus gros poste de préparation observé. Ces chiffres
ne prouvent ni une étape inutile ni un gain causal d'une modification future.

### Dépendances, isolation et caches

Les jobs Python ont des runners/environnements distincts : CPython 3.12/dev
et 3.14/ha-test. Les deux installations ne sont pas un doublon dans un même
environnement. Le groupe dev utilise des plages de versions, le harness HA
est épinglé mais ses dépendances ne constituent pas un lock CI complet.
Le pip upgrade est distinct de ces installations ; son retrait demanderait
une preuve de compatibilité de pip avec --group sur tous les runners admis.

Validate n'active ni cache setup-python ni action de cache explicite. Cela
ne prouve pas l'absence de caches natifs pip/outils préinstallés du runner.
Le run C4 résout notamment CPython 3.12.16 et 3.14.10 ; les sélecteurs YAML
3.12/3.14, @v7, @main et @master ne sont pas des pins de tous les exécutables.
Les actions réellement téléchargées sont relevées dans les logs, sans les
modifier : setup-python `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0`, checkout
`3d3c42e5aac5ba805825da76410c181273ba90b1`, HACS
`1ebf01c408f29afcb6406bd431bc98fd8cbb15aa`, Hassfest
`07f46fd2e19967768b5fd3000f91f857452b767c` pour C4 seulement.

Sources setup-python à ce SHA : [inputs](https://github.com/actions/setup-python/blob/6d4fd22b20465ccc0f7354476588e8df7c9ca0e0/action.yml),
[activation conditionnelle](https://github.com/actions/setup-python/blob/6d4fd22b20465ccc0f7354476588e8df7c9ca0e0/src/setup-python.ts),
[cache pip](https://github.com/actions/setup-python/blob/6d4fd22b20465ccc0f7354476588e8df7c9ca0e0/src/cache-distributions/pip-cache.ts).
L'action ne restaure un cache que si cache est demandé. Le cache pip porte sur
pip cache dir, pas sur un venv installé. Sa clé inclut OS/architecture/Linux,
version Python, gestionnaire et hash des dépendances ; une clé de repli peut
restaurer des archives sans le même hash. Une restitution ne doit donc jamais
remplacer installation/résolution ni validations.

Le glob par défaut est `**/requirements.txt` avant repli : le seul fichier ainsi
nommé ici est scripts/ha_session_runtime/requirements.txt, pour l'image Docker,
alors que les commandes CI installent les groupes du pyproject. Un futur essai
devrait expliciter `cache-dependency-path: pyproject.toml` et vérifier invalidation,
portée PR/branche, isolation 3.12/3.14 et restauration partielle. Aucun essai
froid/chaud, coût de transfert/sauvegarde ou taux de hits n'est observé ici :
**aucun gain de cache revendiqué, aucune activation proposée dans C5**.

Les dépendances exécutées ne se limitent pas aux commandes pip :
[HACS](https://github.com/hacs/action/blob/1ebf01c408f29afcb6406bd431bc98fd8cbb15aa/action.yml)
utilise Docker ghcr.io/hacs/action:main ;
[Hassfest](https://github.com/home-assistant/actions/blob/07f46fd2e19967768b5fd3000f91f857452b767c/hassfest/action.yml)
est une action composite qui lance l'image Hassfest via Docker. Un SHA d'action
ne rend pas ces tags d'image immuables. Préparation Actions/pip/validations peut
utiliser Internet ; « offline » signifie aucun Hoben/HA domestique, pas airgap.
Aucun workflow live, environnement, approbation ou protection n'est inspecté
pour être modifié ou utilisé par ce lot.

### Reproduction, validation et décision

Lecture REST de actions/runs/{id}, actions/runs/{id}/jobs?per_page=100 et des
logs de chaque job ; vérifier HEAD/événement/tentative/quatre conclusions puis
soustraire les timestamps UTC. Pour la fenêtre, prendre max des fins moins min
des débuts, indépendamment de l'ordre de la liste des jobs. Pour les médianes
de quatre valeurs, moyenne des deux centrales triées. Recontrôler les fichiers
aux SHA sources ; ne pas déduire un coût manquant d'une valeur absente.

Conserver quatre jobs/noms/commandes, déclencheurs, contents:read par job,
persist-credentials:false, absence de secrets/environnements réels et tests
intégraux. Diff limité à cette annexe ; aucun test, dépendance, YAML, cache,
runtime/protocole, permission, gate, manifest/version modifié. Cohérence des
mesures, liens, invariant statique Validate, Ruff/diff-check et quatre CI au
HEAD exact consignés dans la PR/#189. Suites complètes locales non relancées
pour cet audit documentaire ; la CI les exécute. Pas de CHANGELOG : audit
interne sans impact HACS/API/comportement, pas d'accélération revendiquée.
Tests réels **NOT RUN** ; aucun dispatch/rerun, commande/écriture Modbus,
secret/GUID/RX/donnée privée, main/release/tag ou fusion DEV. Revue MANAGER
puis arrêt ; aucune optimisation ou tâche suivante auto-attribuée.

## Annexe D2 — cohérence du guide DataUpdated avec le code actuel

Tâche `HOBEN-189-D2-DATAUPDATED-DIAGNOSTIC-DOC-CONSISTENCY-016`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Base `experimental` : `28e20e428961018c7a79dcb80713ee85ec86fc08`.
Document unique audité : [data-updated-recovery.md](data-updated-recovery.md).
**Conserver le guide à l'octet : aucune divergence factuelle établie sur les
flux ciblés.** Cette annexe est la sortie documentaire de conservation prévue
par la consigne, sans correction cosmétique ni nouveau fait protocolaire.

| Affirmation vérifiée | Source actuelle en lecture seule / conclusion |
| --- | --- |
| Livraison entière 0x1B sur framer libre et propriétaire RX valide ; forme publiable FFFF/unité 1/04/20 UInt16 | [v4_session.py](../custom_components/hoben/v4_session.py) : _delivery_drop_allowed et _consume_data_updated_delivery ; _candidate_words du [module shadow](../custom_components/hoben/shadow_data_updated.py). Les autres formes ne deviennent pas une acquisition. |
| Invalides admis abandonnés sans scan, garde #160 ni reset de délai ; erreurs decode/callback bornées | Même session : retour après diagnostic parser_failure/decode_failed/callback_failed ; les contrôles transport/ownership et la récupération des frontières non admissibles restent distincts. |
| Publication par snapshot/décodeur existants, génération et ordre local ; notification retenue avant initiale | Session → callback → [client.py](../custom_components/hoben/client.py) : _receive_data_updated et _async_refresh_once, garde de génération initialisée, latest_data_updated et conservation du timestamp reçu. Une notification ne valide pas le waiter 0x0E. |
| Initiale par génération, cache sans nouvelle fraîcheur, aucun polling périodique de l'entrée push | [__init__.py](../custom_components/hoben/__init__.py) active push_updates ; client distingue tentative/initiale ; [coordinator.py](../custom_components/hoben/coordinator.py) utilise update_interval=None en push et conserve l'heure reçue. Les réessais #212 et le setup borné ne sont pas une nouvelle cadence. |
| Connexion active sans notification ; fenêtre de perte unique de 300 s, stricte après la borne | Coordinator : _session_changed, last_snapshot_held, snapshot_available et _expire_connection_hold ; pas d'extension par simple ouverture/cache, arrêt/refus terminal/cleanup non attesté prioritaires. |
| DEBUG privé explicite et borné, distinct de l'export support ; FIFO historique indépendant | observe_applied_data_updated exige DEBUG sur son logger, conserve le marqueur owner_validated et le JSON borné à 8192 octets ; [diagnostics.py](../custom_components/hoben/diagnostics.py) reste une projection sans valeurs du foyer. Aucune activation réelle effectuée. |

Le guide annonce la priorité de #219-005 et de la disponibilité #219-006,
puis ouvre explicitement « Historique » pour les étapes antérieures au 19/11.
Les mentions de polling, mapping candidat et absence de mutation HA dans ces
archives ne sont pas des interdictions actuelles du push. La branche sans
callback de publication garde son observation historique ; le mode push publie
sur le chemin distinct vérifié ci-dessus. Aucune réécriture de l'historique,
des autorisations ni des limites de preuve ne s'impose sur cette comparaison.

Validation ciblée existante : [tests push](../tests/test_data_updated_push_219.py),
frontières/livraisons et silence/récupération ; [tests HA push](../ha_tests/test_data_updated_push_219.py)
sur vrais client/session/coordinator et horloges/transports simulés. Résultats,
liens, cohérence des références, Ruff/diff-check et quatre CI au HEAD exact
consignés dans la PR/#189. Les sources seules ne prouvent ni mapping universel,
frontière TLS/message, timestamp serveur, anti-rejeu ou validation HA installée.

Diff limité à cette annexe. Guide audité, README D1, tous exécutables/tests,
dépendances/workflows/gates/permissions, runtime/protocole/TLS, manifest/version
byte-identiques à la base. Pas de CHANGELOG : vérification interne sans impact
HACS/API/comportement. Tests réels Hoben/HA **NOT RUN** ; aucun dispatch/rerun,
commande/écriture Modbus, secret/GUID/RX/donnée privée, main/release/tag/version
ou fusion DEV. Revue MANAGER puis arrêt ; aucune autre tâche auto-attribuée.

## Annexe D3 — champs des diagnostics HA et collecte de support

Tâche `HOBEN-189-D3-HA-DIAGNOSTICS-DOC-CONSISTENCY-017`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Base `experimental` : `1a8af5cebd5caa241b7a709b928af1328be9f928`.
Guide unique audité : [home-assistant-integrator.md](home-assistant-integrator.md).
**Conserver le guide à l'octet : aucune divergence factuelle démontrée dans
les champs expurgés et la collecte de support ciblés.**

| Affirmation du guide | Source actuelle en lecture seule / conclusion |
| --- | --- |
| Téléchargement existant en mémoire, sans sonde, refresh ni mutation HA | [diagnostics.py](../custom_components/hoben/diagnostics.py) projette uniquement des métadonnées ; sans runtime typé, seuls domain, entry et runtime_available sont retournés. |
| Champs publiables explicitement limités, erreurs typées et sans chaîne d'exception | diagnostics.py et [safe_reports.py](../custom_components/hoben/safe_reports.py) valident les types, catégories et bornes. La liste du prompt est un sous-ensemble volontairement restrictif : les champs supplémentaires du JSON actuel n'autorisent pas leur collecte/publication automatique. |
| Snapshot conservé ou client ready insuffisants pour prouver une connexion actuelle ; version installée à relever séparément | snapshot_available vérifie la présence en mémoire d'un RawStoveSnapshot ; client.state provient du safe_report. Ces champs ne prouvent ni connexion active, ni ref HACS installée. Le guide distingue explicitement cette ref de sa gouvernance main. |
| Journaux structurés WARNING/ERROR, fallback brut borné, rapport exclusivement catégoriel | Le guide n'autorise pas la collecte DEBUG. [shadow_data_updated.py](../custom_components/hoben/shadow_data_updated.py), observe_applied_data_updated, exige DEBUG explicite sur son logger pour les valeurs locales privées ; ce flux reste distinct de la projection support sans valeurs du foyer. Aucun logger activé pendant l'audit. |

L'absence de session, snapshot_held, horodatage/âge et de certains champs
d'erreur dans la liste publiable du prompt n'est pas une déclaration d'absence
dans le JSON : le guide impose d'omettre les extensions inconnues et de vérifier
clés **et valeurs** avant publication. Ne pas élargir cette autorisation pour
aligner artificiellement le prompt sur tous les champs runtime, ni recopier
les DEBUG privés dans un rapport de support. README D1 et guide DataUpdated D2
restent hors modification ; aucun fait protocolaire nouveau.

Validation : tests existants de schéma privé en mémoire, téléchargement via
l'endpoint HA simulé, absence de runtime et opt-in DEBUG dédié ; références,
diff-check/lint et quatre CI au HEAD exact consignés dans la PR/#189. Ces tests
utilisent uniquement des données synthétiques et ne prouvent pas l'état d'une
installation réelle. Diff limité à cette annexe ; aucun exécutable/test,
workflow/gate, runtime, manifest/version ou CHANGELOG modifié : audit interne
sans impact HACS/API/comportement. Tests réels Hoben/HA **NOT RUN** ; aucune
fusion DEV. Revue MANAGER puis arrêt, sans autre tâche auto-attribuée.

## Synthèse E1 — bilan consolidé, décision de pré-release encore distincte

Tâche `HOBEN-189-E1-PRE-RELEASE-AUDIT-CONSOLIDATION-018`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
État vérifié le 21/11/2026 sur `experimental`
`c2e63b52f995dff18c08c530b4f6b0db86cbeaec`.
**Bilan documentaire des lots fusionnés, pas une validation de pré-release.**
L'inventaire A1 et chaque annexe gardent leur base historique ; cette synthèse
résume leurs décisions sans réécrire les preuves ni réauditer tout le plugin.

### Lots livrés et preuves CI

Les 17 PR ci-dessous sont fusionnées, base exactement experimental ; leurs
commits intégrés sont ancêtres de la base E1. Les liens HEAD abrégés désignent
les SHA complets des candidats ; les runs Validate liés, pull_request/tentative 1,
portent chacun **tests, ha-tests, hacs et hassfest SUCCESS sur ce HEAD exact**.
Ils ne constituent ni une CI au SHA de squash, ni une validation réelle.

| Lot | PR / HEAD source | Validate 4/4 SUCCESS | Résultat intégré |
| --- | --- | --- | --- |
| A1 | [#190](https://github.com/Guillaume0385/ha-hoben-community/pull/190) · [dc80b23f62fa](https://github.com/Guillaume0385/ha-hoben-community/commit/dc80b23f62fad0b9673a56da2127424ae15ce645) | [42118746911](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/42118746911) | Inventaire initial et limites ; aucun retrait. |
| D1 manuel · 002 | [#230](https://github.com/Guillaume0385/ha-hoben-community/pull/230) · [16e215bc680b](https://github.com/Guillaume0385/ha-hoben-community/commit/16e215bc680ba41de54f96cbf6cacc6dddcd2c07) | [44804775363](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/44804775363) | Deux voies modernes clarifiées ; voie historique conservée. |
| B1 | [#231](https://github.com/Guillaume0385/ha-hoben-community/pull/231) · [da5651bcddcb](https://github.com/Guillaume0385/ha-hoben-community/commit/da5651bcddcbbab0194a0301271b7c34790e2815) | [44814136597](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/44814136597) | Couple HA-parity retiré ; fixtures et gardes maintenus. |
| B2 | [#232](https://github.com/Guillaume0385/ha-hoben-community/pull/232) · [0e639621f1d9](https://github.com/Guillaume0385/ha-hoben-community/commit/0e639621f1d9a8d43c60a74d5f7e6278c0eca757) | [44819621348](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/44819621348) | Moteur session-300 et lanceur conservés à cette étape. |
| B3 | [#233](https://github.com/Guillaume0385/ha-hoben-community/pull/233) · [c76a2d6eb177](https://github.com/Guillaume0385/ha-hoben-community/commit/c76a2d6eb177da4e5ba159a28b9e88da38ac427d) | [44824399721](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/44824399721) | Seul lanceur session-300 retiré ; moteur partagé conservé. |
| B4 | [#234](https://github.com/Guillaume0385/ha-hoben-community/pull/234) · [3a3a94951803](https://github.com/Guillaume0385/ha-hoben-community/commit/3a3a949518030000b76451e69c76b4e06e8b31a4) | [44829182492](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/44829182492) | Lanceur experimental-boundary conservé : dépendances établies. |
| B5 | [#235](https://github.com/Guillaume0385/ha-hoben-community/pull/235) · [6e31a9c3e337](https://github.com/Guillaume0385/ha-hoben-community/commit/6e31a9c3e337d291939079a127f9d5ffefe65299) | [44834329329](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/44834329329) | Fondation natural-900 et test dédié retirés ; exclusions maintenues. |
| B6 | [#236](https://github.com/Guillaume0385/ha-hoben-community/pull/236) · [9f2e2ce1cf16](https://github.com/Guillaume0385/ha-hoben-community/commit/9f2e2ce1cf1667edb0314e97e4f017e6e17020f6) | [44840475548](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/44840475548) | Lecteur Actions registry retiré ; 30 cas du transport conservés. |
| B7 | [#237](https://github.com/Guillaume0385/ha-hoben-community/pull/237) · [7cb73d1369b3](https://github.com/Guillaume0385/ha-hoben-community/commit/7cb73d1369b31ceed94d0d1080b9316ed529503e) | [44850677310](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/44850677310) | Lecteur Git Blob retiré ; 25 cas transport/arbre conservés. |
| C1 | [#238](https://github.com/Guillaume0385/ha-hoben-community/pull/238) · [d1536e63a15d](https://github.com/Guillaume0385/ha-hoben-community/commit/d1536e63a15db80caf3bae7c84ffe525a1d4fa2b) | [44854425100](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/44854425100) | 55 cas du contrat HA offline conservés. |
| C2 | [#239](https://github.com/Guillaume0385/ha-hoben-community/pull/239) · [4cfd3cb9de69](https://github.com/Guillaume0385/ha-hoben-community/commit/4cfd3cb9de6907b11fc5869c618a57e08a0901fc) | [44858023072](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/44858023072) | 54 cas du validateur de preuve HA conservés. |
| C3 | [#240](https://github.com/Guillaume0385/ha-hoben-community/pull/240) · [9c0309464089](https://github.com/Guillaume0385/ha-hoben-community/commit/9c03094640890a2191adb5401ee131775920e7f2) | [44860403780](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/44860403780) | Réexamen de C1, pas une autre famille : 55 cas conservés. |
| C4 | [#241](https://github.com/Guillaume0385/ha-hoben-community/pull/241) · [3a86973ac419](https://github.com/Guillaume0385/ha-hoben-community/commit/3a86973ac4193e1128d49e32dea04b3628010fa3) | [44864460143](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/44864460143) | 12 cas du vrai chemin HA synthétique conservés. |
| C5 | [#242](https://github.com/Guillaume0385/ha-hoben-community/pull/242) · [4bb82c6ee18e](https://github.com/Guillaume0385/ha-hoben-community/commit/4bb82c6ee18ecbdefb3457ad8cc3781fa01ff8ae) | [44867116406](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/44867116406) | Coûts observés documentés ; quatre jobs et caches inchangés. |
| D1 HACS · 015 | [#243](https://github.com/Guillaume0385/ha-hoben-community/pull/243) · [e9c568c613f6](https://github.com/Guillaume0385/ha-hoben-community/commit/e9c568c613f6f4af951677e44e04ddcf600ae229) | [44870822905](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/44870822905) | Installation HACS/ref et diagnostics README clarifiés. |
| D2 | [#244](https://github.com/Guillaume0385/ha-hoben-community/pull/244) · [83651f4ac10d](https://github.com/Guillaume0385/ha-hoben-community/commit/83651f4ac10d608be8b884330c7728f562466fc9) | [44872577063](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/44872577063) | Guide DataUpdated conservé ; preuves ajoutées à l'audit. |
| D3 | [#245](https://github.com/Guillaume0385/ha-hoben-community/pull/245) · [769521f2055b](https://github.com/Guillaume0385/ha-hoben-community/commit/769521f2055bc698e246edfc31507fcfec68b80b) | [44880754594](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/44880754594) | Guide diagnostics conservé ; séparation support/DEBUG confirmée. |

Les deux D1 correspondent aux tâches distinctes 002 (campagnes manuelles) et
015 (installation HACS). Les C1–C5 effectivement livrés auditent les tests/coûts ;
ils n'exécutent pas la proposition A1 de retrait du workflow historique.

### Suppressions bornées et conservations

Six scripts retirés seulement : `launch_live_ha_parity.py`,
`run_live_ha_parity.py`, `launch_session_300.py`, `session_natural_900.py`,
`github_campaign_actions_registry.py` et `github_campaign_workflow_blob.py`
(sous scripts/). Les annexes B1/B3/B5/B6/B7 portent les graphes statiques et
dynamiques, consommateurs, limites externes et équivalences des garanties.
Les tests strictement attachés ont été retirés/adaptés ; le seul fichier de
tests supprimé est test_session_natural_900.py. Les 30 cas transport B6 et
25 cas transport/arbre B7 restent testés directement, sans API retirée.

run_session_300.py, launch_experimental_boundary.py, moteurs/validateurs
partagés, fixtures historiques et contrats indépendants Python/Node sont
conservés. C1–C4 n'ont supprimé aucun test ; C3 réexamine C1. C5 n'a modifié
ni workflow/cache/dépendance ni revendiqué un gain causal. Les diffs propres
aux 17 lots ne modifient aucun fichier du plugin distribué ni YAML ; cela ne
prétend pas que le runtime soit resté identique entre A1 et E1, d'autres issues
ayant évolué séparément. Aucune économie globale de CI n'est démontrée ici.

### Risques ouverts et suite à décider

- Retrait du workflow hoben-manual.yml et de ses dépendances non autorisé par
  ces lots ; différences d'admission et consommateurs à préserver. Autres
  candidats A1 non traités conservés, pas implicitement déclarés morts.
- Audit A1 limité aux workflows/scripts et supports listés : pas d'exhaustivité
  de chaque fonction/runtime, ni preuve d'absence d'usages privés externes.
  Politiques natives, approbations effectives, reproductibilité des actions
  flottantes et éventuelles optimisations de cache restent à vérifier séparément.
- [#186](https://github.com/Guillaume0385/ha-hoben-community/issues/186),
  [#219](https://github.com/Guillaume0385/ha-hoben-community/issues/219) et
  [#220](https://github.com/Guillaume0385/ha-hoben-community/issues/220)
  restent ouvertes, state:waiting au contrôle E1 ; leur suite relève de MANAGER,
  sans réactivation ici. Les anciens corps/commentaires ne remplacent pas les
  décisions plus récentes ; #163/#192/#212 sont closes, pas des tâches à reprendre.
- Le FAIL HA historique cité en A1 reste un constat à son SHA, pas le verdict
  du runtime actuel. Les CI synthétiques et fusions documentaires ne soldent
  aucune validation réelle : propriétaire/MANAGER doivent rapprocher observations,
  version réellement chargée et SHA avant toute décision de pré-release.
- Export de support expurgé distinct du DEBUG privé local ; aucune valeur
  domestique, secret, GUID ou RX brut dans ce bilan. V4 lecture seule et TLS
  certificat/hostname vérifiés myhoben.fr:465 inchangés.

Vérifications E1 : références PR/commits/runs/jobs, ascendance des fusions,
fichiers réellement retirés/conservés, liens et diff documentaire contrôlés ;
Ruff/diff-check et quatre CI du nouveau HEAD E1 consignés dans la PR/#189.
Pas de nouveau test miroir ni de suite complète locale pour cette synthèse ;
les suites existantes sont exécutées par la CI. Diff limité à cette synthèse,
pas de CHANGELOG : audit interne sans changement de livrable/API/comportement.
Tests réels **NOT RUN** ; aucun dispatch/rerun live, commande ou écriture Modbus.
**Aucune promotion main, version, tag, release ou déclaration « prête » autorisée
par E1.** Revue MANAGER, state:review puis arrêt DEV, sans fusion ni autre tâche.

## Complément E2 — lacunes restantes et décisions réservées

Tâche `HOBEN-189-E2-REMAINING-AUDIT-GAPS-INVENTORY-019`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Base `experimental` vérifiée le 21/11/2026 :
`95ea584858a856b9c290fc8e68c6536c0241ec46`, après [E1/#246](https://github.com/Guillaume0385/ha-hoben-community/pull/246).
Ce tableau précise seulement les quatre lacunes d'E1 ; les lots clos et leurs
décisions ne sont pas réaudités. Aucun candidat supplémentaire à suppression.

| Lacune / preuve publique vérifiée | Limite de preuve | Risque restant | Prochaine décision réservée au propriétaire / MANAGER |
| --- | --- | --- | --- |
| Usages externes : la méthode A1 et les annexes B examinent les arbres, imports/appels, CLI, copies et documents du dépôt aux SHA indiqués. | Ce périmètre n'observe ni scripts privés, ni tâches locales, ni consommateurs tiers ; aucune absence d'usage externe n'est prouvée. | Un futur retrait pourrait casser un usage hors dépôt ; ce risque n'est pas un consommateur avéré ni un motif pour rouvrir les retraits déjà revus. | Avant tout autre retrait, qualifier les dépendances externes connues avec le propriétaire, par catégories expurgées, et définir les preuves/compatibilités nécessaires. Aucun inventaire privé collecté par E2. |
| Approbations natives : [campagne HA](../.github/workflows/hoben-ha-manual.yml#L90) déclare hoben-live ; [campagne protocole](../.github/workflows/hoben-protocol-manual.yml#L88) déclare hoben-experimental. | Une déclaration environment ne prouve ni reviewers effectifs, ni interdiction d'auto-approbation, ni politique appliquée à un run/ref donné. Aucun réglage ou environnement lu dans E2. | Une protection inconnue ne peut être présumée présente **ou absente** ; YAML et CI seuls ne suffisent pas à déclarer une campagne approuvée. | Vérifier ultérieurement les protections effectives par un accès légitime et une preuve authentifiée, sous décision distincte ; aucun assouplissement, dispatch ou autorisation de live ici. |
| Actions flottantes : [Validate](../.github/workflows/validate.yml) utilise actions/checkout@v7, actions/setup-python@v7, hacs/action@main et home-assistant/actions/hassfest@master. | Ces tags/branches ne sont pas des SHA immuables. E2 ne résout ni ne choisit leurs révisions ; un succès historique ne fixe pas le contenu d'une prochaine exécution. Les références SHA des campagnes manuelles ne rendent pas tout le dépôt reproductible. | Variation possible du contenu exécuté à ref du dépôt constante ; aucun incident ou compromis n'est démontré par ce constat. | Arbitrer séparément une politique de reproductibilité et de maintenance des actions, avec compatibilité et quatre checks préservés ; aucun pin, workflow ou dépendance modifié en E2. |
| Portée : A1 inventorie cinq workflows et 88 fichiers d'outillage à sa base c81b79643485e8b148695c6e4fc0e2a9a50f2a87 ; E1 consolide les lots effectivement livrés. | Ces nombres sont historiques, pas un inventaire courant de chaque fonction du plugin ni une couverture exhaustive des comportements. Les changements d'autres issues ne sont pas réaudités ici. | Présenter le bilan comme exhaustif masquerait des zones non examinées ; aucune nouvelle anomalie runtime n'est établie. | Définir, si nécessaire, un prochain petit périmètre et ses critères de preuve avant de l'attribuer ; conserver les éléments dont l'inutilité n'est pas établie. Aucune tâche suivante créée par DEV. |

Les preuves historiques restent bornées à leurs SHA. Le vert des quatre CI
d'E1 et celui requis pour E2 portent sur leurs HEAD sources respectifs, pas sur
les politiques natives, les usages externes ou une validation HA installée.
Les observations propriétaires, suivis fonctionnels et décision de pré-release
restent distincts, selon E1 ; aucune lacune ci-dessus n'est déclarée résolue
par cette seule documentation.

Validation E2 : liens/références, conformité du tableau aux déclarations
publiques, confidentialité, ajout documentaire seul, Ruff/diff-check et quatre
CI sur le HEAD exact consignés dans la PR/#189. Pas de nouveau test ni suite
complète locale pour ce tableau ; les suites existantes restent exécutées en CI.
Diff limité à ce complément ; pas de CHANGELOG, sans impact HACS/API/runtime.
Tests réels **NOT RUN** ; aucun accès aux secrets/environnements, dispatch/rerun
live, commande/écriture Modbus, main/release/tag/version ou fusion DEV.
V4 lecture seule, TLS certificat/hostname vérifiés myhoben.fr:465 inchangés.
Revue MANAGER puis arrêt en state:review ; aucune déclaration de version prête.

## Annexe E3 — faisabilité d'un pinning des actions de Validate

Tâche `HOBEN-189-E3-VALIDATE-ACTIONS-PINNING-FEASIBILITY-AUDIT-020`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Base `experimental` : `3310df6b89aaafda8e5831b32b494d1c21ccdd81`.
**Conclusion : syntaxe de pinning disponible, adoption non décidée et
compatibilité d'une révision future non démontrée. Aucun SHA candidat résolu,
sélectionné ou appliqué.**

[Validate](../.github/workflows/validate.yml) contient quatre références
distinctes dans sept étapes uses ; les quatre jobs doivent rester présents.

| Référence actuelle | Jobs / occurrences | Contrat à préserver dans une éventuelle tâche autorisée |
| --- | --- | --- |
| actions/checkout@v7 | tests, ha-tests, hassfest / 3 | Checkout du candidat et persist-credentials:false ; vérifier les exigences du runner de la révision retenue, sans changer de génération d'action implicitement. |
| actions/setup-python@v7 | tests, ha-tests / 2 | Séparation Python 3.12/dev et 3.14/ha-test, installations et commandes existantes ; disponibilité des interpréteurs et compatibilité action/runner à vérifier. |
| hacs/action@main | hacs / 1 | category:integration, comment:false et verdict HACS ; figer le code de l'action ne garantit pas de figer ses images/dépendances. |
| home-assistant/actions/hassfest@master | hassfest / 1 | Sous-chemin hassfest et verdict HA conservés ; vérifier code composite, images et dépendances de la révision future. |

La [syntaxe officielle GitHub](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/find-and-customize-actions#using-shas)
permet un SHA complet et précise que les mises à jour ne sont alors plus reçues
automatiquement. C5 décrit des images HACS/Hassfest mobiles à ses SHA historiques,
sans nouvelle résolution ici. ubuntu-latest, Python, pip et les dépendances de
[pyproject.toml](../pyproject.toml) ne seraient pas figés par ce seul pin.
La [référence de sécurité GitHub](https://docs.github.com/en/actions/reference/security/secure-use#using-third-party-actions)
demande origine dans le dépôt de l'action, pas un fork, et revue du code :
immuabilité ne signifie pas innocuité. Ses lockfiles ne sont pas évalués en E3.

Avant une éventuelle mise en œuvre, propriétaire/MANAGER doivent arbitrer :

- **Provenance** : autorisation distincte pour les sept occurrences, origine,
  version intentionnelle et revue ; les anciens SHA C5 ne sont pas des candidats
  approuvés ni une preuve de compatibilité actuelle.
- **Entretien** : responsable et cadence de revue des correctifs/avis. Aucun
  dependabot.yml/.yaml suivi dans .github à cette base, sans preuve sur le suivi
  externe. Le mécanisme
  [Dependabot pour les actions](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/auto-update-actions)
  est documenté, pas activé ou autorisé par E3.
- **Compatibilité** : exigences runner/action, entrées, images et dépendances ;
  PR distincte revue avec quatre CI SUCCESS au HEAD exact, correction même PR
  si échec, sans supprimer un job ni élargir permissions/runtime/cache.

**Décision E3 : conserver le YAML actuel pendant cet audit ; aucun pin proposé
comme prêt à appliquer.** Bénéfice possible : référence directe stable ; risques :
correctifs non intégrés sans maintenance et reproductibilité transitive
surestimée. Aucune vulnérabilité ou économie CI établie ; politique finale
réservée au propriétaire, aucun réglage natif présumé disponible.

Sources publiques consultées le 21/11/2026 ; liens, occurrences, limites,
confidentialité, Ruff/diff-check et quatre CI au HEAD E3 consignés dans PR/#189.
Diff limité à l'annexe, sans CHANGELOG (audit interne, aucun impact HACS/API).
Pas de nouveau test ni suite complète locale ; suites existantes en CI.
Workflow/code/tests/dépendances/permissions/environnements/version inchangés.
Tests réels **NOT RUN**, V4 lecture seule et TLS vérifié myhoben.fr:465 préservés.
Revue MANAGER puis arrêt state:review, sans fusion/main/release/tag ni version
déclarée prête ; aucune action live, commande/écriture Modbus ou donnée privée.

## Annexe E4 — déclencheurs CI et frontière avec les campagnes manuelles

Tâche `HOBEN-189-E4-VALIDATE-TRIGGERS-LIVE-BOUNDARY-DOC-AUDIT-021`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Base `experimental` : `b6bb03700f79553c7a0e7c51069fed801b5ef39b`.
**Cohérence constatée sur le périmètre ciblé ; aucun texte existant ou YAML
à corriger.** Cette preuve complète les décisions A1 sans changer de déclencheur.

| Fait dans les YAML publics | Portée / séparation vérifiée |
| --- | --- |
| [Validate](../.github/workflows/validate.yml) : push, branches main et chore/** | Pas de déclenchement push direct déclaré pour experimental ; une fusion sur experimental n'est pas en elle-même une campagne réelle. |
| Validate : pull_request, sans filtre branches/paths explicite | CI des PR, distincte du filtre push ; quatre checks à constater au HEAD exact, pas à déduire de l'existence du YAML. |
| Validate : workflow_dispatch | Dispatch de la CI ordinaire ; ce nom d'événement ne signifie pas à lui seul accès Hoben réel. Aucun lancement effectué dans E4. |
| Validate : schedule, cron 0 0 * * 1 | Planification hebdomadaire déclarée de CI, pas une campagne live ni une preuve d'exécution effective ou d'heure observée. |
| Validate : permissions globales vides, contents:read dans chacun des quatre jobs | tests = pytest/Ruff ; ha-tests = pytest HA synthétique ; hacs et hassfest = validations dédiées. Aucun environment ou secret Hoben référencé, ni étape de dispatch/collecteur réel déclarée dans ce YAML. |
| [HA](../.github/workflows/hoben-ha-manual.yml) et [protocole](../.github/workflows/hoben-protocol-manual.yml) : seul événement workflow_dispatch | Admission sur dépôt, acteur ET triggering_actor propriétaires, ref autorisée et catalogue fermé ; collect dépend de l'admission réussie. Environnements déclarés hoben-live / hoben-experimental, mutex commun hoben-read-only-observation sans annulation du run actif. Aucun push/PR/schedule/workflow_run déclaré pour ces campagnes. |

Le [workflow expérimental](experimental-protocol-workflow.md) annonce les deux
campagnes actuelles et réserve les exigences historiques PR/CI/claim/recheck
à la voie #119. Ses anciennes descriptions d'un lancement sur push restent
historiques : elles ne déclenchent pas les YAML actuels. Ne pas les transférer
dans Validate ni réintroduire leurs gates dans les deux campagnes modernes.
Leur admission autorise des refs nommées ; elle ne prouve ni installation sur
chaque branche ni approbations natives effectives, qui restent hors preuve E4.

Lecture YAML complète et comparaison documentaire seulement : aucun dispatch,
rerun, accès privé ou contrôle de Settings. CI « offline » signifie sans Hoben/HA
domestique, pas sans Internet pour outils/dépendances. Un vert de CI ne valide
pas le poêle, une campagne réelle ou une pré-release ; une déclaration de gate
ne prouve pas sa politique native. Liens, événements/droits, confidentialité,
identité des trois YAML, Ruff/diff-check et quatre CI au HEAD E4 consignés dans
PR/#189. Diff limité à l'annexe, sans CHANGELOG (audit interne sans impact API).
Pas de nouveau test ni suite complète locale ; suites existantes en CI.
Tests réels **NOT RUN**, V4 lecture seule et TLS vérifié myhoben.fr:465 préservés.
Revue MANAGER puis arrêt state:review, sans fusion, main/release/tag/version,
commande/écriture Modbus, donnée privée ou autre tâche auto-attribuée.

## Annexe E5 — matrice des points ouverts avant décision de pré-release

Tâche `HOBEN-189-E5-PRE-RELEASE-OPEN-BLOCKERS-EVIDENCE-MATRIX-022`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Base `experimental` : `f2d7f3b90703c927ad1859bfa6eb9e1e0e5a3416`.
Synthèse des preuves E1–E4, sans nouvelle validation : le propriétaire doit
encore qualifier chaque point comme bloquant, accepté ou reporté, avec son
motif et sa preuve, sans déroger aux gates et validations obligatoires.
Ces lacunes ne sont pas cinq défauts runtime démontrés.

| Point / état établi et source publique | Preuve manquante / risque | Décision réservée au propriétaire, avec revue MANAGER |
| --- | --- | --- |
| Réel : NOT RUN consigné dans les lots [E1/#246](https://github.com/Guillaume0385/ha-hoben-community/pull/246) à [E4/#249](https://github.com/Guillaume0385/ha-hoben-community/pull/249) ; leurs CI valident leurs HEAD sources hors ligne. | Validation réelle de la version effectivement installée non établie par ces lots ; risque de confondre tests synthétiques et stabilité domestique. | Examiner les observations existantes, expurgées et corrélées au SHA chargé, puis décider des preuves encore nécessaires et d'une éventuelle validation séparément autorisée. Aucun lancement accordé par E5. |
| Politiques natives : environnements/admission déclarés, effectivité non prouvée ([E2/#247](https://github.com/Guillaume0385/ha-hoben-community/pull/247), E4). | Politique et approbation applicables au contexte réel non attestées ; risque d'inférer une autorisation depuis le YAML ou une CI verte. | Exiger la preuve authentifiée pertinente avant une éventuelle campagne autorisée ; aucune protection présumée absente, aucun changement ou contournement ici. |
| Usages externes : limites du graphe du dépôt établies en E1/E2 ; aucun consommateur externe avéré par cet audit. | Absence d'usage hors dépôt non prouvée ; risque pour un futur retrait, sans remise en cause automatique des lots clos. | Qualifier les usages connus par catégories expurgées et les besoins de compatibilité avant tout autre retrait ; conserver les candidats dont l'inutilité n'est pas établie. |
| Actions : quatre références flottantes/sept occurrences constatées ; faisabilité syntaxique seule, aucun pin choisi ([E3/#248](https://github.com/Guillaume0385/ha-hoben-community/pull/248)). | Politique de provenance, entretien et compatibilité d'une révision future non décidés ; contenu direct/transitif susceptible d'évoluer. Aucun compromis démontré. | Arbitrer la politique et son entretien ; toute mise en œuvre reste une tâche distincte avec revue et quatre CI. Le pinning n'est pas imposé comme critère de release par E5. |
| Inventaire : périmètre historique A1 et lots livrés établis en E1/E2. | Exhaustivité de chaque fonction/runtime non démontrée ; risque de présenter un inventaire partiel comme certification globale. | Délimiter les zones à examiner ou à reporter et justifier leur acceptation ; aucune tâche supplémentaire ni suppression attribuée par DEV. |

Les runs propriétaires historiques restent bornés à leurs SHA ; NOT RUN ici
ne signifie pas qu'aucun test propriétaire n'a jamais eu lieu. Les quatre CI
E5 n'apportent aucune des preuves externes ci-dessus. Aucune ligne n'est soldée
par cette matrice ; aucune version prête, promotion, release ou autorisation
live ne se déduit de la fusion des audits. Décisions et validations restent
distinctes, avec preuve au SHA concerné.

Contrôles E5 : sources E1–E4, cohérence, liens, confidentialité, ajout seul,
Ruff/diff-check et quatre CI au HEAD exact consignés dans PR/#189. Aucun nouveau
test ni suite complète locale ; suites existantes en CI. Diff limité à cette
annexe, sans CHANGELOG (audit interne, aucun impact HACS/API/comportement).
Code/tests/workflows/droits/gates/dépendances/environnements/runtime/version
inchangés. Tests réels **NOT RUN** ; aucun accès privé, dispatch/rerun live,
commande/écriture Modbus, donnée privée, main/release/tag ou fusion DEV.
V4 lecture seule et TLS vérifié myhoben.fr:465 préservés ; state:review puis arrêt.

## Annexe E6 — registre des arbitrages restant au propriétaire

Tâche `HOBEN-189-E6-PRE-RELEASE-AUDIT-CLOSURE-DECISION-REGISTER-023`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Base `experimental` : `224f90d698d91a83864249d62a3bc86ec58f31cb`.
Source unique de cette synthèse : matrice [E5/#250](https://github.com/Guillaume0385/ha-hoben-community/pull/250).
**Cinq arbitrages en attente ; aucune décision propriétaire présumée.** Les
conditions ci-dessous concernent chaque point, pas la clôture de #189 ni une
promotion. Un report ne satisfait aucune obligation de sécurité ou validation.

| Point E5 / décision encore requise | Preuve attendue | Responsable de l'arbitrage | Condition de clôture du point ou de report |
| --- | --- | --- | --- |
| Réel : déterminer les observations/validations encore nécessaires pour le SHA effectivement chargé. | Bilan expurgé corrélant SHA installé, contexte, résultats et limites ; autorisation distincte avant tout éventuel nouvel essai. | Propriétaire ; MANAGER examine la preuve. | Clôture seulement sur décision explicite citant les preuves recevables ; à défaut, report motivé et validation réelle non acquise. Ni fusion d'audit ni CI ne la remplace. |
| Politiques natives : établir l'admissibilité d'une éventuelle campagne autorisée. | Preuve authentifiée des protections et approbations applicables au contexte/ref/run, pas leur seule déclaration YAML. | Propriétaire pour les autorisations ; MANAGER vérifie la conformité. | Clôture sur conformité attestée ; sinon campagne non admise. Reporter son examen n'autorise ni lancement, ni assouplissement ou contournement des gates. |
| Usages externes : décider des contraintes de compatibilité avant tout autre retrait. | Dépendances connues par catégories expurgées, périmètre et incertitudes explicités ; aucune collecte de scripts privés exigée ici. | Propriétaire ; MANAGER borne l'analyse. | Décision documentée sur ce périmètre, sans prétendre prouver l'absence universelle d'usages ; sinon conserver les candidats et reporter tout retrait non démontré. |
| Actions : choisir la politique de références et son entretien, sans pin imposé par l'audit. | Décision sur portée, responsable/cadence et critères de provenance/compatibilité ; preuves de révision seulement dans une future tâche autorisée. | Propriétaire ; MANAGER organise revue et contrôles. | Clôture de l'arbitrage sur politique et limites explicites ; mise en œuvre séparée si autorisée. Sans décision, report enregistré, YAML inchangé et risque E5 conservé. |
| Inventaire : décider des zones à examiner, accepter de manière bornée ou reporter. | Périmètre retenu, exclusions, justification et critères de preuve ; pas une certification globale déduite des lots A1–E5. | Propriétaire ; MANAGER vérifie la traçabilité. | Clôture de cet arbitrage avec couverture/limites approuvées ; sinon zones non auditées maintenues comme telles. Toute suite exige attribution distincte. |

Pour enregistrer ultérieurement un arbitrage : décision propriétaire datée et
liée, SHA/périmètre concernés, lien de preuve, conclusion MANAGER et motif de
clôture/report. Sans ces éléments, garder « en attente » ; ne pas remplir les
cases à partir d'une ancienne CI ou d'une absence de réponse. Aucun choix,
délai, essai ou travail suivant n'est attribué par E6. La décision de pré-release
reste distincte et aucune version n'est déclarée prête.

Contrôles E6 : correspondance des cinq lignes E5, liens, cohérence des rôles et
limites, confidentialité, ajout seul, Ruff/diff-check et quatre CI au HEAD exact
consignés dans PR/#189. Pas de nouveau test ni suite complète locale ; suites
existantes conservées en CI. Diff limité au registre, sans CHANGELOG (audit
interne sans impact HACS/API). Aucun code/test/workflow/droit/gate/environnement/
dépendance/protocole/manifest/version modifié. Tests réels **NOT RUN** ; aucune
action live, commande/écriture Modbus, donnée privée, main/release/tag ou fusion
DEV. V4 lecture seule et TLS vérifié myhoben.fr:465 préservés ; revue puis arrêt.

## Annexe B8 — chemins DataUpdated actuels, compatibilité shadow et tests Python

Tâche `HOBEN-189-B8-SHADOW-LEGACY-PYTHON-TEST-AUDIT-024`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Base `experimental` : `3a2d0e751311f7278588b7a017036167ac10af79` (25/11/2026).
**Audit seul : aucun chemin ni test prouvé supprimable. Conserver le module
et les quatre familles ; aucun B9 de suppression proposé sur cette preuve.**
« Legacy » décrit une API de compatibilité, pas une absence de consommateur.

| Fonction/branche et consommateur établi à cette base | Tests / invariant distinct | Décision et risque de retrait |
| --- | --- | --- |
| [_candidate_words / preview_data_updated / ShadowPreview](../custom_components/hoben/shadow_data_updated.py#L49) : admission utilisée par le push dans [V4Session](../custom_components/hoben/v4_session.py#L754), le FIFO et le logger candidat. | [Python shadow](../tests/test_shadow_data_updated_219s.py#L36) : structure sans proposition, immutabilité, faux mapping par égalité ; [Python privé](../tests/test_private_data_updated_219.py#L157) et [push](../tests/test_data_updated_push_219.py#L67) : faux TID/unité/fonction/taille, mots forgés dont bool refusés. | **Conserver** : retirer le « preview » affecterait aussi le filtre push. parsed/ok seul n'admet pas la forme FFFF/unité 1/04/20 UInt16 ; les métadonnées ne prouvent ni adresse ni frontière TLS. |
| [_private_register_journal](../custom_components/hoben/shadow_data_updated.py#L72) : appelé par observe_data_updated **et directement par le push** (session lignes 788–792), avant décodage/callback. | [Python privé](../tests/test_private_data_updated_219.py#L95) : opt-in indépendant, refus CI, FIFO 0600/UID/lien unique, O_PATH/inode revérifié, substitution de chemin, pression/sans lecteur, PIPE_BUF, fermeture des descripteurs, erreur sans fuite et générations. [HA privé](../ha_tests/test_private_data_updated_219.py#L22) : état/fraîcheur/listeners/TX/exports inchangés en compatibilité. | **Conserver** : le FIFO n'est pas orphelin du mode installé. Aucune création de fichier, fallback public, rétention/replay ni attente du lecteur ; ne pas remplacer ces négatifs par un seul test de logger. |
| [observe_data_updated / _public_index](../custom_components/hoben/shadow_data_updated.py#L169) : branche sans callback ; HobenClient garde push_updates=False par défaut, et le client dual de [ha_session_live_worker](../scripts/ha_session_live_worker.py#L60) demande ha_reconnect sans push. | [Python shadow](../tests/test_shadow_data_updated_219s.py#L74) : DEBUG parent insuffisant, arrêt/reload/disabled, contexte opaque et handler en échec, EOF/nouvelle génération sans RX/TX ajouté. Python privé ajoute nombres candidats bornés, opt-in HA sans FIFO et absence de backlog. | **Conserver** : appel opérationnel possible, pas seulement une fixture. Le scénario dual est cité comme consommateur, sans réactivation ni critère de release. Valeurs locales autorisées seulement en DEBUG explicite ; jamais export de support. |
| [observe_applied_data_updated](../custom_components/hoben/shadow_data_updated.py#L238) : callback push de l'entrée [__init__.py](../custom_components/hoben/__init__.py#L68), snapshot existant/décodeur V4 puis [client](../custom_components/hoben/client.py#L250) → [coordinator](../custom_components/hoben/coordinator.py#L154). | [HA push](../ha_tests/test_data_updated_push_219.py#L33) : vingt publications atomiques, initiale unique/ordre, ancien callback révoqué, root DEBUG inopérant, opt-in/off, JSON local et panne decode/callback sans état partiel ni exception privée. | **Conserver** : chemin courant distinct du candidat. mapping owner_validated relève de la décision empirique propriétaire, pas d'une adresse transmise ; borne JSON 8192 et garde DEBUG dédiées, pas de nouvelle lecture réseau. |
| Fixtures : [legacy_polling_client](../ha_tests/conftest.py#L128) impose push_updates=False via peers ; [push_peers](../ha_tests/test_data_updated_push_219.py#L20) rétablit le constructeur de production. HA privé importe FLAG/fields/notification/private_fifo du fichier Python privé. | [HA shadow](../ha_tests/test_shadow_data_updated_219s.py#L16) : aucune publication/listener/fraîcheur/TX sur vingt livraisons ; HA privé : quatre combinaisons FIFO/DEBUG plus vrai service logger HA simulé. Les tests push exigent au contraire des publications. | **Conserver** : ces attentes opposées concernent des modes explicites, pas un test obsolète interdisant le push. Ne pas supprimer un fichier porteur de fixtures partagées. Les vingt paramètres du preview restent **à vérifier** pour équivalence. L'écriture FIFO en entrée push reste aussi à vérifier : les tests privés HA imposent le mode de compatibilité ; aucune réduction prouvée. |
| Dépendances indirectes : [SourceBundle](../scripts/ha_session_supervisor.py#L91) copie tous les modules *.py ; [intégrité #219/#186](../tests/js/data-updated-integrity-219.test.cjs#L28) exige le module shadow et refuse mutation/omission. | [Drop](../tests/test_data_updated_drop_219.py), push Python/HA et [disponibilité](../ha_tests/test_connection_availability_219.py) gardent faux messages sans #160/reconnect, vrai EOF/cleanup, retries #212, refus d'ancienne génération et perte réelle >300 s sans fraîcheur fabriquée. | **Conserver** ces garanties indépendantes. Toute éventuelle modification runtime devrait faire arbitrer séparément la dépendance d'intégrité ; B8 ne change ni empreinte ni gate. Les quatre familles ciblées ne remplacent pas ces régressions. |

Méthode : lecture à SHA fixe, recherche textuelle sur 105 fichiers runtime/scripts
et 296 fichiers tests/docs/supports, puis inspection des appels/fixtures repérés.
Le seul import_module de ces scripts charge la sonde boundary nommée ; le glob
SourceBundle constitue un consommateur sans import textuel direct du module.
Pas d'AST ou de trace d'exécution obtenus : cette recherche ne démontre pas
l'absence d'usages privés/dynamiques inconnus. [La documentation](data-updated-recovery.md#L119)
maintient explicitement le FIFO indépendant ; les sections historiques ne
remplacent pas le contrat push actuel. _private_register_journal et _candidate_words
sont importés par valeur dans v4_session : un futur test de substitution doit
viser le symbole réellement consommé, sans neutraliser le chemin de production.

Coût : **pytest ciblé --durations=20 NOT RUN**, aucune durée ni accélération CI
inventée. Le Cloud sélectionné a échoué avant le shell : environment_startup_failed,
container_creation/container_service_failed/transport_failed. Source/base et
état failed/offline vérifiés ; aucun checkout/exécuteur utilisable. Les quatre
fichiers contiennent statiquement 8 / 18 / 1 / 2 fonctions de test, avec
paramétrisations ; ce ne sont pas des comptes de collecte ou des mesures.
Commandes de reproduction sur cette base, non exécutées ici :

```sh
python3.12 -m pytest -q tests/test_shadow_data_updated_219s.py tests/test_private_data_updated_219.py --durations=20
python3.14 -m pytest -c ha_tests/pytest.ini -q ha_tests/test_shadow_data_updated_219s.py ha_tests/test_private_data_updated_219.py --durations=20
```

Les quatre CI du HEAD B8 et leurs résultats sont consignés dans PR/#189 ;
leurs durées globales ne sont pas celles de cette sélection. git diff --check
et Ruff locaux **NOT RUN** pour la même panne ; ajout seul, liens/lignes et
espaces vérifiés via le connecteur, lint/tests ordinaires vérifiés en CI.
Diff limité à cette annexe ; exécutables/tests byte-identiques à la base,
pas de CHANGELOG (audit interne sans effet HACS/API). Aucun retrait engagé,
aucun lot suivant attribué ; arbitrages E5/E6 ouverts. Tests réels **NOT RUN** :
aucun dispatch/rerun live, commande/écriture Modbus, secret/GUID/RX/valeur privée,
main/release/tag/version ou fusion DEV. TLS certificat/hostname vérifiés vers
myhoben.fr:465 et V4 lecture seule préservés ; state:review puis arrêt.

## Annexe B9 — pilote WARNING examiné, instrumentation non retenue

Tâche `HOBEN-189-B9-PLUGIN-WARNING-USAGE-PILOT-025`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Base `experimental` : `86c646bc173ad54def4bb393d248b076aae5ad98` (25/11/2026).
**Sortie d'audit seule autorisée : aucun candidat admissible démontré dans ce
balayage limité ; proposition de trace non retenue.** Aucun WARNING, changement
runtime, test ajouté, désactivation ou suppression. Shadow/FIFO B8 hors périmètre.

| Auxiliaires examinés / preuve d'appel | Conséquence pour le pilote |
| --- | --- |
| [entity](../custom_components/hoben/entity.py), [sensor](../custom_components/hoben/sensor.py), [binary_sensor](../custom_components/hoben/binary_sensor.py), [session_sensor](../custom_components/hoben/session_sensor.py) : plateformes transmises par __init__, création explicite des entités ; callback moniteur et timer local 60 s du capteur de session. [Tests entités](../ha_tests/test_entities.py), [session](../ha_tests/test_session_sensor.py). | Chemins ordinaires déjà reliés à l'installation et aux publications HA ; les tracer ne tranche pas un usage incertain. Le garde de type précis est examiné ci-dessous. |
| [helpers](../custom_components/hoben/helpers.py), [safe_reports](../custom_components/hoben/safe_reports.py), error_phases : identité et erreurs expurgées appelées par config_flow, __init__, coordinator. [Test helper](../ha_tests/test_helpers.py). | Hors candidat : fonctions actives ou sensibles à la confidentialité/authentification, pas une sonde d'usage neutre. Ne pas provoquer d'erreur pour obtenir une trace. |
| [session_monitor](../custom_components/hoben/session_monitor.py), session_observation, session_diagnostics : imports client/coordinator/lifecycle/session et consommateurs dans scripts d'observation. [Tests moniteur](../tests/test_session_monitor.py). | Flux courant de statut et preuves bornées ; chemins d'erreur/cleanup non garantis dans 24 h normales. Conserver, sans log dans RX/TX, timings ou sécurité. |
| [diagnostics](../custom_components/hoben/diagnostics.py) : hook HA de téléchargement, projection session via project_report ; [test endpoint HA](../ha_tests/test_diagnostics.py#L279). | Appel conditionné par une demande de diagnostic, pas une activité passive attendue chaque jour. Son absence ne prouve pas une inutilité ; projection privée à préserver. |

**Un seul candidat de branche examiné** : dans
[HobenSessionSensor.native_value, ligne 36](../custom_components/hoben/session_sensor.py#L34),
le terme `type(self.client) is not HobenClient` renvoie disconnected. L'entrée
normale construit explicitement HobenClient ; [les fixtures HA](../ha_tests/conftest.py#L71)
peuvent fournir un Mock. Aucune substitution normale du client n'est établie
dans le graphe examiné. Le terme voisin `_shutdown_requested` relève, lui,
de l'arrêt normal : tracer le garde commun confondrait ces deux causes.
Un WARNING limité au type différent n'aurait pas de sollicitation normale
identifiée pendant 24 h. Candidat donc **non retenu**, sans le déclarer mort
ni retirer sa protection de compatibilité. Les tests entités sur client simulé
et session sur véritables propriétaires couvrent des contextes distincts.

Méthode : inventaire des 35 modules Python, lecture ciblée des auxiliaires,
recherche rg et AST des imports de 98 fichiers runtime/scripts ; inspection de
la délégation HA, de l'import_module nommé et du glob SourceBundle qui copie
les modules. Pas de preuve universelle sur des extensions externes ; la
déclaration propriétaire sur les consommateurs ne remplace pas les liens internes.
Prochain périmètre proposé au MANAGER : recensement hors ligne des tests
helpers/diagnostics et de leurs fixtures partagées, sans instrumentation runtime.
C'est une proposition, pas une nouvelle tâche attribuée.

**Observation future, seulement après un autre pilote admissible et fusionné** :
propriétaire confirme le SHA instrumenté effectivement chargé, le début de la
collecte WARNING et le processus concerné, puis 24 h normales sans nouveau
changement sur ce chemin. B9 n'émet pas HOBEN189_B9_USAGE : aucun SHA à installer
pour ce pilote. Une future trace devrait garder marqueur/branche constants,
une fois par processus, sans contenu privé, et supporter un logger défaillant.
Trace observée : chemin utilisé, conserver. Trace absente mais sollicitation
normalement attendue : vérifier sollicitation réelle, SHA, filtres/rétention,
redémarrages et éventuelle émission avant la fenêtre ; aucune preuve de code mort.
Résultat ambigu : soumettre une phase distincte de désactivation réversible,
sans suppression, revue/quatre CI puis nouvel essai propriétaire séparément
autorisé. Aucun essai ni désactivation réalisé ou déclenché par B9.

Tests hors ligne existants du moniteur, des entités, du capteur de session,
helpers/diagnostics : 13 tests Python et 167 tests HA PASS, détails dans PR/#189 ; pas de nouveau
test miroir ni de test de marqueur inexistant. Liens, AST, diff documentaire,
Ruff/diff-check et quatre CI au HEAD exact contrôlés. Diff limité à cette annexe,
sans CHANGELOG (audit interne, aucun impact HACS/API). Tous code/tests/YAML,
droits/gates/refs Actions/manifest/version inchangés ; aucun Settings inspecté.
Tests réels **NOT RUN**, aucune installation, commande/écriture Modbus, secret,
GUID/RX/valeur privée, main/release/tag ou fusion DEV. V4 lecture seule et TLS
certificat/hostname myhoben.fr:465 préservés ; state:review, arrêt DEV et revue MANAGER.

## Annexe B10 — coût du sandbox hors ligne, protections conservées

Tâche `HOBEN-189-B10-OFFLINE-SANDBOX-CI-COST-026`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Base `experimental` : `c556980ace668244a8190db8379e9a8f1eec5a16` (25/11/2026).
**Audit seul : aucun changement sûr de test démontré, aucun retrait ni gain CI
revendiqué.** Les deux familles restent complémentaires, pas interchangeables.

| Famille / consommateur | Preuves spécifiques à conserver |
| --- | --- |
| [sandbox](../tests/test_ha_session_sandbox.py), 14 cas → vrai Engine local, supervisor/guardian et worker HA synthétique | DNS/IP interdits, seul socket Unix Docker fixe autorisé ; namespace sans réseau, cgroups mémoire/swap/PIDs effectifs ; healthy/CloseClient/EOF/TLS/read_timeout, mémoire/processus/forged, descendants setsid résistants avec deadline/annulation/perte du contrôle hôte, réapage vérifié par observateur indépendant. Canal stdin synthétique privé ; configuration live inspectée à l'arrêt, start refusé et feed interdit. |
| [supervisor](../tests/test_ha_session_supervisor.py), 33 cas → moteur double, vrai superviseur/SourceBundle/guardian | Refus de capacités absentes et de 12 configurations effectives falsifiées avant start ; backend absent sans fallback hôte, annulation, horloge/délais originaux, plafonds non extensibles, métriques obligatoires, bundle public non modifiable et refus des symlinks. Ne prouve pas les limites ni le réapage du noyau réel. |

### Mesures locales et limites

Python 3.12.14, Docker 28.4.0 ; moteur local annonçant cgroup v2 et contrôles
MemoryLimit/SwapLimit/PidsLimit. Même code que la base, `--durations=20`,
cache pytest désactivé, aucun changement des gardes ou des budgets.

| Passage | Résultat mesuré |
| --- | --- |
| Superviseur seul, deux processus pytest | 33 PASS en 0,17 puis 0,33 s ; appels les plus lents 0,02 puis 0,04 s. Pas de temps Docker simulé présenté comme réel. |
| Sandbox, premier build effectif | 14 PASS en 530,99 s ; setup partagé 133,19 s, dont couche pip non réutilisée 127,3 s et export de couches 5,6 s selon BuildKit. |
| Appels sandbox les plus lents | Descendants deadline/annulation 39,49/39,00 s ; perte contrôle 34,34 s ; read_timeout 33,57 s ; TLS 32,89 s ; mémoire 32,49 s. Healthy 9,25 s, CloseClient 24,92 s, EOF 29,26 s ; ce sont des durées d'appel complètes, pas les durées internes du reçu. |
| Rebuild identique immédiatement après | 0,214 s, succès ; COPY et pip CACHED. Même commande que la fixture, socket Unix et CA vérifiée conservés. |
| Cas configuration arrêtée, image chaude | 1 PASS en 34,83 s : setup 0,35 s, call 34,44 s ; requête create 32,780 s, DELETE 1,614 s, autres requêtes ≤0,019 s. Aucun start/feed effectif. |
| Contrats adjacents | 166 PASS en 6,91 s : ha_live_proof, ha_manual_live, ha_manual_live_diagnostics, ha_session_proof ; synthétiques uniquement. |

Ce n'est **pas un cold complet** : base/COPY déjà disponibles après les essais
préparatoires ; caches ni images purgés, aucun cache CI introduit. Premier essai
restreint : 1 FAIL (création de socket refusée par l'exécuteur), 13 SKIP ; puis
1 PASS/13 ERROR (configuration Docker en lecture seule), et 1 PASS/13 ERROR en
36,46 s (build sans accès direct à PyPI). Relance avec support sockets du
harnais et configuration Docker temporaire sous /tmp utilisant le proxy fourni,
sans publier ses valeurs ni désactiver TLS. Gardes DNS/IP, Engine Unix fixe et
`Env=[]`/`network=none` des workers inchangés. Les échecs ne sont pas des mesures
de scénarios exécutés. Aucune modification des dépendances épinglées.

La fixture image est **déjà session-scoped** : un build partagé par processus
pytest, pas un build par cas. Le rebuild chaud ne démontre donc pas un gain à
obtenir par changement de scope. Les durées d'appels incluent préparation,
échanges Engine, exécution et nettoyage : ne pas les confondre avec le plafond
du reçu ni réduire les deadlines pour masquer un coût non attribué.
Le cas arrêté a été chronométré par wrapper temporaire de Engine.request,
appel original inchangé, sans enregistrer corps/réponses/noms de conteneurs.
Il situe son coût avant start, dans create ; pas une preuve universelle pour les
autres cas. Pas de deuxième suite sandbox complète chaude ni cold entièrement
vide. Contrats adjacents et second superviseur ont chevauché respectivement
le build initial et le cas arrêté : mesures de conditions locales, pas benchmark
CPU isolé ni comparaison avant/après optimisation. Aucun changement proposé.

Reproduction : `python -m pytest -q -p no:cacheprovider --durations=20 -rs`
suivi de `tests/test_ha_session_sandbox.py`, puis de
`tests/test_ha_session_supervisor.py` dans un processus distinct. Si moteur ou
capacités absents, fixture SKIP et runtime NOT RUN sans fallback ; si build
disponible mais échoué, erreur conservée, jamais convertie en succès.

### CI comparable et décision

[B8/45656942877](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/45656942877)
et [B9/45664490965](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/45664490965) :
mêmes fichiers ciblés/runtime/Validate, Python 3.12 sur ubuntu-latest,
10 229 PASS en 237,83/204,15 s. Écarts entre dernière ligne du module précédent
et ligne sandbox : 113,04/101,70 s ; ligne supervisor suivante : 0,16/0,13 s.
**Intervalles de sortie pytest**, pas `--durations` historiques : buffering,
build, couches et état du runner non séparables ; aucune attribution certaine
de 117 s au module actuel ni extrapolation du Cloud vers un gain GitHub.

Conserver tests, assertions, fixtures et délais. Une équivalence de couverture
ou une attente évitable n'est pas établie ; substituer les doubles au noyau,
réduire des marges ou contourner une préparation échouée affaiblirait la preuve.
Recommandation : obtenir des durées détaillées comparables avant un éventuel
petit lot distinct, sans modifier Validate ni attribuer cette suite ici.
Diff B10 : cette annexe seule ; pas de CHANGELOG (audit interne sans effet
HACS/API). Ruff/diff-check, ciblés et quatre CI du HEAD exact consignés dans
PR/#189. Aucun plugin/script/test/fixture/YAML/gate/droit/cache/dépendance,
manifest/version modifié. Tests Hoben/HA réels **NOT RUN** ; pas de dispatch,
commande/écriture Modbus, donnée privée, main/release/tag ou fusion DEV.
V4 lecture seule et TLS vérifié myhoben.fr:465 préservés ; revue MANAGER puis arrêt.

## Annexe B11 — audit croisé DataUpdated delivery/drop Python–HA

Tâche `HOBEN-189-B11-DATAUPDATED-CROSS-SUITE-TEST-AUDIT-027`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/189#issuecomment-7048670130).
Base `experimental` : `104cec1b73ff47364f831db4b80c5e1b5df764c5` (26/11/2026).
**Conserver les quatre fichiers et leurs 44 cas : aucune équivalence complète
autorisant fusion/suppression démontrée.** Audit documentaire seulement.

### Préconditions et chemin réellement exercé

Codes de la matrice : [PD : Python delivery](../tests/test_data_updated_delivery_219.py),
[HD : HA delivery](../ha_tests/test_data_updated_delivery_219.py),
[PX : Python drop](../tests/test_data_updated_drop_219.py),
[HX : HA drop](../ha_tests/test_data_updated_drop_219.py).
Les noms de fonctions ci-dessous omettent seulement le préfixe test_.

PD/PX utilisent les vrais V4Lifecycle/V4Session et leur RX/framer, via
[Factory](../tests/test_v4_persistent.py#L43) et Stream en mémoire : ouverture et
réponses V4 synthétiques déclenchées par TX ; assert_clean contrôle fermeture
unique, absence d'I/O actives, opérations/waiters/timer et RX terminés.
[make_owner/Clock/pump](../tests/test_data_updated_silence.py#L30) activent
ha_reconnect/recover_acquisition, sans callback de données ; Clock remplace
l'horloge du loop et l'avance sans attente, pump cède 40 tours, Backoff est libéré explicitement.
Aucun coordinator, registre d'entités ni état HA n'est créé par PD/PX.

HD/HX chargent réellement l'intégration, client/coordinator et capteurs, via
[peers/load/sensor/assert_stopped](../ha_tests/test_persistent_client.py#L40).
Le transport seul est simulé ; le harness HA bloque les sockets externes et
[no_hoben_network](../ha_tests/conftest.py#L32) refuse un transport non remplacé.
**peers dépend de [legacy_polling_client](../ha_tests/conftest.py#L129)** :
push_updates=False ; il conserve aussi le backoff historique, pas le timing
rapide de production. Le décodeur V4 alimente le snapshot initial réel.
HD désabonne le refresh existant, puis vérifie une lecture explicite dans deux
cas ; HX vérifie au contraire l'identité d'un timer de polling encore présent.
Unload vérifie fermeture, effacement d'identité et absence de tâches lifecycle/RX.

Cela ne contredit pas [l'entrée de production](../custom_components/hoben/__init__.py#L61),
qui active push_updates=True. Le [routage commun](../custom_components/hoben/v4_session.py#L754)
consomme une livraison entière admissible avant le framer, appelle le parser
structurel et son diagnostic expurgé ; sans callback, aucune publication HA.
Avec callback, la forme applicative admise produit RawStoveSnapshot et passe par
decode_v4_snapshot, lifecycle/client puis coordinator._data_updated. Les
[tests push voisins](../ha_tests/test_data_updated_push_219.py#L20) rétablissent
le constructeur de production et attendent des mises à jour atomiques ; leurs
préconditions ne sont donc pas équivalentes à HD/HX. Les commentaires historiques
« mapping unproven » de HX décrivent une fixture de compatibilité, pas la décision
propriétaire actuelle. Aucun fait protocolaire ni fichier de test corrigé ici.

### Matrice des cas, recouvrements et différences

Chaque ligne : **conserver** ; nombre = cas pytest, pas nombre de notifications.

| Source / fonction | Cas | Assertions et différence de couverture |
| --- | --- | --- |
| [PD each_whole_delivery_is_diagnosed_without_an_acquisition](../tests/test_data_updated_delivery_219.py#L20) | 1 | Trois événements, index 1–3, taille/scope read_delivery, boundary_proven=false ; aucune acquisition, TX d'ouverture seul. HD commence après une vraie lecture et vérifie des objets HA absents ici. |
| [PD fragment_is_not_reassembled_or_left_in_the_mbap_framer](../tests/test_data_updated_delivery_219.py#L54) | 5 | Coupures 1/5/10/14/53 : diagnostic incomplete, aucun tampon MBAP/recollage/récupération ; livraison complète suivante parsed sans TX. HX réutilise ces préfixes, sans vérifier chacun des restes ni le framer. |
| [PD adjacent_suffix_is_never_scanned_or_credited_to_pending_v4](../tests/test_data_updated_delivery_219.py#L87) | 3 | Suffixe Ping, début réponse ou seconde notification : ambiguous/delivery_suffix, taille exacte, waiter toujours pendant, aucune séquence ni scan. HD teste une autre concaténation sans requête en vol ; PX inflight va jusqu'à une réponse corrélée. |
| [PD payload_byte_1b_continuing_a_real_partial_0e_is_not_a_notification](../tests/test_data_updated_delivery_219.py#L121) | 1 | Une continuation 0E contenant des octets 1B termine la vraie réponse, sans événement DataUpdated ; non couvert par des candidats lus au repos. |
| [PD delimited_message_before_1b_survives_but_the_suffix_is_not_a_new_read](../tests/test_data_updated_delivery_219.py#L144) | 2 | Ping/Pong ou réponse corrélée préservé ; suffixe not_read_start sans valeurs et garde #160 active. Distinct d'un candidat frais invalide que PX/HX doivent jeter sans garde. |
| [PD opening_residue_is_not_relabelled_as_a_complete_read_delivery](../tests/test_data_updated_delivery_219.py#L176) | 1 | Résidu de handshake : taille de livraison inconnue, not_read_start et garde active, pas une nouvelle lecture. Aucun paramètre HA équivalent. |
| [PD counter_saturates_but_every_delivery_still_emits_an_event](../tests/test_data_updated_delivery_219.py#L201) | 1 | Trois événements encore émis à 65535, counter_capped vrai ; pas d'acquisition/récupération. HX vingt événements ne sollicite pas la saturation. |
| [PD reconnect_keeps_generations_separate_and_never_replays_old_candidates](../tests/test_data_updated_delivery_219.py#L226) | 1 | EOF, génération/index réinitialisés, ancien RX non rejoué ; seule vraie lecture nouvelle crédite génération 2. PX EOF part de vingt invalides et contrôle explicitement cleanup avant réouverture. |
| [PD failed_logging_handler_cannot_change_rx_or_read_correlation](../tests/test_data_updated_delivery_219.py#L264) | 1 | Logger qui lève : RX reste connecté, vraie lecture corrélée possible. Ce n'est pas l'exception du parser testée par PX/HX. |
| [PD ineligible_notification_closes_the_read_gate_before_awaiting_prior_pong](../tests/test_data_updated_delivery_219.py#L292) | 1 | Pong suspendu : garde déjà fermée avant await, aucune lecture pendante/TX ajoutée ; puis Pong seul. Aucun test HA de cette compétition. |
| [PX invalid_candidate_never_enters_silence_guard_or_creates_a_probe](../tests/test_data_updated_drop_219.py#L34) | 13 | Cinq préfixes, protocole/longueur MBAP invalides, PDU vide/impair/tronqué, fonction non admise, deux concaténations ; chaque cas après initiale. Avance 301 s, aucun probe/garde/échec/lecture, même RX/TLS ; Ping puis parsed ne créditent pas V4. HX couvre le lot, pas cette échéance monotone. |
| [PX parser_failure_is_closed_diagnostic_without_private_exception_or_recovery](../tests/test_data_updated_drop_219.py#L77) | 2 | Parser qui lève OU retourne un mauvais type : parser_failure sans valeur/exception privée ; parseur restauré, RX/Pong utilisables. HX ne simule que la levée, mais avec vingt livraisons et état HA. |
| [PX drop_does_not_complete_or_abandon_an_inflight_v4_request](../tests/test_data_updated_drop_219.py#L114) | 3 | Préfixe, longueur invalide ou suffixe ; notification/Ping puis vrai 0E : une seule requête réussit, compteur d'échec nul. PD suffixe constate seulement le waiter non terminé avant annulation. |
| [PX real_eof_after_drops_still_requires_cleanup_before_next_generation](../tests/test_data_updated_drop_219.py#L135) | 1 | Vingt invalides n'entraînent aucune fermeture ; vrai EOF impose cleanup avant génération 2 et vraie lecture, ancien candidat laissé dans l'ancienne queue. HX unload ne remplace pas une reconnexion après EOF. |
| [PX dropping_candidate_neither_resets_v4_deadline_nor_disables_212](../tests/test_data_updated_drop_219.py#L167) | 1 | Drop à 29 s, timeout original à 30 s, retry seulement 60 s après, RX maintenu sans garde. HX n'avance ni cette échéance ni le compteur #212. |
| [HD notification_preserves_ha_snapshot_freshness_and_polling](../ha_tests/test_data_updated_delivery_219.py#L26) | 5 | parsed/unsupported/incomplete/ambiguous/malformed : statut et taille exacts, mêmes data/capteur/timestamp, listener silencieux, même RX, aucun backoff/close/TX ajouté, logs expurgés. parsed est un candidat structurel de deux mots, pas une forme push admise. parsed/unsupported autorisent ensuite une vraie lecture ; PD ne possède aucun objet HA. |
| [HX twenty_drops_then_valid_keep_tls_ha_snapshot_and_existing_poll](../ha_tests/test_data_updated_drop_219.py#L19) | 2 | Sans/avec erreur parser : vingt livraisons cyclent sur 13 formes (pas 20 uniques), vingt diagnostics, timer/snapshot/timestamp/capteur/listener préservés ; parser restauré puis parsed/Pong, vraie lecture avance fraîcheur/séquence, unload propre. Recouvre les formes PX et certains statuts HD, sans leurs assertions individuelles, mauvais type, échéances ou frontières. |

Recouvrements réels : diagnostic commun, même RX, absence de TX/acquisition
fabriquée pour candidat frais, puis réponse V4 encore utilisable. Même entrée
« double notification » dans PD/PX, mais waiter en vol contre état après initiale
et horloge avancée ; mêmes INVALID dans PX/HX, mais isolation par cas contre lot
avec état/timer HA. Le [parser pur voisin](../tests/test_data_updated_parser_219.py)
valide les structures et la confidentialité, pas le routage RX ni les entités.
AST : 17 corps de fonctions test distincts parmi ces quatre fichiers ; absence
de doublon syntaxique ne démontre ni indépendance des branches ni équivalence
sémantique. Pas de mesure de couverture de branches/mutations revendiquée.

### Dépendances actives, coût et registre cumulatif

Imports AST/rg : reports (PD) est consommé par PX, HD et HX ; INVALID (PX) par
HX, [HA push](../ha_tests/test_data_updated_push_219.py#L16) et
[HA disponibilité](../ha_tests/test_connection_availability_219.py#L22).
notification/response/candidate et Clock/Backoff sont partagés ; un helper
identique n'est pas un doublon d'assertions. Fixtures pytest importées peers,
délégation du loader HA et script_transport exécutent les propriétaires réels,
pas un mock de coordinator. Découverte par les deux jobs distincts de
[Validate](../.github/workflows/validate.yml) ; aucun consommateur runtime des
fonctions test ni besoin de les copier dans SourceBundle identifié.

Mesures par fichier dans quatre processus successifs, hors ligne, caches pytest
désactivés et bytecode désactivé pour cette série ; dépendances existantes sous
/tmp, Python 3.12.14 ou 3.14.7/harness HA 0.13.367. Support sockets de l'exécuteur
requis par asyncio, gardes réseau du test/harness inchangés. Aucun SKIP/NOT RUN
dans les ciblés. Une mesure par fichier, caches OS non purgés ; pas un gain CI.

| Fichier | Cas PASS | Temps pytest / processus mural | --durations=20 observé |
| --- | --- | --- | --- |
| PD | 17 | 0,10 / 0,373 s | Phases du top 20 sous 0,005 s à la résolution affichée. |
| PX | 20 | 0,11 / 0,420 s | Phases du top 20 sous 0,005 s. |
| HD | 5 | 0,44 / 2,430 s | Setup maximal 0,16 s, call 0,05 s, autres calls 0,03 s. |
| HX | 2 | 0,29 / 1,924 s | Setup maximal 0,15 s, calls 0,05/0,03 s. |

Commandes : `python -m pytest -q -p no:cacheprovider --durations=20 <fichier>` ;
HA ajoute `-c ha_tests/pytest.ini`. Temps processus = chronomètre monotone autour
de subprocess.run, inclut lancement/plugins/collecte/arrêt, contrairement aux
seuls temps call. Première vérification groupée : 37 Python PASS/0,56 s et
7 HA PASS/1,10 s dans deux processus concurrents ; non utilisée comme mesure
isolée. Voisins de contexte : 147 Python et 36 HA PASS, sans prétendre les avoir
audités exhaustivement. Ruff check/format (361 fichiers), liens et diff-check
PASS ; CI du HEAD exact dans PR/#189. [CI B10](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/45715814145)
confirme les quatre fichiers (17/20/5/2 cas) dans 10 229 Python et 917 HA PASS,
sans --durations par fichier : aucune durée ciblée CI déduite des timestamps.

Registre cumulatif : C1–C5 conservent preuves/validateurs et limites de coût ;
B8 conserve shadow/FIFO et B10 le sandbox. Cette tranche ajoute **quatre fichiers,
44 cas analysés, tous conserver** ; ni inventaire global terminé ni suppression
candidate démontrée. Tranches proposées au MANAGER, non attribuées : push et
ordering/générations ; ignore/silence/framing ; private/shadow en réutilisant B8 ;
puis autres tests Python/HA, JS et contrats/fixtures de workflows manuels en
lecture seule. Chaque tranche devra ajouter fichiers/cas/fixtures, consommateur,
équivalence et coût mesuré au registre ; une suppression éventuelle exigerait
une PR distincte avec preuve avant/après et quatre CI, jamais un retrait ici.

Diff B11 : cette annexe seulement, audit antérieur intact ; aucun code/test,
fixture/CI/cache/dépendance/gate/droit/manifest/version modifié. Pas de CHANGELOG
(audit interne sans effet HACS/API). Tests réels Hoben/HA **NOT RUN** ; aucun RX
brut/identifiant privé publié, dispatch/rerun live, commande/écriture Modbus,
inspection de protection native, main/release/tag ni fusion DEV. TLS vérifié
myhoben.fr:465 et V4 lecture seule préservés ; state:review, revue MANAGER et arrêt.
