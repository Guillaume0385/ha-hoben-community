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

### Choix de l'implémentation poêle — CONFIRMÉ

`StoveFactory.Create()` utilise les valeurs retournées lors de l'ouverture :

- `type == 5` → `StoveV4`
- `type == 2`, révisions 0/1 et vsoftMaj 0 → `StoveV6`
- `type == 2`, révision 2 et vsoftMaj 0 → `BoilerV6_230`
- `type == 3`, révision 0, vsoftMaj 0/1 → `StoveV6`
- `type == 3`, révision 1, vsoftMaj 0/1, version <= 5 → `StoveV6`
- `type == 3`, révision 1, vsoftMaj 0/1, version > 5 → `StoveV6v16`

Dans `OpenedClient`, `type` correspond à `product_type`, la révision à
`product_revision` et `vsoftMaj` à `software_major`. Ces correspondances permettent
de sélectionner les quatre cas non ambigus ci-dessus.

**À VALIDER — discriminant « version » :** le champ comparé au seuil 5 dans les
deux règles `type == 3`, révision 1, vsoftMaj 0/1 n'est pas identifié explicitement.
La documentation et l'historique du dépôt ne prouvent pas qu'il s'agit de
`software_minor`, de `application_version` ou d'un autre champ. La liste des
arguments d'`InstantiateStove` ci-dessus ne suffit pas à établir ce lien avec la
comparaison dans `StoveFactory.Create()`.

Tant que ce lien n'est pas prouvé, `select_stove_profile()` retourne `UNKNOWN`
pour cette branche, quelles que soient les valeurs de `software_minor` et
`application_version`. Les deux règles V6/V6v16 restent documentées en attente de
validation du champ. Toute autre combinaison non documentée retourne également
`UNKNOWN`. Le sélecteur renvoie uniquement un identifiant `StoveProfile`, sans
cartographie ni comportement de poêle ; le DeviceGuid n'intervient jamais dans
la sélection et n'est pas journalisé.

Le plugin Home Assistant doit donc **attendre `OpenedClient` et sélectionner dynamiquement la cartographie**, plutôt que supposer que l'Osmose est V6/V6v16.

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
Les lectures applicatives V4 (20 registres) et V6/V6v16 (110 registres) documentées
ci-dessous respectent ces contraintes.

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

### Requête applicative V6 / V6v16 — CONFIRMÉ

`StoveV6.GetRegApplicatif()` et `StoveV6v16.GetRegApplicatif()` font une lecture **Input Registers / fonction 04** :

```text
Transaction ID : FFFF
Unit ID        : 01
Function       : 04
Start address  : 1024 = 0x0400
Quantity       : 110  = 0x006E
```

Trame Modbus TCP :

```text
FF FF 00 00 00 06 01 04 04 00 00 6E
```

Trame MyHOBEN/TLS complète :

```text
0D FF FF 00 00 00 06 01 04 04 00 00 6E
```

### Requête applicative V4 — CONFIRMÉ

Même principe, mais seulement 20 registres :

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
celle V6/V6v16.

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
235 et 190 selon ce convertisseur, mais aucune capture brute simultanée n'a encore
été enregistrée : ces nombres ne doivent donc pas être présentés comme des valeurs
de registre observées en production.

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

### V6/V6v16 — zone applicative (lecture, base 1024)

| Adresse | Nom HOBEN | Utilité HA |
|---:|---|---|
| 1024 | erarConsigneMarchArret | état/consigne marche-arrêt |
| 1025 | erarTemperatureDerogation1 | température dérogation 1 |
| 1026 | erarTempoStartDerogation1 | départ dérogation 1 |
| 1027 | erarDureeDerogation1 | durée dérogation 1 |
| 1028-1036 | dérogations 2 à 4 | programmation/dérogations |
| 1037 | erarPuissance_Etat | puissance + état, champ combiné |
| 1038-1039 | erarDefautsCombustion1/2 | défauts combustion |
| 1040-1041 | erarWarnings1/2 | avertissements |
| 1042-1043 | erarInformations1/2 | informations |
| 1044 | erarAnnee_Mois | date poêle |
| 1045 | erarJourSemaineJourMois_Heures | date/heure |
| 1046 | erarMinutes_Secondes | minute/seconde |
| 1047 | erarConfigMiseAJour | indicateur config |
| 1048 | erarTemperatureCorpsConv | température corps convertie |
| 1049 | erarTemperatureFumeeConv | température fumées convertie |
| 1050 | erarValeurVBatConv | tension batterie/convertie |
| 1051 | erarTensionEntreeConv | tension entrée |
| 1052 | erarELogiquesTOR | entrées logiques |
| 1053 | erarConsigneMoteurVis | moteur vis |
| 1054 | erarConsigneMoteurAirPrim | air primaire |
| 1055 | erarConsigneMoteurAirSec | air secondaire |
| 1056 | erarConsigneMoteurExchanger | échangeur/ventilation |
| 1057 | erarConsigneMoteurNettoyage | nettoyage |
| 1058 | erarSortiesTOR | sorties TOR |
| 1059 | erarDefautsMoteurs | défauts moteurs |
| 1060-1061 | erarDefautsSondes1/2 | défauts sondes |
| 1062 | erarDefautsCommAcc | défaut communication accessoires |
| 1063 | erarInfoStart | infos démarrage |
| 1064 | erarCommandes | commandes |
| 1065 | erarResultats | résultats |
| 1070-1072 | Wi-Fi état/type | diagnostic Wi-Fi |
| 1090+ | CE Hydro / sondes / accessoires | données supplémentaires selon modèle |
| 1123 | erarCESondeRFExtTemperature | température sonde RF externe |
| 1125/1127/1129/1131 | sondes RF ambiantes 1..4 | températures zones |
| 1133 | erarCEPelletDetectLevel | niveau/détection granulés si présent |
| 1134-1137 | fréquences moteurs | diagnostics |

### Zone configuration utilisateur (lecture)

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

### Historique (lecture)

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

### Modes — CONFIRMÉ

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

Pour **V6/V6v16**, ne pas généraliser automatiquement ce facteur tant que le
chemin d'affichage correspondant n'a pas été établi ou confirmé sur une capture
réelle.

---

## 10. Commandes d'écriture utilisateur

Toutes les commandes ci-dessous sont **CONFIRMÉES dans HobenCore** pour `StoveV6` et `StoveV6v16` sauf mention contraire.

### 10.1 Marche / arrêt

Méthode HOBEN : `SetOnOff`

- Function Modbus : `06`
- Register : **1280 / `0x0500`**
- Nom : `erawConsigneMarchArret`
- Valeur observée côté application : l'interface bascule `OnOff XOR 1`, donc valeurs logiques **0/1**.
- Transaction ID application : `0xFFF0`

Requête ON (`value=1`) :

```text
MBAP/PDU : FF F0 00 00 00 06 01 06 05 00 00 01
MyHOBEN  : 0D FF F0 00 00 00 06 01 06 05 00 00 01
```

Requête OFF (`value=0`) :

```text
0D FF F0 00 00 00 06 01 06 05 00 00 00
```

**Sécurité :** cette commande demande au contrôleur HOBEN son arrêt normal. Elle ne coupe pas l'alimentation électrique et doit rester la seule méthode d'arrêt depuis HA.

### 10.2 Température de dérogation / consigne temporaire

Méthode : `SetTemperatureDerogation`

V6/V6v16 :

- Function : `06`
- Register : **1283 / `0x0503`**
- Nom : `erawTemperatureDerogation`
- Type transmis : valeur 16 bits (`Int16` converti en `UInt16` au niveau Modbus).

V4 :

- Register : **1281 / `0x0501`** ;
- l'UI MyHOBEN travaille en dixièmes de degré : **190 = 19,0 °C** ;
- pas utilisateur observé : **5 unités = 0,5 °C** ;
- plage UI observée : **50..300 = 5,0..30,0 °C**.

Le facteur V4 est confirmé statiquement par le chemin d'affichage/édition de
MyHOBEN. Une écriture réelle reste toutefois interdite tant que la phase de
contrôle prévue par `project.md` n'a pas été atteinte et validée par lecture de
retour. Pour V6/V6v16, l'échelle d'écriture reste à valider séparément.

### 10.3 Temporisation de dérogation

Méthode : `SetTempoDerogation`

V6/V6v16 :

- Function : `06`
- Register : **1284 / `0x0504`**
- Nom : `erawTempoStartDerogation`
- Valeur : UInt16.

V4 : registre **1282**. MyHOBEN l'interprète en **minutes** pour calculer le
début de dérogation relativement à l'heure courante.

Pour V6/V6v16, l'unité reste **À VALIDER** avant exposition comme service HA.

### 10.4 Durée de dérogation

V4 :

- **1283 / `0x0503`** ;
- unité MyHOBEN : **minutes** ;
- pas UI : **15 minutes** ;
- maximum UI : **1440 minutes / 24 h**.

V6/V6v16 :

- **1285 / `0x0505`** = `erawDureeDerogation`.

Pour V6/V6v16, l'unité reste à valider dynamiquement.

### 10.5 Mode ventilation

Méthode : `SetModeVentil`

V6/V6v16 :

- Function : `06`
- Register : **1286 / `0x0506`**
- `0` Normal
- `1` Silence
- `2` Boost

Exemple Silence :

```text
0D FF F0 00 00 00 06 01 06 05 06 00 01
```

V4 : registre **1284**.

### 10.6 Mode de fonctionnement

Méthode : `SetModeFonctionnement`

V6/V6v16 :

- Function : `06`
- Register : **1792 / `0x0700`** (`ercuwModeFonctionnement`)
- Valeurs envoyées :
  - 0 Direct
  - 1 Manuel
  - 2 Automatic1
  - 3 Automatic2
  - 4 Magasin
  - 5 ManuelTest
- Toute valeur non reconnue par la méthode est ramenée à `2`.

**Recommandation HA : ne pas exposer `Magasin` ni `ManuelTest` à l'utilisateur standard.** Ce sont des modes qui ne sont pas nécessaires au pilotage domestique normal.

### 10.7 Température mode manuel

Cartographie d'écriture V6/V6v16 :

- **1798 / `0x0706`** = `ercuwTemperatureModeManuel`

### 10.8 Puissance max mode manuel

- **1799 / `0x0707`** = `ercuwPuissMaxModeManuel`

### 10.9 Mode vacances

Registres V6/V6v16 :

- 1793 : année fin vacances
- 1794 : mois/jour fin vacances
- 1795 : heures/minutes fin vacances
- 1796 : température mode vacances
- 1797 : puissance max vacances
- 1800 : temps anticipation vacances

### 10.10 Option démarrage/arrêt automatique en mode manuel

Méthode : `SetManuelStartStopAutoOption`

- Function : **22 / Mask Write Register (`0x16`)**
- Register : **1801 / `0x0709`** (`ercuwUserBits`)
- Bit modifié : **bit 8** (`0x0100`)
- AND mask : **65279 / `0xFEFF`**
- OR mask : `0x0100` si activé, `0x0000` sinon.

Cela permet de changer uniquement ce bit sans écraser les autres options utilisateur.

---

## 11. Différences V4 à prendre en compte

La cartographie V4 n'est pas identique à V6/V6v16. Pour les commandes principales :

| Fonction | V4 | V6/V6v16 |
|---|---:|---:|
| Marche/arrêt | 1280 | 1280 |
| Température dérogation | 1281 | 1283 |
| Tempo dérogation | 1282 | 1284 |
| Durée dérogation | 1283 | 1285 |
| Ventilation | 1284 | 1286 |
| Mode fonctionnement direct | 1285 (cartographie V4) | 1792 |
| Options | 1286 | principalement zone utilisateur 1801 |

La lecture applicative V4 ne demande que 20 registres à partir de 1024, contre 110 pour V6/V6v16.

Le plugin doit donc utiliser une classe de profil (`V4`, `V6`, `V6v16`) choisie après la réponse `OpenedClient`.

---

## 12. Registres d'écriture V6/V6v16 identifiés

### Zone applicative utilisateur

| Adresse | Nom |
|---:|---|
| 1280 | erawConsigneMarchArret |
| 1281 | erawConsigneTemperatureDir |
| 1282 | erawConsignePMaxDir |
| 1283 | erawTemperatureDerogation |
| 1284 | erawTempoStartDerogation |
| 1285 | erawDureeDerogation |
| 1286 | erawModeVentilation |
| 1287 | erawConsigneMoteurVis |
| 1288 | erawConsigneMoteurFumee |
| 1289 | erawConsigneMoteurVentilation |
| 1290 | erawConsigneMoteurSecondaire |
| 1291 | erawConsigneMoteurNettoyage |
| 1292 | erawSortiesTOR |
| 1293 | erawCommandes |

**Les registres 1287-1293 sont techniques/test et ne doivent PAS être exposés dans Home Assistant.**

### Configuration utilisateur

| Adresse | Nom |
|---:|---|
| 1792 | ercuwModeFonctionnement |
| 1793 | ercuwDateFinVacAnnee |
| 1794 | ercuwDateFinVacMois_JourMois |
| 1795 | ercuwDateFinVacHeures_Minutes |
| 1796 | ercuwTemperatureModeVacances |
| 1797 | ercuwPuissMaxModeVacances |
| 1798 | ercuwTemperatureModeManuel |
| 1799 | ercuwPuissMaxModeManuel |
| 1800 | ercuwTempsAnticipationVac |
| 1801 | ercuwUserBits |

### Configuration installateur

La zone d'écriture commence à 2304 (`erciw...`) et comprend puissance mini, corrections moteurs, offsets sondes, cycle nettoyage, temporisations auto, différentiels, etc.

**Ne pas exposer ces registres dans l'intégration Home Assistant.** Ils modifient le réglage de combustion/installation et doivent rester sous contrôle du constructeur/installateur.

---

## 13. Décodage recommandé côté Home Assistant

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
├── stove_v6.py
├── stove_v6v16.py
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

## 14. Entités Home Assistant proposées

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

## 15. Stratégie de sécurité pour les écritures

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

## 16. Points encore à valider sur le HOBEN Osmose réel

La rétro-ingénierie statique permet maintenant de décrire beaucoup plus
précisément la première connexion. Les validations dynamiques restantes doivent
être réalisées sans commande de chauffage et en commençant par l'ouverture de
session :

1. **frontière complète d'OpenedClient** : l'ouverture réelle avec UserGuid
   configuré et DeviceGuid initial nul a reçu `0x04` le 2026-10-04, sans suffixe
   déjà reçu ; la longueur totale universelle, dont un suffixe arrivant plus tard,
   reste à établir ;
2. **association réelle** : déterminer comment le code demandé par MyHOBEN est
   présenté/généré et confirmer la séquence `2F → 30 + code → 04` ;
3. **validation dynamique de la cartographie V4 désormais connue statiquement** :
   capturer de façon expurgée une lecture 1024..1043 pendant un affichage MyHOBEN
   comparable, afin de confirmer sur le serveur/poêle réel le facteur 0,1 °C,
   puissance/état, mode et ventilation sans publier d'identifiant ;
4. **bitmaps V4 incomplets** : terminer la correspondance bit par bit de
   `erarWarnings` et `erarInformations`, ainsi que la table exacte code →
   libellé de `erarDefautsCombustion` ;
5. **champs V4 encore partiels** : préciser le packing date/heure 1036-1038 et
   la sémantique réellement exploitable de 1033 et 1042 ;
6. contenu des **4 octets de métadonnées de `DataUpdated`**.

Les deux premières validations concernent l'ouverture/association du client
et peuvent être réalisées sans requête Modbus ni commande du poêle.
Toute capture destinée au dépôt doit être anonymisée avant publication.


---

## 17. Séquence minimale pour un prototype lecture seule

La sonde ne met pas encore en œuvre tout le flux d'association décrit ci-dessous.
`session-open` reste une observation ponctuelle sans Modbus. Après l'ouverture
V4 confirmée, `read-v4-state` prépare une seule lecture brute documentée (§7),
à lancer volontairement depuis `main` après revue/fusion, puis fermeture.
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
3. SEND 0D + ModbusTCP(FFFF, unit=1, func=04, start=1024, qty=110 si V6)
4. RX 0E + Modbus response
5. Décode registres
6. Publie entités Home Assistant
7. Accepte RX 1B (DataUpdated), retire 5 octets puis décode Modbus
```

Pour V4, utiliser `qty=20`.

Aucune étape d'association ne doit déclencher une commande de fonctionnement du
poêle.


---

## 18. Exemples de trames

### Lire les 110 registres applicatifs V6

```text
0D FF FF 00 00 00 06 01 04 04 00 00 6E
```

Décomposition :

```text
0D       MyHOBEN DataRequestClient
FF FF    transaction ID
00 00    protocol ID
00 06    longueur MBAP
01       unit ID
04       Read Input Registers
04 00    adresse 1024
00 6E    110 registres
```

### Marche

```text
0D FF F0 00 00 00 06 01 06 05 00 00 01
```

### Arrêt normal

```text
0D FF F0 00 00 00 06 01 06 05 00 00 00
```

### Ventilation Silence (V6/V6v16)

```text
0D FF F0 00 00 00 06 01 06 05 06 00 01
```

### Ventilation Boost (V6/V6v16)

```text
0D FF F0 00 00 00 06 01 06 05 06 00 02
```

### Mode Manuel (V6/V6v16)

```text
0D FF F0 00 00 00 06 01 06 07 00 00 01
```

### Mode Automatic1 (V6/V6v16)

```text
0D FF F0 00 00 00 06 01 06 07 00 00 02
```

---

## 19. Niveau de confiance

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
- interprétation des rejets `CloseClient` sous-codes `02` à `06` ;
- sélection V4/V6/V6v16 ;
- MBAP Modbus TCP ;
- Unit ID 1 ;
- fonctions Modbus 03/04/06/16/22 ;
- lecture V6 : fonction 04, 1024, 110 registres ;
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

La cartographie et le formatage des 20 registres V4 sont maintenant établis
statiquement dans §8, mais une capture brute simultanée avec l'interface reste
nécessaire pour transformer ces correspondances en validation dynamique du
poêle réel. La réutilisation observée du DeviceGuid ne permet pas de généraliser
ce comportement à tous les modèles Hoben.
