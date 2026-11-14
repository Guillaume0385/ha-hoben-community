# #212 — récupération bornée après timeout V4

Tâche `HOBEN-212-V4-THREE-REQUEST-RECOVERY-001`, développement sur
`experimental`. Aucun test Hoben ou Home Assistant installé n'est autorisé
par ce changement. Les essais utilisent des transports et horloges simulés.

## Politique du propriétaire

Le lifecycle HA reste l'unique superviseur de la génération TLS. Après une
lecture réellement émise puis expirée, il conserve TLS, le lecteur RX et les
Ping/Pong. Il attend **60 secondes après le timeout**, puis émet une deuxième
demande avec le même timeout. Un deuxième échec entraîne la même attente,
puis une troisième demande. Le troisième échec rejoint le chemin existant de
cleanup et de reconnexion. Une fermeture non attestée interdit toute nouvelle
TLS. EOF, CloseClient, erreur TLS et arrêt conservent leurs traitements propres.

Avec le timeout nominal de 30 secondes et sans autre erreur, les demandes
partent à T+0, T+90 et T+180 secondes ; leurs échéances sont T+30, T+120 et
T+210. Le backoff de reconnexion existant vient ensuite, sans raccourcir le
cleanup. Ce sont des délais locaux, pas des propriétés du serveur.

Le compteur porte uniquement sur les demandes dont l'écriture s'est terminée
et qui n'ont pas reçu de réponse exploitable. Une expiration en attente du
verrou TX ne compte pas comme une émission ; elle attend encore 60 secondes
avant un nouvel essai. Une erreur d'écriture garde son traitement terminal.
Les rafraîchissements HA ordinaires ne peuvent ni doubler ces émissions ni
réinitialiser les timers. La tâche de relance du lifecycle est annulée et
rejointe avant son cleanup, y compris lors d'un unload. La notification
directe de perte reste inchangée.

## Limite de corrélation conservée

Le TID des lectures demeure `0xFFFF`. Après l'abandon d'une demande, aucune
preuve disponible ne permet de distinguer sa réponse tardive d'une réponse à
la deuxième ou troisième demande. Même complète et structurellement valide,
une telle réponse est donc **non créditée**. Elle ne réinitialise ni le compteur
ni la fraîcheur HA. Les deux relances sont des observations bornées, pas une
permission de publier une mesure ambiguë. Une corrélation sûre sur ces relances
nécessiterait une preuve protocolaire distincte ; aucune n'est inventée ici.

Une réponse normalement corrélée avant tout abandon remet le compteur à zéro.
Après trois échecs sur une génération incertaine, la nouvelle génération doit
elle aussi fournir une vraie réponse corrélée avant le retour des mesures.
La rétention HA et son expiration à 300 secondes ne sont pas prolongées par
les relances, les réponses non créditées ou une ouverture TLS seule.

La récupération DataUpdated garde sa politique séparée de silence/purge :
ces relances ne traversent pas une quarantaine DataUpdated active. Elles
n'inventent aucune frontière ni sémantique de `0x0C` ou `0x1B`. Les chemins de
campagne et les clients n'activant pas la politique de reconnexion HA gardent
leur comportement existant.

## Vérifications et livraison

Le RED utilise les vrais `V4Session`, `V4Lifecycle`, `HobenClient` et
`HobenDataUpdateCoordinator` : il constatait l'absence de deuxième demande à
timeout +60 secondes. Les tests ciblés vérifient les émissions et échéances,
la continuité RX/Ping/Pong, les réponses FFFF tardives ou fragmentées, le
cleanup avant reconnexion, l'échec de cleanup, les pertes indépendantes,
l'arrêt et la rétention HA sans fausse fraîcheur.

L'arbitrage MANAGER du 14/11/2026 dans la consigne canonique autorise deux
extensions limitées. Les SHA256 de `v4_session.py` et `v4_lifecycle.py` sont
recalculés dans `.github/info-manual-route.json` ; tous les autres champs sont
comparés à `experimental` et restent identiques. Route Info, gates, workflows,
validateur et tests #186 conservent leur logique.

Le banc de double session conserve le verdict d'échec du scénario `stale` :
la réponse tardive de génération 1 n'est pas créditée. Après les trois échecs,
la génération 2 peut fournir ses propres acquisitions corrélées ; la fenêtre
restante ne prouve cependant pas les 300 secondes de récupération exigées par
ce scénario. Le rapport ne transforme donc pas cette observation en succès.

Le producteur réduit seulement deux résumés d'en-têtes ordinaires de génération
1, avant l'incident, lorsque leurs lectures réussies sont déjà attestées avec
les mêmes horodatages. Il conserve les compteurs, toutes les lectures, les
réponses tardives, l'incident, l'échec, le terminal, l'ordre des transitions,
les générations et leurs preuves de cleanup. Les en-têtes non ordinaires et
celui après l'incident restent présents. Les cas reproduits passent de
8 360 à 7 872 octets, enveloppe superviseur comprise, sous le plafond inchangé
de 8 192 octets. Les tests RED/GREEN comparent le rapport complet avant/après,
vérifient son expurgation et l'absence de changement pour les autres scénarios.

V4 lecture seule, TLS vérifié vers `myhoben.fr:465`, aucun secret, RX brut ou
donnée domestique exporté. Live HA et Home Assistant installé : **NOT RUN**.
