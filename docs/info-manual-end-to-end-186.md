# #186-D7 — observation passive, préparation hors ligne

Tâche `HOBEN-186-INFO-MANUAL-END-TO-END-010`, base experimental
`4fdcf03a9dc266858f14a1eb5e751df6a50bcbc7`.
[Consigne et décision propriétaire prioritaire du 09/11/2026](https://github.com/Guillaume0385/ha-hoben-community/issues/186#issuecomment-6713923452).
**NOT RUN : aucun essai Hoben/HA, dispatch ou approbation effectué par DEV.**
Cette PR exige revue MANAGER et quatre checks au HEAD exact avant toute fusion.
La publication du changement d'assertion historique dans
`tests/test_ha_manual_live.py` reste refusée : ne pas contourner ce contrôle,
déplacer les fixtures, désactiver le test ou annoncer READY en cachant son échec.
MANAGER doit résoudre légalement ce blocage distinct sur cette même PR.

## Observation sans longueur supposée

La décision du 09/11 permet l'observation sans connaître la fin de Info.
[RE APK34 épinglée](https://github.com/Guillaume0385/MyHOBEN_extract/blob/e2f88b0dfcd130b9b9f9e52d69a900d8ded48b6e/analysis/receive_boundary_contract_apk34.md),
[démonstration A](tls-read-candidate-offline-186.md),
[prototype B](info-delivery-drop-experiment-186.md) et
[ports D6](info-delivery-tls-adapter-offline-186.md) restent applicables.
ReadAsync fournit un bloc plaintext TLS, jamais une frontière applicative.
Aucun sous-code, longueur totale, scan de suffixe ou saut de deux octets.

Le worker dédié utilise une seule instance réelle de V4Session PERSISTENT et
les ports D6. Son transport dérivé appelle le vrai AsyncTlsTransport, vérifie
certificat, hostname myhoben.fr:465 et SSLObject effectif. La capacité privée B
n'est fournie que dans ce worker, jamais dans l'intégration HA distribuée.
Le discriminateur est observé uniquement au début d'un retour effectif de
transport.read par le propriétaire RX, après ouverture acceptée, framer vide,
sans tail ni quarantaine DataUpdated. Le préfixe OpenedClient reste un préfixe,
aucun total de 48 octets n'est supposé. Un suffixe d'ouverture n'est pas observé
comme une nouvelle livraison.

La politique fermée `passive_candidate_stop` compte un candidat opaque 0x0C et
sa taille de livraison, abandonne cette livraison entière via B, puis parque
les lectures suivantes jusqu'au cleanup. Elle ne force **aucune** lecture V4
post-candidat : aucune reprise d'un parseur désynchronisé. Fragments et blocs
coalescés peuvent contenir d'autres messages perdus ; ils ne prouvent pas Info
complet. Une absence de candidat ne prouve pas une absence globale de Info.
Les Ping/Pong natifs avant candidat et la sonde DataUpdated native restent
inchangés. Aucun superviseur de reconnexion, seconde session ou commande.

| Observation attestée | Verdict scientifique |
| --- | --- |
| Aucun candidat pendant toute la fenêtre, cleanup et réapage attestés | INCONCLUSIVE / candidate_absent |
| Candidat observé et abandonné, cleanup et réapage attestés | INCONCLUSIVE / candidate_observed_continuation_not_proven |
| Erreur, délai global dépassé, cleanup ou provenance incertaine | FAILURE |
| Refus prouvé avant lancement du processus | NOT RUN |

Cette stratégie ne produit jamais SUCCESS. Une future continuation démontrée
sûre avec acquisition V4 fraîche corrélée dans la même session pourrait le
permettre, sans prouver la frontière Info ; cette PR ne fabrique pas cette preuve.
`info_framing=INCONCLUSIVE` et `boundary_proven=false` sont obligatoires.

## Identité initiale — tâche #186-011

La nouvelle voie Info injecte uniquement le secret `HOBEN_USER_GUID` dans
`collect-info`, après le recheck GitHub et sa permission à usage unique.
Le lanceur utilise `normalize_user_guid` et l'existant `INITIAL_DEVICE_GUID`,
identique à la première ouverture des campagnes protocol et HA, sans valeur
nouvelle ni second secret. `V4Session` n'adopte une identité attribuée par le
serveur qu'après validation d'un `OpenedClient` V4 ; une demande d'association
`DeviceAuthReq` échoue sans réponse d'autorisation automatique.
Une identité utilisateur absente ou invalide est `NOT RUN` avant tout processus
ou connexion. Aucune valeur d'identité, trame RX ni donnée domestique
n'entre dans le rapport public ; le guardian et les preuves de cleanup restent
inchangés.

## Admission et provenance distinctes des fixtures

Le choix existant hoben-live de Tests Hoben manuels est réaffecté uniquement à
Info. Il n'est pas ajouté à all. Le workflow HA dédié demeure byte-identique.
Les autres scénarios, budgets, gates et collect 50 minutes restent intacts.
Info utilise collect-info, publish-info et result-info ; environment
hoben-experimental obligatoire, collect 75 minutes pour marge Actions.

Le gate conserve propriétaire/sender/triggering_actor, ref experimental et HEAD
protégé courant, PR fusionnée/arbre candidat/revue/four CI avant dispatch,
absence de concurrence, tentative 1, claim atomique anti-rejeu et mutex
hoben-read-only-observation. Selon la décision propriétaire postérieure à D7,
aucun approbateur indépendant additionnel n'est requis quand la configuration
GitHub de l'environnement n'en comporte pas. Une approbation réelle indépendante
fraîche reste obligatoire si `required_reviewers` est effectivement configuré,
et les preuves sont recontrôlées après l'accès à l'environnement. L'environnement
est vérifié, jamais créé, approuvé ou affaibli par ce code. La route n'est
connectée qu'après vérification du câblage et du manifeste fermé SHA256 des
sources au même SHA via API. Une empreinte ou valeur ready ne prouve pas une
exécution : ces contrôles précèdent toujours les témoins physiques.

Après admission effective par l'environnement (et approbation si exigée), un
nouveau recheck complet réserve le tag de lancement
`hoben-info-start-<run>-attempt1` et une permission locale privée à nonce aléatoire
à usage unique. Le launcher relit HEAD, tag exact et horodatage de moins de
120 secondes, run/étape de collecte réellement en cours, double checkout et
empreintes. Il consomme la permission **avant** lecture des identités. Les
secrets Hoben n'existent que dans cette étape ; le token d'admission ne passe
jamais au worker. Aucun argument libre de commande, hôte, chemin ou durée.

Le parent lance un guardian fixe dans une nouvelle session OS, puis vérifie
SID/PGID réels avant transmission des seules identités par pipe privé. Le
worker appartient à ce groupe, sans token Actions, stdout/stderr publiable ou
CLI de fixture. Nonce privé, objets fermés et pipes à propriétaires uniques
lient le rapport au processus réellement lancé. Le guardian est subreaper ;
il vérifie l'absence de descendants adoptés et réape effectivement chaque enfant.
L'absence d'un mécanisme noyau requis refuse le lancement, sans attestation fictive.

Le transport atteste la fermeture par le Future original du protocole asyncio,
pas par abort/is_closing seuls. Le rapport exige aussi RX terminé, opérations
RX/TX arrêtées, V4Session CLOSED et cleanup_succeeded. Première cause et erreur
cleanup restent séparées. #192 demeure non résolu en conditions réelles : un
cleanup réel incertain donnera FAILURE et aucune seconde connexion.

Une clé éphémère de scellement est créée seulement **après** réapage physique,
fermeture des pipes et groupe vide (ou absence prouvée de lancement). Le
collecteur vérifie HMAC, rapport fermé, gate/politique et approbation si requise,
ainsi que les étapes
GitHub réellement achevées avant de réserver un reçu immuable lié au SHA256 du
rapport. Publish et result, runners distincts sans secrets Hoben, relisent ces
preuves via API et refusent toute substitution. La clé privée est supprimée.
Le modèle de confiance est le runner GitHub protégé et le code revu, pas une
attestation matérielle ni une résistance à un administrateur compromis.
D1 refuse toujours inconditionnellement la publication de son contrat offline.
Les JSON synthétiques D1–D6 ne sont jamais convertis en rapports live.

## Temps, arrêt et confidentialité

Origine monotone fixée avant lancement OS, après admission locale, jamais
réarmée : observation jusqu'à T+3540 s, réserve cleanup 60 s, plafond absolu
T+3600 s. L'ouverture et le démarrage du processus consomment ce budget.
Sans candidat, attendre la fenêtre entière ; un candidat permet cleanup immédiat.
Le guardian possède son échéance indépendante, demande arrêt normal, puis
SIGTERM et SIGKILL si nécessaire, attend wait/reap et contrôle les descendants,
y compris ceux ayant changé de groupe. Annulations répétées ne réarment rien.
Une terminaison forcée n'est jamais un succès. La durée publique est confrontée
aux timestamps de l'étape GitHub (tolérance de précision 2 s et bootstrap 120 s,
sans prolonger le budget du worker).

Schéma fermé <=8192 octets : compteurs bornés, tailles de livraisons, temps,
états catégoriels et identifiants publics de provenance. Jamais GUID, RX,
payload/header, valeur domestique, PID, chemin, stdout/stderr ou exception libre.
Sans rapport enfant lié, les zéros initiaux ne sont pas une preuve d'absence de
connexion ; le résumé indique observation non attestée et FAILURE.
Une publication technique réussie avec INCONCLUSIVE reste explicitement
INCONCLUSIVE, jamais validation fonctionnelle ou validation de release.

## Validation et lancement futur

Les tests exécutent le vrai chemin session/transport avec TLS MemoryBIO vérifié
et horloge simulée, sans socket ni serveur Hoben. Certificat éphémère local,
identités de fixtures existantes, aucune identité domestique. Les tests OS courts
exécutent uniquement des processus bénins à durées bornées : TERM ignoré,
enfants adoptés, changement de groupe, annulation, nonce falsifié et réapage.
Les tests GitHub simulent API, approbations, claims, provenance, reçus et rapports
altérés ; aucun dispatch réel. Les régressions A–D6 et HA restent hors ligne.

Après résolution du contrôle de publication, revue sécurité MANAGER, quatre CI
SUCCESS au HEAD exact et fusion, MANAGER pourra déclarer
READY FOR MANUAL DISPATCH — NOT RUN. Seul le propriétaire déclenche alors
personnellement workflow_dispatch. Il peut utiliser ses réglages usuels sur
son interface, sans causalité prouvée avec Info, sans réglage installateur,
fabricant ou sécurité demandé ; aucun réglage via le plugin. DEV ne lance,
n'approuve, ne rerun et ne programme aucune campagne.
