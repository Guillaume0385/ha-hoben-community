# Deux campagnes manuelles — contrat d’exécution #126

Pour le choix des scénarios, le formulaire manuel et l’interprétation des
résultats, consulter le [guide utilisateur](manual-test-campaign-guide.md).
La consolidation 018+019 ajoute des résumés lisibles et exige toutes les
lectures planifiées réussies ainsi qu’une session encore active dans les
compléments HA ordinaires ; seule la reconnexion tolère une lecture échouée
avant récupération attestée. Elle préserve les plafonds ci-dessous.

Tâche HOBEN-126-CAMPAIGNS-016-017, selon le
[commentaire MANAGER canonique](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6435985641)
et l’arbitrage des budgets du 27/10/2026 dans #126. Les plafonds nouveaux sont
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
| session-open | 30 s | Une ouverture V4 avec identité persistée, aucune lecture Modbus. |
| read-v4-state | 45 s | Une ouverture et lecture V4 de 20 registres fixes, valeurs jetées. |
| h1h2 | 1800 s | Collecteur historique : 6 H1 + 6 H2, 90 s et 1 Mio RX par session. Rapport complet borné INCONCLUSIVE, aucune frontière universelle prouvée. |
| session-300 | 360 s | Observation existante : 300 s utiles, trois ouvertures, six lectures maximum espacées d’au moins 60 s, 1 Mio RX total, Ping/Pong et réponse corrélée. |
| session-reconnect | 480 s | Observation naturelle, trois ouvertures, dix lectures maximum à cadence >=60 s, 1 Mio RX total ; perte puis nouvelle génération, lecture corrélée et 120 s de stabilité. Sans perte/récupération prouvée : INCONCLUSIVE. |
| all | 2820 s | Six scénarios dans l’ordre du formulaire, indépendants et séquentiels ; maxima individuels 2730 s, marge 90 s. |

TLS et ouverture réutilisent AsyncTlsTransport/V4Lifecycle/V4Session ; la session
300 réutilise son observateur et ses budgets. H1/H2 réutilise boundary_capture,
ses protections et son calendrier sans changer ses hypothèses historiques.
Le rapport de campagne en projette seulement les compteurs nécessaires ; les
chronologies privées ne sont pas publiées par cette voie.
Les compteurs Ping/Pong non mesurés dans ce résumé H1/H2 restent null.

La nouvelle reconnexion ne reçoit aucune politique NoPongAfter120 et ne force
aucune perte. EOF, erreur transport et CloseClient ne deviennent pas une cause
serveur inventée : loss_kind=transport ne prouve pas un EOF TLS ; CloseClient
garde sa catégorie et son sous-code numérique. Le témoin de récupération vient
du gestionnaire partagé. Un timeout local n’est pas une perte naturelle.
48 octets restent un préfixe décodable d’OpenedClient, jamais une longueur
totale universelle.

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
Une identité absente/invalide ou initiale n’autorise pas d’association.

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
