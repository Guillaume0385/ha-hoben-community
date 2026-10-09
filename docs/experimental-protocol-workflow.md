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

La phase 2 de #54 prépare **uniquement** `hoben-experimental.yml`, à installer
après revue et fusion de sa PR vers `experimental`. Elle réutilise les
collecteurs #55 ; aucun composant HA n'importe ces instruments.
`hoben-live` reste une phase suivante, sans job réel dans cette livraison.

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
   de `hoben-experimental` : exactement Branch `experimental`, required reviewer
   User indépendant et `prevent_self_review=true`. API inaccessible, type de
   politique absent de la liste **et** du détail, Team non vérifiable, branche
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
6. **PENDING APPROVAL** décrit l'attente réelle du job `collect` attaché à
   `hoben-experimental`. GitHub garde son approbation obligatoire. Après celle-ci,
   le runner revalide HEAD, décision, CI, politique inchangée, réservation du
   même run et historique d'approbation du reviewer User indépendant attendu.
   Bypass administrateur, rejet, absence de preuve ou déplacement du HEAD :
   **NOT RUN**, aucune collecte. Ce contrôle n'ajoute aucune permission GitHub.
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
politique de branche non strictement `experimental`, une absence de reviewers
User indépendants ou `prevent_self_review != true` donnent un refus
`environment_unverified`, rendu **NOT RUN** sans message d'exception brut.
Au job `collect`, après l'éventuelle attente d'approbation GitHub, une seconde
lecture identique et l'historique d'approbation doivent réussir **avant le step
qui reçoit les identifiants**. Un refus ne réserve aucun nouveau SHA/scénario
et n'appelle pas la collecte.

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
  `collect` attend la politique GitHub et recontrôle réellement l'approbation.
  `PENDING APPROVAL` n'est pas un succès de collecte. Vérifier le bon environnement
  dans la page GitHub du run avant toute approbation.

Le commentaire `hoben-experimental-approval:v1` est une **décision réelle du
MANAGER, déposée sans édition avant fusion**, jamais un texte produit par DEV
ou par un test. S'il manque, est altéré ou lie un ancien HEAD, le refus intervient
avant lecture de l'environnement. Le MANAGER doit vérifier les settings effectifs
sur l'interface GitHub lorsqu'ils restent invérifiables via sa connexion ; une
capture d'écran ou un commentaire de confirmation seul ne remplace pas
l'attestation du runner. **À ce stade : le workflow modifié existe seulement
dans la PR #59 ; préflight de ce workflow sur GitHub et H1/H2 : NOT RUN.**

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
