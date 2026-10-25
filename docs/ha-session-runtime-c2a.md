# Étape 8 C2a — superviseur et preuve HA inactifs

Consigne : [première section MANAGER de #112](https://github.com/Guillaume0385/ha-hoben-community/issues/112#issuecomment-6395141200).
Base `d797f5c5b9fc3ceba4bf4970f08bf20ba9f5d474`, après A/B/C1.
La décision propriétaire du 25/10 supprime le plafond RX **pour hoben-live
seulement** : aucun compteur, proxy, quota ou test de quota RX dans C2a.
Les limites historiques H1/H2 et session-300 restent inchangées. Le schéma C1
reste un format offline historique, jamais une preuve d'exécution live.

## Une fondation entièrement hors ligne

`scripts/ha_session_supervisor.py` ne propose aucun CLI, chargement de secret ou
mode réseau. Il accepte uniquement des `OfflineCase` de fixtures connues.
Il refuse sans repli sur l'hôte si le daemon local, l'image préparée, cgroup v2,
mémoire/swap/PID ou leur configuration effective sont invérifiables.
Les conteneurs utilisent toujours **network=none**, sans variables héritées,
sans token GitHub/Actions, socket Docker montée ou workflow.

Le worker de fixtures construit les vraies classes HobenClient,
HobenDataUpdateCoordinator et HomeAssistant dans une instance isolée. Seul le
transport est synthétique, explicitement dans les fixtures ; aucune socket
Hoben réelle ni instance domestique. L'observer réutilisable
`scripts/ha_session_observer.py` appelle le vrai `coordinator.async_refresh()`
et projette seulement SessionObservation. Il n'accède pas au lifecycle privé,
ne modifie pas handshake, codec, stratégie de retry, TLS ou destination.
Le client persistant garde son budget de deux tentatives ; six refreshs fixes
à 0/50/100/150/200/250 s au plus. Le premier témoin termine la préparation et
ancre la fenêtre ; le lecteur persistant reste actif jusqu'à **300 s après ce
témoin**, sans septième refresh. Un réveil à 299,999 s impose une nouvelle attente.
Les tests accélèrent cette planification avec une horloge virtuelle explicitement
marquée `synthetic` ; ce n'est pas une observation réelle de 300 s.

Le témoin final précède le cleanup et conserve les pertes apparues après le
dernier refresh. `SessionObservation.active` est un booléen public sans I/O,
calculé par le propriétaire V4 : une fermeture protocolaire sans perte naturelle
ne doit pas passer pour une session encore active. Aucun codec, retry, lecteur
ou flux HA n'est modifié ; le projecteur et le format C1 restent inchangés.

## Ressources et arrêt

| Ressource | Contrôle effectif |
| --- | --- |
| Mémoire | cgroup `memory.max` <=1 Gio pour gardien, HA, threads et descendants ; swap désactivé |
| Processus/threads | cgroup `pids.max` <=128, sans possibilité de migration pour le worker |
| Fenêtre utile | 300 s monotones nécessaires à completed ; horloge accélérée distinguée |
| Exécution/nettoyage | échéance absolue <=360 s armée sur l'hôte avant start, transmise au gardien sans reset |
| Rapport | JSON canonique <=8192 octets ; aucune publication C2a |

La préparation de l'image et du conteneur **arrêté, sans secret** précède
l'exécution bornée. L'échéance est armée avant le start, incluant le démarrage
du gardien et du worker. Les tests peuvent resserrer les plafonds, jamais les
augmenter. L'observer borne aussi ses attentes et appelle async_close.
La préparation et la collecte disposent ensemble de 330 s au plus, le cleanup
HA de 10 s ; le gardien accepte le reçu après 300 s et arrête l'attente worker
au plus tard à T+340 s nominal. Les 20 s restants couvrent terminaison, reaping et
contrôle externe, toujours sur l'échéance originale T+360 s. Si le démarrage
consomme cette marge, la collecte échoue ; aucun timer n'est réarmé.
À l'arrêt externe, SIGTERM donne une chance bornée au cleanup HA, puis SIGKILL
arrête le groupe du worker. La sortie de PID 1 termine aussi les descendants
qui ont créé leur propre session Unix. Une marge reste réservée au kill/reaping.

Le gardien vérifie les vrais compteurs cgroup avant le lancement du worker,
qui tourne sous UID/GID 65534, sans groupes supplémentaires ni capacités,
avec no-new-privileges et un cgroup non modifiable. Le gardien conserve seulement
SETUID/SETGID/KILL ; racine et code sont en lecture seule. Un snapshot de fichiers
publics allowlistés est préparé séparément : aucune permission du checkout n'est
relâchée, aucun .git ou fichier privé monté. Les données HA temporaires sont en
tmpfs, dans la même enveloppe mémoire.

Le worker n'exporte pas stdout/stderr. Le gardien écrit atomiquement un reçu
borné et expurgé, le contrôleur le copie puis acquitte sa libération. Le reçu
ne devient une preuve de reaping qu'après confirmation externe de la fin du
namespace et suppression du conteneur/volume. OOM, limite de PID, timeout et
annulation sont des arrêts **locaux** ; ils ne valident jamais une reconnexion.

Si le canal de contrôle disparaît, le gardien conserve l'échéance originale et
termine le namespace ; le contrôleur refuse toute preuve de cleanup non attestée.
Un conteneur arrêté et son reçu anonymisé peuvent nécessiter une suppression
après rétablissement du daemon. Ce cas est une FAILURE de supervision, jamais
une livraison réussie ; aucun secret n'est stocké dans le volume de reçu C2a.

## Dépendances et tests

L'image de test utilise un Python 3.14-slim fixé par digest, Home Assistant
2026.9.4 et toutes les versions transitives figées dans
`scripts/ha_session_runtime/requirements.txt`. Le Dockerfile ne reçoit aucun
identifiant Hoben. Le bundle CA public est un montage de build temporaire ;
la vérification TLS de pip reste activée. Préparer cette image est une étape
distincte des expériences : tous les tests en conteneur sont sans réseau.

Les tests pytest préparent l'image via le daemon local si ses capacités sont
présentes. Sans backend, les cas positifs sandbox sont explicitement SKIPPED et
les refus NOT RUN sont testés avec doubles ; un skip n'atteste aucun backend.
Le garde réseau de ces tests autorise seulement le socket Unix Docker fixe,
en conservant l'interdiction DNS/TCP et des autres sockets Unix.
Les tests HA natifs restent indépendants de Docker.

## Rapport distinct, aucune admission

Schéma **2**, scénario `ha-persistent-live`, mais **execution=offline** et
**admission=NOT RUN** obligatoires en C2a ; `boundary_proven=false`.
Provenance fournie par les fixtures, sans vérification GitHub.
Le reçu porte les plafonds effectifs, l'état démarré/attesté, le motif local,
OOM/PID et le reaping. Les critères et l'issue globale sont recalculés par Python
et par un validateur Node indépendant. Les seules aides partagées avec C1 sont
la validation des témoins, pas les budgets ou les schémas.

Les six samples portent des temps relatifs monotones. `window` porte le type
d'horloge, la durée écoulée et le témoin final actif/perte. Python et Node refusent
completed à 250 s ou 299,999 s, un témoin régressif et une durée monotone supérieure
au reçu externe. `continuous_300s` exige six lectures décodées, la même génération
sans perte et un témoin final actif à la borne. Une perte tardive ou un arrêt
protocolaire rend ce critère FAILURE, même si une reconnexion antérieure reste
prouvée ; collection, continuité, reconnexion et cleanup sont des critères distincts.
Une annulation de cleanup conserve le témoin de fenêtre, sans succès global.

Deux lectures décodées/corrélées de même génération prouvent la réutilisation.
Une perte observée, cleanup, nouvelle génération et nouvelle lecture corrélée
sont nécessaires à la reconnexion ; sans perte : INCONCLUSIVE. CloseClient
reste distinct de transport, avec seul UInt8 numérique ; transport n'affirme
aucun EOF. Une absence de démarrage/rapport attesté reste NOT RUN ; une défaillance
de supervision a une issue globale FAILURE même sans résultat protocolaire.

C2b devra être attribuée séparément : véritable mode live, preuve UI, admission
propriétaire/ref/SHA/PR/revue/CI, politique hoben-live et approbations, anti-rejeu,
mutex, recheck et publication isolée. Modifier un discriminant C1/C2a ne crée
aucune preuve live recevable. Aucun workflow ou gate n'est raccordé dans C2a.
