# Branche `experimental` — recherche du protocole Hoben en lecture seule

> **Proposition documentaire en attente de revue du propriétaire.** Cette page
> décrit le processus souhaité. Elle ne configure pas GitHub, ne change pas les
> permissions, ne modifie pas les workflows et n'autorise aucun test réel par
> elle-même. Les protections effectives restent celles des workflows en vigueur.

## Deux circuits séparés

| Circuit | Branche cible | Objectif | Conditions de fusion |
| --- | --- | --- | --- |
| Recherche protocolaire | `experimental` | Expérimentations H1/H2, trames, Ping/Pong, observations Modbus **en lecture seule** | **Revue simplifiée MANAGER uniquement**, tests ciblés et vérification de sécurité ; **pas de CODEX REVIEW** ni de `state:validate` |
| Intégration publiée | `main` | Code stable Home Assistant/HACS et bibliothèques protocolaires validées | **CODEX REVIEW indépendant, puis MANAGER**, tests complets, HACS/Hassfest et gate live pré-fusion si applicable, selon `AGENTS.md` |

Le propriétaire peut appliquer à `experimental` des vérifications de merge
plus légères que celles de `main`. Cela concerne **la fusion de code**, pas
l'autorisation de remettre les identifiants Hoben à ce code.

## Revue MANAGER simplifiée pour les PR vers `experimental`

Le **critère de routage est la branche cible de la PR** (champ GitHub `base.ref`),
non son nom, ses labels ou la branche source :

- **Base `experimental` :** aucune pré-revue CODEX REVIEW, aucune approbation
  indépendante ni passage obligé par `state:validate`. CODEX DEV termine
  l'implémentation, exécute les tests ciblés puis place l'Issue en `state:review`.
  Le MANAGER prend **directement** la PR en revue, vérifie le diff, le scénario,
  les résultats des tests ciblés, l'absence de fuite d'identifiants, et
  l'absence de commande ou écriture réelle. Si ces points sont satisfaits,
  il peut fusionner vers `experimental` sans attendre la campagne live H1/H2 ;
  la campagne sera lancée séparément après autorisation du MANAGER. Des
  corrections retournent à CODEX DEV (`state:in-progress` puis `state:review`),
  **sans étape CODEX REVIEW**. Une erreur CI pertinente ou un risque de
  sécurité réel reste un motif de correction, pas une dérogation silencieuse.
- **Base `main` :** circuit complet inchangé : `state:review` → CODEX REVIEW
  indépendant → `state:validate` → MANAGER → validations requises → merge.
  La promotion depuis `experimental` passe obligatoirement par une PR dédiée
  ciblant `main`; une revue passée sur `experimental` ne remplace jamais celle
  du code finalement livré.

Les agents et tâches programmées doivent appliquer ce filtrage : **PRE-REVIEW
ignore toute PR dont la base est `experimental`**, et MANAGER ne réclame pas
son approbation avant une fusion expérimentale. Les approbations GitHub
éventuellement exigées par une règle de protection de branche sont distinctes :
leur réglage doit correspondre à cette politique. Les accès aux secrets sont
gérés séparément dans la section suivante. Si l'Issue couvre aussi une future
livraison stable, conserver sa traçabilité jusqu'à la PR finale vers `main` ;
ne pas marquer cette livraison comme réalisée après une simple fusion de
recherche.

## Cycle expérimental

1. Préparer une petite PR ciblant **`experimental`** (pas `main`) et y
   associer le scénario, la capture attendue, les limites et un test hors ligne.
2. Faire examiner les octets émis et les modules exécutés : TLS vérifié,
   destination MyHOBEN documentée, requêtes de lecture uniquement, arrêt borné,
   aucun paramètre libre de commande ou de destination. Ne jamais envoyer de
   commande de marche/arrêt, écriture Modbus, association ou mode technique.
3. Après fusion et examen du **commit exact**, MANAGER demande éventuellement
   **un** run GitHub Actions expérimental ; aucun lancement implicite au merge,
   au push, par cron ni à chaque passage horaire.
4. Relever le SHA, la catégorie de résultat, les arrêts et les métadonnées
   anonymisées. Stocker les RX privés uniquement chiffrés, avec une clé privée
   conservée hors GitHub ; conserver les fixtures expurgées.
5. Corriger ou recommencer dans une nouvelle PR de recherche. Le statut « test
   expérimental réussi » ne démontre pas à lui seul la frontière OpenedClient
   ni la sécurité de fusion vers `main`.
6. Quand le comportement est confirmé, ouvrir une **PR finale vers `main`**,
   avec les tests de non-régression et les mises à jour de `protocol.md` et
   `project.md`. Les contrôles habituels de `main` demeurent obligatoires.

La campagne #48/#49 peut préparer des observations avant une validation finale
de PR ; `state:blocked` n'empêche pas le travail documentaire et les
préparatifs sans secret. Une vraie observation reste soumise au contrôle du
workflow installé et de la configuration effective de l'environnement.

## Accès aux secrets : ne pas confondre branche et environnement

**Préférer un environnement séparé `hoben-experimental`** : règle de déploiement
sélectionnant uniquement la branche `experimental`, approbation obligatoire
par le propriétaire ou un reviewer de confiance avant que le job puisse accéder
aux secrets, secrets limités à la campagne, aucun accès aux forks ni aux PR
non fusionnées. Le propriétaire configure ces règles dans GitHub Settings ;
aucun agent ne les crée ou ne les assouplit.

Si le propriétaire choisit plutôt d'ouvrir **`hoben-live`** à
`experimental`, ne jamais utiliser « No restriction » : autoriser
explicitement les deux branches `main` et `experimental`, conserver la
protection de `main` et ajouter une approbation de déploiement indépendante
pour toute exécution susceptible de recevoir un identifiant. Un code fusionné
sur `experimental` pourrait autrement utiliser les secrets dans un workflow
distinct : un simple `if:` du workflow habituel ne protège pas ce cas.

Dans les deux cas, la sélection de branche seule ne remplace pas la relecture
du code exécuté ni le contrôle humain avant l'accès à un identifiant réel.
Ne pas déplacer `HOBEN_USER_GUID` dans des secrets globaux du dépôt, les logs,
les arguments shell, les commentaires GitHub ou des artefacts non chiffrés.

## Changements techniques et administratifs encore nécessaires

- **Propriétaire GitHub :** configurer la protection légère de `experimental`
  (PR + revue humaine pour les modifications de code ayant accès aux secrets),
  puis l'environnement, ses branches explicitement autorisées et son
  approbateur. Ne rien modifier sur `main` avant revue.
- **PR technique distincte :** adapter les workflows/gates H1/H2 existants,
  aujourd'hui strictement liés à `main` et à la politique `hoben-live`
  `main`-only. Une PR purement documentaire n'active pas les nouvelles règles ;
  les refus de gate existants ne doivent pas être contournés.
- **MANAGER :** ne jamais considérer un résultat expérimental comme un
  `live-hoben-authenticated=success` de validation de livraison et ne jamais
  fusionner vers `main` sans la revue complète habituelle.

## Critères d'ouverture des tests réels

Avant toute première sonde sur le serveur Hoben, vérifier cumulativement :
l'environnement et la règle d'approbation effective, le commit exact revu,
le workflow installé sur une branche de confiance, la destination TLS fixe,
la liste des seuls messages de lecture autorisés, les budgets de temps/sessions,
le chiffrement préalable des captures et la disponibilité d'un rapport
anonymisé. Tout élément inconnu ou toute vérification inaccessible entraîne
**NOT RUN** plutôt qu'un accès approximatif aux secrets.

Ce document ne modifie aucune donnée de `protocol.md` et ne présume aucune
longueur de trame inconnue.
