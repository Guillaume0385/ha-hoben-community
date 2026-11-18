# Réception DataUpdated et récupération locale — #160 / #219-A

Décision propriétaire du 30/10/2026, **option B**, dans
[l’Issue #160](https://github.com/Guillaume0385/ha-hoben-community/issues/160).
Cette politique est un choix de récupération, sans validation réelle revendiquée.

## #219-005 — incrément sûr et preuve de mapping manquante

La [décision du 18/11/2026](https://github.com/Guillaume0385/ha-hoben-community/issues/219#issuecomment-6980810892)
autorise le raccordement DataUpdated→entités et l'initialisation V4 unique,
avec suppression du polling, **sous condition de mappings justifiés**. Elle
remplace les interdictions historiques d'étape 2 figurant plus bas. Cet incrément
ne prétend pas achever ce raccordement : il livre seulement la partie sûre
indépendante des valeurs, le drop des candidats invalides.

Pour un vrai read commençant par `0x1B`, framer vide, transport/génération
encore possédés par l'unique RX, le candidat entier est analysé une fois.
`incomplete/malformed/unsupported/ambiguous` ou exception du parseur : abandon
de toute la livraison, diagnostic structurel fermé, pas de garde silence #160,
pas de sonde, TX supplémentaire, timeout crédité ni reconnexion causée par
cette seule erreur. `parser_failure` n'expose ni exception ni contenu reçu.
Un Ping, un candidat valide ou un vrai `0x0E` dans les **reads suivants** restent
traités normalement. Aucun suffixe du candidat abandonné n'est réinjecté.

Les frontières non admissibles restent soumises à la garde #160 historique :
`0x1B` après un message délimité dans le même read ou dans le résidu d'ouverture.
Un vrai `0x0E` partiel garde ses continuations, même commençant par `0x1B`.
Les erreurs transport/TLS et d'ownership, les trois demandes #212 et la preuve
de cleanup #192 restent distinctes. Aucun affaiblissement d'intégrité #186 :
seules les empreintes du parseur et de la session modifiés sont actualisées.

### Limite de preuve à soumettre au MANAGER

L'[analyse statique existante, révision ad977f5](https://github.com/Guillaume0385/MyHOBEN_extract/blob/ad977f506d9eaa1fd000094bd1a8ea091c9105eb/analysis/data_updated_spec_apk34.md)
établit la chaîne `0x1B → UInt16 → FFFF → UpdateApplicatif`, mais qualifie
encore FFFF/04/20 de `v4_applicative_candidate` et demande la validation du
contrat réel avant publication HA. Les réponses n'embarquent pas d'adresse de
départ. Le protocole et le logger de cette base gardent `mapping=unverified`.
Une égalité de nombres synthétiques ou une longueur de vingt mots ne prouve
pas la correspondance des champs.

La consigne récente évoque des observations privées de températures/consigne/
ventilation, sans table des positions effectivement corroborées ni provenance
de version chargée. La preuve attendue est une **table expurgée** : index
DataUpdated, champ V4 accepté, conversion, qualification et référence de
l'analyse ; aucun nombre domestique, RX, GUID ou octet opaque requis. Les
champs composés 1030/1033/1042 ne sont pas promus. Aucun accès HA réel par DEV
n'est utilisé pour combler cette lacune. Signalement [#6980951060](https://github.com/Guillaume0385/ha-hoben-community/issues/219#issuecomment-6980951060).

En attendant cette preuve, tous les DataUpdated restent sans effet sur les
snapshots, entités, listeners et fraîcheur HA. **Le polling V4 existant est
conservé** : le supprimer avant de disposer d'une source mappée démontrée ne
remplirait pas l'objectif d'acquisition. La lecture initiale unique, l'absence
de polling et la publication HA demandées restent donc **non implémentées**,
à reprendre dans la même PR après décision MANAGER. Les règles de fraîcheur/
disponibilité existantes ne sont ni réinitialisées ni annoncées comme validées
pour un futur mode push.

Tests RED→GREEN nouveaux : candidats tronqués/MBAP/PDU/suffixes/unsupported,
exception ou retour invalide du parseur, vingt invalides puis valide sur la
même TLS, Ping/Pong, attente V4 non créditée par 1B, pas de sonde même après
301 s de silence, EOF réel/cleanup/générations et unload. Les tests historiques
de la garde utilisent maintenant un `0x07` délimité avant `0x1B` : cas toujours
non admissible, sans TX ajouté ni option runtime de contournement. Les cas de
fragments/suffixes admissibles sont mis à jour pour la nouvelle décision ;
aucun test n'est désactivé. Diagnostics et fixtures exclusivement synthétiques.
Live Hoben / HA installé : **NOT RUN** ; réussite globale #219-005 non revendiquée.

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

Depuis #219-005, les candidats `incomplete`, `malformed` ou `ambiguous` sont
consommés sans scan et abandonnés sans garde. Aucun suffixe Ping/0x0E coalescé après
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

## Hypothèse de silence historique, conservée aux frontières non admissibles

Seule la politique d’entrée HA (`ha_reconnect=True`) active cette extension du
gestionnaire partagé. Les campagnes, clients bornés et codecs gardent leurs
contrats antérieurs. Depuis #219-005, seule la frontière non admissible déclenche
encore cette garde ; le candidat admis au début d'un read puis rejeté par le
parseur n'y entre plus :

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

## #219-S — shadow catégoriel initial, sans correspondance prouvée

Le mapping V4 existant décrit une lecture sollicitée de 1024..1043.
Le PDU DataUpdated analysé n'établit ni cette adresse de départ, ni l'ordre
sémantique de ses mots ; ses métadonnées restent opaques. Un statut
`parsed/ok`, vingt mots ou leur égalité dans une fixture ne prouvent pas
l'identité avec le snapshot V4. Aucun état d'entité ne peut en être déduit.

Le chemin catégoriel de `shadow_data_updated.py` produit une décision immuable
`shadow_mapping_unproven`, avec zéro proposition. Le RX existant l'observe
sans tâche, cache, lecteur, émission ou timer supplémentaire. Aucun appel au
décodeur sémantique, aux entités, au coordinator ou aux listeners ; aucun
snapshot publié, compteur de fraîcheur ou polling n'est modifié.

Le diagnostic catégoriel est désactivé par défaut. Seul le niveau explicitement
`debug` du logger `custom_components.hoben.shadow_data_updated` l'active ;
un DEBUG général ou hérité ne suffit pas. Repasser ce logger à `info` ou
`NOTSET` arrête immédiatement l'observation, y compris après reload.
Une panne de journalisation n'affecte pas le RX. Le repli catégoriel ne contient
que la catégorie, les indicateurs fixes, zéro proposition et des compteurs
locaux bornés. Aucun identifiant d'entité, valeur, registre, contenu RX,
métadonnée opaque ou texte d'exception n'est journalisé ou retenu.

La PR #222 ne livrait aucun chemin numérique. L'autorisation distincte
#219-DU-REGISTER-LOG-003 ci-dessous permet maintenant un journal privé
**candidat**, sans lever l'absence de preuve DataUpdated→V4 (plage et ordre).
CODEX DEV ne lance aucune observation réelle pour obtenir cette preuve.

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

## #219-DU-REGISTER-LOG-003 — DEBUG numérique local privé, hypothèse candidate

L'[autorisation explicite du 17/11/2026](https://github.com/Guillaume0385/ha-hoben-community/issues/219#issuecomment-6946450542)
permet d'étiqueter les indices 0..19 comme registres V4 **candidats**
1024..1043, uniquement pour un DataUpdated admissible `parsed/ok`, transaction
FFFF, fonction 04, unité 1 et vingt UInt16. Les noms sont ceux de la table V4
de `protocol.md` ; aucune conversion physique n'est effectuée. Les adresses
ne sont pas transmises dans le PDU : `mapping=unverified`, `simulated=true`
et `source=DataUpdated` figurent sur chacune des vingt lignes.
Ni la forme de la notification, ni ce journal ne prouvent le mapping.
Les autres formes restent diagnostiquées seulement en catégories expurgées.

**Décision propriétaire du 17/11/2026 :** les identifiants de registres candidats et valeurs numériques envoyées par le poêle **peuvent être affichés en clair dans les logs Home Assistant locaux et enregistrés dans un fichier local sur le serveur HA**. Cette permission ne concerne ni GitHub, ni les CI, ni les diagnostics de support ou exports publics. GUID, identifiants de compte, secrets, métadonnées opaques et trames RX brutes restent exclus. Cette autorisation documentaire ne change pas le code déjà fusionné : dans la PR #223, le journal reste un flux de texte étiqueté DEBUG, **pas un logger Python** ; aucun LogRecord, LogRecordFactory, handler HA, stdout/stderr, fichier ordinaire ou diagnostic de support ne reçoit actuellement les couples. Le DEBUG général et le logger shadow catégoriel ne l'activent pas.
Le module ne crée aucun fichier, n'installe aucun handler et ne garde aucun
writer, candidat ou historique entre notifications/générations.

Le propriétaire doit configurer explicitement, dans le processus HA local :

```text
HOBEN_PRIVATE_DATAUPDATED_DEBUG=1
HOBEN_PRIVATE_DATAUPDATED_FIFO=/dev/shm/hoben-private/dataupdated.pipe
```

Après installation volontaire du SHA revu et démarrage HA avec ces variables,
le propriétaire seul peut ouvrir un terminal **privé dans le même conteneur** :

```sh
umask 077
mkdir -m 700 /dev/shm/hoben-private
mkfifo -m 600 /dev/shm/hoben-private/dataupdated.pipe
cat <> /dev/shm/hoben-private/dataupdated.pipe
```

Ces commandes sont une procédure propriétaire, jamais exécutée par CODEX DEV sur HA installé. **La redirection vers un fichier local ou l'affichage dans les logs HA locaux est autorisé par le propriétaire** ; cette possibilité n'est pas implémentée directement par la PR #223 et dépend de la configuration locale. Ne jamais envoyer ces valeurs dans GitHub, CI, un diagnostic de support ou un collecteur externe. Utiliser des permissions restrictives pour les fichiers locaux.
Le `<>` Linux garde la FIFO ouverte entre les notifications sans conserver
de writer dans le module HA ; Ctrl-C ferme ce lecteur privé et arrête la sortie.
Si la plateforme ne permet pas ce canal local séparé, l'implémentation actuelle reste inactive ; aucun repli automatique vers les logs HA n'est encore implémenté. Cela n'interdit pas une évolution locale explicitement autorisée. Fermer le lecteur arrête les sorties
immédiatement ; retirer le commutateur et redémarrer HA désactive aussi le chemin.
Le répertoire/FIFO peut ensuite être supprimé par le propriétaire.

Le writer exige Linux `O_PATH`, un inode FIFO appartenant à l'UID HA, mode
exact 0600, un seul lien, sans symlink. L'inode est épinglé avant ouverture
non bloquante ; son identité et ses permissions sont revérifiées. Les vingt
lignes tiennent dans une seule écriture atomique bornée à `PIPE_BUF`.
Sans lecteur, avec un lecteur lent/fermé, une erreur ou un hôte incompatible,
la notification est abandonnée sans attente, retry, rétention ou exception
publique. Les variables `CI` ou `GITHUB_ACTIONS` interdisent le journal, même
avec opt-in. Il n'existe aucun TX réseau ou lecteur RX supplémentaire.

Les tests utilisent exclusivement des FIFO temporaires et des nombres inventés,
avec vingt notifications, limites UInt16, mutations de chemin/permissions,
pression, erreurs, activation/arrêt, générations et unload. Les tests HA
vérifient l'identité des états/snapshots, la fraîcheur, les listeners, le timer
de polling, les émissions et l'absence des valeurs dans les exports de support.
Le manifeste #186 réépingle seulement le module shadow ; gates inchangés.
**Tests Hoben / HA installé : NOT RUN. #219-B reste non autorisée.**

## #219-DU-HA-DEBUG-004 — bloc dans les logs HA locaux

La [nouvelle tâche autorisée du 17/11/2026](https://github.com/Guillaume0385/ha-hoben-community/issues/219#issuecomment-6959464626)
ajoute une sortie directe dans `custom_components.hoben.shadow_data_updated`.
Elle ne requiert **ni FIFO, ni variable d'environnement**. L'autorisation
concerne exclusivement les logs/fichiers locaux HA du propriétaire : aucune
valeur réelle dans GitHub, CI, diagnostics exportés ou rapports de support.
Ne pas partager les logs de cette période ; aucun GUID, secret, métadonnée
opaque, RX brut ou exception arbitraire n'est ajouté, même en DEBUG.

Activation explicite dans les outils de développement HA, action :

```yaml
action: logger.set_level
data:
  custom_components.hoben.shadow_data_updated: debug
```

Désactivation des prochains blocs :

```yaml
action: logger.set_level
data:
  custom_components.hoben.shadow_data_updated: info
```

Un DEBUG du logger parent ou général ne suffit pas ; NOTSET/INFO/WARNING/ERROR
sur le logger dédié n'émettent aucun nombre. INFO arrête les futurs blocs,
sans effacer les éventuels fichiers locaux déjà écrits par la configuration HA.
Ces actions sont une procédure propriétaire après installation volontaire du
SHA revu ; CODEX DEV les teste uniquement sur le harnais HA simulé, pas sur HA installé.

Une notification admissible produit **un seul LogRecord DEBUG**, identifié par
`Hoben SHADOW SIMULATION`, `generation`, `index` et
`source=DataUpdated mapping=unverified simulated=true`. La clé structurée
`hoben_shadow.candidate_registers` contient vingt objets avec `index` 0..19,
`register_candidate` 1024..1043, `name` de référence et `raw_value` UInt16.
Le même tableau JSON compact figure dans le texte après `candidate_registers=`,
donc il est lisible dans les logs HA sans dépendre du rendu des champs `extra`.
Le message complet est borné à 4096 octets, sans découpage en vingt records.

Les conditions restent FFFF/04, unité 1, vingt UInt16 et contexte de génération
valide. Autres formes/contexte inconnu : repli catégoriel seulement. Les nombres
ne sont ni convertis en mesures physiques ni associés à des entités :
`proposals=0` conserve son sens de zéro proposition d'état HA.
**Les adresses sont candidates et non transmises dans le PDU ; le mapping
reste non prouvé.** Aucun snapshot, fraîcheur, listener, polling ou TX modifié.

Le chemin FIFO #003 reste indépendant, avec ses propres opt-in, contrôles et
refus en CI. Activer le logger n'active pas le FIFO, et inversement. Aucun cache
ou replay des blocs n'est ajouté ; arrêt/reload/changement de génération ne
rejouent pas d'anciennes valeurs. Les exports de diagnostic HA restent sur leur
projection expurgée, sans ces LogRecords.
L'empreinte shadow seule est réépinglée pour revue explicite MANAGER #186 ;
aucune logique de gate ni workflow changé. **Live / HA installé : NOT RUN.**
