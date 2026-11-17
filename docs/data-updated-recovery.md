# Réception DataUpdated et récupération locale — #160 / #219-A

Décision propriétaire du 30/10/2026, **option B**, dans
[l’Issue #160](https://github.com/Guillaume0385/ha-hoben-community/issues/160).
Cette politique est un choix de récupération, sans validation réelle revendiquée.

## Réception HA par livraison — #219-A

L'[étape 1 de #219](https://github.com/Guillaume0385/ha-hoben-community/issues/219)
remplace le framing MBAP de la notification pour la seule politique HA qui
active #160. L'unique RX reçoit un candidat entier lorsque son vrai read
commence par `0x1B`, après ouverture et avec framer vide. Le candidat n'est
ni assemblé sur plusieurs reads ni découpé selon MBAP.Length. Ce choix local
ne démontre aucune frontière TLS/message : `read_delivery`,
`boundary_proven=false` dans tous les rapports.

Le parseur pur contrôle enveloppe/MBAP/PDU et les réponses Modbus 03/04 ou
exceptions documentées. Les quatre métadonnées restent opaques ; données,
identifiants et valeurs décodées demeurent internes, sans correspondance
aux entités ni au snapshot V4. Les fonctions inconnues restent `unsupported`.
Le [contrat et les cinq statuts](../protocol.md#réception-ha-dataupdated-par-livraison--hypothèse-locale-219-a)
distinguent structure interne et hypothèse de frontière.

Les candidats `incomplete`, `malformed` ou `ambiguous` sont consommés sans scan
puis entrent dans la garde ci-dessous. Aucun suffixe Ping/0x0E coalescé après
`0x1B` ne peut être crédité. Un Ping/0x0E déjà délimité avant la notification
garde son ordre et son échange ; la notification qui suit n'est pas un nouveau
read et déclenche la garde sans assemblage MBAP. Le framer d'un vrai 0x0E
partiel garde ses octets de continuation, y compris un premier octet `0x1B`.
Les résidus d'ouverture ne bénéficient jamais de la nouvelle convention.

Chaque candidat produit un événement DEBUG `hoben_data_updated` : compteur
saturant par tentative, génération, taille réellement livrée, sections et
présence des champs, cohérence, raison fermée et nombre de valeurs. Aucun
contenu brut, métadonnée opaque, ID, adresse, valeur domestique ou texte
arbitraire n'est journalisé, même en repli. La saturation n'arrête ni RX ni
les événements. Une erreur du handler de log ne change pas la politique RX.
Dans la garde, une livraison commençant par `0x1B` produit un état ambigu
`recovery_discarded` sans examiner son contenu ni prouver son type.

## Contrat antérieur conservé pour campagnes/clients bornés

Sans activation de la politique HA, le framer conserve l'ignorance exacte de
`11 + MBAP.Length` octets après validation de l'en-tête et des bornes 2..254.
Les tests de fragmentation/concaténation de cette voie restent inchangés.
Une notification ne complète jamais une lecture 0x0E, ne produit aucun
snapshot et ne déclenche aucun listener HA sur l'une ou l'autre voie.

## Hypothèse de silence explicitement autorisée

Seule la politique d’entrée HA (`ha_reconnect=True`) active cette extension du
gestionnaire partagé. Les campagnes, clients bornés et codecs gardent leurs
contrats antérieurs. Un candidat DataUpdated rejeté (ou une frontière non admissible) déclenche :

1. Un WARNING par épisode : type DataUpdated, raison fermée du parseur/de la frontière, Length
   annoncé lorsqu’il est disponible (UInt16), hypothèse `silence_30s`.
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

## Validation de l'étape 1 et suite

Les tests #219-A sont entièrement synthétiques : livraison, parsing, champs
expurgés, fragments/coalescences, échanges adjacents, générations et absence
de mutation HA. Le polling périodique et les réessais #212 restent actifs.
Après revue MANAGER et fusion sur experimental, seule une observation passive
volontaire du propriétaire sur HA, avec SHA chargé prouvé, pourra apporter
les preuves réelles. **Étape 2 non attribuée ; aucune fin du polling ni mise
à jour des entités par DataUpdated dans cette PR. Live / HA réel : NOT RUN.**

## #219-S — shadow limité faute de correspondance prouvée

Le mapping V4 existant décrit une lecture sollicitée de 1024..1043.
Le PDU DataUpdated analysé n'établit ni cette adresse de départ, ni l'ordre
sémantique de ses mots ; ses métadonnées restent opaques. Un statut
`parsed/ok`, vingt mots ou leur égalité dans une fixture ne prouvent pas
l'identité avec le snapshot V4. Aucun état d'entité ne peut en être déduit.

Le module `shadow_data_updated.py` produit uniquement une décision immuable
`shadow_mapping_unproven`, avec zéro proposition. Le RX existant l'observe
sans tâche, cache, lecteur, émission ou timer supplémentaire. Aucun appel au
décodeur sémantique, aux entités, au coordinator ou aux listeners ; aucun
snapshot publié, compteur de fraîcheur ou polling n'est modifié.

Le diagnostic catégoriel est désactivé par défaut. Seul le niveau explicitement
`debug` du logger `custom_components.hoben.shadow_data_updated` l'active ;
un DEBUG général ou hérité ne suffit pas. Repasser ce logger à `info` ou
`NOTSET` arrête immédiatement l'observation, y compris après reload.
Une panne de journalisation n'affecte pas le RX. Chaque événement ne contient
que la catégorie, les indicateurs fixes, zéro proposition et des compteurs
locaux bornés. Aucun identifiant d'entité, valeur, registre, contenu RX,
métadonnée opaque ou texte d'exception n'est journalisé ou retenu.

L'exception propriétaire du 17 novembre pour un DEBUG numérique local ne
constitue pas une preuve de mapping : aucun chemin de journal numérique n'est
implémenté ici. La simulation numérique demandée reste **bloquée** jusqu'à
une preuve revue de la correspondance DataUpdated→V4 (plage et ordre).
La suite exige un arbitrage MANAGER et les preuves autorisées ; CODEX DEV ne
lance aucune observation réelle pour les obtenir.

Les tests synthétiques couvrent au moins vingt messages, l'égalité trompeuse
avec un V4, les invalides/fragments/coalescences, l'activation et l'arrêt,
les générations, le cleanup et l'absence de publication HA ou de TX ajouté.
L'étape #219-B et la suppression du polling restent non autorisées.
Live / HA installé : **NOT RUN**.

L'[arbitrage MANAGER du 17/11](https://github.com/Guillaume0385/ha-hoben-community/pull/222#issuecomment-6943374521)
autorise le raccordement d'intégrité #186 : ajout du seul module shadow à
FILES/manifeste et actualisation des empreintes session/module/routeur. Les
autres champs, empreintes et toute logique d'admission restent identiques.
Les tests refusent une modification synthétique ou l'omission du module ;
cette conformité des sources ne prouve aucun mapping ni admission live.
