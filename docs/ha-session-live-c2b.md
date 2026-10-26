# Étape 8 C2b — voie manuelle du vrai client HA

Source : [première section MANAGER #112](https://github.com/Guillaume0385/ha-hoben-community/issues/112#issuecomment-6395141200),
décision propriétaire du 26/10. Base C2a fusionnée par #127,
`6a58afe65b200bc9a43c71efa11658086abc1084`.
Développement et CI exclusivement hors ligne ; aucun test réel par DEV.
Le run propriétaire ultérieur #40326783513 a échoué (voir correction C2c),
sans validation de session HA.

## Sélection et admission

Le workflow `hoben-manual.yml` ajoute `hoben-live`. Le choix `all` reste
**h1h2 → session-300 → session-reconnect**, avec ses budgets historiques.
Le nouveau choix possède ses propres jobs collect-ha/publish-ha/result-ha et
l'environnement **hoben-live** ; les anciens jobs gardent hoben-experimental.
Ni push, PR, merge, label, commentaire, cron ni CI ne lance une observation.
Main reste refusée ; seul le ref/SHA réellement choisi par **Use workflow from**
est exécuté, sans checkout de substitution.

L'admission manuelle existante conserve toutes ses preuves : propriétaire et
identifiants numériques, dépôt/ref/SHA/run exacts, tentative 1, PR fusionnée par
le propriétaire, arbre identique au candidat, revue sans remarque active,
Validate du candidat avec quatre jobs réussis avant dispatch, HEAD protégé
courant, absence d'observation concurrente, mutex partagé et claim immuable
par run. Les relances restent refusées ; aucun claim n'est créé pendant DEV/CI.
Les tests utilisent seulement des doubles d'API GitHub.

L'environnement courant a été accepté par le propriétaire sur captures : mode
Protected branches only, reviewers/wait timer désactivés, bypass administrateur
activé. Cette décision autorise le développement, **pas un run réel**. Le gate
relit la politique API effective et exige toujours experimental protégé au SHA
exact, même si l'environnement permet aussi main. Le mode personnalisé ne vaut
que pour une règle exacte experimental de type branch. API inaccessible,
réponse incomplète ou règle inconnue : refus avant secrets. L'empreinte de
politique est liée au claim ; aucun réglage Settings n'est modifié.
Si des reviewers sont configurés, ils restent obligatoires, indépendants et
leur approbation doit être fraîche pour ce run et cet environnement.
Le recheck est effectué après l'attente d'environnement et la préparation de
l'image, immédiatement avant l'unique étape recevant les identifiants.
Aucun commentaire pré-fusion MANAGER ne remplace ces vérifications.

## Exécution et confidentialité

Le parent réutilise le [superviseur C2a](ha-session-runtime-c2a.md), son gardien
PID 1 indépendant et ses cgroups. Le mode offline reste network=none avec son
worker de fixtures. Le mode live vérifie le conteneur bridge, l'image immutable,
le programme fixe, stdin, les montages, la racine en lecture seule, les capacités,
la mémoire/swap et les PID avant d'envoyer une identité.

Les identifiants sont transmis seulement en mémoire : stdin Docker privé puis
pipe anonyme vers le worker UID/GID 65534 sans capacités. Aucun identifiant dans
Docker Env, commande, couche d'image, volume de reçu, stdout/stderr ou rapport.
Le worker n'a ni token GitHub/Actions/OIDC, fichiers de commandes Actions,
socket Docker, checkout .git ni mode/scénario arbitraire. Le log driver est none.
L'entrée privée est bornée et fermée ; aucun secret réel n'est utilisé en DEV.
Le volume de reçu contient seulement des champs numériques/catégoriels validés.

Le worker construit les vraies classes HomeAssistant, HobenClient et
HobenDataUpdateCoordinator, avec l'observer C2a en **horloge native uniquement**.
L'amorçage minimal du registre ConfigEntries utilise son API interne figée en
HA 2026.9.4 pour permettre la vraie persistance d'un DeviceGuid renouvelé, sans
setup d'entités ni lecture supplémentaire. Ce point est testé avec le vrai HA ;
une mise à jour HA nécessitera une nouvelle revue. Les données HA temporaires
restent en tmpfs privé, dans le même cgroup. Son arrêt complet exécute les hooks
HA de sauvegarde/nettoyage, puis le namespace et le tmpfs sont détruits.
Aucun transport parallèle, mock, codec ou stratégie de retry dans le worker live.
Les tests injectent explicitement transport et horloge synthétiques.

Les seules connexions applicatives du worker sont celles du client partagé :
TLS certificat et hostname vérifiés vers **myhoben.fr:465**, lecture seule,
pas d'association, commande ou écriture Modbus 06/16/22. Le bridge n'est pas un
proxy ou une preuve de filtrage réseau par destination ; le programme fixe,
les contrôles du transport et la revue du SHA assurent ce chemin applicatif.

Plafonds conservés : 300 s utiles après premier témoin, six refreshs, deux
ouvertures, 360 s absolues démarrage/cleanup/kill/reaping inclus, mémoire agrégée
1 Gio sans swap, 128 PID/threads, rapport complet <=8192 octets. Le gardien et
son échéance ne sont jamais réarmés. Aucun quota, compteur ou proxy RX hoben-live.
Les budgets H1/H2, session-300 et reconnexion restent inchangés.

## Preuve et résultat

Le schéma **3 hoben-live** est distinct des enveloppes C1/C2a qui restent offline.
Il lie merge/candidate SHA, PR, CI, run/tentative, environnement/empreinte et SHA
du claim aux preuves attendues par les jobs sans secret. Le reçu live est
obligatoire ; un reçu de fixtures ou une horloge synthetic ne peut pas être promu.
Les témoins logiques sont validés en Python et indépendamment en Node.
Les valeurs/registre/snapshots/GUID/RX/erreurs libres sont absents du schéma fermé.

SUCCESS du scénario HA exige collection, réutilisation TLS, continuous_300s,
cleanup et supervision réussis. Le critère de reconnexion reste **INCONCLUSIVE
sans perte** ; il n'est pas requis pour réussir cette observation de continuité.
Une perte tardive invalide la continuité, même si une reconnexion antérieure est
prouvée. Les arrêts locaux ne prouvent jamais EOF ou reconnexion.
Une absence de démarrage attesté reste NOT RUN ; absence/rapport falsifié après
capture échouée => NOT RUN pour la preuve de session, avec échec global, jamais
preuve d'absence de connexion ni requalification du job échoué en non-exécution.

Collect exporte seulement une valeur base64 bornée après validation ; un runner
publish distinct, sans environnement/secret Hoben, revalide contre les preuves
preflight et écrit le seul JSON publiable. Artefact ha-live-report-SHA-run-a1,
rétention sept jours maximum. Result revalide encore cet artefact.
Le backend Docker/cgroup absent refuse sans exécution sur l'hôte. Comme en C2a,
une perte du contrôle Docker peut laisser des métadonnées/volume anonymisé à
supprimer après rétablissement ; aucun reaping non attesté n'est inventé.

## Correction C2c — collecte refusée avant superviseur

Le run propriétaire [#40326783513](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/40326783513)
sur le merge #128 a échoué : preflight et construction d'image réussis,
`python -I trusted/scripts/launch_ha_manual_live.py` arrêté avec code 1,
collect-ha/result-ha FAILURE, sans artefact. Ce run a bien été lancé ; aucune
session HA aboutie n'est prouvée. Les journaux ne contiennent pas la phase
interne exacte de l'ancienne sortie silencieuse.

Défaut d'entrée démontré par code et reproduction offline : **C2b exige les
deux entrées HOBEN_USER_GUID et HOBEN_DEVICE_GUID**. Le DeviceGuid doit être déjà
attribué, exactement 32 caractères ASCII et différent de l'identité initiale.
La valeur DeviceGuid vide observée dans l'environnement du job suffit à faire
échouer sa validation avant tout appel du superviseur, indépendamment de TLS,
du serveur ou du protocole. La reproduction isolée Python `-I` emploie de vrais
checkouts Git locaux et contrôles de provenance/image, un événement/identifiant
de fixture et un superviseur interdit : même refus, aucun accès réseau. Elle
n'ajoute pas rétroactivement une trace de phase au run historique et n'exclut
pas un autre refus antérieur non journalisé.

Cette exigence est conservée : ni identité inventée, ni repli à zéro, ni nouvelle
association, ni recherche/lecture/création de secret par DEV. Avant un futur test,
le propriétaire/MANAGER doit faire fournir l'identité persistée via la gestion
de secrets autorisée, hors de ce correctif. Sans elle, le refus reste obligatoire.

Le correctif remplace la sortie silencieuse par **un seul diagnostic fermé** :
phase (provenance/image/identity/supervision/report), catégorie allowlistée,
statut de démarrage, rapport absent/validé, résultat de session et code de sortie.
Aucune valeur d'entrée, exception libre, identifiant de session ou donnée Hoben.
Un refus d'image/identité après provenance valide écrit le schéma 3 NOT RUN
existant (`unavailable` : prérequis indisponible), sans témoin ni faux cleanup ;
la catégorie du diagnostic précise le prérequis. Le lanceur garde **code 1**.
L'export s'exécute aussi après échec de capture, uniquement après recheck admis ;
seul le rapport fermé validé peut être publié sur le runner sans secret. Aucun
rapport n'est fabriqué après échec de provenance, exception du superviseur ou
rapport invalide ; le démarrage reste alors non attesté après appel du superviseur.
Une panne d'écriture laisse un échec explicite sans repli brut.

Result-ha distingue le statut du **job de collecte** et la **preuve de session**.
Un rapport NOT RUN publiable ne rend jamais la collecte ni le run réussis.
Un rapport absent ou même SUCCESS ne neutralise pas l'échec du job. Les tests
offline couvrent ces cas, entrée manquante/invalide, arrêt précoce, exception
privée et codes retour ; gates, anti-rejeu, TLS, vrai HA et budgets inchangés.
Après fusion et autorisation distincte du propriétaire, seul un **nouveau**
dispatch serait admissible ; aucune relance du run consommé, aucun run par DEV.

## Promotion minimale du formulaire vers main — plan historique MANAGER

État C2c selon la consigne canonique : #129 fusionnée par MANAGER, choix UI
experimental/hoben-live acquis. Le plan initial C2b ci-dessous est conservé
comme historique ; il ne constitue ni une nouvelle PR main ni une activation.

Lors de la préparation C2b, lecture GitHub effectuée : main possède le même chemin de workflow_dispatch,
mais ses options actuelles s'arrêtent à all. La capture propriétaire confirme
que la sélection experimental n'affiche pas encore hoben-live.
Après revue/fusion C2b, proposer séparément au MANAGER **uniquement** ce changement
sur la définition de formulaire de main :

```diff
-        options: [h1h2, session-300, session-reconnect, all]
+        options: [h1h2, session-300, session-reconnect, all, hoben-live]
```

Ne reporter ni jobs collect/publish, scripts runtime, dépendances ni secrets sur
main. Son préflight inactif et son refus de main sont conservés. Les scripts,
le scénario et ses checks proviennent ensuite du SHA experimental réellement
sélectionné par le mécanisme natif. Cette tâche DEV ne crée aucune PR main.
La compatibilité UI effective reste à vérifier par le propriétaire après cette
publication séparée ; ne pas inventer une capture ou un dispatch réussi.

Un test réel exigera une autorisation distincte, le choix UI effectif, les
politiques API/recheck et les éventuelles approbations vérifiées. DEV ne lance
ni dispatch, rerun, claim, approbation ou observation ; MANAGER seul fusionne.
