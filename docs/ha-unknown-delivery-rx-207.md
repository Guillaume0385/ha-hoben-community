# #207-D1 — abandon des livraisons à tête non prise en charge

Décision propriétaire du 11/11/2026, tâche
`HOBEN-207-HA-UNKNOWN-DELIVERY-RX-001`, cible experimental.
[Consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/207#issuecomment-6792046806)
et [décision #186](https://github.com/Guillaume0385/ha-hoben-community/issues/186#issuecomment-6790374074).

Le lifecycle HA (`ha_reconnect=True`, mode PERSISTENT) fournit explicitement
`discard_unsupported_deliveries=True` à sa session. Le défaut des autres
propriétaires de session reste False. La capacité privée `_InfoDeliveryDropExperiment`
reste séparée, désactivée par défaut, limitée à Info et plafonnée comme auparavant.
Elle n'est jamais fournie par HA ; les deux politiques ne se cumulent pas.

Au retour réel de transport.read, le RX peut abandonner la livraison entière
uniquement si la session est CONNECTED, le task et transport sont les propriétaires
courants, le framer n'a ni partiel ni tail, aucune erreur/fermeture n'est en cours
et la récupération DataUpdated n'est pas active. Le premier octet doit être
non pris en charge : Info, autre type connu non supporté ou type inconnu.
Les types 05/07/0A/0E/1B gardent le framer normal ; les marqueurs d'autorisation
2F/30 gardent leur refus terminal. Une trame connue malformée n'est jamais
transformée en livraison inconnue à ignorer.

La totalité du bloc admissible est perdue, y compris un Ping, une réponse V4
ou un DataUpdated concaténé. Cette perte est explicitement acceptée par le
propriétaire. Aucun suffixe n'est scanné ou conservé, aucune taille Info ou
frontière n'est déduite : TLS reste un flux, boundary_proven=false. La livraison
suivante repasse dans le vrai framer, sur le même RX et la même TLS. Un deuxième
fragment de trame connue, même s'il commence par une tête inconnue, ne satisfait
pas les gardes et reste décodé normalement. Les suffixes d'ouverture restent
hors de ce point d'interception.

Un drop n'appelle ni close, reconnexion, publication de snapshot ou succès de
lecture. Il ne réarme pas la demande en attente ni son échéance. Une cession
coopérative après abandon libère le bloc et laisse les annulations, échéances
et autres tâches HA progresser même si le transport est continuellement prêt.
La fraîcheur et la disponibilité ne sont réévaluées que par les événements et
lectures validés existants ; un drop seul ne change pas la dernière acquisition.

Diagnostics DEBUG scalaires : catégorie fermée unknown/unsupported,
delivery_bytes (1..4096), discarded_deliveries (compteur saturant à 65535),
length_scope=tls_delivery et boundary_proven=false. Échantillonnage aux quatre
premiers drops puis aux puissances de deux : au plus 17 événements par session.
Après saturation, les drops continuent sans nouvelle allocation, log ou erreur
locale. Aucun octet reçu, sous-code, GUID, registre ou valeur domestique.

## Limites et validation

D1 n'altère pas `_request_v4_data`, le TID fixe FFFF, le traitement des réponses
non sollicitées ou mal corrélées, ni les timeouts. Un timeout peut donc encore
fermer TLS malgré les drops : D2 reste nécessaire et aucune reprise sûre après
réponse tardive n'est revendiquée. B7 300 s, B8 10+10/30/60, DataUpdated silence
30 s, EOF/TLS/certificat, auth, annulation et cleanup restent applicables.
#192 cleanup réel demeure non résolu.

Les tests sont synthétiques : RED/GREEN du vrai client/coordinator HA, toutes
les têtes non gérées, plus de 16 drops, concaténations entièrement perdues,
fragmentation connue, suffixes, erreurs/corrélation, annulation, saturation et
absence de fausse fraîcheur. Les anciennes régressions de cleanup/reconnexion
utilisent désormais une réponse connue à MBAP invalide ou une tête inconnue
après un préfixe supporté pour provoquer une vraie erreur de frontière ; elles
ne réimposent pas l'ancien rejet des têtes de nouvelles livraisons inconnues.
Le manifeste de sources du test #186 est réépinglé aux trois sources modifiées,
sans changer de workflow, de gate, de rapport ni de politique de campagne.

Aucun test réel, dispatch/rerun, accès Hoben/HA, commande ou écriture Modbus,
changement main, automation ou fusion par CODEX. Les deux validations réelles
#207 et D2/D3 restent des étapes MANAGER distinctes. Tests réels NOT RUN.
