# Archive — autres versions MyHOBEN (hors développement V4 actif)

Ces extraits complets proviennent de `protocol.md` et `AGENTS.md` au SHA
`ba007baf42f5120ce9b26aada95231c3930ca449` (base de la PR #77).
Les mentions CONFIRMÉ désignent l'analyse statique MyHOBEN 2.2 build 34,
sauf qualification dynamique explicite. Les campagnes H1/H2 V4 ne valident
pas ces autres profils. Les comparaisons V4 sont conservées pour comprendre
les différences, sans remplacer la [spécification V4 active](../protocol.md).
Aucun extrait n'autorise une écriture, un test réel ou une promotion `main`.
Les [règles de sécurité actuelles](../AGENTS.md) restent applicables.

## Sélection historique des profils

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
arguments d'`InstantiateStove` dans la section OpenedClient de `protocol.md` ne suffit pas à établir ce lien avec la
comparaison dans `StoveFactory.Create()`.

Tant que ce lien n'est pas prouvé, `select_stove_profile()` retourne `UNKNOWN`
pour cette branche, quelles que soient les valeurs de `software_minor` et
`application_version`. Les deux règles V6/V6v16 restent documentées en attente de
validation du champ. Toute autre combinaison non documentée retourne également
`UNKNOWN`. Le sélecteur renvoie uniquement un identifiant `StoveProfile`, sans
cartographie ni comportement de poêle ; le DeviceGuid n'intervient jamais dans
la sélection et n'est pas journalisé.

Le plugin Home Assistant doit donc **attendre `OpenedClient` et sélectionner dynamiquement la cartographie**, plutôt que supposer que l'Osmose est V6/V6v16.

## Lectures des autres profils

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

### Températures non V4 — limite de preuve

Pour **V6/V6v16**, ne pas généraliser automatiquement ce facteur tant que le
chemin d'affichage correspondant n'a pas été établi ou confirmé sur une capture
réelle.

## Commandes historiques et comparaisons entre profils

Les sections 10 à 12 ci-dessous conservent leurs qualifications de profil originales.

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

## Exemples historiques complets — aucune exécution autorisée

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

## Ancienne politique des écritures non V4 (AGENTS.md)

For V6/V6v16, candidate user-facing writes currently include:

- 1280: normal controller ON/OFF request;
- 1283: derogation temperature;
- 1284: derogation start/timing;
- 1285: derogation duration;
- 1286: ventilation mode;
- 1792: operation mode;
- 1798: manual-mode temperature;
- 1799: manual-mode max power;
- 1801: selected user bits using mask-write.

Knowing a writable register does **not** determine when it may be exposed. Follow the release sequencing in [project.md](../project.md): v0.1 remains strictly read-only; validated temperature/ventilation/user-mode controls belong to v0.2; normal controller ON/OFF belongs to v0.3.

Do **not** expose registers 1287-1293 (technical/motor/test) or the installer/factory area beginning around 2304.

Before enabling a writable feature:

- protocol bytes must be covered by tests;
- real-device behavior must be validated if practical;
- valid input range must be known;
- command rate must be limited;
- a read-back confirmation should be performed;
- error responses must be handled without retry loops.

---
