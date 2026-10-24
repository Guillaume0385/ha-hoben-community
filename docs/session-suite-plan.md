# Suite « Tests expérimentaux session » — L6bis livré, correction L6ter candidate

## Parcours minimal courant — Issue #112

La [consigne NOPONG-MINIMAL-002](https://github.com/Guillaume0385/ha-hoben-community/issues/112#issuecomment-6327710447)
réutilise le collecteur et le gestionnaire partagés sans nouveau reçu ni schéma.
Depuis l'acceptation initiale, les Pong sont normaux avant 120 s, puis inhibés
sur cette seule génération. EOF effectivement observé et nouvelle ouverture
doivent précéder 240 s ; 120 s avec Pong et lecture corrélée sur la même nouvelle
génération sont nécessaires au succès. L'observation finit au plus à 360 s,
ou plus tôt si le plafond de processus existant l'impose. Aucun temps n'est
réinitialisé à la reprise. Ce chemin réduit remplace l'attente fonctionnelle
historique de 180 s après inhibition décrite plus bas.

Le rapport v2 et ses validateurs historiques restent inchangés. Type partiel,
réponse invalide, perte supplémentaire ou preuve manquante ne donnent aucun
succès ; aucun raccordement de quarantaine ou diagnostic v3 n'est ajouté.
Les plafonds externes 360/600/1020 s, les budgets de lectures et H1/H2 restent
inchangés. La [consigne ADMISSION-MINIMAL-003](https://github.com/Guillaume0385/ha-hoben-community/issues/112#issuecomment-6327710447)
autorise le retrait du seul arrêt inconditionnel `quarantine-installation` et de
son `needs` dans `dry-run`. Le parcours reste préflight sans secret → admission
avec décision MANAGER/PR/CI/SHA exacts et claim anti-rejeu → environnement → recheck
avant l'unique étape secrète. Approbation requise non attestée : PENDING APPROVAL
puis refus avant collecte ; preuve absente ou changée : NOT RUN. Ce retrait
n'active pas la quarantaine et ne constitue ni une décision de campagne ni une
preuve des Settings effectifs. MANAGER doit vérifier séparément l'admission
réelle et les approbations requises. Tests réels NOT RUN ; étape 7 non validée,
étape 8 suspendue. Les sections suivantes conservent les contrats et l'historique.

### Relances natives de la suite — SESSION-NATIVE-RERUN-004

La suite réutilise `experimental-native-rerun.cjs`, comme H1/H2, sans nouvelle
infrastructure. Tentative 1 : décision v1 et claim historique inchangés, contrat
fixe de suite toujours vérifié. Tentatives 2 à 50 : uniquement **Re-run all jobs**
du run d'origine, avec nouvelle décision MANAGER v2 unique et immuable, après
fusion et avant le début du dry-run courant. Marqueur exact
`<!-- hoben-session-suite-approval:v2 -->`, clés exactes `schema=2`,
`scenario=session-suite`, `candidate_sha`, `ci_run_id`, `pr_number`, `merge_sha`,
`run_id`, `run_attempt`. La v1 d'origine reste requise et lie les scénarios et
budgets fixes ; la v2 ne les paramètre pas.

Les mêmes contrôles H1/H2 vérifient les jobs de la tentative courante, le dry-run
précédent réussi et l'identité API `triggering_actor`. Re-run failed jobs, job
isolé ou preuve ambiguë : NOT RUN. Claim distinct
`hoben-session-suite-<merge_sha>-run<run_id>-attempt<N>`, conservé même après échec
ou annulation ; recheck complet et approbation indépendante fraîche si requise.
Le champ existant `run_attempt` est borné à 1–50 dans le contexte et les rapports
Python/Node ; artefact `session-suite-report-<SHA>-<run_id>-a<N>`, sans nouveau
schéma ni diagnostic. L'ancienne voie autonome session-300 reste sans rerun.

Le run historique **#40091399093 ne reçoit pas ces changements** : GitHub relance
normalement le workflow et le code de son commit d'origine. Les preuves de
relance ne remplacent pas la présence du nouveau code au SHA exécuté. Aucun run,
claim réel ni décision de campagne par DEV ; MANAGER seul décide après revue/CI.

La [consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6176992612)
demande une suite unique, sur le workflow push `experimental` existant :
`session-300`, puis `session-reconnect-no-pong`. L'étape 8 est suspendue.
La validation historique de la session continue reste acquise :
[run 38766830984](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/38766830984),
SHA `4ea1c802155b95014d50c6a4aab8250621959466`, résultat vérifié par MANAGER
`continuous_300s`, sans reconnexion. Elle ne valide pas le nouveau scénario ni
la suite, et ne prouve aucune frontière universelle OpenedClient.

## Fondation L1 isolée — réception NON INSTALLÉE / NON ACTIVÉE

K est fusionnée par la PR #98 au SHA
`2adb4d1c51a9341c41dc0d352bad0f222bb9db1e` ; la proposition reste non installée.
Le [bilan MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6207920402)
ne publie aucune décision live pour cette PR documentaire. Le run de push
#38849433135 a été refusé à l'admission avant secrets (deux scénarios NOT RUN),
sans nouvelle observation du poêle.

L1 est fusionnée par la PR #99 au SHA
`c220072d82ec9a34d178a3fa15406ea841ed527a`, après revue MANAGER et quatre checks
réussis (3058 tests offline, dont 152 cas de politique). Elle ajoute seulement
[EofQuarantinePolicy](../custom_components/hoben/v4_eof_quarantine.py),
machine d'état pure sans I/O, horloge réelle, tâche, transport ou credentials.
L4 autorise le seul import de politique par `V4Session` derrière une capacité
privée activée par les tests uniquement. L5 ajoute le seul import de timing par
V4Lifecycle, dont la capacité privée reste sans fournisseur consommateur/factory
actif ; le comportement par défaut reste identique. La [limite de cette fondation](session-eof-quarantine-proposal.md#fondation-l1-isolée-api-et-limites)
est distincte du futur gel TX, de l'attente TLS et de la récupération.

Les tests unitaires déterministes couvrent frontières/invalides/ordres/idempotence,
snapshots scalaires bornés, import limité à dataclasses/enum et absence de
références consommatrices (seuls ponts privés L4/L5 revus autorisés). Ils ne réalisent pas la
matrice complète d'intégration K et ne prouvent
aucune action réelle. Une intégration/exception de portée, les évolutions de
rapport/admission puis l'activation nécessitent des tâches MANAGER séparées,
avec verrou structurel avant usage. Suite non validée, étape 8 suspendue.

## Verrou L2 installé — quarantaine non raccordée

La PR #100 est fusionnée sur `experimental` au SHA
`ea08be522c73fcca742c4bacbeafa7df75e8b0c7`. Le [bilan MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6209326192)
vérifie le run #38859779145 tentative 1 : `quarantine-installation` failure attendu,
tous les jobs aval skipped, aucun accès Hoben. Ce job initial échoue
inconditionnellement : runner sans checkout/action,
environnement, secret ou permission (`permissions: {}`), timeout d'une minute,
script local écrivant exactement les deux lignes ci-dessous, puis `exit 1` :

```text
session-300: NOT RUN (quarantine_not_installed)
session-reconnect-no-pong: NOT RUN (quarantine_not_installed)
```

`dry-run` dépend de ce préalable, avec ses conditions exactes inchangées. Son
échec empêche préflight, admission/réservation, recheck et capture ; les conditions
de publication/statut ne peuvent produire une approbation absente. Aucun
commentaire/décision ancien ou nouveau ne peut contourner ce préalable. Nom,
push `experimental`, mutex non annulable, gates, permissions et budgets restent
inchangés. Les deux scénarios sont suspendus ensemble, sans voie autonome.

Le test local exécute ce script sans identité/réseau et vérifie code 1 et deux
NOT RUN exacts ; les tests structurels couvrent l'absence de condition/action/
environnement/secret/contournement et le graphe jusqu'au secret. Les régressions
de gate, provenance, publication, supervision et absence de raccordement L1
restent conservées. Ce test n'est ni un push réel ni une preuve d'installation.
La preuve post-fusion ci-dessus est distincte des tests locaux.

L2 ne raccorde pas la fondation et n'adopte pas l'exception de réception K.
Un futur pont RX/TX/lifecycle/rapport exige une nouvelle tâche MANAGER après
installation vérifiée du verrou. Son retrait sera une activation distincte,
après installation/revue complète de la quarantaine éventuelle et de ses
contrats ; aucune activation automatique, décision live/claim/rerun par DEV.
Anciens runs/claims consommés inchangés, suite non validée, étape 8 suspendue.

## Fondation temporelle L3 NON RACCORDÉE

Le [contrat proposé actualisé](session-eof-quarantine-proposal.md#contrat-temporel-l3-pur-sans-statut-de-réussite-réel)
fixe T0 à l'acceptation stricte de la première génération du second scénario :
Pong normaux avant 120 s, inhibition dès 120 s, futur diagnostic fermé dès 150 s,
EOF admissible ET réouverture avant 240 s, puis 120 s stables sur la même nouvelle
génération avec Pong/lecture corrélée. Maximum fonctionnel 360 s, fin précoce
permise après stabilité ; égalités aux deadlines et courses ambiguës refusées.
Un EOF seul avant 240 s ne suffit pas. Absence d'exercice/EOF, ouverture tardive,
seconde perte ou budget restant insuffisant : aucun recovered_120s.

L3 remplace dans la seule politique pure la borne T0+300 par T0+240 et ajoute
`RecoveryTiming` immuable et `check_recovery_timing()`, calcul sans statut réel
de succès. L3 fusionnée n'a ajouté aucun gel TX/attente TLS/retry ; L4 prépare
seulement le pont privé désactivé décrit ci-dessous, sans consommateur.
Les anciennes hypothèses proposées EOF T0+300/attente 180 sont remplacées par
**récupération totale 120 s, EOF et ouverture avant 240 s**. Les valeurs du moteur
et du contrat actif ci-dessous restent installées et inchangées sous verrou.
Le premier scénario garde 300 s ; ouverture initiale/nettoyage sont hors de la
fenêtre fonctionnelle du second mais sous les plafonds existants. Les deadlines
observation/process/suite ne sont jamais prolongées. Avant usage, un contrat
d'admission versionné devra lier ces constantes : aucune ancienne décision/claim
ou rapport ne valide L3.

Les observations renforcées proposées dès 150 s se limitent aux temps relatifs,
compteurs/tailles/offsets bornés, état/motif/catégorie fermés au rejet, origine ou
absence EOF. Clés/version/cohérence Python/Node à spécifier avant instrumentation.
Aucun RX/hex/base64 de trame, sous-code deviné, valeur domestique, GUID, exception
libre ou capture brute publique/privée autorisée. Verrou L2, runtime, gates,
rapports v1/v2, budgets et publication inchangés ; étape 8 suspendue.

## Pont L4 livré — non raccordé aux consommateurs

L3 est fusionnée par #101 (`11b2609ebd7a8f4abde46d8b0f94d8bc57ba0ce8`),
quatre checks réussis/3220 tests offline, [bilan MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6209782800).
Le run post-fusion #38862945022 s'arrête au verrou L2, tous les jobs aval skipped.
Le [pont de session proposé](session-eof-quarantine-proposal.md#pont-de-session-l4-livré-capacité-fermée-et-défaut-off)
est livré par #102, fusion `4ebee209926ad9d24f6cb3cf3fab4e6a37ebdb2b`,
[bilan MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6210627676),
quatre checks/3294 tests offline réussis, run #38868819504 arrêté au verrou L2.
Il reste désactivé chez les consommateurs : capacité interne
à usage unique, liée aux deux propriétaires exacts SessionReconnect/NoPongAfter120,
sans fournisseur actif ni flag env/input/commentaire. Première génération,
inhibition positive et rejet close_client admissible seulement. Latch synchrone,
contrôle TX sous verrou, TX engagée distincte des files ; waiter privé sans
close/replay, budget/session non utilisables sans notification terminale précoce.
RX unique continue passivement jusqu'à l'échéance L3 sans framer, capture ou
double comptage. Seul read EOF admissible donne un candidat privé révocable.
Sans capacité lifecycle L5, pas de retry/recovered_120s ; stop, course, délai, budget ou TLS sans
EOF restent refusés. Les tests TLS/horloge simulés couvrent ces effets et le
nettoyage, en conservant les tests L1/L3/verrou et les régressions par défaut.

Garde structurelle : seul import approuvé par V4Session, aucun constructeur/appel
consommateur ne fournit la capacité. Lifecycle, HobenClient/HA, collecteurs,
launchers/superviseurs, rapports v1/v2, validateurs/publication, contrats/gates,
workflows et tous les budgets restent inchangés. Aucun diagnostic 150 s branché.
Lifecycle/collecteur et contrats 150 s/rapports/admission versionnée formeront
une tranche MANAGER séparée, puis activation distincte revue. Aucun live/claim/
décision/rerun par DEV ; suite non validée, étape 8 suspendue.

## Lifecycle L5 livré, récupération privée bornée sans collecteur

Le [contrat L5](session-eof-quarantine-proposal.md#lifecycle-l5-livré-consommation-liée-à-lorigine-et-récupération-bornée)
ajoute une capacité fermée et à usage unique de V4Lifecycle, défaut-off,
fournie par les tests/factories de test seulement. Les propriétaires exacts
SessionReconnect/NoPongAfter120, T0 strict initial et les deadlines L3 restent
liés. Seuls session/lifecycle peuvent porter les références privées revues ;
aucun client/HA, collecteur, launcher ou workflow ne fournit la capacité.

L'événement local de quarantaine suspend immédiatement état/snapshot et
wait_connected ; requests échouent sans replay/close. Le waiter privé ne déclenche
pas le cleanup. À la décision RX, consommation synchrone unique d'une observation
EOF encore admissible liée à sa session/génération, avant nettoyage intentionnel.
Un snapshot copié/révoqué/périmé/doublé n'est pas un permis. L'origine reste
recontrôlée après cleanup et avant/après backoff/ouverture/acceptation ; arrêts,
annulations et courses gagnent fermement. Le cleanup possédé reste distinct d'un
stop public concurrent, qui révoque toujours. Toute fin du lifecycle scelle l'origine.

Session fraîche, identité autorisée/budgets/cadence partagés, aucune réémission ou
réponse tardive transférée. EOF ET acceptation avant T0+240, avec 120 s stables
encore possibles sous min(T0+360, observation, process, suite) ; aucun reset ou
prolongation. La session refuse la borne exacte avant adoption. Des timers privés
bornent toutes les phases, sans modifier les plafonds externes. Au plus trois
tentatives ; la première nouvelle acceptation ouvre la seule phase stable, dont
toute perte est terminale même immédiatement après acceptation. Pong/lectures
sur cette génération sont testés pendant 120 s synthétiques, sans rapport public.

L5 est fusionnée par #103 (`49d20ed62d2d1f15c09c4b8a873bf2b390fcebac`), livrée hors ligne, défaut-off, sans
fournisseur consommateur. Aucune validation globale/recovered_120s par cette
tranche : collecteur et contrats diagnostic 150 s/rapport/admission versionnée
restent séparés, puis activation/retrait du verrou après revue complète.
Framer/protocole/ouverture/identité/TLS/profils, clients/HA, collecteurs,
launchers/superviseurs, rapports v1/v2/validateurs/export, gates/contrats/workflows
et budgets 360/600/1020, 350+10/590+10, 3 ouvertures/1 Mio, 6/10 lectures >= 60 s inchangés.
Aucun diagnostic 150 s branché, brut, live/décision/claim/rerun. Deux NOT RUN avant
secrets conservés ; suite 7 non validée et étape 8 suspendue.

## Contrat public v3 — 7/8-L6 livré sans producteur

L5 est fusionnée par #103 au SHA `49d20ed62d2d1f15c09c4b8a873bf2b390fcebac`.
[Revue/bilan MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6213829821) :
Validate #38875547530, quatre checks, 3350 tests offline et 308 HA réussis ;
run post-fusion #38889510562 arrêté au verrou L2, sans collecte.
Le lifecycle et la session restent défaut-off, sans fournisseur consommateur.

L6 ajoute seulement projection et validation de rapports synthétiques. Le couple
**suite/schema3 + second/schema3** est explicite ; premier sous-rapport
`session-300/schema1` strictement inchangé. Les couples historiques 1/1 et 2/2,
leurs fixtures et toutes leurs règles sont conservés, y compris leur ancien
`eof_after_threshold_ms` relatif au seuil 120 s et leur limite historique 180 s.
Ce champ n'existe PAS en v3 ; aucun mélange, ajout implicite ni rétrocomplément.
Les producteurs `second_empty`, `_observe_reconnect` et `observe_suite` continuent
d'émettre v2. Aucun collecteur, runtime, constructeur, gate, admission, YAML ou
superviseur modifié. L6 est fusionnée par #104 au SHA
`6cc17b9d380835fdb77cb9b671707eb469c79b4d`, contrat livré **sans producteur v3**.
L6bis est fusionnée par #105 au SHA
`182daa62177c74bb14dc6412a166e95ad36c8350`. La correction contractuelle L6ter
ci-dessous est candidate jusqu'à revue/fusion, puis livrée. Le travail local L7
incomplet est préservé, non publié ; L7 reste suspendue jusqu'à fusion L6ter
et réautorisation MANAGER distincte.
Instrumentation 150 s/collecteur, admission versionnée puis
activation/retrait du verrou exigent de nouvelles tâches MANAGER distinctes.

### Clés héritées et nouvelles clés exactes

Les clés de suite restent exactement : `schema`, `scenario`, `boundary_proven`,
`result`, `duration_ms`, `session_300`, `session_reconnect_no_pong` et provenance
`merge_sha`, `candidate_sha`, `run_id`, `run_attempt`, `pr_number`.
Scénarios exacts `session-suite` et `session-reconnect-no-pong`,
`boundary_proven=false`, SHA hex minuscules de 40 caractères, tentative entière 1–50,
provenance identique au contexte attendu et aux deux sous-rapports. En v3,
run/PR sont des entiers positifs sûrs <= 2^53-1, jamais booléens/flottants.
La durée de suite reste bornée à 1020000 ms et au moins la somme des durées des
sous-scénarios. Le premier conserve ses propres bornes, clés et conditions.

Le second v3 reprend tous les compteurs bornés existants (durée processus
600000 ms ; 3 ouvertures/2 réouvertures ; 1 Mio RX/chunks/Ping/Pong/suppressions ;
10 lectures/réponses ; 3 EOF ; 1 EOF après inhibition ; stabilité <=120000 ms ;
génération <=3). Les relations compteurs restent exigées : réouvertures =
max(0,ouvertures-1), Pong+inhibitions <= Ping, succès+échecs = lectures,
lectures réussies <= réponses <= lectures, chunks <= octets, compteurs de
reprise inclus dans les totaux. Ces plafonds ne créent aucun droit d'émission.
Budgets de cadence/runtime 6/10 lectures >=60 s, 360/600/1020 s et
350+10/590+10 inchangés. Aucune clé libre, octet RX, sous-code, registre, valeur
domestique, exception, horloge murale, GUID, secret ni capture brute autorisée.

Le second conserve `read_slot`, `failure_phase`, `failure_category`,
`message_category`, mais v3 définit ces quatre champs comme le **premier rejet
causal**, distinct du terminal final et du nombre final de lectures. `read_slot`
est entier 0..`reads` : 0 si aucune lecture engagée lors du rejet, sinon rang
causal, jamais remplacé par le total après reprise. Les couples phase/message
fermés sont ceux de v2 : none/opening/scheduled_read/lifecycle_transition/
teardown/tls_read -> unclassified ; frame_boundary -> unclassified/ambiguous ;
message_classification -> unclassified/close_client/data_updated/other_known/
unknown ; request_correlation/response_validation -> data_response ; pong_tx ->
ping. Les catégories restent les terminaux fermés historiques ; phases de
parsing exigent protocol, tls_read exige transport/budget, pong_tx exige
transport/protocol, teardown exige closed final. Sans causalité, phase none,
catégorie verified ou first_not_admissible égale au terminal, read_slot=0.

| Nouvelle clé scalaire | Type, unité et borne | Null / cohérence |
| --- | --- | --- |
| `causal_ms` | Entier relatif T0 en ms, 0..360000, ou null. | Null si phase none ; avant première acceptation, phase opening et null obligatoire. Sinon <= fin fonctionnelle ; pour la quarantaine, `causal_ms <= quarantine.entered_ms` sous les bornes temporelles et preuves de provenance/EOF existantes, sans délai maximal supplémentaire inventé. |

Les quatre objets nouveaux suivants ont **exactement** les clés de la table
ci-dessous, tirée du [contrat fermé commun](../scripts/session_suite_v3_contract.json).
`I?` signifie entier 0..borne ou null (booléen/flottant/non fini refusé), unité ms
pour les temps, octet pour bytes/offset/size, compteur pour chunks/generation.
Les enums et booléens sont obligatoires et non null. Les règles de cohérence
sous la table font partie du contrat autant que les types/bornes.

| Objet.clé exact | Type / valeurs fermées | Borne |
| --- | --- | --- |
| `timing.t0_observed` | booléen | — |
| `timing.functional_end_ms` | I? | 360000 |
| `timing.observation_deadline_ms` | I? | 600000 |
| `timing.process_deadline_ms` | I? | 600000 |
| `timing.suite_deadline_ms` | I? | 1020000 |
| `timing.inhibition_ms` | I? | 360000 |
| `quarantine.outcome` | `not_entered`, `waiting`, `no_eof`, `expired`, `refused`, `revoked`, `consumed` | — |
| `quarantine.entered_ms` | I? | 360000 |
| `quarantine.eof_ms` | I? | 360000 |
| `quarantine.consumed_ms` | I? | 360000 |
| `quarantine.origin_generation` | I? | 1 |
| `quarantine.eof_origin` | `none`, `transport_read`, `local`, `ambiguous` | — |
| `quarantine.receipt` | `none`, `valid_at_consumption`, `invalid`, `revoked_before_consumption` | — |
| `quarantine.cleanup_ms` | I? | 360000 |
| `quarantine.stop` | `none`, `local_before_consumption`, `cancel_before_consumption`, `local_after_consumption`, `cancel_after_consumption` | — |
| `quarantine.stop_ms` | I? | 360000 |
| `quarantine.accepted_ms` | I? | 360000 |
| `quarantine.accepted_generation` | I? | 3 |
| `stability.start_ms` | I? | 360000 |
| `stability.end_ms` | I? | 360000 |
| `stability.generation` | I? | 3 |
| `stability.interrupted` | booléen | — |
| `stability.first_pong_ms` | I? | 360000 |
| `stability.first_read_ok_ms` | I? | 360000 |
| `rx_diagnostic.observed` | booléen | — |
| `rx_diagnostic.start_ms` | I? | 360000 |
| `rx_diagnostic.end_ms` | I? | 360000 |
| `rx_diagnostic.first_rx_ms` | I? | 360000 |
| `rx_diagnostic.last_rx_ms` | I? | 360000 |
| `rx_diagnostic.bytes` | I? | 1048576 |
| `rx_diagnostic.chunks` | I? | 1048576 |
| `rx_diagnostic.start_offset` | I? | 1048576 |
| `rx_diagnostic.end_offset` | I? | 1048576 |
| `rx_diagnostic.rejection_ms` | I? | 360000 |
| `rx_diagnostic.rejection_offset` | I? | 1048576 |
| `rx_diagnostic.rejection_size` | I? | 1048576 |
| `rx_diagnostic.framer` | `not_observed`, `empty`, `prefix`, `ambiguous`, `refused` | — |
| `rx_diagnostic.phase` | `none`, `frame_boundary`, `message_classification`, `request_correlation`, `response_validation` | — |
| `rx_diagnostic.category` | `none`, `protocol` | — |
| `rx_diagnostic.message` | `unclassified`, `ambiguous`, `close_client`, `data_updated`, `other_known`, `unknown`, `data_response` | — |
| `rx_diagnostic.eof_ms` | I? | 360000 |

### T0 et chronologie de récupération

`t0_observed=true` signifie première acceptation stricte de la génération 1 du
second scénario ; toutes les dates sont relatives à CE T0, sans reset à la
reconnexion. Sans T0, tous les nombres de timing restent null : un échec opening
conserve seulement durée processus/tentatives/RX d'ouverture, diagnostic opening
sans causal_ms et aucun effet post-ouverture. NOT RUN exige tous compteurs à0,
aucun T0 et aucun diagnostic/événement. `null` n'est jamais un zéro observé.
Après T0, fin fonctionnelle et les trois échéances sont présentes ; fin <=360000
et <= chaque échéance, durée processus >= fin fonctionnelle. Durée processus
inclut ouverture/nettoyage, contrairement à la fenêtre fonctionnelle ; ne pas
les additionner comme deux fenêtres de mesure.

Inhibition présente si et seulement si suppression effectivement comptée,
à >=120000 ms et <= fin. Entrée de quarantaine après inhibition, avant min(240000,
observation,process,suite), liée à génération1 et au rejet causal
message_classification/protocol/close_client au même temps. Ce seul discriminant
n'est ni message complet ni EOF. Sans entrée, tous champs temporels/génération
de quarantaine sont null et outcome=not_entered, origine/reçu/stop=none.

`eof_ms` peut décrire un événement refusé (origine local/ambiguous), jamais une
preuve consommable. Origine transport_read après entrée seulement ; compteur
`eofs_after_suppression` vaut1 pour un EOF transport de première génération après
inhibition, pas pour un événement local. Un EOF sans quarantaine reste comptable
mais non admissible pour récupération ; le compteur seul ne constitue pas une preuve.
Un EOF transport de quarantaine exige ce compteur à1. Les compteurs peer_eofs restent des EOF transport seulement.
`receipt=valid_at_consumption` et outcome=consumed équivalent à consumed_ms non
null ; entrée < EOF transport <= consommation < min(240000,échéances), origine génération1.
L'EOF consommable est strictement postérieur à l'entrée : le même timestamp
quantifié est ambigu et refusé par la politique L1/L3 et le pont L4. Les cas
entrée−1 et entrée ne peuvent fournir un reçu valide ni un succès ; entrée+1
reste admissible structurellement si toutes les autres preuves concordent.
Le futur projecteur DOIT recevoir du propriétaire d'origine un reçu figé valide
au moment exact de consommation ainsi que son premier arrêt public et le
cleanup possédé. Ce reçu n'est pas encore produit publiquement par L5 ; L6 ne
le fabrique pas depuis son snapshot final. Validation structurelle n'authentifie
ni ne démontre aucun effet réseau.

L'issue est waiting/no_eof uniquement sans EOF/reçu/stop ; waiting reste avant
la borne, expired exige fin à/après la borne ; invalid implique refused.
revoked équivaut au reçu revoked_before_consumption et exige un stop local/cancel
avant consommation. Ces issues n'ont jamais de consumed_ms. Le premier stop
public est séparé du cleanup possédé : aucun stop -> stop_ms null ; stop avant
consommation -> aucun reçu valide ; stop après consommation -> temps supérieur
ou égal à consumed_ms, uniquement pour l'histoire interrompue décrite ci-dessous.
cleanup_ms, s'il existe, est
entre consommation et fin. Un cleanup intentionnel ne révoque pas rétroactivement
le reçu, un arrêt public ne peut pas être caché derrière ce cleanup.

Nouvelle acceptation uniquement avec reçu consommé et cleanup terminé,
consommation < acceptation < min(240000,échéances). Génération 2..opens,
acceptation+120000 <= min(360000,échéances), aucune prolongation. Le premier arrêt
public post-consommation doit avoir un temps supérieur ou égal à l'acceptation
déjà attestée, uniquement pour cette histoire interrompue. Aucune acceptation
après un arrêt réel n'est autorisée. L'ancien seuil EOF180s de v1/v2 n'intervient
jamais ici.

### Correction L6bis livrée — reçu historique et arrêt quantifié

La [décision MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6176992612)
résout le [blocage L7](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6216427042)
sans nouvelle clé, enum ni version. Pour local_after_consumption et
cancel_after_consumption, le propriétaire doit attester un reçu valid_at_consumption
effectivement acquis avant son premier stop public ; outcome=consumed conserve
ce fait historique. consumed_ms <= stop_ms est alors admis, même si les deux
événements se quantifient à la même milliseconde. Une égalité de nombres seule
ne prouve jamais leur ordre d'exécution. Avant consommation, consumed_ms reste
null ; aucun reçu ne peut être inventé ou obtenu depuis le snapshot final révoqué.

Tout stop public pendant l'observation impose le résultat global du second
scénario interrupted. Sans acceptation, terminal=closed, stabilité non commencée
(dates/génération nulles, interrupted=false dans ce seul sous-objet). Après une
acceptation réellement attestée, terminal=stability_lost, stabilité interrompue
avec fin présente au plus au premier stop et durée exactement dérivée de cette
fenêtre. accepted_ms <= stop_ms peut alors représenter l'égalité quantifiée ;
accepted_ms > stop_ms reste interdit. Le reçu historique ne restitue aucune
capacité courante ni droit de reprise/réussite après stop. Même au temps de fin
fonctionnelle, aucun stop public ne peut accompagner recovered_120s/verified,
suite success, completed ou un statut final réussi.

entrée < EOF <= consommation, consommation < acceptation et les deadlines
strictes restent inchangées. Aucun déplacement de timestamp, attente +1 ms,
effacement d'arrêt, modification de politique ou généralisation d'admissibilité.
Les validateurs restent structurels ; le futur producteur doit obtenir la
preuve d'ordre auprès du propriétaire, ils ne l'authentifient pas. Les tests
relèvent les scalaires après le vrai retour de consommation, avant révocation,
puis ferment les vrais propriétaires sous TLS/horloge simulés, avec égalité et
contrôle séparé +1 ms, avant/après acceptation. Aucun hook runtime ajouté.
L6bis ne fournit pas L7 : producteur, instrumentation et raccordement restent
suspendus jusqu'à nouvelle autorisation. Verrou, v1/v2, producteurs v2 et budgets
inchangés ; aucune validation réelle ni nouvelle preuve de protocole.

### Correction L6ter candidate — livraison et décision distinctes

La [décision MANAGER L6ter](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6176992612)
résout le [blocage livraison/parsing](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6219012693)
sans nouvelle clé, enum ni version. Les règles d'agrégat ci-dessous séparent
les livraisons non vides des décisions de parsing/validation. Aucun timestamp
n'est déplacé et aucun compteur n'est gonflé pour les faire coïncider. Les seuls
changements exécutables concernent les deux validateurs ; aucun propriétaire,
producteur, collecteur, gate, workflow, budget ou politique de reprise ne change.
Les wrappers de TEST relèvent les vrais points de livraison/décision sous TLS et
horloge simulés. La reproduction 151000/151001, EOF admissible puis réouvertures
échouées reste inconclusive/reopen_failed ; completed et le vrai script result
restent en échec, même si collect/publication sont déclarés réussis.

Deux anciens cas négatifs communs deviennent structurellement acceptables :
`coherence_rx_diagnostic.rejection_offset_0` référence l'octet global 199 déjà
reçu avant start_offset=200 ; il ne crée aucun octet après150.
`cannot_fit_two_reads_in_zero_interval` ne permettait pas de déduire les temps
des requêtes de celui de la première validation : le rapport ne contient pas
ces temps individuels. Il demeure un rapport interrompu, jamais un succès.
La nouvelle borne de nombre de lectures utilise le début réel de la génération
et la durée de sa phase, pas un temps de dernière lecture inventé. Tous les
autres anciens cas et rapports positifs sont conservés. Une projection acceptée
reste structurelle : le futur propriétaire devra attester chaque événement,
la cadence réelle et les octets disponibles lors de la décision.

L6ter candidate puis livrée après revue/fusion MANAGER ne livre pas L7. Le
producteur local L7 n'est ni inclus ni revu ici. Réautorisation L7, admission
versionnée/routage fixe puis activation/retrait du verrou restent séparés.
Étape7 non validée, étape8 suspendue ; aucune preuve protocolaire/live nouvelle.

### Stabilité et décision de suite

Début stable = acceptation, génération stable = nouvelle génération du reçu,
recovery_generation identique. Sans nouvelle acceptation, stabilité entièrement
null, interrupted=false et compteurs de reprise/stable_ms nuls. Fin stable, si
présente, entre début et fin fonctionnelle ; stable_ms est exactement la différence,
jamais un cumul de fenêtres. Premier Pong et première lecture corrélée sur CETTE
génération sont présents exactement quand leur compteur de reprise est positif,
entre début et fin stable (ou fin fonctionnelle si fenêtre encore incomplète).
Le temps de lecture est celui de la réponse corrélée acceptée par RX. Le nombre
de lectures est borné par les créneaux de requêtes possibles depuis l'acceptation,
pas par des intervalles fictifs entre validations. Les totaux et le slot causal
doivent aussi tenir sous la cadence minimale des requêtes.
Ces contrôles nécessaires ne prouvent pas la cadence réelle des événements.
Un stop public pendant cette fenêtre impose interruption et fin stable au plus
à son temps. stability_lost exige une acceptation et interrupted=true.

recovered_120s équivaut à terminal=verified et exige TOUS les éléments :
inhibition exercée, quarantaine/EOF transport/reçu valide, cleanup possédé,
acceptation stricte avant240, génération neuve, fin stable=acceptation+120000,
Pong et lecture corrélée rétablis, aucune interruption/stop public, exactement un
EOF et opens=génération acceptée. Fin stable <= fin fonctionnelle, strictement
avant toutes échéances externes ; agrégat RX observé jusqu'à la fin. Une seconde
perte ou une égalité/tardiveté de deadline interdit ce résultat. La fin précoce
est permise ; aucun rapport synthétique n'atteste une réussite réelle.

Suite success exactement si premier résultat continuous_300s/reconnected ET
second recovered_120s validé ; sinon not_successful, jamais succès partiel.
Premier non admissible impose second not_run. Le statut final existant exige
encore collecte ET publication success ; skipped/cancelled/failure/absence
restent en échec. NOT RUN, absence de rapport et PENDING APPROVAL ne deviennent
jamais des preuves de stabilité.

### Agrégat RX fixe à partir de T0+150000 ms

`observed=true` atteste une fenêtre instrumentée commençant exactement à150000,
fin entre150000 et la fin fonctionnelle. Les quatre compteurs/offsets sont alors
présents : end_offset-start_offset=bytes, chunks<=bytes et <= totalchunks,
bytes=0 équivaut à chunks=0 ; end_offset<=totalRX. La fenêtre peut s'armer au
seuil exact sans recevoir d'octet : zéro explicite, first/last_rx null. Sans
instrumentation (dont arrêt avant150 ou NOT RUN), observed=false, TOUS les nombres
null et framer=not_observed, phase/category=none, message=unclassified. Un rapport
incomplet peut rester nonobservé après150 ; il ne peut pas être un succès v3.

Les offsets sont positions dans les livraisons RX comptées une seule fois,
ouverture incluse conformément au budget actuel. Chaque livraison est attribuée
par son temps de livraison, pas une segmentation physique devinée ; aucune
frontière de message n'est affirmée. Si bytes>0, first_rx<=last_rx dans la fenêtre.
Une lecture corrélée peut être validée après sa dernière livraison. Aucune borne
last_rx>=validation, ni dernière livraison extrapolée depuis un compteur de
lectures, n'est exigée. Les requêtes sont espacées d'au moins60s par le vrai
propriétaire ; leurs validations ne le sont pas nécessairement. Structurellement,
recovery_reads_ok <= floor((fin_stabilité-acceptation)/60000)+1 ; les temps de
validation restent dans la stabilité de la même génération. Si cette génération
est acceptée après150, une validation dans la fenêtre exige des octets nouveaux
et first_rx<=première_validation : aucun suffixe d'avant acceptation ne peut
être transféré. Si acceptation est antérieure150, une réponse déjà livrée avant
150 peut y être validée sans nouvelle livraison (sauf start_offset=0, qui
exclut tout octet antérieur). Les preuves de chaque échange restent à obtenir
du propriétaire. Un rejet causal de parsing dans la fenêtre doit
correspondre au premier rejet RX résumé, pas être effacé ou renommé.
Pas de liste de chunks, de chronologie libre ni d'entrées extensibles : un seul
agrégat de taille fixe. Sans nouvelle réception, le framer peut conserver son
état empty/prefix/ambiguous, sans faux rejet ajouté. Un état refused déjà acquis
avant150 peut aussi être fidèlement observé : rejection_* restent tous nulls,
phase/category/message de l'événement de fenêtre restent none/none/unclassified,
et le premier causal antérieur150 doit être une phase de parsing fermée de
catégorie protocol. Sans ce causal, refused sans événement reste interdit.

Le premier rejet pertinent dans la fenêtre est le seul résumé : temps réel de
décision dans [150000,end_ms], même après last_rx ou avant first_rx si les octets
concernés étaient déjà reçus avant150. Offset GLOBAL dans [0,end_offset[,
taille positive bornée par end_offset-offset ; framer=refused, category=protocol et couple
phase/message autorisé. Sans rejet dans la fenêtre, temps/offset/taille null,
phase/category=none, message=unclassified. Un rejet causal AVANT150 reste dans
les champs causaux ; il n'est jamais recopié comme rejet après150. Des livraisons
ultérieures après150 sont comptées sans réinterpréter le suffixe de quarantaine.
L'intervalle doit référencer des octets effectivement reçus avant la décision,
ce que le futur propriétaire atteste sans payload. Si l'intervalle dépasse
start_offset, first_rx doit exister et ne pas suivre la décision. Un intervalle
entièrement antérieur peut être rejeté avec bytes=chunks=0, first/last_rx=null,
start_offset=end_offset>0. Aucun octet référencé n'est alors recompté après150.
Sans octet disponible (end_offset=0), aucun rejet référencé n'est admissible.
`eof_ms` du diagnostic est un EOF transport dans la fenêtre, pas un compteur de
chunk ni des octets ; il exige peer_eofs>0. Si l'EOF d'origine appartient à cette
fenêtre, il doit y être concordant ; avec un seul EOF, aucun autre temps n'est
admis. Avant150 il reste seulement dans quarantine. Absence d'EOF instrumenté
est null, pas une preuve de fermeture serveur.

### Enveloppe et tests sans activation

Clés et enums fermés, nombre fixe de champs, nombres bornés : toutes les
fixtures admissibles restent sous8192octets. L'export refuse même un JSON valide
paddé à8193octets ; 8192 reste admis. Base64 canonique <=10924, décodé <=8192,
projection/revalidation Python puis Node à l'export/publication ; fichier0600,
dossier0700 exclusifs, publication séparée sans secret et rétention7jours restent
inchangés. Aucun octet privé ne figure dans le contrat ni dans les fixtures.
Les fixtures partagées Python/Node couvrent succès structurel, échecs/snapshots,
rejet causal puis reprise, races de stop, reçu invalide/révoqué, générations,
120/150/240/360, stabilité119999/120000, absence/null/zéro, provenance, types,
enums, champs superflus, sentinelles de payload et limites d'export/publication.
Les tests historiques v1/v2, profils, L1–L5, verrou, gates et supervision restent
requis. Aucun résultat réel nouveau ; suite7 non validée, étape8 suspendue.


## Activation H historique, suite fonctionnelle non validée

La fondation 7/8-E livre
la politique opt-in `NoPongAfter120`, son raccordement au vrai `V4Session`, et
ses tests avec le vrai `V4Lifecycle`. Le collecteur de suite installé par G2
instancie cette politique uniquement pour le second scénario. Le scénario
`session-300` conserve son fonctionnement par défaut.

G2 (PR #95) a raccordé la suite complète derrière le job en échec inconditionnel
`suite-installation`. MANAGER a revu son HEAD et ses quatre checks réussis avant
fusion. H (PR #96) a retiré seulement ce job et son `needs` dans `dry-run`, sans
modifier gates, budgets ou runtime. MANAGER l'a fusionnée le 16/10/2026 à
00:15:13 UTC, après revue, quatre checks CI et décision immuable distincte :
merge `d382540b056adf189bc7969b3d9905ab7dc8cd8f`.

Avant installation du nouveau verrou L2, le push `experimental` commençait par le
préflight sans secret, puis admission, environnement et recheck avant l'unique
étape utilisant l'identité. Sans décision de suite valide, aucun scénario ne
démarre ; une ancienne autorisation session-300 ne suffit jamais. Aucun Setting,
secret, claim réel, gate historique ou H1/H2 n'est modifié par DEV.

Le [bilan MANAGER sourcé](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6205715813)
consigne le [run #38828423500](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/38828423500),
tentative 1 sur ce merge, et l'artefact anonymisé #12016098316 lu par MANAGER :

| Observation du run | Résultat consigné |
| --- | --- |
| Premier scénario | `continuous_300s`, 300000 ms, une ouverture, aucune reconnexion, cinq lectures corrélées réussies et cinq Ping/Pong. |
| Second scénario | `inconclusive/protocol`, 181042 ms, une ouverture, trois lectures réussies, cinq Ping, trois Pong et deux Pong inhibés. |
| Reprise | Aucun EOF observé, aucune reconnexion ni stabilité de récupération. |
| Suite | `not_successful`, 481714 ms ; collecte/publication réussies et statut global en échec. |

Les deux scénarios ont été exécutés : ce résultat n'est **pas NOT RUN**. Le
nouveau 300 s est concluant comme l'historique, mais la suite/reconnexion ne sont
pas validées. La cause précise du refus protocolaire reste inconnue ; aucun
CloseClient reçu, EOF serveur ou timeout Ping causal n'est établi. Le rapport
v1 ne sera pas rétrocomplété. `boundary_proven=false` demeure, étape 8 suspendue.

### Run J avec diagnostics : refus local identifié, aucun EOF prouvé

Après revue/CI et décision MANAGER distincte, la PR #97 a été fusionnée au SHA
`991fbb8aefb3e3df9c38cd0eed38944a03e88cc7`. Le
[bilan J](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6207295244)
consigne le run #38839083483 tentative 1, artefact anonymisé #12020478846 :
suite v2 `not_successful` (481995 ms), premier scénario `continuous_300s`, second
`inconclusive/protocol` à 181260 ms, diagnostic
`message_classification/protocol/close_client`, lecture 3. Trois lectures réussies,
deux Pong inhibés, aucun EOF/reconnexion/stabilité ; les deux tests ont tourné.
Le framer a rejeté un octet de tête, puis le code installé ferme localement.
Aucun message CloseClient complet/sous-code, fermeture serveur ou timeout Ping
causal n'est établi. Ne pas rétrocompléter le rapport v1 précédent.

K propose seulement un [contrat de quarantaine jusqu'à EOF](session-eof-quarantine-proposal.md),
**PROPOSÉ / NON INSTALLÉ**, opt-in limité au second scénario après inhibition
exercée. Chronologie, coupure TX, lecture en vol, RX unique, suffixes privés,
bornes/arrêts et matrice offline y sont spécifiés. Le refus installé reste actif ;
aucune exception de portée ni implémentation n'est adoptée par cette PR.

## Politique de Pong testée hors ligne

- Le délai monotone de 120 s part de l'ouverture strictement acceptée de la
  première génération. Seule la réponse Pong à un Ping déjà reçu est inhibée.
- La décision est prise sous le verrou TX juste avant l'émission ; lectures V4
  et unique propriétaire RX restent inchangés. Aucun timer ne ferme le transport.
- Toute nouvelle génération rétablit les Pong normaux. Le lifecycle partagé
  reste propriétaire des pertes, du nettoyage et du backoff borné.
- Seul un EOF effectivement reçu est compté comme fermeture du pair. Fermeture
  locale, silence et erreur TLS générique ne sont pas des preuves d'EOF serveur.
  Un EOF après inhibition est une observation temporelle, pas une preuve de
  timeout Ping. Aucun payload, registre, identifiant ou exception n'est exporté.

La tranche 7/8-F a livré le moteur partagé décrit ci-dessous. G2 a raccordé le
point d'entrée et la publication sous verrou ; H a fusionné son retrait isolé.
Le run décrit ci-dessus n'a pas validé la reconnexion.

## Plafonds fixes du contrat, sans nouvelle autorisation live

| Budget | Maximum fixe |
| --- | --- |
| Scénario 1 | 300 s utiles ; plafond 360 s inchangé. |
| Scénario 2 | Plafond dur 600 s, nettoyage inclus ; au plus trois ouvertures, 1 Mio RX cumulé et dix lectures fixes espacées d'au moins 60 s. |
| Attente après inhibition du moteur/contrat actif, sous verrou | Historique inchangé : au plus 180 s après T+120 ; L3 ne le raccorde pas et propose une récupération totale de 120 s avec EOF ET ouverture avant 240. |
| Après réouverture | 120 s stables, avec lecture corrélée et Pong rétablis ; aucune attribution causale automatique. |
| Suite | Plafond dur 1020 s : 360 + 600 + 60 s de marge d'orchestration/nettoyage. |

Ces plafonds ont été acceptés dans la consigne MANAGER 7/8-F pour l'implémentation
offline, puis liés à la décision distincte H pour le run consommé. Le budget
historique de six lectures de `session-300` reste
inchangé ; `SessionReconnect` est un type explicitement allowlisté avec dix
lectures maximum, trois ouvertures et 1 Mio RX, sans réinitialisation à la reprise.

## Moteur et double schéma hors ligne

`scripts/session_suite.py:observe_suite()` reçoit une fabrique du gestionnaire
partagé, sans lire d'identité, d'environnement ou de destination. Il appelle le
collecteur `session-300` inchangé, attend son nettoyage, puis le second collecteur
uniquement si le premier résultat est `continuous_300s` ou `reconnected`. Sinon,
le deuxième sous-rapport porte explicitement `not_run/first_not_admissible`.
L'API du moteur n'expose aucun mode autonome pour le deuxième scénario. Le seul
point d'entrée de G2 appelle cette API séquentielle sans réimplémenter le protocole.

Le second collecteur réutilise `V4Lifecycle` et `V4Session` avec `NoPongAfter120`.
Il ne lit pas TLS et ne possède aucun protocole ni backoff. Les lectures fixes
restent espacées d'au moins 60 s, y compris après une perte ; aucune n'est rejouée.
Les observations monotones proviennent des callbacks d'ouverture/EOF du seul
propriétaire RX, même si une perte et une reprise surviennent entre deux ticks.
Un EOF après inhibition n'établit aucune causalité de timeout serveur.

Dans ce moteur actif historique, toujours sous verrou L2 et inchangé par L3 :
sans Pong inhibé avant T+300 : `not_exercised`. Sans EOF admissible au plus
180 s après T+120 : `no_disconnect`. Reconnexion épuisée : `reopen_failed`.
Une nouvelle perte après la première génération donne `stability_lost`, même si
le lifecycle se rétablit rapidement. Aucun cumul de fragments de sessions.
`recovered_120s/verified` exige une nouvelle génération, 120 s ininterrompues
depuis son ouverture acceptée, une lecture corrélée réussie et un Pong rétabli
sur cette même génération. Une erreur TLS générique n'est jamais comptée en EOF.

Le scénario 2 réserve 590 s à l'observation et 10 s au nettoyage dans les 600 s.
Le délai d'une lecture ne peut dépasser la deadline d'observation courante.
La suite garde une deadline de 1020 s, sans prolongation automatique ; une
expiration globale refuse de produire un rapport complet. L'annulation nettoie
le propriétaire partagé et se propage. Un nettoyage échoué interdit le succès.
Le launcher G2 applique en plus les limites externes décrites ci-dessous.

Deux sous-rapports identifiés contiennent uniquement provenance SHA/run/PR/
tentative, `boundary_proven=false`, compteurs bornés et catégories fermées.
Le schéma `session-300` est conservé ; celui du scénario 2 ajoute suppression,
EOF observés, délai relatif après seuil et preuves de reprise. Le résultat global
est `success` seulement si les deux résultats satisfont leurs critères ; sinon
`not_successful`. Python et `.github/scripts/session-suite-report.cjs` valident
indépendamment les clés exactes, types, plafonds, provenance et cohérence.
Aucun octet, registre, identifiant, empreinte, exception libre ou valeur du foyer.

Les tests utilisent le vrai gestionnaire et le vrai lifecycle, avec TLS/clock
simulés : ordre, échec du premier scénario, suppression puis EOF, reprise et Pong,
absence de Ping/EOF, erreur TLS, nouvelle perte, plafonds et cadence, annulation,
deadlines, nettoyage et refus des champs sensibles par les deux validateurs.

## Contrat d'admission spécifique — sous-ensemble 7/8-G1

La tranche G1 a installé le contrat et le gate de suite, testés hors ligne.
G2 les a branchés au workflow existant avec launcher/collecteur/publication sous
verrou. H a retiré seulement le préalable structurel, sans changer ce contrat ni
son implémentation. Aucun commentaire d'approbation réel n'est publié par DEV.

Le point d'entrée fixe `.github/scripts/session-suite-gate.cjs` réutilise les
mêmes contrôles que le gate historique : dépôt/acteur/push/HEAD protégé, workflow,
PR fusionnée et arbre identique, décision MANAGER, revue et CI exacte, politique
d'environnement, exclusion des observations historiques, réservation puis
recheck et approbation indépendante fraîche si requise. Il ne permet pas de
choisir un profil, des scénarios ou des budgets via des options ou l'environnement.
Les wrappers historiques `session-300` conservent leur contrat à quatre champs.

Pour la tentative 1, le commentaire MANAGER doit commencer exactement par le marqueur
`<!-- hoben-session-suite-approval:v1 -->`, suivi d'un unique objet JSON fermé :

| Clé exacte | Valeur attendue |
| --- | --- |
| `schema` | Entier `1`. |
| `scenario` | `session-suite`. |
| `candidate_sha` | HEAD candidat revu, 40 caractères hexadécimaux minuscules. |
| `ci_run_id` | Entier positif du run Validate PR, tentative 1, quatre checks réussis avant la décision. |
| `scenarios` | Tableau ordonné exact : `session-300`, puis `session-reconnect-no-pong`. |
| `limits` | Objet fixe de `.github/scripts/session-suite-contract.cjs`, ci-dessous. |

`limits` contient exactement `suite_process_seconds=1020`, `session_300` et
`session_reconnect_no_pong`. Les clés exactes de `session_300` sont
`useful_seconds=300`, `process_seconds=360`, `max_opens=3`,
`max_rx_bytes=1048576`, `max_reads=6`, `min_read_interval_seconds=60`.
Les clés exactes de `session_reconnect_no_pong` sont `process_seconds=600`,
`observation_seconds=590`, `cleanup_seconds=10`, `max_opens=3`,
`max_rx_bytes=1048576`, `max_reads=10`, `min_read_interval_seconds=60`,
`suppress_after_seconds=120`, `eof_wait_seconds=180`, `stable_seconds=120`.
Toutes les limites sont des entiers exacts ; aucune clé libre, valeur différente,
conversion de chaîne/booléen, sélection partielle ou permutation n'est acceptée.
Ces valeurs attestent un contrat revu ; elles ne paramètrent aucun processus.

La décision v1 doit être unique, authentifiée MANAGER, non modifiée et antérieure
à la fusion. Les anciens marqueurs session-300/H1H2/ha-parity n'autorisent pas
la suite, même avec des valeurs ressemblantes. La réservation atomique distincte
de tentative 1 est `refs/tags/hoben-session-suite-<candidate_sha>`. Son objet lie scénario,
contrat fixe complet, SHA candidat/merge, PR, run/tentative, décision immuable
et empreinte de politique d'environnement. Le recheck exige cette référence
exacte et ce contenu ; aucun repli vers un ancien claim, aucune suppression ou
réécriture d'un claim consommé ; relances natives selon le contrat courant ci-dessus.
La création d'un claim n'est testée
qu'avec GitHub simulé dans cette tranche, sans réservation réelle.

## Launcher G2 : plafonds externes et nettoyage

`launch_session_suite.py` lance uniquement `run_session_suite.py` avec Python
isolé, stdin/stdout/stderr neutralisés et un environnement allowlisté : contexte
Actions public, trois preuves `SESSION_SUITE_*`, dossier temporaire et identité
Hoben privée. Aucun token GitHub/Actions/OIDC, fichier de commandes Actions,
hook Python ou dépendance candidate arbitraire n'est transmis/installé.
Le collecteur refuse les seules anciennes preuves `SESSION300_*`, vérifie le HEAD
Git exact avant toute lecture d'identité, puis appelle `observe_suite()` avec le
vrai `V4Lifecycle`/`V4Session` et la politique partagée. Aucun scénario libre.

Un superviseur parent possède un groupe de processus distinct. Son horloge
monotone arme 360 s dès le démarrage, avec un plafond global de 1020 s. Après
nettoyage du premier scénario admissible, le collecteur demande l'unique
transition via un octet fixe sur un pipe privé. Le parent arme les 600 s avant
son acquittement sur un second pipe ; le deuxième lifecycle attend cet ACK.
Ni les plafonds ni un mode ne proviennent du pipe, d'un commentaire ou d'un input.
Transition doublée/invalide : arrêt, sans rapport inventé. Premier résultat KO :
aucune demande de transition et deuxième sous-rapport NOT RUN.

Le parent réserve la dernière seconde de chaque plafond à SIGKILL/reaping,
et arrête le groupe entier au plus tard au seuil 359/599/1019 s applicable.
Le nettoyage des descendants a lieu aussi après sortie normale, exception,
SIGINT ou SIGTERM du launcher ; les signaux sont brièvement masqués pendant
l'acquisition/nettoyage pour conserver la propriété du processus. Le collecteur
isolé rétablit ensuite leur livraison normale. Un timeout asyncio ignoré ou un
blocage du collecteur ne prolonge donc pas son budget externe. Échec/expiration
du superviseur : pas d'export, pas de faux sous-rapport de collecte.

Les tests horloge/processus simulés vérifient les plafonds propres et global,
l'ACK et les refus de contexte/IPC. Les tests POSIX hors réseau lancent un
processus résistant à l'annulation asyncio avec un descendant : arrêt dans
chacune des deux phases, sortie normale et SIGTERM du parent sans enfant actif.

## Export, publication et résultat G2

Le collecteur valide le double rapport Python avant création exclusive 0600
dans `hoben-session-suite-exports` (0700), au plus 8192 octets. Le workflow
n'exporte qu'après recheck réussi et sortie réussie du superviseur. Node relit
un fichier régulier sans suivre de symlink, revalide provenance et schéma,
puis transmet seulement du base64 canonique borné (10924 caractères maximum).
Un runner de publication distinct, sans environnement ni secret Hoben, valide
et matérialise à nouveau un fichier neuf 0600, sans écraser une sortie existante.
Artefact `session-suite-report-<SHA>-<run_id>-a1`, rétention sept jours maximum.

Le résultat `hoben-experimental-session-suite` relit et revalide le rapport.
Il réussit uniquement si collecte/publication sont réussies et si le résultat
global est `success` avec ses deux sous-résultats admissibles. Rapport manquant
ou refusé : sous-résultats non vérifiés et statut d'échec, sans données inventées.
Les refus pré-secrets inscrivent séparément les deux NOT RUN. Tests Python/Node
et scripts réels du workflow exécutés hors ligne couvrent ces chemins, les
plafonds d'export, les champs sensibles et les faux succès partiels.

## Diagnostics fermés du second scénario — 7/8-I

I exporte uniquement le diagnostic déjà enregistré dans `SessionReconnect` :
`failure_phase`, `failure_category`, `message_category`, et `read_slot` borné à
dix et égal au nombre de lectures tentées. Le premier diagnostic de la génération
en échec est conservé avant nettoyage ; un échec secondaire peut toujours donner
le terminal existant `closed`, sans remplacer la cause initiale. Une nouvelle
ouverture conserve la remise à zéro existante du diagnostic de transport rétabli.
Sans diagnostic enregistré, phase fermée opening/read/lifecycle/teardown et
catégorie terminale existante servent de repli. Aucun comportement n'est modifié.

Le framer refuse toujours tout type autre que Ping/DataResponse. Pour le seul
second scénario, l'octet de tête **déjà rejeté** peut donner `close_client`,
`data_updated`, `other_known` (table des discriminants de protocol.md §3),
`unknown`, ou `unclassified` sans discriminant attribuable. Aucun sous-code,
payload ou octet inconnu numérique n'est publié. Ces noms ne prouvent ni message
complet, ni longueur, ni frontière ; aucun décodage, saut, consommation de suffixe,
resynchronisation ou nouveau retry. Le diagnostic historique session-300 reste
`unknown` pour ces refus et son contrat reste inchangé.

Production et projection Python/Node émettent explicitement `schema=2` pour la
suite et le second sous-rapport, avec les quatre champs exacts obligatoires.
Le premier sous-rapport reste v1. La lecture des anciens rapports exige suite v1
et second v1, sans ces champs : aucun ajout implicite ni mélange v1/v2. Les deux
validateurs refusent clés/types/enums/provenance incorrects et toute donnée libre.
Bornes 8192 octets/10924 caractères, publication isolée et succès global indivisible
restent identiques. Les cas NOT RUN et recovered_120s gardent leurs critères.

Les tests synthétiques utilisent le vrai V4Lifecycle/V4Session : Ping/Pong puis
inhibition après 120 s, trois lectures corrélées et refus vers 181 s. Ils
discriminent type rejeté, MBAP invalide, corrélation et validation, EOF délivré
par le TLS simulé,
timeout, budget et nettoyage secondaire. Ce scénario est synthétique, pas une
reconstruction prouvée du run réel ; il ne résout pas sa cause inconnue.

## Handoff au MANAGER, sans relance DEV

MANAGER doit relire le diff et les quatre checks sur le HEAD candidat exact.
Une éventuelle décision de nouvelle validation réelle devra être distincte,
unique, immuable et conforme au contrat installé (SHA, CI, scénarios et limites),
avant la fusion au HEAD attendu. La tâche documentaire K n'autorise ni
implémentation ni validation réelle ; MANAGER décidera séparément d'une suite.
L'ancien run et son claim restent consommés. DEV ne publie ni
décision ni claim réel et ne lance aucun run. Le push reste soumis aux gates et au
recheck ; aucune ancienne décision/claim ni relance ne constitue un repli.

La validation exige ensuite un run réellement admis et son rapport anonymisé
vérifié : premier scénario admissible et second `recovered_120s`. `NOT RUN`,
`no_disconnect`, `not_exercised`, `inconclusive` ou échec ne valident pas la suite.
Un EOF après inhibition ne prouve pas sa cause ; `boundary_proven=false` reste
obligatoire. L'étape 8 demeure suspendue tant que cette validation manque.
DEV/CI restent offline ; ni rerun ancien, ni workflow indépendant, ni déclencheur
manuel, ni HA/hoben-live/main, ni commande/association/écriture Modbus.
