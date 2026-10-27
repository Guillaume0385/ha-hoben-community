# Deux campagnes manuelles non activées — #126

Tranche `HOBEN-126-SPLIT-SHELLS-002`, selon la
[consigne MANAGER actuelle](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6435985641).
L'[inventaire #134](manual-test-campaign-inventory.md) décrit la substance à
réutiliser ultérieurement. Cette tranche prépare uniquement les formulaires.

| Définition nouvelle | Choix fermés, tous NOT RUN |
| --- | --- |
| [hoben-protocol-manual.yml](../.github/workflows/hoben-protocol-manual.yml) — Tests expérimentaux MyHOBEN | tls-only, session-open, read-v4-state, h1h2, session-300, session-reconnect, all. |
| [hoben-ha-manual.yml](../.github/workflows/hoben-ha-manual.yml) — Vérification réelle Home Assistant | hoben-live, open-errors, refresh-v4, session-reuse, session-reconnect, cleanup, availability, all. |

Ces identifiants désignent des **scénarios prévus**, sans implémentation ni
promesse de fonctionnement dans ces fichiers. Pour HA, hoben-live désigne le
futur report du socle #112 sans le dupliquer ; open-errors les erreurs
d'ouverture, refresh-v4 la lecture/décodage via coordinator, session-reuse la
réutilisation de TLS/génération, session-reconnect la perte naturelle/récupération,
cleanup la fermeture, availability la disponibilité/erreurs. Aucune association.
Pour le protocole, session-reconnect désigne aussi la cible naturelle à définir ;
le parcours historique avec inhibition des Pong n'est pas raccordé ici.

Chaque fichier possède uniquement workflow_dispatch, un input scenario à choix
fermé et un job sans permissions, environnement, secret, action ou checkout.
Le seul programme est du Bash à littéraux : écrire un résumé fixe NOT RUN et
une annotation d'erreur, puis **exit 1**. Tous les choix, y compris all, sont
refusés sur toute branche. FAILURE signifie ici campagne non activée, aucune
preuve protocolaire ou HA ; le résumé ne prétend pas qu'un test a réussi.
Aucun appel de collecteur, client/coordinator, réseau Hoben, gate ou claim.
Ces fichiers ne sont pas appelables comme workflows réutilisables.

Le [workflow hoben-manual.yml](../.github/workflows/hoben-manual.yml) reste
strictement inchangé et la seule voie live installée. Ses contrôles, choix,
budgets, contrats de rapport et restrictions de branche ne sont pas modifiés.
Les deux nouveaux fichiers ne demandent pas son mutex, puisqu'ils ne lancent
aucune observation ; tout futur raccordement devra conserver le verrou partagé
entre campagnes, l'admission/recheck et toutes les protections existantes.

## Formulaire GitHub et branches

Use workflow from est le sélecteur natif GitHub ; aucun input de ref ni checkout
de substitution n'est ajouté. La présence de fichiers sur experimental ne
prouve pas leur visibilité dans la liste Actions ou le formulaire chargé depuis
la branche par défaut. Aucune UI n'a été vérifiée ni aucun dispatch lancé pour
cette tranche. Les fichiers ne sont pas reportés sur main ; aucune admission
réelle sur main n'est autorisée ou démontrée par ces formulaires inertes.

Une vérification UI par le propriétaire et, si nécessaire, une nouvelle demande
de publication sur main resteront distinctes. Ne pas contourner une absence de
formulaire par API/CLI ou remplacement de branche. Un futur branchement des
collecteurs exige une autre tâche/revue, des tests offline et quatre CI sur le
HEAD exact ; tout test réel exige ensuite sa propre autorisation et les
approbations/protections effectives. DEV ne lance pas de test réel ni de rerun.

Les [tests de contrat](../tests/test_manual_campaign_shells.py) lisent le YAML
installé et exécutent uniquement ses refus Bash dans un dossier temporaire,
sans contexte secret ni appel Actions. Ils couvrent tous les choix sur
experimental/main, les permissions nulles, les clés autorisées et une liste
positive de commandes littérales. Cela prouve le refus local, pas le comportement
de l'UI GitHub ni une admission sur une branche.

## Contrat statique pur — HOBEN-126-SHELL-SEMANTICS-013

Base experimental `5df31d7d51239adace6466922257a96898cb7591`, après #145.
[campaign_shell_semantics.py](../scripts/campaign_shell_semantics.py) reçoit
seulement une enum campaign protocol/ha et des **octets YAML injectés**, immuables,
UTF-8 sans BOM, de 1 à **16 Kio**. Aucune lecture de fichier, environnement,
token, HTTP, client HA ou preuve d'admission. Le validateur n'est raccordé à
aucun workflow, autre lecteur, gate ou collecteur ; son lancement direct sort
avec code 1 sans CLI ni sortie.

PyYAML est déjà déclaré dans le groupe dev (`PyYAML>=6,<7`) : aucune dépendance
n'est ajoutée. Une sous-classe locale de SafeLoader contrôle la structure,
sans modifier les loaders globaux. Avant construction, les tokens sont bornés
à **512**, avec refus de tout tag, ancre, alias ou directive ; le document unique
est limité à **128 nœuds / profondeur 12**. Seuls mappings à clés texte uniques,
listes et scalaires str/int/bool sont construits. Doublons, merge keys, types
inconnus, null, dates/timestamps implicites ou documents multiples refusent.
Les booléens ne peuvent être que true/false en minuscules et les entiers de
petite forme décimale canonique, avant vérification de leur valeur exacte.

Le contrat accepte un sous-ensemble conservateur correspondant aux shells
actuels, dont la clé **`'on'` citée**. La résolution YAML 1.1 de PyYAML ferait
de on/yes des booléens : ces formes ambiguës sont refusées plutôt que supposées
équivalentes à la lecture GitHub. Un refus ne prouve donc pas qu'un autre YAML
est invalide pour GitHub ; il prouve seulement qu'il n'est pas accepté ici.
Commentaires, ordre des clés et présentations YAML sûres peuvent varier, à
condition de produire exactement la structure/littéraux approuvés. Les
expressions Actions `${{ ... }}` sont refusées, même en commentaire.

Les contrôles fermés portent sur :

- nom de campagne et seul trigger workflow_dispatch ; un seul input scenario,
  description/type/required/default actuels et liste exacte ordonnée des choix
  de chaque plan, incluant all sans absence, ajout ou doublon ;
- permissions exactement `{}` au workflow et au job ; unique job not-activated
  sur ubuntu-latest, timeout-minutes entier exactement 1 ;
- une seule étape Bash de refus, nom actuel et clés exactes ; aucune autre clé,
  environnement, secret, action, checkout, condition, stratégie ou bypass ;
- **intégralité de la séquence approuvée** : quatre printf de résumé à littéraux
  vers la seule variable GITHUB_STEP_SUMMARY, un printf d'annotation fixe,
  puis exit 1. Texte, ordre, redirections et fin de séquence doivent correspondre.
  Ni présence d'exit 1 dans un programme arbitraire, ni denylist de commandes.

Il s'agit d'analyse statique : aucun YAML, script Bash, action ou collecteur
n'est exécuté par le validateur. Même positif, le résultat figé reste
**can_start=false / execution=NOT RUN / actions_result=FAILURE**, conversion
booléenne false. Seuls cinq faits statiques peuvent être attestés : trigger,
choix, permissions, job borné inerte et séquence de refus exacte. Toute erreur
laisse tous les faits UNKNOWN, avec catégorie fermée, sans contenu/script ni
exception libre. Une empreinte SHA-256 privée lie campagne et octets injectés ;
elle n'authentifie pas leur source et n'est pas une signature.

Source/identité Git, YAML chargé par GitHub au commit exécuté, workflow_ref,
enregistrement Actions, UI/main, admission/gates, protections, revues,
approbations, claims, mutex, anti-rejeu et fraîcheur restent **UNKNOWN**.
La limitation d'accès au registre Actions (connecteur INVALID_ARGUMENT/400)
et l'impossibilité de self-APPROVED MANAGER ne sont pas levées. Aucun repli de
cette preuve statique vers une autorisation réelle.

Les [tests](../tests/test_campaign_shell_semantics.py) injectent les deux
shells et des mutations synthétiques : déclencheurs, scénarios/plans,
permissions, environnement/secret, commandes ajoutées ou cachées malgré exit 1,
jobs/étapes, YAML malformé/ambigu, tags/alias/doublons, bornes et confidentialité.
DNS/sockets sont interdits ; les tests des tags dangereux interdisent aussi
I/O/exécution. Aucun nouveau test ne lance le Bash. Les tests historiques de
refus local et les autres lecteurs sont conservés/rejoués sans modification.
Les deux shells, transport, autres validateurs, gates, HA, protocole, codecs et
budgets sont inchangés. Aucun test réel, dispatch/rerun, secret, commande poêle,
écriture Modbus, PR main ou fusion DEV ; livraison puis STOP.
