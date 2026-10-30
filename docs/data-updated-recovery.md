# DataUpdated ignoré et récupération locale — #160

Décision propriétaire du 30/10/2026, **option B**, dans
[l’Issue #160](https://github.com/Guillaume0385/ha-hoben-community/issues/160).
Cette politique est un choix de récupération, sans validation réelle revendiquée.

## Réception normale

À la frontière post-ouverture admise par le chemin persistant existant, le framer
attend cinq octets d’enveloppe puis six octets MBAP. Protocole nul et Length
dans 2..254 donnent exactement `11 + Length` octets. Le corps est consommé sans
décodage de registre ni interprétation des quatre octets opaques. Les suffixes
et leur propriétaire d’échange sont conservés. Une notification ne complète
jamais une lecture 0x0E, ne produit aucun snapshot et ne déclenche aucun listener
HA. Une fragmentation normale n’active pas la récupération.

## Hypothèse de silence explicitement autorisée

Seule la politique d’entrée HA (`ha_reconnect=True`) active cette extension du
gestionnaire partagé. Les campagnes, clients bornés et codecs gardent leurs
contrats antérieurs. Un en-tête DataUpdated dont le MBAP est invalide déclenche :

1. Un WARNING par épisode : type DataUpdated, raison fermée `invalid_length`
   ou `invalid_protocol`, Length annoncé (UInt16), hypothèse `silence_30s`.
   Aucun octet opaque, identifiant, registre ou texte d’exception n’est publié.
2. Une phase explicite de récupération sur le **même TLS** : arrêt du décodage
   et des nouvelles lectures ordinaires. L’unique RX abandonne immédiatement
   les livraisons de cette phase, au plus 4096 octets chacune, sans accumulation
   ni recherche de signature. Toute réception non vide réarme le silence.
3. Après **30 secondes monotones consécutives sans RX**, purge du framer,
   invalidation de l’ancien waiter et une seule sonde V4 : lecture existante
   fonction 04, transaction FFFF, unité 1, registres 1024..1043. L’ancien appel
   ne peut recevoir le succès de cette sonde. Une acquisition nouvelle en
   attente peut observer son résultat validé ; s’il arrive entre deux appels,
   l’appel suivant peut le consommer une seule fois, sans lecture supplémentaire
   ni répétition d’un résultat déjà publié.
4. Seule une réponse 0x0E complète, liée à ce nouvel échange, avec transaction,
   unité, fonction et vingt registres validés, permet la reprise. Une réponse
   invalide, une exception Modbus ou l’expiration de la sonde ne donne aucun
   snapshot ; retour en récupération. Échec de sonde diagnostiqué au plus une
   fois par épisode, sans codes reçus ni payload.

La sonde expire en 30 s et il n’y a jamais plus d’une sonde active ni plus
d’une sonde par 30 s. Le délai reste glissant selon le dernier RX non vide ;
des données continues peuvent donc empêcher toute sonde. Chaque appel externe
reste borné par son délai existant et reçoit une erreur typée de différé si la
récupération n’a pas abouti. Aucun timer d’inactivité n’est ajouté au mode sain.
La mémoire retient un état fixe, un résultat, un waiter et une tâche de sonde,
sans historique RX. Arrêt, annulation et changement de génération invalident
ces propriétaires ; aucun timer ancien ne peut écrire après fermeture.

**Limite de preuve :** 30 s de silence ne prouvent ni une frontière universelle
ni l’origine serveur d’une réponse tardive. La transaction applicative FFFF
reste celle du contrat existant. La validation repose sur l’hypothèse autorisée,
la purge et le nouvel échange local ; elle ne démontre pas qu’une ancienne
réponse complète avec le même identifiant ne pourrait jamais arriver tard.
Les 48 octets du préfixe OpenedClient ne deviennent pas une longueur universelle.

## Valeurs Home Assistant et vraies erreurs

Pendant un différé, le coordinator garde son précédent objet de données,
`last_update_success=false` et une erreur structurée `data_updated_recovery`.
Il ne renvoie pas l’ancien snapshot comme une nouvelle acquisition et n’appelle
pas ses listeners pour republier les anciennes valeurs. Les entités conservent
ces valeurs et leur disponibilité pour ce seul différé. Une vraie acquisition
validée rétablit le succès et peut publier les nouvelles valeurs.

Une perte réelle de transport/TLS, une erreur permanente ou l’arrêt demandé
met fin à cette conservation ; les règles de disponibilité et de reconnexion HA
existantes s’appliquent. La récupération locale ne masque pas ces erreurs.
Au premier setup, aucune valeur n’est inventée : l’entrée attend une acquisition
valide sur son même client, avec appels bornés et annulation possible.

Tests synthétiques : fragmentation/concaténation, silence glissant, données
continues, sondes refusées/expirées, waiter ancien, annulation/générations,
maintien HA sans faux rafraîchissement et perte réelle pendant la récupération.
**Tests réels : NOT RUN.** Aucun accès serveur, écriture Modbus, commande poêle,
nouvelle émission DataUpdated ou modification des budgets expérimentaux.
