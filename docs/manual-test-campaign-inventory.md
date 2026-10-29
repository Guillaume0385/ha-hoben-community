# Inventaire des campagnes manuelles MyHOBEN et Home Assistant

**Archive du 27/10 :** les exclusions d’inhibition Pong et anciens plafonds
ci-dessous ont été remplacés pour la tâche expérimentale 027 par la décision
propriétaire du 29/10. Consulter le [contrat courant et sa table de
correspondance](manual-test-campaign-runtime.md#correspondance-des-collecteurs-et-preuve) :
reconnexion expérimentale 600 s, all 3000 s ; HA reste séparée.

Audit documentaire du **27 octobre 2026**, tâche `HOBEN-126-AUDIT-001`, selon
la [consigne MANAGER active de #126][consigne]. Ce document prépare une séparation ;
il ne change aucune exécution, admission ou autorisation de test réel.
Les restrictions de lancement de l'ancien corps de #126 sont historiques :
la consigne active autorise uniquement cet inventaire après validation de #112.

## Sources et état vérifié

| Référence GitHub consultée | État constaté |
| --- | --- |
| [experimental au SHA audité][exp] | `da80bff53dc4bf6ece5ec2d3229b794239d0d579`, base de cet inventaire. |
| [main au SHA audité][main] | `a62b73529a38cd9a663ecee75ee5d911ad381f78`. |
| Arbre Git des deux HEAD | Identique : `ae42173e8b15942d60a9ef30d162a7ffa98a7e50`. Tous les chemins actuels inventoriés ci-dessous existent donc sur **les deux branches**, sauf ceux explicitement indiqués comme disparus/proposés. |
| [PR #121][pr121] | Fusion experimental `3969c02375603d94f331ca5f721dd476ce3408ae` : voie manuelle et retrait des anciennes définitions Actions vers les fixtures. |
| [PR #124][pr124] | Fusion experimental `35e8bf96a6c9223706a0741344f7add7aed222ce` : véritable client HA raccordé au lifecycle persistant partagé. |
| [PR #128][pr128] | Fusion experimental `f19376ccb9c7fae18a0ebc97e56dc63500302553` : choix manuel hoben-live, vrai coordinator et superviseur C2a. |
| [PR #131][pr131] | Fusion experimental `762f217710ba4e062cba09c4e101412e94393cb3` : refus d'entrée explicite, diagnostic fermé, distinction collecte/session. |
| [PR #132][pr132] | Fusion vers main confirmée par l'API, au SHA main ci-dessus. Sa description de préparation contient encore « draft / NE PAS FUSIONNER » : cet ancien texte ne remplace pas l'état merged actuel. |
| [Issue #112][issue112] | Clôturée ; prérequis déclaré validé par MANAGER dans [la consigne #126][consigne]. |
| [Run expérimental #40411630619][run-exp] | workflow_dispatch, experimental au SHA audité, tentative 1, SUCCESS ; sélection **all** vérifiée dans le contexte du job collect ; preflight/collect/publish/result SUCCESS, jobs HA skipped. |
| [Run HA #40411664834][run-ha] | workflow_dispatch, même SHA/ref, tentative 1, SUCCESS ; preflight/collect-ha/publish-ha/result-ha SUCCESS, jobs expérimentaux skipped. |

Les liens de code relatifs décrivent cet instantané. Les runs existants ont été
consultés en lecture seule ; aucun dispatch, rerun, claim, artefact privé ou
nouveau test réel n'a été exécuté pour cet audit. Un job de résultat vert reste
à interpréter avec son contrat scientifique, notamment pour H1/H2.

Règles consultées sur experimental : [AGENTS.md](../AGENTS.md),
[project.md](../project.md), [protocol.md](../protocol.md),
[workflow expérimental](experimental-protocol-workflow.md) et
[workflow MANAGER/DEV](manager-dev-workflow.md).
Leurs paragraphes historiques « one-shot », « main sans runtime » ou
« C2 pas encore autorisée » doivent être rapprochés du code et de la consigne
actuels ; ils ne réactivent aucune ancienne voie.

## Points d'entrée réellement installés sur main et experimental

| Chemin actuel | Rôle vérifié | Décision proposée |
| --- | --- | --- |
| [.github/workflows/hoben-manual.yml][manuel] | **Unique workflow de collecte** : workflow_dispatch seulement ; options h1h2/session-300/session-reconnect/all/hoben-live. Deux familles de jobs, environnements hoben-experimental et hoben-live. all exclut hoben-live. | **ADAPTER** en deux workflows indépendants, après attribution distincte ; conserver les collecteurs pertinents et les contrôles. |
| [.github/workflows/validate.yml](../.github/workflows/validate.yml) | Quatre checks offline tests/ha-tests/hacs/hassfest. Ses événements push/PR/schedule ne lancent aucune collecte Hoben. | **CONSERVER**, hors des deux campagnes live. |
| [.github/workflows/publish-release.yml](../.github/workflows/publish-release.yml) | Publication manuelle de releases, sans collecte Hoben ni environnement hoben-live. | **CONSERVER**, hors du chantier. |

**main contient désormais le runtime**, mais sa collecte reste refusée :
le preflight de [hoben-manual.yml][manuel] retourne branch_not_activated hors
experimental ; [manual-hoben-gate.cjs][gate] impose aussi ce ref, le HEAD protégé
et une PR fusionnée vers experimental. [manual_hoben_context.py][contexte]
fige encore le workflow/ref experimental. Copier le fichier ou partager un arbre
Git ne suffit donc pas à autoriser une observation réelle sur main.

## Scénarios : code encore présent et décision de réutilisation

Catégories : **EXPÉRIMENTAL** = sonde/gestionnaire protocolaire, **HA** = client
de l'intégration, **OBSOLÈTE** = ancienne voie de lancement/ancien contrat à
écarter. Une décision « retirer » vise la future voie live, sans supprimer ici
le code ni ses fixtures de compatibilité. Les chemins valent sur les deux HEAD.

| Scénario demandé | Chemin exact actuel et raccordement | Catégorie | Décision et justification |
| --- | --- | --- | --- |
| tls-only | [scripts/probe_hoben_connection.py][probe], option --tls-only ; transport [transport.py](../custom_components/hoben/transport.py). Ancien fichier Actions live-validation.yml disparu, [fixture conservée][ancien-live]. Aucun appel depuis le workflow de collecte installé. | EXPÉRIMENTAL | **ADAPTER** : conserver la vérification TLS/fermeture, l'encadrer par l'admission et les bornes de la future campagne ; ce n'est ni une ouverture applicative ni une validation HA. |
| session-open | Même [probe][probe], option réelle **--session** (session-open était le nom d'input/job) ; [session.py](../custom_components/hoben/session.py), open_session_once. Ancien workflow disparu, [fixture][ancien-live]. | EXPÉRIMENTAL | **ADAPTER** : réutiliser ouverture/erreurs/cleanup figés ; le CLI historique part d'un DeviceGuid initial, sans envoi de code d'association. Définir les entrées autorisées et refuser tout besoin d'association avant raccordement futur ; ne pas réactiver aveuglément ce CLI. |
| read-v4-state | Même [probe][probe], option --read-v4-state ; [v4_read.py](../custom_components/hoben/v4_read.py), open_and_read_v4_once. Ancien workflow disparu, [fixture][ancien-live]. | EXPÉRIMENTAL | **ADAPTER** : lecture V4 fixe, fonction 04, 20 registres à partir de 1024 ; conserver corrélation et refus des ouvertures ambiguës, publier seulement des métriques autorisées. Le décodeur partagé ne constitue pas le chemin coordinator HA. |
| h1h2 | [manuel][manuel] → [launch_manual_hoben.py][parent-exp] → [run_manual_hoben.py][collect-exp], h1h2() → [run_experimental_boundary.py](../scripts/run_experimental_boundary.py), [boundary_capture.py](../scripts/boundary_capture.py), [boundary_analysis.py](../scripts/boundary_analysis.py). | EXPÉRIMENTAL | **CONSERVER** la substance et les plafonds. Une collecte complète reste scientifiquement INCONCLUSIVE, boundary_proven=false ; aucun succès ne prouve une longueur universelle d'OpenedClient. |
| session-300 | Même entrée/parent/collecteur manuel, sessions() → [run_session_300.py](../scripts/run_session_300.py), observe(), avec [V4Lifecycle](../custom_components/hoben/v4_lifecycle.py)/[V4Session](../custom_components/hoben/v4_session.py). Le vieux hoben-session-300.yml est uniquement une [fixture][ancienne-suite]. | EXPÉRIMENTAL | **CONSERVER** le scénario continu et ses refus/budgets. Il teste le gestionnaire partagé sans HobenDataUpdateCoordinator ; il ne remplace pas hoben-live. |
| session-reconnect | [collecteur manuel][collect-exp], sessions() → [session_suite.py](../scripts/session_suite.py), _observe_reconnect(), avec [v4_no_pong.py](../custom_components/hoben/v4_no_pong.py), NoPongAfter120. | EXPÉRIMENTAL | **ADAPTER**, pas reprendre comme « naturel » : le code inhibe les Pong après 120 s. #126 exclut l'inhibition artificielle pour sa cible. Une tâche/arbitrage séparé doit définir une observation naturelle bornée et son résultat sans perte ; aucun budget existant n'est modifié par cet inventaire. |
| all actuel | [manual_hoben_context.py][contexte], PLANS ; [collecteur manuel][collect-exp], [parent][parent-exp], [manual-hoben-report.cjs](../.github/scripts/manual-hoben-report.cjs). | EXPÉRIMENTAL | **ADAPTER** à deux plans distincts : actuellement h1h2 → session-300 → session-reconnect, jamais HA ; transitions armées/ACK, précondition de suite et statuts NOT RUN conservés. La future version ne doit pas embarquer silencieusement l'inhibition historique. |
| live-hoben-authenticated | Ancien status/job de manager-live-hoben.yml disparu ; [fixture][ancien-manager]. Substance encore présente dans [probe][probe], --live-premerge : vrai [HobenClient][client], deux refreshs et decode_v4_snapshot(), sans coordinator. Non raccordé à l'Actions installé. | HA | **ADAPTER** les cas pertinents d'identité/lecture/erreur/fermeture aux vrais tests HA. Retirer l'ancienne admission par label/commentaire/PR et l'ancien contrat « deux TLS one-shot » ; le client réel est persistant depuis #124, ces anciens commentaires ne décrivent plus son comportement. Ne pas dupliquer le premier test #112. |
| ha-parity | [launch_live_ha_parity.py](../scripts/launch_live_ha_parity.py) → [run_live_ha_parity.py](../scripts/run_live_ha_parity.py), observe() ; ancien hoben-live-experimental.yml disparu, [fixture][ancienne-ha]. Script conservé et testé, sans appel depuis la collecte actuelle ; son contexte exige encore push/ancien chemin. | HA | **ADAPTER** les régressions utiles, **retirer son ancien contrat live** : utilise le vrai client et le décodeur mais pas le coordinator ; schéma 1 fixe encore session_mode=one-shot et unsupported pour la persistance. Un import du client actuel ne rend pas ces métadonnées recevables comme preuve persistante. Ancien budget 150 s non transféré implicitement au scénario HA 300/360 s. |
| live-session-negative | Ancien job/label de [live-validation.yml en fixture][ancien-live] ; code conservé dans [probe][probe], --session-negative, _probe_negative(). Aucun raccordement Actions actuel. | EXPÉRIMENTAL | **CONSERVER les tests offline seulement** : ouverture avec identité synthétique non attribuée, sans lecture des entrées Hoben. Ce n'est pas un test d'authentification d'un compte réel ni un test coordinator. Ancien déclenchement par label à retirer de la cible live ; aucune nouvelle authentification/association active autorisée. |
| Premier scénario HA réel #112 : hoben-live | [manuel][manuel], collect-ha → [launch_ha_manual_live.py][parent-ha] → [ha_session_supervisor.py][superviseur]/[ha_session_guard.py](../scripts/ha_session_guard.py) → [ha_session_live_worker.py][worker] → [ha_session_observer.py][observateur] → vrai [coordinator][coordinator]/[client][client]/V4Lifecycle PERSISTENT. | HA | **CONSERVER**, migrer sans réimplémentation : vrai HomeAssistant/ConfigEntry/coordinator isolé, persistance d'identité, six refreshs, fenêtre monotone 300 s, cleanup. Ce n'est pas une installation domestique complète ni un test de toutes les entités/flows. Réutiliser ce socle pour les compléments. |

La reconnexion de hoben-live reste **INCONCLUSIVE sans perte naturelle** ; son
SUCCESS de continuité n'exige pas une perte. Le
[contrat schéma 3](../scripts/ha_manual_live_report.py) exige collection,
réutilisation TLS, continuous_300s, cleanup et supervision. Ni le silence, ni
un arrêt local, ni CloseClient ne prouvent un EOF TLS. Les tests de pertes
synthétiques ne sont pas une preuve de reconnexion réelle.

Autres éléments à ne pas réactiver : [session_natural_900.py](../scripts/session_natural_900.py)
et son [test](../tests/test_session_natural_900.py) sont une fondation historique
sans choix Actions actuel ; 900 s n'est pas un budget autorisé pour #126.
Le mode --live-v4-validation-values du [probe][probe] est un outil de recherche
privée, refusé dans Actions ; il n'appartient à aucun all ni rapport public.

## Anciennes définitions Actions : chemins disparus et fixtures encore utilisées

Tous les chemins de la première colonne sont **absents de .github/workflows/**
aux deux HEAD. Les [fixtures archivées](../tests/fixtures/retired_workflows/README.md)
restent des sources des régressions offline, pas des workflows installés.
Catégorie **OBSOLÈTE**, décision **RETIRER de la cible live** pour leurs anciennes
voies d'admission/déclenchement ; conserver les fixtures et tests pertinents.

| Ancien chemin disparu | Chemin existant de fixture | Substance/régressions à préserver |
| --- | --- | --- |
| .github/workflows/live-validation.yml | [tests/fixtures/retired_workflows/live-validation.yml][ancien-live] | [test_live_validation.py](../tests/test_live_validation.py), tests de probe TLS/ouverture/lecture/négatif ; aucun retour des labels live-validation/live-session-negative. |
| .github/workflows/manager-live-hoben.yml | [tests/fixtures/retired_workflows/manager-live-hoben.yml][ancien-manager] | [test_manager_live_workflow.py](../tests/test_manager_live_workflow.py), [test_probe_premerge.py](../tests/test_probe_premerge.py) ; ne pas réintroduire le status live-hoben-authenticated comme nouvelle admission. |
| .github/workflows/opened-client-boundary.yml | [tests/fixtures/retired_workflows/opened-client-boundary.yml](../tests/fixtures/retired_workflows/opened-client-boundary.yml) | [test_boundary_workflow.py](../tests/test_boundary_workflow.py), analyse/fragments ; pas de nouveau framing ou ancien dispatch main. |
| .github/workflows/hoben-experimental.yml | [tests/fixtures/retired_workflows/hoben-experimental.yml](../tests/fixtures/retired_workflows/hoben-experimental.yml) | [test_boundary_campaign_regressions.py](../tests/test_boundary_campaign_regressions.py), [experimental-lab-gate.cjs](../.github/scripts/experimental-lab-gate.cjs), rapports H1/H2. |
| .github/workflows/hoben-live-experimental.yml | [tests/fixtures/retired_workflows/hoben-live-experimental.yml][ancienne-ha] | [test_experimental_live_workflow.py](../tests/test_experimental_live_workflow.py), rapports ha-parity historiques. |
| .github/workflows/hoben-session-300.yml | [tests/fixtures/retired_workflows/hoben-session-300.yml][ancienne-suite] | [test_session_300_workflow.py](../tests/test_session_300_workflow.py), suite/reconnexion et leurs validateurs. |
| .github/workflows/experimental-manager-preflight.yml | [tests/fixtures/retired_workflows/experimental-manager-preflight.yml](../tests/fixtures/retired_workflows/experimental-manager-preflight.yml) | [tests/js/experimental-push-preflight.test.cjs](../tests/js/experimental-push-preflight.test.cjs) ; aucune restauration de la voie push ni de décision MANAGER par commentaire. |

**Ne pas supprimer en bloc les anciens gates/scripts** : le [gate manuel][gate]
réutilise réellement reviewedCI/environmentPolicy/noOtherObservation de
[experimental-lab-gate.cjs](../.github/scripts/experimental-lab-gate.cjs) et
environmentPolicy/actualApproval de
[experimental-live-gate.cjs](../.github/scripts/experimental-live-gate.cjs).
Leurs anciennes admissions par commentaires ne sont pas appelées par la voie
manuelle. Les preuves/claims historiques ne sont jamais un repli admissible.

## Budgets et tests à prendre comme références, sans les modifier

| Parcours actuel | Bornes installées | Régressions offline à conserver/réutiliser |
| --- | --- | --- |
| TLS/ouverture/lecture historique | Options fermées du probe ; futur raccordement et budget à arbitrer avant activation, sans inventer un plafond. | [test_probe.py](../tests/test_probe.py), [test_probe_v4.py](../tests/test_probe_v4.py), [test_probe_negative.py](../tests/test_probe_negative.py). |
| h1h2 | Au plus 6 H1 + 6 H2 ; 90 s et 1 Mio RX **par session**, parent 1800 s. | [test_experimental_boundary_capture.py](../tests/test_experimental_boundary_capture.py), [test_boundary_campaign_regressions.py](../tests/test_boundary_campaign_regressions.py). |
| session-300 | 300 s utiles, 360 s processus, 3 ouvertures, 6 lectures fixes, 1 Mio RX. | [test_session_300_probe.py](../tests/test_session_300_probe.py), [test_session_300_runtime.py](../tests/test_session_300_runtime.py). |
| session-reconnect historique | Maximum fonctionnel 360 s, parent 600 s, 3 ouvertures, 10 lectures, 1 Mio RX ; inhibition Pong actuelle à distinguer de la cible naturelle. | [test_session_no_pong.py](../tests/test_session_no_pong.py), [test_session_suite_minimal.py](../tests/test_session_suite_minimal.py), [test_session_reconnect_diagnostics.py](../tests/test_session_reconnect_diagnostics.py). |
| all expérimental actuel | Deux sessions plafonnées ensemble à 1020 s, parent total 2820 s avec H1/H2 ; aucune étape HA. | [test_manual_hoben_runtime.py](../tests/test_manual_hoben_runtime.py), [tests/js/manual-hoben.test.cjs](../tests/js/manual-hoben.test.cjs). |
| hoben-live | 300 s utiles monotones, 360 s absolues démarrage/cleanup inclus, 1 Gio/128 PID-threads, 6 refreshs, 2 ouvertures, **aucun quota RX hoben-live**. | [test_ha_manual_live.py](../tests/test_ha_manual_live.py), [test_ha_manual_live_diagnostics.py](../tests/test_ha_manual_live_diagnostics.py), [test_ha_session_sandbox.py](../tests/test_ha_session_sandbox.py), [ha_tests/test_ha_manual_live_worker.py](../ha_tests/test_ha_manual_live_worker.py), [ha_tests/test_ha_live_observer.py](../ha_tests/test_ha_live_observer.py). |

Le socle partagé est aussi couvert par
[test_v4_persistent.py](../tests/test_v4_persistent.py),
[test_session_close_client.py](../tests/test_session_close_client.py),
[test_session_ignored_rx.py](../tests/test_session_ignored_rx.py) et
[ha_tests/test_persistent_client.py](../ha_tests/test_persistent_client.py).
Les compléments HA doivent reprendre les cas de
[test_config_flow.py](../ha_tests/test_config_flow.py),
[test_reauth.py](../ha_tests/test_reauth.py),
[test_runtime.py](../ha_tests/test_runtime.py) et
[test_entities.py](../ha_tests/test_entities.py), sans transformer leurs fixtures
en nouvelles opérations live. Le périmètre association reste exclu.

## Cible des deux campagnes : exigences, pas installation actuelle

| Campagne cible | Entrée et périmètre | Réutilisation et contraintes |
| --- | --- | --- |
| **Tests expérimentaux MyHOBEN** | Workflow workflow_dispatch indépendant, scénario individuel ou all ; TLS/ouverture/lecture/framing/V4/Ping-Pong et future observation de perte naturelle. Environnement hoben-experimental. | Reprendre les collecteurs protocolaires, leur confidentialité et leurs plafonds. Adapter les scénarios historiques avant ajout ; aucune inhibition artificielle dans la cible #126, aucun ancien trigger push/label/PR/schedule. |
| **Vérification réelle Home Assistant** | Autre workflow workflow_dispatch, scénario individuel ou all propre à HA ; environnement hoben-live. | Reprendre intégralement le vrai client/coordinator et le superviseur #112. Compléter par petites tranches les erreurs d'ouverture, refresh/décodage, disponibilité, perte naturelle/récupération et cleanup, sans première association ni doublon du premier scénario. |

Pour **chacun**, le sélecteur natif **Use workflow from** doit proposer
experimental/main et exécuter le SHA du ref sélectionné, sans input de branche
de substitution, API/CLI de contournement ou checkout d'un autre ref. Le futur
input scenario/all ne constitue aucune autorisation de collecte sur main.
Les noms/chemins des deux nouveaux fichiers restent à fixer par la tâche de
séparation ; aucun nouveau workflow n'existe dans cet audit.

L'admission future doit rester fermée par défaut, **propre au workflow, à la
campagne, au ref et à l'environnement** : propriétaire/identités GitHub vérifiés,
SHA du workflow/run/HEAD protégé concordants, PR/arbre/revue et quatre CI au
HEAD candidat exact, politiques API et approbations effectives, anti-rejeu lié
aux preuves immuables. Après attente/préparation, recheck avant secrets. Conserver
le mutex commun hoben-read-only-observation entre les deux workflows et le
contrôle des anciennes observations ; une file par workflow ne suffirait pas.
Ne pas accepter simplement main en remplaçant une comparaison de ref : provenance
de sa promotion et route de revue main restent à concevoir/valider séparément.

Publication sur runner distinct sans secret, schémas fermés et validation
indépendante Python/Node ; rétention courte (7 jours au plus). Chaque scénario
doit exposer **SUCCESS / FAILURE / INCONCLUSIVE / NOT RUN** selon ses preuves.
Une interruption laisse les étapes suivantes NOT RUN ; un job échoué ne prouve
ni une observation INCONCLUSIVE ni l'absence de connexion. Un rapport absent ou
refusé ne devient pas un succès, et une collecte H1/H2 complète ne valide pas
le framing. Les formats C1/C2a offline ne deviennent jamais des preuves live.

Lecture seule absolue, TLS certificat/hostname vérifiés vers **myhoben.fr:465**,
aucune écriture Modbus 06/16/22, commande poêle ou association. Aucun secret,
GUID, RX brut, valeur domestique, stdout/stderr privé ou exception libre publié.
Préserver codecs/compatibilité, corrélation, EOF/CloseClient distincts et refus
des frontières ambiguës ; 48 octets ne prouvent pas une longueur universelle
d'OpenedClient. Les budgets actuels ne changent pas par décision documentaire.

### Preuves UI et limites encore à lever

Les runs cités attestent l'utilisation du formulaire existant sur experimental
pour all et hoben-live ; la consigne MANAGER confirme ce prérequis opérationnel.
Ils **n'attestent pas** les formulaires de deux futurs workflows, leurs inputs
selon chaque branche, ni une admission live sur main. Aucun écran UI ni Settings
effectifs n'a été inspecté pendant cet audit ; l'égalité des arbres ne comble pas
ces inconnues. Les politiques doivent toujours être relues lors de l'admission.

Avant activation de nouvelles voies, le propriétaire devra vérifier pour chacun
des deux fichiers : bouton Run workflow chargé depuis la branche par défaut,
présence des deux refs et des options exactes, workflow/ref/SHA effectivement
sélectionnés, refus main tant que non autorisée et approbations d'environnement
attendues. Si la définition sur experimental n'apparaît pas dans le formulaire
chargé depuis main, STOP et arbitrage propriétaire pour une publication séparée
sur main ; aucune PR main automatique, dispatch de diagnostic ou substitution.

## Ordre proposé des petites PR suivantes

1. **Cet audit** : un document seulement, chemins/liens et diff vérifiés, quatre
   CI offline au HEAD exact ; pas d'impact exécutable, donc pas de modification
   de CHANGELOG ni des fichiers de contrat existants.
2. **Contrat de séparation et admission** : fixer deux chemins/formulaires et
   deux plans fermés ; tester offline les refus ref/SHA/PR/CI/environnement,
   anti-rejeu, concurrence et rapports. Définir la procédure UI/main séparée ;
   garder toute nouvelle collecte inactive avant preuve et autorisation. Ne pas
   élargir le gate main ni réutiliser les anciens commentaires d'admission.
3. **Migration expérimentale par scénario** : transférer h1h2 et session-300 sans
   changement de budget ; raccorder TLS/ouverture/lecture après adaptation.
   Isoler l'arbitrage de reconnexion naturelle : l'inhibition historique ne
   devient pas le nouveau scénario par renommage ; le budget 900 s n'est pas
   adopté. Préserver les régressions et le comportement actuel jusqu'à décision.
4. **Migration HA du socle #112**, sans le réimplémenter, puis compléments
   séparés : erreurs d'ouverture/refresh et disponibilité ; décodage/coordination ;
   récupération après perte naturelle et cleanup. Reprendre les cas historiques
   utiles sur le vrai coordinator, sans contrat one-shot ni association active.
5. **Bascule des all et retrait de l'entrée combinée**, seulement après parité
   des scénarios retenus, quatre checks et preuve UI des deux nouvelles voies.
   Maintenir les fixtures offline et le mutex partagé ; ne supprimer aucun
   helper encore utilisé. Promotion/activation main et chaque futur test réel
   exigent leurs demandes et revues distinctes du propriétaire/MANAGER.

Ce découpage est une proposition : seule une prochaine consigne MANAGER peut
attribuer sa mise en œuvre. Livraison de cet audit puis STOP ; aucune suite
automatiquement anticipée, aucun test réel ni fusion par DEV.

[consigne]: https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6435985641
[issue112]: https://github.com/Guillaume0385/ha-hoben-community/issues/112
[exp]: https://github.com/Guillaume0385/ha-hoben-community/commit/da80bff53dc4bf6ece5ec2d3229b794239d0d579
[main]: https://github.com/Guillaume0385/ha-hoben-community/commit/a62b73529a38cd9a663ecee75ee5d911ad381f78
[pr121]: https://github.com/Guillaume0385/ha-hoben-community/pull/121
[pr124]: https://github.com/Guillaume0385/ha-hoben-community/pull/124
[pr128]: https://github.com/Guillaume0385/ha-hoben-community/pull/128
[pr131]: https://github.com/Guillaume0385/ha-hoben-community/pull/131
[pr132]: https://github.com/Guillaume0385/ha-hoben-community/pull/132
[run-exp]: https://github.com/Guillaume0385/ha-hoben-community/actions/runs/40411630619
[run-ha]: https://github.com/Guillaume0385/ha-hoben-community/actions/runs/40411664834
[manuel]: ../.github/workflows/hoben-manual.yml
[gate]: ../.github/scripts/manual-hoben-gate.cjs
[contexte]: ../scripts/manual_hoben_context.py
[probe]: ../scripts/probe_hoben_connection.py
[parent-exp]: ../scripts/launch_manual_hoben.py
[collect-exp]: ../scripts/run_manual_hoben.py
[ancien-live]: ../tests/fixtures/retired_workflows/live-validation.yml
[ancien-manager]: ../tests/fixtures/retired_workflows/manager-live-hoben.yml
[ancienne-ha]: ../tests/fixtures/retired_workflows/hoben-live-experimental.yml
[ancienne-suite]: ../tests/fixtures/retired_workflows/hoben-session-300.yml
[parent-ha]: ../scripts/launch_ha_manual_live.py
[superviseur]: ../scripts/ha_session_supervisor.py
[worker]: ../scripts/ha_session_live_worker.py
[observateur]: ../scripts/ha_session_observer.py
[client]: ../custom_components/hoben/client.py
[coordinator]: ../custom_components/hoben/coordinator.py
