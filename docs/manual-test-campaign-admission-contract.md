# Contrat offline d'admission des deux campagnes — #126

Tranche `HOBEN-126-ADMISSION-CONTRACT-003`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6435985641).
Base : `d58071fe4927e2dc9763821930227b24994fbb43`, après fusion de #135.
Les [deux formulaires](manual-test-campaign-shells.md) restent inertes ;
l'[inventaire](manual-test-campaign-inventory.md) reste la référence de périmètre.

## Portée et frontière de confiance

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

## Enveloppe fermée et relations vérifiées

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

## Responsabilités différées et limites

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

## Résultats et publication futurs

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
