# #163/C1 — preuve hors ligne, troisième reprise bloquée

Tâche : [HOBEN-163-C1-THREE-ERROR-CYCLES-OFFLINE-006](https://github.com/Guillaume0385/ha-hoben-community/issues/163#issuecomment-6556352275).
Code de production testé, inchangé : `3ba541a5689769a094adb03876709d42aa347cc3`.
Cette branche est une **preuve non livrée**, pas une correction ni une PR validée.

## Résultat effectivement observé

Un seul vrai HobenClient, coordinator, lifecycle partagé et capteur A2 parcourent
les trois injections successives. Seuls les transports et le temps sont
synthétiques. Aucun client n'est recréé pour contourner la troisième erreur.
Le backoff emploie le vrai `asyncio.sleep`, avec horloge figée avancée par le test.
Les polls automatiques sont désinscrits dans le banc pour isoler les acquisitions
explicitement vérifiées ; ce n'est pas une modification du client distribué.

| Cycle injecté | Cleanup | Reprise et lecture corrélée | A2 / classification |
| --- | --- | --- | --- |
| 1 — erreur TLS read synthétique | Génération 1 fermée une fois | Aucune ouverture à 59 s ; génération 2 après 60,001 s virtuelles, puis nouvelle lecture V4 valide | reconnecting → connected ; transport_unavailable / tls_read ; reconnect_count=1 |
| 2 — EOF synthétique | Génération 2 fermée une fois | Même temporisation ; génération 3 et nouvelle lecture corrélée | reconnecting → connected ; transport_unavailable / tls_read ; reconnect_count=2 |
| 3 — exception Python synthétique dans feed RX | Génération 3 nettoyée ; owner terminal et aucun RX restant | **Aucune génération 4**, aucun troisième backoff, aucune nouvelle lecture après 120 s virtuelles et un poll supplémentaire | disconnected ; internal_failure / frame_boundary ; reconnect_count=2 |

Dans chaque phase, le snapshot mémorisé et sa date de succès restent inchangés
jusqu'à un nouveau décodage réellement corrélé. L'ouverture seule n'avance pas
la fraîcheur. Une vraie perte retire la disponibilité des mesures, conformément
au contrat A1 existant ; la conservation du cache n'est pas présentée comme une
disponibilité continue. recovery_count reste 0 : ces pertes transport et l'erreur
permanente ne sont pas des épisodes DataUpdated.

Un seul lifecycle demeure propriétaire. Aucun ancien RX/transport ne survit à
son cycle ; un seul transport est actif après chaque reprise. L'unload final
termine les propriétaires, sans tâche DataUpdated orpheline. Les envois du banc
sont limités à ouverture, Pong et lecture V4 fonction 04.

B3 produit les ordinaux 1/2/3. Pour l'exception injectée avant attribution d'un
message, type/tailles restent inconnus ; catégorie `unexpected_error`, phase
`frame_boundary`. Aucun chunk ou ancien message ne fournit une taille fictive.
Les tests vérifient la confidentialité des logs et l'absence de traceback dans
les événements B3. Aucun contenu de trame, registre ou exception libre publié.

## Test rouge conservé, caractérisation verte distincte

Utiliser l'environnement Python 3.14 du groupe `ha-test` du dépôt, exclusivement
avec les transports synthétiques des fixtures :

```sh
python -m pytest -q -c ha_tests/pytest.ini ha_tests/test_three_error_cycles_c1.py --tb=short --show-capture=no --timeout=20
```

Résultat : **1 failed, 1 passed**. L'acceptation
`test_c1_requires_three_correlated_recoveries` reste volontairement rouge :
résultat observé `[True, True, False]`, critère C1 `[True, True, True]`.
Le cleanup est effectué avant cette assertion. Aucun xfail/skip ne masque cet
échec. Le second test constate la politique existante ; sa réussite ne valide
pas le critère des trois récupérations.

Validation de cette preuve : **suite HA : 1 failed, 542 passed**, le seul échec
étant l'acceptation C1 ci-dessus (541 régressions intégrées et une caractérisation
verte). **839 tests unitaires ciblés PASS** : framing/fragmentation/concaténation,
session/lifecycle, DataUpdated, CloseClient/TLS/annulation, phases B1, collecteur
expérimental et validation de la preuve #126. Ruff check/format PASS.

## Chemin exact et arbitrage manquant

- `v4_session.py::_receive_experimental` annote l'appel `feed` avec
  `error_boundary("frame_boundary")`. L'injection locale est uniquement un
  déclencheur de test ; elle ne reproduit pas la cause historique sur HA.
- `V4Session._receive_unproven_handoff`, `except Exception`, transforme ce cas
  en `HobenInternalError` en conservant la phase prouvée ; le transport est fermé.
- `v4_lifecycle.py::V4Lifecycle._run` autorise le retry pour les **types exacts**
  récupérables ; même avec recover_acquisition, seuls HobenProtocolError et
  HobenTimeoutError exacts sont ajoutés. HobenInternalError est exclu. Après
  cleanup, `if not retryable: break` termine le propriétaire. Ce n'est pas un
  manque de temps ou une limite à deux ouvertures : le mode HA est bien activé.
- `coordinator.py::_async_update_once` conserve la sémantique permanente des
  sous-classes de HobenProtocolError, avec ConfigEntryError. A2 reste disconnected.

**Blocage C1 :** le troisième résultat demandé ne peut pas être attesté avec la
politique actuelle. La consigne impose : « Si les tests rouges démontrent que
la politique existante empêche la troisième reprise, ne pas convertir
silencieusement HobenInternalError en erreur transitoire ni augmenter les
retries. Fournir le test rouge minimal et le chemin exact, signaler un blocage
pour arbitrage MANAGER ». Aucun code de production/retry/codec n'est modifié.

MANAGER doit arbitrer si ce cycle doit constater un arrêt permanent sûr, ou
préparer une tâche distincte autorisant une reprise strictement définie avec
preuves de sûreté. Aucun retry générique, nouveau client ou quatrième ouverture
forcée n'est proposé. Pas de relais CODEX DEV vers #126/030 ; pas de reprise B2.

Les tests de non-régression et leurs résultats sont consignés dans le bilan
GitHub. Les quatre CI ne sont pas déclarées réussies sur cette preuve : aucune
PR livrée tant que l'acceptation C1 est rouge. Les CI de B3 ne sont pas attribuées
à ce nouveau commit. **Tests réels NOT RUN**, aucune action HA, commande poêle,
connexion serveur, dispatch/rerun, changement main ou automation.
CHANGELOG non modifié : aucune fonctionnalité/correction livrée, preuve bloquante
uniquement. Aucune PR de livraison n'est proposée tant que l'acceptation reste
rouge et que l'arbitrage demandé n'a pas été donné.
