# Suite « Tests expérimentaux session » — contrat offline 7/8-G1

La [consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6176992612)
demande une suite unique, sur le workflow push `experimental` existant :
`session-300`, puis `session-reconnect-no-pong`. L'étape 8 est suspendue.
La validation historique de la session continue reste acquise :
[run 38766830984](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/38766830984),
SHA `4ea1c802155b95014d50c6a4aab8250621959466`, résultat vérifié par MANAGER
`continuous_300s`, sans reconnexion. Elle ne valide pas le nouveau scénario ni
la suite, et ne prouve aucune frontière universelle OpenedClient.

## Installation structurelle : aucun accès réel

La fondation 7/8-E livre
la politique opt-in `NoPongAfter120`, son raccordement au vrai `V4Session`, et
ses tests avec le vrai `V4Lifecycle`. Aucun collecteur live n'instancie cette
politique. Le scénario `session-300` conserve son fonctionnement par défaut.

Le job initial `suite-installation` échoue inconditionnellement, sans checkout,
permission, environnement ni secret. Il écrit deux résultats **NOT RUN** dans
le résumé du run. `dry-run` en dépend et ne peut continuer ; admission, collecte
et publication restent derrière leurs dépendances et conditions existantes.
Une ancienne autorisation session-300, même authentique, ne lève pas ce verrou.
Cette pause mécanique empêche une exécution réelle du premier scénario seul.
Elle ne modifie aucun Setting, secret, claim, gate historique ou H1/H2.

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

La tranche 7/8-F ajoute le moteur hors ligne décrit ci-dessous. Aucun collecteur
live n'appelle ce moteur ; aucun nouveau rapport n'est publié sur les runs réels.

## Plafonds approuvés pour le moteur offline, sans autorisation live

| Budget | Maximum fixe non activé en live |
| --- | --- |
| Scénario 1 | 300 s utiles ; plafond 360 s inchangé. |
| Scénario 2 | Plafond dur 600 s, nettoyage inclus ; au plus trois ouvertures, 1 Mio RX cumulé et dix lectures fixes espacées d'au moins 60 s. |
| Attente après inhibition | Au plus 180 s après T+120, puis `no_disconnect` ou `not_exercised`, sans forcer la fermeture serveur. |
| Après réouverture | 120 s stables, avec lecture corrélée et Pong rétablis ; aucune attribution causale automatique. |
| Suite | Plafond dur 1020 s : 360 + 600 + 60 s de marge d'orchestration/nettoyage. |

Ces plafonds ont été acceptés dans la consigne MANAGER 7/8-F pour l'implémentation
offline uniquement. Le budget historique de six lectures de `session-300` reste
inchangé ; `SessionReconnect` est un type explicitement allowlisté avec dix
lectures maximum, trois ouvertures et 1 Mio RX, sans réinitialisation à la reprise.

## Moteur et double schéma hors ligne

`scripts/session_suite.py:observe_suite()` reçoit une fabrique du gestionnaire
partagé, sans lire d'identité, d'environnement ou de destination. Il appelle le
collecteur `session-300` inchangé, attend son nettoyage, puis le second collecteur
uniquement si le premier résultat est `continuous_300s` ou `reconnected`. Sinon,
le deuxième sous-rapport porte explicitement `not_run/first_not_admissible`.
Il n'existe aucun point d'entrée CLI ni raccordement au launcher dans cette PR.

Le second collecteur réutilise `V4Lifecycle` et `V4Session` avec `NoPongAfter120`.
Il ne lit pas TLS et ne possède aucun protocole ni backoff. Les lectures fixes
restent espacées d'au moins 60 s, y compris après une perte ; aucune n'est rejouée.
Les observations monotones proviennent des callbacks d'ouverture/EOF du seul
propriétaire RX, même si une perte et une reprise surviennent entre deux ticks.
Un EOF après inhibition n'établit aucune causalité de timeout serveur.

Sans Pong inhibé avant T+300 : `not_exercised`. Sans EOF admissible au plus
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
Le futur launcher devra aussi appliquer un plafond externe dur de processus.

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

La tâche 7/8-G permet un sous-ensemble cohérent si le raccordement complet
dépasse une petite PR. Cette tranche installe uniquement le contrat et le gate
de suite, testés hors ligne ; elle ne raccorde aucun launcher, workflow ou export.
Le verrou `suite-installation` reste strictement inchangé. Aucun commentaire
d'approbation réel n'est publié par DEV.

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

## Raccordement restant avant toute activation

Une tranche MANAGER suivante devra installer ensemble : le raccordement de ce moteur
au collecteur/launcher existant, les plafonds de processus externes, l'export et la
publication isolée des deux sous-rapports, le statut global du workflow et l'appel
du nouveau gate de suite installé mais encore inutilisé. Les limites de processus
360/600/1020 s, le nettoyage des enfants et l'allowlist d'environnement doivent
être démontrés hors ligne avant ce raccordement. Un premier résultat non valide
doit laisser le second NOT RUN. Sans Ping inhibé : `not_exercised` ; sans perte
observée : `no_disconnect` ; sans reprise/stabilité : échec ou inconclusif.

Le nouveau contrat doit refuser les anciennes décisions et claims session-300,
conserver les gates acteur/SHA/CI/environnement/recheck et la publication isolée,
et réserver une nouvelle autorisation anti-rejeu de suite. Ce raccordement complet
conservera le verrou structurel. Son retrait final et l'autorisation du run réel
exigeront une PR/décision d'activation séparée, après revue du contrat installé
et de tous les raccordements par MANAGER.
DEV/CI restent offline ; ni rerun ancien, ni workflow indépendant, ni déclencheur
manuel, ni HA/hoben-live/main, ni commande/association/écriture Modbus.
