# Hoben — ha-hoben-community

Intégration communautaire **NON OFFICIELLE** pour Home Assistant, destinée à
prendre en charge les poêles à granulés Hoben via le service MyHOBEN.

Ce projet n'est ni affilié à, ni approuvé par, ni maintenu par Hoben, Inovalp,
Home Assistant ou HACS.

## État du projet

La version `0.0.1` reste un **socle de développement**. L’intégration peut désormais
être ajoutée depuis l’interface Home Assistant : elle teste la connexion,
enregistre un appareil et rafraîchit les données V4 toutes les **60 secondes**.
Le candidat de l’issue #26 ajoute un décodeur typé et **16 entités de lecture**,
dont deux désactivées par défaut. Il conserve les 20 registres UInt16 bruts en
mémoire avec les valeurs décodées. La cartographie vient de l’analyse statique
documentée dans `protocol.md` : **la validation MANAGER sur le HEAD exact et une
comparaison privée simultanée avec MyHOBEN restent requises avant fusion**.
Le décodeur et les premières entités ne sont pas encore marqués DONE dans la
roadmap. Chaque rafraîchissement utilise le client `HobenClient` et une connexion
TLS bornée. Toutes les entités sont en lecture seule ; le contrôle reste indisponible.
Une sonde manuelle conserve aussi les modes ponctuels TLS, `session-open` sans
lecture et `read-v4-state`. L'identification suit MyHOBEN 2.2 build 34 :
Identifiant HOBEN normalisé, DeviceGuid initial nul puis attribution/réutilisation
en mémoire puis persistance dans Home Assistant, demande d'autorisation ou rejet
documenté. Aucun code d'association n'est envoyé. La réutilisation du DeviceGuid
sur une seconde connexion a été confirmée sur l’Osmose de référence le
2026-10-04, lors de la validation MANAGER de la PR #22 (voir `protocol.md`).
La première version fonctionnelle prévue (`v0.1.0`) sera en lecture seule.

## Configuration dans Home Assistant

Après installation des fichiers `custom_components/hoben/` et redémarrage de
Home Assistant, ouvrir **Paramètres → Appareils et services → Ajouter une
intégration → Hoben**. Saisir l’**Identifiant HOBEN** affiché ou configuré dans
MyHOBEN, avec ou sans tirets. Le champ est masqué et les messages ne répètent
jamais la valeur saisie.

Le flux normalise l’identifiant avec le validateur du protocole, refuse les
doublons, effectue un seul appel `HobenClient.async_refresh()` et ferme le client
temporaire sur chaque résultat. Cet appel conserve les tentatives bornées du
client. Une lecture V4 réussie et un DeviceGuid attribué non nul sont nécessaires
avant de créer l’entrée. Les profils V6/V6v16/inconnus sont refusés.

Les champs sensibles `user_guid` (normalisé) et `device_guid` (attribué) sont
stockés uniquement dans `ConfigEntry.data`, jamais dans les options. Protéger les
fichiers de configuration et sauvegardes Home Assistant qui les contiennent.
L’ID unique de l’entrée et l’identifiant de l’appareil utilisent la même empreinte
SHA-256 complète, calculée sur l’identifiant normalisé avec le préfixe fixe
`hoben:user_guid:`. Ni le nom neutre `Hoben`, ni les erreurs, ni les journaux
n’affichent les GUID.

Lors du setup, une première lecture doit réussir avant l’activation du
coordinateur. `entry.runtime_data` contient le client et le coordinateur typés.
Le coordinateur conserve `HobenCoordinatorData(raw, state)`, construit avec une
seule lecture suivie d’un décodage sans I/O. Les entités s’abonnent au coordinateur
et lisent uniquement sa mémoire. Le déchargement retire leurs abonnements, arrête
les timers et ferme le client, y compris une lecture active. Un setup partiel
échoué décharge les plateformes et supprime aussi le runtime incomplet.
Le rechargement réutilise le DeviceGuid persisté. Après une lecture réussie,
une nouvelle attribution modifie uniquement `device_guid`, sans réécrire l’entrée
si la valeur est inchangée. L’appareil expose le fabricant `Hoben`, le profil
`Protocol V4` et la version logicielle d’OpenedClient ; il ne déduit pas un nom
commercial tel qu’Osmose.

Un problème réseau rend le rafraîchissement indisponible et permet à Home
Assistant de retenter le setup. Un identifiant rejeté ou une autorisation requise
arrête le sondage et ouvre une confirmation de réauthentification dans Home
Assistant. Confirmer reteste l’entrée avec ses GUID persistés, sans les afficher
ni permettre de changer l’identité. Une lecture V4 réussie persiste une éventuelle
rotation du DeviceGuid et recharge l’intégration, même sans rotation, pour
reprendre le sondage. Une autorisation toujours requise ou un identifiant encore
refusé maintient le formulaire avec un message fixe ; l’association reste non
prise en charge. Le flux initial permet aussi de réessayer plus tard. Pour
utiliser un autre identifiant HOBEN, configurer explicitement une nouvelle entrée.
Une réponse protocolaire, Modbus ou un profil non pris en charge fait échouer le
setup avec un message fixe expurgé.

L’intervalle de 60 secondes n’est pas configurable pour cet incrément. Aucun
socket permanent, DataUpdated, dump de registres, association ou contrôle du
poêle n’est ajouté.

## Entités V4 en lecture seule

| Entité | Unité / type | Catégorie | Activée par défaut |
|---|---|---|---|
| Température ambiante | °C, mesure | standard | oui |
| Température de consigne | °C, lecture de réglage | standard | oui |
| Niveau de puissance | %, mesure | standard | oui |
| État de fonctionnement | enum V4 | standard | oui |
| Mode de fonctionnement | automatique / magasin / manuel | standard | oui |
| Mode de ventilation | normal / silence / boost | standard | oui |
| Température des fumées | °C, mesure | diagnostic | oui |
| Température de l’air comburant | °C, mesure | diagnostic | oui |
| Température ambiante filaire | °C, mesure | diagnostic | **non** |
| Température ambiante RF | °C, mesure | diagnostic | **non** |
| Température de dérogation | °C, lecture de réglage | standard | oui |
| Délai de début de dérogation | minutes | standard | oui |
| Durée de dérogation | minutes | standard | oui |
| Dérogation active | binaire | standard | oui |
| Dérogation programmée | binaire | standard | oui |
| Consigne marche/arrêt du contrôleur | binaire OnOff | standard | oui |

La consigne marche/arrêt reflète uniquement l’octet OnOff du contrôleur : elle
ne prouve pas une combustion en cours. L’état de fonctionnement V4 reste la
référence pour la phase du poêle. Aucun interrupteur, sélecteur, réglage numérique,
climate, bouton ou service de contrôle n’est créé, y compris pour le mode magasin.

Les températures utilisent Int16 / 10 °C ; `0x0FFF` donne un état inconnu pour le
capteur concerné. La consigne principale inférieure à 5 °C est masquée comme dans
MyHOBEN. Un code enum inconnu, un OnOff différent de 0/1 ou une puissance supérieure
à 100 % donne aussi un état inconnu, sans devenir arbitrairement automatique,
arrêt ou zéro. Les codes bruts restent accessibles uniquement dans le modèle
interne. Les trois valeurs numériques de dérogation sont inconnues lorsqu’elle
n’est ni active ni programmée ; aucun défaut local de l’interface MyHOBEN n’est
substitué.

Un échec de rafraîchissement rend toutes les entités actives indisponibles, sans
effacer les dernières données internes. Un rafraîchissement réussi les rétablit.
Une seule température indisponible ne rend pas les autres entités indisponibles.
Les identifiants uniques utilisent l’empreinte non secrète de l’entrée suivie
d’une clé stable, conservée après rechargement et rotation du DeviceGuid. Toutes
les entités appartiennent à l’appareil existant. Noms et états enum sont traduits
en français et anglais dans `translations/`.

Les défauts, warnings, autres bits d’information, date/heure et PVI restent des
champs bruts internes sans entité, faute de cartographie complète.

## API protocolaire HobenClient

Depuis une coroutine, sans dépendance Home Assistant :

```python
from custom_components.hoben.client import HobenClient

client = HobenClient(
    user_guid=configured_hoben_id,
    device_guid=persisted_device_guid_or_none,
)
try:
    snapshot = await client.async_refresh()
    # Sensible : uniquement pour un stockage explicite et sécurisé, jamais un log.
    new_device_guid = client.device_guid_for_persistence
finally:
    await client.async_close()
```

Le build **34** et le descripteur communautaire historique **`GitHubActions`**
sont les défauts du client. `DEFAULT_BUILD` et `DEFAULT_DEVICE_INFO` sont définis
une seule fois dans `client.py` et partagés avec les sondes. La suite
`--live-premerge` utilise directement ces défauts, comme l’appelant HA.

Le constructeur normalise l'Identifiant HOBEN en 32 caractères hexadécimaux
minuscules sans tirets. Sans DeviceGuid persisté, il utilise les **32 zéros ASCII**
initiaux. Une valeur fournie est validée avant le réseau : exactement 32 octets
ASCII, sans imposer de format hexadécimal non prouvé. Une ouverture V4 valide et
sans suffixe ambigu met immédiatement à jour le DeviceGuid en mémoire, avant la
lecture. Les prochains rafraîchissements et retries réutilisent cette identité,
même si la lecture précédente échoue. Une nouvelle attribution peut la remplacer.

`device_guid_for_persistence` est un accès **explicitement sensible**. Le
config flow stocke cette valeur dans `ConfigEntry` puis la fournit à une
nouvelle instance. Le client n'écrit aucun fichier ni stockage HA.
`has_assigned_device_guid` indique sans divulgation si la valeur diffère des zéros.
Les GUID ne figurent ni dans `repr`, ni dans `safe_report()`, ni dans les erreurs.
Le client n'est pas une dataclass exportable par `asdict()`.

Le résultat immuable `RawStoveSnapshot` contient `profile`, `registers` (tuple de
**20 UInt16 bruts**), `product_type`, `product_revision`, `software_major`,
`software_minor` et `application_version`. Il ne contient aucune identité,
session ou trame brute, même via `asdict()`. Son rapport sûr conserve seulement
les métadonnées et le nombre de registres. `client.profile` conserve le dernier
profil accepté ; `client.last_snapshot` conserve le dernier rafraîchissement
réussi. `RawStoveSnapshot` reste volontairement **brut** : il ne transforme
pas ces UInt16 en propriétés physiques. La couche indépendante de Home Assistant
`v4_state.py` expose `decode_v4_snapshot(snapshot) -> V4StoveState`, avec un état
immuable et hashable et le helper `decode_v4_temperature(raw)`. Elle exige V4 et
exactement 20 UInt16, sans modifier le snapshot ni accéder au réseau. Elle décode
les températures, mode/OnOff, puissance/état, ventilation et dérogation selon
`protocol.md`, et conserve explicitement les champs partiels/codes inconnus.
Ne pas publier son repr/asdict : il contient des valeurs du foyer. V4 reste sélectionné
dynamiquement ; les autres profils échouent explicitement, sans supposer que
tous les Osmose sont V4.

Chaque tentative ouvre un TLS vérifié vers `myhoben.fr:465`, effectue OpenClient,
valide OpenedClient puis une seule lecture **04 / FFFF / unité 1 / adresse 1024 /
quantité 20**, et ferme la connexion. Les primitives existantes construisent et
valident les trames. La longueur complète d'OpenedClient restant inconnue, une
connexion permanente et DataUpdated sont différés. Les suffixes déjà reçus sont
refusés sans réinterprétation ; un suffixe arrivant plus tard reste une incertitude.

Par défaut, un échec de transport permet **2 tentatives au total**, séparées par
**1 seconde** de backoff asynchrone, après fermeture de la première connexion.
`max_attempts` accepte 1 ou 2, `retry_delay` 0 à 30 secondes ; les délais globaux
d'ouverture/lecture sont chacun de 30 secondes et configurables. Les erreurs
protocole, autorisation, CloseClient, profil ou Modbus ne sont jamais retentées.
Un verrou asynchrone sérialise les appels concurrents et les mises à jour
d'identité. L'annulation se propage avec nettoyage. `async_close()` est idempotent,
annule une opération active, attend sa fermeture et interdit tout nouvel appel
sur cette instance. Le coordinateur HA assure la planification.

Les erreurs de `custom_components.hoben.exceptions` permettent de distinguer :

| Situation | Erreur typée |
| --- | --- |
| Entrée locale invalide | `HobenInvalidInputError` |
| Identifiant rejeté par le serveur | `HobenInvalidCredentialsError` |
| DeviceAuthReq | `HobenAuthorizationRequiredError` |
| CloseClient | `HobenClosedError`, avec motif documenté |
| Profil non pris en charge | `HobenUnsupportedProfileError` |
| Réponse malformée / suffixe ambigu | `HobenProtocolError` / `HobenAmbiguousSessionError` |
| Exception Modbus corrélée | `HobenModbusError`, code numérique brut |
| Transport / timeout après les tentatives permises | `HobenRefreshExhaustedError`, sous-type de `HobenTransportError`, avec cause expurgée (`HobenTimeoutError` pour un timeout) |
| Instance fermée | `HobenClientClosedError` |

Aucune commande d'écriture/contrôle, association, boucle permanente ni tâche de
fond n'est exposée par cette API.

## Installation via HACS

La distribution via HACS est prévue. Lorsqu'une version fonctionnelle sera
publiée, le dépôt pourra être ajouté à HACS comme dépôt personnalisé de catégorie
« Integration ». Le socle actuel peut être installé manuellement pour tester
la configuration et le coordinateur brut, selon les instructions ci-dessus ;
il ne fournit pas encore de capteurs utilisateur.

## Contribution et tests

Lire [AGENTS.md](AGENTS.md), [project.md](project.md) (architecture et roadmap,
source de vérité) et [protocol.md](protocol.md) (faits et incertitudes du protocole)
avant de contribuer. Les tests du socle sont locaux, déterministes et ne
nécessitent ni Home Assistant, ni serveur Hoben.

Avec Python 3.12 ou supérieur et pip prenant en charge les groupes de dépendances
(pip 25.1 ou supérieur), ainsi que Node.js pour simuler hors ligne les scripts
GitHub Actions de confiance (déjà présent sur les runners GitHub) :

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --group dev
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

Les tests Home Assistant ont un environnement **séparé**. Le harnais est fixé à
`pytest-homeassistant-custom-component==0.13.367`, qui fixe **Home Assistant
2026.9.4**, dernière version stable retenue plutôt que la bêta 2026.10 du harnais
suivant. Cette version de HA nécessite **Python 3.14.2 ou supérieur**. Le groupe
`ha-test` évite d’installer HA dans l’environnement protocolaire Python 3.12.
Depuis la racine du dépôt, dans un second environnement :

```sh
python3.14 -m venv /tmp/hoben-ha-tests
. /tmp/hoben-ha-tests/bin/activate
python -m pip install --upgrade pip
python -m pip install --group ha-test
python -m pytest -c ha_tests/pytest.ini ha_tests
```

Les tests chargent les vrais config entries, flux, timers du coordinateur,
traductions et registre d’appareils HA. Ils vérifient notamment le démarrage du
flux de réauthentification sur une erreur d’authentification, la reprise après
rechargement et la conservation de l’identité, les métadonnées/valeurs des
entités, leurs traductions, les sentinelles/codes inconnus, la disponibilité et
le nettoyage après setup partiel. `HobenClient` est simulé pour l’orchestration ;
des tests de réauthentification et d’entités utilisent aussi le vrai client sur
un transport scripté, pour vérifier les trames exactes et l’absence de commande
ou de réponse d’association.
Le harnais bloque les sockets externes et un garde interdit toute construction
de transport Hoben réel, même si une simulation est oubliée. Aucun test HA ne
contacte `myhoben.fr`.

La CI exécute les jobs séparés `tests` et `ha-tests`, ainsi que les validateurs
officiels HACS et Hassfest.
L'icône communautaire originale représente trois points reliés ; elle ne reprend
aucun logo Hoben ou Inovalp. Les assets locaux `brand/` sont pris en charge à
partir de Home Assistant 2026.3.

### Quatre couches de validation

| Couche | Déclenchement et portée |
| --- | --- |
| CI déterministe hors ligne | `Validate` : pytest/Ruff, HACS et Hassfest ; aucun accès Hoben ni secret. Les validateurs officiels peuvent accéder à leurs propres services. |
| Smoke protocolaire sans secret | Labels optionnels `live-validation` (TLS seulement) et `live-session-negative` (identité synthétique), sans authentification réelle. |
| Validation authentifiée avant fusion | Après revue MANAGER, label exact `manager-live-hoben` ; workflow de confiance sur `main`, code candidat au SHA exact et suite fixe en lecture seule. |
| Exploration manuelle sur main | `Live Validation` / `workflow_dispatch`, dont les modes réels `session-open` et `read-v4-state` réservés à `main` protégé. |

La CI normale reste déterministe. Chaque fusion exige en plus la validation
authentifiée du **commit candidat exact**, déclenchée volontairement après revue.
Un smoke TLS ou une observation négative ne satisfait pas cette exigence.

### Validation authentifiée avant fusion, après revue MANAGER

Le workflow [MANAGER authenticated Hoben validation](.github/workflows/manager-live-hoben.yml)
utilise uniquement **`pull_request_target: labeled`**. Sa définition provient de
`main` protégé, même s'il checkout ensuite le code candidat. Seul l'ajout du label
exact **`manager-live-hoben`** par **`Guillaume0385`** peut autoriser une PR ouverte,
non draft, vers `main`, dont la branche appartient exactement à
`Guillaume0385/ha-hoben-community`. Les forks sont exclus. Les identités et le
label sont aussi comparés strictement dans le script de confiance, car l'égalité
des expressions GitHub ignore la casse.

> Adding `manager-live-hoben` means the MANAGER has reviewed the exact candidate HEAD and explicitly trusts that code to run with the Hoben live credential.

**Avant d'ajouter le label**, le MANAGER doit :

1. inspecter le diff complet, y compris la sonde et les modules importés ;
2. vérifier le respect de `AGENTS.md`, `project.md` et `protocol.md` ;
3. vérifier l'absence d'exfiltration, de journalisation d'identifiants et
   d'opérations d'écriture/contrôle non autorisées ;
4. vérifier la CI hors ligne (`tests`, `ha-tests`, `hacs`, `hassfest`) ;
5. consigner dans la revue le **SHA HEAD complet** approuvé ;
6. ajouter `manager-live-hoben` seulement après cette revue.

Le job de confiance vérifie aussi que la PR courante possède encore ce SHA et
ce label avant de publier `live-hoben-authenticated = pending` sur le candidat.
Un événement mis en attente devenu obsolète est refusé. La commande candidate
utilise un autre runner, les seules permissions `contents: read`, le checkout
exact **`github.event.pull_request.head.sha`**, `persist-credentials: false` et
l'environnement **`hoben-live`**, qui doit garder sa restriction à la seule
branche `main` protégée décrite plus bas. Le seul secret Hoben reste
**`HOBEN_USER_GUID`**, injecté uniquement dans l'étape suivante :

```sh
python scripts/probe_hoben_connection.py --live-premerge
```

Cette suite fixe ignore les surcharges exploratoires, ne prend aucun argument
libre d'hôte/fonction/registre et n'installe aucune dépendance candidate. Elle
construit le client sans surcharge de `build` ni `device_info` pour valider
réellement ses valeurs par défaut utilisées par HA. Elle
utilise **le même HobenClient pour deux rafraîchissements séquentiels**. Le premier
part du DeviceGuid nul et adopte une identité attribuée ; le second la réutilise
automatiquement. Chacun ouvre un **nouveau** TLS vérifié vers `myhoben.fr:465` →
OpenClient/OpenedClient → profil dynamiquement V4 sans suffixe déjà reçu →
**une seule** lecture fonction **04**, transaction **`0xFFFF`**, unité **1**, adresse
**1024**, quantité **20** → réponse corrélée de **20 UInt16** → fermeture.
Les retries sont désactivés dans cette suite fixe : exactement deux sessions et
deux lectures en cas de réussite. Chacun des deux snapshots passe aussi par le
décodeur V4, **sans lecture supplémentaire ni publication des valeurs décodées**.
Le retry/backoff du client est testé hors ligne.
Une autorisation demandée, un rejet, un autre profil, un timeout, une exception
Modbus ou une réponse non corrélée fait échouer la validation. Les valeurs des
registres peuvent changer : aucune valeur exacte n'est exigée. Le JSON exporte
les métadonnées expurgées et le nombre de registres, sans leurs contenus. La
réussite exige `state: "client_refresh_validated"`, `profile: "v4"`,
`device_guid_reuse: "validated"`, `refresh_count: 2`, `register_count: 20` et
`v4_decode_count: 2`. Ce compteur valide l’exécution du décodeur, pas la
correspondance de ses valeurs avec l’affichage MyHOBEN.
Un premier rafraîchissement réussi seul ne suffit pas. Aucun identifiant ne
figure dans le rapport. `protocol.md` consigne la réutilisation confirmée sur
l’Osmose de référence après la validation MANAGER de la PR #22, sans généraliser
aux autres modèles. Chaque nouveau candidat exige sa propre validation.
Aucun code d'association, fonction 06/16/22, transaction `0xFFF0` ni commande
de température, ventilation, mode ou ON/OFF n'est envoyé.

Un dernier job de confiance, sans checkout candidat ni secret Hoben, publie
**`success` seulement si le job et la sonde ont réussi**, sinon **`failure`**.
Le token avec `statuses: write` reste dans les jobs de confiance ; il n'est
jamais remis à la commande candidate. Les logs, le résumé et le nom de l'artefact
`live-hoben-authenticated-<SHA>` identifient le commit testé. Aucun GUID, code
d'autorisation, paquet brut ou texte d'exception arbitraire n'est exporté.

**Après le test**, le MANAGER doit vérifier le SHA testé, lire le rapport
expurgé, confirmer `live-hoben-authenticated = success`, retirer le label, puis
fusionner uniquement si HEAD est toujours exactement ce SHA et tous les checks
requis sont verts. Tout nouveau commit exige une nouvelle revue et le retrait /
réajout du label. Ni `opened`, `synchronize`, `reopened`, push, schedule, label
déjà présent ni bouton « Re-run jobs » n'autorisent une nouvelle sonde réelle.
La fusion reste une décision MANAGER ; Codex laisse la PR ouverte.

Après la première validation réussie, configurer manuellement :

```text
Settings → Branches → main
→ Require status checks to pass before merging
→ add: ha-tests
→ add: live-hoben-authenticated
```

Les checks requis deviennent **`tests`**, **`ha-tests`**, **`hacs`**, **`hassfest`** et
**`live-hoben-authenticated`**. Le statut est publié sur le SHA candidat, car
le contexte du workflow `pull_request_target` est celui de la base. Le succès
d'un ancien SHA ne satisfait donc pas la protection d'un nouveau commit.
Sans ce réglage effectif, le statut seul ne bloque pas techniquement la fusion.
Avant toute publication communautaire, vérifier en particulier que `ha-tests`
est effectivement requis par la protection de `main`, en plus des checks déjà
présents. La réussite de ce job dans une PR ne configure pas cette protection.

**Installation initiale :** GitHub ne peut pas lancer une nouvelle définition de
confiance qui existe seulement dans cette première PR. Le MANAGER doit décider
et organiser une installation initiale distincte, revue, sur `main` protégé,
avant de labelliser la PR d'implémentation et tester son SHA. Cette contrainte
d'amorçage ne permet pas d'utiliser le YAML candidat pour obtenir le secret.
Créer aussi la définition du label exact `manager-live-hoben` dans le dépôt,
sans l'appliquer à une PR avant sa revue. Vérifier la restriction effective de
`hoben-live` à la seule branche `main` avant toute exécution authentifiée.
La PR reste ouverte en attente de cette installation et de la revue live.

Chaque future PR v0.1 ajoutant un mécanisme de lecture seule testable en sécurité
(session persistante, Ping/Pong, reconnexion, lecture documentée, DataUpdated)
doit étendre cette suite allowlistée avec un test réel borné approprié.
L'ajout de code d'écriture n'autorise jamais automatiquement un test réel de
contrôle : une décision de sécurité distincte reste nécessaire.

### Smoke sans secret et exploration manuelle sur GitHub Actions

Le workflow [Live Validation](.github/workflows/live-validation.yml) est
**opt-in**, avec les déclenchements explicites suivants, séparés du workflow MANAGER :

- **TLS avant fusion :** ajouter le label exact `live-validation` à la PR.
  Seul l'événement `pull_request: labeled` pour ce label lance `tls-only`.
- **Test négatif avant fusion :** ajouter le label exact
  **`live-session-negative`**. Le job séparé exécute le commit de tête de la PR,
  sans secret GitHub ni environnement `hoben-live`. Les deux labels sont
  indépendants ; aucun ne peut lancer `session-open` ou `read-v4-state`.
- **Usage manuel :** une fois le workflow présent sur `main`, utiliser
  **Actions → Live Validation → Run workflow** (`workflow_dispatch`). Choisir
  `tls-only` (défaut), `session-open` ou `read-v4-state`. Les deux derniers
  exigent la référence
  `github.ref == 'refs/heads/main'` : les autres branches et les tags sont exclus.

L'ouverture d'une PR, un push ou `synchronize` ne lance aucun test live, même
avec un label déjà présent. Retirer puis réajouter le label voulu demande un
nouvel essai volontaire. La CI normale `Validate` reste déterministe et hors
ligne vis-à-vis de Hoben, indépendante de ces jobs.

Les jobs utilisent Python 3.12 sur `ubuntu-latest`, les seules permissions
`contents: read` et un checkout avec `persist-credentials: false`. Le job
`tls-only` ouvre une connexion TLS vérifiée à `myhoben.fr:465` puis ferme,
sans identifiant ni message MyHOBEN. `session-open` et `session-negative` exécutent :
TLS → un OpenClient → Pong si nécessaire → observation → fermeture.
Ces deux modes de session n'envoient aucune requête Modbus. Le mode séparé
`read-v4-state` ajoute exactement une lecture applicative V4 après ouverture
validée. Aucun polling, code d'authentification, contrôle ou retry automatique
n'est ajouté.

Le job **`live-session-negative`** utilise exactement :

```text
UserGuid   = 00000000000000000000000000000000
DeviceGuid = 00000000000000000000000000000000
```

Le UserGuid est **synthétique/non attribué**, mais son format de 32 caractères
hexadécimaux ASCII est valide. Le DeviceGuid est la **valeur initiale normale
d'un nouveau client**, confirmée dans `protocol.md`, et non un identifiant
volontairement invalide. Ce mode ignore toutes les variables `HOBEN_*`, même
présentes, et réutilise le build 34 et le DeviceInfo stable décrits plus bas.

Un `OpenedClient`, `DeviceAuthReq`, `CloseClient`, type inattendu ou EOF après
l'envoi donne `observation: "informative"` et le code **0** : une réaction a été
observée après TLS et l'écriture OpenClient. Cela **ne valide pas une
authentification**. `05 02` est classé `invalid_identifier` si reçu ; aucune
réponse particulière du serveur réel n'est présumée. Timeout, erreur TLS ou
transport, préfixe malformé ou autre échec donnent `observation: "inconclusive"`
et le code **1**. Le résumé et l'artefact **`live-session-negative-output`**
conservent uniquement le rapport expurgé, y compris en cas d'échec.

Les vrais jobs **`session-open`** et **`read-v4-state`** utilisent l'environnement
**`hoben-live`** et
l'unique secret Hoben **`HOBEN_USER_GUID`**, l'Identifiant HOBEN réel.

**Prérequis de sécurité obligatoires, avant tout ajout du secret :**

1. Protéger `main` dans les règles du dépôt en imposant une PR approuvée pour
   toute modification. Les comptes pouvant pousser des branches et lancer les
   workflows ne doivent pas pouvoir y introduire du code non revu par push
   direct ou contournement des règles.
2. Dans **Settings → Environments → hoben-live → Deployment branches and tags**,
   choisir **Selected branches and tags**, avec une seule règle de type
   **Branch** et de nom exact **`main`**. Aucune autre branche, aucun joker et
   **aucun tag** ne doit être autorisé. « No restriction » est interdit ;
   « Protected branches only » ne garantit pas l'exclusivité de `main`.
   Une approbation de déploiement peut compléter cette restriction.
3. Vérifier la politique effective dans GitHub, séparément des tests du dépôt.
   Seulement ensuite, ajouter manuellement **`HOBEN_USER_GUID`** dans **cet
   environnement**. Ne pas le stocker comme secret de dépôt ou d'organisation
   accessible sans cette protection.

La condition du job complète la politique de l'environnement, qui reste
**indispensable** : une branche non revue peut modifier le YAML et la sonde.
Ni la validation du UserGuid, ni `contents: read`, ni le masquage des logs
n'empêchent ce code de copier un secret déjà reçu dans un artefact. La restriction
de déploiement doit empêcher GitHub de lui remettre le secret.

Pour contrôler les réglages depuis un contexte de confiance, avec les droits
de lecture nécessaires et sans lancer de sonde :

```sh
gh api repos/Guillaume0385/ha-hoben-community/branches/main --jq '{name, protected}'
gh api repos/Guillaume0385/ha-hoben-community/environments/hoben-live --jq '.deployment_branch_policy'
gh api repos/Guillaume0385/ha-hoben-community/environments/hoben-live/deployment-branch-policies --paginate
```

Résultat requis : `protected: true`, politique `protected_branches: false` /
`custom_branch_policies: true`, et exactement une règle
`{ "name": "main", "type": "branch" }`. Vérifier aussi les règles actives de
`main` : revue de PR obligatoire, sans contournement pour les comptes concernés.
Une politique absente, une branche non protégée ou une lecture impossible laisse
le prérequis **non validé** : ne pas ajouter le secret ni lancer ces deux modes.
Les tests YAML hors ligne ne prouvent pas ces réglages distants.

Le workflow ne crée ni n'affiche le UserGuid. Le secret n'est injecté que dans
l'environnement de l'étape Python de chaque job réel, jamais dans un argument, le job
négatif ou la CI normale. Le DeviceGuid initial est construit par le programme.
Le résumé `session-open` distingue `observed` (réponse classée) et `failure` ;
le JSON précise le résultat, sans assimiler une autorisation demandée ou un rejet
à une session authentifiée. Le JSON expurgé est conservé dans les logs, le résumé
et l'artefact `live-validation-output`, même en cas d'échec. Aucun dump
d'environnement n'est exporté.

## Sonde manuelle TLS / OpenClient

Cette validation de développement est **strictement volontaire**, indépendante
des tests et de Home Assistant. Python 3.12+ suffit, sans dépendance externe.
Les tests automatisés utilisent des flux simulés et interdisent les connexions
réseau. Les commandes de sonde ci-dessous contactent réellement Hoben.

Pour vérifier uniquement TLS, sans identifiant ni message MyHOBEN :

```sh
python scripts/probe_hoben_connection.py --tls-only
```

La sonde utilise `myhoben.fr:465`, les autorités de confiance du système et la
vérification du nom `myhoben.fr`. Un certificat invalide ou un nom incorrect fait
échouer la connexion. Aucun mode non vérifié, port 433 ou repli en clair n'existe.

Pour le test négatif distinct, sans secret et sans validation d'authentification :

```sh
python scripts/probe_hoben_connection.py --session-negative
```

Les cinq modes CLI sont mutuellement exclusifs. Pour **une première connexion
avec `--session`**, les paramètres sont :

| Paramètre | Source / défaut |
| --- | --- |
| `HOBEN_USER_GUID` | Seul identifiant sensible requis : **Identifiant HOBEN** réel, GUID avec ou sans tirets |
| DeviceGuid | **32 zéros**, valeur initiale normale construite par le programme |
| `HOBEN_BUILD` | **34** par défaut ; surcharge locale non secrète de 0 à 65535 |
| `HOBEN_DEVICE_INFO` | Descripteur communautaire stable ci-dessous ; surcharge locale non secrète possible |

La source du UserGuid est désormais confirmée : l'Identifiant HOBEN saisi ou
scanné dans MyHOBEN, sans hash ni dérivation. La sonde accepte les notations
`8-4-4-4-12` avec tirets ou 32 chiffres hexadécimaux ASCII, puis normalise en
32 caractères hexadécimaux minuscules sans tirets. Une valeur absente ou invalide
est refusée **avant création du transport**, sans connexion réseau. Le nom usuel
du poêle n'entre pas dans OpenClient. Le UserGuid est un secret d'association,
même s'il est accessible ou imprimé pour l'utilisateur.

`--session` et `--read-v4-state` ne lisent ni n'exigent `HOBEN_DEVICE_GUID`.
Le DeviceGuid initial correspond
à `Guid.Empty` sans tirets. Après une association/ouverture réussie, le DeviceGuid
renvoyé dans `OpenedClient[14:46]` est destiné à être persisté puis réutilisé,
comme le fait MyHOBEN. `--session` s'arrête à cette observation. Aucun de ces deux
modes ne persiste ni n'exporte le DeviceGuid reçu.

Le build 34 correspond à MyHOBEN Android 2.2 analysé dans `protocol.md`.
Le DeviceInfo par défaut reste exactement :

```text
ha-hoben-community/GitHubActions/en/Python/Linux/0/0/1/0/0,0
```

C'est le descripteur communautaire partagé par `HobenClient` et les sondes,
centralisé dans `custom_components/hoben/client.py`. Son nom historique
`GitHubActions` est conservé, y compris pour l’usage HA. Il ne s'agit pas
d'une valeur extraite de MyHOBEN ni d'un format obligatoire du serveur au-delà
de la structure documentée.

Exemple Bash avec saisie masquée, sans identifiant dans l'historique ou les
arguments du processus (ne pas activer `set -x`) :

```bash
IFS= read -r -s -p 'Identifiant HOBEN (GUID avec ou sans tirets) : ' HOBEN_USER_GUID
printf '\n'
export HOBEN_USER_GUID
python scripts/probe_hoben_connection.py --session
unset HOBEN_USER_GUID
```

Le rapport JSON contient uniquement l'hôte/port et les observations structurées :

| Réponse observée | Rapport |
| --- | --- |
| `OpenedClient 0x04` | `state: "opened"`, champs produit/logiciel/application, profil et `unclassified_bytes` |
| `DeviceAuthReq 0x2F` | `state: "authorization_required"`, `message_type: 47` |
| `CloseClient 05 02` | `state: "closed"`, `message_type: 5`, `reason: "invalid_identifier"` |
| `CloseClient 05 03` | `reason: "stove_connection_required"` : le poêle doit être connecté au serveur pour l'authentification mobile |
| `CloseClient 05 04` | `reason: "authorization_rejected"` |
| `CloseClient 05 05` | `reason: "authorization_timeout"` |
| `CloseClient 05 06` | `reason: "server_maintenance"` |
| Autre sous-code CloseClient, ou absent à EOF | `state: "closed"`, `message_type: 5`, `reason: "unknown"` |
| Type réellement inattendu | `error: "unexpected_message_type"`, numéro `message_type` uniquement |

`authorization_required` signifie que l'OpenClient a atteint la demande
**« Code d'authentification ? »**. Aucun code n'est demandé ni envoyé par cette
sonde : **DeviceAuthRes `0x30` n'est pas implémenté**. La provenance du code reste
à valider ; aucune hypothèse n'est ajoutée. Un `profile: "unknown"` reste une
ouverture observée, notamment pour la branche V6/V6v16 ambiguë.

Pour `--session`, le code de sortie vaut **0** pour `opened`,
`authorization_required` ou `closed` : l'observation a abouti, sans garantir une
authentification. Il vaut **1** pour une erreur et **2** pour un usage CLI invalide.
Le mode négatif conserve les critères `informative`/`inconclusive` décrits plus
haut. TLS, transport, EOF, délai, entrées invalides et protocole produisent
uniquement des erreurs classées, jamais le texte d'une exception arbitraire.
Les UserGuid, DeviceGuid, codes d'autorisation, payloads inconnus et trames brutes
sont exclus des logs et rapports.

Les délais par défaut sont 10 s pour la connexion, chaque lecture et chaque
écriture/drain, 5 s pour la fermeture et 30 s pour l'échange complet après TLS.
Les Ping ou fragments successifs ne réinitialisent pas ce dernier délai.
Seuls les **48 premiers octets confirmés** d'OpenedClient sont décodés ; sa
longueur totale reste inconnue. Un sous-code CloseClient fragmenté est attendu
dans ces mêmes délais. Aucun suffixe opaque déjà reçu n'est traité comme un autre
message, même s'il commence par Ping. La connexion est fermée sur chaque issue.

Pour les développeurs, `AsyncTlsTransport.connect/write/read/close` fournit les
octets bruts avec des erreurs distinctes `TransportTimeout` et `TransportEOF`.
`open_session_once(transport, user_guid=..., build=..., device_guid=...,
device_info=...)` possède le cycle connexion/fermeture et retourne un
`OpenSessionResult`, `AuthorizationRequiredResult` ou `ClosedSessionResult`.
Utiliser `safe_report()` pour les diagnostics ; ne pas exporter l'objet complet
avec `dataclasses.asdict()`, car le codec OpenedClient conserve le DeviceGuid.
Ces modules n'importent pas Home Assistant.

### Une lecture V4 brute manuelle sur main

L'observation réelle du **4 octobre 2026** a confirmé dynamiquement le profil
**V4** du Hoben Osmose de référence : type produit 5, révision 0, logiciel 8.2,
version application 512 et `unclassified_bytes: 0`. Cela ne classe pas tous les
Osmose comme V4 et ne prouve pas la longueur totale universelle d'OpenedClient.

Après fusion sur `main` protégé, le responsable/utilisateur peut lancer
**Actions → Live Validation → read-v4-state**, avec l'environnement `hoben-live`
et le seul secret `HOBEN_USER_GUID` déjà protégé comme pour `session-open`.
Le mode exploratoire `read-v4-state` reste réservé à `main` ; seule la suite
`--live-premerge` du workflow de confiance peut tester un SHA de PR après revue
et label MANAGER. Les tests pytest sont entièrement simulés et hors ligne.
La commande du job exploratoire,
réservée à cette validation volontaire depuis le code revu, est :

```sh
python scripts/probe_hoben_connection.py --read-v4-state
```

Le module protocolaire `v4_read.py` possède le cycle complet : TLS vérifié →
un OpenClient → OpenedClient → profil dynamique exactement V4 et aucun suffixe
déjà reçu → une lecture → une réponse correspondante → fermeture. Une demande
d'autorisation, tout CloseClient, un préfixe invalide, un profil différent/inconnu
ou des octets OpenedClient non classifiés empêchent la lecture. Aucun suffixe
opaque n'est réinterprété. Un suffixe qui arriverait plus tard reste une question
de frontière protocolaire non résolue.

La requête unique est celle de `protocol.md` : transaction `0xFFFF`, unité 1,
fonction **04**, adresse 1024, quantité **20**. Les codecs construisent exactement :

```text
0D FF FF 00 00 00 06 01 04 04 00 00 14
```

Seuls des Ping initiaux reçoivent un Pong pendant l'attente de `0x0E`
DataResponseClient. Le buffer attend les six octets du préfixe MBAP avant de
calculer sa longueur bornée, accepte les fragments TLS et valide transaction,
unité, fonction et exactement 40 octets de données. Une réponse tronquée,
malformée, démesurée ou accompagnée d'octets supplémentaires déjà reçus est
rejetée ; aucun second message n'est traité.

Le rapport JSON allowlisté ajoute `host`, `port` et `mode: "read-v4-state"` à
ce schéma de réussite (**valeurs illustratives synthétiques**) :

```json
{
  "state": "read",
  "profile": "v4",
  "function": 4,
  "start_address": 1024,
  "quantity": 20,
  "registers": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
}
```

Les registres sont toujours exportés par cette sonde comme **UInt16 bruts** dans
l'ordre reçu : la sonde ne fait volontairement aucun décodage sémantique. La
sémantique V4 est toutefois maintenant documentée dans `protocol.md` après
analyse de MyHOBEN 2.2 build 34. En particulier, 1031 est la température ambiante,
1032 la consigne, 1030 contient puissance+état, et les températures V4 utilisent
un format Int16 en dixièmes de degré. Cette séparation permet de conserver la
sonde comme outil brut de validation du futur décodeur.
Une exception Modbus correspondante donne `state: "modbus_exception"` et le
`exception_code` numérique brut, avec les mêmes champs de requête, sans retry.
Les refus après OpenedClient donnent `read_not_attempted` et une raison
allowlistée ; autorisation/fermeture et erreurs conservent leurs rapports expurgés.
Le code de sortie vaut **0 uniquement pour `read`**, **1** pour les autres
résultats et **2** pour un usage CLI invalide.

Les mêmes délais de transport s'appliquent, avec 30 s au total pour l'ouverture
puis 30 s au total pour l'unique échange de lecture ; les Ping ne les prolongent
pas. Tout résultat ferme la connexion. Aucun identifiant, trame brute, code
d'association ou dump d'environnement n'entre dans les logs, résumés ou artefacts.
Le job conserve ce JSON dans **`live-v4-read-output`**, y compris en cas d'échec.
Ce mode n'ajoute ni écriture (06/16/22, transaction `0xFFF0`), ni DeviceAuthRes,
ni polling, reconnexion, client persistant ou contrôle du poêle.

## Format des principales données V4

La cartographie détaillée et les niveaux de confiance sont dans
[protocol.md](protocol.md). Pour le profil V4 du poêle de référence, l'analyse de
MyHOBEN établit notamment :

- registre 1031 : température ambiante principale, Int16 / 10 °C ;
- registre 1032 : consigne de température, Int16 / 10 °C ;
- registre 1030 : octet haut = puissance %, octet bas = état V4 ;
- registre 1024 : octet haut = mode V4, octet bas = marche/arrêt ;
- registre 1028 : ventilation 0 Normal, 1 Silence, 2 Boost ;
- registres 1025-1027 : dérogation, avec température en dixièmes de degré et
  temporisation/durée en minutes.

Le convertisseur MyHOBEN traite `0x0FFF` comme température indisponible. Les
captures d'écran 23,5 °C / 19,0 °C sont cohérentes avec le facteur /10, mais
aucune valeur brute simultanée n'a encore été publiée : une validation réelle
expurgée reste prévue avant fusion des premières entités physiques.

Pour le candidat #26, après CI verte et validation authentifiée sur le HEAD exact,
le MANAGER compare **en privé et au même instant** l’état décodé et l’interface
MyHOBEN de l’Osmose : ambiance, consigne, mode, ventilation, OnOff et état/puissance
selon ce que la phase actuelle permet d’observer. Dans la PR, consigner seulement
les champs comparés, pass/fail et date/heure, sans GUID ni valeurs du foyer.
Une contradiction impose de corriger d’abord les preuves protocole, le décodeur
et les tests, puis de recommencer la validation. Le workflow de confiance reste
inchangé et ne doit jamais publier ces valeurs privées. Une confirmation
dynamique documentaire pourra être ajoutée séparément après comparaison réussie.

## Licence

Le code de ce dépôt est distribué sous [licence MIT](LICENSE).
