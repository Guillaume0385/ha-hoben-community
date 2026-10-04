# Hoben — ha-hoben-community

Intégration communautaire **NON OFFICIELLE** pour Home Assistant, destinée à
prendre en charge les poêles à granulés Hoben via le service MyHOBEN.

Ce projet n'est ni affilié à, ni approuvé par, ni maintenu par Hoben, Inovalp,
Home Assistant ou HACS.

## État du projet

La version `0.0.1` reste un **socle de développement**, sans fonctionnalité
utilisable dans Home Assistant : aucun flux de configuration ni entité.
Une sonde manuelle permet de valider TLS puis OpenClient. Un mode opt-in dédié
prépare maintenant une seule lecture de 20 registres V4 bruts, sans interprétation
ni entité Home Assistant. Le mode `session-open` reste une observation sans lecture.
Elle suit l'identification confirmée dans MyHOBEN 2.2 build 34 : Identifiant HOBEN
normalisé en UserGuid, DeviceGuid initial nul et observation possible d'une demande
d'autorisation ou d'un rejet documenté. Aucun code d'authentification n'est envoyé.
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
**opt-in**, avec les déclenchements explicites suivants :

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

Les quatre modes CLI sont mutuellement exclusifs. Pour **une première connexion
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

C'est le descripteur de notre client de test, pas une valeur extraite de MyHOBEN
ni un format obligatoire du serveur au-delà de la structure documentée.

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

### Une lecture V4 brute, après revue et fusion sur main

L'observation réelle du **4 octobre 2026** a confirmé dynamiquement le profil
**V4** du Hoben Osmose de référence : type produit 5, révision 0, logiciel 8.2,
version application 512 et `unclassified_bytes: 0`. Cela ne classe pas tous les
Osmose comme V4 et ne prouve pas la longueur totale universelle d'OpenedClient.

Après fusion sur `main` protégé, le responsable/utilisateur peut lancer
**Actions → Live Validation → read-v4-state**, avec l'environnement `hoben-live`
et le seul secret `HOBEN_USER_GUID` déjà protégé comme pour `session-open`.
**Ne pas exécuter cette lecture réelle depuis une branche de développement.**
Les tests de la PR sont entièrement simulés et hors ligne. La commande du job,
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

Les registres sont des **UInt16 bruts** dans l'ordre reçu. Aucune température,
puissance, échelle, mode ou signification V4 n'est attribuée. Leur sémantique
sera examinée séparément après la première observation réelle sur `main`.
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

## Licence

Le code de ce dépôt est distribué sous [licence MIT](LICENSE).
