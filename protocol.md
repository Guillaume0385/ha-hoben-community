# Spécification non officielle du protocole HOBEN / MyHOBEN

**Cible :** développement d'une intégration Home Assistant pour poêles HOBEN (dont HOBEN Osmose)  
**Source analysée :** application Android MyHOBEN 2.2, build 34 (`com.inovalp.myhoben`)  
**Date de l'analyse :** 30 septembre 2026  
**Statut :** rétro-ingénierie statique de l'application officielle ; aucune commande n'a été envoyée au poêle pendant l'analyse.

> Cette documentation est non officielle. Les informations marquées **CONFIRMÉ** proviennent directement du code IL de MyHOBEN/HobenCore. Les éléments **À VALIDER** sont ceux qui nécessitent une capture réelle sur un poêle afin de confirmer la sémantique ou l'unité. Pour une première intégration Home Assistant, le mode lecture seule est recommandé par défaut.
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

**Recommandation Home Assistant : utiliser exclusivement `myhoben.fr:465` avec vérification normale du certificat TLS.**

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

### Identifiants utilisés

MyHOBEN utilise :

- le **MyHOBEN User GUID** du poêle (`Stove.UserGuid`) ;
- un **DeviceGuid** propre au client (application/téléphone) ;
- la version/build de l'application ;
- une chaîne descriptive du terminal.

Le GUID MyHOBEN doit être considéré comme une donnée sensible d'association : ne pas l'inscrire dans les logs Home Assistant.

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

**À VALIDER :** longueur/forme exacte du UserGuid sur le serveur (le code utilise la chaîne telle qu'enregistrée) et format initial du DeviceGuid. La réponse montre cependant un DeviceGuid serveur sur 32 caractères ASCII.

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

Note : le code appelle `InstantiateStove(type=octet8, product/rev=octet7, vsoftMaj=octet10, vsoftMin=octet9)`.

### Choix de l'implémentation poêle — CONFIRMÉ

`StoveFactory.Create()` utilise les valeurs retournées lors de l'ouverture :

- `type == 5` → `StoveV4`
- `type == 2`, révisions 0/1 et vsoftMaj 0 → `StoveV6`
- `type == 2`, révision 2 et vsoftMaj 0 → `BoilerV6_230`
- `type == 3`, révision 0, vsoftMaj 0/1 → `StoveV6`
- `type == 3`, révision 1, vsoftMaj 0/1, version <= 5 → `StoveV6`
- `type == 3`, révision 1, vsoftMaj 0/1, version > 5 → `StoveV6v16`

Le plugin Home Assistant doit donc **attendre `OpenedClient` et sélectionner dynamiquement la cartographie**, plutôt que supposer que l'Osmose est V6/V6v16.

---

## 5. Association / autorisation d'un nouveau client

Le code contient les échanges :

- `AskNewClient = 42`
- `CancelAskNewClient = 43`
- `AskNewClientStatus = 44`
- `AskNewClientAck = 45`
- `CancelAskNewClientAck = 46`
- `DeviceAuthReq = 47`
- `DeviceAuthRes = 48`

### Envoi du code d'autorisation — CONFIRMÉ

La méthode `SendDeviceAuth(code)` fabrique un payload de **2 octets little-endian** :

```text
code_LSB code_MSB
```

et l'envoie avec le type **48 / `DeviceAuthRes`** :

```text
30 <code_LSB> <code_MSB>
```

L'application attend ensuite une réponse et, si le premier octet vaut `04` et la longueur est au moins 11 octets, traite la réponse comme `OpenedClient`.

**À VALIDER dynamiquement :** séquence exacte qui provoque l'affichage/génération du code côté poêle et les contenus de `AskNewClient*`. Les noms, types et le paquet de réponse au code sont confirmés, mais le workflow complet mérite une capture avant automatisation dans Home Assistant.

### Recommandation pour l'intégration

Prévoir un `config_flow` en deux étapes :

1. saisie du GUID MyHOBEN ;
2. si le serveur indique `NotAuthorized`/demande d'association, affichage d'une seconde étape demandant le code ;
3. stockage du `DeviceGuid` retourné par `OpenedClient` dans l'entrée de configuration HA.

Ne jamais journaliser le GUID du poêle, le DeviceGuid complet ou le code d'association au niveau INFO.

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

## 8. Registres V6/V6v16 utiles pour Home Assistant

### Zone applicative (lecture, base 1024)

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

### États de fonctionnement — CONFIRMÉ

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

### Températures — IMPORTANT

Dans `HobenCore`, les températures applicatives sont lues comme **Int16 signé** (`ReadTempKey`). Il n'y a pas de division par 10 dans cette routine de décodage.

**À VALIDER sur une trame Osmose réelle :** unité finale utilisée par les registres (°C direct, dixième de degré, ou format HOBEN spécifique). L'intégration ne doit pas supposer une échelle avant comparaison entre une valeur brute et la température affichée par MyHOBEN.

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

- Register : **1281 / `0x0501`**.

**À VALIDER : échelle de température** sur une capture réelle. Ne pas activer une écriture `climate.set_temperature` tant que le facteur brut ↔ °C n'a pas été vérifié.

### 10.3 Temporisation de dérogation

Méthode : `SetTempoDerogation`

V6/V6v16 :

- Function : `06`
- Register : **1284 / `0x0504`**
- Nom : `erawTempoStartDerogation`
- Valeur : UInt16.

V4 : registre **1282**.

L'unité exacte (minutes/secondes ou format horaire interne) est **À VALIDER** avant exposition comme service HA.

### 10.4 Durée de dérogation

Registre V6/V6v16 :

- **1285 / `0x0505`** = `erawDureeDerogation`.

Présent dans la cartographie d'écriture. L'unité est à valider dynamiquement.

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

La rétro-ingénierie statique permet de créer le client et les requêtes, mais quatre validations dynamiques sont nécessaires avant d'activer toutes les commandes :

1. **profil retourné par ton Osmose** (`StoveV6` ou `StoveV6v16`) via les octets 7-10 de `OpenedClient` ;
2. **échelle des températures** en comparant un registre brut et l'affichage MyHOBEN ;
3. **unité des temporisations/durées de dérogation** ;
4. contenu des **4 octets de métadonnées de `DataUpdated`**.

Ces validations peuvent être réalisées sans modifier le poêle : une première version du client peut se connecter en lecture seule, enregistrer les trames brutes localement (avec masquage des GUID), et comparer les valeurs à l'application.

---

## 17. Séquence minimale pour un prototype lecture seule

```text
1. TLS connect myhoben.fr:465
2. SEND 03 + OpenClient payload
3. WAIT 04 OpenedClient
4. Parse profil poêle + DeviceGuid
5. Démarrer boucle de lecture
6. Si RX 0A -> SEND 0B
7. SEND 0D + ModbusTCP(FFFF, unit=1, func=04, start=1024, qty=110 si V6)
8. RX 0E + Modbus response
9. Décode registres
10. Publie entités Home Assistant
11. Accepte RX 1B (DataUpdated), retire 5 octets puis décode Modbus
```

Pour V4, utiliser `qty=20`.

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
- structure générale OpenClient ;
- champs majeurs OpenedClient ;
- sélection V4/V6/V6v16 ;
- MBAP Modbus TCP ;
- Unit ID 1 ;
- fonctions Modbus 03/04/06/16/22 ;
- lecture V6 : fonction 04, 1024, 110 registres ;