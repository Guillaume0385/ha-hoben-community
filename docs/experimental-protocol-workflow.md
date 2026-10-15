# Workflow courant — développement experimental, validation et promotion

## Règles de branche et de revue

Toute PR de développement contenant du code, des tests, des sondes ou des
workflows cible exactement `experimental`. Une Issue autorisée porte un seul
label `state:*` : `state:ready` → CODEX DEV `state:in-progress` → `state:review`
pour MANAGER. MANAGER relit l'intégralité du diff, le SHA exact, la CI, la sécurité,
les faits de protocole et les remarques antérieures. Les corrections reviennent
sur la même PR, puis en revue MANAGER. Les quatre checks ordinaires `tests`,
`ha-tests`, `hacs`, `hassfest` doivent réussir sur le HEAD examiné.
CODEX REVIEW et `state:validate` ne sont pas requis sur cette voie expérimentale.

Une PR strictement documentaire peut cibler `main` seulement sur demande
explicite du propriétaire. Toute promotion de développement vers `main` exige
une nouvelle demande explicite ; ne pas préparer ou rouvrir une PR de promotion
comme étape automatique. CODEX DEV ne fusionne pas, ne s'auto-approuve pas,
n'ajoute pas `state:validate` ou `manager-live-hoben` et ne lance pas de test réel.

## Installation vérifiée et limites de cette documentation

État vérifié le 14 octobre 2026 sur la base `experimental`
`ba007baf42f5120ce9b26aada95231c3930ca449` :

- [#67](https://github.com/Guillaume0385/ha-hoben-community/pull/67) est fusionnée
  depuis le 10 octobre (`b9fa072ea061598e4855fface00133e9ec6eb921`) : les nouvelles
  campagnes H1/H2 exportent seulement un rapport anonymisé, sans export RX ni CMS.
- [#75](https://github.com/Guillaume0385/ha-hoben-community/pull/75) est fusionnée
  depuis le 11 octobre (`f2c9b89f36404ad14193faac6dc006e84d7db36f`) : la preuve de
  rerun natif v2 est raccordée aux deux gates. Les anciennes mentions DRAFT/non
  installé décrivent la préparation de cette PR, pas l'état courant.
- Les définitions exécutées **uniquement sur `experimental`** sont [H1/H2](https://github.com/Guillaume0385/ha-hoben-community/blob/experimental/.github/workflows/hoben-experimental.yml)
  et [HA parity](https://github.com/Guillaume0385/ha-hoben-community/blob/experimental/.github/workflows/hoben-live-experimental.yml), avec les gates
  [lab](https://github.com/Guillaume0385/ha-hoben-community/blob/experimental/.github/scripts/experimental-lab-gate.cjs),
  [live](https://github.com/Guillaume0385/ha-hoben-community/blob/experimental/.github/scripts/experimental-live-gate.cjs),
  [push](https://github.com/Guillaume0385/ha-hoben-community/blob/experimental/.github/scripts/experimental-push-preflight.cjs) et
  [rerun](https://github.com/Guillaume0385/ha-hoben-community/blob/experimental/.github/scripts/experimental-native-rerun.cjs).

Une installation Git ne prouve ni les Settings effectifs, ni les secrets, ni
l'approbation d'un environnement, ni le fonctionnement universel des reruns.
Le runner doit établir ces preuves à chaque admission et recheck. Les tests CI
des gates utilisent des fixtures GitHub simulées. Les observations H1/H2 restent
[sourcées séparément](../protocol.md#observations-de-protocole-v4--observé--à-valider).
Les anciennes voies `main` sont historiques ; elles ne sont ni un préalable
expérimental ni une autorisation de lancement. Les règles de sécurité des anciens
exports CMS restent décrites dans la [procédure historique](opened-client-boundary-campaign.md).

## Deux voies réelles distinctes, strictement en lecture seule

| Scénario | Environnement | Portée réelle au SHA indiqué |
| --- | --- | --- |
| `h1h2` | `hoben-experimental` | Recherche H1/H2 séparée du runtime HA ; au plus 6 H1 + 6 H2, 90 s et 1 MiB RX par session. |
| `ha-parity` | `hoben-live` | Vrai `HobenClient` du SHA testé : deux `async_refresh()`, même `decode_v4_snapshot()` que le coordinator, puis `async_close()`. |

HA parity utilise actuellement un client `one-shot`, deux connexions TLS et deux
lectures V4 de 20 registres, avec réutilisation en mémoire du DeviceGuid,
`max_attempts=1` et un budget global de 150 s. Il ne teste pas l'ordonnanceur HA
complet. Session persistante, Ping/Pong post-open, DataUpdated et reprise après
panne ne sont pas validés par ce rapport : conserver `unsupported`/`not_tested`.
Une sonde H1/H2 ne remplace jamais le test du vrai client.

Les deux voies gardent TLS vérifié, destination fixe `myhoben.fr:465`, budgets
bornés et arrêt sans replay implicite. Aucune association, écriture Modbus
06/16/22, transaction de commande FFF0, consigne, marche/arrêt, ventilation,
commande technique, destination/script/mode libre. L'instrumentation H1/H2
reste hors de `custom_components/hoben/`. Les suites pytest/CI PR restent hors
ligne, sans identifiant Hoben ni accès au poêle.

## Voie `session-300` — hypothèse expérimentale

La [tranche structurelle 7/8-E](session-suite-plan.md) a suspendu cette voie avec
un job en échec pendant l'installation de la suite complète à deux scénarios.
G1/G2 sont fusionnées ; H prépare le seul retrait de ce préalable, après revue
MANAGER du raccordement. Tous les gates ci-dessous restent conservés ; aucune
ancienne autorisation session-300 n'admet la suite. Une PR candidate ne lance
aucun test réel : suite/reconnexion restent NOT RUN. La validation historique
300 s acquise ne vaut pas validation du nouveau scénario ni autorisation de 8.

La [décision de périmètre #74](https://github.com/Guillaume0385/ha-hoben-community/issues/74#issuecomment-6177981552)
et l'[Issue #81](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6176992612)
autorisent la préparation d'une validation fonctionnelle expérimentale de 300 s
avec le gestionnaire partagé. Après l'alignement documentaire 7/8-A, la tranche
7/8-B fournit le [workflow dédié](../.github/workflows/hoben-session-300.yml),
son [gate](../.github/scripts/session-300-gate.cjs), la
[sonde](../scripts/run_session_300.py) et le
[validateur d'export](../.github/scripts/session-300-report.cjs).
Le code seul n'autorise aucun accès réel. Routage réel et validation 300 s :
**NOT RUN** jusqu'à un run admis et un rapport effectivement vérifiés.

Pour ce seul scénario opt-in, borné, sur `experimental` et l'Osmose V4 de
référence, les octets suivant le préfixe V4 de 48 octets strictement accepté
pourront être traités comme trafic post-ouverture. Cette **hypothèse
expérimentale** ne prouve ni le handoff local ni une longueur totale universelle,
et ne transforme aucune observation en fait `CONFIRMÉ`.
Le [contrat de périmètre](../project.md#décision-de-périmètre--handoff-expérimental-session-300)
limite le futur framer à Ping et DataResponse corrélée, avec arrêt sûr sur type
inconnu, DataUpdated, MBAP invalide, suffixe indécidable ou dépassement de budget.

La voie fixe vise 300 s utiles, avec plafond dur de processus 360 s, au plus
trois ouvertures, 1 Mio RX cumulé et six lectures fixes espacées d'au moins 60 s.
La collecte réserve 350 s, puis au plus 10 s au nettoyage. Le rapport n'exporte
que la provenance SHA/run/PR/tentative, `boundary_proven=false`, les compteurs
et des catégories fermées ; aucun registre, identifiant ni RX brut.
Scénario exact `session-300`, environnement
`hoben-experimental`, mutex `hoben-read-only-observation`, déclenchement uniquement
par le push du merge MANAGER sur `experimental`. Avant tout accès réel, elle
devra conserver la provenance dépôt/branche/SHA/acteur, la PR revue et fusionnée
par MANAGER, les quatre checks CI du HEAD exact et une autorisation MANAGER
distincte, unique, immuable et antérieure au merge. Admission, politique
d'environnement lue par API, approbation éventuelle, réservation anti-rejeu et
recheck avant secrets restent obligatoires ; aucun token GitHub/Actions ne doit
être transmis à la sonde. DEV et la CI PR restent hors ligne. Aucun commentaire
d'autorisation live n'est publié par DEV. Le marqueur dédié est
`<!-- hoben-session-300-approval:v1 -->`, suivi d'un objet JSON strict avec
`schema=1`, `scenario=session-300`, `candidate_sha` et `ci_run_id` seulement.
MANAGER publie cette décision immuable après revue et CI du HEAD, avant merge.
La réservation atomique `hoben-session-300-<candidate_sha>` reste consommée même
en cas d'échec. Seule la tentative 1 est admise : aucun rerun n'est autorisé par
cette voie. Le recheck relit SHA, politique, décision et claim après l'attente
d'environnement ; si des reviewers sont requis, une approbation indépendante
datée après le début du dry-run doit être réellement vérifiable. Sinon NOT RUN.
Les données validées passent vers un runner de publication sans secret, puis
sont revalidées avant artefact (rétention sept jours) et résultat. Seules
`continuous_300s` et `reconnected` peuvent valider la fenêtre fonctionnelle ;
les autres catégories sont `interrupted`, `inconclusive` et `not_run`.

Cette future voie n'étend ni ne remplace H1/H2 ou HA parity : leurs budgets,
gates, rapports, réservations et statuts restent inchangés. Les contrats détaillés
ci-dessous décrivent ces deux voies historiques installées ; leur v1/v2 ne
vaut jamais autorisation `session-300`. La revue et les gates dédiés restent
requis pour le scénario exact, sans réutilisation d'une décision H1/H2.
`NOT RUN`, `PENDING APPROVAL`, `inconclusive` ou interruption ne valident pas
l'étape 7 et bloquent l'étape 8. Une reconnexion ne sera jamais présentée comme
une connexion continue. Aucun changement HA ni usage par `hoben-live` avant une
étape 7 réellement concluante ; aucune promotion automatique vers `main`.

## Suite installée, activation candidate 7/8-H

Le [sous-ensemble 7/8-G1](session-suite-plan.md#contrat-dadmission-spécifique--sous-ensemble-78-g1)
installe `session-suite-gate.cjs` et son contrat fixe. G2 (PR #95) a branché ce gate
dans le workflow push existant et ajouté le launcher/collecteur de suite sous
verrou. H retire seulement `suite-installation` et son `needs` dans `dry-run` ;
conditions exactes push/branche/acteurs/tentative, permissions, gates, runtime,
contrat et budgets restent identiques. Aucune ancienne décision ne peut activer
un run partiel. Le préflight sans secret mène à l'admission, puis à
l'environnement et au recheck avant capture ; tout refus pré-secrets conserve
les deux NOT RUN.
Le gate `session-300` historique garde son contrat et ses contrôles. Les deux
wrappers réutilisent les mêmes vérifications de provenance/revue/CI/politique
d'environnement et le même recheck, avec des décisions et claims distincts.

Le futur marqueur dédié est `<!-- hoben-session-suite-approval:v1 -->`.
Ses clés exactes sont `schema`, `scenario`, `candidate_sha`, `ci_run_id`,
`scenarios`, `limits` : scénario `session-suite`, ordre fixe session-300 puis
session-reconnect-no-pong, plafonds fixes détaillés dans le plan. La décision
unique doit être authentique, immuable et antérieure à la fusion. DEV ne la
publie pas. Le claim `hoben-session-suite-<candidate_sha>` lie le contrat entier,
la décision, PR/CI via cette décision, SHA/run/tentative et politique. Une ancienne
décision ou référence session-300/H1H2/ha-parity n'est jamais utilisée comme repli.

Le launcher fixe `launch_session_suite.py` lance un unique collecteur
`run_session_suite.py` qui appelle `observe_suite()` et la vraie implémentation
partagée. Le parent supervise les plafonds externes 360/600/1020 s, arme le
second plafond avant son ACK et tue le groupe entier au timeout, à l'annulation
ou à la fin. Les budgets internes 350+10 et 590+10 restent distincts ; aucun
commentaire ou input ne fournit de durée libre. Une seconde est réservée au
SIGKILL/reaping dans chaque plafond. Les tests offline incluent un processus
résistant à l'annulation asyncio et son descendant dans chacune des phases.
Le collecteur reçoit seulement l'allowlist de contexte et preuves
`SESSION_SUITE_*`, avec identité privée : aucun token GitHub/Actions/OIDC,
fichier de commandes Actions, hook Python ni installation de dépendance libre.

Après validation Python, le rapport exclusif 0600/0700 est borné à 8192 octets.
Le workflow exporte uniquement après recheck et superviseur réussis. Node
revalide le double schéma, la provenance et la taille avant transfert base64
canonique (10924 caractères maximum), puis revalide et matérialise le JSON sur
un runner séparé sans secret Hoben. L'artefact
`session-suite-report-<SHA>-<run_id>-a1` conserve sept jours maximum de rétention.
Le statut `hoben-experimental-session-suite` exige les deux sous-résultats
admissibles, la collecte et la publication réussies ; rapport absent/incomplet
ou refusé reste en échec. Les refus pré-secrets annoncent les deux NOT RUN,
sans fabriquer de rapport de collecte. Les scripts du workflow et cette
chaîne d'export/publication sont testés hors ligne.

Ce candidat d'activation doit être revu par MANAGER sur son SHA exact et ses
quatre checks CI. MANAGER publie ensuite la décision unique immuable conforme au
contrat installé avant la fusion au HEAD attendu. DEV ne publie aucune décision,
ne réserve aucun claim réel et ne lance aucun run. Le push après fusion reste
soumis aux contrôles installés, dont recheck, politique et approbation fraîche
si requise. La PR ouverte ou fusionnée ne prouve aucun résultat réel.
Suite/reconnexion : NOT RUN tant qu'aucun run admis et rapport anonymisé ne sont
vérifiés. Il faut le premier scénario admissible et `recovered_120s` ; absence
d'EOF, scénario non exercé, résultat inconclusif ou échec bloquent l'étape 8.
EOF après inhibition n'établit pas sa cause ; `boundary_proven=false` demeure.
Aucune preuve de frontière OpenedClient ne découle des tests simulés du gate.

## Admission : provenance, revue et CI exactes

Le premier run provient uniquement d'un `push` sur `refs/heads/experimental`
après une fusion MANAGER. Un push seul ne libère aucun secret. Préflight,
admission et recheck vérifient notamment :

- dépôt exact `Guillaume0385/ha-hoben-community`, ID `1401398724` ; acteur et
  `triggering_actor` exacts `Guillaume0385` (identité GitHub User ID `18246624`
  dans les preuves API applicables), événement et workflow attendus ;
- SHA Actions, SHA du workflow et HEAD courant de la branche protégée
  `experimental` identiques ; push ni forcé, ni création/suppression de branche ;
- une seule PR associée, fusionnée par MANAGER, non draft, même dépôt/base
  `experimental` ; SHA de fusion exact et arbre candidat identique à l'arbre
  fusionné. Les conflits résolus dans un autre arbre exigent une nouvelle revue ;
- revue MANAGER de cette PR, aucun avis actif `CHANGES_REQUESTED`, tous les
  threads résolus ; la décision structurée ci-dessous lie la revue au candidat ;
- run `Validate` de type `pull_request`, tentative **1**, même HEAD/branche/dépôt,
  terminé avec succès avant la décision MANAGER ; exactement quatre jobs
  `tests`, `ha-tests`, `hacs`, `hassfest` réussis sur ce SHA. Une association PR
  restante doit correspondre à cette PR/base ; une liste vide après fusion
  n'est acceptée qu'avec la décision MANAGER authentique liant CI/PR/HEAD.

Les PR code/tests/docs/workflows sont éligibles sans `Refs #54` ni état imposé à
l'Issue #54 ; cette éligibilité ne vaut pas autorisation de campagne.
Un rerun de CI ordinaire ne remplace pas la tentative 1 exigée par ces gates.

## Décisions MANAGER et preuve de relance complète

Les commentaires de décision sont réels, authentifiés, uniques pour la cible,
non modifiés (`created_at == updated_at`), avec uniquement les champs attendus :

| Tentative | Marqueur au début du commentaire | Champs JSON exacts |
| --- | --- | --- |
| 1 | `<!-- hoben-experimental-approval:v1 -->` ou `<!-- hoben-live-approval:v1 -->` | `schema=1`, `scenario`, `candidate_sha`, `ci_run_id` |
| N > 1 | `<!-- hoben-experimental-approval:v2 -->` ou `<!-- hoben-live-approval:v2 -->` | `schema=2`, `scenario`, `candidate_sha`, `ci_run_id`, `pr_number`, `merge_sha`, `run_id`, `run_attempt` |

`scenario` vaut respectivement `h1h2` ou `ha-parity`. La v1 doit précéder la
fusion et reste vérifiée lors des répétitions ; son absence ne se répare pas
par une v1 post-fusion. La nouvelle v2 doit être postérieure à la fusion et
antérieure au démarrage du dry-run de la tentative visée. Une v1 ou une ancienne
v2 ne vaut jamais autorisation de la tentative suivante. DEV ne publie pas ces
décisions et ne fabrique pas une approbation au nom de MANAGER.

Après ces prérequis, seul **Re-run all jobs** sur le run original et le même SHA
peut répéter la campagne (tentatives 2 à 50). Les jobs utilisent toujours le YAML
et le code du SHA original : un ancien run ne reçoit pas les correctifs ultérieurs.
Aucun commit factice, branche temporaire, tag déclencheur, `workflow_dispatch`
indisponible, rerun de job isolé ou **Re-run failed jobs** n'est un substitut.
Le propriétaire peut utiliser l'interface GitHub si le connecteur n'expose pas
le rerun complet ; cette action seule n'autorise jamais l'accès Hoben.

Pour N > 1, l'API doit fournir le run et son `run_attempt`, l'identité distincte
`triggering_actor`, puis des jobs courants uniques avec `run_id`, `head_sha` et
`run_attempt` concordants. Le dry-run courant doit être réussi et son
`started_at` exploitable ; admission courante queued/in_progress à l'admission,
puis réussie au recheck avec collect courant queued/in_progress/waiting.
Le dry-run de N−1 doit lui aussi être attesté réussi. Après un dry-run antérieur
en échec, une relance complète est indiscernable d'une relance partielle et reste
refusée. Champ absent, succès réutilisé ou preuve ambiguë : **NOT RUN**.

## Environnements, approbations et recheck avant secrets

La politique effective doit être relue par API, sans déduire sa conformité de
`experimental.protected=true` ou d'une déclaration de réglage. Les gates actuels
n'acceptent pas les mêmes modes pour les deux environnements :

| Environnement | Politique acceptée |
| --- | --- |
| `hoben-experimental` | `protected_branches=false`, `custom_branch_policies=true` ; exactement une règle `experimental` de type `branch`, sans wildcard ni tag. |
| `hoben-live` | Même politique personnalisée, **ou** `protected_branches=true`, `custom_branch_policies=false` avec lecture API effective de `experimental`, `protected=true`, HEAD égal au SHA testé à l'admission et au recheck. |

L'empreinte de réservation inclut la politique, la preuve de branche et les
reviewers ; un changement de mode ou de politique refuse le recheck. Réponse
incomplète, mode mixte/inconnu, erreur API ou branche déplacée : **NOT RUN**.

L'absence de reviewers requis est admise uniquement si l'API l'atteste réellement.
Une règle `required_reviewers` impose `prevent_self_review=true`, des utilisateurs
GitHub identifiés, au moins un reviewer indépendant de MANAGER, et une véritable
approbation du déploiement. Les règles inconnues sont refusées ; les règles
GitHub configurées, notamment l'attente, restent obligatoires. Jusqu'à approbation
requise : **PENDING APPROVAL**, sans vote à la place du reviewer ni contournement.

Pour N > 1, le recheck exige une approbation fraîche propre à la tentative,
avec date de décision au moins égale au début du dry-run courant. Le `created_at`
de `environments[]` date l'environnement, **pas** l'approbation. Si l'historique
GitHub ne fournit pas de date exploitable de décision, le gate refuse. Cette
compatibilité avec reviewers requis reste **non validée opérationnellement** ;
ni CI verte, ni ancien approval, ni commentaire ne comble cette preuve manquante.

Le job collect attend l'environnement puis revalide toutes les preuves avant
l'unique étape recevant `HOBEN_USER_GUID` et `HOBEN_DEVICE_GUID`. Ne pas installer
de dépendance candidate arbitraire ni transmettre de token GitHub/Actions/OIDC
ou de fichier de commandes Actions au sous-processus candidat. Les lanceurs
utilisent une allowlist d'environnement et n'exportent pas stdout/stderr privés.
Ne jamais modifier Settings, secrets, reviewers ou protections pour faire passer
un test. Une configuration invérifiable laisse la campagne non exécutée.

## Réservation anti-rejeu et concurrence

Admission réserve atomiquement un tag non release, sur un runner sans secret
Hoben. Tentative 1 : `hoben-experimental-h1h2-<SHA>` ou
`hoben-live-ha-parity-<SHA>`. Tentative N > 1 :
`hoben-<scenario>-<SHA>-run<run_id>-attempt<N>`. Au recheck, référence, objet,
SHA et empreinte de décision/politique doivent correspondre exactement.
Une réservation consommée par échec ou annulation n'est jamais supprimée,
réécrite ou réutilisée pour contourner l'admission.

`createRef` est atomique tant que la référence existe ; cela ne garantit pas
son indélébilité. Les protections de tags/rulesets ne sont pas présumées actives.
Un acteur pouvant supprimer/réécrire le tag pourrait effacer la trace ; MANAGER
doit évaluer cette limite. Si une preuve durable de non-réutilisation est requise
et indisponible, conserver **NOT RUN**, sans changer les permissions.

Les deux voies partagent le mutex `hoben-read-only-observation`. À l'admission
et au recheck, les gates recherchent aussi les workflows historiques actifs
(`requested`, `queued`, `pending`, `waiting`, `in_progress`) et refusent une
observation concurrente ou une identification ambiguë. Ces deux lectures API
ne sont pas un verrou global atomique contre un workflow hors mutex. MANAGER
doit contrôler les chemins historiques encore déclenchables et ne pas exécuter
une ancienne sonde simultanément. Ne pas revendiquer une exclusion globale non
prouvée.

## Données privées, publication et résultat

Le chemin H1/H2 courant conserve RX, journaux et identité dans un dossier privé
hors checkout (0700, fichiers 0600), puis les détruit dans `finally`. Aucun RX,
GUID, secret, code, registre ou donnée domestique ne quitte le runner. Les anciens
exports CMS restent chiffrés ; aucune clé ancienne n'est demandée ou reconstruite.
Leur procédure n'autorise pas un export brut dans le chemin actuel sans CMS.

Seul un rapport numérique/catégoriel allowlisté sort de collect, après projection
Python et validation Node indépendante. Les chronologies portent sur temps
relatifs, tailles, offsets, catégories TX/RX, fermeture et candidats H2, jamais
les octets inconnus ni des exceptions libres. Les candidats restent
`h2_hypothesis_only` ; les compteurs de fragmentation/concaténation ne prouvent
pas de frontières. Bornes de validation : 260 lectures, 100 TX, 256 annotations,
1 MiB RX, 180 s de chronologie par session, lecture du rapport au plus 2 MiB.
Le transfert vers publish impose en plus un JSON d'au plus **340 KiB**
(`MAX_REPORT_BYTES`) ; dépasser cette borne refuse la sortie encodée. Ces
plafonds n'étendent pas le budget d'expérience de 90 s par session.

Collect ne téléverse aucun fichier. Sa sortie encodée et bornée est transmise
au job publish sur un **nouveau runner sans environnement ni secret Hoben**,
qui décode, valide et matérialise à nouveau le JSON. Sortie absente/tronquée ou
champ supplémentaire : aucun upload ni repli brut. Les rapports contiennent
`scenario`, `merge_sha`, `pr_number`, `run_id`, `run_attempt`, vérifiés contre
les preuves Actions/recheck avant upload et de nouveau au résultat. Artefacts
`experimental-report-<SHA>-<run_id>-a<N>` ou
`live-ha-parity-report-<SHA>-<run_id>-a<N>`, rétention maximale de 7 jours.

Le job result, sans secret Hoben, publie le statut correspondant seulement si
collect, publication et rapport validé satisfont leur contrat. Un succès H1/H2
reste `inconclusive` / `boundary_proven=false`, jamais une validation de framing.
Une expérience absente/incomplète ne devient pas un succès protocolaire.

## Handoff MANAGER et promotion

Avant campagne, MANAGER contrôle le code, les preuves ci-dessus et la nécessité
du scénario ; il publie la v1 avant fusion ou la v2 avant rerun. Après lancement
réel, relever SHA, scénario, PR, run_id, run_attempt, acteur, URL, état effectif
et limites du rapport. Une opération indisponible reste **NOT RUN** ; ne pas
inventer un déclenchement ou une review. Aucun test live par DEV, cron ou CI PR.

Les observations étayées vont dans [protocol.md](../protocol.md), la roadmap dans
[project.md](../project.md), les règles d'agents dans [AGENTS.md](../AGENTS.md).
Les résultats KO d'orchestration restent dans les runs/PR/Issues, pas comme faits
de protocole. Dédupliquer les Issues ; `state:waiting` par défaut, `state:ready`
uniquement après triage MANAGER. Une observation inconclusive ne clôt pas une
inconnue. Chaque PR actualise [CHANGELOG.md](../CHANGELOG.md) ou justifie l'absence
d'impact ; séparer fusions vérifiées, recherche expérimentale et travail en cours.

Après développement et validations pertinentes sur `experimental`, seule une
**nouvelle demande explicite du propriétaire** autorise à préparer la promotion
vers `main`. Cette future PR exige CODEX REVIEW, MANAGER, CI et les validations
conditionnelles applicables au SHA exact. Un résultat expérimental ne remplace
pas le gate stable ; ses anciennes politiques doivent être revalidées avant
usage. Cette documentation ne prépare ni n'autorise cette promotion.
