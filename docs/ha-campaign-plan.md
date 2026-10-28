# Plan Home Assistant offline — #126

## Exécution courante — 016+017

L’arbitrage des budgets dans #126 du 27/10/2026 lève les inconnues ci-dessous.
Le [contrat runtime courant](manual-test-campaign-runtime.md) décrit les
scénarios raccordés et leurs limites effectivement appliquées. Le module de
planification et les sections suivantes restent l’historique offline 004/005,
sans autorité d’exécution ; leurs catalogues fermés sont réutilisés. Aucun
ancien None ni ancien gate de preuve ne devient un défaut d’exécution.

## Historique du plan non raccordé

Tranche `HOBEN-126-HA-PLAN-005`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6435985641),
base `d0b0719d1efc9a26195e767d856704e601334afd`.
L'[inventaire](manual-test-campaign-inventory.md), les
[shells inertes](manual-test-campaign-shells.md), le
[contrat d'admission](manual-test-campaign-admission-contract.md) et le
[plan protocolaire](protocol-campaign-plan.md) restent inchangés.

[ha_campaign_plan.py](../scripts/ha_campaign_plan.py) décrit des données figées,
sans importer le client/coordinator, un gate ou un collecteur. Aucune lecture
d'environnement/secret, horloge, connexion, tâche, pipe, ACK, commande ou rapport.
Les références sont des chemins à étudier, pas des callables ou commandes.
Tous les plans, étapes et transitions restent **NOT RUN / can_start=false /
actions_result=FAILURE**, avec conversion booléenne false. L'exécution directe
du fichier se termine avec code 1 sans sortie ; aucune CLI n'est proposée.

## Huit choix fermés, sans nouveau scénario raccordé

| Choix | État dans ce plan | Réutilisation à étudier |
| --- | --- | --- |
| hoben-live | historical_reference ; résultats historiques SUCCESS/FAILURE/NOT RUN. | Ancien lanceur HA, superviseur/gardien C2a, vrai worker/observer, HobenClient persistant, coordinator et gestionnaire V4 partagé. |
| open-errors | not_implemented / NOT RUN. | Erreurs du client/coordinator et cas config-flow/reauth/runtime, sans association. |
| refresh-v4 | not_implemented / NOT RUN. | Vraies données client, décodeur V4 et coordination, sans exposer de valeurs domestiques. |
| session-reuse | not_implemented / NOT RUN. | Session/génération persistante et tests du vrai client/coordinator. |
| session-reconnect | not_implemented / NOT RUN. | Perte naturelle et récupération future via gestionnaire partagé ; ancien NoPong exclu. |
| cleanup | not_implemented / NOT RUN. | Fermeture du client, unload et superviseur, avec tests de nettoyage existants. |
| availability | not_implemented / NOT RUN. | Coordinator, disponibilité, erreurs et tests runtime/entités/diagnostics. |
| all | Sept étapes dans l'ordre du tableau, chaque étape dépend de la précédente. | Aucun budget agrégé connu ; arrêt avant le premier complément non implémenté. |

La référence hoben-live provient de #112 dans **hoben-manual.yml**, avec vrai
HomeAssistant/ConfigEntry, HobenClient persistant et HobenDataUpdateCoordinator.
Elle n'est pas un nouveau raccordement au shell hoben-ha-manual.yml. Le plan ne
réimplémente ni ne lance ce scénario ; les six autres scénarios dédiés ne sont
pas réputés livrés parce que certains composants/cas de tests existent déjà.
Les chemins précis de réutilisation sont dans le module et leur existence est
testée. Le vieux contrat one-shot ne remplace pas cette référence persistante.

## Budgets réellement connus, sans valeur par défaut pour les compléments

Pour la seule référence historique hoben-live : **300 s utiles monotones**,
**360 s absolues démarrage/cleanup compris**, collecte 330 s, mémoire agrégée
**1 Gio**, **128 PID/threads**, six refreshs, deux ouvertures au maximum sur la
durée de vie du client, rapport fermé de 8192 octets au plus. Les six refreshs
ne suffisent pas seuls : la fenêtre et le témoin final doivent couvrir 300 s.
Le superviseur et son confinement réel existants ne sont pas modifiés.

Ces valeurs sont des références documentaires vérifiées par lecture AST des
constantes et de la signature du client, sans import HA. Aucune limite n'est
armée, mesurée ou appliquée par le plan. **Aucun quota/compteur/proxy RX HA**
n'est ajouté ou emprunté à la campagne protocolaire.
Les plafonds des six compléments et du all sont **None/inconnus**, sans zéro,
illimité, multiplication par sept ni copie du budget historique d'un autre
scénario. Ils nécessitent un arbitrage distinct avant toute implémentation.

## Préfixes, preuves et résultats

`build_plan(selection)` accepte exactement les huit choix du YAML HA ; valeur
inconnue, choix protocolaire ou mauvais type donne un plan vide NOT RUN, sans
reprise de l'entrée dans les diagnostics. `assess_transition(selection,
evidence)` vérifie seulement la cohérence de reçus **synthétiques**.

L'enveloppe fermée contient selection, admission_attested, next_step,
next_deadline_armed, next_ack, next_limits_attested, next_cleanup_attested et
completed. Les reçus doivent être le préfixe exact du plan, sans trou, doublon,
autre sélection ou étape supplémentaire. Chaque reçu contient step, outcome,
loss_kind, reconnection_status et les indicateurs attested/deadline_armed/ack/
limits_respected/process_ok/cleanup_ok/report_valid/collection_complete/
continuous_300s. Les indicateurs requis doivent être exactement true, jamais
un entier, texte ou valeur inconnue. Clé manquante/null inattendu/extra : refus.

Pour constater un préfixe hoben-live cohérent, son rapport doit être déclaré
validé et son résultat **SUCCESS**, avec continuité/limites/processus/cleanup
attestés. FAILURE/INCONCLUSIVE/NOT RUN ou résultat inconnu ne débloquent rien.
Sans perte, le critère de reconnexion reste **INCONCLUSIVE** : ce n'est pas une
reconnexion observée. Une réussite de continuité peut donc coexister avec ce
critère INCONCLUSIVE ; le résultat global historique n'est pas lui-même ainsi
requalifié. Le plan ne remplace pas les validateurs du rapport schéma 3.

Les catégories de perte restent distinctes : none, local_stop, close_client,
eof, transport_error et unknown. Un arrêt local n'est pas une perte naturelle,
CloseClient n'est pas un EOF TLS, une erreur transport ne prouve pas sa cause,
unknown signifie preuve insuffisante. Toute perte dans cette fenêtre empêche
de déclarer sa continuité. loss_kind porte sur la fenêtre utile ; la fermeture
normale du finally après son témoin final n'est ni une perte dans cette fenêtre
ni une reconnexion. Une future reconnexion naturelle devra prouver la
perte admissible, une nouvelle génération et une lecture corrélée récupérée ;
ce scénario dédié et ses bornes ne sont pas implémentés ici. Les chemins
session_suite.py / v4_no_pong.py sont explicitement exclus de cette cible :
l'inhibition artificielle des Pong ne devient pas une perte naturelle.

Avant la phase suivante, admission, limite/cleanup prévus, délai armé avant
ACK et ACK doivent être attestés. Après un préfixe individuel complet,
next_step est null et tous les indicateurs de prochaine phase sont false.
Même des attestations fournies comme satisfaisantes ne peuvent débloquer
open-errors ou un autre complément not_implemented. Le scénario cleanup futur
ne remplace jamais le finally/cleanup obligatoire de **chaque** scénario,
y compris après échec ; ces opérations existantes restent inchangées.

## Intégration et arbitrages différés

Les indicateurs ne sont pas authentifiés par ce module. Un futur adaptateur
devra relier admission/receipts/limites et rapports aux sources vérifiées ;
consistent=true du modèle d'admission offline ne constitue pas un permis.
Un succès de job Actions n'est pas un succès HA, un rapport absent ne prouve
pas une absence de connexion et un jeu de fixtures n'est aucune preuve live.
Les [tests](../tests/test_ha_campaign_plan.py) vérifient les plans, refus et
références, sans instancier HA ou exécuter un collecteur.

Workflows/shells, gates/claims/environnements, runtime, protocole et budgets
restent inchangés. Toute future implémentation/raccordement, budget, admission
et procédure UI/main exige une autre tâche/revue. Aucune UI ni admission main
attestée ici ; aucun dispatch, rerun, test réel, PR main ou fusion DEV.
Lecture seule et TLS certificat/hostname myhoben.fr:465 conservés ; aucune
association/commande/écriture Modbus 06/16/22, donnée privée/GUID/RX brut publié,
ni hypothèse universelle OpenedClient=48. Livraison de ce plan puis STOP.
