# Quarantaine jusqu'à EOF — NON RACCORDÉE (fondation temporelle 7/8-L3)

Cette conception répond à la [tâche MANAGER L3](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6176992612).
L3 autorise seulement la fondation temporelle pure décrite ici, sans observation
réelle ni raccordement. Le comportement installé
reste le refus protocolaire suivi du nettoyage local, sans retry de ce refus.
Le scénario 300 s, les sessions ordinaires et HA/hoben-live restent inchangés.

## Fondation L1 isolée, API et limites

La décision MANAGER L1 autorise seulement un module pur non raccordé :
`v4_eof_quarantine.py`. Cette fondation existe séparément de la proposition de
réception ci-dessous, toujours **NON INSTALLÉE / NON ACTIVÉE**. Elle n'importe que
dataclasses/enum, ne lit aucune horloge, n'appelle aucun callback et n'acquiert
aucun verrou. Aucun chemin actif ne l'importe ou ne l'appelle ; un contrôle
structurel couvre custom_components, scripts et les automatisations du dépôt.

| API pure | Contrat local, sans effet réel |
| --- | --- |
| Construction | Première génération acceptée déclarée `1`, T0 et échéances observation/process/suite injectés. Temps monotones en millisecondes entières entre 0 et 2^53−1, marge d'addition 240000 pour la politique, 360000 pour le contrat L3 ; booléens, flottants (dont NaN/infini), valeurs invalides ou génération inconnue refusés. |
| `request()` | Scénario/rejet en enums fermés, génération, timestamp, nombre d'inhibitions borné, booléens TX engagée/arrêt local. Éligibilité après 120 s et avant la plus courte échéance, uniquement second scénario/close_client. Toute demande pose irréversiblement `block_tx`; ce drapeau **n'atteste pas** une coupure TX réalisée. |
| `advance()` | Événement fermé EOF/tick/TLS sans EOF/close/annulation/TX engagée et génération/temps injectés. REQUEST est réservé à request(). Aucune réception/décodage d'octets ou sous-code. Aucun timer ne fait avancer cet état sans appel. |
| `snapshot` / repr | Copie figée : état, motif fermé, block_tx, génération, deadline et date du candidat éventuel, scalaires bornés uniquement. Repr de politique constant ; aucun texte d'exception/payload/identité. |

L3 remplace la borne historique pure L1 T0+300000 par
`min(T0+240000, observation, process, suite)` en ms ; aucune
durée configurable ou remise à zéro. Le refus est absorbant, sans reset ni
réarmement par génération tardive. Une répétition identique est idempotente.
Des temps rétrogrades ou deux événements distincts au même timestamp sont
refusés comme invalides/ambigus ; close/annulation/TX engagée restent prioritaires.
EOF exactement à la deadline est refusé fermement : cette fondation ne tranche
pas une course temporelle réelle à la limite ni un ordre sous la milliseconde.

`EOF_CANDIDATE` est une indication **provisoire**, jamais preuve transport ou
décision de retry. Arrêt, échéance, événement périmé/invalide ou ordre ambigu
peuvent la révoquer vers un refus définitif ; aucun recovered_120s n'est produit.
Le futur pont RX devra attester origine/génération/ordre avant toute décision
réelle. Le futur propriétaire TX devra réaliser et prouver son gel. Ces limites
conservatrices ne sont pas une implémentation de la quarantaine K ; aucun
comportement, budget, rapport ou gate existant n'est changé par L1.
Un EOF/tick avant la demande admissible est refusé ; les arrêts préalables
scellent aussi le refus. Cette API ne remplace pas un ordonnanceur de session.

## Contrat temporel L3 pur, sans statut de réussite réel

`RecoveryTiming` est immuable, limité à des scalaires validés et indépendant de
toute horloge réelle. T0 désigne l'acceptation stricte déclarée de la **première
génération du second scénario**, pas le début du processus ni de la suite.

| Repère fixe | Contrat proposé, NON RACCORDÉ |
| --- | --- |
| Avant T0+120000 ms | Pong normaux. |
| Dès T0+120000 ms | Inhibition Pong à exercer réellement ; début de la fenêtre totale de récupération. |
| Dès T0+150000 ms | Seuil de future observation renforcée, aucune instrumentation branchée ici. |
| Avant T0+240000 ms strictement | Inhibition exercée, EOF transport admissible, nettoyage/backoff bornés ET nouvelle ouverture strictement acceptée. |
| Après cette ouverture | Pong rétablis, lecture corrélée réussie et 120000 ms ininterrompues sur cette même génération. |
| T0+360000 ms au plus | Maximum nominal fonctionnel, jamais un minimum à remplir ; fin précoce après les 120 s permise. Une égalité à une deadline échoue fermée. |

La fenêtre totale de récupération est **120 s**, EOF **et réouverture** compris.
Elle remplace les anciennes hypothèses proposées EOF T0+300/attente 180 s.
Un EOF précoce suivi d'une ouverture à/après 240 s ne suffit pas. Une reprise à
239999 ms permet arithmétiquement une fin à 359999 ms ; une reprise à 200000 ms
peut finir à 320000 ms. Seconde perte, absence d'inhibition/EOF/Pong/lecture,
stabilité insuffisante, génération périmée ou course ambiguë : pas de recovered_120s.

`check_recovery_timing()` vérifie seulement des déclarations scalaires : ordre
suppression/EOF/ouverture, générations, dates de Pong/lecture/stabilité et absence
déclarée de perte/arrêt/ambiguïté. Son enum `compatible_calculation_only` n'est
ni une preuve d'effets, ni un rapport, ni un droit de retry. `None`/bool/float/NaN,
overflow et temps rétrogrades échouent fermés. L'origine EOF, l'ouverture stricte,
le gel TX et le backoff/nettoyage restent à prouver par le futur pont.

Les deadlines effectives sont les minima avec observation/process/suite : aucune
réinitialisation ni prolongation pour obtenir les 120 s. Premier scénario toujours
300 s ; plafonds externes installés **360/600/1020 s**, budgets internes
**350+10/590+10**, trois ouvertures/1 Mio par scénario, six/dix lectures espacées
d'au moins 60 s conservés. Ouverture initiale et nettoyage sont séparés du maximum
fonctionnel de 360 s et restent sous ces plafonds. Budget restant insuffisant :
non concluant. Le contrat d'admission actif n'est pas modifié : avant usage, un
futur contrat versionné devra lier ces constantes et leurs sémantiques ; aucune
ancienne décision/claim/rapport ne les valide.

À partir de 150 s, les futures observations seront limitées aux temps relatifs,
compteurs/tailles/offsets bornés, état/motif/catégorie fermés au point de rejet et
origine/absence d'EOF. Clés, version et matrice de cohérence Python/Node restent
à spécifier avant instrumentation. Aucun octet RX, hex/base64 de trame, sous-code
deviné, valeur domestique, GUID, exception libre ou capture brute persistée/exportée.
Une capture privée brute n'est **pas autorisée** par L3.

Le verrou L2 est installé et vérifié : voir le [bilan MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6209326192),
fusion #100 `ea08be522c73fcca742c4bacbeafa7df75e8b0c7`, run #38859779145
tentative 1 en échec attendu au préalable, tous les jobs aval skipped, deux NOT RUN
avant admission/claim/secrets. Ce verrou reste intact ; la quarantaine reste non
raccordée/non activée. Tests L3 synthétiques de calcul et invariants L1 seulement,
sans exécution de la matrice d'intégration future ci-dessous ni nouveau live.

## Observation, explication locale et inconnues

Le [bilan MANAGER J](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6207295244)
consigne le [run #38839083483](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/38839083483),
tentative 1, candidat PR #97 `409c65d971f51c686fed9dc2e0fbd8754d8fe085`, merge
`991fbb8aefb3e3df9c38cd0eed38944a03e88cc7`. Collecte/publication réussies,
résultat global en échec ; artefact anonymisé #12020478846 vérifié par MANAGER.

| Élément OBSERVÉ et consigné | Résultat |
| --- | --- |
| Suite v2 | `not_successful`, 481995 ms, `boundary_proven=false`. |
| Premier scénario v1 | `continuous_300s`, 300000 ms, une ouverture, cinq lectures et cinq Ping/Pong, aucune reconnexion. |
| Second scénario v2 | `inconclusive/protocol`, 181260 ms ; `message_classification/protocol/close_client`, `read_slot=3`. |
| Compteurs du second | Une ouverture, trois lectures réussies, cinq Ping, trois Pong, deux inhibitions ; 205 octets/10 chunks comptés, sans contenu publié. |
| Preuves de récupération | Zéro EOF/reconnexion/stabilité ; `eof_after_threshold_ms=null` (aucun délai mesuré), aucune génération/lecture/Pong de récupération. |

Les deux scénarios ont tourné : ce n'est pas NOT RUN. Le code installé explique
le **refus local** : `ExperimentalV4Framer.feed` rejette l'octet de tête examiné,
puis `_receive_unproven_handoff` libère le transport dans son `finally`.
`V4Lifecycle` ne retente pas cette erreur protocolaire. Cela ne prouve aucun
message CloseClient complet, sous-code, longueur, EOF serveur ou timeout Ping
causal. Le rapport v1 antérieur #38828423500 n'est pas rétrocomplété. La session
continue historique #38766830984 et les nouveaux 300 s sont concluants ; la suite
et la reconnexion restent NON VALIDÉES, étape 8 suspendue.

## Périmètre proposé et point de coupure

Une future politique distincte, fermée et opt-in serait limitée au **second**
scénario, à sa première génération strictement acceptée. Elle exigerait toutes
ces conditions au moment du refus : T0 d'acceptation connu, T >= T0+120 s mais
T < T0+240 s, au moins un Pong réellement inhibé sur cette génération, et le
seul discriminant `close_client` déjà rejeté au point de classification existant.
Aucun élargissement du framing, aucun décodage du sous-code/suffixe. Un type
DataUpdated/inconnu, une frontière MBAP ambiguë ou un refus sur une génération
ultérieure garderaient le comportement installé. Éligibilité incertaine : arrêt
protocolaire sûr, sans attente spéciale ni reconnexion sur ce refus.

Le propriétaire RX poserait **sans await**, avant toute autre action, un verrou
logique irréversible pour cette génération : mode interne proposé `QUARANTAINE`.
Cet instant est le point de coupure des émissions applicatives. Tous les chemins
de lecture V4/Pong revérifieraient ce verrou sous le verrou TX existant, juste
avant l'émission ; les opérations déjà en file ne passeraient plus. Aucune
nouvelle tâche RX, nouvel OpenClient ou nouvelle TX ne serait lancé par ce mode.
L'échéance absolue borne l'attente ; aucun timer émetteur ou close pour fabriquer
un EOF n'est introduit.

Un write déjà remis au transport ne peut être rappelé. L'absence de TX en cours
devrait être attestée au point de coupure par le suivi du propriétaire TX ;
sinon l'observation serait déclarée non admissible et nettoyée sans faux EOF ni
retry. Attendre le verrou puis prétendre avoir gelé plus tôt serait incorrect.
Le latch synchrone bloque toute nouvelle entrée avant acquisition du verrou ;
RX ne conserve aucun verrou TX pendant l'attente passive. Arrêt explicite ou
annulation restent prioritaires et rendent cette observation non admissible.

## Lecture en vol, propriétaire unique et données privées

Une lecture dont la TX est achevée mais la réponse encore attendue serait
terminée une seule fois par un **signal interne de quarantaine**, sans résultat
inventé ni replay. Son numéro reste consommé ; une requête réellement envoyée
sans réponse corrélée reste une lecture échouée. Une demande en file non émise ne
consomme pas de nouveau slot. Une réponse validée et livrée avant la coupure
reste acquise ; aucun événement non livré du chunk rejeté ne devient un succès.

Ce signal ne doit emprunter ni l'actuel chemin d'abandon de lecture qui appelle
`close()`, ni le catch générique du collecteur qui termine la suite, ni une
conversion artificielle en `HobenTransportError`. Le waiter et son timeout sont
retirés une fois, le suivi d'opération est libéré, sans prolonger sa deadline ni
annuler RX. Si la deadline/annulation a déjà gagné ou si cette séparation ne
peut être prouvée, arrêter sans observation EOF admissible. Le collecteur cesse
de planifier des lectures et attend l'état de l'unique propriétaire partagé.
La notification de quarantaine suspendrait la disponibilité applicative publiée
par le lifecycle : ni `wait_connected()` ni le budget utilisable ne doivent
laisser planifier une nouvelle lecture sur cette génération. Le signal de perte
terminale ne serait émis qu'après la décision EOF/échec, sans déclencher le
cleanup du lifecycle pendant l'attente.

Le propriétaire RX existant continuerait seul à lire TLS vérifié, sans repasser
dans le framer ni router les octets reçus en quarantaine. Le fragment rejeté et
son suffixe coalescé, puis les fragments ultérieurs, resteraient privés et non
interprétés, bornés par le budget RX restant. Aucun saut, scan de Ping, découpage
CloseClient ou DataUpdated, décodage domestique, log ou fichier de capture.
Tous les octets livrés, y compris ceux du chunk rejeté, sont comptés **une seule
fois** par le budget partagé (ouverture incluse). Une livraison dépassant le
budget arrête l'observation ; ne pas la stocker au-delà du plafond, ni publier
son contenu. Les buffers privés sont libérés au nettoyage, sans réutilisation
par une autre génération. Ni le collecteur ni le lifecycle ne lisent TLS.

## EOF admissible et bornes inchangées

La deadline monotone de récupération serait **T0+240 s**, donc une fenêtre totale
de 120 s après T0+120 pour EOF ET réouverture. Elle ne se réarme
jamais sur des octets, une requête ou un Ping. Les bornes internes restent
590 s d'observation + 10 s de nettoyage dans 600 s pour le scénario, plafond
externe 600 s, suite 1020 s et premier scénario 360 s. Toujours trois ouvertures,
1 Mio RX par scénario et dix lectures espacées d'au moins 60 s pour le second,
six pour le premier ; cadence et budgets ne se réinitialisent pas à la reprise.
L'échéance effective est la plus proche de T0+240, de l'échéance d'observation
(début du second scénario +590 s) et des plafonds externes/scénario/suite. Si le budget restant
ne permet pas la récupération et ses 120 s stables, échouer sans prolongation.

Seul un EOF effectivement délivré par la lecture du transport de cette génération
avant toute demande locale de fermeture/annulation, dans le délai, pourrait
produire une preuve privée d'EOF admissible. Le callback porterait génération,
horodatage monotone et origine EOF, sans payload. Il serait idempotent. Un
retour vide causé par un arrêt local ne convient pas : l'ordre des événements
locaux doit être attesté, pas déduit du seul type d'exception après nettoyage.

| Fin d'attente proposée | Décision avant nettoyage |
| --- | --- |
| EOF transport réellement livré, génération/provenance/délai vérifiés | Sceller une seule preuve EOF ; autoriser ensuite le lifecycle à considérer cette perte pour sa récupération bornée. |
| Silence à T0+240, octets sans EOF, dépassement de durée/RX | Résultat non concluant, aucune preuve EOF ni réouverture liée à cette quarantaine. |
| Erreur TLS/transport sans EOF attesté | Échec non admissible, aucune promotion de cette erreur en preuve EOF/retry de quarantaine. |
| Annulation, arrêt local, TX déjà en vol ou ordre d'événements incertain | Interruption/non-admissibilité ; nettoyage autorisé, aucun EOF admissible ni retry. |

Un EOF ne serait admissible que si sa livraison est attestée strictement
à T < T0+240 et que la décision de timeout/arrêt n'a pas déjà été scellée.
L'égalité exacte est refusée et la nouvelle ouverture doit aussi précéder 240 s.
Une course ambiguë échoue fermée. Nettoyage après décision/échéance et fermeture
locale sont distincts de la lecture EOF et n'incrémentent jamais `peer_eofs`.
Le superviseur garde son arrêt externe, même si le propriétaire ne répond pas ;
un kill, un rapport absent ou un nettoyage défaillant ne donnent aucun succès.

Après EOF admissible seulement, le lifecycle partagé garderait la propriété de
la fermeture/nettoyage, du backoff et des ouvertures restantes. Aucun replay de
lecture, réponse tardive réattribuée ou copie du suffixe vers la nouvelle session.
La génération suivante devrait être acceptée avant T0+240, rétablirait les Pong
normaux et devrait rester stable
120 s **ininterrompues**, avec lecture corrélée réussie et Pong rétabli sur cette
même génération. Deuxième perte : échec, pas cumul de périodes. Il faut aussi
le premier scénario admissible. Un discriminant seul ne valide rien et l'EOF
ultérieur n'établirait toujours pas la causalité d'un timeout Ping.

## Modifications envisageables et ordre de revue

1. Faire décider par MANAGER l'exception de portée, ses critères et le mécanisme
   d'opt-in fixe. Cette PR n'adopte pas l'exception dans `project.md` : elle la
   documente comme PROPOSÉE/NON INSTALLÉE, sans autoriser la tranche suivante.
2. Une tâche d'implémentation offline distincte devrait ajouter le mode privé
   de session, la coupure TX, le signal de lecture sans close, les notifications
   de disponibilité/quarantaine et la preuve EOF au gestionnaire partagé.
   Le lifecycle attendrait sans déclarer cette quarantaine comme perte, puis
   consommerait uniquement la preuve EOF admissible avant sa politique existante.
   Le collecteur observerait ces états sans nouveau lecteur, protocole ou retry.
   Aucun flag libre par variable d'environnement, input ou commentaire candidat.
   Ce futur code devrait rester inactif par défaut et sous verrou structurel
   vérifiable jusqu'à la revue des mécanismes d'admission et l'activation distincte.
3. Examiner séparément l'extension de rapport nécessaire : catégories/compteurs
   fermés de quarantaine et issue de l'attente, distincts des diagnostics causaux
   et du terminal. Python/Node doivent imposer cohérence génération/EOF/reprise,
   clés exactes et version explicite, préserver v1/v2 sans rétrocomplément, taille
   8192 octets/base64 10924 caractères et provenance SHA/run/PR/tentative exacte.
   Le v2 installé n'est pas assoupli pour faire passer un diagnostic protocolaire
   causal pour une réussite ; observation EOF et diagnostic doivent être séparés
   dans le futur contrat explicitement revu.
   Choisir les clés/version dans une future tâche ; rien n'est accepté aujourd'hui.
4. Avant tout usage, faire revoir séparément tout éventuel changement du contrat
   ou gate installé nécessaire pour distinguer cette nouvelle portée. Ne pas
   ajouter un opt-in candidat qui s'autorise lui-même, ni réutiliser l'approbation
   actuelle. Installation structurelle revue avant activation distincte, avec
   blocage réel de l'accès si nécessaire. Décision immuable sur SHA/CI exacts,
   environnement/approbation si requise, recheck, anti-rejeu et publication isolée
   conservés. Les anciens runs et claims restent consommés, sans rerun.

Risques bloquants à démontrer : TX déjà engagée, deadline du waiter qui ferme
TLS, `finally` RX ou cleanup lifecycle prématuré, indisponibilité non propagée,
suffixe remis au framer, double comptage, EOF issu du close local et preuve
d'une génération périmée. Si l'une des garanties échoue, conserver le refus
installé ou arrêter sans récupération admissible ; ne pas inventer un budget,
une preuve ou un succès. Aucune préparation HA/main ni étape 8 automatique.

## Matrice d'intégration offline à réaliser ultérieurement

Tous les cas devront appeler les vrais V4Session/V4Lifecycle et le collecteur
partagé avec TLS et horloge simulés, sans réseau, identités réelles ou RX réel.

| Cas à spécifier | Assertions exigées |
| --- | --- |
| Discriminant seul, fragmenté, coalescé avec suffixe privé | Même éligibilité au point de rejet ; aucune attente de sous-code, aucune longueur inventée, suffixe jamais routé/exporté, octets comptés une fois. |
| EOF livré après coupure vs silence/données sans EOF | Seul le premier cas peut autoriser récupération ; EOF ET ouverture avant la deadline absolue T0+240, inchangée malgré les données. |
| Avant 120 s, inhibition non exercée, génération ultérieure | Refus installé conservé, aucune quarantaine spéciale ni retry protocolaire. |
| EOF avant 120 s ou avant inhibition effective | Perte transport traitée selon le lifecycle existant, sans preuve d'EOF après suppression ni réussite de la nouvelle observation. |
| DataUpdated, type inconnu, MBAP ambigu | Refus identiques, aucune nouvelle interprétation ou resynchronisation. |
| Lecture en attente, TX en file/en vol, Pong, retour de réponse | Point de coupure atomique, aucune nouvelle TX ; TX en vol rend non admissible ; waiter terminé une fois sans close/replay, succès uniquement déjà livré avant coupure. |
| Course deadline de lecture/quarantaine, EOF/timeout/annulation | Tous les ordres déterministes ; priorité arrêt, décision scellée, aucune prolongation/faux EOF ni deadlock du verrou TX. |
| RX au plafond/dépassé, durée dépassée, TLS sans EOF | Arrêt sûr sans faux EOF/récupération ; mémoire et rapport bornés, aucun budget nouveau. |
| Nettoyage, erreur secondaire, arrêt/annulation et superviseur | Pas de tâche/socket/lock/waiter résiduel, close une fois ; premier diagnostic conservé, aucun EOF compté au cleanup. |
| EOF admissible puis reprise bornée, sans Pong/lecture ou seconde perte | Backoff/limites inchangés ; seuls 120 s stables sur même nouvelle génération avec Pong et lecture donnent recovered_120s ; aucune réponse tardive/réémission. |
| Rapports Python/Node, versions anciennes, export/publication/statut | Versions explicites et exactes, provenance/tailles/types/enums/cohérence ; refus de secrets, payload, registres, valeurs domestiques et exceptions ; aucun faux succès partiel/NOT RUN. |

Les 2906 tests de PR #97 constituent une validation **historique** du code
installé, pas l'exécution de cette matrice. Chaque PR doit obtenir ses quatre
checks CI au HEAD exact ; L3 ajoute seulement des tests de
calcul pur et conserve les invariants L1. Aucune collecte réelle ni nouvelle
décision/claim n'est nécessaire ou autorisée pour rédiger cette proposition.
