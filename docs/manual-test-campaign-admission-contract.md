# Admission minimale des deux campagnes — #126

## Contrat courant — HOBEN-126-CAMPAIGNS-016-017

Les deux workflows ont trois jobs admission → collect → result. Le
[contrat runtime](manual-test-campaign-runtime.md) détaille les scénarios,
les budgets explicites arbitrés le 27/10/2026, les rapports et leurs limites.
Admission minimale inchangée : workflow_dispatch, acteur/triggering_actor
propriétaire, refs natives experimental/main et choix fermé ; reruns autorisés,
sans prérequis PR/fusion/revue/CI/comparaison SHA/claim. collector_ready suit
le catalogue fermé implémenté, avec refus pour toute entrée inconnue.

Collect conserve l’environnement hoben-experimental/hoben-live, les approbations
natives et le mutex commun. Seule sa dernière phase reçoit les identités ;
aucun secret dans admission ou result. Checkouts sur github.sha du run, sans
substitution de branche. Publication JSON fermée sur un runner distinct ;
rapport absent/invalide ou étape non attestée donne NOT RUN/FAILURE.
Aucun test réel ou promotion main n’est autorisé par cette préparation.

Les contrôleurs 014 restent archivés byte-identiques dans
tests/fixtures/campaign_admission_014 ; leurs régressions sont conservées.
Les tests runtime/publication vérifient les contrôleurs et raccordements actuels.
Les modèles de preuve et anciens shells restent historiques et non raccordés.

## Historique — admission et points d’insertion 014+015

### Contrat courant — étapes 014 et 015 regroupées

Décision propriétaire du 27/10/2026 et
[consigne canonique](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6435985641),
TASK_ID HOBEN-126-WORKFLOW-ADMISSION-014 ; base experimental
`59bb0177fc686a1e420b2f00a8fb12aef0b435a4`.

Ce contrat remplace, pour les deux nouvelles campagnes, les conditions
d'admission strictes développées précédemment. Cinq arbitrages prioritaires :

1. Sélection native **experimental et main**, avec refs exactement
   refs/heads/experimental ou refs/heads/main ; aucun input libre de branche.
2. Lancement après **tout commit de la branche choisie**, même documentaire ;
   aucune PR ou fusion préalable nécessaire.
3. **Aucune revue MANAGER préalable au lancement**. Les quatre CI restent
   obligatoires pour développer/revoir/fusionner une PR, pas pour lancer un run.
4. **Aucune comparaison de SHA PR/merge/arbre/branche ou preuve de provenance
   cryptographique supplémentaire** à l'admission.
5. **Rerun/rejeu manuel autorisé**, sans filtre run_attempt ni claim anti-rejeu
   personnalisé. L'acteur qui relance doit lui aussi être autorisé.

#### Contrôles effectivement raccordés

Les deux YAML [protocol](../.github/workflows/hoben-protocol-manual.yml) et
[HA](../.github/workflows/hoben-ha-manual.yml) définissent trois jobs :
admission, scenario-slot, result. Le contrôleur Node embarqué dans admission
lit uniquement les métadonnées du contexte natif GitHub, sans interpolation
de ces entrées dans du code/shell, API, checkout ou secret. Acteur/ref/événement
viennent du contexte env ; le scénario vient du fichier GITHUB_EVENT_PATH natif,
borné à 256 Kio de métadonnées GitHub avant parsing. Une valeur de scénario
inconnue n'est ainsi pas développée dans l'env du step affiché par Actions.

Il exige le dépôt exact Guillaume0385/ha-hoben-community, workflow_dispatch,
actor **et triggering_actor** exactement Guillaume0385, une des deux refs,
et un scénario fermé de la campagne. Valeur absente/inconnue : refus.
Une admission conforme produit admitted=true ; cela atteste seulement ces
contrôles de contexte. Les contrôleurs ne consultent jamais PR, revues, CI,
commit/SHA, registre Actions ou les anciens modèles d'admission.

Le groupe de concurrence workflow est **hoben-read-only-observation**, commun
aux deux campagnes et au workflow historique : cancel-in-progress=false,
queue=max. Aucun run actif/pending n'est annulé pour libérer la place. Cette
concurrence native ne constitue pas une preuve d'exclusion contre une voie
qui ne participerait pas au groupe ; le workflow historique est inchangé.

#### Environnements et absence actuelle de collecteur

scenario-slot dépend du succès d'admission, de admitted=true **et**
collector_ready=true. Ce dernier output est fixé à **false** dans cette PR,
pour tous les scénarios, y compris all. Ce verrou d'implémentation est distinct
de l'admission fonctionnelle. Le point d'insertion garde lui-même un refus
explicite NOT RUN / exit 1 ; aucun collecteur, client ou réseau Hoben n'y est
raccordé.

Seul ce job futur porte l'environnement fixe **hoben-experimental** pour
protocol ou **hoben-live** pour HA. Les approbations/attentes configurées dans
GitHub restent à satisfaire avant l'exécution de ce job ; aucune auto-approbation,
requête de bypass ou modification de Settings n'existe. Puisque le job est
actuellement ignoré avant cette étape, un simple refus inerte ne demande
**aucune approbation d'environnement**. admission et result n'ont ni
environnement ni secret. Les politiques effectives ne sont pas attestées par
les tests offline ; leur configuration devra être applicable aux deux branches
avant tout futur lancement réel.

Les permissions workflow/jobs sont toutes {}. Aucun checkout n'est ajouté :
le code de contrôle provient du YAML choisi par Use workflow from, sans
substitution d'une autre branche. La présence/formulaire sur main n'est pas
démontrée par ce développement ; une promotion distincte reste à autoriser.
Les runtimes de contrôle et le stub sont bornés à une minute ; ce ne sont pas
des budgets de collecteurs et aucun plafond H1/H2/session/HA n'est modifié.

#### Résultats et confidentialité

result utilise always() après admission et scenario-slot, sans environnement.
Il revalide la sélection depuis une allowlist, puis émet uniquement des noms
fermés, NOT RUN et des causes catégorielles : collector_not_connected ou
admission_not_verified. Une sélection inconnue n'est jamais recopiée. Pour all,
tous les points d'insertion individuels sont affichés comme NOT RUN ; cette
liste n'exécute ni ne modifie les plans/runtimes historiques.

Même quand le contrôle d'admission réussit, le résultat global et le job result
restent **FAILURE**, execution=NOT RUN ; aucune observation INCONCLUSIVE ou
réussite de scénario n'est inventée. Aucun stdout/stderr privé, secret, GUID,
RX, exception libre ou valeur domestique n'est publié. Les sorties GitHub et
résumés ne contiennent que ces catégories et scénarios publics.

Les [tests offline](../tests/test_campaign_minimal_admission.py) exécutent les
contrôleurs réellement embarqués avec un contexte synthétique, sans Actions,
réseau ou collecteur : acteurs/branches/événements/scénarios, main/experimental,
reruns, absence de PR/revue/CI/SHA, concurrence, environnement conditionnel,
confidentialité et bilans d'échec. La suite 013 reste couverte par ses fixtures
historiques. Les collecteurs/raccordements fonctionnels et tests réels restent
des tâches ultérieures ; aucun dispatch/rerun DEV ni PR main dans cette tâche.

### Historique — contrat strict 003, non raccordé et non bloquant

Le modèle Python et le texte ci-dessous sont conservés pour la traçabilité.
Leurs restrictions PR/revue/SHA/CI, main/rerun/claim ne s'appliquent **pas** à
l'admission minimale courante ; ils ne doivent pas y être branchés.

#### Contrat offline 003 d'origine

Tranche `HOBEN-126-ADMISSION-CONTRACT-003`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6435985641).
Base : `d58071fe4927e2dc9763821930227b24994fbb43`, après fusion de #135.
Les [deux formulaires](manual-test-campaign-shells.md) restent inertes ;
l'[inventaire](manual-test-campaign-inventory.md) reste la référence de périmètre.

#### Historique — portée et frontière de confiance

[manual_campaign_contract.py](../scripts/manual_campaign_contract.py) est un
**modèle pur non branché** : aucun lecteur GitHub, réseau, environnement,
secret, collecteur, écriture de claim ou acquisition de mutex. Il n'importe
aucun gate ni module de l'intégration. Les seules entrées sont des instantanés
normalisés de fixtures dans les [tests](../tests/test_manual_campaign_contract.py).
Le workflow live, ses gates/claims/budgets, les deux shells et les schémas de
rapports existants sont inchangés.

Les champs attested/exclusive/manager_reviewed ne sont **pas authentifiés par
ce module**. Ils décrivent des faits qu'un futur adaptateur devra obtenir de
sources indépendantes, complètes et authentifiées. Une valeur true fournie par
un appelant n'est pas une preuve GitHub. Les tests synthétiques modélisent ces
faits ; ils ne valident aucun déploiement, environnement ou observation réels.
Le SHA-256 de liaison est une empreinte de cohérence, pas une signature.

`assess_admission(snapshot)` modélise l'état **après** réservation atomique et
approbations requises, déjà attestées par hypothèse. Il ne réalise pas le
préflight, l'attente d'approbation ou la réservation. `assess_recheck(model,
snapshot)` relit les mêmes faits dans un nouvel instantané, après approbations
et juste avant tout accès futur aux secrets. L'objet figé conserve seulement
des empreintes/identifiants opaques et l'instant de lecture, sans références
mutables vers les entrées. Une modification ultérieure de l'entrée initiale
ne réécrit pas l'état mémorisé.

**Tout résultat reste execution=NOT RUN et actions_result=FAILURE**, même si
consistent=true/coherent_offline. Sa conversion booléenne vaut toujours false.
L'exécution directe du fichier est refusée avec code 1 sans sortie ; aucune
CLI d'admission n'existe. Le modèle n'est ni un permis ni un rapport live.
Le brancher à une décision d'accès aux secrets est exclu de cette tranche.

#### Historique — enveloppe fermée et relations vérifiées

Chaque clé est obligatoire ; clé inconnue, null inattendu, type approximatif
(dont booléen à la place d'un entier), preuve non attestée ou incohérence : refus.
Les erreurs sont uniquement catégorielles, sans reprendre les entrées ni les
exceptions. Les champs exacts sont allowlistés dans le module et les fixtures.

| Bloc | Contrat normalisé |
| --- | --- |
| Racine | schema=1 local au modèle, campaign, observed_ms et les huit blocs ci-dessous. observed_ms est un entier UTC en millisecondes fourni par le lecteur, jamais une horloge lue ici. |
| dispatch | Dépôt et ID exacts, propriétaire/actor/triggering_actor et IDs exacts, workflow_dispatch, tentative 1, run/scénario fermés. Ref **experimental seulement** ; SHA du run/workflow identiques, workflow_ref complet concordant. L'attestation couvre aussi sender, contexte runner et provenance API concordants. |
| branch | HEAD protégé courant au SHA dispatché ; preuve attestée, pas une déduction de la politique d'environnement. |
| pr | Une seule PR liée, fusionnée par le propriétaire vers experimental, même dépôt source/base, non draft, merge SHA dispatché, candidat et arbres candidat/merge identiques ; fusion antérieure au dispatch. |
| review | Revue MANAGER attestée au candidat exact, aucune demande de changements active ni thread ouvert. manager_reviewed représente la revue de code, jamais un nouveau commentaire d'admission live ; aucun auto-APPROVED GitHub fictif. |
| ci | Validate pull_request, tentative 1, même candidat/branche/PR/dépôt et workflow exact. Quatre jobs uniques tests/ha-tests/hacs/hassfest completed/success au candidat ; CI terminée avant fusion. Aucune déduction depuis le seul statut global. |
| environment | Nom/ID et empreinte complète de politique, mode reconnu, règles connues, branche autorisée et preuve attestée. Le mode experimental_only représente la règle personnalisée exacte experimental ; protected_branches est permis pour HA seulement, avec la preuve branch ci-dessus. |
| claim | Reçu hypothétique de création exclusive pour ce run, non rejoué, attestation complète, objet Git immuable et liaison exacte à l'empreinte. Aucune réservation/consommation réelle ne se produit ici. |
| concurrency | Groupe commun hoben-read-only-observation, propriété exclusive pour ce run et scan complet attestés, aucune autre observation active. Ces assertions ne créent aucun verrou. |

| Campagne | Workflow exact | Environnement | Scénarios |
| --- | --- | --- | --- |
| protocol | .github/workflows/hoben-protocol-manual.yml | hoben-experimental | tls-only, session-open, read-v4-state, h1h2, session-300, session-reconnect, all. |
| ha | .github/workflows/hoben-ha-manual.yml | hoben-live | hoben-live, open-errors, refresh-v4, session-reuse, session-reconnect, cleanup, availability, all. |

main est refusée **inconditionnellement** dans cette version. Aucun champ
promotion_verified/main_authorized ni argument d'activation n'est accepté.
La publication/autorisation/provenance de promotion et la route de revue main
nécessiteront une décision et une version de contrat distinctes ; changer un
ref ou recopier un fichier ne les établit pas.

Si approval_required=true, le bloc approval doit attester un état approved,
indépendant, lié au run et à l'ID d'environnement, daté entre le début du
dispatch et la lecture. Approval absent, périmé, futur ou lié à l'autre
environnement : refus. Si false, approval doit être null **et** l'absence
d'approbation obligatoire doit elle-même être attestée dans la politique.
Une règle inconnue ou un endpoint inaccessible ne devient jamais false.

La liaison est SHA-256 du JSON canonique de tous les blocs sauf claim et
observed_ms : clés triées, séparateurs compacts, ASCII échappé, aucun NaN.
Les jobs CI sont triés par name après vérification de leur unicité.
Le recheck exige une lecture strictement ultérieure et la même liaison ainsi
que le même objet claim. Changement de workflow/ref/SHA/scénario, PR/CI/revue,
politique/approbation, mutex ou claim : refus, même si le nouvel instantané pris
isolément est cohérent. Un état relu ne prolonge aucun budget.

#### Historique — responsabilités différées et limites

Un futur adaptateur devra vérifier les réponses GitHub complètes, pagination,
identités et dates, associations PR/CI, cardinalité des jobs et dernières revues,
politique/règles/reviewers/wait timer/bypass effectifs, approbation indépendante
fraîche et objet réel du claim. Il ne pourra pas construire ces attestations
depuis les inputs du dispatch, des valeurs par défaut ou un simple booléen.
Le modèle ne remplace pas ces lectures et n'importe pas les anciens gates pour
simuler une vérification réelle. Les helpers actuels pertinents sont
[manual-hoben-gate.cjs](../.github/scripts/manual-hoben-gate.cjs),
[experimental-lab-gate.cjs](../.github/scripts/experimental-lab-gate.cjs) et
[experimental-live-gate.cjs](../.github/scripts/experimental-live-gate.cjs) ;
aucune de leurs fonctions n'est modifiée ou appelée ici.

La vraie réservation devra être atomique, liée à campagne/workflow/ref/SHA/
environnement/scénario/run/tentative, relue puis conservée après échec/annulation.
Une collision ou un rerun refuse. Un validateur pur ne mémorise pas globalement
les appels : répéter une fixture identique ne détecte pas un replay réel.
Les refus de replay du modèle reposent sur le reçu externe attesté, les liaisons
et la tentative ; aucune garantie globale d'anti-rejeu n'est revendiquée.

Le mutex doit être partagé par les deux workflows futurs et les observations
historiques. Le scan API seul n'est pas une exclusion atomique contre une voie
hors mutex ; configurations et traces incomplètes restent des refus.
Les faits normalisés devront être relus après approbations et avant secrets,
sans transporter de token GitHub/Actions/OIDC vers les collecteurs.

Use workflow from reste natif. Les formulaires/inputs selon la branche et la
présence sur la branche par défaut ne sont pas attestés par cet exercice.
Si une publication main s'avère nécessaire : STOP et demande propriétaire
distincte, aucune PR main automatique, API/CLI de contournement ou checkout
substitué. Aucune vérification UI, dispatch ou test réel dans cette tranche.

#### Historique — résultats et publication futurs

Le refus d'admission ou l'absence de preuve donne **NOT RUN / FAILURE Actions**,
jamais une réussite protocolaire. Après une collecte autorisée distinctement,
SUCCESS exigera les critères du scénario attestés ; FAILURE une erreur ou un
contrat non respecté ; INCONCLUSIVE une observation recevable mais insuffisante ;
NOT RUN une étape non commencée ou non attestée. Une collecte H1/H2 complète
peut rester INCONCLUSIVE. Un job échoué ne prouve ni absence de connexion ni
observation INCONCLUSIVE ; les étapes suivantes ne deviennent pas des succès.

Seules des projections fermées, allowlistées, bornées et validées indépendamment
pourront être publiées sur un runner sans secret, à rétention courte (7 jours
au plus), liées à campagne/scénario/ref/SHA/provenance. Aucun instantané interne,
GUID, secret, RX brut, valeur domestique ou exception libre exporté. Les schémas
existants restent inchangés ; aucun nouvel exporteur/rapport live n'est ajouté.
EOF, CloseClient et arrêt local restent distincts ; 48 octets ne prouvent pas
une longueur universelle d'OpenedClient. Lecture seule/TLS vérifié et budgets
existants sont conservés, sans nouvelle capacité de collecte.
