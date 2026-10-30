# Reconnexion HA avec inhibition Pong de test — #126 / 028

Décision propriétaire du 30/10/2026, [consigne MANAGER active](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6435985641).
Première livraison ciblée : **session-reconnect** de la campagne HA uniquement.
La tâche expérimentale 027 / PR #158 est terminée. H1/H2 reste inchangé.

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
