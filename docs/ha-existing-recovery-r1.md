# R1 — récupération dans les tests HA existants

Tâche exclusive [HOBEN-126-HA-R1-EXISTING-RECOVERY-012](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6653165337),
base `experimental` `c9ad5f980e8deb02ad0640b593a6a1f6c30daba8`.
HA-F2 est annulée ; aucun scénario de 15 minutes. R2–R5 restent du backlog.

## Résultat et preuves

Seuls `session-reuse` et `availability` changent de critère fonctionnel.
Le chemin nominal conserve son prédicat historique et ses compteurs : disponible
avec les 3/2 acquisitions prévues toutes valides ; `session-reuse` exige en plus
`reused=true`. Il n'imposait pas `opens==1` : deux ouvertures restent admissibles
dans les bornes existantes, même sans preuve de récupération F1. Ce SUCCESS
nominal n'ajoute aucune attestation de récupération : `recovered` reste false
sans preuve F1 stricte. Une erreur intermédiaire peut désormais être couverte par
une récupération **attestée**, sans effacer l'échantillon échoué.

Les champs existants de HA-F1 et des observations suffisent ; aucun nouveau
champ ou schéma de rapport n'est ajouté. La validation indépendante Python/Node
exige ensemble :

- Premier incident lié au premier propriétaire accepté ; catégorie expurgée
  EOF, transport/TLS, timeout, CloseClient non auth ou protocole. La catégorie
  seule ne prouve pas une récupération ; l'erreur terminale et celle du cleanup
  doivent être absentes. Les refus auth et erreurs internes restent des échecs.
- Deux propriétaires/générations réellement acceptés, chacun fermé et réapé,
  aucun pending et cleanup original attesté. Le cleanup de génération 1 précède
  la dernière lecture de génération 2 dans la chronologie F1.
- Dernier échantillon décodé et disponible sur génération 2, avec séquence
  corrélée, nettoyage de génération 1 et preuve F1 de la même lecture. Chaque
  poll échoué appartient à l'ancienne génération et possède un échantillon
  décodé ultérieur sur la nouvelle ; pas d'erreur intermédiaire non couverte.
- Fenêtre finale active, même génération/séquence que le dernier échantillon,
  aucun incident naturel supplémentaire lors du cleanup, arrêt final et
  génération 2 entièrement nettoyée. Supervisor terminé, réapé, sans échec de
  ressource, dans son budget ; preuve monotone native pour un SUCCESS publié.

Un rejet protocolaire effectivement suivi de ces preuves peut être récupéré ;
une erreur terminale F1, un profil non supporté ou une absence de lecture neuve
restent FAILURE. Un timeout ou un rejet de framing ne deviennent pas un EOF
inventé : `loss_kind` conserve le fait observé, éventuellement `none`.

Les appels réels du coordinator vérifient désormais, pour ces deux scénarios,
le remplacement des données décodées **et** l'avancement du témoin génération/
séquence du client. Un simple `last_update_success=true` ou une copie du cache
ne compte pas. La disponibilité provient du vrai `snapshot_available` : une
valeur B7 conservée peut être disponible avec `decoded=false`. Son horodatage
n'est jamais réécrit par l'observateur. Un saut UTC n'efface pas la preuve d'une
nouvelle séquence ; le scénario et F1 utilisent leurs horloges monotones.
Leurs origines relatives peuvent différer : les temps F1 sont comparés entre
faits F1, et les séquences relient ces faits aux échantillons.

`reads` et `reads_ok` restent les tentatives de refresh et acquisitions validées
réellement observées. La récupération n'invente pas la lecture échouée.
`reused` reste vrai seulement pour deux acquisitions successives de la même
session ; le chemin alternatif peut donc réussir avec `reused=false` et
`recovered=true`. Le résumé affiche les deux preuves séparément et conserve le
premier incident, l'erreur terminale et le cleanup F1.

Le chemin récupéré est refusé sans preuve F1 complète ; les rapports nominaux
historiques restent lisibles selon leur contrat existant. Cache ancien/B7,
ouverture sans lecture, cardinalité incomplète, auth/erreur terminale, annulation,
cleanup non confirmé ou plafond atteint : FAILURE ou refus de preuve,
jamais un SUCCESS fabriqué. NOT RUN garde
son sens de collecte non commencée. Les autres scénarios conservent leurs
critères et statuts ; aucune nouvelle règle INCONCLUSIVE n'est introduite.

## Correction de revue : contrat nominal et preuve de récupération

La [demande MANAGER](https://github.com/Guillaume0385/ha-hoben-community/pull/183#issuecomment-6655156501)
signale une restriction `opens==1` ajoutée à tort au nominal dans le premier
HEAD R1. Le [contrat de base](https://github.com/Guillaume0385/ha-hoben-community/blob/c9ad5f980e8deb02ad0640b593a6a1f6c30daba8/scripts/campaign_runtime_contract.py#L310)
et son [équivalent Node](https://github.com/Guillaume0385/ha-hoben-community/blob/c9ad5f980e8deb02ad0640b593a6a1f6c30daba8/.github/scripts/campaign-report.cjs#L44)
ne contiennent pas cette restriction, pour aucun des deux scénarios.
Après les prérequis communs completed/cleanup/error, le prédicat historique est :

- availability : disponible et 2/2 lectures décodées ;
- session-reuse : disponible et 3/3 lectures décodées, avec `reused=true`.

Ces prédicats sont restaurés dans les deux validateurs. La borne structurelle de
deux ouvertures reste inchangée. Un rapport nominal à deux ouvertures sans F1
est donc SUCCESS pour ces lectures disponibles ; `recovered=false` indique
qu'aucune récupération F1 stricte n'est attestée. Ce succès nominal ne prétend
pas démontrer une continuité TLS ni une récupération. Le premier HEAD R1
refusait à tort ces rapports ; quatre tests Python/Node sont RED avant la
correction, puis GREEN.

Les autres régressions vérifient qu'un rapport avec lecture échouée et sans F1
reste FAILURE, que `session-reuse` conserve son exigence `reused` et qu'un
champ `recovered=true` ajouté arbitrairement est refusé même sur un SUCCESS
nominal. Le chemin alternatif récupéré et toute sa validation F1 restent
inchangés par cette correction.

## Bornes inchangées

| Scénario | Échéances des appels | Plafond processus | Collecte avant réserve |
| --- | --- | --- | --- |
| session-reuse | 0, 60, 120 s | 180 s | 150 s |
| availability | 0, 60 s | 120 s | 90 s |

Aucun refresh de rattrapage ni nouvel appel n'est ajouté. Le vrai client,
coordinator et lifecycle existants restent propriétaires du réseau, du retry
et de la corrélation. Ni code distribué, politique B8, codec/framer, autre
observateur, liste/ordre/orchestration `all`, workflow, budget ou gate ne change.
Les scénarios R1 gardent leurs identifiants lorsqu'ils sont déjà inclus dans
`all` ; cela ne modifie pas son orchestration ni les autres scénarios.

## Lecture des neuf runs historiques

Les neuf runs du 04/11/2026 ont admission et collecte SUCCESS, puis résultat
FAILURE, au SHA `96e6e10917ea11c3c7ce1906f1de4d896f486d8a`. Artefacts publics
expurgés et jobs relus ; les neuf rapports restent validés **sans modification**
par Python et Node après R1. Ce SHA contient déjà B6/#179 et F1/#180, et précède
B7/B8 ; ne pas attribuer un symptôme historique au HEAD courant sans preuve.

| Run | Faits attestés dans le rapport |
| --- | --- |
| [41921198441](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/41921198441) | hoben-live : 6/6 lectures, 2 ouvertures, cleanup valide ; incident MBAP puis changement de génération, continuité historique non prouvée. Hors R1. |
| [41921234825](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/41921234825) | session-reconnect : incident MBAP vers 100 s, avant inhibition ; close transport annulé/non attesté, pas de reprise contrôlée. Hors R1. |
| [41921281470](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/41921281470) | dual : worker_failure, aucune ouverture/lecture attestée et aucun premier incident F1 ; cause plus précise inconnue. Hors R1. |
| [41921314474](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/41921314474) | all : session-reuse et availability SUCCESS nominaux ; session-reconnect échoue après rejet de classification/framing avant inhibition, cleanup prouvé. |
| [41927475489](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/41927475489) | session-reconnect : CloseClient 3, 2 ouvertures, 5/5 lectures et reprise attestée ; timeout du close final génération 2, cleanup absent. FAILURE conservé. |
| [41927526419](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/41927526419) | dual : timeout transport_connect pendant l'ouverture, aucune lecture, cleanup attesté. Hors R1. |
| [41927558904](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/41927558904) | session-reconnect : timeout tls_read avant acquisition valide puis timeout transport_close, cleanup absent. Hors R1. |
| [41927594767](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/41927594767) | dual : timeout tls_read puis timeout transport_close, aucune lecture ni cleanup attesté. Hors R1. |
| [41927625891](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/41927625891) | all : hoben-live sans lecture valide, timeout tls_read puis transport_close ; étapes suivantes, dont R1, NOT RUN pour cleanup_failed. Arrêt sûr conservé. |

Ces runs ne démontrent aucun faux échec de récupération de R1. Le défaut de
critère ciblé est reproduit **synthétiquement**, sans réinterpréter ces runs
comme réussis ni déduire une règle serveur, une causalité résidentielle ou un
comportement au HEAD actuel. Les problèmes hors R1 restent du backlog MANAGER.

## Validation et limites

RED initial : six cas HA EOF/CloseClient/timeout, avec nouveaux client et lecture
attestés mais critère historique refusant les lectures intermédiaires échouées.
GREEN : tests des deux scénarios avec les vrais objets client/coordinator et
transports/horloges synthétiques ; nominal, incident pendant une lecture ou
entre polls, rejet protocolaire récupéré, refus permanent, nettoyage échoué/
annulé, arrêt, B7 à 299/300 s, faux succès/cache copié et saut UTC.

Contrats Python/Node : preuve complète, omissions/tampering, faux statut,
ressources, données manquantes, ancien owner non nettoyé, nouvelle session sans
lecture, chronologies et origines F1 distinctes, sortie fermée <=8192 octets,
présentation conservant l'incident et les comptes. Le contrôle UI B7 à 300 s
n'étend aucun budget de campagne. Une horloge synthétique ne valide pas un run
réel ; les reçus construits des tests de contrat restent des fixtures.

La validation structurelle ne signe pas cryptographiquement un rapport arbitraire.
Les contrôles de provenance existants restent indispensables. Aucun test réel,
accès Hoben/HA résidentiel, dispatch/rerun, commande/écriture, secret/GUID/RX/
header/payload privé, valeur domestique, main, automatisation ou fusion DEV.
TLS certificat/hostname vérifiés vers `myhoben.fr:465`, lecture seule inchangée.
Résultats complets et quatre CI à consigner au HEAD exact, puis revue MANAGER.
