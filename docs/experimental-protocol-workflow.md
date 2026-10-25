# Workflow courant — voie manuelle #119 et historique

## Voie courante : dispatch manuel sur experimental

Étape 8, tranche B de #112 : le véritable client HA utilise le mode persistant
partagé préparé par A. Ses tests sont exclusivement hors ligne ; B ne modifie
aucun workflow/gate. Le futur test manuel hoben-live et son admission relèvent
de C. Les descriptions ha-parity one-shot historiques plus bas, ainsi que leurs
anciens rapports, ne valident ni une seconde ouverture actuelle ni ce client
persistant. Aucun accès réel HA n'est activé par la seule livraison de B.

La [procédure #119](hoben-manual-workflow.md) prévaut pour toute nouvelle campagne :
workflow_dispatch du propriétaire, sélecteur natif Use workflow from, experimental
seule active, SHA/provenance/revue/CI exacts, claim anti-rejeu et recheck après
approbations d'environnement. Aucun commentaire MANAGER pré-fusion ni lancement
sur push/PR/merge ; reruns refusés, nouveau dispatch explicite requis.
H1/H2, session-300, reconnexion seule et all réutilisent les vrais collecteurs et
leurs plafonds. Le reste de ce document conserve les contrats et observations
historiques des anciennes voies : leurs décisions/claims ne sont jamais un repli.
Les règles de revue/branche restent applicables, aucun test réel par DEV.

Le [contrat expérimental CloseClient](session-suite-plan.md#closeclient-expérimental--closeclient-session-close-006)
autorisé par #112 emploie deux octets, une fermeture typée distincte d'EOF et
les mêmes bornes de reconnexion/stabilité. Il ne modifie aucune admission,
approbation, protection de workflow ou limite de processus.



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
G1/G2 sont fusionnées ; H (PR #96) a fusionné le seul retrait de ce préalable,
après revue/CI et décision MANAGER distincte. Les gates sont conservés ; aucune
ancienne autorisation session-300 n'admet la suite. Une PR candidate ne lance
aucun test réel. Le run #38828423500 a ensuite exécuté les deux scénarios :
300 s continu, puis reconnexion inconclusive/protocol ; suite non validée et
étape 8 suspendue. Voir le [bilan sourcé](session-suite-plan.md).

La [décision de périmètre #74](https://github.com/Guillaume0385/ha-hoben-community/issues/74#issuecomment-6177981552)
et l'[Issue #81](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6176992612)
autorisent la préparation d'une validation fonctionnelle expérimentale de 300 s
avec le gestionnaire partagé. Après l'alignement documentaire 7/8-A, la tranche
7/8-B fournit le [workflow dédié](../.github/workflows/hoben-session-300.yml),
son [gate](../.github/scripts/session-300-gate.cjs), la
[sonde](../scripts/run_session_300.py) et le
[validateur d'export](../.github/scripts/session-300-report.cjs).
Le code seul n'autorise aucun accès réel. MANAGER a consigné `continuous_300s`
pour les runs #38766830984 et #38828423500 ; aucun des deux ne valide à lui seul
une reconnexion réelle ni une frontière universelle.

Pour ce seul scénario opt-in, borné, sur `experimental` et l'Osmose V4 de
référence, les octets suivant le préfixe V4 de 48 octets strictement accepté
pourront être traités comme trafic post-ouverture. Cette **hypothèse
expérimentale** ne prouve ni le handoff local ni une longueur totale universelle,
et ne transforme aucune observation en fait `CONFIRMÉ`.
Le [contrat de périmètre](../project.md#décision-de-périmètre--handoff-expérimental-session-300)
limite le framer à Ping et DataResponse corrélée, avec l'exception propriétaire
#112 pour ignorer exactement 07/1B après validation MBAP, sans interpréter le
corps. Type inconnu/autre non pris en charge, MBAP invalide, suffixe indécidable
ou dépassement de budget gardent l'arrêt sûr.

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

## Suite activée 7/8-H, diagnostics offline 7/8-I

Le [sous-ensemble 7/8-G1](session-suite-plan.md#contrat-dadmission-spécifique--sous-ensemble-78-g1)
installe `session-suite-gate.cjs` et son contrat fixe. G2 (PR #95) a branché ce gate
dans le workflow push existant et ajouté le launcher/collecteur de suite sous
verrou. H a retiré seulement `suite-installation` et son `needs` dans `dry-run` ;
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

PR #96 est fusionnée au SHA `d382540b056adf189bc7969b3d9905ab7dc8cd8f`, après
revue du HEAD/CI et décision MANAGER immuable avant merge. Le
[bilan MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6205715813)
du run #38828423500 tentative 1 constate collecte/publication réussies, puis
statut global en échec : `continuous_300s` et `inconclusive/protocol` après
181042 ms sans EOF ni reconnexion. Les deux scénarios ont tourné ; ce n'est pas
NOT RUN, et la cause précise reste inconnue. Le rapport v1 ne reçoit aucun
diagnostic rétrospectif. DEV ne publie aucune décision, ne réserve aucun claim
réel et ne lance aucun run. Le push après fusion reste
soumis aux contrôles installés, dont recheck, politique et approbation fraîche
si requise. La PR ouverte ou fusionnée ne prouve aucun résultat réel.
La tranche I exporte les seuls phase/catégorie/message/read_slot fermés du second
scénario : suite et second sous-rapport v2, premier sous-rapport v1 inchangé.
Les lecteurs Python/Node acceptent aussi l'ancien couple suite/second v1, sans
ajouter ni accepter silencieusement ces champs. Les catégories CloseClient/
DataUpdated/autre connu/inconnu désignent le seul octet de tête déjà refusé,
jamais un message complet ni un sous-code ; refus et retries restent identiques.
Limites d'export/publication inchangées. Les tests à trois lectures puis refus
vers 181 s sont synthétiques ; ils n'identifient pas la cause du run réel.
Aucune nouvelle validation réelle n'est autorisée par la tâche I ; ancien run et
claim restent consommés, sans rerun. Il faut le premier scénario admissible et
`recovered_120s` ; absence
d'EOF, scénario non exercé, résultat inconclusif ou échec bloquent l'étape 8.
EOF après inhibition n'établit pas sa cause ; `boundary_proven=false` demeure.
Aucune preuve de frontière OpenedClient ne découle des tests simulés du gate.

## Conception 7/8-K : quarantaine proposée, non installée

Le [bilan MANAGER J](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6207295244)
consigne le run #38839083483, tentative 1 sur le merge #97
`991fbb8aefb3e3df9c38cd0eed38944a03e88cc7` : collecte/publication réussies,
statut global failure ; 300 s continu, puis `inconclusive/protocol` à 181260 ms.
Le diagnostic v2 `message_classification/protocol/close_client`, `read_slot=3`,
identifie le refus d'un discriminant, pas un message complet ni un EOF ; aucun
EOF/reconnexion/stabilité observé. Les deux tests ont tourné, ce n'est pas NOT RUN.
Le rapport v1 précédent reste inchangé ; causalité serveur non démontrée.

Le [contrat proposé](session-eof-quarantine-proposal.md) étudie une coupure TX
atomique et une attente passive par le seul propriétaire RX, avec la borne L3
EOF ET réouverture avant T0+240, uniquement dans le second scénario après T0+120 et inhibition
effectivement exercée. Aucun Pong/lecture nouveau, aucune réinterprétation du
suffixe, aucun retry sur le seul discriminant. Seul un EOF transport admissible
avant arrêt local pourrait précéder une récupération par le lifecycle partagé.
Courses/TX en vol, silence, TLS sans EOF, dépassement et annulation échouent
fermés ; nettoyage local ne prouve jamais un EOF. Critères de succès et plafonds
360/600/1020 s inchangés. **PROPOSÉ / NON INSTALLÉ** : le comportement actif
reste le refus protocolaire et sa fermeture locale, sans retry protocolaire.

K ne modifie que la documentation et spécifie une matrice offline future. Toute
implémentation, adaptation de rapport/contrat/gate, installation et activation
éventuelles exigent des tâches/décisions MANAGER distinctes et des revues/CI
exactes. Aucun candidat ne s'autorise lui-même ; décisions immuables, approbations,
anti-rejeu et publication isolée conservés. Aucun run/décision/claim/rerun par DEV,
aucune réutilisation de l'ancien run/claim. Suite non validée, étape 8 suspendue.

L1 ne fournissait qu'une fondation pure non raccordée et ses tests unitaires.
L4 autorise uniquement son import par le pont privé défaut-off de V4Session,
jamais une activation par un consommateur ; aucun EOF réel ni gel TX live attesté.
Son candidat interne provisoire n'autorise aucun retry. La [portée isolée de L1](session-eof-quarantine-proposal.md#fondation-l1-isolée-api-et-limites)
ne change ni les gates/rapports ni le comportement installé ; intégration et
activation demeurent séparées, sans nouveau run/décision/claim par DEV.

## Préalable structurel L2 installé, fondation L3 sans raccordement

L1 est fusionnée par la PR #99 (`c220072d82ec9a34d178a3fa15406ea841ed527a`),
politique pure toujours non raccordée. L2 installe dans le workflow de suite le
job initial `quarantine-installation`, sans permission/checkout/action tierce/
environnement/secret : deux NOT RUN fixes, raison `quarantine_not_installed`,
puis échec inconditionnel (timeout du job : une minute). `dry-run` en dépend, avec ses
conditions et contrôles exacts conservés ; admission/réservation et accès aux
secrets restent inaccessibles après cet échec. Les deux scénarios sont bloqués
ensemble et aucune décision/commentaire ne peut lever ce préalable.

La PR #100 est fusionnée au SHA `ea08be522c73fcca742c4bacbeafa7df75e8b0c7`.
Le [bilan MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6209326192)
confirme le run #38859779145 tentative 1 : préalable failure attendu et tous les
jobs aval skipped, aucune collecte. Le verrou est installé et reste intact.
Le [plan](session-suite-plan.md) distingue tests locaux et preuve post-fusion.
Déclencheur push, nom/mutex/non-annulation,
autres jobs/conditions/permissions, gates/contrats, budgets, supervision et
publication/statut restent identiques. Aucun nouveau flag/input/bypass.
L2 ne modifie aucun runtime ni raccordement L1 ; le futur pont sera une tâche
distincte après vérification du verrou. Son retrait demandera une activation
séparée après installation/revue complète. Aucun nouveau résultat live acquis,
aucune décision/claim/rerun par DEV ; étape 8 suspendue.

L3 ajoute seulement la [fondation temporelle pure](session-eof-quarantine-proposal.md#contrat-temporel-l3-pur-sans-statut-de-réussite-réel)
non raccordée : T0 à l'acceptation stricte de la première génération du second
scénario, Pong normaux avant 120 s, inhibition dès 120, diagnostic futur dès 150,
EOF admissible ET nouvelle ouverture avant 240, puis 120 s stables sur la même
nouvelle génération avec Pong et lecture corrélée. Fin précoce permise ; 360 s
est le maximum fonctionnel nominal. EOF seul/ouverture tardive/seconde perte/
absence d'exercice/ambiguïté ou égalité de deadline ne donnent aucun succès.
La politique pure borne désormais à min(T0+240, observation, process, suite),
sans prolongation ni reset. Cette proposition remplace EOF T0+300/attente 180,
sans réécrire les runs ni modifier moteur/contrat actif. Premier scénario 300 s,
plafonds 360/600/1020, budgets 350+10/590+10, 3 ouvertures/1 Mio et 6/10 lectures >= 60 s
restent installés. Ouverture initiale/nettoyage sont séparés du temps fonctionnel
et sous ces bornes ; 120 s stables impossibles dans le budget => non concluant.
Un futur contrat d'admission versionné doit lier ces constantes avant usage :
anciennes approbations/claims/rapports ne valident pas ces sémantiques.

Observation renforcée future dès 150 s : temps relatifs, compteurs/tailles/offsets
bornés, état/motif/catégorie fermés au point de rejet et origine/absence EOF,
sans octets RX, hex/base64 de trame, sous-code deviné, données domestiques,
GUID, exception libre ou capture brute publique/privée autorisée. Clés/version/
matrice de cohérence Python/Node à spécifier avant toute instrumentation.
L3 n'a modifié aucun pont RX/TX/lifecycle, diagnostic 150 s ou rapport/validateur/
gate/runtime ; l'activation reste une tâche ultérieure distincte.

## Pont L4 livré, désactivé et sans raccordement consommateur

La PR #101 est fusionnée au SHA `11b2609ebd7a8f4abde46d8b0f94d8bc57ba0ce8` ;
le [bilan MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6209782800)
consigne quatre checks/3220 tests offline réussis et le run de push #38862945022
en échec attendu au verrou L2, tous les jobs aval skipped. L4 ne change pas ce
verrou ni son graphe, les deux NOT RUN avant secrets sont conservés.

Le [pont privé V4Session](session-eof-quarantine-proposal.md#pont-de-session-l4-livré-capacité-fermée-et-défaut-off)
est livré par #102 au SHA `4ebee209926ad9d24f6cb3cf3fab4e6a37ebdb2b`,
quatre checks/3294 tests offline réussis, [bilan MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6210627676).
Le run #38868819504 s'arrête au verrou L2, tous les jobs aval skipped.
Le pont reste défaut-off : capacité à usage
unique liée aux propriétaires EXACTS SessionReconnect/NoPongAfter120, avant
ouverture, deadlines scalaires bornées injectées. Seuls tests offline l'activent.
Garde sur l'unique import de politique par session, absence de tout constructeur/
appel consommateur fournissant la capacité ; aucun flag env/input/commentaire.
Rejet typé du seul discriminant close_client, sans décodage ou frontière nouvelle ;
latch sans await, gardes TX sous verrou et refus des TX engagées, signal waiter
privé sans close/replay, budget/session suspendus sans perte terminale précoce.
Le même RX poursuit TLS passivement sous la deadline L3, sans framer, capture,
replay ou double comptage. L'observation privée figée ne devient candidate que
sur vrai EOF avant arrêt local/deadline ; arrêt/courses/délai/budget/TLS sans
EOF échouent fermés. Annuler un observateur ne tue pas RX ; close/abort restent
idempotents. Sans capacité L5, même un candidat laisse le rejet protocolaire
non réessayable, sans reconnexion ou recovered_120s.

Lifecycle, clients/HA, collecteurs/lanceurs/superviseurs, rapports v1/v2 et
validateurs/export/publication, gates/contrats/workflows/budgets inchangés.
Aucune instrumentation 150 s, nouvelle donnée exportée ou capture brute autorisée.
Lifecycle/collecteur et contrats 150 s/rapports/admission versionnée exigent une
tranche séparée MANAGER, puis activation distincte revue. Aucun live/décision/
claim/rerun par DEV ; suite 7 non validée, étape 8 suspendue.

## Lifecycle L5 livré, défaut-off et sans collecteur actif

Le [lifecycle privé livré](session-eof-quarantine-proposal.md#lifecycle-l5-livré-consommation-liée-à-lorigine-et-récupération-bornée)
lie les propriétaires exacts SessionReconnect/NoPongAfter120 et les deadlines
L3 dans une capacité privée à usage unique. Seuls tests/factories de test la
fournissent ; session/lifecycle seuls portent les références revues, jamais les
clients/HA, collecteurs/launchers/workflows. Aucun env/input/commentaire d'activation.

Notification de quarantaine par événement local, sans autre lecteur ou polling
réseau ; état/snapshot non CONNECTED, wait_connected suspendu, requests sans
close/replay. Le lifecycle consomme une seule fois la preuve EOF courante liée à
la session/génération d'origine, encore candidate avant cleanup. Une copie
révoquée/périmée/doublée/fausse ne vaut pas preuve. L'origine et l'arrêt restent
recontrôlés avant/après cleanup et backoff, avant ouverture et adoption/publication d'une nouvelle acceptation. Le cleanup intentionnel ne masque aucun stop
public concurrent ; courses et annulations prioritaires, révocation au terminal.

La session fraîche réutilise seulement l'identité autorisée et les budgets/
compteurs/cadence partagés, jamais suffixe/waiter/future/transport ou lecture
rejouée. EOF ET acceptation avant T0+240 et 120 s encore possibles sous T0+360 et
observation/process/suite ; borne exacte refusée avant adoption. Timers privés
des phases, trois ouvertures au plus, Pong normaux rétablis ; toute perte après
la première nouvelle acceptation est terminale, même avant publication CONNECTED.
Sans capacité L5, comportements antérieurs inchangés et aucun retry protocolaire.

Fusionné par #103, livré défaut-off, sans consommateur actif.
Les tests sont synthétiques ; aucun rapport public ou nouveau recovered_120s.
Collecteur et contrats diagnostic 150 s/rapport/admission versionnée restent
séparés, puis activation/retrait du verrou après revue complète. Framer, protocole,
ouverture/identité/TLS/profils, clients/HA, collecteurs/lanceurs/superviseurs,
rapports v1/v2/validateurs/export, gates/contrats/workflows/budgets inchangés.
Verrou L2/deux NOT RUN avant secrets conservés, aucun diagnostic 150 s actif,
brut/live/décision/claim/rerun. Suite 7 non validée, étape 8 suspendue.

## Contrat L6 candidat, sans producteur v3

L5 est fusionnée par #103 au SHA `49d20ed62d2d1f15c09c4b8a873bf2b390fcebac`,
quatre checks/3350 tests offline/308 HA réussis. Le [bilan MANAGER L5](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6213829821)
confirme le run #38889510562 arrêté au verrou L2, sans collecte ni décision live.
L6 est fusionnée par #104, L6bis par #105 au SHA
`182daa62177c74bb14dc6412a166e95ad36c8350` : contrat de rapport suite/second v3,
avec validation et projection
Python/Node, fixtures communes, chronologie relative 120/150/240/360 et agrégat
RX fermé. Les couples historiques 1/1 et 2/2 restent strictement inchangés ;
les producteurs actifs continuent d'émettre v2. Premier sous-rapport v1,
provenance, 8192 octets/10924 base64, revalidation et publication isolée restent
requis. Contrat livré sans producteur v3 :
aucune instrumentation 150 s ni capacité fournie à un consommateur. Le reçu
valide à sa consommation ne vient jamais d'une copie finale révoquée. Collecteur,
instrumentation et admission versionnée demandent de nouvelles tranches, puis
activation distincte après revue/CI ; verrou et graphe inchangés. Suite 7 non
validée, étape 8 suspendue, aucun live/claim/décision/rerun par DEV.

La tranche L6ter est une correction contractuelle candidate, puis livrée après
revue/fusion MANAGER. Elle distingue les livraisons non vides first/last_rx des
décisions réelles de rejet/validation : le parsing peut suivre la dernière
livraison et référencer des octets conservés avant150, sans les recompter après.
Un refus antérieur150 peut être observé comme état, sans nouveau rejet inventé.
La cadence >=60s reste celle des requêtes ; aucune dernière livraison n'est
extrapolée de leur nombre. Offsets globaux bornés, génération/stabilité et tous
les critères EOF/reprise/arrêts L6bis restent requis. Voir le
[contrat normatif](session-suite-plan.md#agrégat-rx-fixe-à-partir-de-t0150000-ms).
Seuls validateurs/tests/docs changent ; aucun runtime, hook ou activation.
Le travail local L7 incomplet est préservé, non publié, suspendu jusqu'à fusion
L6ter et réautorisation distincte ; admission/routage fixe puis retrait du verrou
restent séparés. Aucune nouvelle preuve réelle ou frontière protocolaire.

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

La suite `session-suite` réutilise désormais ce même mécanisme H1/H2 : tentative
1 inchangée, décision v1 de suite avec ses scénarios/budgets fixes toujours
requise ; pour N>1, marqueur `<!-- hoben-session-suite-approval:v2 -->` et les
huit champs v2 du tableau ci-dessous, avec `scenario=session-suite`. Claims
par tentative, jobs courants/précédents, acteur de relance, recheck et approbation
fraîche restent identiques. Voir le [contrat de suite](session-suite-plan.md#relances-natives-de-la-suite--session-native-rerun-004).
Un run antérieur à l'installation de ce code, dont #40091399093, conserve son
ancien workflow lors d'un rerun ; aucune mise à niveau implicite ni nouvelle
validation réelle n'en découle.

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

## Modalités actuelles de lancement des agents

Voir [le workflow de coordination](manager-dev-workflow.md). Les mentions historiques « CODEX DEV » dans les cycles de développement expérimental décrivent le rôle DEV ; elles n'imposent plus son déclenchement automatique. MANAGER attribue une seule tâche à CHAT DEV (lancement manuel avec prompt fourni au propriétaire) ou exceptionnellement à CODEX DEV pour une complexité élevée, avec activation automatique explicite possible uniquement après autorisation du propriétaire et vérification de l'attribution. Les règles de revue du HEAD, quatre checks CI, gates live et branche `experimental` restent inchangées. L'Issue #112 conserve la référence technique V4 ; l'Issue #81 est historique et ne doit pas être réactivée automatiquement.
