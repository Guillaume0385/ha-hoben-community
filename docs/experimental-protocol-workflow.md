# Circuit expérimental Hoben — validation Home Assistant et recherche réseau

> Décision du propriétaire, 9 octobre 2026 — **aucune PR vers `main` sans demande explicite de l'utilisateur**. Cette page définit le workflow souhaité et l'exécution autorisée sur `experimental`. Elle ne prouve ni la présence des secrets/environnements, ni la disponibilité actuelle de tous les workflows GitHub. Ne jamais confondre code de test préparé, workflow installé, dry-run et test Hoben réel.

## Deux voies distinctes sur `experimental`

| Voie | Environnement GitHub | Objectif | Intégration Home Assistant |
| --- | --- | --- | --- |
| **`hoben-live`** | `hoben-live` | Valider sur le serveur réel Hoben l'authentification, la connexion TLS, l'attribution/conservation DeviceGuid, la gestion de session, les lectures V4, disponibilité/reconnexion et cycle de vie **avec les mêmes composants et le même comportement que le plugin Home Assistant au commit testé** | Réutiliser autant que possible le client, les modèles et les chemins réellement utilisés par HA ; constater les écarts sans inventer de succès |
| **`hoben-experimental`** | `hoben-experimental` | Sonder et enregistrer le comportement réseau, confronter H1/H2, observer les trames et données inconnues, avec captures privées chiffrées et rapport anonymisé | **Jamais intégré au runtime HA** : les collecteurs, hypothèses de framing et instruments de capture restent dans les scripts/fixtures de laboratoire |

Les deux voies sont des expériences en lecture seule, exécutées depuis GitHub Actions, sur un SHA **fusionné et revu** de `experimental`. Elles ne modifient pas le poêle : aucune commande de marche/arrêt, changement de consigne, ventilation, écriture Modbus (06/16/22), association ou accès installateur. La destination de production est le serveur TLS déjà documenté dans `protocol.md`, avec validation du certificat.

**`hoben-live` ne signifie pas que le runtime est déjà correct ou persistant.** Il doit vérifier le comportement du code réellement présent et créer une Issue lorsqu'un écart est observé. **`hoben-experimental` ne peut pas servir de preuve de qualité du plugin** : ses hypothèses sont distinctes du protocole confirmé.

## Workflow GitHub et autonomie

```text
CODEX DEV : petite Issue autorisée → développement + tests offline
   ↓
PR vers experimental, base.ref = experimental, state:review
   ↓
MANAGER : revue directe du diff/HEAD/CI, confidentialité, lecture seule
   ↓
MANAGER : merge automatique vers experimental (si conditions satisfaites)
   ↓
MANAGER : déclenche en autonomie le scénario hoben-live et/ou hoben-experimental
   ↓
GitHub Actions : gate + environnement effectif + éventuelle approbation GitHub
   ↓
MANAGER : résultat expurgé, observations, protocol.md étayé si applicable
   ↓
MANAGER : Issues dédupliquées → state:ready pour la prochaine tâche autorisée
   ↓
CODEX DEV : reprend le cycle
```

- **Aucune approbation supplémentaire dans la conversation ChatGPT** n'est requise avant un test expérimental prévu par cette politique. MANAGER peut lancer, lire les résultats et préparer une nouvelle Issue sans attendre la réponse de l'utilisateur. **Une approbation d'environnement exigée par GitHub reste applicable : jamais de bypass, de modification de Settings, ni d'accès aux secrets avant accord effectif du reviewer GitHub.**
- Plusieurs PR/Issues peuvent être fusionnées **successivement** sur `experimental` sans contrôle du propriétaire ; la revue MANAGER du SHA exact et la CI pertinente restent obligatoires. Éviter les grands chantiers simultanés ; ne déclencher de nouveau test que si le scénario/SHA a réellement changé et est revu.
- Chaque étape effectuée déclenche une notification informative MANAGER (`EXP-REVIEW`, `EXP-MERGE`, `EXP-TEST-START`, `EXP-TEST-RESULT`, `EXP-PROTOCOL`, `EXP-ISSUES`, `EXP-NEXT`) et MANAGER **continue**. Aucun doublon de notification pour le même run/SHA/état.
- **Aucune promotion vers `main` décidée par MANAGER** : seul le propriétaire peut demander de **préparer** la PR finale. Sans sa demande, pas de branche de promotion, pas de PR vers `main`, pas de merge. Lorsqu'elle est explicitement demandée, reprendre la revue CODEX REVIEW indépendante, les tests et règles de livraison stables ; aucune réussite expérimentale ne les remplace.

## Mise en place technique — état actuel et travaux #54

La PR #55 a été fusionnée sur `experimental`, apportant `scripts/run_experimental_boundary.py` et la capture/analyse H1/H2 ; ces scripts ne sont pas importés par le plugin HA. Le bootstrap précédent de la PR #56 visait `main` et a été fermé **sans fusion** ; ses mécanismes testés constituent au mieux des éléments de référence **à adapter**. Les workflows existants `live-validation.yml`, `manager-live-hoben.yml` et `opened-client-boundary.yml` conservent aujourd'hui des déclencheurs/règles liées à `main` : **ne pas les présenter comme des workflows expérimentaux opérationnels avant le développement et l'installation réels**.

L'Issue [#54](https://github.com/Guillaume0385/ha-hoben-community/issues/54) demande la mise en place des **deux voies** sur `experimental` avec un gate fiable, des scénarios allowlistés, une preuve de déclenchement MANAGER réellement faisable via sa connexion GitHub et des tests de sécurité offline.

Un workflow `issues:labeled` charge sa définition depuis la branche par défaut, pas depuis `experimental`. Un `workflow_dispatch` d'un nouveau workflow absent de `main` ne doit pas être considéré comme acquis. CODEX DEV doit sélectionner et **démontrer** un déclencheur adapté au périmètre sans fusion vers `main`. Un `push` autorisé sur `experimental` peut déclencher une étape **sans secret**, mais il ne vaut jamais à lui seul revue/autorisation de remettre les identifiants à du code nouvellement fusionné. L'absence de voie sûre ou d'outil de déclenchement se rapporte honnêtement par `NOT RUN` avec une Issue de prérequis, sans contourner GitHub.

## Gouvernance des secrets et protections

Le propriétaire déclare avoir effectué les réglages GitHub. L'API disponible a confirmé `experimental.protected=true`, **sans permettre de consulter les règles détaillées de protection, les environnements, leurs approbations ni leurs secrets**. Cette limite n'est pas une preuve de leur absence ou de leur conformité.

Avant un test réel, vérifier **effectivement** sur GitHub et dans le gate du workflow :
- la branche `experimental` protégée, le code et le HEAD revus et les checks ciblés réussis ;
- les environnements distincts `hoben-live` et `hoben-experimental`, leurs politiques d'accès à `experimental`, leur approbation GitHub lorsqu'elle est configurée, et la provenance du job qui demande le secret ;
- l'injection des seuls `HOBEN_USER_GUID` et `HOBEN_DEVICE_GUID` nécessaires, dans l'étape minimale, sans faire hériter au code candidat d'un token GitHub doté de droits d'écriture ;
- le caractère lecture seule, le TLS vérifié, les budgets bornés et l'interdiction d'une destination/script/mode libre ;
- pour `hoben-experimental`, la possession hors GitHub de la **clé privée** du certificat public contrôlé, préflight CMS avant TLS, RX uniquement chiffré avec AES-256-GCM et RSA-OAEP/SHA256, rapports allowlistés sans donnée domestique, et rétention maximale de sept jours.

Aucun secret n'est écrit dans les Issues/PR, fichiers de config, logs, summaries ou captures en clair. Les données brutes restent chiffrées avant toute sortie du runner. Si le gate ne peut vérifier la politique/approbation ou si le certificat est invalide : **`NOT RUN` / `PENDING APPROVAL`**, notification, aucune connexion Hoben.

## Contrat des essais et exploitation

**`hoben-live` :** exercer par le vrai client du plugin, lorsque disponible, les opérations de connexion/TLS, ouverture et identification, session, lecture et refresh V4, Ping/Pong/DataUpdated seulement là où réellement implémentés et documentés, perte de connexion/reprise et unload. Conserver les observations expurgées. Les fonctionnalités non implémentées ou non confirmées donnent lieu à `unsupported` / `inconclusive` ou à une Issue ciblée, jamais à des assertions fictives.

**`hoben-experimental` :** conserver la campagne H1/H2 déjà documentée (#48/#49/#55), plafonds actuels **6 H1 + 6 H2**, **90 s et 1 Mio RX par session**, arrêt anticipé sans replay implicite. Les silences, préfixes et tailles observés ne prouvent pas à eux seuls la frontière OpenedClient. Les captures conservent les octets inconnus uniquement sous chiffrement, avec analyse locale privée et résumé public expurgé.

Chaque run doit être corrélé à son **SHA, scénario, acteur autorisé, état réel, identifiant/URL GitHub, résultats et limites**, et exécuté au plus une fois sans nouvelle décision et nouveau SHA/scénario. Pas de test réel dans pytest, CI PR, DEV, cron ou automatisme de merge dépourvu d'une décision MANAGER contrôlée. Un dry-run secretless permet d'établir le chemin de déclenchement **sans** interpréter un succès synthétique comme preuve réseau.

Après le run, MANAGER évalue les informations vérifiées, propose sur `experimental` une PR `protocol.md` uniquement pour les faits dûment étayés (`CONFIRMÉ` / `OBSERVÉ` / `À VALIDER`), crée ou actualise les Issues utiles, et peut autoriser la prochaine Issue `state:ready` sans solliciter le propriétaire. Un run échoué n'arrête pas les autres tâches sans lien avec lui.

## Portée des anciennes voies `main`

Les anciens workflows et procédures de validation sur `main` restent historiques et inchangés tant que le propriétaire n'a pas demandé une livraison. **Ils ne doivent plus être considérés comme un prérequis** à la recherche H1/H2 ou à la validation expérimentale autonome. N'élargir ni secrets ni droits de `main` dans le cadre de #54. La préparation d'une PR de promotion sur `main` est réservée à une demande ultérieure et explicite du propriétaire.
