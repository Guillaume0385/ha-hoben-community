# Workflow MANAGER automatique / CHAT DEV manuel / CODEX DEV expert

## Portée et sources

Ce document définit uniquement l'orchestration des agents. Il ne modifie ni le protocole MyHOBEN, ni les droits GitHub, ni les protections de branche, ni les autorisations de tests réels.

La branche de développement est exclusivement `experimental`. Avant toute action, lire sur cette branche `AGENTS.md`, `project.md`, `protocol.md` et `docs/experimental-protocol-workflow.md`. Leurs règles techniques et de sécurité restent prioritaires. Les décisions explicites récentes du propriétaire priment sur les anciens arbitrages contradictoires.

**Références distinctes :** l'Issue #112 est la référence technique de la session V4 et de la reconnexion par inhibition des Pong. L'Issue #81 est un historique de développement ; ne pas la réactiver comme tâche active par déduction. MANAGER doit identifier l'Issue de travail explicitement autorisée avant d'écrire ou d'attribuer une tâche. Une Issue de référence ne vaut jamais autorisation de développement ou de test live.

## Responsabilités

- **MANAGER (automatique)** : constate l'état réel de GitHub, choisit une petite tâche autorisée, publie ou met à jour une consigne unique, vérifie les PR, demande les corrections et fusionne seulement les PR conformes sur `experimental`. Il ne lance ni ne reprogramme automatiquement CHAT DEV ou CODEX DEV.
- **CHAT DEV (manuel, par défaut)** : le propriétaire colle le prompt fourni par MANAGER dans une conversation interactive disposant des permissions GitHub nécessaires. CHAT DEV développe la tâche assignée, exécute les tests hors ligne et ouvre ou corrige une PR ; il ne fusionne jamais.
- **CODEX DEV (exceptionnel)** : réservé aux tâches réellement complexes (architecture, concurrence asynchrone, protocole difficile), après décision motivée de MANAGER. Même limites de branche, de sécurité et de livraison que CHAT DEV. Aucune exécution automatique implicite.

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

## Notification et lancement manuel

Après publication **et vérification GitHub** de la tâche `CHAT_DEV` en `state:ready`, MANAGER notifie le propriétaire et fournit un prompt complet, prêt à copier, comprenant l'Issue, le `TASK_ID`, la branche cible, le lien vers le commentaire canonique et les exclusions. Il ne prétend pas avoir lancé CHAT DEV.

Modèle de prompt à remettre :

> Agis comme CHAT DEV pour `Guillaume0385/ha-hoben-community`. Lis sur `experimental` les quatre documents obligatoires, puis l'Issue de travail indiquée et le commentaire MANAGER actif pour `TASK_ID: <ID>`. Vérifie `TASK_OWNER: CHAT_DEV`, `TASK_STATUS`, `TARGET_BRANCH: experimental` et les critères. Travaille uniquement sur cette tâche : branche issue d'`experimental`, commits, tests hors ligne, PR vers `experimental` (jamais `main`). Corrige la même PR si nécessaire. Aucun test réel ni commande poêle. Continue jusqu'à livraison ou blocage réel ; en cas de blocage, informe-moi d'abord ici, avant tout signalement de blocage au MANAGER. Ne fusionne rien. Termine par PR, HEAD exact, tests et limites.

MANAGER évite les notifications répétées d'une même version de tâche ; si la preuve d'une notification antérieure manque, il ne l'invente pas. Une tâche corrigée ou une nouvelle intervention manuelle nécessaire justifie une nouvelle notification.

## Revue, fusion et suite

Pour toute PR, vérifier `base.ref == experimental`, la correspondance avec la tâche active, le diff complet, le HEAD SHA exact, les remarques ouvertes, l'architecture, la confidentialité et les tests pertinents. Les quatre checks `tests`, `ha-tests`, `hacs`, `hassfest` doivent être réussis sur le HEAD examiné. Un check manquant, en attente ou en échec interdit la fusion.

En cas de défaut : commentaires factuels, `state:in-progress`, correction sur **la même PR**, puis nouvelle revue du nouveau HEAD. Si conforme : fusion par MANAGER uniquement, confirmation du SHA intégré à `experimental`, bilan bref et préparation d'une seule tâche suivante. Aucune PR `main` sans nouvelle demande explicite. Ne pas fermer une Issue de chantier avant tous ses critères validés.

## Échecs, tests réels et sécurité

Un échec GitHub transitoire peut être vérifié puis retenté une fois. Un refus explicite de permission ou de sécurité n'est jamais contourné ; ne pas annoncer une écriture non confirmée. La surveillance MANAGER peut se poursuivre sans autoriser de développement supplémentaire.

Tous les tests DEV et CI ordinaires sont hors ligne. Les tests réels passent exclusivement par des mécanismes GitHub installés, des budgets et gates distincts, et les approbations d'environnement requises. `NOT RUN`, `PENDING APPROVAL` et `inconclusive` ne valent pas validation.

Sécurité absolue : lecture seule, TLS vérifié vers `myhoben.fr:465`, aucune écriture Modbus 06/16/22, aucune commande du poêle, aucun secret, GUID, RX brut ou donnée domestique exposé, aucune frontière totale `OpenedClient` inventée. Préserver les codecs et tests existants. La validation Home Assistant réelle ne remplace pas la validation expérimentale préalable exigée.

## Compte rendu MANAGER

Rapport concis : Issue de travail, étape, TASK_ID, agent, état GitHub, PR, HEAD, quatre checks, tests réels (exécutés / NOT RUN / en attente), décision, prochaine action et nécessité de lancer manuellement CHAT DEV ou CODEX DEV. Aucun succès sans preuve GitHub.
