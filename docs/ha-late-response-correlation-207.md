# #207-D2 — Silence et corrélation tardive, hors ligne

Tâche `HOBEN-207-HA-LATE-RESPONSE-CORRELATION-002`, base
`37b51bb8a36cc9f366303439c8033e5ad3682f2e`, cible `experimental`.
La politique est explicitement activée par le seul lifecycle HA persistant.
Les sessions conservatrices, fixtures privées #186 et autres campagnes ne
reçoivent pas cette activation. Aucun changement de workflow, codec ou TID.

## Contrat

Un délai de réponse expiré ne prouve ni EOF ni erreur TLS. Le RX propriétaire,
le framer incrémental et les réponses Pong restent sur le même transport.
Un `TransportTimeout` immédiat impose 1 s avant la prochaine tentative RX,
y compris en récupération DataUpdated : pas de boucle chaude à `sleep(0)`,
pas de fermeture, pas de deuxième lecteur. L'attente reste annulable ; les
événements suivants EOF/TLS/auth gardent leur traitement et leur provenance
(l'authentification ne peut pas être déduite de bytes en quarantaine inconnue).
Ce délai de retry RX ne change aucun backoff de reconnexion B8.
L'échec d'acquisition reste un timeout typé, phase `request_correlation` ; il
n'est jamais converti en succès ni en perte de transport attestée.

Après une demande **émise** puis abandonnée, une réponse FFFF ultérieure peut
être ancienne ou rejouée : même drainer une première réponse ne prouve pas la
fraîcheur de la suivante. Cette génération suspend donc toute nouvelle demande
V4 et toute publication de réponse, sans fermer TLS pour lever l'ambiguïté.
Les réponses connues restent décodées/validées : TID, unité, fonction, longueur
et erreurs MBAP ne sont pas ignorés. Les demandes attendant seulement le verrou
TX, jamais émises, n'introduisent pas cette dette. Une erreur ou interruption
pendant l'écriture conserve la politique stricte existante.

Une véritable perte ultérieure conserve le superviseur unique, les preuves de
cleanup et les délais B8 existants ; une nouvelle génération permet une lecture
neuve corrélée. Aucun nouveau transport avant cleanup attesté, aucun retry en
cas d'authentification refusée, arrêt ou cleanup incertain. Un silence seul peut
ainsi laisser la session ouverte **sans acquisition validable indéfiniment** ;
ce comportement sûr est une limite explicite, pas une récupération annoncée.

DataUpdated invalide seul garde sa fenêtre glissante de 30 s et sa sonde unique
lorsqu'aucune demande abandonnée n'en rend la réponse ambiguë. Abandonner une
lecture en cours ou une sonde non consommée interdit une nouvelle sonde FFFF
sur cette génération. Une exception Modbus réellement corrélée constitue une
réponse consommée, et non une demande sans réponse.

## Home Assistant

Le moniteur rapporte `recovering` pendant l'incertitude, tandis que la session
TLS reste active. Le dernier snapshot décodé et `last_successful_read_at`
restent inchangés ; aucun poll, drop ou doublon ne renouvelle la grâce B7.
Elle expire à 300 s depuis la première incertitude, avec notification HA même
sans poll. Les valeurs `None`/inconnues gardent leur sémantique. Sans acquisition
initiale, setup attend le même propriétaire et ne boucle pas sur des lectures
immédiatement refusées ; arrêt/unload annule et nettoie cette attente.

Les anciens scénarios hors ligne qui provoquaient une reconnexion par silence
injectent désormais un **EOF distinct** ou une vraie erreur TLS pour exercer
leurs preuves de fermeture. Les scénarios de silence/réponse tardive restent
négatifs : aucune récupération de campagne n'est artificiellement créditée.
Aucun test désactivé, aucune assertion de cleanup remplacée par `abort` ou
`is_closing`. Les quatre empreintes des sources partagées dans le manifeste
#186 sont réépinglées, sans modifier ses gates ou sa route.

## Preuves et limites

Le test RED sur la base démontre la fermeture locale après expiration. Les
tests unitaires et HA GREEN utilisent les vrais session/lifecycle/client et
coordinator, des transports mémoire et des horloges injectées : réponses tardives
fragmentées et doublonnées, Ping/Pong, délai TX sans émission, réponse consommée
suivie d'un timeout RX idle, DataUpdated, EOF/TLS/auth/certificat/erreur interne,
MBAP/TID invalides, cleanup retenu/échoué, nouvelle génération, setup/annulation,
et expiration B7 sans fausse fraîcheur. Les suites B4/B6/B7/B8 et #192 conservent
leurs vérifications de sûreté. Les résultats précis et quatre checks au HEAD
sont consignés dans la PR ; une CI non exécutée n'est jamais annoncée réussie.

V4 lecture seule, certificat/hostname `myhoben.fr:465` inchangés, aucun accès
Hoben/HA réel, dispatch/rerun, commande, secret ou donnée domestique. D3 et les
validations réelles sont NOT RUN ; le cleanup réel #192 n'est pas déclaré résolu.
