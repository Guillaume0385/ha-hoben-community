# Circuit expérimental Hoben — validation Home Assistant et recherche réseau

> Décision du propriétaire, 9 octobre 2026 — **aucune PR vers `main` sans demande explicite de l'utilisateur**. Cette page définit le workflow souhaité et l'exécution autorisée sur `experimental`. Elle ne prouve ni la présence des secrets/environnements, ni la disponibilité actuelle de tous les workflows GitHub. Ne jamais confondre code de test préparé, workflow installé, dry-run et test Hoben réel.

## Deux voies distinctes sur `experimental`

| Voie | Environnement GitHub | Objectif | Intégration Home Assistant |
| --- | --- | --- | --- |
| **`hoben-live`** | `hoben-live` | Valider sur le serveur réel Hoben l'authentification, la connexion TLS, l'attribution/conservation DeviceGuid, la gestion de session, les lectures V4, disponibilité/reconnexion et cycle de vie **avec les mêmes composants et le même comportement que le plugin Home Assistant au commit testé** | Réutiliser autant que possible le client, les modèles et les chemins réellement utilisés par HA ; constater les écarts sans inventer de succès |
| **`hoben-experimental`** | `hoben-experimental` | Sonder et enregistrer le comportement réseau, confronter H1/H2, observer les trames et données inconnues, avec captures privées chiffrées et rapport anonymisé | **Jamais intégré au runtime HA** : les collecteurs, hypothèses de framing et instruments de capture restent dans les scripts/fixtures de laboratoire |

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

### Phase 1 constatée ; phase 2 préparée pour revue MANAGER

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
Le workflow utilise toujours les collecteurs #55 hors runtime HA ; la voie
`hoben-live` reste différée.

Procédure MANAGER, sans dispatch ni modification de Settings :

1. Examiner le diff complet, le HEAD exact, la confidentialité, le destinataire
   CMS et les quatre jobs CI `tests`, `ha-tests`, `hacs`, `hassfest` du même HEAD.
   Vérifier hors GitHub la possession de la clé privée correspondant au certificat
   public épinglé. Ne fournir aucune clé privée au runner.
2. Avant fusion, déposer **sur cette PR** un commentaire de décision au format
   strict ci-dessous. Remplacer `<HEAD_PR_40_HEX>` et `0` par le HEAD examiné et
   le véritable ID du run `Validate` réussi. Aucun texte additionnel, champ libre
   ou commentaire édité. Ce commentaire est une autorisation MANAGER du code,
   du scénario et de la preuve CI ; DEV ne le dépose jamais sur sa propre PR.

   ```text
   <!-- hoben-experimental-approval:v1 -->
   {"schema":1,"scenario":"h1h2","candidate_sha":"<HEAD_PR_40_HEX>","ci_run_id":0,"recipient_sha256":"f0209da5d964c02b9733610bfb4457f7bebd24fdfd32934e1165460bf0ab3246"}
   ```

3. Fusionner via la connexion MANAGER vers `experimental`. Aucun autre push ne
   suffit. Le workflow du SHA fusionné exécute d'abord son propre `dry-run`
   sans environnement, secret ou connexion Hoben, avec préflight CMS réel sur
   données synthétiques. L'admission vérifie aussi la réussite effective de ce
   job par l'API du run courant, pas seulement une sortie déclarée.
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
   et CMS avant TLS, puis appelle `campaign_with_signals(mode="both", seconds=90)`.
   Aucune sonde alternative, destination ni budget libre n'est accepté.
8. Même après un échec de collecte, le code d'export examine un fichier régulier
   borné, DER strict, destinataire épinglé, AuthEnvelopedData AES-256-GCM et
   RSA-OAEP/SHA256. Une clé publique ne peut authentifier le tag GCM candidat :
   le validateur rechiffre **tous** les octets admis dans un nouveau CMS avant
   l'upload. Ainsi aucun contenu clair caché dans un DER conforme ne sort en
   clair. Seul ce nouveau fichier fixe, et un rapport aux clés/valeurs allowlistées
   validé séparément, sont uploadés, avec rétention de sept jours.
9. Rechercher le run **Hoben experimental (MANAGER)** par SHA fusionné,
   événement push, branche, acteur et tentative 1. Conserver ID/URL, conclusions
   des jobs, statut `hoben-experimental-h1h2` du même SHA et rapport correspondant.
   Les artefacts sont `experimental-ciphertext-<SHA>-<run_id>` et
   `experimental-report-<SHA>-<run_id>`. Le publisher séparé ne reçoit aucun secret
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
rapport failure lorsqu'il peut être scellé. Une panne de chiffrement ne possède
aucun fallback en clair. Le workflow phase 2 et ses tests sont préparés hors
ligne ; leur installation, approbation et observation réelle seront constatées
par MANAGER après fusion. Aucun run Hoben par DEV n'est revendiqué.

Pour déchiffrer, hors GitHub dans un dossier privé 0700, authentifier d'abord
le CMS exporté vers un CMS intermédiaire 0600, puis authentifier ce dernier vers
le tar privé 0600, avec la même clé/certificat. **Deux déchiffrements réussis**
sont indispensables avant extraction ; supprimer toute sortie partielle après
un échec GCM. Ne joindre aucun résultat brut, clé, identité ou valeur domestique
aux Issues, artefacts publics ou logs.


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
   `state:review`. Vérifier séparément le certificat public CMS et
   l'empreinte `recipient_sha256` du fichier
   `.github/config/hoben-experimental.json`. Ne pas déduire la
   configuration réelle de l'environnement de cette revue.
4. **MANAGER uniquement**, *après CI et avant fusion*, dépose sur la PR
   l'unique commentaire non édité `hoben-experimental-approval:v1`
   selon le schéma strict indiqué dans la procédure de phase 2 ci-dessus,
   avec `candidate_sha` du HEAD revu, `ci_run_id` réel et l'empreinte
   exacte épinglée. Aucun exemple synthétique ni ancienne décision ne peut
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

## Gouvernance des secrets et protections

Le propriétaire déclare avoir effectué les réglages GitHub. L'API disponible a confirmé `experimental.protected=true`, **sans permettre de consulter les règles détaillées de protection, les environnements, leurs approbations ni leurs secrets**. Cette limite n'est pas une preuve de leur absence ou de leur conformité.

Avant un test réel, vérifier **effectivement** sur GitHub et dans le gate du workflow :
- la branche `experimental` protégée, le code et le HEAD revus et les checks ciblés réussis ;
- les environnements distincts `hoben-live` et `hoben-experimental`, leurs politiques d'accès à `experimental`, leur approbation GitHub lorsqu'elle est configurée, et la provenance du job qui demande le secret ;
- l'injection des seuls `HOBEN_USER_GUID` et `HOBEN_DEVICE_GUID` nécessaires, dans l'étape minimale, sans faire hériter au code candidat d'un token GitHub doté de droits d'écriture ;
- le caractère lecture seule, le TLS vérifié, les budgets bornés et l'interdiction d'une destination/script/mode libre ;
- pour `hoben-experimental`, la possession hors GitHub de la **clé privée** du certificat public contrôlé, préflight CMS avant TLS, RX uniquement chiffré avec AES-256-GCM et RSA-OAEP/SHA256, rapports allowlistés sans donnée domestique, et rétention maximale de sept jours.

Aucun secret n'est écrit dans les Issues/PR, fichiers de config, logs, summaries ou captures en clair. Les données brutes restent chiffrées avant toute sortie du runner. Si le gate ne peut vérifier la politique/approbation ou si le certificat est invalide : **`NOT RUN` / `PENDING APPROVAL`**, notification, aucune connexion Hoben.

## Contrat des essais et exploitation

**`hoben-live` :** exercer par le vrai client du plugin, lorsque disponible, les opérations de connexion/TLS, ouverture et identification, session, lecture et refresh V4, Ping/Pong/DataUpdated seulement là où réellement implémentés et documentés, perte de connexion/reprise et unload. Conserver les observations expurgées. Les fonctionnalités non implémentées ou non confirmées donnent lieu à `unsupported` / `inconclusive` ou à une Issue ciblée, jamais à des assertions fictives.

**`hoben-experimental` :** conserver la campagne H1/H2 déjà documentée (#48/#49/#55), plafonds actuels **6 H1 + 6 H2**, **90 s et 1 Mio RX par session**, arrêt anticipé sans replay implicite. Les silences, préfixes et tailles observés ne prouvent pas à eux seuls la frontière OpenedClient. Les captures conservent les octets inconnus uniquement sous chiffrement, avec analyse locale privée et résumé public expurgé.

Chaque run doit être corrélé à son **SHA, scénario, acteur autorisé, état réel, identifiant/URL GitHub, résultats et limites**, et exécuté au plus une fois sans nouvelle décision et nouveau SHA/scénario. Pas de test réel dans pytest, CI PR, DEV, cron ou automatisme de merge dépourvu d'une décision MANAGER contrôlée. Un dry-run secretless permet d'établir le chemin de déclenchement **sans** interpréter un succès synthétique comme preuve réseau.

Après le run, MANAGER évalue les informations vérifiées, propose sur `experimental` une PR `protocol.md` uniquement pour les faits dûment étayés (`CONFIRMÉ` / `OBSERVÉ` / `À VALIDER`), crée ou actualise les Issues utiles, et peut autoriser la prochaine Issue `state:ready` sans solliciter le propriétaire. Un run échoué n'arrête pas les autres tâches sans lien avec lui.

## Portée des anciennes voies `main`

Les anciens workflows et procédures de validation sur `main` restent historiques et inchangés tant que le propriétaire n'a pas demandé une livraison. **Ils ne doivent plus être considérés comme un prérequis** à la recherche H1/H2 ou à la validation expérimentale autonome. N'élargir ni secrets ni droits de `main` dans le cadre de #54. La préparation d'une PR de promotion sur `main` est réservée à une demande ultérieure et explicite du propriétaire.
