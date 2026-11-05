# B7 — dernières valeurs HA pendant une perte de session

Tâche exclusive [HOBEN-163-B7-HOLD-300S-012](https://github.com/Guillaume0385/ha-hoben-community/issues/163#issuecomment-6643704581),
base `experimental` `96e6e10917ea11c3c7ce1906f1de4d896f486d8a`.
B7 a été fusionnée par PR #181. B8 reste une tâche séparée, désormais décrite
dans [son contrat](ha-reconnect-timing-b8.md) ; #126 reste suspendue.

## Comportement

Après une acquisition V4 complète, corrélée et décodée, les capteurs de mesure
et les binary sensors peuvent afficher leurs dernières valeurs disponibles
pendant **moins de 300 secondes depuis la première perte effective de session**.
Le coordinator écoute les événements du propriétaire existant : une perte idle
entre deux polls commence donc aussi cette fenêtre. Aucun poll réseau n'est
ajouté par cette écoute.

La fenêtre utilise une horloge monotone. Elle ne mesure pas l'âge de la dernière
acquisition : une mesure déjà ancienne avant la perte peut être conservée moins
de 300 secondes supplémentaires. Son horodatage UTC original et son âge réel
restent visibles dans le diagnostic de session existant. Le statut de session
reste reconnecting/disconnected selon le vrai propriétaire ; une valeur retenue
n'atteste ni connexion saine, ni acquisition actuelle.

À une perte idle, `last_update_success` devient false ; pendant un refresh,
Home Assistant enregistre et journalise d'abord sa véritable exception, sans
la masquer par une bascule anticipée de ce drapeau. Pendant la conservation, aucun
listener de mesure n'est appelé avec les anciennes valeurs : leur état et
`last_updated` ne sont pas réécrits. Les états intrinsèquement unknown/None
restent inchangés. Une tentative, une ouverture acceptée sans lecture, un poll
échoué ou un décodage refusé ne remet jamais la fenêtre à zéro.

À **300,000 secondes ou plus**, le timer local notifie Home Assistant même sans
poll, et les entités deviennent unavailable. La prochaine acquisition vraiment
validée rétablit la disponibilité, même si les valeurs décodées sont identiques
aux précédentes. Elle seule permet une nouvelle fenêtre lors d'une perte future.

Les callbacks portent un jeton d'acquisition : une ancienne expiration déjà
en file après annulation, revalidation ou unload ne peut pas expirer la fenêtre
suivante. Un callback trop précoce réarme seulement le temps monotone restant.
Les déplacements d'horloge UTC ne prolongent ni ne raccourcissent la fenêtre.

## Refus sûrs et preuve de nettoyage

Sans acquisition antérieure, aucune disponibilité ni fenêtre n'est créée.
Refus d'identité/authentification, certificat rejeté, erreur interne permanente,
arrêt/unload, cleanup_failed ou absence de propriétaire récupérable révoquent
la conservation immédiatement. Le cache reste informatif en mémoire ; aucune
notification ne le transforme en acquisition réussie.

La disponibilité conservée exige aussi une preuve de nettoyage du propriétaire
accepté déconnecté. Normalement elle vient de `cleaned_generation`. Les tests
rouges/verts ont montré une course de publication locale : le refresh peut
retourner après fermeture complète de la vraie session, juste avant copie de
la preuve par le lifecycle. Le coordinator consulte alors, **en lecture seule**,
la même session et son `cleanup_succeeded`, liés à son exacte génération active.
Cette dépendance étroite aux références internes existantes est documentée dans
`_cleanup_proven` ; elle ne change ni n'écrit ces références. Session absente,
transport simplement détaché, close TLS encore en attente/annulé/échoué ou
génération non attestée ne suffisent pas. Aucun close de remplacement ni
attestation reconstruite n'est ajouté.

Une indisponibilité effectivement publiée ne réactive pas les anciennes valeurs
avant une nouvelle lecture validée. La fenêtre UI ne permet aucune connexion
supplémentaire et ne modifie pas la barrière de cleanup du gestionnaire partagé.

La récupération #160 sur TLS encore vivant conserve son comportement A1 :
DataUpdated invalide seul ne commence pas une perte de session ni ce timer.
Silence glissant 30 s, sonde unique, framing, absence de frontière universelle
OpenedClient et tous les contrats de sécurité restent inchangés.

## Validation et portée

Avant modification, deux tests sont rouges : EOF indisponible immédiatement,
timeout conservé sans expiration autonome. Les tests verts utilisent les vrais
client, coordinator, capteurs et gestionnaire HA, avec transports, streams TLS
et horloges synthétiques : 299/299,999/300/301 s, perte idle, polls répétés,
deux reconnexions sans acquisition, lecture identique après expiration, refus
de décodage, callbacks périmés, sauts UTC, arrêt, annulation, auth, erreurs
permanentes et preuve TLS/cleanup B6. Les attentes historiques de disponibilité
immédiatement perdue sont adaptées à cette autorisation B7, sans assouplir les
preuves de lecture/reconnexion/cleanup ni les refus permanents.

Production modifiée uniquement dans `coordinator.py`. Aucun changement à
V4Session, V4Lifecycle, client, transport, codec, protocole, framing, délais de
reconnexion, capteur de session, campagnes/workflows, automations ou main.
V4 reste en lecture seule et TLS certificat/hostname vérifiés vers
`myhoben.fr:465`. Aucun secret, identifiant, RX/header/payload, donnée domestique
ou exception libre publié. Aucun test réel ni dispatch/rerun par DEV/CI.

Les résultats hors ligne ne valident pas une installation réelle. Le timer est
notifié au premier passage de la boucle HA après échéance ; `available` refuse
dès le seuil monotone, sans garantie d'ordonnancement temps réel sous blocage
de la boucle. Résultats des suites et quatre CI à consigner au HEAD exact de la
PR. Revue/fusion MANAGER uniquement ; les délais B8 sont documentés séparément.
