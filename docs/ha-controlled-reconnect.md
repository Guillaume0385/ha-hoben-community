# Reconnexion HA avec inhibition Pong de test — #126 / 028–029

Décision propriétaire du 30/10/2026, [consigne MANAGER active](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6435985641).
Première livraison ciblée : **session-reconnect** de la campagne HA uniquement.
La tâche expérimentale 027 / PR #158 est terminée. H1/H2 reste inchangé.
Fiabilisation 029 : [consigne canonique MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6549641918).

## Isolation et chemin réel

Le worker privé possède un seul vrai HomeAssistant/ConfigEntry, HobenClient,
V4Lifecycle, V4Session et coordinator. L'intégration distribuée sous
custom_components/hoben ne change pas et n'importe aucun de ces scripts.

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
