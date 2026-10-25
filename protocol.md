# Spécification non officielle du protocole HOBEN / MyHOBEN

**Cible :** développement d'une intégration Home Assistant pour poêles HOBEN (dont HOBEN Osmose)  
**Source analysée :** application Android MyHOBEN 2.2, build 34 (`com.inovalp.myhoben`)  
**Date de l'analyse :** 30 septembre 2026, approfondie le 4 octobre 2026  
**Statut :** rétro-ingénierie statique de l'application officielle ; aucune commande n'a été envoyée au poêle pendant l'analyse.

> Cette documentation est non officielle. Les informations marquées **CONFIRMÉ** proviennent directement du code IL de MyHOBEN/HobenCore, sauf mention explicite d'une confirmation dynamique en production. Les éléments **À VALIDER** sont ceux qui nécessitent une capture réelle sur un poêle afin de confirmer la sémantique ou l'unité. Pour une première intégration Home Assistant, le mode lecture seule est recommandé par défaut.
>
> **Rôle de ce fichier :** `protocol.md` décrit ce qui est techniquement connu du protocole. La roadmap, l'architecture du projet et le calendrier d'exposition des fonctionnalités sont définis dans `project.md`, qui prévaut en cas d'ambiguïté sur ces sujets. La présence d'une commande ou d'un registre dans ce document ne signifie donc pas qu'il doit être exposé immédiatement dans Home Assistant.

---

## 1. Résumé de l'architecture

MyHOBEN ne dialogue pas directement avec le poêle lorsqu'il est utilisé via Internet. L'application établit une connexion vers l'infrastructure HOBEN.

### Serveur utilisateur

- Hôte : `myhoben.fr`
- Port production TLS : `465`
- Port production TCP non TLS / mode forcé : `433`
- Port test TLS : `9002`
- Port test TCP : `9003`
- Protocole normal : TCP protégé par TLS (`SslStream` dans l'application)
- Nom TLS/SNI utilisé par l'application : `myhoben.fr` (`AuthenticateAsClient("myhoben.fr")`)
- Validation certificat : le callback observé refuse la connexion lorsqu'une erreur de certificat TLS est signalée ; aucun contournement de validation n'a été trouvé dans ce chemin utilisateur
- Timeout de connexion observé dans ce chemin : **5 secondes**

**Recommandation Home Assistant : utiliser exclusivement `myhoben.fr:465` avec vérification normale du certificat TLS et du nom `myhoben.fr`.**

### API installateur séparée

L'application contient également une API HTTP(S) distincte sur le port `5177` (`https://myhoben.fr:5177/api/`). Cette API n'est pas le canal principal utilisé par l'utilisateur MyHOBEN pour lire/piloter le poêle. Elle est liée aux fonctions installateur/parc.

---

## 2. Empilement des protocoles

La communication utilisateur suit trois couches :

```text
TLS/TCP
  └── Message MyHOBEN : 1 octet de type + charge utile
        └── pour DataRequestClient/DataResponseClient : trame Modbus TCP
```

### Encapsulation MyHOBEN — CONFIRMÉ

Lors d'un envoi normal via TLS, `TcpConnection.WriteDataThread` construit :

```text
[ message_type : uint8 ][ payload : N octets ]
```

Il n'y a **pas de champ longueur MyHOBEN supplémentaire** dans la fonction d'écriture observée. Pour une requête Modbus utilisateur :

```text
0x0D + <trame Modbus TCP>
```

`0x0D` = `DataRequestClient` (13).

Le code de lecture reçoit les données directement depuis le flux TLS et examine le premier octet comme type MyHOBEN.

### Réponses Modbus

- `DataResponseClient = 14 (0x0E)` : le code saute **1 octet** puis donne le reste au décodeur Modbus.
- `DataUpdated = 27 (0x1B)` : le code saute **5 octets** avant le décodeur Modbus. Les quatre octets intermédiaires sont des métadonnées de notification serveur ; leur sémantique exacte reste **À VALIDER** par capture réelle.
- `DataResponseServer = 7` est également traité comme une réponse contenant des registres.

### Réception expérimentale 07/1B sans interprétation du corps — périmètre autorisé

La [demande propriétaire #112](https://github.com/Guillaume0385/ha-hoben-community/issues/112#issuecomment-6388642026)
autorise le framer de session expérimentale à ignorer **exactement** ces deux
enveloppes : préfixe de 1 octet pour `0x07`, de 5 pour `0x1B`, puis MBAP.
La longueur totale est respectivement `7 + MBAP.length` ou `11 + MBAP.length`.
L'identifiant de protocole doit être nul et Length entre 2 et 254 inclus :
totaux 9–261 et 13–265 octets. Le framer conserve au plus les en-têtes nécessaires,
puis compte les octets restants sans décoder Unit ID, fonction, registres ou
métadonnées. Une fragmentation ne crée aucune nouvelle frontière ; un corps
incomplet n'est jamais compté comme message entièrement ignoré.

C'est une décision de traitement limitée au chemin expérimental, **pas une
validation réelle**, une interprétation de notification ni une mise à jour HA.
Ping et DataResponseClient corrélée gardent leurs traitements. Les autres types
connus non pris en charge sont refusés après le seul discriminant, avec erreur
typée et numéro public ; CloseClient garde son chemin spécifique. Un type inconnu,
MBAP invalide ou suffixe ambigu ne permet jamais de saut ou resynchronisation.
Cette règle ne prouve aucune longueur universelle d'OpenedClient.

---

## 3. Types de messages MyHOBEN

Valeurs extraites de `HobenCore.MessageType` :

| Déc. | Hex | Nom |
|---:|---:|---|
| 0 | 00 | OpenStove |
| 1 | 01 | OpenedStove |
| 2 | 02 | CloseStove |
| 3 | 03 | OpenClient |
| 4 | 04 | OpenedClient |
| 5 | 05 | CloseClient |
| 6 | 06 | DataRequestServer |
| 7 | 07 | DataResponseServer |
| 8 | 08 | NewPairing |
| 9 | 09 | NewHomeGuid |
| 10 | 0A | Ping |
| 11 | 0B | Pong |
| 12 | 0C | Info |
| 13 | 0D | DataRequestClient |
| 14 | 0E | DataResponseClient |
| 15 | 0F | DataRequestInstaller |
| 16 | 10 | DataResponseInstaller |
| 17 | 11 | NewInstallerAssoRequest |
| 18 | 12 | NewInstallerAssoResponse |
| 19 | 13 | OpenRemoteControl |
| 20 | 14 | OpenedRemoteControl |
| 21 | 15 | CloseRemoteControl |
| 22 | 16 | OpenInstall |
| 23 | 17 | OpenedInstall |
| 24 | 18 | CloseInstall |
| 26 | 1A | StoveConnected |
| 27 | 1B | DataUpdated |
| 28 | 1C | DataRequestMaker |
| 29 | 1D | DataResponseMaker |
| 30 | 1E | AskAuthRemoteControl |
| 31 | 1F | CancelAuthRemoteControl |
| 32 | 20 | RemoteControlAuthStatus |
| 33 | 21 | AskAuthRemoteControlAck |
| 34 | 22 | CancelAuthRemoteControlAck |
| 35 | 23 | OpenMaker |
| 36 | 24 | OpenedMaker |
| 37 | 25 | SendCmd |
| 38 | 26 | SendCmdAck |
| 39 | 27 | CloseMaker |
| 40 | 28 | DataReqStove |
| 41 | 29 | DataResStove |
| 42 | 2A | AskNewClient |
| 43 | 2B | CancelAskNewClient |
| 44 | 2C | AskNewClientStatus |
| 45 | 2D | AskNewClientAck |
| 46 | 2E | CancelAskNewClientAck |
| 47 | 2F | DeviceAuthReq |
| 48 | 30 | DeviceAuthRes |
| 80 | 50 | FirstConnReq |
| 81 | 51 | FirstConnResp |
| 82 | 52 | NewPublicIdReq |
| 83 | 53 | NewPublicIdResp |
| 84 | 54 | OpenStoveV4 |
| 85 | 55 | OpenedStoveV4 |
| 86 | 56 | CloseStoveV4 |
| 87 | 57 | Ping_V4 |
| 88 | 58 | Pong_V4 |
| 96 | 60 | InternalCloseDemand |

### Keepalive — CONFIRMÉ

Si le client reçoit :

```text
0A
```

il répond immédiatement :

```text
0B
```

soit `Ping (10)` → `Pong (11)`.

### Cycle post-`OpenedClient` persistant — OBSERVÉ statiquement, validation réelle encore partielle

L'analyse statique de MyHOBEN **2.2 build 34** montre que, dans le chemin
utilisateur, la connexion TLS n'est pas destinée à être fermée après chaque
lecture applicative. Après traitement d'un `OpenedClient`, l'application
conserve la connexion et sa boucle `ReadLoopAsync` continue de lire sur le même
flux. Cette boucle traite notamment :

- `Ping (0x0A)` et répond `Pong (0x0B)` ;
- `DataResponseClient (0x0E)`, dont le premier octet MyHOBEN est retiré avant
  décodage Modbus ;
- `DataUpdated (0x1B)`, dont cinq octets MyHOBEN sont retirés avant décodage
  Modbus.

Le `UserGuid` appartient à la construction d'`OpenClient` ; il n'est pas
présent dans ces messages post-ouverture. Le `DeviceGuid` attribué par
`OpenedClient` est conservé pour une future ouverture/reconnexion.

**Portée de cette preuve :** cela établit le cycle visé par cette version de
l'application MyHOBEN et justifie l'architecture de session persistante. Cela ne
prouve pas encore, sur l'Osmose de référence, la durée maximale d'une session
silencieuse, la cadence serveur des Ping, une politique de timeout d'inactivité,
la sémantique de reconnexion après chaque type d'erreur, ni la longueur totale
universelle d'`OpenedClient`. Ces points restent à valider sans inventer de
comportement.

La boucle de l'application observée effectue des lectures du flux et traite le
bloc retourné comme directement exploitable ; cela **ne constitue pas** une
preuve que TCP/TLS respecte les frontières des messages. Le client communautaire
doit donc conserver son propre buffer et ses règles de framing déterministes.

Aucun APK, DLL, identifiant réel ou capture privée n'est publié dans cette
documentation.

---

## 4. Ouverture de session MyHOBEN

### Origine et normalisation du `UserGuid` — CONFIRMÉ

Dans l'écran **« Ajout d'un nouveau poêle »**, l'utilisateur renseigne un nom
usuel et un **« Identifiant HOBEN »**, soit au clavier, soit en scannant le QR
code. L'analyse statique montre que cet identifiant est la source de
`Stove.UserGuid`.

Le chemin observé est :

```text
Identifiant HOBEN saisi ou scanné
        ↓
suppression des tirets "-"
        ↓
validation comme GUID
        ↓
stockage dans Stove.UserGuid
        ↓
suppression des tirets avant ConnectToServer
        ↓
UserGuid réseau : 32 caractères hexadécimaux ASCII
```

Le résultat du scan QR suit le même chemin que la saisie manuelle : aucun token
QR distinct, hash, chiffrement ou identifiant dérivé n'a été trouvé. Le
**nom usuel du poêle n'intervient pas dans l'ouverture de session** ; il sert à
l'affichage local dans l'application.

Conséquence pour l'intégration : l'entrée utilisateur à demander est
l'**Identifiant HOBEN** imprimé/affiché pour le poêle. Le client peut accepter
une représentation GUID avec ou sans tirets, mais la valeur envoyée dans
`OpenClient` doit être normalisée en **32 caractères hexadécimaux sans tirets**.

### `DeviceGuid` initial et persistance — CONFIRMÉ

Le `DeviceGuid` identifie le client (application/téléphone), pas le poêle.

Lorsqu'aucun DeviceGuid n'a encore été attribué au client, MyHOBEN initialise
la valeur avec l'équivalent de :

```text
Guid.Empty.ToString().Replace("-", "")
= 00000000000000000000000000000000
```

Les **32 zéros sont donc la valeur initiale normale d'un nouveau client**. Ils ne
doivent pas être documentés comme un DeviceGuid volontairement invalide.

Après une ouverture/autorisation réussie, `ManageOpened` lit le DeviceGuid
renvoyé dans `OpenedClient` aux offsets 14..45. Si cette valeur diffère de celle
enregistrée localement, MyHOBEN la met à jour et la conserve pour les connexions
suivantes. Le cycle attendu est donc :

```text
nouveau client
DeviceGuid = 32 zéros
        ↓ OpenClient / éventuelle autorisation
serveur Hoben
        ↓ OpenedClient
DeviceGuid attribué par le serveur
        ↓
persistance locale puis réutilisation aux connexions suivantes
```

### Réutilisation du DeviceGuid sur l'Osmose de référence — CONFIRMÉ dynamiquement le 2026-10-04

La validation authentifiée MANAGER de la [PR #22](https://github.com/Guillaume0385/ha-hoben-community/pull/22),
sur le SHA `420e0d16a3640af03671c79f5ad78da1e2a271a2`
([run réussi](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/37205061347)),
a effectué deux rafraîchissements avec la **même instance de HobenClient**
sur l'Osmose de référence, via `myhoben.fr:465` avec TLS vérifié.

La première connexion utilise le DeviceGuid initial nul. Le DeviceGuid renvoyé
par le premier `OpenedClient` est adopté en mémoire, puis la première session
est fermée après une lecture V4 réussie. Sur une **seconde connexion TLS fraîche**,
le client réutilise automatiquement cette identité attribuée ; le serveur
répond par un **OpenedClient valide**, puis la lecture V4 suivante réussit.
Chacun des deux rafraîchissements reçoit exactement **20 registres UInt16 bruts**.
Le rapport expurgé indique `device_guid_reuse: "validated"` et `refresh_count: 2`.

**La valeur du DeviceGuid et les autres identifiants réels ne sont pas publiés.**
Cette observation est limitée à l'Osmose de référence testé à cette date : elle
ne prouve pas le comportement de tous les modèles Hoben, la longueur complète
d'OpenedClient ni la signification physique des registres V4.

### Identifiants utilisés

MyHOBEN utilise donc :

- le **MyHOBEN User GUID** du poêle (`Stove.UserGuid`), issu de l'Identifiant HOBEN et envoyé sans tirets ;
- un **DeviceGuid** du client, initialement nul (32 zéros) puis attribué/persisté depuis `OpenedClient` ;
- la version/build de l'application ;
- une chaîne descriptive du terminal.

Le UserGuid, le DeviceGuid attribué et tout code d'autorisation doivent être
considérés comme sensibles et ne doivent pas être inscrits dans les logs Home
Assistant.

### Payload `OpenClient` (type 3) — CONFIRMÉ

La construction observée dans `ConnectToServer` est, dans cet ordre :

```text
UTF8(UserGuid)
+ 00 01
+ build_LSB build_MSB
+ UTF8(DeviceGuid)
+ UTF8(DeviceInfo)
```

`DeviceInfo` est une chaîne de la forme :

```text
Manufacturer/Model/Idiom/Platform/OSVersion/Width/Height/Density/Orientation/0,0
```

Le paquet envoyé est donc :

```text
03 + payload_OpenClient
```

Le build Android analysé est 34, donc les deux octets de build sont little-endian :

```text
22 00
```

La nouvelle analyse du chemin d'ajout de poêle lève les deux inconnues précédentes :

- `UserGuid` est envoyé sous forme de **32 caractères hexadécimaux ASCII sans tirets** ;
- pour un nouveau client, `DeviceGuid` vaut **32 caractères ASCII `0`** ;
- après association, le `DeviceGuid` renvoyé par le serveur est réutilisé.

Le début d'un `OpenClient` de première association a donc la disposition
déterministe suivante :

```text
03
+ UserGuid ASCII[32]
+ 00 01
+ build UInt16 little-endian
+ DeviceGuid ASCII[32]   # "000...000" pour un nouveau client
+ DeviceInfo UTF-8       # jusqu'à la fin du message
```

### Réponse `OpenedClient` (type 4) — CONFIRMÉ

`ManageOpened` lit les champs suivants dans la réponse complète :

```text
offset 0    : 04 = OpenedClient
...
offset 7    : révision produit
offset 8    : type/carte produit
offset 9    : version logicielle mineure
offset 10   : version logicielle majeure
offset 14..45 : DeviceGuid ASCII, 32 octets
offset 46   : version application LSB
offset 47   : version application MSB
```

Après lecture de `offset 14..45`, MyHOBEN compare le DeviceGuid reçu à la
valeur locale et le persiste s'il a changé. C'est le mécanisme observé
d'attribution du DeviceGuid au client après la première association.

Note : le code appelle `InstantiateStove(type=octet8, product/rev=octet7, vsoftMaj=octet10, vsoftMin=octet9)`.

**À VALIDER — longueur totale :** les champs confirmés nécessitent un préfixe de
48 octets, mais cela ne prouve pas que le message complet mesure 48 octets.
Le chemin de validation ponctuelle `open_session_once()` accumule ce préfixe,
appelle `decode_opened_client()` puis ferme la connexion. Les octets suivants
déjà reçus restent non classifiés : seul leur nombre peut être rapporté, jamais
leur contenu. Ils ne sont pas interprétés comme un nouveau message.
Les Ping précédant le préfixe sont consommés un par un avec un Pong immédiat,
y compris lorsqu'ils arrivent avec le début d'OpenedClient dans une même lecture.
La sonde classe aussi `DeviceAuthReq (0x2F)` comme `authorization_required` et les
sous-codes documentés de `CloseClient (0x05)` (§5), puis ferme sans envoyer de
code d'authentification. Un sous-code absent à EOF ou inconnu reste non interprété.
Les types réellement inattendus sont rapportés uniquement par leur numéro,
sans payload ni hypothèse sur sa longueur. Aucun suffixe inconnu n'est reframé.

> **Note normative — décision de périmètre, pas preuve protocolaire :** la
> [décision #74](https://github.com/Guillaume0385/ha-hoben-community/issues/74#issuecomment-6177981552)
> et la tâche #81 permettent de préparer l'hypothèse locale opt-in `session-300`
> décrite dans [project.md](project.md#décision-de-périmètre--handoff-expérimental-session-300).
> Elle ne change ni le chemin ponctuel décrit ici ni la preuve factuelle :
> longueur totale **À VALIDER**, observations `boundary_proven=false`, validation
> fonctionnelle 300 s **NOT RUN**. La boucle cible du §16 et les observations
> H1/H2 ci-dessous ne deviennent pas des capacités validées par cette décision.

### Profil V4 actif

Le développement actuel vise uniquement V4. La règle statiquement établie dans
`StoveFactory.Create()` est `type == 5` → `StoveV4` ; `type` correspond à
`product_type` dans `OpenedClient`. Attendre cette identification avant de choisir
la cartographie ; le modèle commercial Osmose ne suffit pas. Les règles des
autres profils et leur discriminant « version » non résolu sont conservés dans
[l'archive](docs/archive-autres-versions.md). L'archivage ne change ni le sélecteur
existant ni ses tests. La frontière totale d'OpenedClient reste à valider.

### Session de l'Osmose de référence — CONFIRMÉ dynamiquement le 2026-10-04

Une observation réelle contre **`myhoben.fr:465`**, avec TLS vérifié et
l'Identifiant HOBEN configuré, a reçu `OpenedClient (0x04)` après un OpenClient
de première connexion. Les seules métadonnées publiques retenues sont :

| Champ | Valeur observée |
|---|---:|
| `product_type` | 5 |
| `product_revision` | 0 |
| `software_major` | 8 |
| `software_minor` | 2 |
| `application_version` | 512 |
| profil sélectionné dynamiquement | `v4` |
| `unclassified_bytes` déjà reçus | 0 |

Le **Hoben Osmose de référence s'identifie actuellement comme V4**. Cette
observation ne classe pas tous les Osmose comme V4 et ne prouve pas une longueur
totale universelle d'OpenedClient. La fixture de régression
`tests/fixtures/opened_client_v4_production_2026_10_04.json` contient uniquement
ces métadonnées expurgées : aucun UserGuid, DeviceGuid, secret ou octet de capture
réelle. Les tests utilisent un préfixe binaire indépendant et entièrement
synthétique pour vérifier la sélection et les offsets.

Le nouveau chemin ponctuel de lecture V4 doit refuser la lecture si cette
première observation comporte un suffixe non classifié, même s'il ressemble à
un autre message. Il exige exactement V4 et ne continue après aucune demande
d'autorisation, fermeture ou ouverture malformée. La lecture applicative réelle
des deux rafraîchissements est désormais confirmée par la validation MANAGER
documentée ci-dessus. Cette première observation de session confirme seulement
l'ouverture et le profil, sans sémantique de registre V4.

---

## 5. Association / autorisation d'un nouveau client

Le code contient les échanges :

- `AskNewClient = 42 (0x2A)`
- `CancelAskNewClient = 43 (0x2B)`
- `AskNewClientStatus = 44 (0x2C)`
- `AskNewClientAck = 45 (0x2D)`
- `CancelAskNewClientAck = 46 (0x2E)`
- `DeviceAuthReq = 47 (0x2F)`
- `DeviceAuthRes = 48 (0x30)`

### Déclenchement de la demande de code — CONFIRMÉ

Lorsque le client reçoit `DeviceAuthReq (0x2F)`, MyHOBEN ouvre une demande
utilisateur **« Code d'authentification ? »**. Cela confirme que ce message est le
signal utilisé par l'application pour demander le code d'association d'un nouveau
client.

**Marqueur `DeviceAuthReq` — analyse statique MyHOBEN, décision MANAGER du
2026-10-06 :** la nouvelle analyse du chemin
`HobenApp.Services.TcpConnection` compare le premier octet reçu à `0x2F` ;
aucun champ/payload suivant n'est décodé ou exploité pour cette demande.
Pour l'interopérabilité de ce chemin, la
[résolution MANAGER de #32](https://github.com/Guillaume0385/ha-hoben-community/issues/32#issuecomment-6020116376)
établit donc le marqueur d'un octet `2F`, sans payload supplémentaire.
La provenance est l'analyse statique de MyHOBEN 2.2 build 34
(`HobenCore` / `HobenApp`), pas une observation de première association réelle.
Aucun APK/DLL ou identifiant sensible n'est publié.

La même analyse confirme `30 + UInt16-LE(code)` puis l'attente d'OpenedClient.
Cela ne fait pas d'une lecture socket une frontière TLS générale : le parseur
doit conserver les octets coalescés après `2F`, accumuler les préfixes fragmentés
et refuser les types inconnus sans rechercher arbitrairement un `0x04`.
La longueur complète d'OpenedClient reste inconnue (§4).

L'analyse statique ne permet pas encore d'affirmer **où ni comment ce code est
présenté/généré côté poêle ou infrastructure Hoben**. Cette partie doit être
observée sur le Hoben Osmose réel avant d'automatiser le flux.

### Envoi du code d'autorisation — CONFIRMÉ

La méthode `SendDeviceAuth(code)` fabrique un payload de **2 octets
little-endian** :

```text
code_LSB code_MSB
```

et l'envoie avec le type **48 / `DeviceAuthRes`** :

```text
30 <code_LSB> <code_MSB>
```

L'application attend ensuite une réponse et peut traiter un `OpenedClient
(0x04)` comme réussite. Le DeviceGuid de ce `OpenedClient` est alors le
candidat à persister pour les connexions suivantes.

`myhoben.encode_device_auth_response(code: int) -> bytes` implémente uniquement
ce sérialiseur pur, couvert par des vecteurs synthétiques indépendants. Il accepte
un entier représentable en UInt16, sans conversion implicite de booléen, chaîne
ou flottant. Cette contrainte de représentation ne définit ni la plage de codes
acceptés par le serveur, ni un nombre de chiffres, ni leur durée de validité.
Le paquet retourné contient le code sensible et ne doit jamais être journalisé.
`HobenClient.async_associate(authorization_code_provider=...)` est le seul appel
client qui autorise explicitement cette soumission, après le marqueur `2F`.
Il partage le handshake avec la lecture existante, garde le buffer entre les
messages et traite Ping/Pong avant/après soumission. Il attend un préfixe
OpenedClient valide puis applique les vérifications existantes (profil V4 pris
en charge, absence de suffixe déjà reçu) avant d'adopter le DeviceGuid. Une
ouverture déjà autorisée ne consulte pas le fournisseur. Sans fournisseur,
l'autorisation requise reste un résultat/une erreur distincte. Les fermetures
conservent les sous-codes documentés ci-dessous.

Politique locale explicite, sans affirmation sur le serveur : un seul envoi de
code et une seule connexion, aucun retry automatique, aucune requête Modbus et
pas de stockage du code/fournisseur. Une seconde demande après soumission est
refusée sans renvoi. Le délai global existant du handshake inclut l'attente du
fournisseur et reste configurable ; il ne représente pas la durée de validité
du code. Le fournisseur est asynchrone et ses exceptions/valeurs invalides sont
expurgées sous `HobenAuthorizationCodeError`. L'annulation ferme le transport.
Le succès retourne `AssociationResult`, métadonnées publiques uniquement ; le
DeviceGuid reste accessible par le contrat de persistance sensible existant.
`async_refresh()` et les sondes ne fournissent aucun code et ne déclenchent pas
cette association. L'orchestration HA (#34) ferme d'abord le client qui constate
l'autorisation requise, puis affiche un champ masqué sans I/O active. Chaque
soumission explicite utilise un nouveau client et cette API typée existante,
sans modifier le framing ni déduire la provenance, la présentation ou la durée
de vie du code. Le code n'est pas persisté ; seule une ouverture V4 acceptée
permet l'adoption du DeviceGuid par l'entrée. Les séquences d'association et les
flux HA sont testés hors ligne ; aucune première association réelle n'est
revendiquée.

### Rejets/états `CloseClient` observés — CONFIRMÉ

Le chemin de connexion utilisateur interprète plusieurs réponses commençant par
`CloseClient (0x05)`. Les sous-codes suivants sont associés dans MyHOBEN à ces
situations :

| Trame minimale observée | Interprétation dans MyHOBEN |
|---|---|
| `05 02` | identifiant MyHOBEN/HOBEN invalide |
| `05 03` | le poêle doit être connecté au serveur pour authentifier l'application mobile |
| `05 04` | demande d'authentification rejetée |
| `05 05` | délai d'authentification dépassé |
| `05 06` | serveur en maintenance |

Ces correspondances viennent du code de l'application. **`05 02` →
`invalid_identifier` a aussi été confirmé dynamiquement en production** contre
`myhoben.fr:465` lors du test négatif avec un UserGuid synthétique/non attribué
de 32 zéros et le DeviceGuid initial normal de 32 zéros. Aucun identifiant réel
n'est publié. Les autres sous-codes restent confirmés statiquement seulement ;
leur comportement exact sur le serveur actuel reste à valider.

### Contrat expérimental CloseClient post-open — décision propriétaire, pas fait confirmé

L'arbitrage E8 tranche A du même commentaire autorise désormais le mode typé
`V4SessionMode.PERSISTENT` à réutiliser le framer et ces contrats post-open,
indépendamment des budgets Session300/SessionReconnect. Ce préalable partagé
ne raccorde pas encore le client HA. Les hypothèses OpenedClient/préfixe 48
octets et CloseClient/deux octets restent explicitement non universelles ; les
succès fonctionnels E7 sur le SHA fusionné de #122 ne changent pas cette preuve.
Voir le [contrat de ressources et API](project.md#étape-8-tranche-a--contrat-persistant-partagé).

L'[arbitrage #112 du 25 octobre 2026](https://github.com/Guillaume0385/ha-hoben-community/issues/112#issuecomment-6395141200)
autorise **exactement deux octets**, type `05` puis sous-code UInt8, dans le
framer V4 expérimental sous handoff session-300/reconnexion. Attendre le second
octet s'il est fragmenté ; conserver les octets coalescés suivants au framer,
sans les traiter après cette fermeture ni les attribuer à une nouvelle session.
Ce contrat n'établit aucune longueur universelle de CloseClient ou OpenedClient.
Les codecs d'ouverture/compatibilité restent inchangés.

Le gestionnaire émet une fermeture typée `experimental_close_client`, termine
les waiters et ferme le transport. La reconnexion utilise le budget/backoff
existant ; ni la fermeture seule ni une réouverture sans lecture V4 corrélée ne
constituent un succès. Les compteurs EOF TLS ne sont jamais incrémentés par
CloseClient. Les sous-codes, y compris inconnus, sont rapportés numériquement
dans une extension bornée ; aucun payload n'est publié. Voir le
[contrat de rapport](docs/session-suite-plan.md#closeclient-expérimental--closeclient-session-close-006).

### Flux de première association déduit du code — CONFIRMÉ statiquement / À VALIDER dynamiquement

```text
Identifiant HOBEN
        ↓ normalisation GUID sans tirets
UserGuid[32]

DeviceGuid non encore attribué
        ↓
00000000000000000000000000000000

        ↓ TLS + OpenClient

serveur
   ├─ 04 OpenedClient
   │      → connexion ouverte
   │      → persister DeviceGuid reçu
   │
   ├─ 2F DeviceAuthReq
   │      → demander le code à l'utilisateur
   │      → envoyer 30 + UInt16-LE(code)
   │      → attendre OpenedClient ou rejet
   │
   └─ 05 xx CloseClient
          → traiter le sous-code connu sans retry agressif
```

La structure de ce flux est confirmée par le code MyHOBEN. L'ordre exact des
messages du serveur de production, le mécanisme d'obtention du code et les délais
réels doivent encore être validés sur le poêle.

### Recommandation pour l'intégration

Prévoir un `config_flow` capable de :

1. demander l'**Identifiant HOBEN** et le normaliser en UserGuid de 32 caractères sans tirets ;
2. charger un DeviceGuid déjà persisté, ou utiliser **32 zéros** pour un nouveau client ;
3. envoyer `OpenClient` ;
4. si `DeviceAuthReq (0x2F)` est reçu, afficher une seconde étape demandant le code ;
5. envoyer `DeviceAuthRes (0x30)` avec le code sur 2 octets little-endian ;
6. sur `OpenedClient`, persister le DeviceGuid renvoyé par le serveur ;
7. présenter proprement les rejets `05 02` à `05 06` sans boucle de reconnexion agressive.

Ne jamais journaliser le UserGuid, le DeviceGuid complet ou le code
d'association au niveau INFO/debug partageable.


---

## 6. Couche Modbus TCP

Le code Hoben embarque un générateur Modbus TCP standard.

### MBAP — CONFIRMÉ

`CModbusTCP.addTcpProtocoleParameters()` génère :

```text
Byte 0-1 : Transaction ID, big-endian
Byte 2-3 : Protocol ID = 0x0000
Byte 4-5 : Length = taille(PDU Modbus) + 1, big-endian
Byte 6   : Unit ID / adresse esclave
Byte 7.. : PDU Modbus
```

Le `Unit ID` utilisé par MyHOBEN est **1**.

### Limites Modbus standard — NORMATIF

Source : [MODBUS Application Protocol Specification V1.1b3](https://www.modbus.org/file/secure/modbusprotocolspecification.pdf),
sections **4.1** (taille du PDU et de l'ADU TCP), **4.4** (adressage),
**6.3** (fonction 03) et **6.4** (fonction 04).
Ces contraintes viennent du standard Modbus ; elles ne sont pas des hypothèses
sur les registres ou les capacités d'un poêle Hoben.

- Un PDU contient au moins le code fonction et au maximum **253 octets**.
- Le champ MBAP `Length` compte le Unit ID et le PDU : **2 à 254 octets**.
  L'ADU Modbus/TCP complet fait donc au maximum **260 octets** (6 + 254),
  sans compter une éventuelle enveloppe MyHOBEN.
- Les lectures 03 et 04 portent sur **1 à 125 registres**.
- Les adresses du PDU vont de **0 à 65535**. La dernière adresse demandée,
  `address + quantity - 1`, doit rester dans cet espace ; le codec rejette donc
  `address + quantity > 65536`, même si chaque champ est représentable séparément.

Le codec valide ces limites à l'encodage et au décodage MBAP, ainsi que la
quantité et la fin de plage lors de la construction des requêtes de lecture.
La lecture applicative V4 documentée ci-dessous (20 registres) respecte ces limites standard. Les autres profils sont décrits dans [l'archive](docs/archive-autres-versions.md).

### Requête lecture

Le PDU interne de lecture est :

```text
function
address_hi address_lo
quantity_hi quantity_lo
```

Fonctions utilisées :

- `03` Read Holding Registers
- `04` Read Input Registers

### Réponses de lecture 03/04 — NORMATIF

Source : MODBUS Application Protocol Specification V1.1b3 (lien ci-dessus),
sections **6.3**, **6.4** et **7** (réponses d'exception).
Le PDU d'une réponse normale contient :

```text
function (03 ou 04)
byte_count
register_1_hi register_1_lo ... register_N_hi register_N_lo
```

`byte_count` vaut exactement `2 × N`, avec **1 à 125 registres** : il est donc
non nul, pair et au plus égal à **250**. Le PDU contient exactement
`2 + byte_count` octets, sans données supplémentaires. Chaque registre est un
**UInt16 big-endian**, conservé brut par le codec, sans conversion signée ou physique.

Une réponse d'exception contient exactement **deux octets** :
`function | 0x80` (`83` ou `84` en hexadécimal), puis `exception_code`.
Le codec représente cette réponse séparément d'une réponse normale et conserve
le code fonction original (`03` ou `04`) ainsi que le code d'exception UInt8 brut.
Les deux types de réponse conservent les Transaction ID et Unit ID du MBAP ;
la corrélation avec une requête relève de l'opération cliente, notamment de
`open_and_read_v4_once()` pour cette lecture ponctuelle.
Ces règles sont celles de Modbus et n'ajoutent aucun fait spécifique à Hoben.

### Écriture simple — fonction 06

PDU généré par `requestWriteSingle` :

```text
06
register_hi register_lo
value_hi value_lo
```

### Écriture multiple — fonction 16 (0x10)

MyHOBEN embarque également `Fct16RequestWriteMultipleRegisters`, notamment pour les blocs de configuration/plages horaires.

### Masquage d'un registre — fonction 22 (0x16)

Le code utilise `Fct22RequestMaskWriteRegister` pour modifier certains bits sans écraser le reste du registre.

### Transaction ID utilisés par MyHOBEN

- lecture applicative principale : **65535 / `0xFFFF`** ;
- commandes utilisateur observées (marche/arrêt, température, etc.) : **65520 / `0xFFF0`**.

Le code de réception possède un traitement spécifique pour `0xFFF0`, ce qui confirme que cette valeur sert de transaction de commande.

---

## 7. Lecture des données principales

### Requête applicative V4 — CONFIRMÉ

Lecture Input Registers, fonction `04`, transaction `FFFF`, unité `01`,
adresse `1024 / 0x0400`, quantité `20 / 0x0014` :

```text
0D FF FF 00 00 00 06 01 04 04 00 00 14
```

### Réponse

Réponse typique côté MyHOBEN :

```text
0E + <réponse Modbus TCP>
```

Le décodeur vérifie le MBAP, extrait le Transaction ID, puis convertit les registres en `UInt16`.

---

## 8. Registres applicatifs et formatage des valeurs

### V4 — 20 registres 1024..1043 — CONFIRMÉ statiquement

L'analyse complémentaire de `HobenCore.dll` et `HobenApp.dll` de MyHOBEN
2.2 build 34 permet maintenant de relier les 20 registres lus par le profil V4
aux propriétés affichées par l'application. Cette cartographie est distincte de
celle des autres profils archivés.

| Adresse | Nom HOBEN V4 | Format / interprétation MyHOBEN |
|---:|---|---|
| 1024 | `erarMode_ConsigneMarchArret` | octet haut = mode V4 ; octet bas = marche/arrêt |
| 1025 | `erarTemperatureDerogation` | Int16 signé, affichage en °C après division par 10 |
| 1026 | `erarTempoStartDerogation` | temporisation de début en minutes |
| 1027 | `erarDureeDerogation` | durée en minutes |
| 1028 | `erarModeVentilation` | 0 Normal, 1 Silence, 2 Boost |
| 1029 | `erarDefautsCombustion` | code de défaut V4 |
| 1030 | `erarPuissance_Etat` | octet haut = puissance en %, octet bas = état V4 |
| 1031 | `erarTemperatureAmbianteOffseted` | température ambiante principale, Int16 / 10 °C |
| 1032 | `erarConsigneTemperatureEC` | température de consigne affichée, Int16 / 10 °C |
| 1033 | `erarModeVentilEC_ConsignePMaxEC` | champ combiné déclaré ; non recopié par `UpdateApplicatif` V4 dans ce build |
| 1034 | `erarWarnings` | bitmap de warnings |
| 1035 | `erarInformations` | bitmap d'informations/états |
| 1036 | `erarAnnee_Mois` | date poêle empaquetée |
| 1037 | `erarJourSemaineJourMois_Heures` | jour/date/heure empaquetés |
| 1038 | `erarMinutes_Secondes` | minutes/secondes empaquetées |
| 1039 | `erarTemperatureAmbianteConv` | température ambiante filaire/convertie, Int16 / 10 °C |
| 1040 | `erarTemperatureComburantConv` | température air comburant, Int16 / 10 °C |
| 1041 | `erarTemperatureFumeeConv` | température fumées, Int16 / 10 °C |
| 1042 | `erarPVIConv` | valeur PVI ; l'interface possède un affichage en mV, mais ce champ n'est pas recopié par `UpdateApplicatif` V4 analysé |
| 1043 | `erarTemperatureRFConv` | température ambiante RF, Int16 / 10 °C |

Les registres arrivent comme des UInt16 Modbus big-endian. Pour les températures,
MyHOBEN réinterprète la valeur 16 bits comme **Int16 signé**, puis son convertisseur
d'affichage applique **valeur / 10**. Le facteur `0,1 °C` est donc maintenant
**confirmé statiquement pour V4**. Le convertisseur traite `0x0FFF` / 4095 comme
une température indisponible et affiche `-.-°C`. Pour la consigne principale,
l'interface masque également les valeurs brutes inférieures à 50.

Les captures MyHOBEN fournies le 2026-10-04 montrent **23,5 °C** en température
ambiante et **19,0 °C** en consigne. Elles sont cohérentes avec des valeurs brutes
235 et 190 selon ce convertisseur, sans preuve brute simultanée pour ces captures
du 2026-10-04 : ces nombres restent des illustrations, pas des valeurs de registre
observées en production. La comparaison privée MANAGER ultérieure du 2026-10-05
a validé le jalon décodeur/entités (§8), sans publier les valeurs du foyer.

#### V4 — marche/arrêt et mode dans le registre 1024

`erarMode_ConsigneMarchArret` est un champ combiné :

```text
bits 15..8 : mode V4
bits  7..0 : OnOff
```

Décodage du mode observé dans MyHOBEN V4 :

| Octet mode | Mode affiché |
|---:|---|
| 0 | Automatic |
| 1 | Magasin |
| 2 | Manuel |
| autre | Automatic par défaut |

L'octet bas porte la valeur logique marche/arrêt 0/1.

#### V4 — puissance et état dans le registre 1030

`erarPuissance_Etat` est également combiné :

```text
bits 15..8 : puissance 0..100 %
bits  7..0 : état V4
```

La puissance est utilisée directement comme pourcentage ; l'interface ramène à
0 une valeur supérieure à 100.

Le profil V4 utilise son propre décodage d'état :

| Octet état V4 | État MyHOBEN |
|---:|---|
| 0 | Arrêt |
| 1 | Fin de combustion |
| 2 | Démarrage standard |
| 3 | Démarrage blackout |
| 4 | Stabilisation |
| 5 | Gestion combustion |
| autre | Arrêt par défaut |

Ce mapping V4 ne doit pas être remplacé par les valeurs numériques de
`EOperationState` documentées plus bas.

#### V4 — dérogation et unités

Pour V4, les registres 1025-1027 ont maintenant une unité établie par le code de
l'application :

- 1025 : température de dérogation en dixièmes de degré ; l'UI évolue par pas de
  5 unités brutes = **0,5 °C**, avec une plage utilisateur **5,0 à 30,0 °C** ;
- 1026 : temporisation de début en **minutes** ; l'application l'utilise pour
  calculer l'heure de début relativement à l'heure courante ;
- 1027 : durée en **minutes** ; l'UI évolue par pas de **15 minutes**, avec un
  maximum de **1440 minutes / 24 h**.

Attention à l'écran « Mode dérogation » : lorsque la dérogation n'est ni active
ni programmée, les valeurs visibles sont des **valeurs locales de préparation de
l'interface**, pas une preuve du contenu de 1025-1027. Dans la capture fournie,
l'application reprend la consigne courante (19,0 °C), l'heure courante (16:16) et
une durée locale par défaut de 180 minutes (03:00).

L'interrupteur d'activation est dérivé du registre 1035 `erarInformations` :

- bit 5 / masque `0x0020` : dérogation active ;
- bit 6 / masque `0x0040` : dérogation programmée.

L'interface considère la dérogation activée si l'un de ces deux indicateurs est
présent.

Le même bitmap contient aussi des états liés notamment aux vacances, hors-gel,
anti-vent, anti-condensation, arrêt externe, cycle de nettoyage, anticipation,
démarrage à chaud et fenêtre ouverte. Les positions exactes de tous ces indicateurs
ne sont pas encore consignées ici et ne doivent pas être devinées.

#### V4 — warnings, défauts et PVI

Le registre 1034 est un bitmap de warnings. Les libellés retrouvés dans
l'application couvrent notamment les sondes RF/TA/TC/PVI, une température fumées
élevée, un conduit bouché et une entrée d'air bouchée. La correspondance exacte
bit par bit doit être extraite/testée avant création d'entités diagnostiques.

Le registre 1029 porte un **code de défaut**, pas un bitmap. La table V4 de
l'application contient notamment les valeurs `360`, `362`, `364`, `365`,
`366`, `370` et `372`, avec des libellés liés aux fumées, pressostat,
thermostat, timeout d'allumage, conduit bouché et entrée d'air bouchée. La
correspondance code → libellé doit rester documentée comme incomplète tant que
l'association exacte de chaque code n'a pas été revue.

Le registre 1042 `erarPVIConv` dispose d'un convertisseur d'affichage en
**millivolts** dans l'application, mais `UpdateApplicatif` V4 ne le copie pas
dans la propriété publique utilisée par l'écran analysé. Il ne doit donc pas
encore être exposé comme mesure V4 fiable.

#### Implémentation #26 / PR #27 — validée sur l'Osmose de référence le 2026-10-05

`v4_state.py` applique cette cartographie statique à un `RawStoveSnapshot` V4 de
20 UInt16, dans un `V4StoveState` immuable indépendant de Home Assistant. Le
helper de température réinterprète Int16 et divise directement par 10 ; seul
`0x0FFF` est une sentinelle, et la consigne 1032 masque aussi les valeurs signées
inférieures à 50. Aucune plage d’édition UI n’est utilisée pour borner les mesures.

Choix explicite de l’intégration : les modes/états/ventilations non documentés,
OnOff hors 0/1 et puissance supérieure à 100 donnent `None`, avec conservation
du code brut. Elle ne reproduit pas les replis de l’interface MyHOBEN vers
Automatic, Arrêt ou zéro. Le mapping d’état reste celui de V4, sans réutiliser
`EOperationState`. Les valeurs de dérogation sont conservées dans le modèle,
mais les entités numériques les masquent si les bits 5 et 6 sont tous deux nuls.
Les défauts, champ combiné 1033, warnings, bitmap d’information complet,
date/heure et PVI restent bruts sans interprétation supplémentaire ni entité.

Les tests déterministes sont complétés par la **validation dynamique MANAGER
PASS du 2026-10-05** sur le HEAD
`288d6408d376dcec875ea09135eab800e5563b4f`, suivie de la fusion de la PR #27.
La [preuve MANAGER](https://github.com/Guillaume0385/ha-hoben-community/pull/27#issuecomment-6001144860)
confirme le chargement HA, les entités disponibles et leur comparaison privée
simultanée avec MyHOBEN : ambiance, consigne, mode, ventilation, OnOff,
état/puissance dans la phase observée, dérogation et ses temporisations.
La sonde pré-merge décode les deux snapshots déjà lus et ne rapporte qu'un
compteur de réussite ; aucune valeur du foyer n'est publiée. Cette validation
concerne uniquement l'Osmose de référence et les situations observées, sans
généralisation aux autres modèles ou aux champs encore partiels.

Le mode manuel distinct `--live-v4-validation-values` fournit cette comparaison
locale privée : un seul rafraîchissement du client existant, horodatage UTC,
20 UInt16 indexés par adresse 1024–1043 et les 16 valeurs d’entités avec leur
code brut, leur valeur décodée et leur valeur HA effective. Il conserve les
valeurs numériques de dérogation dans le modèle même lorsque les entités les
masquent. Il refuse GitHub Actions avant toute connexion et aucun workflow ne
l’appelle. Ce JSON contient des valeurs du foyer : partage volontaire seulement
en chat privé avec le MANAGER, jamais en log/artefact/commentaire public. Aucun
GUID, traceback, pairing ou écriture n’est ajouté. La disponibilité de cet outil
et ses tests hors ligne ne constituent pas à eux seuls une preuve dynamique.
Toute modification future de ce chemin nécessite sa propre revue, sa CI et la
décision de validation authentifiée MANAGER sur le nouveau HEAD.

### Zone configuration utilisateur (lecture) — attribution V4 non établie

Cette table historique est conservée sans la promouvoir en cartographie V4.
Elle ne fait pas partie de la lecture V4 confirmée des 20 registres 1024–1043 ;
son profil et ses conversions doivent être prouvés avant toute utilisation.

| Adresse | Nom |
|---:|---|
| 1536 | ercurPMaxModeVac_PMaxModeManuel |
| 1537 | ercurTemperatureModeManuel |
| 1538 | ercurTemperatureModeVacances |
| 1539 | ercurDateFinVacHeures_Minutes |
| 1540 | ercurDateFinVacMois_JourMois |
| 1541 | ercurModeFct_DateFinVacAnnee |
| 1542 | ercur_TempsAnticipation |
| 1543 | ercurUserBits |

### Historique (lecture) — profil et sémantique à valider

Les éléments suivants sont des pistes historiques, pas une lecture V4 validée.

La zone commence à `2560`. Elle contient notamment :

- temps de fonctionnement par plages de puissance ;
- nombre d'allumages ;
- date de mise en service ;
- dernier entretien ;
- derniers démarrage/arrêt ;
- compteurs moteurs ;
- nombre d'allumages ;
- statistiques annuelles ;
- poids/consommation de granulés selon version.

Ces données peuvent devenir des entités diagnostics/statistiques Home Assistant dans une seconde phase.

---

## 9. Valeurs décodées par MyHOBEN

Le modèle objet HOBEN expose au minimum :

- `OnOff`
- `TempAmbient`
- `TempRF`
- `TempDerogation`
- `TempSmoke`
- `TempAirComburant`
- `TempConsigneEC`
- `DurationDerogation`
- `TempoDerogation`
- `Power`
- `ModeVentil`
- `PVI`
- `OperationState`
- `OperationMode`
- `MAF`
- défauts combustion
- warnings
- infos
- défaut système
- défaut communication
- défaut sondes 1/2
- défaut moteur

### États de fonctionnement génériques — CONFIRMÉ

`EOperationState` expose les états du modèle objet commun. **Le profil V4 ne
place pas directement ces numéros dans son octet d'état** : utiliser la table V4
du registre 1030 en §8 pour les 20 registres applicatifs V4.

`EOperationState` :

| Valeur | État |
|---:|---|
| 0 | Attente |
| 1 | Arret |
| 2 | Demarrage |
| 3 | Stabilisation |
| 4 | Modulation |
| 5 | FinDeCombustion |
| 6 | DemarrageStandard |
| 7 | DemarrageBlackout |
| 8 | GestionCombustion |

### Modes du modèle objet commun — CONFIRMÉ statiquement

Ces numéros ne sont pas les octets du mode V4 du registre 1024 (voir §8),
ni une liste de valeurs autorisées à écrire dans le registre V4 1285.
`Magasin` et `ManuelTest` ne doivent jamais devenir des contrôles utilisateur.

`EOperationMode` :

| Valeur | Mode |
|---:|---|
| 0 | Direct |
| 1 | Manuel |
| 2 | Automatic1 |
| 3 | Automatic2 |
| 4 | Magasin |
| 5 | ManuelTest |
| 6 | Automatic |

### Ventilation — CONFIRMÉ

`EModeVentil` :

| Valeur | Mode |
|---:|---|
| 0 | Normal |
| 1 | Silence |
| 2 | Boost |

### Températures — formatage par profil

Dans `HobenCore`, les températures applicatives sont lues comme **Int16 signé**
(`ReadTempKey`). Cette routine conserve la valeur brute ; la conversion physique
peut donc être appliquée plus haut dans l'application.

Pour **V4**, l'analyse de `HobenApp.dll` confirme que le convertisseur d'affichage
utilisé par MyHOBEN applique **Int16 / 10**, soit une résolution de **0,1 °C**.
La valeur `4095 / 0x0FFF` est traitée comme indisponible par l'affichage. Cette
règle s'applique aux températures V4 identifiées en §8, notamment ambiance,
consigne, dérogation, air comburant, fumées et RF.

Ce facteur de température concerne les champs V4 identifiés. Les règles des autres profils sont archivées.

---

## 10. Commandes d'écriture utilisateur V4 — documentation statique, aucune exécution

**Interdiction :** les tests et l'intégration actuels restent en lecture seule. Les commandes ci-dessous décrivent les chemins statiquement identifiés dans MyHOBEN pour V4, **pas** des commandes autorisées ou vérifiées sur le poêle. Les détails des profils non V4 (registres 1283–1286 dans d'autres usages, 1792–1801, modes techniques et exemples associés) sont conservés dans [l'archive](docs/archive-autres-versions.md).

### 10.1 Marche / arrêt normal

Le registre **1280 / 0x0500** figure dans la cartographie V4. **À VALIDER pour V4 :** l'utilisation de la fonction Modbus `06`, le champ `erawConsigneMarchArret`, l'encodage `OnOff XOR 1` et l'identifiant de transaction `0xFFF0` sont décrits pour V6/V6v16 dans [l'archive](docs/archive-autres-versions.md), mais aucune preuve spécifique V4 n'établit leur application à V4. Ne pas en déduire une trame d'écriture V4 ni implémenter une commande. Toute demande future d'arrêt devra respecter l'arrêt normal du contrôleur, **jamais** couper l'alimentation électrique.

### 10.2 Température de dérogation

Registre V4 **1281 / 0x0501** ; la valeur est codée en dixièmes de °C (190 = 19,0 °C), pas d'interface de 5 unités (0,5 °C), plage d'interface observée de 50 à 300 (5,0 à 30,0 °C). La correspondance vient du chemin statique d'affichage/édition MyHOBEN ; pas de validation d'écriture réelle.

### 10.3 Temporisation de dérogation

Registre V4 **1282 / 0x0502** ; unité **minute** dans le calcul MyHOBEN du début de dérogation relatif à l'heure courante. Effet réel non testé.

### 10.4 Durée de dérogation

Registre V4 **1283 / 0x0503** ; unité **minute**, pas d'interface de 15 minutes, maximum d'interface 1440 minutes (24 h). Effet réel non testé.

### 10.5 Ventilation

Le registre **1284 / 0x0504** est documenté dans la cartographie V4 pour la ventilation. L'interface documente 0 = Normal, 1 = Silence, 2 = Boost. **À VALIDER pour V4 :** l'utilisation de la fonction Modbus `06` et son encodage d'écriture ne sont pas démontrés par une source spécifique V4 ; la méthode `SetModeVentil` et la fonction `06` sont décrites dans le contexte V6/V6v16 de [l'archive](docs/archive-autres-versions.md). Ne pas en déduire une trame d'écriture V4. Aucun essai réel et aucune commande autorisée.

### 10.6 Mode direct et options

La cartographie V4 documente **1285** pour le mode de fonctionnement direct et **1286** pour les options utilisateur. Les valeurs et effets V4 sont **À VALIDER** ; ne pas reprendre les modes `Magasin`/`ManuelTest` ou les champs 1792–1801 d'autres profils.

### 10.7 Zones exclues

Les registres **1287–1293** sont techniques/moteur/test ; la zone installateur commence à **2304**. Ils ne doivent jamais être exposés ni écrits par l'intégration. Les fonctions Modbus d'écriture **06/16/22** et la transaction applicative **0xFFF0** sont interdites dans les tests live et expérimentaux.

---

## 11. Cartographie V4 des commandes — documentation statique uniquement

La cartographie V4 est différente des autres versions. Les adresses ci-dessous sont documentées à partir des chemins de MyHOBEN et **ne constituent pas une autorisation d'écriture ni une validation dynamique** :

| Fonction V4 | Registre V4 | État |
| --- | ---: | --- |
| Marche / arrêt normal | 1280 | Documentation statique, jamais exécutée par les tests |
| Température de dérogation | 1281 | Documentation statique, dixièmes de °C |
| Temporisation de dérogation | 1282 | Documentation statique, minutes |
| Durée de dérogation | 1283 | Documentation statique, minutes |
| Ventilation | 1284 | Documentation statique |
| Mode de fonctionnement direct | 1285 | Cartographie V4, valeurs/effets à valider |
| Options utilisateur | 1286 | Cartographie V4, bits/effets à valider |

Les registres techniques/test 1287–1293 et la zone installateur 2304+ sont exclus de toute exposition/écriture. La lecture applicative V4 documentée porte sur 20 registres à partir de 1024. Les cartographies des autres versions sont conservées dans [l'archive](docs/archive-autres-versions.md). **Aucune commande physique n'est autorisée.**

## 12. Décodage recommandé côté Home Assistant

Cette section décrit une **organisation possible pour le prototype initial**. Elle ne remplace pas l'architecture de référence définie dans `project.md`. Le code protocolaire doit conserver des frontières suffisamment propres pour être extrait vers la bibliothèque indépendante `pyhoben` lorsque la couche de lecture sera stable.

Architecture Python possible pendant le prototypage :

```text
custom_components/hoben/
├── __init__.py
├── manifest.json
├── config_flow.py
├── const.py
├── protocol.py       # TLS + messages MyHOBEN
├── modbus.py         # MBAP/PDU encode/decode
├── stove.py          # profil de base
├── stove_v4.py
├── coordinator.py
├── sensor.py
├── binary_sensor.py
├── switch.py
├── select.py
└── climate.py        # seulement après validation de l'échelle température
```

### `protocol.py`

Responsabilités :

- ouvrir TLS vers `myhoben.fr:465` ;
- envoyer `OpenClient` ;
- gérer `OpenedClient` ;
- répondre `Pong` à `Ping` ;
- gérer reconnexion et timeout ;
- envoyer `0x0D + modbus_frame` ;
- router `0x0E` et `0x1B` vers le décodeur Modbus ;
- gérer le workflow d'association sans écrire de secrets dans les logs.

### `modbus.py`

Constructeur minimal :

```python
def mbap(transaction_id: int, unit_id: int, pdu: bytes) -> bytes:
    length = len(pdu) + 1
    return (
        transaction_id.to_bytes(2, "big")
        + b"\x00\x00"
        + length.to_bytes(2, "big")
        + bytes([unit_id])
        + pdu
    )


def read_input_registers(tx: int, start: int, quantity: int) -> bytes:
    pdu = b"\x04" + start.to_bytes(2, "big") + quantity.to_bytes(2, "big")
    return mbap(tx, 1, pdu)


def write_single_register(tx: int, address: int, value: int) -> bytes:
    pdu = b"\x06" + address.to_bytes(2, "big") + (value & 0xFFFF).to_bytes(2, "big")
    return mbap(tx, 1, pdu)
```

Envoi MyHOBEN :

```python
writer.write(bytes([13]) + modbus_frame)
await writer.drain()
```

### Gestion des lectures TCP/TLS

L'application officielle suppose qu'un `ReadAsync` fournit une unité de message exploitable. Une implémentation Home Assistant doit être plus robuste :

- accumuler les octets dans un buffer ;
- reconnaître les messages simples à un octet (`Ping`) ;
- pour les réponses Modbus, utiliser le champ `Length` MBAP pour déterminer la longueur complète ;
- gérer le cas où plusieurs messages arrivent dans une même lecture TLS ou si une trame est fragmentée.

Pour `DataResponseClient` :

```text
1 octet MyHOBEN + 6 octets MBAP avant Unit ID + Length MBAP
```

La longueur Modbus totale vaut `6 + MBAP.length`.

Pour `DataUpdated`, il faut retirer les 5 premiers octets avant de lire le MBAP. La signification des 4 octets après `0x1B` reste à valider, mais ils peuvent être ignorés pour le parsing Modbus si le format reste constant.

---

## 13. Entités Home Assistant proposées

Cette section suit la roadmap de `project.md`.

### v0.1.x — lecture seule

À créer en premier :

- température ambiante ;
- température fumées ;
- température air comburant si pertinente ;
- température consigne/dérogation lue ;
- puissance/niveau de puissance ;
- état de fonctionnement ;
- mode de fonctionnement ;
- mode ventilation ;
- connexion poêle/serveur ;
- warnings ;
- défauts ;
- PVI si exploitable ;
- diagnostics Wi-Fi en catégorie diagnostic.

Aucune entité de cette version ne doit envoyer de commande au poêle.

### v0.2.x — température et contrôles utilisateur validés

Après validation réelle :

- commande de température/dérogation ;
- durée de dérogation si son unité et sa sémantique sont validées ;
- `select` ventilation 0/1/2 ;
- `select` mode parmi les modes utilisateur pertinents ;
- confirmation par lecture après écriture ;
- limitation de fréquence et gestion des commandes rejetées.

Une entité `climate` peut être introduite pendant cette phase seulement lorsque les points suivants sont validés :

- échelle exacte des températures ;
- mode qui correspond à la consigne utilisée ;
- plage min/max autorisée ;
- comportement de la dérogation ;
- retour d'état après écriture.

### v0.3.x — marche/arrêt normal du contrôleur

Après validation dédiée du registre 1280 :

- commande ON via le contrôleur HOBEN ;
- commande OFF via le contrôleur HOBEN en conservant son cycle normal d'arrêt ;
- confirmation d'état après commande ;
- gestion des timeouts/rejets sans boucle de retry agressive.

Le registre 1280 est documenté plus haut pour l'interopérabilité, mais son exposition Home Assistant appartient à cette phase, conformément à `project.md`.

---

## 14. Stratégie de sécurité pour les écritures

Une intégration Home Assistant ne doit jamais :

- couper l'alimentation secteur du poêle ;
- écrire dans les registres moteurs/test (`1287+`) ;
- écrire dans la configuration installateur (`2304+`) ;
- écrire des paramètres fabricant ;
- contourner les sécurités internes HOBEN ;
- envoyer des commandes en boucle rapidement.

Règles recommandées :

1. la v0.1.x est strictement en lecture seule ;
2. à partir de la v0.2.x, n'exposer que les commandes explicitement prévues par la roadmap et déjà validées ;
3. conserver une whitelist stricte des registres utilisateur ;
4. limiter la fréquence des commandes ;
5. effectuer une lecture de confirmation après chaque écriture ;
6. en cas de réponse Modbus d'erreur, ne pas réessayer en boucle ;
7. conserver le cycle d'arrêt normal du poêle ;
8. ne jamais exposer les modes test/installateur ;
9. si une option utilisateur « Autoriser le pilotage » est retenue par le projet, elle doit être explicite et désactivable, mais son existence reste une décision d'architecture définie dans `project.md`.

---

## 15. Points encore à valider sur le HOBEN Osmose réel

La rétro-ingénierie statique permet maintenant de décrire beaucoup plus
précisément la première connexion. Les validations dynamiques restantes doivent
être réalisées sans commande de chauffage et en commençant par l'ouverture de
session :

1. **frontière complète d'OpenedClient** : l'ouverture réelle avec UserGuid
   configuré et DeviceGuid initial nul a reçu `0x04` le 2026-10-04, sans suffixe
   déjà reçu ; la longueur totale universelle, dont un suffixe arrivant plus tard,
   reste à établir ;
2. **association réelle** : le marqueur `DeviceAuthReq` est établi pour le chemin
   d'interopérabilité par analyse statique (§5) ; déterminer comment le code
   demandé par MyHOBEN est présenté/généré et
   confirmer la séquence `2F → 30 + code → 04` ;
3. **étendre les observations V4** : le jalon #26 / PR #27 est validé et fusionné
   depuis le 2026-10-05 sur l'Osmose de référence (§8). Les autres modèles et
   situations non observées restent non confirmés ;
4. **bitmaps V4 incomplets** : terminer la correspondance bit par bit de
   `erarWarnings` et `erarInformations`, ainsi que la table exacte code →
   libellé de `erarDefautsCombustion` ;
5. **champs V4 encore partiels** : préciser le packing date/heure 1036-1038 et
   la sémantique réellement exploitable de 1033 et 1042 ;
6. contenu des **4 octets de métadonnées de `DataUpdated`**.

Les deux premières validations concernent l'ouverture/association du client.
Elles restent différées par la décision de portée du 2026-10-07 dans `project.md`,
sauf le handoff local strictement nécessaire à la session persistante. Cette
liste d’inconnues n’autorise aucune nouvelle expérience.
Toute capture destinée au dépôt doit être anonymisée avant publication.


---

## 16. Séquence minimale pour un prototype lecture seule

La sonde ne met pas encore en œuvre tout le flux d'association décrit ci-dessous.
`session-open` reste une observation ponctuelle sans Modbus. Après l'ouverture
V4 confirmée, `read-v4-state` prépare une seule lecture brute documentée (§7),
dans l'ancienne voie manuelle `main`, puis fermeture. Cette description est
historique ; les seuls lancements actuels suivent le
[workflow expérimental](docs/experimental-protocol-workflow.md) et ses gates.
Il ne met pas en œuvre la boucle de lecture ni les entités proposées ci-dessous.

### Première association d'un client

```text
1. Obtenir l'Identifiant HOBEN saisi/scanné par MyHOBEN
2. Normaliser UserGuid = GUID sans tirets, 32 caractères ASCII
3. Charger DeviceGuid persisté ; si absent, utiliser 32 zéros
4. TLS connect myhoben.fr:465 avec validation normale du certificat
5. SEND 03 + OpenClient(UserGuid, build, DeviceGuid, DeviceInfo)
6. Répondre 0B à tout Ping 0A nécessaire
7. Si RX 2F DeviceAuthReq :
      demander le code à l'utilisateur
      SEND 30 + code UInt16 little-endian
8. Si RX 05 xx CloseClient :
      classer le sous-code connu et fermer sans retry agressif
9. WAIT 04 OpenedClient
10. Parse profil poêle + DeviceGuid
11. Persister le DeviceGuid reçu
12. Fermer la sonde ponctuelle, ou seulement ensuite démarrer la session lecture seule
```

### Session lecture seule après ouverture réussie

```text
1. Démarrer boucle de lecture
2. Si RX 0A -> SEND 0B
3. SEND 0D + ModbusTCP(FFFF, unit=1, func=04, start=1024, qty=20 pour V4)
4. RX 0E + Modbus response
5. Décode registres
6. Publie entités Home Assistant
7. Accepte RX 1B (DataUpdated), retire 5 octets puis décode Modbus
```

Cette boucle est une cible après handoff prouvé, pas une capacité validée du
client actuel. Un candidat de 54 octets ne suffit pas à identifier `DataUpdated`
ni à autoriser une mise à jour de l’état (voir les tâches 1 et 5 de `project.md`).

Aucune étape d'association ne doit déclencher une commande de fonctionnement du
poêle.


---

## 17. Exemples de trames

La requête de lecture V4 complète figure au §7. Les exemples historiques
marche/arrêt, ventilation et modes des autres profils sont conservés avec
leurs adresses et qualifications dans [l'archive](docs/archive-autres-versions.md).
Ils ne sont pas des instructions d'exécution.

## 18. Niveau de confiance

### Confirmé par désassemblage IL

- serveur/ports ;
- TLS ;
- encapsulation 1 octet MyHOBEN + payload ;
- message types ;
- Ping/Pong ;
- origine de `Stove.UserGuid` depuis l'Identifiant HOBEN saisi/scanné ;
- normalisation du UserGuid en 32 caractères hexadécimaux sans tirets ;
- DeviceGuid initial = `Guid.Empty` sans tirets (32 zéros) ;
- persistance du DeviceGuid reçu dans `OpenedClient` ;
- structure générale OpenClient ;
- champs majeurs OpenedClient ;
- déclenchement `DeviceAuthReq (0x2F)` et réponse `DeviceAuthRes (0x30)` avec code UInt16-LE ;
- marqueur `DeviceAuthReq` d'un octet pour le chemin d'association reproduit,
  sans champ supplémentaire exploité, selon l'analyse statique examinée par le
  MANAGER le 2026-10-06 (§5) ;
- interprétation des rejets `CloseClient` sous-codes `02` à `06` ;
- sélection V4 par `product_type == 5` ; autres règles et limites dans l’archive ;
- MBAP Modbus TCP ;
- Unit ID 1 ;
- fonctions Modbus 03/04/06/16/22 ;
- lecture V4 : fonction 04, adresse 1024, 20 registres ;
- lecture V6/V6v16 : fonction 04, adresse 1024, 110 registres (archive) ;
- cartographie V4 des 20 registres 1024..1043 dans `UpdateApplicatif` ;
- champs V4 combinés 1024 (mode + marche/arrêt) et 1030 (puissance + état) ;
- températures V4 interprétées en Int16 et affichées avec un facteur /10 ;
- ventilation V4 0/1/2 = Normal/Silence/Boost ;
- dérogation V4 : température en dixièmes de degré, temporisation/durée en minutes ;
- bits 5/6 de `erarInformations` pour dérogation active/programmée ;
- valeur température indisponible `0x0FFF` dans le convertisseur d'affichage V4.

### Observé dans l'interface MyHOBEN fournie

- affichage 23,5 °C en température ambiante et 19,0 °C en consigne le 2026-10-04,
  cohérent avec le format V4 /10 mais sans capture brute simultanée ;
- écran de dérogation inactif affichant 19,0 °C, l'heure courante et 03:00 :
  ces valeurs sont des valeurs locales de préparation lorsque les bits
  active/programmée sont absents, pas une lecture prouvée de 1025-1027.

### Confirmé dynamiquement en production

- réception d'OpenedClient sur l'Osmose de référence le 2026-10-04 : type 5, révision 0,
  logiciel 8.2, version application 512, profil sélectionné V4 ;
- zéro octet non classifié déjà reçu après le préfixe, sans preuve d'une longueur
  totale universelle d'OpenedClient ;
- adoption en mémoire du DeviceGuid renvoyé par le premier OpenedClient, puis
  réutilisation réussie sur une seconde connexion TLS avec le même HobenClient,
  réception d'un second OpenedClient valide et deux lectures V4 de 20 registres
  réussies sur l'Osmose de référence le 2026-10-04 (§4) ;
- test négatif précédemment observé avec UserGuid synthétique nul : `CloseClient 05 02`,
  `invalid_identifier`.

Le jalon V4 #26 / PR #27 a aussi reçu une validation dynamique MANAGER PASS
le 2026-10-05, avec comparaison privée simultanée des entités et de MyHOBEN sur
l'Osmose de référence (§8). Les valeurs privées n'ont pas été publiées ; les
champs partiels et situations non observées restent inconnus. Cette validation,
comme la réutilisation observée du DeviceGuid, ne prouve pas un support universel
de tous les modèles Hoben. Une première association avec code reste à valider.

---

## Observations de protocole V4 — OBSERVÉ / À VALIDER

Provenance documentaire : [comparaison MANAGER du 13 octobre 2026](https://github.com/Guillaume0385/ha-hoben-community/pull/77#issuecomment-6154916025)
et [revue des rapports anonymisés](https://github.com/Guillaume0385/ha-hoben-community/pull/77#pullrequestreview-5509930190).
Cette synthèse conserve les observations déjà consignées ; elle ne revendique
ni nouvelle capture ni nouvelle lecture d'un artefact expiré.

| Campagne | Source conservée | Sessions |
| --- | --- | --- |
| [#38036834012](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/38036834012), tentative 1 | Rapport #11665220212 examiné par MANAGER | 6 H1 + 6 H2 |
| [#38145162358](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/38145162358), tentative 1 | Constat expurgé de la PR ; l'ancien artefact a1 n'était plus listé après rerun | 6 H1 + 6 H2 |
| Même run, tentative 2 | Rapport #11848055922 examiné par MANAGER | 6 H1 + 6 H2 |

Les deux tentatives du run #38145162358 portent sur le même SHA
`ba007baf42f5120ce9b26aada95231c3930ca449`. Les 18 sessions par mode incluent
la tentative 1 attestée par son constat documentaire, pas trois artefacts
actuellement disponibles.

- **OBSERVÉ H1, 18/18 :** lectures TLS de 48, puis 1, puis 2 octets,
  octets tardifs vers 30/60 s, EOF vers 61 s sans lecture V4 ni Pong.
  Ce sont des tailles de lectures, pas des frontières de messages ; la causalité
  « absence de Pong → déconnexion » n'est pas démontrée.
- **OBSERVÉ sous H2, 18/18 :** après le préfixe V4 de 48 octets, deux
  réponses candidates de 50 octets corrélées aux deux lectures V4, puis deux
  candidats d'un octet vers un intervalle de 30 s, avec deux Pong émis sous
  hypothèse H2. Leur confiance reste `h2_hypothesis_only`.
- **OBSERVÉ sous H2, 2/18 :** candidat supplémentaire de 54 octets :
  run #38036834012, pause 0,1 s, répétition 1, offset 150 vers 89,962 s ;
  run #38145162358 tentative 2, pause 0,1 s, répétition 2, offset 148 vers
  52,989 s. Absent des six H2 de la tentative 1. Position et temps variables.
- **À VALIDER :** frontière totale d'`OpenedClient`, identification des
  candidats `Ping` et `DataUpdated`, métadonnées et segmentation indépendante.
  Les rapports restent `inconclusive` / `boundary_proven=false`. Ne pas
  interpréter ni jeter 54 octets sans framing sûr ; ne pas promouvoir les
  annotations `notification_h2` en fait. La recherche discriminante reste
  [#74](https://github.com/Guillaume0385/ha-hoben-community/issues/74).
