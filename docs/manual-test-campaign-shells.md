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
