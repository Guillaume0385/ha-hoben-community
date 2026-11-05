# Reconnexion HA avec inhibition Pong de test — #126 / R5

## Contrat courant R5 — plusieurs reprises prouvées

[Consigne MANAGER #6665052749](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6665052749),
base `b17437f9e78d8c9ae7953471f4048096d5da5d29` après R4/#187. Ce contrat remplace
les limites à deux générations et à une seule perte des sections historiques
ci-dessous, pour le seul scénario HA `session-reconnect` existant.

Le banc décore la factory d'un client frais dans son worker isolé : son vrai
lifecycle reçoit deux délais finis identiques au délai de campagne existant,
donc **trois ouvertures maximum**, sans modifier l'API HobenClient ni activer
la politique HA distribuée. C'est la limite déjà arbitrée pour ce scénario,
anciennement restreinte à deux par son adaptateur. Une troisième reprise est
refusée ; aucun reset de compteur, client de remplacement ou session parallèle.

L'inhibition reste exclusivement celle des Pong de la **première génération**
après 120 s depuis son acceptation stricte. Une perte avant inhibition ne
valide pas le scénario et interdit sa poursuite. La perte contrôlée exige un
EOF réellement reçu ou un CloseClient complet reconnu ; première reprise avant
240 s. Aucun autre octet n'est filtré, réinterprété ou enregistré. Les générations
suivantes rétablissent les Pong, même après plus de 120 s.

Chaque génération possède des métadonnées fermées : connexion demandée,
acceptation, premier incident typé/sous-code prouvé, nettoyage complet et Pong
transmis après acceptation. Avant chaque nouvelle connexion, le banc vérifie le
cleanup réel du propriétaire précédent : TLS détaché sans échec, RX et opérations
terminés, TX et waiter absents, sonde DataUpdated réapée. Le lifecycle réel reste
seul propriétaire des retries et fermetures. Les témoins HA-F1 indépendants
doivent aussi attester l'ancien propriétaire réapé et aucune ressource pending.
Les temps R5 et HA-F1 partagent la même origine monotone ; un cleanup F1
postérieur à la connexion suivante invalide le rapport.

Le rapport `recovery.schema=2` exige une lecture V4 fraîche corrélée pour
**chaque génération acceptée**, y compris l'intermédiaire : génération/séquence
réelles, nouvel objet décodé du coordinator et ancien cleanup attesté. Un poll
échoué reste échoué, sans replay ; le snapshot disponible B7 n'est pas une
nouvelle lecture. Un timeout typé n'est pas renommé EOF : les champs publics
de perte naturelle restent ceux du lifecycle. Une erreur interne, auth, arrêt,
framing non admissible, ouverture refusée ou cleanup non prouvé reste en échec.

La stabilité de 120 s repart de la **dernière ouverture acceptée**, avec lecture
neuve, génération active inchangée et Pong réellement transmis après acceptation.
Une nouvelle perte efface cette stabilité, jamais les preuves antérieures.
L'observation est bornée à 570 s et à la deadline parent moins 40 s ; close final
borné à 10 s, réserve restante pour arrêt HA/réapage, plafond absolu 600 s.
Six refreshs maximum, au moins 60 s après la fin du précédent ; plus assez de
temps ou de lectures implique échec, sans prolongation. HA/all conserve 1800 s,
15 ouvertures et 42 refreshs ; les autres scénarios gardent deux ouvertures.

`recovered` décrit la reprise observée avant teardown. Une erreur de fermeture
finale reste séparément visible, invalide `completed`/`cleanup`, impose FAILURE
et arrête HA/all ; aucun close idempotent ultérieur ne peut l'effacer. Les anciens
rapports sans v2 gardent leur validation historique à deux générations. Les
preuves synthétiques ne deviennent jamais une complétion live. Sortie allowlistée
≤8192 octets, `boundary_proven=false`, aucun total OpenedClient inventé.

Le run historique **41927475489**, SHA
`96e6e10917ea11c3c7ce1906f1de4d896f486d8a`, montre deux ouvertures, cinq lectures
décodées, une reprise et 120 s stables, puis timeout de fermeture TLS génération 2
et cleanup non attesté : FAILURE correct. Ce SHA contient déjà #171/#179 et
précède B7/B8. Ce constat ne prouve aucune cause serveur ni un nouveau défaut de
fermeture du HEAD actuel ; aucune correction production spéculative dans R5.

Tests : vrai client/coordinator/session sur transports et horloge synthétiques,
zéro/une/deux reprises, troisième refusée, pertes avant/après inhibition, EOF et
CloseClient distincts, timeout, lecture intermédiaire absente, reprise trop
tardive, auth/interne/protocole, ouverture refusée, cleanup des trois générations,
annulation/timeout de close via les régressions #171, altérations Python/Node.
Aucun test réel, dispatch/rerun ou changement d'automatisation par DEV.

## Historique 028–031

Décision propriétaire du 30/10/2026, [consigne MANAGER active](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6435985641).
Première livraison ciblée : **session-reconnect** de la campagne HA uniquement.
La tâche expérimentale 027 / PR #158 est terminée. H1/H2 reste inchangé.
Fiabilisation 029 : [consigne canonique MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6549641918).

## Isolation et chemin réel

Le worker privé possède un seul vrai HomeAssistant/ConfigEntry, HobenClient,
V4Lifecycle, V4Session et coordinator. L'intégration distribuée sous
custom_components/hoben n'importe aucun de ces scripts. Les tranches 028–029
ne la modifiaient pas ; la correction partagée de fermeture 031, prouvée aussi
sans instrumentation, est décrite ci-dessous.

Pour ce seul scénario, ha_pong_injection décore temporairement la factory de
session du client frais. Le contexte refuse une seconde installation et la
politique HA de production ha_reconnect=True. Son sous-type de session appelle
les méthodes réelles sans les recopier : l'instant d'ouverture est enregistré
immédiatement après l'acceptation stricte. Le vrai lifecycle conserve ses
**deux tentatives**, son backoff de campagne et son cleanup. Aucun appel ne ferme
un transport pour fabriquer une panne ; aucun RX n'est interprété par l'adaptateur.

Sous le verrou TX existant, le transport décoré filtre exclusivement le paquet
Pong d'un octet de la première génération après **120 s** depuis l'acceptation,
en réutilisant NoPongAfter120. Tous les autres envois restent identiques.
La deuxième génération rétablit les Pong. TLS, certificat, hostname et
destination fixes restent ceux du transport réel. Après cleanup, la factory
initiale est restaurée, également après annulation/erreur. Aucune tâche ou
installation globale ne survit au contexte du banc isolé.

## Correspondance expérimentale / HA

| Élément repris de la parité 027 | Mise en œuvre HA |
| --- | --- |
| NoPongAfter120, première génération seulement | Transport décoré du banc ; aucun changement au client HA installé. |
| T0 = ouverture strictement acceptée | Retour de V4Session.connect, aucune déduction depuis le préfixe RX. |
| Perte après inhibition, reprise avant T0+240 s | EOF réellement reçu ou CloseClient complet reconnu par le propriétaire, plus témoin de perte du lifecycle. Aucune attribution de causalité serveur. |
| Réponse corrélée à la nouvelle génération | Vrai refresh du coordinator, données nouvellement décodées et séquence propriétaire ; aucune sonde indépendante. |
| 120 s stables, Pong rétablis | Génération finale active inchangée, perte suivante absente, lecture corrélée et au moins un Pong réellement transmis après réouverture. |
| Cleanup et rapport fermé | Temps/état figés avant fermeture explicite, génération nettoyée, validation Python et Node indépendantes. |

La comparaison 029 porte sur `_observe_reconnect` de `session_suite.py`, son
appel dans `protocol_campaign_collect.py`, et le chemin
`ha_campaign_worker` → `ha_session_live_worker.collect` →
`ha_reconnect_observer.observe` / `ha_pong_injection` :

| Point vérifié | Expérimental PR #158 | HA 029 |
| --- | --- | --- |
| Origine des 120 s | `NoPongAfter120.accepted`, après `V4Session.connect` | Même politique, même retour strict ; délai d'ouverture exclu, horloge monotone vérifiée. |
| Durée de la première génération | Ordinal initial conservé jusqu'à perte ; aucune nouvelle origine après réouverture | Ordinal initial conservé ; interruption non provoquée terminale, même si le retry concurrence le refresh. |
| Pong effectivement inhibé | Compteur `policy.suppressed`, filtre interne opt-in expérimental | Même compteur, filtre du seul transport de test, sous verrou TX existant. |
| Perte admissible | EOF ou CloseClient complet après inhibition, témoin propriétaire | Mêmes événements et témoin ; EOF vide ou levé distinct de fermeture locale/timeout/erreur protocole. |
| Réouverture | Acceptation avant T0+240 s | Même échéance ; vraie génération 2 du client/coordinator, pas de replay du read échoué. |
| Lecture corrélée | Séquence de lecture du propriétaire, budget de génération | Nouveau décodage du coordinator, génération/séquence et ancienne génération nettoyée. |
| Pong restaurés / stabilité | Nouvelle génération active, ≥1 Pong transmis après acceptation, 120 s | Mêmes exigences ; un Pong pendant l'ouverture ne suffit pas. |
| Frontière | Hypothèse persistante, `boundary_proven=false` | Même hypothèse, même champ false ; un succès fonctionnel ne prouve pas une longueur universelle OpenedClient. |
| Cleanup | État figé avant `close`, arrêt et dernière génération nettoyée, aucun échec | Idem ; échec/expiration conservé dans le rapport avant finalisation idempotente du worker. |
| Plafonds existants | Processus 600 s, observation 590 s, horizon fonctionnel T0+360 s, 3 opens / 10 reads | Processus 600 s, observation ≤570 s et deadline parent −40 s, reprise <240 s + stabilité 120 s ; 2 opens / 6 refreshs. Aucun plafond augmenté. |

## Interruption précoce et nettoyage — 029

Les artefacts expurgés des runs `41242880445` et `41243780903` ont été lus.
Le premier porte `cleanup_failed=true` et `cleaned_generation=1` après une
reprise sur génération 2 : il s'agit d'un échec propriétaire conservé, pas d'un
succès que le banc pourrait réattester. Le second montre une génération 2 sans
Pong inhibé ni perte admissible. Les causes historiques restent **inconnues**.

Le banc arrête désormais une interruption non admissible de la première
génération avec `terminal=closed`, `outcome=not_exercised`, et refuse son retry
avant ouverture du transport suivant. Une perte de génération 2 invalide la
stabilité. Aucune session n'est fermée artificiellement pour fabriquer la perte.
L'arrêt explicite intervient uniquement après décision d'échec du scénario.
Un refus avant acceptation de la génération 2 reste `reopen_failed`, distinct
de `stability_lost` après acceptation effective de cette génération.

`recovery.diagnostic`, optionnel pour lire les anciens rapports, contient deux
emplacements bornés : `interruption` et `cleanup`. Chaque emplacement conserve
le premier événement observé : catégorie typée, propriétaire local
(`transport_read`, `transport_write`, `opening`, `session`, `transport_close`
ou `observer_cleanup`), génération ordinale, inhibition déjà exercée ou non,
et sous-code CloseClient uniquement s'il est reconnu par le vrai propriétaire.
Les mêmes scalaires sont journalisés ; aucun texte d'exception ni cause distante
déduite. Les validateurs Python et Node refusent les champs libres, types faux
et diagnostics incompatibles avec une preuve de succès.

Une erreur transport de fermeture reste `cleanup=false`. Si la fermeture de
l'observateur échoue ou expire, son rapport d'échec est conservé pour la
finalisation du worker ; un second close idempotent ne réécrit pas cette preuve.
Le transport de production, ses délais et ses erreurs ne sont pas modifiés.
Les tests synthétiques couvrent aussi un Pong en vol lors du teardown, un retry
concurrent, une ouverture retardée et les validations négatives Python/Node.

Le socle hoben-live conserve sa preuve de six lectures sur 300 s et son
observateur #112. Les autres scénarios, dont session-reuse sans panne injectée,
gardent leur chemin antérieur. La cause du closed du run #41016459980 reste
**inconnue** : cette simulation ne l'explique pas et ne la corrige pas.
Sa correction/diagnostic complémentaire est reporté à un arbitrage MANAGER.

## Fermeture suspendue après perte — correction 031

[Consigne MANAGER #6559839377](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6559839377),
base `6e835541d4cda011219b886eaf74bf652bbde4c5` après #170. Le run propriétaire
#41317930747 atteste cinq lectures, une reprise et 120 s stables, mais conserve
`cancelled / transport_close / generation=1` et un échec de cleanup. Aucun
nouveau test réel n'est lancé pour cette correction.

Chemin causal local reproduit avec les vrais client/coordinator/session :

1. `V4Session._receive_unproven_handoff` signale la perte avant son finally de
   fermeture ; `wait_lost` réveille donc le lifecycle avant la fin du close.
2. `_release_transport` détache le transport sous le verrou TX puis attend
   `transport.close()`. Le TLS réel peut suspendre sur `wait_closed()` ; les
   anciens doubles de tests fermant sans suspension ne reproduisaient pas la course.
3. `V4Lifecycle._cleanup` appelle `session.abort()` puis `_close`. L'ancien
   `_close` annulait RX même lorsque RX fermait déjà le transport : la fermeture
   était réellement interrompue, pas seulement la lecture RX annulée normalement.
4. `_release_transport` ne mémorisait pas cette `CancelledError`, contrairement
   aux autres erreurs de close. Un transport détaché pouvait donc sembler nettoyé.
   Une annulation déjà reçue par l'appelant pouvait aussi être propagée à tort
   une seconde fois à l'attente d'un lecteur lui-même annulé, interrompant la
   libération du propriétaire dans le finally.

La correction reste dans `v4_session.py`, car le test rouge identique **sans
PongInjection** démontre que la course n'est pas créée par le banc. Aucun code
de lifecycle, transport TLS, observateur, diagnostic ou validateur n'est remplacé.
La reprise ordinaire attend RX si le transport a déjà été détaché pour fermer ;
elle peut toujours interrompre une lecture active. Un arrêt explicite conserve
sa faculté d'interruption et toute annulation réelle du close est mémorisée
comme échec. Si le lecteur était déjà annulé avant l'attente, la demande
antérieure traitée dans le finally n'est pas relancée comme une nouvelle erreur.
Les nouvelles demandes ainsi que celles déjà programmées avant l'attente d'un
lecteur actif continuent de se propager.

Aucune tâche de close secondaire ni seconde fermeture idempotente pour attester
un succès. L'attente protégée du lecteur distingue sa propre annulation de celle
de l'appelant ; toute annulation réelle de l'appelant est immédiatement transmise
au lecteur et son arrêt attendu, sans close laissé en arrière-plan. Le timeout TLS existant et les
deadlines du parent restent appliqués ; aucune prolongation/retry ou modification
de la politique permanente #163/C1. Les témoins d'échec restent persistants et
les rapports Python/Node ainsi que l'arrêt sûr HA/all sont inchangés.

Les tests `ha_tests/test_reconnect_cleanup_031.py` injectent uniquement transports,
horloge et ordonnancement. Le chemin nominal présente deux Pong inhibés,
CloseClient à +180,550 s, réouverture à +183,534 s, cinq lectures corrélées,
120 s stables et les **deux appels originaux** de close terminés avant
`cleanup=true`. Une réouverture retardée attend aussi le premier close.
La matrice couvre les générations 1/2 : close annulé avant/pendant/après,
erreur transport, timeout, annulation de l'observateur avant/pendant/après close,
double annulation concurrente et refus d'effacer l'échec par un close ultérieur.
Les preuves restent `synthetic` : elles ne deviennent jamais une complétion live.
Les suites de régression conservent TX en vol, H1/H2, les sept scénarios HA/all,
DataUpdated 30 s, logs B3, confinement et réapage. Cette reproduction démontre
un défaut local compatible avec le symptôme, sans attribuer de causalité au
serveur ni prétendre identifier toutes les circonstances du run distant.

## Bornes et résultats

Plafond original **600 s** processus/cleanup compris, 30 s réservées au teardown
de l'observateur ; la deadline absolue héritée peut seulement le raccourcir.
Deux ouvertures, six refreshs maximum, espacés d'au moins 60 s après la fin du
précédent ; polling de contrôle borné, aucun polling de capteurs supplémentaire.
1 Gio / 128 PID, rapport privé 8192 octets, aucun quota/compteur RX HA ajouté.
All HA reste 1800 s, 15 ouvertures / 42 refreshs cumulés.

SUCCESS exige inhibition réellement exercée, perte reconnue après T0+120 s,
réouverture strictement avant T0+240 s, lecture corrélée sur génération 2,
Pong transmis après reprise, 120 s stables et cleanup attesté. La seule
réouverture ou la fin du job ne suffit pas. Sans Ping, sans perte ou avec reprise
tardive : INCONCLUSIVE. Erreur/timeout/annulation ou cleanup défaillant : FAILURE.
Une perte pendant la stabilité invalide la preuve. Les scénarios non exécutés
restent NOT RUN ; une ancienne preuve de reconnexion naturelle ne valide plus
ce test contrôlé. Une horloge injectée reste synthetic et ne donne jamais une
complétion live attestée.

Seuls compteurs, générations ordinales, temps relatifs et catégories fermées
sortent du worker. Aucun octet reçu, GUID, secret, donnée domestique ou exception
libre. boundary_proven=false : le préfixe OpenedClient de 48 octets ne devient
pas une longueur universelle. Tests réels **NOT RUN** ; aucun dispatch/rerun,
changement d'admission/environnement, main ou automation par cette livraison.
