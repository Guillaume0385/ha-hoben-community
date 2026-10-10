# Circuit expérimental Hoben — validation Home Assistant et recherche réseau

> Décision du propriétaire, 9 octobre 2026 — **aucune PR vers `main` sans demande explicite de l'utilisateur**. Cette page définit le workflow souhaité et l'exécution autorisée sur `experimental`. Elle ne prouve ni la présence des secrets/environnements, ni la disponibilité actuelle de tous les workflows GitHub. Ne jamais confondre code de test préparé, workflow installé, dry-run et test Hoben réel.

> **Contrat préparé par la PR #67, applicable seulement après revue et fusion :**
> les nouveaux essais H1/H2 exportent exclusivement le rapport anonymisé validé.
> Aucune capture RX ne sort du runner. Les mentions d'artefacts CMS ci-dessous
> décrivent les anciennes exécutions, pas un prérequis de clé pour ce chemin.
> Une CI verte ne démontre ni son installation ni une collecte réelle.

## Campagnes répétées — décision propriétaire du 10 octobre 2026

**État de la PR #75 après la revue du 10 octobre : NON LIVRÉ / NOT RUN.**
Ce qui suit est le **contrat cible** imposé par le propriétaire, pas une
description des gates installés. Les fichiers actuels
`experimental-lab-gate.cjs`, `experimental-live-gate.cjs` et les workflows
secrets restent inchangés ; à ce stade ils refusent toujours les
`run_attempt > 1`, exigent encore `Refs #54` et ne savent pas réserver
plusieurs tentatives. Le déclencheur temporaire rejeté a été retiré.
**Aucun clic « Re-run all jobs » ne doit être considéré comme autorisation
d'accès Hoben avant fusion d'un correctif complet, revu et testé.**
La PR #75 est explicitement interdite de fusion sans nouvel accord
du propriétaire.

Le propriétaire a **rejeté la création de branches temporaires**. La méthode
actuelle est exclusivement **GitHub Actions → ouvrir un run existant de
`Hoben experimental (MANAGER)` ou `Hoben live HA parity (MANAGER)` →
`Re-run all jobs`**. Les deux workflows restent abonnés au seul `push` de
`experimental`. Ne pas utiliser `Re-run failed jobs`, une relance d'un job
isolé, `workflow_dispatch` indisponible ou un commit factice. Le rerun
exécute le YAML et le code du **SHA d'origine**, donc seules les exécutions
créées après fusion d'un correctif pourront en hériter. La connexion MANAGER
n'expose actuellement pas le rerun complet ; le propriétaire accepte de
cliquer manuellement `Re-run all jobs` dans GitHub Actions.

**Autorisations indépendantes :** tentative 1 → commentaire pré-fusion
`hoben-experimental-approval:v1` ou `hoben-live-approval:v1` avec
`schema=1,scenario,candidate_sha,ci_run_id`. Tentative N>1 → **nouveau**
commentaire MANAGER non modifié au format v2, rattaché à la PR d'origine et
identifiant **exactement** son `candidate_sha`, `ci_run_id`, `merge_sha`,
`pr_number`, `run_id`, `run_attempt` et `scenario`.
Une décision v1 n'autorise **jamais** les tentatives ultérieures.
L'autorisation v2 doit être postérieure à la fusion et antérieure au
démarrage de la nouvelle tentative. Les deux scénarios ont des marqueurs et
décisions séparés. Un `Re-run all jobs` n'est que le déclencheur physique :
sans décision v2 préalable et sans toutes les gates, **NOT RUN**.

Les admissions et rechecks devront vérifier la provenance du push initial,
l'identité distincte `triggering_actor`, HEAD encore exact sur branche
`experimental` protégée, PR fusionnée par MANAGER et arbre testé, les 4 jobs
CI `tests/ha-tests/hacs/hassfest`, la politique d'environnement GitHub,
l'approbation d'environnement réelle quand configurée et un nouveau claim
atomique par `run_id/run_attempt/scenario/SHA`. Le dry-run et l'admission
doivent appartenir à **la tentative en cours**, sans réutiliser un
ancien succès de job. Le runner doit refuser toute preuve de relance
complète insuffisante et toute tentative partielle. L'exécution est
sérialisée par `hoben-read-only-observation` et les rapports/artefacts
anonymisés sont séparés par tentative, avec rétention maximale de 7 jours.
Aucun RX brut, GUID, secret ni donnée domestique n'est publiable.

**Éligibilité de toute PR `experimental` :** la PR d'origine peut porter
sur du code, des tests, de la documentation, des workflows ou un protocole,
avec ou sans `Refs #54`. Cela ne vaut jamais autorisation de secret.
Les gates ne devront plus exiger de lien bloquant avec l'état de l'Issue #54 ;
ils exigent à la place les preuves exactes de **la PR choisie**, revue
MANAGER et CI. Une PR documentaire ne déclenche aucun Hoben réel sans
décision propre au scénario.

**Limite de livraison :** ne jamais fusionner PR #75 sans l'accord
supplémentaire explicite du propriétaire. Aucun test live n'est exécuté
par CODEX DEV ; le MANAGER vérifie les tentatives réelles sur GitHub et
consigne `NOT RUN` si une preuve fait défaut. Les anciennes instructions
historiques de cette page qui imposent `Refs #54` ou un unique SHA/campagne
sont remplacées par le contrat ci-dessus.

## Deux voies distinctes sur `experimental`

| Voie | Environnement GitHub | Objectif | Intégration Home Assistant |
| --- | --- | --- | --- |
| **`hoben-live`** | `hoben-live` | Valider sur le serveur réel Hoben l'authentification, la connexion TLS, l'attribution/conservation DeviceGuid, la gestion de session, les lectures V4, disponibilité/reconnexion et cycle de vie **avec les mêmes composants et le même comportement que le plugin Home Assistant au commit testé** | Réutiliser autant que possible le client, les modèles et les chemins réellement utilisés par HA ; constater les écarts sans inventer de succès |
| **`hoben-experimental`** | `hoben-experimental` | Confronter H1/H2 et rapporter des chronologies anonymisées ; nouveaux essais de #67 sans export de capture, artefacts CMS historiques distincts | **Jamais intégré au runtime HA** : les collecteurs, hypothèses de framing et instruments de capture restent dans les scripts/fixtures de laboratoire |

Les deux voies sont des expériences en lecture seule, exécutées depuis GitHub Actions, sur un SHA **fusionné et revu** de `experimental`. Elles ne modifient pas le poêle : aucune commande de marche/arrêt, changement de consigne, ventilation, écriture Modbus (06/16/22), association ou accès installateur. La destination de production est le serveur TLS déjà documenté dans `protocol.md`, avec validation du certificat.

**`hoben-live` ne signifie pas que le runtime est déjà correct ou persistant.** Il doit vérifier le comportement du code réellement présent et créer une Issue lorsqu'un écart est observé. **`hoben-experimental` ne peut pas servir de preuve de qualité du plugin** : ses hypothèses sont distinctes du protocole confirmé.

## Workflow GitHub et autonomie

```text
CODEX DEV : petite Issue autorisée → développement + tests offline
   ↓
PR vers experimental, base.ref = experimental, state:review
   ↓
MANAGER : revue directe du diff/HEAD/CI, confidentialité, lecture seule
   ↓
MANAGER : merge automatique vers experimental (si conditions satisfaites)
   ↓
MANAGER : déclenche en autonomie le scénario hoben-live et/ou hoben-experimental
   ↓
GitHub Actions : gate + environnement effectif + éventuelle approbation GitHub
   ↓
MANAGER : résultat expurgé, observations, protocol.md étayé si applicable
   ↓
MANAGER : Issues dédupliquées → state:ready pour la prochaine tâche autorisée
   ↓
CODEX DEV : reprend le cycle
```

- **Aucune approbation supplémentaire dans la conversation ChatGPT** n'est requise avant un test expérimental prévu par cette politique. MANAGER peut lancer, lire les résultats et préparer une nouvelle Issue sans attendre la réponse de l'utilisateur. **Une approbation d'environnement exigée par GitHub reste applicable : jamais de bypass, de modification de Settings, ni d'accès aux secrets avant accord effectif du reviewer GitHub.**
- Plusieurs PR/Issues peuvent être fusionnées **successivement** sur `experimental` sans contrôle du propriétaire ; la revue MANAGER du SHA exact et la CI pertinente restent obligatoires. Éviter les grands chantiers simultanés ; ne déclencher de nouveau test que si le scénario/SHA a réellement changé et est revu.
- Chaque étape effectuée déclenche une notification informative MANAGER (`EXP-REVIEW`, `EXP-MERGE`, `EXP-TEST-START`, `EXP-TEST-RESULT`, `EXP-PROTOCOL`, `EXP-ISSUES`, `EXP-NEXT`) et MANAGER **continue**. Aucun doublon de notification pour le même run/SHA/état.
- **Aucune promotion vers `main` décidée par MANAGER** : seul le propriétaire peut demander de **préparer** la PR finale. Sans sa demande, pas de branche de promotion, pas de PR vers `main`, pas de merge. Lorsqu'elle est explicitement demandée, reprendre la revue CODEX REVIEW indépendante, les tests et règles de livraison stables ; aucune réussite expérimentale ne les remplace.

## Mise en place technique — état actuel et travaux #54

La PR #55 a été fusionnée sur `experimental`, apportant `scripts/run_experimental_boundary.py` et la capture/analyse H1/H2 ; ces scripts ne sont pas importés par le plugin HA. Le bootstrap précédent de la PR #56 visait `main` et a été fermé **sans fusion** ; ses mécanismes testés constituent au mieux des éléments de référence **à adapter**. Les workflows existants `live-validation.yml`, `manager-live-hoben.yml` et `opened-client-boundary.yml` conservent aujourd'hui des déclencheurs/règles liées à `main` : **ne pas les présenter comme des workflows expérimentaux opérationnels avant le développement et l'installation réels**.

L'Issue [#54](https://github.com/Guillaume0385/ha-hoben-community/issues/54) demande la mise en place des **deux voies** sur `experimental` avec un gate fiable, des scénarios allowlistés, une preuve de déclenchement MANAGER réellement faisable via sa connexion GitHub et des tests de sécurité offline.

Un workflow `issues:labeled` charge sa définition depuis la branche par défaut, pas depuis `experimental`. Un `workflow_dispatch` d'un nouveau workflow absent de `main` ne doit pas être considéré comme acquis. CODEX DEV doit sélectionner et **démontrer** un déclencheur adapté au périmètre sans fusion vers `main`. Un `push` autorisé sur `experimental` peut déclencher une étape **sans secret**, mais il ne vaut jamais à lui seul revue/autorisation de remettre les identifiants à du code nouvellement fusionné. L'absence de voie sûre ou d'outil de déclenchement se rapporte honnêtement par `NOT RUN` avec une Issue de prérequis, sans contourner GitHub.

### Phases 1 et 2 — preuves historiques

La PR #58 a installé le préflight sans secret. Le run réel
[37903694784](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/37903694784),
sur `4eb8bb90252dae41ca3e83a58e751d36f57c8fd1`, a réussi ses deux jobs
`dry-run (hoben-live)` et `dry-run (hoben-experimental)`. Cela établit le
déclencheur push après fusion MANAGER, aucune propriété réseau ou d'environnement.

La phase 2 de #54 a installé **uniquement** `hoben-experimental.yml` via
la PR #59 fusionnée dans `experimental` au SHA
`1b776a5028610083d74a11d2836bbcd5beac375d`. Le vrai run
[37923236744](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/37923236744)
a confirmé `dry-run=success` et `admission=failure` avant toute réservation :
`collect` et `result` étaient `skipped`, H1/H2 **NOT RUN**. La cause précise
n'est pas observable dans cet ancien run (exception volontairement masquée).
Cette preuve ne valide ni l'accès aux environnements ni la connexion au serveur.
Cette installation utilisait les collecteurs #55 hors runtime HA et des exports
CMS ; la voie `hoben-live` était alors différée. La phase 3 est décrite plus bas.

### Procédure MANAGER H1/H2 préparée par #67 — rapport uniquement

1. Examiner le diff complet, le HEAD exact, la confidentialité du rapport
   anonymisé, ses validations indépendantes Python/Node et les quatre jobs CI
   `tests`, `ha-tests`, `hacs`, `hassfest` du même HEAD. Vérifier l'absence
   d'export RX ; aucun certificat ou pin CMS et aucune clé privée ne sont requis.
2. Avant fusion, déposer **sur cette PR** un commentaire de décision au format
   strict ci-dessous. Remplacer `<HEAD_PR_40_HEX>` et `0` par le HEAD examiné et
   le véritable ID du run `Validate` réussi. Aucun texte additionnel, champ libre
   ou commentaire édité. Ce commentaire est une autorisation MANAGER du code,
   du scénario et de la preuve CI ; DEV ne le dépose jamais sur sa propre PR.

   ```text
   <!-- hoben-experimental-approval:v1 -->
   {"schema":1,"scenario":"h1h2","candidate_sha":"<HEAD_PR_40_HEX>","ci_run_id":0}
   ```

3. Fusionner via la connexion MANAGER vers `experimental`. Aucun autre push ne
   suffit. Le workflow du SHA fusionné exécute d'abord son propre `dry-run`
   sans environnement, secret, certificat CMS ou connexion Hoben. L'admission
   vérifie aussi la réussite effective de ce job par l'API du run courant,
   pas seulement une sortie déclarée.
4. L'admission vérifie à nouveau dépôt/acteur/sender/tentative/branche protégée,
   PR fusionnée/base/HEAD, arbre fusionné identique au HEAD revu, décision
   préalable et quatre jobs du run CI lié. Après corrections, une décision
   portant sur l'ancien HEAD reste historique et ne vaut pas pour le nouveau.
   Si GitHub a vidé `pull_requests` après fusion, la décision MANAGER authentifiée
   lie explicitement run CI, PR et HEAD ; leurs métadonnées doivent toujours
   correspondre. Une association contradictoire, une preuve manquante ou un
   check échoué sous un run vert refuse. Elle vérifie ensuite la politique réelle
   de `hoben-experimental` : exactement Branch `experimental` et
   protection effective de la branche. La décision propriétaire du 9 octobre
   autorise **aucune règle de reviewers obligatoires** dans cet environnement
   géré par un seul mainteneur, comme pour `hoben-live`. Si une règle existe,
   le gate exige toujours `prevent_self_review=true` et un reviewer User
   indépendant, puis vérifie son approbation réelle. Règle malformée, API
   inaccessible, type de politique absent de la liste et du détail, branche
   wildcard ou mauvais environnement donnent **NOT RUN**, avant secrets.
5. Une réservation atomique, tag annoté non destiné aux releases
   `hoben-experimental-h1h2-<SHA_FUSION>`, lie SHA/scénario/run/PR/décision et
   empreinte de politique. Le job qui écrit ce tag ne reçoit aucun secret Hoben.
   Une annulation ou un échec consomme aussi la réservation : jamais de suppression,
   modification ni rerun pour la réutiliser. Le workflow conserve le mutex
   `hoben-read-only-observation` pendant toute l'attente et la collecte ; jusqu'à
   100 demandes peuvent attendre sans remplacement. Les futures voies live
   devront partager ce groupe. Les probes historiques actives sont refusées ;
   MANAGER ne doit pas en démarrer pendant cette campagne.
6. **PENDING APPROVAL** est réservé aux environnements qui exigent
   effectivement une approbation GitHub. Sans `required_reviewers`, le job
   `admission` produit **READY FOR ENVIRONMENT** après réservation ; le job
   `collect` conserve son environnement dédié et son recheck indépendant
   HEAD/décision/CI/politique/réservation avant tout secret. Si GitHub exige une
   approbation, le runner vérifie en plus l'historique d'approbation d'un User
   indépendant. Rejet, absence de preuve requise ou déplacement du HEAD :
   **NOT RUN**, aucune collecte. Ce modèle renonce à l'approbation humaine
   indépendante lorsqu'elle n'est pas configurée, sans changer les autres gates.
7. Seul le step `capture` reçoit `HOBEN_USER_GUID` et le DeviceGuid optionnel.
   Un lanceur fixe transmet au processus Python une liste fermée de variables,
   sans token GitHub/Actions/OIDC, fichiers de commandes Actions, dépendances
   candidates ou sortie libre. Le client de laboratoire valide contexte/checkouts
   puis appelle `campaign_with_signals(mode="both", seconds=90)` sans CMS.
   Aucune sonde alternative, destination ni budget libre n'est accepté.
8. Même après un échec de collecte, l'export Node examine uniquement
   `report.json` : fichier régulier sans symlink, borné à 2 Mio, schéma
   strict à clés/valeurs allowlistées et chronologies validées indépendamment
   du producteur Python. Un rapport invalide n'émet aucune sortie d'upload
   et ne crée aucun fichier public. Seul le JSON validé est copié vers
   le répertoire public fixe, avec rétention de sept jours. Aucun RX,
   archive privée ou fichier `captures.cms` n'est exporté.
9. Rechercher le run **Hoben experimental (MANAGER)** par SHA fusionné,
   événement push, branche, acteur et tentative 1. Conserver ID/URL, conclusions
   des jobs, statut `hoben-experimental-h1h2` du même SHA et rapport correspondant.
   L'unique artefact est `experimental-report-<SHA>-<run_id>/report.json`.
   Le publisher séparé ne reçoit aucun secret
   et ne considère comme réussi qu'un job de collecte réussi avec un rapport
   de douze sessions `inconclusive`. Un rapport failure, export refusé ou artefact
   absent ne devient jamais success. Une annulation forcée peut empêcher la
   publication : la conclusion originale GitHub reste la preuve de cancellation.

### Audit des permissions et preuve après fusion (corrections MANAGER PR #59)

**Contrat documenté GitHub (API REST 2026-03-10) :** les lectures
`repos.getEnvironment` (GET /repos/{owner}/{repo}/environments/{environment_name}),
`repos.listDeploymentBranchPolicies` et `repos.getDeploymentBranchPolicy`
demandent **Actions: read** sur le dépôt pour un jeton fin ; elles ne demandent
pas Administration:write. Les jobs `admission` et `collect` déclarent déjà
`actions: read`. Source :
[environments](https://docs.github.com/en/rest/deployments/environments),
[branch policies](https://docs.github.com/en/rest/deployments/branch-policies).
Ce contrat public **ne démontre ni leur accessibilité effective par le
GITHUB_TOKEN d'un runner, ni la configuration des environnements**. Aucun PAT
administrateur ni nouvelle permission n'est demandé.

Le code lit ces trois endpoints avant la création de la réservation dans le job
`admission`. Une réponse 401/403/404, une API absente, un corps incomplet, une
politique de branche non strictement `experimental` ou une règle
`required_reviewers` effectivement configurée mais non conforme donnent
un refus catégoriel **NOT RUN** sans message d'exception brut. **L'absence de
règle de reviewers** est désormais admise par la décision propriétaire
(mono-mainteneur) : le gate ne simule pas une approbation inexistante.
Au job `collect`, après l'éventuelle attente d'approbation GitHub, une seconde
lecture de la politique et de la réservation doit réussir **avant le step
qui reçoit les identifiants**. Si une approbation est effectivement requise,
son historique est aussi vérifié. Un refus ne réserve aucun nouveau
SHA/scénario et n'appelle pas la collecte.

### Catégories publiques d'admission (correction après le run #37923236744)

Le step `admission` écrit maintenant **uniquement** `NOT RUN` et la catégorie
fixe retournée par `refusalCategory()` dans le summary et l'échec GitHub.
L'allowlist est `provenance`, `preflight`, `merge`, `decision`, `ci`,
`environment_api`, `environment_response`, `environment_branch`,
`environment_reviewers`, `claim`, `approval`, `other`. Toute exception
inconnue produit `other` ; **jamais** de texte libre, stack, URL, header,
payload ou nom de reviewer.

Pour l'environnement, distinguer strictement :

| Catégorie | Interprétation autorisée |
| --- | --- |
| `environment_api` | API GitHub inaccessible/refusée (y compris 401/403/404, problème de transport) : sous-cause exacte indéterminée |
| `environment_response` | Réponse API absente ou structure/champ obligatoire incomplet |
| `environment_branch` | Identité ou politique de branche incohérente : doit être strictement `experimental`, sans wildcard ou tag |
| `environment_reviewers` | Règle de reviewers réellement configurée mais incorrecte (absence de règle acceptée pour ce dépôt mono-mainteneur) |

Les autres catégories localisent la famille du refus sans révéler les entrées
API : `merge` (PR/SHA/arbre), `decision` (Issue, commentaire MANAGER, review),
`ci` (preuves CI), `claim` (concurrence/réservation), `provenance` et
`preflight` (déclencheur et test préliminaire). `other` est un refus fermé,
pas un motif d'autoriser un nouveau run. Les codes de motif restent stables et
sont testés avec des erreurs synthétiques contenant de fausses données privées.

**La catégorie est un diagnostic, pas une autorisation.** Le MANAGER étudie
le nouveau run `push` d'un **nouveau SHA fusionné** pour voir la catégorie
effective ; l'ancien SHA/run ne peut être relancé. Il décide ensuite si la cause
nécessite une correction logicielle ou une intervention du propriétaire sur la
configuration GitHub. Aucun accès Hoben n'est effectué par DEV.

**Preuves différentes, ne pas les confondre :**

- **Hors ligne / PR Validate :** mocks HTTP 401/403/404, politique/branche,
  absence de décision MANAGER, SHA erroné, approbation manquante et non-réservation.
  Ces tests prouvent le refus du code, pas un droit API réel.
- **Installé sur `experimental` seulement après revue et fusion :** retrouver
  le run `Hoben experimental (MANAGER)` de type `push`, tentative 1, SHA
  fusionné, vérifier la réussite du job `dry-run` *du même run* (sans secret),
  puis consulter le résultat du job `admission`. Un run Validate sur la PR ne
  peut **jamais** le remplacer.
- **Runner réel :** `admission` est la preuve de lecture effective des politiques.
  Si 403, refus ou données invérifiables : **NOT RUN**, pas de réservation et
  aucune tentative de réexécuter avec un jeton plus puissant. Si admis, le job
  `collect` recontrôle réellement la politique GitHub et, **si obligatoire**,
  l'approbation indépendante. `PENDING APPROVAL` n'est pas un succès de collecte.
  `READY FOR ENVIRONMENT` non plus : seule une collecte avec rapport expurgé
  peut établir une observation. Vérifier le bon environnement dans le run.

Le commentaire `hoben-experimental-approval:v1` est une **décision réelle du
MANAGER, déposée sans édition avant fusion**, jamais un texte produit par DEV
ou par un test. S'il manque, est altéré ou lie un ancien HEAD, le refus intervient
avant lecture de l'environnement. Le MANAGER doit vérifier les settings effectifs
sur l'interface GitHub lorsqu'ils restent invérifiables via sa connexion ; une
capture d'écran ou un commentaire de confirmation seul ne remplace pas
l'attestation du runner. **Constat du 9 octobre : le `dry-run` de #59 est démontré par GitHub, mais
l'admission échoue sans connaître la sous-cause ; H1/H2 restent NOT RUN.
La catégorisation ajoutée ici attend un nouveau SHA fusionné et un run distinct.**

Le succès du workflow signifie seulement collecte bornée terminée ; tous les
rapports conservent `boundary_proven=false`. Les arrêts anticipés produisent un
rapport failure uniquement si sa projection et sa validation réussissent.
Une projection refusée ou absente n'a aucun repli vers les fichiers privés.
L'installation du chemin de #67 et les observations réelles restent à constater
par MANAGER après revue et fusion. Aucun run Hoben par DEV n'est revendiqué.

### Diagnostic expurgé du lancement H1/H2 — suite de #54

Le lanceur conserve `python -I`, l'environnement à variables allowlistées et
`stdout/stderr` de l'enfant vers `/dev/null`. Il ne lit aucun message d'exception,
fichier de diagnostic, sortie RX ou texte libre de l'enfant. En cas d'échec,
il traduit uniquement un code de sortie fermé en une ligne fixe :
`H1/H2 failed; phase=<phase>; phase_source=child_exit.`

| Code enfant | Phase | Portée du diagnostic |
| --- | --- | --- |
| 10 | `context` | Arguments, provenance/checkouts, variables interdites, stockage ou chargement du module de laboratoire |
| 11 | `identity` | Identité absente ou invalide, avant appel de campagne ; DeviceGuid absent/vide utilise les 32 zéros déjà implémentés |
| 12 | `dns_tls` | Construction/connexion du transport TLS vérifié ; sous-cause DNS/TLS non publiée |
| 13 | `open` | Émission OpenClient et réception du préfixe accepté, rejet ou timeout d'ouverture |
| 14 | `collect` | Réception/lectures post-ouverture, interruption ou campagne incomplète |
| 15 | `projection` | Analyse/chronologie, projection allowlistée ou écriture du seul rapport |
| 16 | `cleanup` | Fermeture/nettoyage ; cet échec ne peut produire une réussite de collecte |

La première phase d'échec observée reste mémorisée pendant la projection du
rapport partiel et le nettoyage. Un problème récupéré ne transforme pas à lui
seul une campagne complète en échec ; un nettoyage défaillant refuse le succès.
Ces catégories décrivent l'exécution du code, jamais une frontière de message
confirmée, un résultat de protocole ou une autorisation de collecte.

Un code inconnu, signal, timeout du sous-processus ou impossibilité de lancement
produit `phase=context; phase_source=unavailable`. Cette ligne signifie
**phase enfant inconnue**, sans preuve sur l'existence ou le nombre de connexions.
Un échec du nettoyage supplémentaire par le parent produit seulement
`phase=cleanup; phase_source=parent`. Le lanceur sort avec 1 dans tous ces cas,
même si l'enfant avait renvoyé 0. Aucune trace, identité, valeur domestique ou
capture n'est ajoutée au rapport ou aux logs ; les validateurs Python/Node,
l'unique upload de `report.json` et tous les gates restent applicables.

**Régression reproduite hors ligne :** l'ancien import de
`scripts.boundary_public_timeline` au démarrage échouait avec `python -I` avant
les contrôles de contexte. Il est déplacé dans la projection, après validation
du checkout et installation explicite de son chemin par `collect()`. Le vrai
CLI isolé est testé avec deux checkouts Git locaux et un contexte push synthétique,
sans secret ni réseau ; le vrai lanceur doit aussi transmettre les refus de
contexte et d'identité sans reprendre les sorties privées.
Cette reproduction ne prouve pas la cause interne des anciens runs silencieux
#37993325566 ou #38029711686. Leur phase exacte reste inconnue. MANAGER vérifie
le correctif après revue, CI et fusion d'un nouveau SHA vers `experimental` ;
aucune relance d'un run/SHA consommé ni expérience Hoben n'est effectuée par DEV.

### Exécution H1/H2 sur serveur simulé — demande expresse du propriétaire

À la demande expresse de l'utilisateur, les régressions hors ligne exécutent
désormais **la campagne complète de six H1 puis six H2** sur un serveur simulé
en mémoire, avec `HOBEN_USER_GUID` fabriqué de **32 zéros** et DeviceGuid initial
nul. Le simulateur attribue ensuite une identité synthétique non nulle et vérifie
sa réutilisation. Il accepte uniquement OpenClient, Pong et les deux lectures
V4 fixes par session H2 ; H1 reste passif après l'ouverture. Les fixtures
préexistantes fournissent préfixes, Ping, notifications et réponses fragmentées
ou coalescées. Elles ne constituent pas une preuve de frontière protocolaire.

Exécution reproductible sans secret ni connexion Hoben :

```sh
python -m pytest -q tests/test_experimental_phase_diagnostics.py
```

Le bootstrap **réservé aux tests** `tests/experimental_simulated_server.py`
charge le véritable point d'entrée sous `python -I`, avant d'ajouter le dépôt
au chemin d'import. Après les contrôles locaux de contexte/checkouts, seuls les
points d'injection existants du transport et de l'horloge sont remplacés : le
wrapper de signaux, la campagne, le collecteur, les parseurs, les chronologies
et la projection restent réellement exécutés. Un garde réseau dans l'enfant
interdit résolution DNS et connexion socket ; les 90 secondes et pauses sont
virtuelles. Le lanceur conserve son isolation et sa transmission catégorielle,
vérifiées avec cet enfant simulé, sans nouveau mode dans les scripts de production.

Ces tests cherchent les erreurs Python d'import et d'exécution sur tout le
parcours. Ils injectent aussi des erreurs de syntaxe/import, expression,
ouverture, réception, analyse et fermeture pour vérifier les codes fixes,
l'absence de traceback/texte privé, l'arrêt anticipé et le nettoyage. Le rapport
produit passe ensuite la validation et l'export Node indépendants ; aucun RX
ni identifiant ne sort de son répertoire temporaire. Les rapports restent locaux
à pytest, explicitement synthétiques, et ne sont pas publiés comme résultats live.

La PR #72 étant déjà fusionnée vers `experimental`, ce complément est livré
dans une petite PR de suivi de #54. Il ne remplace pas les campagnes réelles
réservées au MANAGER et ne modifie ni leurs gates/environnements/secrets,
ni le runtime HA, ni les faits de `protocol.md`. Le succès de la simulation
prouve l'exécution du chemin Python testé, pas la réussite sur le serveur Hoben.

### Historique CMS — hors procédure des nouveaux essais

Les anciens exports utilisaient AES-256-GCM et RSA-OAEP/SHA256 avec destinataire
public épinglé, préflight avant TLS et scellement final dans un second CMS.
Ils nécessitaient deux déchiffrements privés authentifiés avant extraction.
La clé historique est indisponible : aucune récupération de clé, tentative de
déchiffrement ou conversion de ces captures n'est prévue par #67. Aucun résultat
brut, clé, identité ou valeur domestique ne peut être joint aux Issues,
artefacts publics ou logs. Ce mécanisme historique n'est pas appelé par les
nouveaux essais, qui n'exportent aucune capture.


### Décision mono-mainteneur et preuve du prochain SHA (9 octobre 2026)

Le propriétaire ne dispose pas d'un autre compte GitHub pouvant être ajouté comme
`required reviewer`. Par décision explicite consignée dans l'Issue #54, le
laboratoire adopte le **même modèle d'environnement sans reviewer obligatoire
que les anciens workflows `hoben-live`**, mais garde son environnement **distinct
`hoben-experimental`** et sa politique de branches limitée à `experimental`.
Une approbation GitHub déjà activée dans les Settings n'est jamais contournée :
si GitHub la déclare, le job doit rester en attente puis vérifier sa preuve.
Cette décision supprime une garantie d'approbation humaine indépendante,
compensée partiellement par la revue MANAGER du diff et des quatre jobs CI,
l'identité du merge, la décision immuable portant sur le SHA exact, la
réservation atomique et les restrictions d'accès aux secrets.

L'ancien run #37936003393 a refusé l'admission avec `environment_reviewers`
et n'a contacté aucun serveur Hoben. La correction n'est **pas** une autorisation
de le relancer : un nouveau SHA revu et fusionné est obligatoire. Les détails
réels de configuration GitHub restent à confirmer via le prochain runner, et
les tests de PR ne constituent **pas** une preuve de connexion MyHOBEN.

## Handoff pré-fusion #54 — contrôle consultatif sans secret (PR suivant #61)

Le run post-fusion de #61 (37963217918, SHA
`70a8a3bb480f3cdee27b169935c0dcb4f2be9e69`) a terminé le
`dry-run`, puis refusé `admission` avec `category=decision` :
`collect/result=skipped`, campagne H1/H2 **NOT RUN**. Trois éléments
étaient absents : rattachement littéral `Refs #54` dans la PR,
Issue #54 non bloquée, décision MANAGER authentifiée **avant** fusion.
Ce run et ce SHA sont consommés : ni relance ni approbation rétroactive.

**Ordre opératoire obligatoire pour la prochaine PR vers `experimental` :**

1. **CODEX DEV** ouvre une nouvelle PR dans le même dépôt, base exactement
   `experimental`, avec la ligne littérale `Refs #54` dans le corps dès
   la création. Ni `Closes #54` ni réouverture de #61/#56. Mettre au point
   le HEAD final et attendre les quatre jobs `tests`, `ha-tests`,
   `hacs`, `hassfest` **réussis sur ce HEAD**, dans un unique run
   `Validate` de PR, tentative 1. Transmettre PR/HEAD/run/risques.
2. **CODEX DEV** place seulement l'Issue #54 en `state:review`, ouverte,
   avec exactement un label `state:*`. Aucun commentaire d'approbation
   privilégié n'est rédigé ou déposé par DEV.
3. **MANAGER uniquement** relit le diff, HEAD, reviewers/threads, les quatre
   jobs, la preuve de provenance du run CI et l'Issue toujours
   `state:review`. Pour le chemin de #67, vérifier le rapport public,
   les deux validations et l'absence d'upload privé ; aucun pin CMS n'entre
   dans la décision. Ne pas déduire la
   configuration réelle de l'environnement de cette revue.
4. **MANAGER uniquement**, *après CI et avant fusion*, dépose sur la PR
   l'unique commentaire non édité `hoben-experimental-approval:v1`
   selon le schéma strict à quatre champs de #67 indiqué ci-dessus,
   avec `candidate_sha` du HEAD revu et `ci_run_id` réel.
   Les anciennes décisions à cinq champs avec `recipient_sha256` sont refusées.
   Aucun exemple synthétique ni ancienne décision ne peut
   servir de preuve ; le contrôle consultatif n'émet jamais cette décision.
5. **MANAGER uniquement** fusionne vers `experimental` après cette
   décision. Le nouveau run `push` doit être sur le **SHA de merge**
   exact, tentative 1. Vérifier successivement `dry-run` secretless,
   `admission`, puis `collect/result` uniquement si l'admission a
   effectivement réussi. Relever ID, URL, job conclusions, catégorie
   publique, statut et rapport anonymisé. Toute information absente,
   refusée ou incohérente signifie **NOT RUN** ; aucune connexion Hoben
   n'est revendiquée sur la seule base du dry-run.

### Diagnostic facultatif, jamais un gate d'admission

`.github/scripts/experimental-handoff-check.cjs` accepte **un fichier JSON
local borné (128 Kio maximum)** contenant des *copies des métadonnées
GitHub* `pr`, `issue`, `ci`, `jobs`, `comments` ; aucune identité
Hoben, secret, capture RX, token ou valeur domestique. Exemple d'invocation :

```sh
node .github/scripts/experimental-handoff-check.cjs /chemin/prive/handoff.json
```

Le MANAGER récupère ces cinq jeux de métadonnées **en lecture seule** depuis
GitHub (PR et ses commentaires, Issue #54 et ses labels, run `Validate`
et ses jobs). Le diagnostic compare dépôt/base/HEAD, rattachement de l'Issue,
`state:review`, association CI exacte à la PR et au HEAD, les quatre jobs et
le commentaire authentifié/immuable. Sa sortie n'affiche **que** les codes
`unlinked_pr`, `blocked_issue`, `issue_not_in_review`,
`ci_incomplete`, `missing_manager_decision` ou
`stale_or_invalid_manager_decision` (ou `ok` par dimension), sans
reproduire les entrées. Il rend `NOT READY` avec code sortie 1 si une
preuve manque. **Il est normal qu'une PR avant décision MANAGER reste
`NOT READY` : ne pas faire échouer Validate pour cette raison.**

Même `READY FOR MANAGER REVIEW` est **consultatif uniquement** : un fichier
JSON local peut être incomplet ou synthétique, donc le statut ne confère ni
permission, ni approbation, ni droit de fusion ou de collecte. Seul le
gate réel `managerDecision()` / `reviewsAndCI()` /
`environmentPolicy()`, après push MANAGER, lit la preuve GitHub et réserve
le SHA/scénario. L'absence de `required_reviewers` n'est acceptable que
lorsqu'elle est effectivement attestée par l'API runner pour
`hoben-experimental`, branche strictement `experimental` ; toute règle
réellement configurée reste obligatoire. Le diagnostic ne consulte ni
environnements ni secrets.

## Phase H1/H2 — nouveaux essais sans clé CMS (Issue #54)

**Contrat de #67 pour les nouveaux HEAD après revue et fusion :** les captures
brutes peuvent être utilisées temporairement dans un dossier privé 0700 du runner
(ouvertures de fichiers 0600) pour dériver des mesures, mais **ne sont jamais
publiées**, ni en clair ni en CMS. Le répertoire temporaire est supprimé dans
un bloc `finally`, aussi en cas de rapport refusé. L'artefact GitHub autorisé
se limite à `experimental-report-<SHA>-<run_id>` contenant
`report.json` : valeurs numériques bornées, catégories fixes, candidat H2
explicitement hypothétique et `boundary_proven=false`.
Deux validateurs indépendants Python/JavaScript doivent accepter le rapport ;
l'absence d'une preuve de sécurité entraîne **NOT RUN**, sans repli brut.

Ce chemin **sans export de capture** ne dépend d'aucun certificat CMS,
empreinte `recipient_sha256` ou clé privée ; TLS reste vérifié normalement.
L'approbation MANAGER sur une nouvelle PR doit être authentique, immuable,
postérieure aux quatre CI et antérieure à la fusion, au schéma exact :

```text
<!-- hoben-experimental-approval:v1 -->
{"schema":1,"scenario":"h1h2","candidate_sha":"<HEAD_PR_40_HEX>","ci_run_id":0}
```

Le déclencheur reste un **nouveau push de fusion MANAGER sur
`experimental`**, pas `workflow_dispatch` inventé, ni un rerun
d'Actions. Le SHA validé est réservé une seule fois pour ce scénario par
tag atomique ; l'usage plusieurs fois d'un même SHA **n'est pas encore
autorisé** sans une future implémentation de campagnes distinctes et
d'autorisation indépendante. Les policies réelles d'environnement et
approbations GitHub restent obligatoires.

**Historique à ne pas réexécuter :** les paragraphes datés des phases
précédentes décrivant le pin CMS, la possession hors GitHub d'une clé privée, le
`captures.cms` et le commentaire à cinq champs concernent **exclusivement
les anciennes exécutions**. Ils ne sont plus des instructions applicables aux
nouveaux runs ni une autorisation de publier du RX brut. Les anciens artefacts
chiffrés ne sont pas déchiffrables sans la clé correspondante et ne sont
ni relancés ni convertis.

## Phase H1/H2 — chronologies expurgées, première livraison (Issue #54)

Le module privé `scripts/boundary_timeline.py` dérive du journal de chaque
session une suite strictement quantitative et bornée. Il ne déduit **pas**
l'existence d'une frontière protocolaire à partir d'un appel TLS `read()`.
La projection Python `scripts/boundary_public_timeline.py` et le validateur
**indépendant** `.github/scripts/experimental-timeline.cjs` rejettent les
clés supplémentaires (en particulier identifiants, payloads et chaînes
libres), les nombres non finis, les comptes/offsets incohérents, les
chronologies truquées et les dépassements de bornes.

Chaque rapport de session effectivement enregistré peut ainsi contenir
`timing_observations` avec des valeurs en **millisecondes relatives à
l'émission OpenClient** : pour chaque `read()`, index, temps de début/fin,
durée, taille demandée/reçue, offset cumulatif, pause entre lectures,
délai depuis dernier TX achevé et catégorie `received/eof/cancelled_read/read_error`.
Les TX sont des catégories allowlistées `open_client`, `pong_before_open`,
`read_v4_h2`, `pong_h2` avec temps et durée mesurés si l'émission
a effectivement abouti. La fermeture est suivie par catégories/temps
de début et de fin, sans exporter les exceptions. Les candidats
`ping_h2/response_h2/notification_h2` sont rapportés par offset,
longueur, instant et nombre de lectures entre lesquelles ils sont
répartis : leur confiance reste **`h2_hypothesis_only`**.
Les octets non attribués sont des **offsets/longueurs seulement**,
y compris le suffixe H1 apparent après les 48 premiers octets ;
jamais leurs valeurs. Les compteurs de fragmentation et de
concaténation sont dérivés des recouvrements, pas d'une supposition
sur les frontières. Les données initiales H1/H2 51/150/209 octets sont
des observations à **comparer**, non un modèle universel.

Une limite locale interdit plus de 260 lectures, 100 émissions,
256 annotations, 1 Mio RX ou 180 secondes de chronologie par session.
Tout dépassement empêche la publication du rapport : **échec fermé**.
Le rapport complet est plafonné à 2 Mio et n'accepte aucun champ RX brut.
Les fixtures anciennes sans cette extension restent lisibles pour tests
de rétrocompatibilité ; les nouvelles sessions du collecteur produisent
cette extension, y compris en cas d'EOF ou de terminaison partielle.

**Historique de la première livraison (#66) :** elle ajoutait les observations
anonymisées et le double filtrage tout en conservant le seul export chiffré
des captures. #67 prépare désormais un export limité au rapport validé,
sans capture et sans dépendance CMS, après sa propre revue et CI. Les clés
anciennes indisponibles ne sont pas demandées ni reconstruites. Les campagnes
répétables sur le même SHA restent une modification distincte. Un fichier
brut ne devient jamais un artefact par suppression du chiffrement.

## Phase 3 — `hoben-live` expérimental, client Home Assistant réel

La phase H1/H2 a terminé sur le commit fusionné
`5a904855ba1c3d74353301cf0c7605a168e04453` :
[run #37974967946](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/37974967946),
jobs `dry-run/admission/collect/result` réussis, **hypothèses de frontière
inconclusives**. Aucun changement de `protocol.md` n'en découle. La voie
`hoben-live` est indépendante et ne réutilise pas les sondes H1/H2.

### Contrat exécuté au SHA fusionné

Le workflow `.github/workflows/hoben-live-experimental.yml` n'est
déclenché que par le `push` du merge MANAGER sur la branche exacte
`experimental`. Son premier job est un dry-run secretless. L'admission
utilise `.github/scripts/experimental-live-gate.cjs` et demande une
preuve séparée, non interchangeable avec l'approbation H1/H2 :

- PR du même dépôt, base `experimental`, corps contenant `Refs #54`,
  HEAD et arbre du merge identiques ;
- Issue #54 ouverte avec un seul label admissible (`state:review` avant
  fusion), revue MANAGER et threads résolus ;
- un run `Validate` `pull_request` tentative 1 sur le HEAD exact,
  quatre jobs `tests/ha-tests/hacs/hassfest` réussis ;
- **commentaire réel MANAGER immuable**, pré-fusion, débutant exactement
  par le marqueur `<!-- hoben-live-approval:v1 -->`, suivi d'un objet
  JSON contenant **strictement** `schema=1`, `scenario="ha-parity"`,
  `candidate_sha` (HEAD de PR) et `ci_run_id` (ID du run Validate
  validé). CODEX DEV ne crée ni ne poste cette décision ;
- politique effective de l'environnement GitHub **`hoben-live`** :
  **deux modes fermés seulement** sont admis. (a) Politique personnalisée
  `protected_branches=false` et `custom_branch_policies=true`, avec
  exactement **la branche `experimental`**, de type `branch`, sans
  wildcard ni tag ; ou (b) politique GitHub « branches protégées » avec
  `protected_branches=true` et `custom_branch_policies=false`, à la
  condition supplémentaire de relire réellement `experimental` par
  l'API et de vérifier **`protected=true` et SHA HEAD du merge testé
  strictement égal au SHA du run**. La vérification est refaite pendant
  l'admission **et** pendant le recheck avant secrets. La preuve de branche,
  le mode et la politique de reviewers entrent dans l'empreinte du claim ;
  changer de mode entre les deux contrôles fait refuser le recheck.
  Politique mixte, non protégée, branche déplacée, réponse partielle,
  accès API refusé ou politique inconnue = **NOT RUN**, sans collecte ;
- l'absence de `required_reviewers` reste tolérée pour le modèle
  mono-mainteneur uniquement si elle est effectivement attestée par
  GitHub. Toute règle réelle de reviewers doit être appliquée et son
  approbation indépendante prouvée, sans contournement ni auto-approbation.

**Constat du 9 octobre 2026 :** le run live #37985718299 de la PR
#64 a validé son préflight, puis refusé l'admission avec la catégorie
`environment_branch` ; `collect/result` étaient ignorés. Cette
correction ajoute la prise en charge explicite des branches protégées,
mais ne prouve **pas** que la configuration GitHub est conforme : seul
un nouveau run du runner sur un nouveau SHA revu peut l'établir.
L'ancien SHA/run ne doit jamais être réexécuté.

Avant tout secret, une réservation atomique
`hoben-live-ha-parity-<SHA_MERGE>` lie run, décision, HEAD, scénario
et empreinte de la politique d'environnement. Aucune reprise d'un run
annulé/échoué n'est autorisée pour ce SHA/scénario ; un nouveau HEAD
revu et une décision MANAGER distincte sont nécessaires. Les deux
workflows utilisent le même mutex `hoben-read-only-observation`.
L'environnement `hoben-live` reste distinct de `hoben-experimental`.

Le job de collecte attend l'environnement et recontrôle l'ensemble
des preuves et l'éventuelle approbation GitHub **avant** l'unique step
recevant les identifiants. Ce step lance un sous-processus à variables
allowlistées, sans token GitHub/Actions/OIDC ni fichiers de commandes
Actions, sans stdout/stderr du client. Il utilise au SHA exact
**`custom_components.hoben.client.HobenClient`** deux fois de suite
via `async_refresh()`, le même décodeur
`decode_v4_snapshot()` que le `HobenDataUpdateCoordinator`, puis
`async_close()`. Le même objet client conserve en mémoire le DeviceGuid
attribué. `max_attempts=1` empêche le retry implicite ; timeout
d'ensemble 150 s, deux connexions TLS vérifiées, deux lectures
Modbus 04 V4 de 20 registres. Aucun pairing, fonction 06/16/22,
écriture, commande poêle ou destination variable.

**Portée réelle :** le runtime actuel réalise des rafraîchissements
`one-shot` ; la campagne vérifie deux rafraîchissements successifs,
décodage, conservation de l'identité et fermeture, **pas**
l'ordonnanceur/timer complet HA. Les fonctions session persistante,
Ping/Pong, `DataUpdated` et reprise automatique après panne ne sont
**ni implémentées ni déclarées validées**. Le rapport conserve
`session_mode=one-shot`, ces limites marquées
`unsupported`/`not_tested`, et uniquement états, booléens et
compteurs bornés. Aucun registre, température, GUID, trace ou exception
libre ne peut apparaître dans l'artefact. Le validateur Node bloque
tout champ additionnel ou résultat de succès partiel ; export du seul
`live-ha-parity-report-<SHA>-<run_id>` (7 jours).
Le job `result`, sans secret, ne publie le statut
`hoben-live-ha-parity=success` que si le job collecte et son
rapport validé réussissent ensemble. Le succès **ne prouve pas**
les fonctions absentes.

### Handoff MANAGER

1. CODEX DEV livre la PR `Refs #54` vers `experimental`, HEAD
   final et quatre jobs CI passants, puis `state:review`.
2. MANAGER inspecte diff, code exécuté, environnement isolé, HEAD,
   CI, provenance et limitations ; publie **avant merge** son
   commentaire authentique `hoben-live-approval:v1` sur la PR avec
   le SHA exact et le run CI réel.
3. MANAGER fusionne vers `experimental` uniquement. Constater le
   nouveau run `push`, tentative 1, son SHA et l'ID/URL, puis
   `dry-run`, `admission`, `collect`, `result`, statut associé et
   rapport expurgé. Une admission refusée, un export absent ou une
   expérience incomplète signifie **NOT RUN/FAILURE**, jamais un
   succès simulé ni une relance.
4. MANAGER consigne séparément les constats et ouvre si nécessaire
   des Issues de session/reconnexion ; `protocol.md` reste fondé
   exclusivement sur les faits établis, jamais sur le dry-run.

L'API du connecteur ne prouve pas les détails de Settings ni les
secrets `hoben-live`. La lecture réelle de la politique n'est
établie que par le runner après fusion ; aucun paramètre ni secret
n'est modifié par DEV.

## Gouvernance des secrets et protections

Le propriétaire déclare avoir effectué les réglages GitHub. L'API disponible a confirmé `experimental.protected=true`, **sans permettre de consulter les règles détaillées de protection, les environnements, leurs approbations ni leurs secrets**. Cette limite n'est pas une preuve de leur absence ou de leur conformité.

Avant un test réel, vérifier **effectivement** sur GitHub et dans le gate du workflow :

- la branche `experimental` protégée, le code et le HEAD revus et les checks ciblés réussis ;
- les environnements distincts `hoben-live` et `hoben-experimental`, leurs politiques d'accès à `experimental`, leur approbation GitHub lorsqu'elle est configurée, et la provenance du job qui demande le secret ;
- l'injection des seuls `HOBEN_USER_GUID` et `HOBEN_DEVICE_GUID` nécessaires, dans l'étape minimale, sans faire hériter au code candidat d'un token GitHub doté de droits d'écriture ;
- le caractère lecture seule, le TLS vérifié, les budgets bornés et l'interdiction d'une destination/script/mode libre ;
- pour le chemin `hoben-experimental` de #67, le rapport aux clés/valeurs
  allowlistées sans donnée domestique, sa double validation Python/Node,
  l'absence d'export des fichiers privés et la rétention maximale de sept jours.
  Les prérequis CMS appartiennent uniquement aux anciennes voies chiffrées.

Aucun secret n'est écrit dans les Issues/PR, fichiers de config, logs ou summaries.
Le chemin de #67 ne fait sortir aucune donnée RX brute du runner. Les captures
historiques restent chiffrées ; aucune nouvelle sortie de capture n'est autorisée
par cette PR. Une voie exportant des captures doit conserver le préflight CMS
et leur chiffrement avant export. Politique ou approbation invérifiable :
**`NOT RUN` / `PENDING APPROVAL`**, notification, aucune connexion Hoben.
Rapport refusé : échec fermé, aucun upload ni repli brut.

## Contrat des essais et exploitation

**`hoben-live` :** exercer par le vrai client du plugin, lorsque disponible, les opérations de connexion/TLS, ouverture et identification, session, lecture et refresh V4, Ping/Pong/DataUpdated seulement là où réellement implémentés et documentés, perte de connexion/reprise et unload. Conserver les observations expurgées. Les fonctionnalités non implémentées ou non confirmées donnent lieu à `unsupported` / `inconclusive` ou à une Issue ciblée, jamais à des assertions fictives.

**`hoben-experimental` :** conserver la campagne H1/H2 déjà documentée (#48/#49/#55), plafonds actuels **6 H1 + 6 H2**, **90 s et 1 Mio RX par session**, arrêt anticipé sans replay implicite. Les silences, préfixes et tailles observés ne prouvent pas à eux seuls la frontière OpenedClient. Le chemin de #67 utilise les fichiers RX temporairement dans le dossier privé, les détruit dans `finally` et publie uniquement les offsets, longueurs, temps et catégories validés du rapport ; jamais les octets inconnus ni une archive de capture.

Chaque run doit être corrélé à son **SHA, scénario, acteur autorisé, état réel, identifiant/URL GitHub, résultats et limites**, et exécuté au plus une fois sans nouvelle décision et nouveau SHA/scénario. Pas de test réel dans pytest, CI PR, DEV, cron ou automatisme de merge dépourvu d'une décision MANAGER contrôlée. Un dry-run secretless permet d'établir le chemin de déclenchement **sans** interpréter un succès synthétique comme preuve réseau.

Après le run, MANAGER évalue les informations vérifiées, propose sur `experimental` une PR `protocol.md` uniquement pour les faits dûment étayés (`CONFIRMÉ` / `OBSERVÉ` / `À VALIDER`), crée ou actualise les Issues utiles, et peut autoriser la prochaine Issue `state:ready` sans solliciter le propriétaire. Un run échoué n'arrête pas les autres tâches sans lien avec lui.

## Portée des anciennes voies `main`

Les anciens workflows et procédures de validation sur `main` restent historiques et inchangés tant que le propriétaire n'a pas demandé une livraison. **Ils ne doivent plus être considérés comme un prérequis** à la recherche H1/H2 ou à la validation expérimentale autonome. N'élargir ni secrets ni droits de `main` dans le cadre de #54. La préparation d'une PR de promotion sur `main` est réservée à une demande ultérieure et explicite du propriétaire.
