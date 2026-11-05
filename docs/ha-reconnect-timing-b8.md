# B8 — reconnexion HA selon une perte prouvée

Tâche exclusive [HOBEN-163-B8-RECONNECT-10-30-013](https://github.com/Guillaume0385/ha-hoben-community/issues/163#issuecomment-6647516982),
base `experimental` `16eefe3c5d927be45b9db642392a73af9482f0d8` après B7/PR #181.
#126 reste suspendue par le propriétaire. Ces délais sont une politique locale
HA ; ils ne prouvent aucune règle de disponibilité ou d’exclusivité du serveur.

## Classification et échéances

| Preuve du propriétaire RX/acquisition | Délai avant reprise |
| --- | --- |
| CloseClient complet, sous-code reconnu 3 ou 6, post-open | Cleanup attesté, puis 10 s avant nouvelle TLS ; 10 s après ouverture acceptée avant lecture |
| EOF TLS exact ou lecture vide, sans message partiel dans le framer | Même règle 10 + 10 s |
| Timeout effectivement expiré d’une acquisition/lecture | Lecture neuve au plus tôt à timeout + 30 s, après cleanup et nouvelle ouverture |
| Erreur transport générique, timeout sans preuve d’acquisition, CloseClient inconnu, framing rejeté ou EOF partiel | Politique conservatrice existante de 60 s après cleanup |
| Auth/identité refusée, certificat rejeté, erreur interne permanente, cleanup_failed/non attesté, stop/unload | Aucun retry |

La classe ou la phase d’une exception ne suffit pas à prouver EOF ou timeout
d’acquisition. V4Session conserve uniquement deux faits privés de propriétaire :
EOF exact du read TLS et instant monotone d’une acquisition abandonnée par son
véritable timeout. Ils ne contiennent aucun octet reçu. Un timeout de Pong sans
acquisition prouvée reste conservateur ; une erreur interne n’est jamais
transformée en timeout récupérable. Les sous-codes auth 2/4/5 restent terminaux.
Aucun parsing, codec ou framing n’est modifié ; 48 octets OpenedClient restent
un préfixe et non un total universel.

L’attente de 10 s avant TLS commence **après** le nettoyage et le réapage.
L’échéance timeout utilise l’instant original : si le nettoyage dure 3 s,
il reste 27 s ; s’il dure plus de 30 s, aucun délai supplémentaire n’est exigé,
mais aucune ouverture n’est permise avant preuve complète. Le contrat ne promet
pas une lecture à exactement 30 s si le nettoyage, TLS ou l’ouverture prennent
plus longtemps. Les durées sont monotones et la boucle peut exécuter une action
plus tard ; un saut UTC ne permet pas d’anticiper une échéance.

## Propriétaires et acquisition

L’entrée HA active explicitement `ha_reconnect=True, ha_fast_reconnect=True`.
Ce second choix interne n’ajoute aucune option UI, secret ou workflow. Il permet
de préserver les clients de campagne/config-flow et leurs politiques explicites
existantes, y compris HA-60 ; aucun budget ou scénario #126 n’est modifié.

Le même superviseur lifecycle demeure propriétaire des tentatives et du cleanup.
Après ouverture, le propriétaire RX reste actif et répond aux Ping pendant les
10 s supplémentaires. Une perte dans cette attente annule/réape ses deux
observateurs temporaires, nettoie cette génération et applique la politique de
la nouvelle cause ; elle n’autorise aucune lecture anticipée. Un échec d’ouverture
récupérable revient au délai conservateur de 60 s. Aucun compteur artificiel de
tentatives n’est ajouté au superviseur HA existant.

Une fois la génération réellement prête, le lifecycle publie une admissibilité
locale de génération, distincte d’une preuve de lecture. Le coordinator existant
programme **une seule acquisition événementielle**, par son API de refresh HA,
avec son verrou client et ses contrôles de corrélation/décodage. Un setup ou poll
déjà en attente la consomme sans doubler la requête. Les événements répétés ne
lancent pas de boucle, de timer de polling ou de nouvelle session. La cadence
périodique normale reste 60 s. Un arrêt annule et joint aussi cette acquisition.
Le choix conservateur conserve son comportement de lecture au prochain refresh.

La disponibilité B7 reste limitée à moins de 300 s depuis la **première perte**.
Ni une tentative ni une ouverture ni l’événement d’admissibilité ne rafraîchissent
les valeurs, le succès HA, l’âge ou l’horodatage original. Une perte pendant
l’attente suivante ne renouvelle pas la fenêtre. À 300 s, les entités expirent
même sans poll ; seule une réponse neuve corrélée et décodée peut rétablir la
fraîcheur. Sans lecture préalable, aucune conservation n’est accordée.

## Preuves hors ligne et limites

Avant correction, un test sur les vrais V4Lifecycle/V4Session montre RED :
une perte EOF nettoyée demande 60 s au lieu des 10 s autorisées. Après correction,
les tests synthétiques vérifient 9,999/10 et 19,999/20 s, timeout + 29,999/30 s,
nettoyage inclus, ainsi que la voie conservatrice à 59,999/60 s.

Les tests HA utilisent les vrais entrée, HobenClient, coordinator et capteurs,
avec transport et horloge injectés : EOF, CloseClient, timeout réellement expiré,
trois pertes successives, concurrence avec un poll, setup sans lecture valide,
pertes avant acquisition, expiration B7 sans poll et nouvelle acquisition.
Les tests de l’adaptateur AsyncTlsTransport gardent connect/read/write/close,
TLS certificat/hostname vérifiés et wait_closed sur **streams synthétiques** :
fermeture retardée, double close, erreur, annulation et expiration de fermeture.
Le premier timeout reste distinct de cleanup_failed ; aucune nouvelle TLS dans
les cas non attestés. Les régressions historiques B6/B7 conservent explicitement
leur politique HA-60 pour isoler leurs contrats ; B8 exerce la politique réelle
de l’entrée avec son propre temps contrôlé.

Deux régressions supplémentaires confirment que le timeout réel de TX Pong
conserve 60 s, avec ou sans lecture en attente. Elles passent sans correctif
supplémentaire : ce cas n’atteste pas un timeout de l’acquisition en cours.

### Correction de revue : interruption de la gate post-open

La [demande MANAGER](https://github.com/Guillaume0385/ha-hoben-community/pull/182#issuecomment-6648937540)
exige une branche de perte explicitement terminale avant la fin des 10 s.
Précision de preuve : le vrai `V4Session.wait_lost` lève toujours son erreur
typée après notification ; cette exception interrompait déjà `await lost`,
sans atteindre `await sleeper`. Quatre tests HA avec perte à 3 s dans la gate
(EOF, CloseClient non auth, transport générique, auth) sont verts avant le
correctif : annulation immédiate du timer, cleanup de génération 2 à 3 s,
aucune lecture sur elle, nouvelle cadence 10/60 s selon cause, ou arrêt auth.

Deux tests RED démontrent en revanche l'attente restante si cet observateur
retourne normalement après une vraie perte synthétique, en violation de son
contrat. À 3 et 9,999 s, le superviseur attend alors encore le sleeper.
La correction de quatre lignes rend ce retour immédiatement terminal par
`HobenInternalError`. Le `finally` existant annule et réape les deux tâches ;
le superviseur nettoie la session, sans acquisition ni retry de cette erreur
interne. Les erreurs typées réelles continuent de se propager sans requalification.
Les six cas sont verts ensuite. Aucun contrat RX, framing ou transport modifié,
et aucune attribution à un comportement réel du serveur.

DataUpdated invalide seul reste sur la même session : silence glissant 30 s,
sonde unique, aucun délai de reconnexion B8 induit par ce seul message. Les tests
existants #160, frame_boundary B4, diagnostic B3/B5, annulation, H1/H2 et campagnes
restent des régressions. Aucun résultat hors ligne n’atteste un comportement
réel du serveur. Les résultats complets et quatre CI doivent être consignés au
HEAD exact de la PR, puis revue/fusion MANAGER uniquement.

V4 lecture seule ; TLS vérifié vers `myhoben.fr:465`. Aucun test réel, accès Hoben
ou HA résidentiel, dispatch/rerun, modification d’automatisation/workflow live,
commande poêle, écriture Modbus, secret/GUID, RX/header/payload brut, valeur
domestique ou exception libre publié. Aucun changement de main ni fusion DEV.
