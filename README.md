# Hoben — ha-hoben-community

Intégration communautaire **NON OFFICIELLE** pour Home Assistant, destinée à
prendre en charge les poêles à granulés Hoben via le service MyHOBEN.

Ce projet n'est ni affilié à, ni approuvé par, ni maintenu par Hoben, Inovalp,
Home Assistant ou HACS.

## État du projet

La version `0.0.1` reste un **socle de développement**, sans fonctionnalité
utilisable dans Home Assistant : aucun flux de configuration ni entité.
Une sonde manuelle permet maintenant de préparer le premier test TLS puis
OpenClient. Elle ferme la connexion après l'ouverture et ne lit aucun registre.
L'analyse approfondie de MyHOBEN 2.2 build 34 confirme désormais l'origine du
UserGuid, le DeviceGuid initial nul et le mécanisme d'autorisation d'un nouveau
client ; l'implémentation de la sonde doit encore être alignée sur ces faits avant
le premier test d'association réel. La première version fonctionnelle prévue
(`v0.1.0`) sera en lecture seule.

## Installation future via HACS

La distribution via HACS est prévue. Lorsqu'une version fonctionnelle sera
publiée, le dépôt pourra être ajouté à HACS comme dépôt personnalisé de catégorie
« Integration ». Les instructions de configuration et d'utilisation seront
publiées avec cette version. L'installation du socle actuel ne fournit aucune
fonctionnalité dans Home Assistant.

## Contribution et tests

Lire [AGENTS.md](AGENTS.md), [project.md](project.md) (architecture et roadmap,
source de vérité) et [protocol.md](protocol.md) (faits et incertitudes du protocole)
avant de contribuer. Les tests du socle sont locaux, déterministes et ne
nécessitent ni Home Assistant, ni serveur Hoben.

Avec Python 3.12 ou supérieur et pip prenant en charge les groupes de dépendances
(pip 25.1 ou supérieur) :

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --group dev
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

La CI exécute ces contrôles ainsi que les validateurs officiels HACS et Hassfest.
L'icône communautaire originale représente trois points reliés ; elle ne reprend
aucun logo Hoben ou Inovalp. Les assets locaux `brand/` sont pris en charge à
partir de Home Assistant 2026.3.

### Live Validation sur GitHub Actions

Le workflow [Live Validation](.github/workflows/live-validation.yml) est
**opt-in**, avec deux déclenchements explicites :

- **Avant fusion :** ajouter le label exact `live-validation` à la PR. Seul
  l'événement `pull_request` de type `labeled` pour ce label autorise le job,
  toujours en mode `tls-only`. Retirer puis réajouter ce label permet une nouvelle
  validation volontaire. L'ajout d'un autre label, l'ouverture de la PR et les
  nouveaux commits (`synchronize` ou push) ne lancent pas la sonde, même si le
  label `live-validation` reste présent.
- **Usage normal :** une fois le workflow présent sur `main`, utiliser
  **Actions → Live Validation → Run workflow** (`workflow_dispatch`). Choisir
  `tls-only`, seule option disponible et valeur par défaut.

La CI normale `Validate` reste déterministe et hors ligne vis-à-vis de Hoben.
Live Validation est indépendante des contrôles ordinaires des PR. Pour la PR
qui introduit ce workflow, le MANAGER déclenchera la validation par label et
vérifiera le succès TLS réel avant de décider de sa fusion.

Sur `ubuntu-latest` avec Python 3.12, il exécute uniquement
`python scripts/probe_hoben_connection.py --tls-only` : une connexion TLS vérifiée
à `myhoben.fr:465`, puis fermeture, sans identifiant, secret ni dépendance externe.
Aucun OpenClient, Modbus, appairage, contrôle ou retry automatique n'est effectué.
Le JSON expurgé reste dans les logs, le résumé du job et l'artefact
`live-validation-output`, y compris lorsque la sonde échoue ; son échec fait
échouer le job. Aucun prédiagnostic DNS/TCP supplémentaire n'est ajouté.

Le choix de mode et son aiguillage explicite permettront d'ajouter progressivement
des validations en lecture seule, dans des PR dédiées et revues, en conservant
la préparation et les rapports communs. Aucun mode de session n'est disponible
dans ce workflow.

## Sonde manuelle TLS / OpenClient

Cette validation de développement est **strictement volontaire**, indépendante
des tests et de Home Assistant. Python 3.12+ suffit, sans dépendance externe.
La suite automatisée utilise des flux simulés et interdit les connexions réseau.

Depuis la racine du dépôt, vérifier uniquement TLS, sans identifiant ni message
MyHOBEN :

```sh
python scripts/probe_hoben_connection.py --tls-only
```

La sonde utilise `myhoben.fr:465`, les autorités de confiance du système et la
vérification du nom `myhoben.fr`. Un certificat invalide ou un nom incorrect fait
échouer la connexion. Aucun mode non vérifié, port 433 ou repli en clair n'existe.

Pour tester ensuite **un seul OpenClient avec le code actuellement présent sur
`main`**, fournir les quatre variables ci-dessous. Cette interface de la sonde
est transitoire : elle exige encore explicitement des valeurs que MyHOBEN sait
initialiser lui-même.

| Variable | Valeur à utiliser |
| --- | --- |
| `HOBEN_USER_GUID` | **Identifiant HOBEN réel**, normalisé en GUID de 32 caractères hexadécimaux sans tirets |
| `HOBEN_DEVICE_GUID` | pour une première association : **`00000000000000000000000000000000`** ; ensuite, DeviceGuid attribué par le serveur et persisté |
| `HOBEN_DEVICE_INFO` | description du terminal ; la sonde actuelle l'exige explicitement |
| `HOBEN_BUILD` | utiliser **34** pour reproduire le build Android analysé |

Ces valeurs reflètent maintenant le comportement statiquement confirmé de
MyHOBEN : le UserGuid provient directement de l'**Identifiant HOBEN** saisi ou
scanné, sans hash ni dérivation ; un nouveau client démarre avec
`Guid.Empty` sans tirets, soit 32 zéros. Le nom usuel du poêle n'est pas envoyé
dans `OpenClient`.

La prochaine modification de la sonde devra faire de ces faits protocolaires des
valeurs/comportements internes appropriés, plutôt que d'exiger un DeviceGuid
préexistant pour une première connexion.

Exemple Bash avec saisie masquée, sans placer les identifiants dans l'historique
ou les arguments du processus (ne pas activer `set -x`) :

```bash
IFS= read -r -s -p 'Identifiant HOBEN (GUID sans tirets) : ' HOBEN_USER_GUID
printf '\n'
HOBEN_DEVICE_GUID=00000000000000000000000000000000
HOBEN_DEVICE_INFO='ha-hoben-community/manual/en/Python/Linux/0/0/1/0/0,0'
HOBEN_BUILD=34
export HOBEN_USER_GUID HOBEN_DEVICE_GUID HOBEN_DEVICE_INFO HOBEN_BUILD
python scripts/probe_hoben_connection.py --session
unset HOBEN_USER_GUID HOBEN_DEVICE_GUID HOBEN_DEVICE_INFO HOBEN_BUILD
```

Le DeviceInfo ci-dessus est un descripteur de sonde communautaire, pas une
valeur extraite de MyHOBEN. Il ne faut pas le présenter comme un format obligatoire
du serveur au-delà de la structure générale documentée dans `protocol.md`.

Le rapport JSON contient uniquement l'hôte/port, l'état et, si l'ouverture
réussit, le type de message, les champs produit/logiciel/application, le profil
et le nombre d'octets supplémentaires déjà reçus (`unclassified_bytes`).
Les UserGuid, DeviceGuid, codes d'autorisation et trames brutes sont exclus. Le
UserGuid réel doit être traité comme un secret d'association même s'il est
imprimé/accessible à l'utilisateur.
`profile: "unknown"` reste un succès, notamment pour la branche V6/V6v16 ambiguë.
Le code de sortie vaut 0 pour un succès, 1 pour un échec, 2 pour un usage invalide.

En cas d'échec, `error` distingue TLS, transport, EOF, délai, entrées invalides et
protocole. Un type inattendu est rapporté uniquement par son numéro
(`unexpected_message_type`, `message_type`) ; sa charge utile n'est pas décodée.
L'association/autorisation est volontairement absente de la sonde actuelle :
aucun code n'est demandé ni envoyé. L'analyse de l'APK confirme toutefois que
`DeviceAuthReq (0x2F)` demande à MyHOBEN un **« Code d'authentification ? »**,
puis que l'application répond par `DeviceAuthRes (0x30)` avec le code sur deux
octets little-endian. Ainsi, un `unexpected_message_type` avec
`message_type: 47` pendant une première association est une observation
attendue à analyser, pas la preuve d'un protocole erroné. La sonde ferme alors
sans requête Modbus, commande de poêle ni reconnexion automatique.

Les délais par défaut sont 10 s pour la connexion, chaque lecture et chaque
écriture/drain, 5 s pour la fermeture et 30 s pour l'échange complet après TLS.
Les Ping ou fragments successifs ne réinitialisent pas ce dernier délai.
Seuls les **48 premiers octets confirmés** d'OpenedClient sont décodés ; sa
longueur totale reste inconnue. Le suffixe déjà reçu n'est jamais traité comme
un autre message, même s'il commence par un Ping.

Pour les développeurs, `AsyncTlsTransport.connect/write/read/close` fournit les
octets bruts avec des erreurs distinctes `TransportTimeout` et `TransportEOF`.
`open_session_once(transport, user_guid=..., build=..., device_guid=...,
device_info=...)` possède le cycle connexion/fermeture et retourne
`OpenSessionResult`. Utiliser sa méthode `safe_report()` pour les diagnostics ;
ne pas exporter l'objet complet avec `dataclasses.asdict()`, car le résultat du
codec conserve le DeviceGuid. Ces modules n'importent pas Home Assistant.

## Licence

Le code de ce dépôt est distribué sous [licence MIT](LICENSE).
