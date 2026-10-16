# Suite « Tests expérimentaux session » — verrou L2 intact, lifecycle L5 défaut-off

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

## Lifecycle L5 candidat, récupération privée bornée sans collecteur

Le [contrat L5](session-eof-quarantine-proposal.md#lifecycle-l5-candidat-consommation-liée-à-lorigine-et-récupération-bornée)
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

L5 est candidat jusqu'à revue/fusion puis livré hors ligne, défaut-off, sans
fournisseur consommateur. Aucune validation globale/recovered_120s par cette
tranche : collecteur et contrats diagnostic 150 s/rapport/admission versionnée
restent séparés, puis activation/retrait du verrou après revue complète.
Framer/protocole/ouverture/identité/TLS/profils, clients/HA, collecteurs,
launchers/superviseurs, rapports v1/v2/validateurs/export, gates/contrats/workflows
et budgets 360/600/1020, 350+10/590+10, 3 ouvertures/1 Mio, 6/10 lectures >= 60 s inchangés.
Aucun diagnostic 150 s branché, brut, live/décision/claim/rerun. Deux NOT RUN avant
secrets conservés ; suite 7 non validée et étape 8 suspendue.

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

Le futur commentaire MANAGER doit commencer exactement par le marqueur
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

La décision doit être unique, authentifiée MANAGER, non modifiée et antérieure
à la fusion. Les anciens marqueurs session-300/H1H2/ha-parity n'autorisent pas
la suite, même avec des valeurs ressemblantes. La réservation atomique distincte
est `refs/tags/hoben-session-suite-<candidate_sha>`. Son objet lie scénario,
contrat fixe complet, SHA candidat/merge, PR, run/tentative 1, décision immuable
et empreinte de politique d'environnement. Le recheck exige cette référence
exacte et ce contenu ; aucun repli vers un ancien claim, aucune suppression ou
réécriture d'un claim consommé, aucun rerun. La création d'un claim n'est testée
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
