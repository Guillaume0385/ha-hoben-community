# Tests Hoben manuels — #119, phase 2 experimental

La phase 1 a installé le bouton sur la branche par défaut `main` (PR #120,
`b0c177d8146d4891d366a39e1fb0cd1dba86126c`). Cette phase 2 reporte le même chemin
`.github/workflows/hoben-manual.yml` sur `experimental` et raccorde les collecteurs
existants. `main` conserve son point d'entrée sans runtime et reste inactive.
Aucun protocole n'est promu vers main ; étape 8 HA toujours suspendue.

## Utilisation après fusion et revue MANAGER

Dans **Actions → Tests Hoben manuels → Run workflow** :

1. Choisir **experimental** dans le sélecteur natif **Use workflow from**.
2. Choisir `h1h2`, `session-300`, `session-reconnect` ou `all`.
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

## Scénarios et budgets conservés

| Sélection | Collecteur et limite externe |
| --- | --- |
| h1h2 | Même campagne H1/H2 : six sessions par hypothèse, 90 s et 1 Mio RX par session ; processus 1800 s. |
| session-300 | Même observe(), 300 s utiles, processus 360 s, trois ouvertures, six lectures fixes et 1 Mio RX. |
| session-reconnect | Même collecteur borné de reconnexion : processus 600 s, fonctionnel au plus 360 s, dix lectures, trois ouvertures, 1 Mio RX. |
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
NOT RUN un scénario non sélectionné ou non commencé selon les preuves disponibles.
Sans rapport vérifiable après un échec de capture, les scénarios demandés restent
INCONCLUSIVE et le workflow échoue : aucune absence de connexion n'est inventée.
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
Seuls hoben-manual, Validate et publication de release restent dans Actions.
Le retrait ne supprime ni ne relance les runs déjà créés ou leurs claims.
Une activation future de main exige une décision propriétaire distincte après
installation et validation de ses contrôles ; aucune PR main dans cette phase.
