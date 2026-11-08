# #186-D5 — protection de processus factice offline

Tâche `HOBEN-186-INFO-PROCESS-SUPERVISOR-OFFLINE-008`, base
`666ffc7f354d3f5873858831487a10bca53f80d4`, [consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/186#issuecomment-6713923452).
Trois fichiers nouveaux seulement : module, tests pytest, cette documentation.

## Ce qui est exécuté

`run_dummy(fixture=...)` n'accepte que quatre noms fermés : `cooperative`,
`ignore-term`, `tree`, `orphan`. Il lance un programme Python **constant** avec
l'interpréteur courant, `-I -S`, environnement non hérité, dossier temporaire
privé et stdin/stdout/stderr vers `/dev/null`. Aucun argv, chemin, code, import,
environnement ou worker réseau ne peut être choisi par input/rapport. Aucun CLI,
connexion socket/TLS ou fournisseur de capacité V4 n'est ajouté.

Sous Linux, cet auxiliaire ouvre sa propre session ; ses cibles occupent un
**autre groupe de processus**. Il active et vérifie `PR_SET_CHILD_SUBREAPER` dans
son propre processus, jamais dans pytest/HA. Les cibles fixes ne font que signaler
leur disponibilité puis attendre un signal. Dans `orphan`, le parent intermédiaire
meurt volontairement ; son enfant est adopté puis réapé par l'auxiliaire.
La vérification SID/PGID précède l'ACK ; le PID du leader est conservé jusque-là.
Le leader et ses descendants n'héritent pas du descripteur de preuve.

Le canal privé borné n'accepte que des jetons fixes. TERM est confirmé **après**
le vrai `killpg(SIGTERM)`. Si nécessaire, KILL n'est demandé qu'après 100 ms à
partir de la première confirmation TERM, puis confirmé après `killpg(SIGKILL)`.
Cette petite grâce est propre à la fixture, pas une politique Hoben. L'auxiliaire
reste vivant pour `waitpid` de **tous** ses descendants et vérifie le groupe vide
avant sa confirmation terminale. Le parent fait ensuite un vrai `Popen.wait` et
ferme ses descripteurs. Un signal envoyé, un EOF du canal, un code de sortie nul
ou la disparition du seul leader ne suffisent pas à attester le nettoyage.

L'EOF du canal de commande déclenche indépendamment kill/réapage de secours.
Le garde-fou local de l'auxiliaire est de quelques secondes ; ses boucles et son
réapage de secours sont bornés. Le parent attend sa terminaison même sur erreur
de contrôle. Un échec de `wait`, même suivi d'un réapage de secours réussi, reste
FAILURE sans attestation réparée. Hors Linux, sans subreaper ou si le parent
ignore/intercepte SIGCHLD, refus sûr sans modifier sa politique de signaux.
Un statut nul synthétisé sur ECHILD ne constitue pas une preuve de wait.
L'isolation démontrée est celle des **groupes/propriétaires**, pas un bac à sable
réseau, une isolation contre du code arbitraire ou une protection de processus live.

## Temps, résultats et preuves

Le réducteur `ProcessBudget` réutilise les constantes D2 : **3540 s observation,
60 s cleanup, 3600 s total**. Origine monotone avant lancement ; première demande
cleanup et deadline figées. Égalité de deadline = échec ; répétition de cancel,
TERM, incident ou activité ne rallonge rien. Tests aux frontières avec faux temps,
jamais une attente CI d'une heure. Les cas OS s'arrêtent dès que la courte fixture
est prête ; ils **ne prouvent pas** une observation Info d'une heure.

Le rapport fermé, rejoué et limité à **8192 octets / 64 événements**, contient
seulement catégories, booléens, comptes 1/2 et temps relatifs. Aucun PID, chemin,
stdout/stderr, environnement, exception libre, identité ou donnée domestique.

| Champ/résultat | Portée exacte |
| --- | --- |
| `proof_scope=synthetic_process_events` | Port de simulation, jamais preuve OS |
| `proof_scope=benign_local_process` | Exécution du seul programme local constant |
| `cleanup_attested` | Conjonction groupe isolé/vide, signaux confirmés, tous enfants réapés, wait parent, fermeture contrôle, horloge et délais valides |
| `os_cleanup_attested` | Même conjonction uniquement sur le port OS exact, pas un port fake |
| `result=SUCCESS` | **Test de protection du processus factice réussi**, jamais succès du scénario Info |
| `info_observation=NOT RUN` | Invariant : aucun V4/Info ne s'exécute dans ces sous-processus |
| `tls_cleanup/live_provenance=not_proven` | Invariants, même avec SUCCESS du test de processus |

Les erreurs, preuves absentes/contradictoires, timeout, annulation et cleanup non
attesté donnent FAILURE ; sans création du processus, NOT RUN. Les demandes de
commande/chemin arbitraires et rapports malformés sont rejetés avec une erreur
fixe expurgée avant tout lancement. Première cause conservée séparément des faits
physiques de réapage ; ceux-ci peuvent être vrais après annulation sans succès.

L'annotation optionnelle `fixture_evidence` réutilise le vrai validateur C/D2/D4.
Elle est fournie par le parent et **non liée au processus** : aucun résultat C
n'est présenté comme produit par cet auxiliaire. Son INCONCLUSIVE/FAILURE demeure
inchangé. La validation JSON vérifie cohérence/types/chronologie, **n'authentifie
pas** un journal intégralement fabriqué. La provenance GitHub/TLS reste non prouvée.
Le refus live D1 demeure inconditionnel, y compris pour un tel rapport valide.

## Validation et limites de livraison

Tests OS courts : coopératif, TERM ignoré puis KILL, arbre, enfant orphelin,
annulation répétée, rupture du contrôle, faux échec du wait ; vérifications
indépendantes groupe disparu et enfant déjà réapé. Matrice synthétique : bornes
3540/3600, réserve anticipée, horloge invalide/recul, ordre et omission de preuves,
reaping/signal/contrôle défaillants, plafond de journal/sortie, falsification et
non-fuites. Régressions A/B/C/D1/D2/D3/D4, #192/B4/B6/B7/B8/DataUpdated, HA et Ruff.

CHANGELOG non modifié : nouveau banc offline non raccordé, aucun effet distribué.
Aucun workflow, gate, claim, launcher manuel, HA, protocole ou budget historique
changé. `manual_info_route_not_connected` et le refus de publication D1 restent
intacts. **Info framing INCONCLUSIVE, boundary_proven=false. Tests réels NOT RUN ;
lancement manuel NON PRÊT.** #192 cleanup S1/S2 et V1–V6 non résolus. MANAGER seul
prépare la suite après revue ; CODEX ne fusionne ni ne s'attribue la tâche suivante.
