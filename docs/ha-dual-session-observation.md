# Observation manuelle de deux sessions — #126/032

[Consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6560615058).
Base : `b5f0857f1c3e1f604fd5bc4c3f366ea26dcd3cca`, après #171/031.
Ce scénario est développé et testé **hors ligne**. État réel : **PENDING REAL
VALIDATION**. Aucun run antérieur ne valide cette observation.

## Sélection et autorisation

Après revue/fusion MANAGER et nouvelle autorisation du propriétaire, sélectionner
explicitement `dual-session-observation` dans le workflow manuel **Vérification
réelle Home Assistant** (`hoben-ha-manual.yml`) au SHA intégré à vérifier.
Les contrôles natifs propriétaire/événement/ref, l'environnement `hoben-live`,
ses approbations et le mutex `hoben-read-only-observation` restent requis.
Ni DEV ni CI ordinaire ne déclenchent ce workflow, de rerun ou de connexion.
Cette livraison ne crée ni ne reprogramme d'automatisation.

`all` conserve exactement ses sept scénarios, son ordre et ses budgets.
La sélection optionnelle n'est ajoutée ni au workflow protocole original ni
à une exécution automatique. Seul le secret existant `HOBEN_USER_GUID` est lu,
dans l'étape protégée. Aucun nouveau secret DeviceGuid ou pairing.
Les deux ouvertures utilisent le contrat normal initial ; un refus de B échoue
fermé et ne conduit pas à demander d'autre identité.

## Chronologie et preuve

T0 est le retour réussi de l'ouverture partagée réelle de A. Le temps de
préparation ou d'attente TLS n'est pas crédité à la fenêtre d'observation.
A utilise le vrai `HobenClient` et `HobenDataUpdateCoordinator`, sans listener
d'entité ni installation résidentielle ; B utilise `V4Session` persistante et
le codec de lecture V4 partagé, dans le même worker isolé. L'adaptateur ne
réimplémente ni le lecteur RX, ni le framer, ni les codecs. Les deux sessions
répondent normalement aux Ping ; aucun adaptateur d'inhibition n'est installé.

| Temps relatif | Preuve requise |
| --- | --- |
| 0, 60, …, 660 s | Douze lectures A tentées et décodées, génération 1, séquences 1 à 12, disponibilité locale et identité de snapshot renouvelée |
| 180 s | Deuxième ouverture B acceptée et une seule lecture V4 corrélée |
| 180–360 s | A poursuit sa cadence ; B reste idle, sans nouvelle lecture ni retry |
| 360 s | Fermeture explicite de B ; appel original de close terminé, RX/TX/opérations libérés |
| après B | A reste active et observée au moins 300 s après la **fin réelle** du close de B, et jusqu'à 660 s au minimum |
| fin | Fermeture A terminée, aucune ressource ni tâche orpheline, réapage indépendant attesté |

La tolérance de départ des opérations et d'acceptation de B est de 5 s ; la
lecture B reste sous son délai partagé de 30 s. La tolérance de fermeture B est
de 10 s. Ce sont des limites de conception locales, pas des faits serveur.
Le temps de nettoyage final de A ne complète jamais la fenêtre utile. Une
fermeture B retardée prolonge seulement l'observation passive de A après sa
lecture à 660 s, dans le budget initial, sans lecture hors cadence.
Une ouverture A supplémentaire est refusée (`max_attempts=1` dans ce seul
banc), sans changement de la politique du client distribué. B n'a aucun retry.
Une panne/indisponibilité/framing invalide interrompt la collecte, conserve
le premier diagnostic catégoriel et nettoie les deux ressources. Elle ne
crédite jamais un succès. Le mutex exclut les autres campagnes GitHub ; il ne
prouve pas l'absence d'application ou d'autre appareil extérieur.

## Budget global et confinement

Le profil de 900000 ms appartient exclusivement à cette sélection. Les profils
historiques restent au plus 600000 ms par worker ; `all` est inchangé.
Le premier step du collecteur arme un timestamp monotone **avant checkout et
construction du runtime**, sans identité. Le job optionnel est plafonné à
15 min. Le parent reprend ce timestamp, puis transmet la même échéance au
superviseur et au gardien ; aucun étage ne réarme 900 s. Le temps de préparation
consomme donc le budget et peut rendre le scénario non réalisable : refus
fermé, sans raccourcir les fenêtres exigées. Un timestamp absent/invalide ou
un budget épuisé refuse avant l'entrée du worker.

L'observateur conserve 60 s de réserve avant l'échéance de son gardien, lui-même
borné par le parent. Les fermetures individuelles ont un plafond de 10 s ;
annulation, arrêt dur, PID namespace et réapage restent dans l'échéance initiale.
Confinement existant : 1 Gio / 128 PID, système de fichiers en lecture seule,
worker non privilégié, Docker logs désactivés, identité sur pipe privé,
aucun fallback hôte. Deux transports au plus, aucune ouverture après fermeture B.
TLS reste vérifié certificat et hostname sur `myhoben.fr:465`, lecture V4 seule.

## Rapport expurgé

Python et Node valident indépendamment les mêmes clés, enums, bornes et preuves.
Le détail privé projetable reste plafonné à 8192 octets, l'étape à 16384 et le
rapport à 64 Kio. Le job de résultat sans secret revalide avant publication ;
un collect échoué/annulé ne peut rendre Actions SUCCESS malgré une étape verte.

Les fenêtres nominales `before` [0,180), `overlap` [180,360), `after` [360,fin]
contiennent séparément pour A/B : octets/livraisons RX, continuations d'un
message déjà partiel, maximum de préfixe tamponné, demandes, Pong, EOF,
invalides/inattendus/tronqués et compteurs de types logiques B3. Ce dernier
compteur n'est pas un compteur de chunks TLS. Une fragmentation de header MBAP
ne duplique pas un message. Le dernier diagnostic B3 de chaque fenêtre est
conservé ; les DEBUG structurés existants observent les headers logiques, sans
copie de RX ni second parseur. Les compteurs restent bornés (4096 événements
par catégorie/fenêtre, 1 Mio RX par rôle) : dépassement = FAILURE `budget`,
aucune publication d'un préfixe ou d'un payload.

Une longueur attendue est publiée seulement si B3 la prouve : Ping 1,
CloseClient 2 sous hypothèse post-open, `7+MBAP.length` pour 0E/07 et
`11+MBAP.length` pour 1B si MBAP validé. **OpenedClient reste un préfixe de 48
octets, total inconnu**, `boundary_proven=false`. Aucune causalité serveur ou
verrou intersession n'est déduite. Un sous-code CloseClient est publié seulement
après observation complète réelle. Exceptions libres, tracebacks, RX/header
bruts, GUID, valeurs de registres/capteurs et données domestiques sont exclus.

SUCCESS exige toutes les preuves, horloge native monotone, échéance respectée
et cleanup/réapage. Une horloge injectée reste `synthetic` et ne produit jamais
de succès live. Refus avant démarrage = NOT RUN ; preuve incomplète, timeout,
annulation, perte A/B, nettoyage non prouvé ou sortie excessive = FAILURE.

## Validation hors ligne

Les tests utilisent les vrais propriétaires client/coordinator/session, des
transports TLS en mémoire et une horloge contrôlée commune aux deux tâches.
Ils couvrent T0 décalé, cadence et lecture unique B, Pong normaux, fermeture B
retardée et fenêtre après fermeture, refus B, CloseClient/EOF/inconnu/troncature,
cleanup A/B interrompu, annulation, recul d'horloge et budget insuffisant.
Des reçus synthétiques indépendants éprouvent les refus Python/Node, les
preuves manquantes, la confidentialité, les gates natifs et le réapage. Les
régressions historiques restent exécutées, notamment #031, DataUpdated 30 s,
B3, H1/H2, HA/all et confinement. Aucun test réel n'est lancé pour ces preuves.
