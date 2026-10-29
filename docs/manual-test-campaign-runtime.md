# Deux campagnes manuelles — contrat d’exécution #126

Pour le choix des scénarios, le formulaire manuel et l’interprétation des
résultats, consulter le [guide utilisateur](manual-test-campaign-guide.md).
La consolidation 018+019 ajoute des résumés lisibles et exige toutes les
lectures planifiées réussies ainsi qu’une session encore active dans les
compléments HA ordinaires ; seule la reconnexion tolère une lecture échouée
avant récupération attestée. Elle préserve les plafonds ci-dessous.

Contrat courant : **HOBEN-126-EXPERIMENTAL-TEST-PARITY-027**, selon le
[commentaire MANAGER canonique](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6435985641)
et la décision propriétaire du **29/10/2026** dans #126. L’arbitrage est clos :
reconnexion expérimentale 600 s, parent all 3000 s ; les anciennes valeurs
480/2820 s sont historiques. Les plafonds nouveaux sont
des décisions de conception testées offline, sans validation réelle revendiquée.
Les plans 004/005 et contrats de preuve antérieurs restent des archives ; leurs
catalogues fermés sont réutilisés, leurs admissions historiques ne sont pas
raccordées à ces deux nouvelles voies.

## Admission et branches

[Protocole](../.github/workflows/hoben-protocol-manual.yml) et
[HA](../.github/workflows/hoben-ha-manual.yml) : uniquement workflow_dispatch,
dépôt exact, actor **et triggering_actor** Guillaume0385, refs natives
experimental/main, scénario allowlisté. Reruns autorisés. Aucun prérequis
PR/merge/revue/CI, comparaison de SHA d’admission, claim ou API GitHub.
Le parent répète les contrôles du contexte avant de lire l’identité.

`Use workflow from` choisit le YAML/code ; les checkouts utilisent github.sha,
sans substitution de branche. Cette PR concerne uniquement experimental.
Disponibilité du formulaire/main et politiques effectives d’environnement
ne sont pas attestées par les tests offline. Promotion main et tout lancement
réel nécessitent une autorisation distincte.

Trois jobs : admission sans checkout/secret ; collect protégé par
hoben-experimental ou hoben-live ; result sur un nouveau runner sans
environnement ni secret Hoben. Collect et result ont seulement contents:read.
Les approbations/attentes natives configurées restent obligatoires, sans bypass
ni modification de Settings. Mutex commun hoben-read-only-observation,
cancel-in-progress=false, queue=max, identique au workflow historique inchangé.

## Protocole

| Scénario | Plafond absolu, cleanup compris | Opérations et preuve |
| --- | --- | --- |
| tls-only | 15 s | TLS système vérifié vers myhoben.fr:465, aucun message applicatif. |
| session-open | 30 s | Une ouverture V4 avec l’identité initiale documentée, aucune lecture Modbus ni association. |
| read-v4-state | 45 s | Une ouverture et lecture V4 de 20 registres fixes, valeurs jetées. |
| h1h2 | 1800 s | Collecteur historique : 6 H1 + 6 H2, 90 s et 1 Mio RX par session. Rapport complet borné INCONCLUSIVE, aucune frontière universelle prouvée. |
| session-300 | 360 s | Observation existante : 300 s utiles, trois ouvertures, six lectures maximum espacées d’au moins 60 s, 1 Mio RX total, Ping/Pong et réponse corrélée. |
| session-reconnect | 600 s | Collecteur historique et NoPongAfter120 : inhibition des seuls Pong du client de test dès T0+120 s sur la première génération. Perte puis réouverture avant T0+240 s, lecture corrélée, Pong rétablis et 120 s stables sur la même génération ; trois ouvertures, dix lectures maximum à cadence >=60 s, 1 Mio RX total. |
| all | 3000 s | Six scénarios dans l’ordre du formulaire, indépendants et séquentiels ; maxima individuels 2850 s, marge 150 s, orchestration et cleanup inclus. |

TLS et ouverture réutilisent AsyncTlsTransport/V4Lifecycle/V4Session ; la session
300 réutilise son observateur et ses budgets. H1/H2 réutilise boundary_capture,
ses protections et son calendrier sans changer ses hypothèses historiques.
Le rapport de campagne en projette seulement les compteurs nécessaires ; les
chronologies privées ne sont pas publiées par cette voie.
Les compteurs Ping/Pong non mesurés dans ce résumé H1/H2 restent null.

T0 est la première ouverture strictement acceptée, pas le lancement du processus.
La politique cesse uniquement de répondre aux Ping par des Pong du client de
**test expérimental**, puis rétablit les Pong sur une nouvelle génération. Elle
n'envoie aucune commande au serveur/poêle, ne ferme pas un transport pour
fabriquer une perte et ne prétend pas prouver une causalité serveur. La voie HA
naturelle et ses limites restent distinctes et inchangées.

### Correspondance des collecteurs et preuve

| Étape actuelle | Référence historique réutilisée | Orchestration / contrat |
| --- | --- | --- |
| session-300 | [run_session_300.py:observe](../scripts/run_session_300.py) | [protocol_campaign_collect.py:collect](../scripts/protocol_campaign_collect.py), vrai V4Lifecycle/V4Session et Session300 ; 300 s utiles, plafond 360 s. |
| session-reconnect | [session_suite.py:_observe_reconnect](../scripts/session_suite.py) et [NoPongAfter120](../custom_components/hoben/v4_no_pong.py) | Même propriétaire partagé, SessionReconnect, trois ouvertures maximum ; fenêtre fonctionnelle historique de 360 s, plafond absolu 600 s. Aucun appel à observe_natural(). |
| h1h2 | [boundary_capture.py:run_campaign](../scripts/boundary_capture.py) | Douze captures privées et nettoyage historiques inchangés ; plafond 1800 s. |
| all / isolement | [run_campaign.py:run/execute](../scripts/run_campaign.py) | ACK après armement de la deadline, min(deadline parent, deadline étape), cleanup/reaping avant la suivante ; parent 3000 s et formulaire workflow_dispatch uniquement. |
| Projection / publication | [contrat Python](../scripts/campaign_runtime_contract.py) et [validation Node](../.github/scripts/campaign-report.cjs) | Deux validations indépendantes, données fermées, bornes individuelles/globales et interprétation explicite du résultat. |

Le collecteur de reconnexion conserve par défaut sa validation historique.
Son projecteur privé permet au worker actuel d'utiliser le résultat existant
sans fabriquer des anciennes preuves PR/merge : la véritable provenance de la
campagne est ajoutée par son parent admis. Les temps et générations sont figés
**au moment de la décision, avant cleanup**, qui invalide ensuite ces états.
Les deux collecteurs historiques possèdent leur teardown ; le wrapper ne leur
accorde pas un deuxième délai de nettoyage.

Le témoin public porte le mode fermé `pong_inhibition_after_120s`, le résultat
catégoriel, `boundary_proven=false`, les générations expérimentales, le nombre
de lectures corrélées sur la génération reprise, les compteurs de Pong inhibés/
rétablis et les instants relatifs de perte/réouverture. SUCCESS exige une
inhibition réellement exercée, une perte après au moins 120 s, réouverture
strictement avant 240 s, 120 s stables, une lecture corrélée et un Pong après
reprise. Une nouvelle ouverture seule, un job fini, une perte précoce ou une
exception TLS sans EOF/CloseClient observable ne suffisent pas.

Sans inhibition/perte/récupération attestée : INCONCLUSIVE. Timeout, dépassement
de budget, protocole refusé ou cleanup échoué : FAILURE. Une étape non commencée
reste NOT RUN ; le parent interdit tout ACK ultérieur après échec ou échéance.
Les anciens témoins incomplets restent lisibles mais ne peuvent pas revendiquer
le succès du nouveau contrat sans preuves d'inhibition et de temporalité.
`transport` ne prouve ni EOF TLS ni cause serveur ; CloseClient conserve sa
catégorie et son sous-code. Les 48 octets d'OpenedClient restent un préfixe,
jamais une longueur totale universelle. Aucun RX brut, identifiant, registre,
valeur domestique ou texte d'exception libre n'est ajouté au rapport.

Validation uniquement hors ligne : horloges/transports synthétiques, maintien
300 s, inhibition à 120 s, récupération/stabilité, cas sans perte/Pong, annulation,
cleanup, deadlines et rejets Python/Node de preuves falsifiées. **Tests réels :
NOT RUN.** La livraison n'autorise aucun dispatch ou rerun réel.

## Home Assistant

| Scénario | Plafond absolu, cleanup compris | Observation |
| --- | --- | --- |
| hoben-live | 360 s | Socle #112 inchangé : 300 s utiles monotones, collecte 330 s, six refreshs, deux ouvertures, preuve finale de continuité. |
| open-errors | 90 s | Premier refresh du vrai coordinator et catégorie de son éventuelle erreur ; aucun credential volontairement invalide. |
| refresh-v4 | 120 s | Deux refreshs et nouveaux objets HobenCoordinatorData issus du décodage V4. |
| session-reuse | 180 s | Trois refreshs, même génération et séquences corrélées successives. |
| session-reconnect | 600 s | Six refreshs maximum ; perte naturelle, cleanup de l’ancienne génération et nouvelle lecture corrélée. Arrêt après récupération prouvée, sinon observation bornée puis INCONCLUSIVE. |
| cleanup | 60 s | Ouverture/lecture puis fermeture effective, état arrêté et génération nettoyée. |
| availability | 120 s | Deux refreshs, état last_update_success/data du vrai coordinator et catégories d’erreur ; aucune disponibilité fictive. |
| all | 1800 s | Sept exécutions indépendantes, cleanup entre elles ; maxima individuels 1530 s, marge 270 s. |

Les compléments ont six refreshs et deux ouvertures maximum. L’arbitrage permet
jusqu’à trois ouvertures pour la reconnexion HA ; le vrai HobenClient conserve
sa limite actuelle plus restrictive de **deux**, sans modifier son API. All
vérifie aussi les plafonds globaux de 15 ouvertures et 42 refreshs.

Le worker réutilise collect() de #112 : véritables HomeAssistant/ConfigEntry,
HobenClient persistant et HobenDataUpdateCoordinator, persistance privée du
DeviceGuid, fermeture du client et arrêt de HA. L’observateur #112 reste l’unique
implémentation de la preuve hoben-live 300 s. Les nouveaux observateurs utilisent
les mêmes objets ; aucun client ou coordinator de remplacement en exécution.
Les données/snapshots domestiques ne sont jamais projetés.

Les cas négatifs et la gestion des erreurs sont vérifiés avec de vrais objets
HA sur transports **simulés** offline. Un succès réel d’open-errors atteste une
ouverture/lecture réussie, pas une erreur d’authentification qui ne serait pas
survenue. Une erreur rencontrée est publiée sous une catégorie fermée et donne
FAILURE. La disponibilité décrite est celle du coordinator, contrat utilisé
par les entités existantes ; aucune campagne ne fabrique une panne pour tester
un changement de disponibilité.

Le superviseur/gardien C2a commun impose **1 Gio mémoire agrégée**, swap nul,
**128 PID/threads**, namespace privé, rootfs/code en lecture seule, tmpfs borné,
worker sans capacités sous UID/GID 65534 et logs Docker désactivés. Les plafonds
ne sont pas additionnés simultanément entre scénarios. Les délais sont armés
avant les appels Docker et le démarrage ; chaque appel consomme le délai
original, transmis au gardien. Les modes historiques restent limités à 360 s ;
seul le nouveau mode fermé de reconnexion HA accepte 600 s.
Le champ useful_ms du superviseur reste 300000 pour hoben-live et null pour
les compléments, qui n’ont pas de fenêtre utile minimale imposée. Aucune durée
fictive ne remplace cette absence de minimum.

**Aucun quota, compteur ou proxy RX HA.** Les champs réservés aux mesures
protocolaires sont null dans les métriques HA. Les ouvertures/lectures sont
des témoins typés publics du client réel, avec plafond courant de deux tentatives
et six lectures ; une génération seule ne prouve pas une réponse corrélée.

## Supervision, données privées et rapports

run_campaign.py possède les deadlines monotones par scénario et du parent,
arme avant ACK, puis réape le groupe avant toute étape suivante. Les identités
ne vont au worker que par pipe ; aucun token GitHub/Actions/OIDC, fichier de
commande Actions, secret en argv, Docker Env ou journal privé n’est transmis.
Les deux campagnes ne demandent que le secret `HOBEN_USER_GUID`, validé et
normalisé avant collecte. `HOBEN_DEVICE_GUID` n’est plus un secret d’entrée,
n’est ni lu ni injecté par ces workflows. Le pipe privé conserve sa structure :
le DeviceGuid de départ est exclusivement `INITIAL_DEVICE_GUID` (32 zéros),
valeur normale documentée dans protocol.md §4, jamais une identité attribuée
fabriquée. Le gestionnaire partagé/le vrai client HA adopte le DeviceGuid d’un
OpenedClient valide et le réutilise dans la session ; H1/H2 conserve également
son mécanisme existant de réutilisation entre captures. Aucun GUID n’est exporté.
Un utilisateur absent/invalide reste refusé ; un défi d’autorisation ne provoque
aucune association ni envoi de code. L’ancien point d’entrée #112 conserve son
exigence d’identité persistée ; seule l’entrée des nouvelles campagnes accepte
la valeur initiale documentée. Cette correction locale ne prouve aucun succès
d’ouverture réel ni panne TLS/serveur dans le run #40768329824.

Pour H1/H2, le parent possède le dossier privé 0700 et le supprime après
réapage, y compris si le worker a été tué avant son finally. Les captures et
identités ne quittent jamais collect. En HA, identité via stdin/pipe privé,
configuration dans le tmpfs du cgroup ; le gardien termine le namespace même
si l’observateur hôte disparaît. Absence de contrôle mémoire/PID, configuration
Docker divergente, reçu absent ou mode erroné : refus, sans repli sur l’hôte.

Le JSON fermé contient ref/SHA/run_id/run_attempt **informatifs**, statuts par
scénario, compteurs, booléens et catégories allowlistées, détail HA de 8192 octets
maximum, histogrammes protocolaires 07/1B si observés et sous-code CloseClient
numérique. Aucun GUID, RX brut, registre, valeur domestique ou exception libre.
Enveloppe totale **64 Kio**, donc base64 inférieur à 88 Kio pour le transfert
par sortie/env Actions ; fichiers/symlinks/taille/JSON canonique vérifiés.

Projection Python puis validation Node indépendante avant transfert, et de
nouveau sur le runner result. Les métriques HA sont recalculées depuis les
témoins, et les statuts depuis les critères. Horloge synthétique ne vaut pas
preuve live. La provenance ancienne PR/merge n’est jamais fabriquée pour
satisfaire un validateur historique ; ses seules vérifications logiques sont
partagées avec les nouveaux rapports.

Le parent marque collection_result=pending. Result remplace cet état par le
résultat effectif du job collect et recalcule le verdict : un job échoué ou
annulé ne produit aucun artefact global SUCCESS, même si certaines étapes sont
positivement attestées. Rapport absent/invalide : NOT RUN par scénario et
FAILURE global, aucun upload. NOT RUN signifie absence de preuve suffisante,
pas preuve qu’aucune tentative réseau n’a pu exister.

La correction 022 distingue les refus du parent avant worker par une projection
fermée : `context_refused`, `identity_refused`, `worker_failure`,
`report_refused`. Seul le nom de catégorie est émis dans une annotation d’erreur,
jamais l’exception, les entrées, des caractéristiques d’identité (présence,
taille, hash, préfixe), l’environnement ou un RX. Le code de sortie reste 1.
Ces catégories identifient une phase locale, pas une cause distante Hoben.

Après contexte entièrement validé et création exclusive du dossier privé,
un échec de préparation produit si possible le même schéma de rapport fermé :
première étape NOT RUN avec catégorie, suivantes NOT RUN / previous_failure,
aucune observation, compteurs nuls/non mesurés et cleanup non attesté.
`collection_result=failure`, `actions_result=FAILURE`. La provenance Actions
informative existante reste la seule métadonnée ; aucune empreinte d’identité.
Ce rapport passe les validateurs Python/Node existants ; prepare reste exécuté
avec `always()` et result peut publier le diagnostic validé sur son runner
sans secrets, avec verdict global FAILURE et rétention inchangée de sept jours.

Contexte non vérifiable, dossier existant/symlink, écriture impossible ou entrée
déjà effectuée dans run() : aucun nouveau reçu pré-worker n’est fabriqué.
Un rapport absent/invalide conserve le refus de publication existant. Aucune
identité n’est réparée, aucun format n’est assoupli et aucun retry live ajouté.
Une allocation partielle de pipes est nettoyée avant le retour du parent.

Les quatre runs réels #40705976259, #40706002568, #40706104688 et #40706130906
sur ef0b7c6 ont admission SUCCESS, capture/prepare/result FAILURE, sans artefact
ni motif catégoriel exploitable. Les tests synthétiques reproduisent l’absence
antérieure de rapport/diagnostic sur refus de préparation, ainsi qu’une fuite
de descripteurs sur échec d’allocation ; ils **n’établissent pas la cause réelle**
de ces quatre runs. La validation d’identité demeure une hypothèse. Aucun test
réel, dispatch ou rerun n’est lancé par cette correction ; la prochaine
validation réelle exige toujours une autorisation distincte du propriétaire.

H1/H2 complet INCONCLUSIVE et reconnexion non observée INCONCLUSIVE peuvent
laisser continuer all si collection/cleanup sont attestés. FAILURE, NOT RUN,
dépassement ou cleanup manquant arrêtent la suite ; étapes restantes NOT RUN.
Le résultat global est SUCCESS uniquement si chaque étape est SUCCESS et le
job collect a réussi. Ainsi all protocole reste globalement FAILURE tant que
H1/H2 reste scientifiquement INCONCLUSIVE ; une collecte complète n’est pas une
validation de framing. Rapport JSON seul, rétention sept jours, runner sans
environnement Hoben ; aucun upload depuis collect.

## Validation et limites de livraison

Tests déterministes des contrôleurs réellement embarqués, refus/reruns,
scénarios individuels/all, fragmentation/coalescence/Ping/CloseClient, absence
de perte, récupération, perte tardive, annulation, limites, processus résistant,
réapage, suppression privée et publication. Vrai runtime HA sur peers simulés.
Tests C2a de namespace/mémoire/PID toujours network=none ; modes de campagne
testés par moteurs Docker injectés, jamais par une connexion Hoben réelle.

Les quatre checks CI tests/ha-tests/hacs/hassfest restent obligatoires sur le
HEAD de la PR. Cette livraison ne lance aucun dispatch/rerun, claim, approbation,
test réel, commande poêle ou écriture Modbus 06/16/22 et ne fusionne rien.
Les tests offline ne prouvent ni la disponibilité UI/main, ni une politique
d’environnement effective, ni la tolérance réelle du serveur aux campagnes.
Le workflow historique hoben-manual.yml reste inchangé et dans le même mutex.
