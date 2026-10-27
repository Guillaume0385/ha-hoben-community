# Plan protocolaire offline — #126

Tranche `HOBEN-126-PROTOCOL-PLAN-004`, selon la
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6435985641),
base `e6e1943996f32939ad2dce3d8d4594bf9f170a1c`.
L'[inventaire](manual-test-campaign-inventory.md), les
[shells inertes](manual-test-campaign-shells.md) et le
[contrat d'admission offline](manual-test-campaign-admission-contract.md)
restent les références ; aucun de ces contrats ou points d'entrée n'est changé.

[protocol_campaign_plan.py](../scripts/protocol_campaign_plan.py) fournit
`build_plan(selection)` et `assess_transition(selection, evidence)` : données
figées et cohérence de reçus synthétiques uniquement. Aucun import de
collecteur, du client/coordinator, des gates ou du modèle d'admission ; aucune
connexion, lecture d'environnement/secret, horloge, tâche, pipe, ACK ou rapport
créé. Les chemins sont des citations, jamais des commandes/callables.
Chaque plan, étape et transition reste **NOT RUN / can_start=false**, avec
conversion booléenne false ; la transition conserve actions_result=FAILURE.
L'exécution directe du fichier se termine par code 1, sans CLI ni sortie.

## Sept choix fermés et état actuel

| Choix | Étapes/citations | État et résultats possibles dans ce modèle |
| --- | --- | --- |
| tls-only | probe_hoben_connection.py / transport.py. | review_required ; NOT RUN. Budget global historique inconnu (None). |
| session-open | Même probe, ancienne option --session / session.py. | review_required ; NOT RUN. Une ouverture historique, budget global inconnu. |
| read-v4-state | Même probe / v4_read.py. | review_required ; NOT RUN. Une ouverture/lecture, 20 registres fixes ; budget global inconnu. |
| h1h2 | run_manual_hoben.py → run_experimental_boundary.py, boundary_capture.py et boundary_analysis.py. | reference_only ; FAILURE/INCONCLUSIVE/NOT RUN. SUCCESS exclu : H1/H2 ne prouve aucune frontière universelle. |
| session-300 | run_manual_hoben.py → run_session_300.py, v4_experiment.py, v4_lifecycle.py et v4_session.py. | reference_only ; SUCCESS/FAILURE/INCONCLUSIVE/NOT RUN selon le futur rapport validé, jamais depuis le seul résultat Actions. |
| session-reconnect | **Aucune implémentation de la cible naturelle référencée.** | not_implemented ; NOT RUN seulement. Aucun reçu ne peut la déclarer terminée. |
| all | **h1h2 → session-300 → session-reconnect bloquée**. Chaque étape dépend de la précédente. | Ordre historique conservé, sans HA. Le plan ne peut pas terminer tant que la cible naturelle reste non implémentée. |

Les trois anciens CLIs ne sont pas raccordés et ne sont pas réputés prêts :
leurs entrées d'identité, refus d'association, protections, critères et budget
global devront être revus séparément. None n'est ni zéro, ni illimité, ni une
valeur par défaut exécutable. Ils restent des choix individuels, hors de all,
conformément à son ordre historique validé ; les y ajouter sans budget connu
augmenterait son périmètre sans preuve et demande un autre arbitrage.

Le module conserve dans excluded_references les chemins historiques
[session_suite.py](../scripts/session_suite.py),
[v4_no_pong.py](../custom_components/hoben/v4_no_pong.py) et
[session_natural_900.py](../scripts/session_natural_900.py).
Le premier parcours utilise **NoPongAfter120**, une inhibition artificielle :
il n'est pas présenté comme perte naturelle et n'est pas une implémentation
réutilisable telle quelle dans cette cible. La fondation 900 s ne constitue
pas davantage une autorisation, une durée retenue ou une voie active.

## Plafonds historiques, sans augmentation ni autorisation nouvelle

| Référence | Valeurs immuables conservées |
| --- | --- |
| H1/H2 | 6 H1 + 6 H2, 90 s et 1 Mio RX **par session**, parent 1800 s. |
| Session 300 | 300 s utiles, parent 360 s, trois ouvertures, six lectures espacées d'au moins 60 s, 1 Mio RX total. |
| Ancienne reconnexion artificielle exclue | Parent 600 s, fonctionnel 360 s, trois ouvertures, dix lectures, 1 Mio RX total, stabilité 120 s. |
| Ancien all | Parent total 2820 s ; sous-suite des deux sessions 1020 s. |

Ces valeurs sont **historical_limits**, des références aux contrats existants,
pas des budgets nouveaux appliqués à la reconnexion naturelle. Aucun délai
n'est armé/prolongé et aucune limite n'est mesurée ou imposée par ce module.
Le futur scénario naturel et ses critères/bornes restent à définir sans
augmenter les plafonds historiques sans décision explicite. Aucun quota ou
comportement HA n'est touché. Les chemins et plafonds exacts sont testés contre
les constantes historiques pertinentes, sans importer ou lancer les collecteurs.

## Préfixe de résultats et barrières de transition

La preuve normalisée fermée contient selection, admission_attested,
next_step, next_deadline_armed, next_ack et completed. Les reçus de completed
doivent former le **préfixe exact**, sans trou, doublon, autre sélection ou
étape ajoutée. Chaque reçu contient step, attested, deadline_armed, ack,
process_ok, cleanup_ok, report_valid, collection_complete, limits_respected
et outcome. Tous les indicateurs exigés doivent être exactement true.
Champs inconnus, manquants, types approximatifs ou preuves absentes refusés.

Pour all, seule une collecte H1/H2 complète, bornée, nettoyée et validée avec
outcome=INCONCLUSIVE permet de constater la cohérence du préfixe avant
session-300. Une interruption INCONCLUSIVE, un processus échoué ou un reçu
incomplet ne suffit pas. Ensuite, session-300 doit avoir outcome=SUCCESS ;
FAILURE/INCONCLUSIVE/NOT RUN ou un résultat inconnu bloque la suite.
H1/H2 étiqueté SUCCESS est refusé. La dernière cible reste not_implemented
même si toutes les autres conditions sont déclarées satisfaites.

Avant toute étape suivante, l'admission, le délai armé **avant ACK** et l'ACK
de cette phase doivent être attestés ; next_step doit correspondre exactement
à l'étape attendue. Après un préfixe individuel complet, next_step est null et
les indicateurs de prochaine phase doivent être false ; aucun ACK fantôme.
Un résultat de cohérence du module ne constitue jamais ce signal ni un permis.

Les indicateurs fournis par les tests ne sont pas authentifiés ici. Un futur
adaptateur devra relier les reçus aux vraies preuves de provenance/admission,
au parent borné et aux rapports validés, après approbations et recheck, sans
transformer consistent=true du modèle d'admission en autorisation réelle.
Les [tests](../tests/test_protocol_campaign_plan.py) vérifient les plans figés,
les choix, plafonds, statuts, refus/ACK et l'absence d'appelant live ; ils ne
prouvent ni une exécution, ni des données serveur, ni l'UI GitHub.

## Intégration différée

Les deux shells et hoben-manual.yml restent inchangés, ainsi que gates,
claims, environnements, budgets, codecs et sessions. Aucun callable de collecte
n'est exposé et aucune sonde HA n'appartient au plan. Une future intégration
nécessitera une autre tâche/revue, des critères validés pour les anciens CLIs
et la reconnexion naturelle, les preuves d'admission/UI/main et les limites
effectivement appliquées. Aucun dispatch de vérification, contournement API/CLI,
checkout substitué ou PR main n'est réalisé ici.

Lecture seule, TLS certificat/hostname vérifiés vers myhoben.fr:465 et refus
de toute commande/association/écriture Modbus 06/16/22 restent inchangés.
Aucun GUID, secret, RX brut, registre domestique ou exception libre publié.
CloseClient, EOF TLS et arrêt local restent distincts ; 48 octets ne prouvent
pas une longueur universelle d'OpenedClient. Livraison de ce plan puis STOP,
sans engager le raccordement ni un test réel ; MANAGER seul revoit et fusionne.
