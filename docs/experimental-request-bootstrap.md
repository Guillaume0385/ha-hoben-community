# Canal MANAGER H1/H2 — bootstrap de confiance de l’Issue #54

Cette PR prépare le canal ; elle ne l’installe pas et ne lance aucun test Hoben.
Le workflow doit être fusionné sur **`main` après CODEX REVIEW indépendant**,
les checks normaux et la décision de validation applicable du MANAGER. Les
sondes font l’objet d’une PR distincte vers `experimental`, revue directement
par MANAGER. Les PR #49/#52 et les blocages #48/#51 restent distincts.

## Référence de déploiement et configuration du propriétaire

[`issues:labeled`](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#issues)
charge le workflow de la branche par défaut ; `GITHUB_REF` reste `main`, même
si un checkout récupère ensuite `experimental`. La variante retenue est donc
**un environnement séparé `hoben-experimental`, autorisant exactement Branch
`main`**, plutôt qu’un accès aux secrets accordé à une branche moins protégée.
Le code expérimental ne décide jamais de son admission. Le workflow installé,
la porte, le lanceur et le certificat public proviennent du SHA de `main`.

Seul le propriétaire configure et vérifie dans Settings :

- `main` protégée et ses checks/reviews habituels ; aucune modification des
  permissions de `hoben-live` ou du statut `live-hoben-authenticated` ; les
  workflows Hoben existants partagent seulement le verrou de concurrence ;
- `hoben-experimental` avec **Selected branches and tags**, une seule règle
  `name=main`, `type=branch`, aucune règle pour `experimental`, wildcard ou tag ;
- required reviewers **User nommés**, au moins un distinct de `Guillaume0385`,
  et **Prevent self-review activé**. Cette première version refuse les Teams
  dont elle ne sait pas établir l’appartenance ;
- secrets `HOBEN_USER_GUID` et éventuellement `HOBEN_DEVICE_GUID` exclusivement
  dans cet environnement, jamais dans le dépôt, les arguments ou une Issue ;
- les deux labels réservés `manager-hoben-experimental-dry-run` et
  `manager-hoben-experimental-live` ;
- la possession hors GitHub de la clé privée correspondant au certificat public
  `.github/config/hoben-experimental-recipient.pem`. L’empreinte SHA-256 DER est
  fixée dans `.github/config/hoben-experimental.json` :
  `f0209da5d964c02b9733610bfb4457f7bebd24fdfd32934e1165460bf0ab3246`.
  C’est le certificat public fourni pour #51/#52, RSA 3072 bits ; aucune clé
  privée n’est embarquée. Une rotation nécessite une nouvelle revue sur main.

Le gate lit les [règles effectives](https://docs.github.com/en/rest/deployments/environments#get-an-environment),
les [politiques de branches](https://docs.github.com/en/rest/deployments/branch-policies)
et, après l’attente du job, l’[historique réel des approbations du run](https://docs.github.com/en/rest/actions/workflow-runs#get-the-review-history-for-a-workflow-run).
Une absence de `type` dans LIST déclenche GET de la même règle (id/node_id/name) ;
si les deux réponses omettent le type, le live reste **NOT RUN**. Une approbation
par le demandeur, un bypass, un rejet, une politique modifiée pendant l’attente
ou une lecture inaccessible refusent le live. Aucune confirmation conversationnelle
ne remplace l’approbation GitHub indépendante.

L’observation DEV du 2026-10-08 est une réponse HTTP 404 à la lecture publique de
`hoben-experimental`. Le connecteur disponible ne permet pas cette lecture de
Settings ; cela ne prouve ni l’absence de l’environnement ni les permissions
futures du runner. Le propriétaire/MANAGER doit vérifier les réponses effectives.
Aucun paramètre, secret, reviewer ou droit n’a été modifié par CODEX DEV.

## Autoriser une demande avec le connecteur disponible

Le connecteur expose commentaires/labels, lecture des branches, runs, jobs et
artefacts ; il n’expose pas de dispatch. Le signal installé est un ajout de
label sur **l’Issue ouverte #54**, jamais sur une PR. Son label d’état doit être
unique et `state:review` ou `state:blocked` ; conserver tous les autres labels.
`state:blocked` permet au MANAGER une observation autorisée pour apporter la
preuve manquante, sans débloquer automatiquement #48/#51 ni démarrer du DEV.

1. MANAGER examine le diff complet, les exécutables et leurs imports/dépendances
   de la PR de recherche du même dépôt, les tests et les threads. Il la fusionne
   lui-même vers `experimental`. Son commit de merge complet doit être le HEAD
   **actuel** de cette branche ; la CI `Validate`/`tests` de la PR doit avoir réussi.
2. Relever le SHA complet de `main` où le bootstrap est installé et celui de
   `experimental`. Ajouter un **nouveau commentaire non édité**, via
   `github_add_comment_to_issue`, avec exactement ce marqueur et cet objet JSON,
   en remplaçant les valeurs entre chevrons :

```text
<!-- hoben-experimental-decision:v1 -->
{"schema":1,"phase":"dry-run","scenario":"h1h2","main_sha":"<40 caractères hexadécimaux>","experimental_sha":"<40 caractères hexadécimaux>","pull_request":<numéro de la PR fusionnée vers experimental>,"decision":"reviewed-read-only","recipient_sha256":"f0209da5d964c02b9733610bfb4457f7bebd24fdfd32934e1165460bf0ab3246"}
```

3. Après ce commentaire, ajouter **uniquement**
   `manager-hoben-experimental-dry-run` avec `github_update_issue` en préservant
   les labels non réservés. Si déjà présent, retirer puis ajouter : une simple
   lecture ou un label resté présent n’est pas une nouvelle autorisation.
   Le signal doit survenir moins d’une heure après le commentaire. Le sender,
   l’actor et le triggering_actor doivent être le compte GitHub réel
   `Guillaume0385` (id 18246624), y compris lorsque le connecteur réalise l’action.
   Un compte App distinct ne reçoit aucune délégation implicite pour le live.
4. Attendre le **dry-run GitHub réel** : il valide la décision, le merge, les
   SHA, les reviews/threads, les tests, la réservation et un chiffrement CMS
   synthétique. Il n’utilise ni environnement Hoben, ni candidat, ni identifiant,
   ni DNS/TLS Hoben. Le rapport doit indiquer `dry_run_pass`, zéro session et
   `boundary_proven=false`. Un pytest simulé ne remplace pas cette preuve installée.
5. Après succès et vérification des Settings, ajouter un nouveau commentaire
   identique avec `phase=live`, retirer le label dry-run puis ajouter le seul
   label `manager-hoben-experimental-live`. Les deux labels ensemble refusent
   la demande. Le job attend la vraie approbation GitHub ; le gate recontrôle les
   SHA, la décision, la politique et son approbateur avant l’étape de collecte.

Les commentaires sont **des données**, pas du code : aucun script, hôte, chemin,
registre ou argument libre n’est accepté. Seul le dernier commentaire MANAGER
portant ce marqueur est considéré ; invalide/édité/périmé, il n’autorise rien.
Toutes les collections et les threads sont paginés. Un changement de `main` ou
`experimental` annule l’autorisation ; une review obsolète ne couvre pas un autre
exécutable.

## Idempotence et consultation une heure plus tard

Une réservation atomique persistante est créée sous le tag annoté
`hoben-experimental-<dry-run|live>-h1h2-<SHA experimental>`. Son message JSON lie
le SHA candidat, le SHA gate, la phase, le scénario, la PR, le commentaire,
l’événement label et le **run_id**. Elle n’est ni remplacée ni supprimée. Un
échec ou une annulation après réservation consomme cette demande : aucun retry,
re-run, cron ou nouveau passage horaire ne la rejoue. Toute nouvelle collecte
requiert une nouvelle PR/HEAD examinée. Les runs reconnus partagent le verrou
GitHub Actions `hoben-boundary-campaign` avec `opened-client-boundary.yml`,
`manager-live-hoben.yml` et tous les modes réseau de `live-validation.yml`.
Le verrou couvre aussi l'attente d'approbation : deux workflows différents ne
peuvent pas lancer leur sonde simultanément. Le contrôle API des runs actifs
reste une défense supplémentaire ; il ne remplace pas ce verrou atomique.
Les labels sans rapport utilisent un groupe propre au run et ne peuvent pas
remplacer une campagne autorisée en attente. Tout futur workflow Hoben doit
utiliser le même verrou avant d'ouvrir une connexion.

MANAGER retrouve la réservation avec `github_fetch`, puis lit son objet tag :

```text
GET /repos/Guillaume0385/ha-hoben-community/git/ref/tags/hoben-experimental-<phase>-h1h2-<SHA>
GET /repos/Guillaume0385/ha-hoben-community/git/tags/<object.sha>
GET /repos/Guillaume0385/ha-hoben-community/actions/runs/<run_id>
GET /repos/Guillaume0385/ha-hoben-community/actions/runs/<run_id>/jobs?filter=latest&per_page=100&page=1
GET /repos/Guillaume0385/ha-hoben-community/actions/runs/<run_id>/artifacts?per_page=100&page=1
GET /repos/Guillaume0385/ha-hoben-community/commits/<SHA>/status
```

Vérifier chemin `hoben-experimental-request.yml`, événement `issues`, tentative 1,
actor/sender attendus, `head_sha=main_sha`, `head_branch=main`, et l’URL
`https://github.com/Guillaume0385/ha-hoben-community/actions/runs/<run_id>`.
Le HEAD du **run** est celui du gate main ; la réservation, le statut et le nom
exact du rapport lient le **SHA expérimental**. Ne jamais les confondre.
Les wrappers `github_fetch_workflow_run_jobs` / `github_fetch_workflow_run_artifacts`
sont utilisables ; paginer avec GET si nécessaire. Le wrapper
`github_fetch_commit_workflow_runs` filtre aux PR et ne découvre pas ces runs
`issues` : utiliser le run_id réservé. `discover()` teste ce parcours en lecture
seule, sans label, lancement ou mutation lors d’un passage ultérieur.

| État constaté | Interprétation |
| --- | --- |
| queued/requested/pending/waiting | `queued`, peut attendre l’approbation réelle |
| in_progress | `running`, aucune nouvelle demande |
| completed success | jobs et rapport à vérifier ; jamais une preuve de frontière |
| completed failure | `failure` ; rapport absent/invalide n’est pas une réussite |
| completed cancelled | `cancelled` ; ne pas relancer |
| gate refusé/collecte skipped | `NOT RUN`, aucune collecte autorisée |

Le statut `hoben-experimental/h1h2/<phase>` et le commentaire de résultat sur #54
associent run_id, URL et les deux SHA. Le publisher est un runner main distinct,
sans secret Hoben ni code candidat ; il ne charge que le rapport expurgé et
revalide clés, catégories, comptages et correspondances. Les répétitions ne
réécrivent pas le résultat d’une réservation précédente et ne dupliquent pas
son commentaire.

## Collecte et confidentialité

Scénario unique `h1h2` : maximum 6 H1 + 6 H2, pauses 0/0,1/1 s répétées deux
fois, 90 s et 1 Mio RX par session, espacement des sessions et arrêts anticipés
repris de #49. TLS validé sur `myhoben.fr:465`, OpenClient documenté, Ping/Pong,
lecture Modbus 04 uniquement (FFFF, unité 1, adresse 1024, quantité 20) sous les
conditions H2 prévues. Aucune écriture 06/16/22, commande poêle ou association.
Les 48 octets de H2 sont une **hypothèse locale**, pas une frontière confirmée.

Le lanceur de main utilise `execve` avec un environnement allowlisté : aucun
token GitHub, Actions runtime, OIDC, credential git, PYTHONPATH ou flag debug
n’entre dans le processus candidat. Les deux secrets Hoben n’apparaissent que
dans cette étape. Les subprocessus crypto/git utilisent un environnement minimal.

Le certificat public et AES-256-GCM CMS/RSA-OAEP SHA-256 sont testés avant tout
accès TLS. Les captures en clair sont privées (répertoires 0700, fichiers 0600),
hors checkout, puis supprimées dans `finally`, y compris à l’interruption traitable.
Un arrêt brutal du runner ne garantit pas une archive partielle ; aucun fallback
plaintext n’est publié. Seuls deux artefacts fixes, rétention **7 jours**, sortent :

- `experimental-ciphertext-<SHA experimental>-<run_id>` : `captures.cms`, RX et
  journaux privés lisibles seulement avec la clé privée hors GitHub ;
- `experimental-report-<SHA experimental>-<run_id>` : `report.json`, projection
  numérique/catégorielle, aucun GUID, octet RX, valeur domestique ou texte libre.

Le rapport produit par le candidat n'est jamais uploadé directement. Un module
de `main`, sans secret Hoben, vérifie d'abord toutes ses clés, catégories,
comptages, les deux SHA et le run_id, puis écrit un nouveau fichier fixe dans
`hoben-experimental-public`. L'upload exige la réussite de cette validation.
Un champ privé inattendu, un fichier absent ou un lien symbolique refuse
l'artefact public avant publication ; le publisher le revalide ensuite sur son
runner distinct. Le ciphertext n'a aucun fallback en clair.

Déchiffrer uniquement hors GitHub selon la procédure de la campagne #48.
Un résultat `inconclusive` / `hypotheses_unproven` exige les **12 sessions
exécutées, 6 H1 puis 6 H2**, sans établir une preuve de H1/H2. Un arrêt de
campagne avant ces 12 sessions produit `failure` / `collection_interrupted`
et un code de sortie non nul ; son rapport partiel reste exploitable sans
accorder de statut success. Une collecte skipped est `NOT RUN`.
Classer les faits OBSERVÉ / CONFIRMÉ / À VALIDER après
analyse du MANAGER ; aucune modification automatique de `protocol.md`.

## Preuves DEV et prérequis restants

Les tests exécutent réellement le module gate Node, le lanceur et les primitives
CMS contre des API GitHub/collecteurs simulés, sans identifiant réel ni serveur.
Ils couvrent pagination, origine, périmètre, HEAD déplacé, décisions invalides,
concurrence, anti-doublon, politique et approbations, découverte répétée, arrêt,
nettoyage et projection publique. Les résultats chiffrés sont contrôlés par des
tests offline ; la clé du certificat MANAGER n’est jamais demandée à DEV.

**Dry-run GitHub installé : NOT RUN tant que le bootstrap n’est pas fusionné sur
main et que la PR expérimentale n’est pas fusionnée/revue. Live : NOT RUN tant
que le dry-run réel, les règles d’environnement et l’approbation indépendante
ne sont pas vérifiés.** CODEX DEV livre du code préparé ; seul MANAGER établit
l’installation effective et les observations réelles. L’Issue #54 reste ouverte
avec `Refs #54` jusqu’à cette décision ; #48/#51 ne sont pas débloquées par ce code.
