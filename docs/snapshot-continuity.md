# Continuité du dernier état HA — #163 A1

[Consigne MANAGER A1](https://github.com/Guillaume0385/ha-hoben-community/issues/163#issuecomment-6548638791).
Une disponibilité de valeur connue ne prouve ni une connexion TLS actuelle,
ni une nouvelle mesure. Aucun capteur de session A2 n'est ajouté ici.

Le défaut local est reproduit sur de vrais client/lifecycle/coordinator/entités
HA : réponse V4 rejetée, timeout ou échec de décodage après une acquisition
valide conservaient le snapshot mais publiaient unavailable. Trois régressions
rouges deviennent vertes : mêmes objets State HA pendant le maintien, donc
valeurs et last_changed/last_updated/last_reported inchangés, échec d'acquisition
toujours attesté par last_update_success=false et le diagnostic typé.

| Situation | Dernier snapshot / disponibilité |
| --- | --- |
| Protocole ou timeout récupérable, propriétaire HA encore en reprise | Dernières valeurs validées conservées et disponibles ; aucun faux succès ou rafraîchissement. Le remplacement local de la session rejetée ne suffit pas à les invalider. |
| Rejet du modèle V4, session utilisable | Même maintien ; le modèle rejeté n'est ni publié ni persisté comme acquisition réussie. |
| Récupération DataUpdated #160 | Même maintien ; silence RX glissant 30 s et sonde inchangés. Aucun registre DataUpdated ne devient une mesure. |
| Vraie perte transport/EOF/TLS, refus permanent, cleanup échoué | Le snapshot reste en mémoire mais ne donne plus de disponibilité : unavailable jusqu'à une nouvelle acquisition complète. Un maintien antérieur ne masque pas ces échecs ultérieurs. |
| Arrêt, unload ou annulation | Maintien terminé, propriétaire/tâches nettoyés ; aucune reconnexion tardive. |
| Aucun snapshot initial validé | Aucune valeur/disponibilité inventée ; setup et erreurs permanentes gardent leur politique existante. |

Les diagnostics existants distinguent snapshot_available (cache présent),
snapshot_held (maintien actuellement autorisé), last_update_success et last_error.
last_successful_read_at est un horodatage UTC **local** enregistré uniquement
après lecture V4, décodage et persistance d'identité réussis ; ce n'est pas une
date d'échantillonnage fournie par le poêle. last_successful_read_age est son âge
en secondes lors de la demande de diagnostic, borné à zéro si l'horloge UTC
recule. Il augmente pendant les échecs ; aucune date n'est réécrite pour rajeunir
les anciennes valeurs. Une lecture réellement réussie mais identique peut
avancer cet horodatage sans changer le State HA : always_update=false subsiste.
Le timestamp HA last_reported ne remplace donc pas ce témoin d'acquisition.

Le signal client acquisition_recovery_pending ne fait que projeter la catégorie
du propriétaire existant. Il permet de retirer le maintien si une ouverture
ultérieure échoue en transport ou définitivement ; aucun retry n'est ajouté.
Un poll avec un snapshot existant rend un échec d'attente plutôt que de rester
indéfiniment suspendu pendant les réouvertures. Le même lifecycle conserve son
backoff HA d'au moins 60 s et ses tentatives, sans replay de lecture. Le poll
normal de 60 s observe ensuite la disponibilité du propriétaire ; une ouverture
seule ne marque jamais une nouvelle mesure. Une perte survenue entre les polls
est reflétée au poll suivant ; les diagnostics peuvent déjà montrer que le
maintien n'est plus autorisé. Aucun nouveau superviseur de connexion n'est créé.

Tests unitaires et HA déterministes : continuité/âge/reprise, nouvelle panne
après maintien, EOF réel simulé, authentification/certificat, annulation/arrêt,
absence d'état initial, lecture identique et non-régression DataUpdated. Les
classifications et règles de setup permanentes ne sont pas élargies. Aucun
changement de parser, codec, contrat RX, workflow, commande ou registre écrit.
La cause des incidents réels #152/#160 reste non démontrée ; aucune exclusivité
MyHOBEN/HA inférée. **Tests réels NOT RUN** ; validation de terrain, capteur A2
et autres étapes de #163 restent distincts.
