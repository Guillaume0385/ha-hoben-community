# Workflow MANAGER automatique / CODEX DEV automatique par défaut / CHAT DEV manuel facultatif

## Portée et sources

Ce document définit uniquement l'orchestration des agents. Il ne modifie ni le protocole MyHOBEN, ni les droits GitHub, ni les protections de branche, ni les autorisations de tests réels.

La branche de développement est exclusivement `experimental`. Avant toute action, lire sur cette branche `AGENTS.md`, `project.md`, `protocol.md` et `docs/experimental-protocol-workflow.md`. Leurs règles techniques et de sécurité restent prioritaires. Les décisions explicites récentes du propriétaire priment sur les anciens arbitrages contradictoires.

**Références distinctes :** l'Issue #112 est la référence technique de la session V4 et de la reconnexion par inhibition des Pong. L'Issue #81 est un historique de développement ; ne pas la réactiver comme tâche active par déduction. L'Issue #112, même en `state:waiting`, ne porte pas de consigne active de développement par sa seule existence. MANAGER doit obtenir une autorisation explicite du propriétaire et identifier l'Issue de travail autorisée avant d'écrire ou d'attribuer une tâche. Une Issue de référence ne vaut jamais autorisation de développement ou de test live.

## Campagnes Hoben manuelles — #119 phase 2

Phase 1 fusionnée sur main par PR #120 ; main reste inactive pour les collectes.
La [voie manuelle experimental](hoben-manual-workflow.md) est exclusivement
workflow_dispatch du propriétaire. Aucun merge, label, commentaire MANAGER ou
état d'Issue ne lance de test réel. Revues/CI/provenance, environnement et
approbations effectives, claim et recheck sont conservés ; aucun test réel DEV.
Le choix all est séquentiel et les résultats sont explicites par scénario.

## Responsabilités

- **MANAGER (automatique)** : constate l'état réel de GitHub, prépare une petite tâche seulement après autorisation explicite du propriétaire, publie ou met à jour une consigne unique, vérifie les PR, demande les corrections et fusionne seulement les PR conformes sur `experimental`. Il ne lance ni ne reprogramme automatiquement CHAT DEV. Pour CODEX DEV, agent de développement par défaut, MANAGER active et reprogramme l'automatisation existante lorsqu'un développement est explicitement demandé par le propriétaire, attribué à CODEX DEV et vérifié sur GitHub ; il confirme alors l'état réel de l'automatisation. Ce mécanisme ne constitue pas une autorisation de développement implicite.
- **CHAT DEV (manuel, sur demande explicite)** : le propriétaire colle le prompt fourni par MANAGER dans une conversation interactive disposant des permissions GitHub nécessaires. CHAT DEV développe la tâche assignée, exécute les tests hors ligne et ouvre ou corrige une PR ; il ne fusionne jamais.
- **CODEX DEV (automatique par défaut)** : prend les tâches de développement explicitement autorisées et attribuées par MANAGER, qu'elles soient simples ou complexes. Même limites de branche, de sécurité et de livraison que CHAT DEV. Aucune exécution automatique implicite par le seul label : toute activation nécessite une demande du propriétaire, une attribution explicite et une autorisation de tâche vérifiée.

## Contrat de tâche actif

Une seule petite tâche de développement active. Le commentaire MANAGER canonique de l'Issue de travail contient au minimum :

```text
TASK_ID: <identifiant stable>
TASK_OWNER: CHAT_DEV | CODEX_DEV
TASK_STATUS: ready | in-progress | review | blocked
TARGET_BRANCH: experimental
OBJECTIF: ...
PERIMETRE: ...
EXCLUSIONS: ...
TESTS_OFFLINE: ...
CRITERES_ACCEPTATION: ...
PR: <numéro ou aucune>
```

Le commentaire actif doit être identifiable sans relire tout l'historique. Les anciennes décisions sont conservées comme historique et ne sont pas des tâches concurrentes. MANAGER vérifie qu'une seule étiquette `state:*` est présente, sans retirer les autres labels.

## Lancement automatique CODEX DEV et option CHAT DEV manuelle

Lorsque le propriétaire choisit exceptionnellement `CHAT_DEV`, après publication **et vérification GitHub** de la tâche `CHAT_DEV` en `state:ready`, MANAGER notifie le propriétaire et fournit un prompt complet, prêt à copier, comprenant l'Issue, le `TASK_ID`, la branche cible, le lien vers le commentaire canonique et les exclusions. Il ne prétend pas avoir lancé CHAT DEV.

Modèle de prompt à remettre :

> Agis comme CHAT DEV pour `Guillaume0385/ha-hoben-community`. Lis sur `experimental` les quatre documents obligatoires, puis l'Issue de travail indiquée et le commentaire MANAGER actif pour `TASK_ID: <ID>`. Vérifie `TASK_OWNER: CHAT_DEV`, `TASK_STATUS`, `TARGET_BRANCH: experimental` et les critères. Travaille uniquement sur cette tâche : branche issue d'`experimental`, commits, tests hors ligne, PR vers `experimental` (jamais `main`). Corrige la même PR si nécessaire. Aucun test réel ni commande poêle. Continue jusqu'à livraison ou blocage réel ; en cas de blocage, informe-moi d'abord ici, avant tout signalement de blocage au MANAGER. Ne fusionne rien. Termine par PR, HEAD exact, tests et limites.

MANAGER évite les notifications répétées d'une même version de tâche ; si la preuve d'une notification antérieure manque, il ne l'invente pas. Une tâche corrigée ou une nouvelle intervention manuelle nécessaire justifie une nouvelle notification.


## Modèles et reprogrammation des automatisations MANAGER / CODEX DEV

Cette section s'applique aux automatisations **existantes** du propriétaire, et non à des workflows GitHub Actions. Elle ne crée aucune autorisation implicite de développement. Une demande explicite du propriétaire de **lancer, reprendre ou poursuivre un développement identifié** autorise MANAGER à préparer la tâche correspondante et à reprogrammer les agents sans que le propriétaire ait à redemander les horaires. MANAGER vérifie auparavant la tâche, l'absence de conflit et les règles de sécurité.

### Paramètres de programmation

- **CODEX DEV** : activer et reprogrammer sa tâche existante pour une exécution **5 minutes après la préparation et la vérification GitHub** d'une consigne autorisée en `state:ready`.
- **MANAGER** : activer et reprogrammer sa tâche existante pour une exécution **30 minutes après l'exécution prévue de CODEX DEV**, soit **35 minutes après la préparation** dans le cas nominal.
- Utiliser les identifiants d'automatisation existants et leur fuseau horaire ; ne pas créer de doublons, ne pas modifier les autres tâches. Reprogrammer par délai relatif calculé au moment de l'action, et vérifier les confirmations retournées. Si l'heure réelle du lancement CODEX diffère ou est inconnue, ne pas prétendre que MANAGER est exactement 30 minutes après son exécution effective : le décalage concerne l'horaire **prévu**.
- **Aucune tâche de développement autorisée** : désactiver l'automatisation CODEX DEV existante, vérifier le résultat ; laisser MANAGER actif pour le suivi, sans attribuer artificiellement une tâche.
- Si une PR est en cours ou en revue, ne pas attribuer de deuxième développement ; MANAGER peut reprogrammer sa propre surveillance sans réactiver DEV pour une nouvelle tâche.
- Toute erreur, permission manquante ou confirmation absente est rapportée explicitement ; aucune programmation n'est déclarée réussie sans preuve.

### Modèle de prompt — MANAGER

```text
MANAGER — dépôt Guillaume0385/ha-hoben-community.
Issue de référence : #<ISSUE> ; tâche active : <TASK_ID>.
Lire AGENTS.md, project.md, protocol.md et docs/experimental-protocol-workflow.md
sur experimental, puis l'Issue, le commentaire actif, les PR et les CI.
Vérifier l'autorisation propriétaire, les dépendances, les labels state:*,
la base experimental, le HEAD exact, le diff, les quatre checks
tests/ha-tests/hacs/hassfest et les règles lecture seule/confidentialité.
Une seule petite PR de développement active ; revue, correction sur même PR,
fusion seulement si conforme ; bilan GitHub et tâche suivante.
Après publication et vérification d'une nouvelle consigne CODEX DEV autorisée
en state:ready : activer/reprogrammer CODEX DEV existant dans 5 minutes,
puis activer/reprogrammer MANAGER existant 30 minutes après l'horaire prévu
de CODEX DEV (35 minutes après préparation nominale).
Sans nouvelle tâche autorisée : désactiver CODEX DEV et confirmer ;
MANAGER conserve le suivi. Ne jamais créer d'automatisation en doublon.
Aucun test réel ni commande poêle sans autorisation et mécanisme dédiés.
```

### Modèle de prompt — CODEX DEV

```text
CODEX DEV — dépôt Guillaume0385/ha-hoben-community.
Prendre exclusivement l'Issue #<ISSUE> et TASK_ID <TASK_ID> si state:ready,
TASK_OWNER: CODEX_DEV, TARGET_BRANCH: experimental et autorisation vérifiée.
Lire les quatre documents obligatoires sur experimental et la consigne active.
Vérifier qu'aucune autre tâche de développement n'est active.
Passer à state:in-progress, travailler uniquement sur la petite tâche attribuée,
tests hors ligne, une PR vers experimental, jamais main.
À livraison : state:review, HEAD exact, tests et limites ; ne pas fusionner.
Si bloqué, rapporter le motif ; aucune tâche de remplacement auto-attribuée.
Lecture seule V4, TLS vérifié, aucune commande poêle, aucun secret/GUID/RX brut,
aucun test réel depuis DEV ou CI ordinaire.
La programmation de l'agent est gérée par MANAGER, pas par CODEX DEV.
```

### Procédure lors d'une demande du propriétaire

1. Identifier l'Issue et la tâche autorisée ; si la demande est ambiguë, demander une clarification plutôt que choisir une autre Issue.
2. Mettre à jour **les prompts des deux automatisations existantes** en suivant les modèles, avec Issue, TASK_ID, branche, périmètre et contraintes à jour ; conserver les identifiants existants et les consignes de sécurité.
3. Publier/actualiser l'unique commentaire de tâche active sur GitHub, vérifier les critères, l'absence de conflit et `state:ready`.
4. Activer/reprogrammer CODEX DEV à +5 min, puis MANAGER à +35 min (30 min après l'heure prévue de CODEX) ; vérifier les deux retours d'outil et les états activés.
5. Après chaque fusion et préparation de tâche suivante, répéter la mise à jour des prompts et des horaires **automatiquement**, sans nouvelle demande d'horaire. Si aucune tâche suivante n'est autorisée, désactiver CODEX DEV.
6. Rendre compte des modifications effectives et des échecs ; aucune mise à jour d'automatisation ne constitue une validation de CI ou de tests réels.

## Revue, fusion et suite

Pour toute PR, vérifier `base.ref == experimental`, la correspondance avec la tâche active, le diff complet, le HEAD SHA exact, les remarques ouvertes, l'architecture, la confidentialité et les tests pertinents. Les quatre checks `tests`, `ha-tests`, `hacs`, `hassfest` doivent être réussis sur le HEAD examiné. Un check manquant, en attente ou en échec interdit la fusion.

En cas de défaut : commentaires factuels, `state:in-progress`, correction sur **la même PR**, puis nouvelle revue du nouveau HEAD. Si conforme : fusion par MANAGER uniquement, confirmation du SHA intégré à `experimental`, bilan bref et préparation d'une seule tâche suivante. Aucune PR `main` sans nouvelle demande explicite. Ne pas fermer une Issue de chantier avant tous ses critères validés.

## Échecs, tests réels et sécurité

Un échec GitHub transitoire peut être vérifié puis retenté une fois. Un refus explicite de permission ou de sécurité n'est jamais contourné ; ne pas annoncer une écriture non confirmée. La surveillance MANAGER peut se poursuivre sans autoriser de développement supplémentaire.

Tous les tests DEV et CI ordinaires sont hors ligne. Les tests réels passent exclusivement par des mécanismes GitHub installés, des budgets et gates distincts, et les approbations d'environnement requises. `NOT RUN`, `PENDING APPROVAL` et `inconclusive` ne valent pas validation.

Sécurité absolue : lecture seule, TLS vérifié vers `myhoben.fr:465`, aucune écriture Modbus 06/16/22, aucune commande du poêle, aucun secret, GUID, RX brut ou donnée domestique exposé, aucune frontière totale `OpenedClient` inventée. Préserver les codecs et tests existants. La validation Home Assistant réelle ne remplace pas la validation expérimentale préalable exigée.

## Compte rendu MANAGER

Rapport concis : Issue de travail, étape, TASK_ID, agent, état GitHub, PR, HEAD, quatre checks, tests réels (exécutés / NOT RUN / en attente), décision, prochaine action et confirmation de programmation CODEX DEV/MANAGER ou nécessité de lancer CHAT DEV manuellement. Aucun succès sans preuve GitHub.
