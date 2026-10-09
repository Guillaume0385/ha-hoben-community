# Branche `experimental` — recherche du protocole Hoben en lecture seule

> **Politique de revue issue de #53 ; canal technique préparé dans #54.**
> Le code proposé ne vaut ni installation du bootstrap sur `main`, ni
> configuration des Settings, ni lancement Hoben. Ces étapes restent vérifiées
> séparément par le propriétaire/MANAGER. Aucun test réel n’est lancé par DEV.

## Deux circuits séparés

| Circuit | Branche cible | Objectif | Conditions de fusion |
| --- | --- | --- | --- |
| Recherche protocolaire | `experimental` | Expérimentations H1/H2, trames, Ping/Pong, observations Modbus **en lecture seule** | **Revue simplifiée MANAGER uniquement**, tests ciblés et vérification de sécurité ; **pas de CODEX REVIEW** ni de `state:validate` |
| Intégration publiée | `main` | Code stable Home Assistant/HACS et bibliothèques protocolaires validées | **CODEX REVIEW indépendant, puis MANAGER**, tests complets, HACS/Hassfest et gate live pré-fusion si applicable, selon `AGENTS.md` |

Le propriétaire peut appliquer à `experimental` des vérifications de merge
plus légères que celles de `main`. Cela concerne **la fusion de code**, pas
l'autorisation de remettre les identifiants Hoben à ce code.

## Revue MANAGER simplifiée pour les PR vers `experimental`

Le **critère de routage est la branche cible de la PR** (champ GitHub `base.ref`),
non son nom, ses labels ou la branche source :

- **Base `experimental` :** aucune pré-revue CODEX REVIEW, aucune approbation
  indépendante ni passage obligé par `state:validate`. CODEX DEV termine
  l'implémentation, exécute les tests ciblés puis place l'Issue en `state:review`.
  Le MANAGER prend **directement** la PR en revue, vérifie le diff, le scénario,
  les résultats des tests ciblés, l'absence de fuite d'identifiants, et
  l'absence de commande ou écriture réelle. Si ces points sont satisfaits,
  il peut fusionner vers `experimental` sans attendre la campagne live H1/H2 ;
  la campagne sera lancée séparément après autorisation du MANAGER. Des
  corrections retournent à CODEX DEV (`state:in-progress` puis `state:review`),
  **sans étape CODEX REVIEW**. Une erreur CI pertinente ou un risque de
  sécurité réel reste un motif de correction, pas une dérogation silencieuse.
- **Base `main` :** circuit complet inchangé : `state:review` → CODEX REVIEW
  indépendant → `state:validate` → MANAGER → validations requises → merge.
  La promotion depuis `experimental` passe obligatoirement par une PR dédiée
  ciblant `main`; une revue passée sur `experimental` ne remplace jamais celle
  du code finalement livré.

Les agents et tâches programmées doivent appliquer ce filtrage : **PRE-REVIEW
ignore toute PR dont la base est `experimental`**, et MANAGER ne réclame pas
son approbation avant une fusion expérimentale. Les approbations GitHub
éventuellement exigées par une règle de protection de branche sont distinctes :
leur réglage doit correspondre à cette politique. Les accès aux secrets sont
gérés séparément dans la section suivante. Si l'Issue couvre aussi une future
livraison stable, conserver sa traçabilité jusqu'à la PR finale vers `main` ;
ne pas marquer cette livraison comme réalisée après une simple fusion de
recherche.

## Cycle expérimental

1. Préparer une petite PR ciblant **`experimental`** (pas `main`) et y
   associer le scénario, la capture attendue, les limites et un test hors ligne.
2. Faire examiner les octets émis et les modules exécutés : TLS vérifié,
   destination MyHOBEN documentée, requêtes de lecture uniquement, arrêt borné,
   aucun paramètre libre de commande ou de destination. Ne jamais envoyer de
   commande de marche/arrêt, écriture Modbus, association ou mode technique.
3. Après fusion et examen du **commit exact**, MANAGER demande éventuellement
   **un** run GitHub Actions expérimental ; aucun lancement implicite au merge,
   au push, par cron ni à chaque passage horaire.
4. Relever le SHA, la catégorie de résultat, les arrêts et les métadonnées
   anonymisées. Stocker les RX privés uniquement chiffrés, avec une clé privée
   conservée hors GitHub ; conserver les fixtures expurgées.
5. Corriger ou recommencer dans une nouvelle PR de recherche. Le statut « test
   expérimental réussi » ne démontre pas à lui seul la frontière OpenedClient
   ni la sécurité de fusion vers `main`.
6. Quand le comportement est confirmé, ouvrir une **PR finale vers `main`**,
   avec les tests de non-régression et les mises à jour de `protocol.md` et
   `project.md`. Les contrôles habituels de `main` demeurent obligatoires.

La campagne #48/#49 peut préparer des observations avant une validation finale
de PR ; `state:blocked` n'empêche pas le travail documentaire et les
préparatifs sans secret. Une vraie observation reste soumise au contrôle du
workflow installé et de la configuration effective de l'environnement.

## Accès aux secrets : ne pas confondre branche et environnement

**Le canal #54 retient un environnement séparé `hoben-experimental`, autorisant
exactement Branch `main`.** `issues:labeled` charge la définition de la branche
par défaut ; sa référence de déploiement reste main même après checkout du SHA
expérimental. Une règle limitée à `experimental` refuserait donc ce job. La règle
main-only empêche surtout un workflow de la branche moins protégée d’obtenir les
secrets ou de décider de sa propre admission. L’exécution reste celle du HEAD
expérimental revu et fusionné, sélectionné par la porte de confiance de main.

Le propriétaire configure **Selected branches and tags**, une seule règle
`name=main`, `type=branch`, required reviewers User nommés dont un distinct du
MANAGER demandeur, et **Prevent self-review**. Une approbation GitHub indépendante
réelle est recontrôlée après l’attente ; un bypass ou une politique invérifiable
signifie NOT RUN. CODEX DEV ne configure aucun de ces paramètres/secrets.

La variante antérieure ouvrant `hoben-live` à main/experimental n’est pas
implémentée par #54 : `hoben-live`, ses règles et les workflows existants gardent
leur contrat. Aucune permission n’est accordée au candidat par un simple `if:`.
Une évolution de cette politique exige une décision et une revue distinctes.

Dans les deux cas, la sélection de branche seule ne remplace pas la relecture
du code exécuté ni le contrôle humain avant l'accès à un identifiant réel.
Ne pas déplacer `HOBEN_USER_GUID` dans des secrets globaux du dépôt, les logs,
les arguments shell, les commentaires GitHub ou des artefacts non chiffrés.

## Changements techniques et administratifs encore nécessaires

- **Propriétaire GitHub :** configurer la protection légère de `experimental`
  (PR + revue humaine pour les modifications de code ayant accès aux secrets),
  puis l'environnement, ses branches explicitement autorisées et son
  approbateur. Ne rien modifier sur `main` avant revue.
- **PR technique distincte :** adapter les workflows/gates H1/H2 existants,
  aujourd'hui strictement liés à `main` et à la politique `hoben-live`
  `main`-only. Une PR purement documentaire n'active pas les nouvelles règles ;
  les refus de gate existants ne doivent pas être contournés.
- **MANAGER :** ne jamais considérer un résultat expérimental comme un
  `live-hoben-authenticated=success` de validation de livraison et ne jamais
  fusionner vers `main` sans la revue complète habituelle.

## Critères d'ouverture des tests réels

Avant toute première sonde sur le serveur Hoben, vérifier cumulativement :
l'environnement et la règle d'approbation effective, le commit exact revu,
le workflow installé sur une branche de confiance, la destination TLS fixe,
la liste des seuls messages de lecture autorisés, les budgets de temps/sessions,
le chiffrement préalable des captures et la disponibilité d'un rapport
anonymisé. Tout élément inconnu ou toute vérification inaccessible entraîne
**NOT RUN** plutôt qu'un accès approximatif aux secrets.

Ce document ne modifie aucune donnée de `protocol.md` et ne présume aucune
longueur de trame inconnue.

## Canal concret de l’Issue #54 — préparation, installation, observation

La PR principale vers `experimental` réutilise les modules capture/analyse/replay
et leurs régressions examinées dans #49 (HEAD
`00215ef0589d34e9cf9c2ed5f3c3d2fe9f51ee06`), ainsi que l’enveloppe CMS examinée
sur #52 (`af05e80a71b847c4a79090d9403d041197915af6`). Elle ajoute l’entrée fixe
`scripts/run_experimental_boundary.py` ; le CLI historique reste séparé et ses
conditions de dispatch ne sont pas contournées. Les PR #49/#52 ne sont ni
modifiées ni fusionnées par cette reprise.

La PR bootstrap distincte propose sur main le workflow
`.github/workflows/hoben-experimental-request.yml`, sa porte, le lanceur minimal,
le certificat public et la [procédure de bootstrap](https://github.com/Guillaume0385/ha-hoben-community/blob/main/docs/experimental-request-bootstrap.md)
(disponible sur main **après installation**). Cette PR conserve CODEX REVIEW
indépendant, les quatre checks main et la classification MANAGER applicable.
La fusion expérimentale n’active pas le trigger à elle seule.

Le connecteur MANAGER sait ajouter des commentaires/labels et lire les runs,
jobs et artefacts ; aucun `workflow_dispatch` disponible n’est supposé. Après
revue et fusion de la PR expérimentale, MANAGER doit :

1. Lire les deux HEAD complets actuels, main et experimental, et garder #54
   ouverte avec un seul état `state:review` ou `state:blocked`.
2. Ajouter sur #54 un **nouveau commentaire non édité** exactement au format
   ci-dessous, remplissant les deux SHA et le numéro de sa PR fusionnée.
3. Ajouter le seul label réservé `manager-hoben-experimental-dry-run`, en
   conservant les autres labels. Retirer puis ajouter si déjà présent ;
   l’événement doit être postérieur au commentaire et daté de moins d’une heure.
4. Retrouver le run réservé et vérifier le succès du **dry-run GitHub installé**
   et son rapport : `dry_run_pass`, zéro session, aucun identifiant ni TLS Hoben.
5. Après vérification des Settings, ajouter un nouveau commentaire `phase=live`,
   retirer le label dry-run puis ajouter `manager-hoben-experimental-live`.
   Attendre l’approbation GitHub indépendante effective, sans confirmation
   conversationnelle supplémentaire. Les deux labels simultanés refusent le run.

```text
<!-- hoben-experimental-decision:v1 -->
{"schema":1,"phase":"dry-run","scenario":"h1h2","main_sha":"<SHA complet main installé>","experimental_sha":"<SHA complet HEAD experimental>","pull_request":<numéro PR fusionnée>,"decision":"reviewed-read-only","recipient_sha256":"f0209da5d964c02b9733610bfb4457f7bebd24fdfd32934e1165460bf0ab3246"}
```

Le compte réel actor/sender/triggering_actor doit être `Guillaume0385`,
id 18246624. Une App distincte n’est pas implicitement déléguée pour recevoir les
secrets. Les commentaires sont des données strictement structurées : aucun
chemin, commande, hôte, registre ou argument libre n’est exécuté. Un HEAD déplacé,
une décision éditée, un thread non résolu, des corrections demandées ou une CI
pertinente échouée refusent l’exécution. Le contrôle est renouvelé après l’attente.

Le propriétaire garde uniquement `HOBEN_USER_GUID` et l’éventuel
`HOBEN_DEVICE_GUID` dans l’environnement dédié. Le certificat public RSA 3072 bits
repris de #52 et son empreinte DER SHA-256 ci-dessus sont publics ; sa clé privée
reste hors GitHub et sa possession est un prérequis du MANAGER. Le gate et l’entrée
vérifient la validité et exercent AES-256-GCM CMS / RSA-OAEP SHA-256 **avant TLS**.
Le lanceur main remplace le processus avec une allowlist d’environnement sans
token GitHub/Actions/OIDC. Le publisher est un autre runner, sans secret Hoben.

### Retrouver et interpréter le résultat sans redemander un test

La réservation persistante est le tag annoté
`hoben-experimental-<dry-run|live>-h1h2-<SHA experimental>`. Lire sa référence puis
son objet avec `github_fetch` (`git/ref/tags/...`, puis `git/tags/<object.sha>`) :
son message JSON fournit `run_id`, `main_sha`, `candidate_sha`, `phase`, `scenario`
et la décision liée. Lire ensuite `actions/runs/<run_id>`, ses jobs et artefacts
(pagination si nécessaire), puis `commits/<SHA experimental>/status`. L’URL est
`https://github.com/Guillaume0385/ha-hoben-community/actions/runs/<run_id>`.
Vérifier chemin du nouveau workflow, événement issues, tentative 1, actor,
`head_sha=main_sha` : le HEAD du run est main, celui du candidat est experimental.
Le wrapper de recherche des runs par commit filtre actuellement aux PR et ne
retrouve pas ces événements issues ; utiliser le run_id de la réservation.

`queued` inclut l’attente d’environnement ; `running` correspond à in_progress.
Puis vérifier success/failure/cancelled et les jobs : gate refusé ou collecte
skipped signifie **NOT RUN**. Le statut `hoben-experimental/h1h2/<phase>` et le
commentaire expurgé sur #54 lient les SHA, scénario, run ID et URL. Le rapport
public a un nom exact `experimental-report-<SHA experimental>-<run_id>` ; les RX
sont séparés dans `experimental-ciphertext-<SHA experimental>-<run_id>`, fichier
`captures.cms`. Les deux expirent après **7 jours**. Aucun export plaintext,
GUID, valeur domestique, frame, texte d’exception ou clé privée n’est publié.

Un échec/une annulation après réservation consomme la demande. Ni un re-run ni
un passage MANAGER une heure plus tard ne relance le scénario. Une nouvelle
collecte exige une nouvelle PR/HEAD revu ; aucun tag n’est effacé pour contourner
la règle. La sérialisation est partagée avec les campagnes précédentes.

Scénario fixe : 6 H1 + 6 H2 au maximum, 90 s et 1 Mio RX par session, pauses
0/0,1/1 s répétées deux fois, arrêts anticipés et émission de lectures V4 04
uniquement selon #49. Le suffixe RX est conservé avant parsing dans l’archive
privée. H2/48 octets reste une hypothèse ; `inconclusive` ne confirme jamais la
frontière et exige les 12 sessions exécutées, 6 H1 puis 6 H2. Une campagne
interrompue plus tôt produit `failure` / `collection_interrupted` et un code de
sortie non nul, avec les seules données partielles validées dans le rapport.
Le bootstrap de main doit contrôler et projeter ce rapport avant son upload,
puis le revalider dans le publisher. Ses workflows Hoben partagent un verrou
de concurrence commun ; les labels sans rapport ne doivent pas occuper ce verrou.
Après analyse privée, MANAGER distingue OBSERVÉ / CONFIRMÉ / À VALIDER
et propose séparément les modifications documentaires/protocolaires étayées.

**État de livraison DEV : code préparé et simulations offline. Dry-run GitHub
installé : NOT RUN avant fusion bootstrap/main et experimental. Live : NOT RUN
avant dry-run réel, politique vérifiable et approbation réelle.** La lecture
publique DEV de `hoben-experimental` a renvoyé HTTP 404 le 2026-10-08 ; aucune
conclusion sur son existence ni les permissions du futur runner n’en découle.
Aucun secret, Setting ou protection n’a été changé ; #48/#51 restent bloquées
jusqu’aux preuves et décisions du MANAGER.
