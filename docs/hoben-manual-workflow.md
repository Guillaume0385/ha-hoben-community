# Tests Hoben manuels — #119, phase 2 experimental

**#186-D8 — continuation opaque actuelle, NOT RUN.** Après un candidat 0x0C,
le même propriétaire TLS continue de comptabiliser les livraisons plaintext et
leurs tailles sans les remettre au framer V4. Les seules sondes actives sont
les lectures V4 fixes toutes les 30 s, sérialisées et sans timeout de silence
déconnectant le client. Les réponses post-Info ne sont pas corrélables avec
certitude : aucune minuterie de récupération 300 s n'est déclenchée sur la
simple ressemblance d'un octet 0x0E. Verdict conservateur INCONCLUSIVE,
Info framing INCONCLUSIVE, boundary_proven=false ; véritable EOF distinct,
cleanup attesté et plafonds 3540+60=3600 s inchangés. La version D8 n'a
**pas** été exécutée sur un Hoben réel par DEV/CI. Les paragraphes D7
ci-dessous décrivent le comportement historique remplacé pour cette seule
route. [Contrat D8](info-manual-end-to-end-186.md).

**#186-D7 : préparation hors ligne, NOT RUN.** Le choix existant hoben-live est
réaffecté à l'observation passive Info sous hoben-experimental ; l'ancien chemin
HA est retiré de ce workflow. Le workflow HA dédié et les autres choix/all ne
changent pas. Un candidat opaque peut être observé sans connaître sa longueur :
ce worker arrête ensuite les lectures et conclut INCONCLUSIVE après nettoyage,
sans forcer une nouvelle acquisition. Aucun essai exécuté. Revue MANAGER,
résolution du contrôle de publication et quatre CI requis avant tout READY.
[Architecture et limites](info-manual-end-to-end-186.md).
[Consigne canonique #186](https://github.com/Guillaume0385/ha-hoben-community/issues/186#issuecomment-6713923452).

La phase 1 a installé le bouton sur la branche par défaut `main` (PR #120,
`b0c177d8146d4891d366a39e1fb0cd1dba86126c`). Cette phase 2 reporte le même chemin
`.github/workflows/hoben-manual.yml` sur `experimental` et raccorde les collecteurs
existants. `main` conserve son point d'entrée sans runtime et reste inactive.
Aucun protocole n'est promu vers main. La [tranche C2b](ha-session-live-c2b.md)
avait ajouté le choix HA hoben-live après autorisation du 26/10 ; cette route du
workflow manuel n'est plus admissible depuis D3. Le workflow HA dédié est inchangé.

## Identité du scénario Info — secret unique #186-011

Seul `HOBEN_USER_GUID` est injecté dans l'étape protégée `collect-info`.
Le lanceur le valide et le normalise avec `normalize_user_guid`, puis utilise
`INITIAL_DEVICE_GUID` du codec partagé comme DeviceGuid initial ; aucun
second secret `HOBEN_DEVICE_GUID` n'est requis pour Info. Après un vrai
`OpenedClient` V4 accepté, `V4Session` peut adopter en mémoire le DeviceGuid
retourné. Toute demande d'autorisation/association provoque un refus fermé :
pas de code d'association, aucune commande ni écriture Modbus.
Sans UserGuid valide, rapport `NOT RUN` avec erreur publique `identity`,
aucune ouverture TLS. Le secret, le DeviceGuid et les octets reçus restent privés.
Aucune modification des campagnes historiques, du workflow HA dédié, de
l'admission GitHub, de la supervision, des plafonds ou de l'anti-rejeu.

## Parcours prévu après un éventuel READY MANAGER, pas de lancement maintenant

Dans **Actions → Tests Hoben manuels → Run workflow** :

1. Choisir **experimental** dans le sélecteur natif **Use workflow from**.
2. Choisir `h1h2`, `session-300`, `session-reconnect`, `all` ou `hoben-live`.
   `all` conserve les trois anciens scénarios ; hoben-live reste séparé et
   utilise la route Info distincte, jamais la campagne HA dédiée.
3. Déclencher explicitement le workflow en tant que propriétaire autorisé.
4. Attendre les approbations d'environnement effectivement requises. PENDING
   APPROVAL ne permet aucune collecte et ne doit jamais être contourné.
5. Lire le résultat distinct de chaque scénario et le rapport anonymisé.

Le fichier doit exister au même chemin sur le ref sélectionné. GitHub utilise
le ref/SHA choisi ; le workflow ne remplace pas une sélection main par un checkout
experimental. La branche main reste visible dans le sélecteur et refuse le live.
Aucun lancement sur push, PR, merge, label ou schedule ; les quatre checks CI
ordinaires restent hors ligne. DEV ne clique pas Run workflow et ne lance aucun
rerun réel. Pour répéter une observation, le propriétaire crée un **nouveau
dispatch**, jamais Re-run all jobs / failed jobs.

## Gate technique, sans commentaire d'admission MANAGER

Le dispatch manuel du propriétaire remplace l'ancien commentaire pré-fusion.
Le gate ne lit aucune décision d'admission dans les commentaires GitHub.
Il vérifie, avant claim puis à nouveau après l'attente d'environnement :

- dépôt/identifiants GitHub exacts, acteur/sender/triggering_actor propriétaire,
  `workflow_dispatch`, tentative 1, inputs fermés et scénario connu ;
- ref exact experimental, SHA du workflow et Actions, HEAD courant protégé,
  provenance API du run ; aucun choix de script, destination ou durée libre ;
- PR unique fusionnée sur ce SHA par le propriétaire, arbre candidat identique,
  absence de CHANGES_REQUESTED actif et de thread non résolu ;
- Validate PR du HEAD candidat exact, branche/dépôt/workflow concordants,
  tentative 1, quatre jobs tests/ha-tests/hacs/hassfest réussis avant le dispatch ;
- politique effective hoben-experimental : branche experimental seule, règles
  reconnues ; reviewers indépendants et approbation réelle fraîche si configurés.

La réservation atomique `hoben-manual-<run_id>-attempt1` lie sélection, SHA,
PR/candidat/CI et empreinte d'environnement. Elle reste consommée après échec
ou annulation. Le recheck relit le claim exact et les preuves ; une politique
modifiée, API inaccessible ou approbation non vérifiable donne NOT RUN.
Les approbations configurées doivent dater au moins du début du dispatch courant.
Aucun secret Hoben avant le recheck. Le mutex hoben-read-only-observation conserve
sa file sans annulation ; les anciens runs sont aussi recherchés avant collecte.
Ce scan API n'est pas un verrou atomique pour une ancienne voie hors mutex :
le propriétaire doit contrôler les runs historiques avant une campagne.

Un refus au préflight est signalé exclusivement par `phase=<categorie>`.
Les catégories publiques fermées sont `provenance`, `merged_pr`, `ci`, `review`,
`environment_policy`, `environment_api`, `environment_approval`,
`concurrent_run`, `claim` et `route_contract`. Une erreur non classifiable
devient `unknown` et reste refusée. Aucun détail d'exception, contenu de réponse
GitHub, identité privée ou donnée Hoben ne doit être publié. Les anciens runs
ayant seulement affiché le refus générique ne peuvent pas être recatégorisés
rétroactivement : vérifier la politique effective avant tout nouvel essai.

Pour `hoben-live`, la décision propriétaire postérieure à D7 demande un
déclenchement manuel sans approbateur indépendant **s'il n'en existe pas dans
la politique GitHub réelle**. Contrairement à l'exigence D7 initiale, le code
n'impose donc plus une règle `required_reviewers` supplémentaire. Les mêmes
preuves techniques, vérifications de la politique `hoben-experimental`, branche
`experimental` unique, mutex, CI/revue/claim et recheck restent obligatoires.
Si GitHub configure effectivement des approbateurs, l'approbation indépendante
fraîche est toujours obligatoire et vérifiée après le contrôle d'environnement ;
aucun chemin parallèle ou bypass n'est autorisé. API de politique inaccessible
ou preuve partielle : `NOT RUN`.
Ensuite le manifeste fermé de sources et le câblage Info sont vérifiés au SHA
exact ; une route incomplète garde manual_info_route_not_connected. Une route
connectée n'est pas une preuve d'exécution. Le recheck après approbation réserve
une permission à usage unique, relue via GitHub avant identités par le launcher.
Un reçu public authentifié n'est produit qu'après cleanup et réapage attestés.
Le rapport offline D1 demeure refusé pour toute publication live. Les détails,
preuves physiques, limites de confiance et refus se trouvent dans le rapport D7.
Les claims et rechecks des autres sélections restent intacts.
Une approbation sur l'ancien environnement ne vaut jamais approbation sur
hoben-experimental. Le dispatch demeure réservé au propriétaire.

Ce refus sur le nouveau code ne révoque pas une exécution déjà engagée depuis
un ancien SHA ; il ne prouve aucune absence de connexion passée.

## Scénarios et budgets conservés

| Sélection | Collecteur et limite externe |
| --- | --- |
| h1h2 | Même campagne H1/H2 : six sessions par hypothèse, 90 s et 1 Mio RX par session ; processus 1800 s. |
| session-300 | Même observe(), 300 s utiles, processus 360 s, trois ouvertures, six lectures fixes et 1 Mio RX. |
| session-reconnect | Même collecteur borné de reconnexion : processus 600 s, fonctionnel au plus 360 s, dix lectures, trois ouvertures, 1 Mio RX. |
| hoben-live | Info #186 : observation passive 3540 s et réserve cleanup 60 s, plafond worker 3600 s ; collect-info 75 min. NOT RUN avant revue/fusion/CI et dispatch propriétaire. |
| all | H1/H2 puis suite existante session-300 → reconnexion ; plafond des deux sessions 1020 s, total processus 1800+1020=2820 s. |

Le superviseur parent possède un seul groupe isolé. Chaque transition fixe doit
être reconnue et acquittée après armement du délai, sans prolonger le précédent.
Une seconde est réservée à SIGKILL/reaping ; groupe entier arrêté à expiration,
annulation et sortie normale, captures privées H1/H2 supprimées avant export.
Aucun stdout/stderr candidat, token GitHub/Actions/OIDC, hook Python, fichier de
commandes Actions ou dépendance libre transmis au collecteur.

`all` poursuit après une campagne H1/H2 entièrement collectée et validée, dont
le résultat scientifique reste INCONCLUSIVE. Une campagne interrompue bloque
les sessions suivantes. Le premier scénario session doit être admissible avant
la reconnexion, selon le moteur existant ; sinon la reconnexion reste NOT RUN.
La sélection autonome session-reconnect utilise le même collecteur et ses
critères, sans fabriquer un premier scénario réussi.

## Résultats et confidentialité

SUCCESS signifie une session fonctionnelle vérifiée ; FAILURE une interruption,
un processus ou un nettoyage en échec ; INCONCLUSIVE une observation non concluante ;
NOT RUN un scénario non sélectionné, non commencé ou dont le démarrage n'est
pas attesté par un rapport validé. Sans rapport vérifiable après un échec ou une
annulation de capture, les scénarios restent NOT RUN et le résultat global est
explicitement FAILURE. Ce statut ne prouve aucune absence de connexion.
L'échec ou l'annulation d'un job ne transforme jamais les étapes sélectionnées
en observations INCONCLUSIVE ; seuls les résultats validés font foi.
H1/H2 reste INCONCLUSIVE même quand la collecte se termine correctement : cela
ne démontre jamais une frontière OpenedClient. Le workflow peut terminer sa collecte
avec ce résultat scientifique, tandis que les sessions exigent leur vrai SUCCESS.

Les projections Python et lecteurs Node historiques sont réutilisés. Les limites
individuelles restent 340 Kio H1/H2, 4096 octets session-300 et 8192 suite/reconnexion.
Le bundle fermé ajoute seulement sélection, provenance, étapes armées et résultat
du processus ; maximum 358400 octets, base64 canonique borné, transmis en quatre
valeurs de 120000 caractères maximum pour respecter aussi la limite exec Linux.
Il est revalidé et
matérialisé sur un runner distinct sans environnement ni secret Hoben, puis publié
sept jours au plus. Aucun RX, registre, valeur domestique, GUID, exception libre
ou identifiant privé. Les anciennes conventions de provenance des sous-rapports
restent intactes et sont vérifiées contre le même SHA exécuté et la PR revue.

TLS certificat et hostname vérifiés vers myhoben.fr:465 ; lecture seule, aucune
association ou commande poêle, aucune écriture Modbus 06/16/22. EOF, CloseClient,
quarantaine et corrélation ne sont pas réinterprétés. boundary_proven=false reste
obligatoire ; aucun succès réel revendiqué par les tests synthétiques.

## Retrait des anciennes voies

Les sept anciennes définitions live/préflight sont déplacées hors d'Actions dans
`tests/fixtures/retired_workflows/`. Leurs scripts et régressions restent testés
hors ligne ; leurs commentaires/gates ne sont jamais un repli de la nouvelle voie.
Les cinq workflows actuels sont Tests Hoben manuels, campagnes HA et protocole
manuelles, Validate et publication de release.
Le retrait ne supprime ni ne relance les runs déjà créés ou leurs claims.
Une activation future de main exige une décision propriétaire distincte après
installation et validation de ses contrôles ; aucune PR main dans cette phase.


## Historique HA et observation Info

L'ancien chemin collect-ha/publish-ha/result-ha est retiré de ce workflow.
Le workflow séparé hoben-ha-manual.yml conserve son propre hoben-live HA.
Info dispose de collect-info/publish-info/result-info et d'un rapport public
fermé de 8192 octets maximum, publié sept jours. Sans Info pendant la fenêtre
complète : INCONCLUSIVE. Candidat observé mais continuation non prouvée :
INCONCLUSIVE après cleanup attesté. Toute erreur, défaut de cleanup ou de
provenance : FAILURE, sans prétendre qu'aucune connexion n'a eu lieu.
Ce worker ne produit jamais SUCCESS ; framing INCONCLUSIVE,
boundary_proven=false et cleanup réel #192 non résolu restent explicites.
Le succès technique du job de publication ne change pas le verdict scientifique.

Une reprise de parsing après Info n'est pas tentée. Fragments et coalescences
sont testés hors ligne, sans inventer de frontière applicative. Aucun test réel
DEV/CI, aucune approbation automatisée, aucune relance ni activation HA.
Le [rapport D7](info-manual-end-to-end-186.md) détaille le contrôle de publication
encore bloquant et les conditions nécessaires avant une déclaration READY par
MANAGER. Ce document ne constitue pas une autorisation de dispatch.
