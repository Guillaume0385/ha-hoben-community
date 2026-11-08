# #186-D4 — worker mémoire offline

Tâche `HOBEN-186-INFO-WORKER-OFFLINE-007`,
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/186#issuecomment-6713923452),
base `194a310a47c22ed92c87892cb2b24e42968c4d6a`.

`scripts/info_delivery_worker.py` relie le vrai `V4Session(PERSISTENT)` aux preuves
[C](info-delivery-scenario-offline-186.md) et au superviseur
[D2](info-delivery-supervisor-offline-186.md). Il conduit une **tâche asyncio en
mémoire**, pas un processus isolé ni une session TLS réelle. La fixture seule
construit la session, fournit l'identité synthétique, active sa capacité privée
et installe l'horloge virtuelle sur sa boucle isolée. Aucun fournisseur d'opt-in,
CLI ou point d'entrée réseau n'est ajouté.

## Ports et parcours synthétiques

Avant tout `connect`, le worker exige les types exacts V4Session persistant,
`MemoryFactory`, `MemoryTransport` et `OfflineClock`, une session vierge, un port
inutilisé et la même horloge virtuelle pour ses timers et ceux du vrai RX.
Une lambda usine réseau ou le transport TLS par défaut est refusé sans appel.
Le transport mémoire n'importe aucune primitive socket/TLS. Ses paramètres
permettent opening/réponses synthétiques, EOF/exception locale, retard ou échec de
fermeture. Ces objets Python ne constituent pas une frontière de sécurité contre
un programme qui les modifie ; aucune provenance authentifiée n'est revendiquée.

Un seul port est créé, une seule ouverture acceptée, un seul propriétaire RX.
Le worker attend une livraison candidate réellement rendue par `read` au RX ;
il observe le compteur de drop du vrai V4Session. Il exige ensuite Ping/Pong puis
émet **une** demande V4 neuve en lecture seule. Le compteur de lecture validée,
la corrélation réelle, l'identité du transport et celle de la tâche RX doivent
rester cohérents. Une lecture antérieure/non sollicitée, une valeur conservée,
une autre session ou une réponse à mauvaise transaction ne constituent pas une
acquisition post-drop.

Le transport enregistre seulement ordre/catégories/tailles ; ni paquet TX ni RX,
identité, valeur de registre ou exception libre n'entre dans le rapport. Ses
émissions autorisées sont l'ouverture initiale générée par la session, Pong et
le vecteur V4 fixe en lecture seule. Limites locales : file de 32 livraisons,
4096 octets par livraison, 256 réceptions/émissions, une demande V4, journal C de
128 événements, capacité de drop bornée en fixture. Ce sont des bornes de test,
pas des limites du serveur ni une preuve de taille/fréquence de messages.

## Temps et preuve en deux phases

Le temps global commence avant l'ouverture : observation au plus **3540 s**,
réserve de teardown **60 s**, total **3600 s**. Les temporisations sont entièrement
synthétiques ; le driver de fixture avance le temps, jamais une attente réelle
d'une heure. Les anciennes bornes des autres scénarios restent inchangées.

C garde sa fenêtre courte existante : elle commence à la première livraison
candidate, ou en fin d'observation si aucune candidate n'arrive. Les faits
connect/opening déjà observés sont reportés depuis le port mémoire, sans seconde
ouverture. Après une candidate, la preuve locale doit arriver avant 30 s ;
la demande V4 attend au plus 5 s et jamais au-delà de la fenêtre parent. Le
cleanup du vrai V4Session garde une limite plus stricte de **5 s**, à l'intérieur
de la réserve D2. Le port mémoire borne lui-même son close à 5 s, y compris
lorsque le chemin d'erreur du vrai RX/demande le ferme avant le teardown du
worker. Un rapport C déjà fermé sur erreur reste final et emprunte le chemin
D2 v1 ; il ne devient jamais une preuve provisoire ni un succès réparé.
Sans Info et avec fermeture attestée, le worker attend bien
3540 s avant de conclure INCONCLUSIVE. Une erreur ne devient jamais « Info absent ».

D2 v1 reste compatible. Le nouveau chemin v2 ajoute `pending_observation` et
l'événement `pending` :

1. Avant `abort`, figer les faits C dans un rapport provisoire
   FAILURE/cleanup_unproven. **Il n'atteste aucune fermeture** et n'est jamais
   publié comme succès. Sans Info, cette transition normale n'est admissible
   qu'à la frontière exacte de 3540 s.
2. Exécuter réellement le cleanup mémoire ; constater `cleanup_succeeded`, état
   CLOSED, fin RX et absence RX/TX/operations, ainsi qu'un seul close achevé.
3. Soumettre le rapport C final. Seuls temps et résultats de teardown peuvent
   évoluer ; ni nouvelle lecture ni remplacement de session ni effacement d'un
   incident ne sont permis. Le temps cleanup est lié aux événements parent
   (tolérance de troncature C : 1 ms).
4. Confirmer distinctement transport fermé et RX terminé. Le caller récupère le
   résultat terminal de **sa tâche enfant déjà terminée** avant `worker_reaped`.
   Tous les helpers Event/timer sont annulés et attendus.

Ces confirmations sont des faits du simulateur en mémoire, **pas** un waitpid,
une attestation de processus protégé ou une preuve de fermeture TLS distante.
Annulation répétée : première cause conservée, deadline non réarmée, une seule
annulation de l'enfant ; son cleanup borné reste protégé des annulations suivantes.
Échec/timeout/cleanup non prouvé => FAILURE ; aucune seconde connexion.
Le validateur v2 rejoue le journal fermé et lie les preuves provisoire/finale ;
un faux verdict, une chronologie modifiée ou une attestation omise est refusé.
Rapport total JSON borné à **8192 octets**.

## Limites et validation

SUCCESS signifie **uniquement simulation réussie** : livraison 0x0C abandonnée,
Ping/Pong, nouvelle lecture corrélée dans la même session, cleanup constaté et
tâche terminée. Une livraison peut amalgamer Info avec Ping/0E et tout perdre ;
un fragment ultérieur peut être indélimitable. Ces cas ne donnent aucun succès
sans preuve neuve. **Info framing INCONCLUSIVE**, **boundary_proven=false** ;
aucun sous-code, longueur totale Info, fingerprint ni règle serveur n'est inféré.

D1 accepte le rapport C final offline, mais refuse toujours toute publication
live (`info_live_provenance_not_proven`). D3 garde
`manual_info_route_not_connected`. Aucun gate, claim, workflow, launcher réel,
HA distribué, protocole ou politique B7/B8/DataUpdated n'est modifié.

Tests RED/GREEN : remise C provisoire/finale sur D2, véritable RX mémoire,
fragments et concaténations, corrélation, limites 3540/3600, erreurs, annulation,
cleanup échoué/tardif, faux rapports et confidentialité ; régressions A/B/C/D1/D2/D3
et suite HA existante. Le refus DNS/socket des tests ordinaires reste actif.
CHANGELOG non modifié : scripts et tests offline non raccordés, sans effet sur le
plugin distribué ni les lancements. Quatre CI exact-HEAD avant revue MANAGER.

**Tests réels NOT RUN. Lancement manuel NON PRÊT.** Le raccordement, l'isolation,
l'authentification du futur worker, la provenance et le plafond du workflow
restent à préparer par MANAGER dans une autre tâche. #192 demeure waiting,
cleanup S1/S2/V1–V6 non résolu. Aucune attribution automatique de tâche suivante,
fusion, commande poêle ou écriture Modbus.
