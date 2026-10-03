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
La première version fonctionnelle prévue (`v0.1.0`) sera en lecture seule.

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
**opt-in**, déclenché uniquement à la main via **Actions → Live Validation →
Run workflow** (`workflow_dispatch`). Choisir le mode `tls-only`, seule option
disponible et valeur par défaut. La CI normale `Validate` reste déterministe et
hors ligne vis-à-vis de Hoben ; Live Validation n'est jamais requis pour les PR.

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
dans ce workflow. Si GitHub ne propose pas son lancement depuis la branche de PR,
le premier lancement manuel pourra avoir lieu après fusion sur `main`.

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

Pour tester ensuite **un seul OpenClient**, fournir les quatre variables :

| Variable | Valeur fournie par le testeur |
| --- | --- |
| `HOBEN_USER_GUID` | UserGuid existant, transmis tel quel |
| `HOBEN_DEVICE_GUID` | DeviceGuid existant, transmis tel quel ; aucune génération |
| `HOBEN_DEVICE_INFO` | Description du terminal, transmise telle quelle |
| `HOBEN_BUILD` | Entier de 0 à 65535, obligatoire |

Le build **34** est celui de MyHOBEN Android 2.2 analysé dans `protocol.md` ; il
n'est pas une valeur par défaut. Le format initial du DeviceGuid reste à valider.
Ne pas inventer un identifiant pour contourner cette incertitude.

Exemple Bash avec saisie masquée, sans placer les identifiants dans l'historique
ou les arguments du processus (ne pas activer `set -x`) :

```bash
IFS= read -r -s -p 'UserGuid : ' HOBEN_USER_GUID
printf '\n'
IFS= read -r -s -p 'DeviceGuid : ' HOBEN_DEVICE_GUID
printf '\n'
IFS= read -r -s -p 'DeviceInfo : ' HOBEN_DEVICE_INFO
printf '\n'
read -r -p 'Build (34 = build Android analysé) : ' HOBEN_BUILD
export HOBEN_USER_GUID HOBEN_DEVICE_GUID HOBEN_DEVICE_INFO HOBEN_BUILD
python scripts/probe_hoben_connection.py --session
unset HOBEN_USER_GUID HOBEN_DEVICE_GUID HOBEN_DEVICE_INFO HOBEN_BUILD
```

Le rapport JSON contient uniquement l'hôte/port, l'état et, si l'ouverture
réussit, le type de message, les champs produit/logiciel/application, le profil
et le nombre d'octets supplémentaires déjà reçus (`unclassified_bytes`).
Les UserGuid, DeviceGuid, codes d'autorisation et trames brutes sont exclus.
`profile: "unknown"` reste un succès, notamment pour la branche V6/V6v16 ambiguë.
Le code de sortie vaut 0 pour un succès, 1 pour un échec, 2 pour un usage invalide.

En cas d'échec, `error` distingue TLS, transport, EOF, délai, entrées invalides et
protocole. Un type inattendu est rapporté uniquement par son numéro
(`unexpected_message_type`, `message_type`) ; sa charge utile n'est pas décodée.
L'association/autorisation est volontairement absente : aucun code n'est demandé
ni envoyé. La sonde envoie uniquement OpenClient et les Pong nécessaires, puis
ferme, sans requête Modbus, commande de poêle ni reconnexion automatique.

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
