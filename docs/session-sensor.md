# Capteur de session — #163 A2

[Consigne MANAGER A2](https://github.com/Guillaume0385/ha-hoben-community/issues/163#issuecomment-6549118277).
A1 est intégrée par PR #165. Cette étape ajoute un seul capteur enum de
diagnostic « Session », rattaché au même appareil. Son unique_id conserve le
suffixe `_session` ; le registre HA choisit l'entity_id selon le nom de
l'appareil et les collisions. Dans le test HA natif :
`sensor.hoben_stove_session`. Noms et quatre états traduits en français/anglais.
Le setup existant exige toujours une première acquisition validée avant de
charger les entités. Les lignes sans snapshot décrivent la projection interne
testée avant ce chargement ; aucun capteur prématuré n'est créé.

| Fait local observé | État du capteur |
| --- | --- |
| Avant acceptation stricte de la première session, aucun propriétaire utilisable | `disconnected`, même pendant la première ouverture TLS. Aucun snapshot ni fraîcheur inférés. |
| Session strictement acceptée et utilisable, sans reprise en cours | `connected`, y compris avant la première mesure et après réouverture sans nouvelle mesure. Cela ne prouve ni santé du serveur ni fraîcheur. |
| Rejet de modèle sur session utilisable, avec ou sans snapshot initial | `recovering` jusqu'à une acquisition modèle validée ou une fin de session. |
| DataUpdated ambigu déclenchant la récupération locale #160 | `recovering` pendant le silence glissant et la sonde. La sonde V4 validée permet `connected`, mais seule sa consommation/décodage par le coordinator avance le témoin d'acquisition. |
| Protocole/timeout récupérable nécessitant remplacement, ou perte transport/EOF suivie d'un retry | `reconnecting` dès l'état réel RECONNECTING du lifecycle : cleanup, backoff et réouverture inclus. Cet état a priorité sur la reprise d'acquisition. |
| Réouverture strictement acceptée | `connected` si le nouveau propriétaire est utilisable ; pas de nouvelle mesure implicite. |
| Refus permanent d'authentification, certificat refusé, échec terminal ou propriétaire inutilisable | `disconnected`. L'erreur reste distincte des valeurs maintenues par A1. |
| Annulation/arrêt | `disconnected` tant que l'entité est chargée. Unload retire l'entité, désabonne les signaux et annule le callback/horloge locale. |

`recovering` décrit une reprise d'acquisition observée, pas une garantie TLS.
`disconnected` est le choix conservateur si l'utilisabilité n'est pas prouvée.
Ces quatre états ne remplacent pas les règles de disponibilité A1 : les valeurs
conservées ne sont jamais republiées pour signaler un changement de session.

Les seuls attributs métier sont :

| Attribut | Preuve et type |
| --- | --- |
| `last_error_category`, `last_error_phase` | Chaînes issues de listes fermées ; catégorie/phase absente ou inconnue = `None`. Aucun texte d'exception, identifiant, transaction, registre ou RX. |
| `last_error_at` | Date UTC ISO de l'observation d'une erreur source ; les polls d'attente ne la réécrivent pas. `None` avant toute erreur observée. |
| `last_successful_read_at` | Date UTC ISO A1, après lecture corrélée, décodage et persistance réussis. Ce n'est pas une date du poêle. `None` avant la première acquisition validée. |
| `last_successful_read_age` | Entier, secondes depuis cette date, borné à zéro si l'horloge recule ; `None` sans date. Actualisé sur événement et par horloge HA locale de 60 s, sans requête réseau. |
| `reconnect_count` | Nombre de générations de session strictement acceptées après la première. Une tentative échouée et un poll ne comptent pas. Première génération = zéro ; génération manquante/incohérente = `None`. |
| `recovery_count` | Nombre d'entrées dans une reprise d'acquisition dégradée : protocole/timeout post-ouverture réessayable, DataUpdated ambigu ou rejet du modèle. Une même reprise répétée compte une fois ; réouverture acceptée, sonde réussie, acquisition modèle réussie ou fin de session terminent l'épisode. Une perte transport seule ne compte pas comme reprise d'acquisition. |

Les compteurs HA observent les événements dès la construction du client et
repartent à zéro lors d'un nouveau setup ; pas de restauration ni historique
serveur supposé. Pour un client non instrumenté, ils valent `None`.
Les attributs natifs HA (options, classe enum, nom) s'ajoutent à ces sept champs.

Les callbacks de session ne font que transporter des métadonnées fermées vers
une entité indépendante des listeners de mesure. Ils sont regroupés sur la
boucle HA ; aucun `async_set_updated_data`, nouveau poll réseau, changement de
retry/backoff, framing, décodage, disponibilité A1 ou contrat DataUpdated.
Un abonné défaillant ne peut pas interrompre le propriétaire ou son cleanup.

Tests déterministes sur vrais client/lifecycle/coordinator/registre/entité HA :
états pendant backoff sans poll, retour sans mesure, DataUpdated, erreur modèle,
absence de snapshot initial, compteurs d'événements, âge, erreurs permanentes,
annulation et absence de résurrection après unload ; régressions A1 conservées.
Transports et horloges synthétiques uniquement. **Tests réels NOT RUN** ; B/C/D
de #163, cause des incidents réels et validation de terrain restent distincts.
