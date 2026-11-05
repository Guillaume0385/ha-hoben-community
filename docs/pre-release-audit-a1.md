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
| [launch_live_ha_parity.py](../scripts/launch_live_ha_parity.py) | C | fixture hoben-live-experimental, tests et ancien contrat | T5 | présent |
| [run_live_ha_parity.py](../scripts/run_live_ha_parity.py) | C | subprocess du lanceur parity ; pas le coordinator actuel | T5 | présent |
| [launch_session_300.py](../scripts/launch_session_300.py) | C | ancienne fixture, tests ; lance run_session_300, moteur partagé | T2/T5 | présent |
| [launch_session_suite.py](../scripts/launch_session_suite.py) | C | ancienne fixture/tests ; subprocess run_session_suite | T2/T5 | présent |
| [run_session_suite.py](../scripts/run_session_suite.py) | C | launch_session_suite ; conservé en compatibilité/test | T2/T5 | présent |
| [probe_hoben_connection.py](../scripts/probe_hoben_connection.py) | C | CLI documentée et tests ; références des plans non exécutables | T2/T5 | présent |
| [v4_validation_values.py](../scripts/v4_validation_values.py) | C | import par probe_hoben_connection ; export privé manuel historique | T5 | présent |
| [replay_opened_client_boundary.py](../scripts/replay_opened_client_boundary.py) | C | outil de replay offline documenté et testé ; pas un collecteur live | T5 | présent |
| [session_natural_900.py](../scripts/session_natural_900.py) | C | tests et référence de plan ; aucune nouvelle admission autorisée | T2 | présent |
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
| [github_campaign_workflow_blob.py](../scripts/github_campaign_workflow_blob.py) | C | tests et doc ; identité des octets Git, pas sémantique YAML | T6 | absent |
| [github_campaign_actions_registry.py](../scripts/github_campaign_actions_registry.py) | C | tests et doc ; métadonnées partielles du registre Actions | T6 | absent |

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
