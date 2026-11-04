# #163/B4 — reprise après un rejet de frontière classifié

[Consigne MANAGER #6627763874](https://github.com/Guillaume0385/ha-hoben-community/issues/163#issuecomment-6627763874),
autorisation propriétaire du 04/11/2026. Base experimental
`b8186138a326bf88296ee49e56ebef09f2d98833`, après fusion #173/032.
Développement et preuves **hors ligne seulement** ; tests réels **NOT RUN**.

## Classification et origine

`HobenFrameBoundaryError` reste dans la catégorie publique `malformed_response`,
avec phase `frame_boundary` et champ fermé `frame_boundary_provenance`. Seuls
les rejets explicites du framer opt-in HA produisent ce type et mémorisent
l'objet exact comme incident courant. La session vérifie l'identité entre
sa faute RX et celle de son propre framer. Le lifecycle exige ce témoin, le
type exact, une ouverture acceptée et sa politique HA ; le texte de phase
ou un objet d'erreur injecté depuis un autre composant ne suffit pas.

| Provenance | Observation locale | Traitement |
| --- | --- | --- |
| `unknown_type` | Discriminant sans contrat de framing | Rejet et nouvelle session ; aucun saut d'octets |
| `unsupported_type` | Type connu non admis après ouverture | Même rejet ; aucune longueur ou signification de payload inférée |
| `invalid_mbap` | Validation normative du header MBAP refusée | Même rejet ; aucun décodage de corps invalide |
| `partial_eof` | EOF transport réellement observé pendant un message partiel | Même reprise ; signal de perte transport distinct du rejet local |

La classification est désactivée par défaut et sélectionnée par le superviseur
HA pour ses sessions persistantes. Les campagnes/config-flow et leurs budgets
finis conservent leurs classes et leur politique historiques. Aucune nouvelle
règle de framing ni longueur de message n'est inventée : OpenedClient reste un
préfixe de 48 octets, jamais un total universel ; un discriminant inconnu ou
un CloseClient sans sous-code ne deviennent pas des messages complets.

Une exception Python dans `feed`, le validateur MBAP ou un autre composant reste
une erreur interne permanente, même annotée `frame_boundary`. Les violations
du contrat local de livraison, de rétention du suffixe ou du résultat du codec
ne sont pas requalifiées en données serveur. Aucune inspection de texte,
cause, traceback ou pile d'exception n'intervient dans la décision de retry.

## Propriétaire, arrêt et délais

Le même lifecycle ferme/abandonne la génération N, attend son RX, ses TX,
opérations et waiters, vérifie `cleanup_succeeded`, puis utilise son backoff
HA existant de **60 s**. Aucune ouverture N+1 n'est possible à 59 s. Une seule
nouvelle session TLS/V4 est créée par tentative. Les tentatives continuent tant
que l'intégration est active, sans recréer le client ni remettre un compteur à
zéro. Une ouverture injoignable conserve les attentes de 60 s ; seule une
acceptation réelle incrémente `reconnect_count`, jamais un poll ou une tentative.

Un close annulé/échoué/non attesté, un refus d'identité/autorisation/certificat,
un arrêt/unload ou une erreur interne indépendante interdisent la reprise.
Les marqueurs d'autorisation 2F/30 après ouverture restent également terminaux ;
aucune soumission de code ou association n'est déclenchée.
La correction #171 reste inchangée : attendre le close original suspendu,
ne jamais substituer une seconde fermeture idempotente pour attester un succès.
Le reload natif termine l'ancien propriétaire avant d'en créer un autre.
Il n'existe ni lecteur concurrent sur l'ancienne socket, ni resynchronisation
par scan, ni replay de lecture perdue ou de commande.

## Snapshot, disponibilité et télémétrie

A1 garde le snapshot validé et sa date d'acquisition jusqu'à une vraie nouvelle
lecture corrélée/décodée. Un rejet local pendant une acquisition conserve son
maintien A1 existant ; une perte idle suivie d'un poll de reconnexion n'invente
pas un maintien préalable. Une ouverture seule ne rafraîchit aucune mesure.
Un EOF partiel réellement reçu est aussi enregistré comme perte transport :
il retire le maintien même s'il suit un rejet local déjà maintenu, y compris
si la nouvelle génération n'a encore fourni aucune acquisition.

A2 suit les événements du même propriétaire. `reconnect_count` compte les
nouvelles générations acceptées ; les épisodes d'acquisition dégradée restent
distincts des pertes transport. Les diagnostics B1/B3 et le rapport HA ne
publient que catégories, phase/provenance fermées et tailles prouvées. Les
octets reçus, GUID, registres, données domestiques, exceptions libres et
tracebacks ne sont jamais publiés. Un sous-code CloseClient requiert toujours
le message complet sous son hypothèse post-open ; `partial_eof` ne le devine pas.

DataUpdated de longueur invalide conserve **strictement #160** : suspension du
parseur, silence glissant de 30 s, une sonde V4 et aucun close TLS provoqué par
cette seule anomalie. La preuve de rejet est effacée lorsque le framer est
réinitialisé pour cette récupération ; elle ne peut pas être réutilisée.

## Preuves et limites

Le test HA des trois frontières utilise un seul vrai client/coordinator,
lifecycle et capteur A2, des transports synthétiques et le vrai timer asyncio
avancé par l'horloge de test. Types non admis, MBAP invalide puis EOF partiel :
trois nettoyages, attentes de 60 s, générations 2/3/4 et lectures V4 corrélées,
sans épuisement au-delà des deux ouvertures historiques. Le close suspend deux
fois pour couvrir la course #171. Snapshot/date/âge, disponibilité et compteurs
sont contrôlés sans publier les valeurs synthétiques.

Les refus couvrent aussi erreur interne générique, phase seule, type forgé hors
framer, contrat de livraison/codec, cleanup annulé ou non attesté, auth, setup,
unload/reload, service durablement injoignable, DataUpdated 30 s, fragmentation,
concaténation et préfixes incomplets. Les suites historiques restent requises.

La preuve C1 [#6556538691](https://github.com/Guillaume0385/ha-hoben-community/issues/163#issuecomment-6556538691)
reste valide pour son troisième cas : une exception Python arbitraire dans RX
demeure fatale et ne devient pas transitoire par sa phase. B4 distingue ces
exceptions des rejets classifiés ; elle ne prétend pas résoudre une cause
interne inconnue ni attribuer les incidents HA historiques à un commit ou au
serveur. B2, réévaluation C1 et observation passive D relèvent des tâches
suivantes du MANAGER. Aucun déploiement, accès HA résidentiel, test live,
dispatch/rerun, changement d'automatisation ou fusion par CODEX DEV.
