# Preuves GitHub — lecteur et transport non raccordés #126

Tranche `HOBEN-126-GITHUB-EVIDENCE-006`,
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6435985641),
base experimental `518e57b3eee4f2966724ed772f4a29e9e5a6d779`.
Le [contrat d'admission](manual-test-campaign-admission-contract.md), les deux
plans et les shells restent inchangés. Ce lecteur ne les importe ni ne les
raccorde ; il ne produit pas un snapshot d'admission complet.

## Périmètre de preuve fermé

[github_campaign_evidence.py](../scripts/github_campaign_evidence.py) lit la
provenance d'une **PR candidate et de sa CI Validate**, pas celle d'un dispatch
live. La requête figée fournit seulement numéro PR, SHA candidat, branche source,
ID du run CI et cible `refs/heads/experimental`. Ces valeurs sont des attentes
à vérifier, jamais des attestations. main est refusée comme cible et source.

Le résultat figé contient des faits nommés par enum, attested ou unknown, une
erreur catégorielle fixe éventuelle et deux empreintes privées. Il ne contient
ni réponse brute, nom de branche libre, URL, body de revue/PR, token, exception
libre ou identité d'utilisateur. Sa conversion booléenne vaut toujours false.
Même avec six faits attestés, il reste **NOT RUN / FAILURE / can_start=false**.
L'exécution directe se termine avec code 1 sans sortie ; aucune CLI n'existe.
Le transport HTTP séparé de la tranche 007 est décrit plus bas, sans raccordement.

| Fait attestable | Vérification depuis les réponses REST |
| --- | --- |
| Dépôt | Nom exact Guillaume0385/ha-hoben-community, ID 1401398724 et propriétaire nom/ID/type exacts. |
| Commit | Réponse Git commit au chemin du dépôt et SHA candidat exact, arbre Git valide. |
| Contexte PR | Numéro, HEAD candidat/branche et dépôts source/base exacts, cible experimental, non draft ; ouverte ou réellement fusionnée par le propriétaire. |
| Revue formelle MANAGER | Dernière décision active de son identité GitHub exacte : APPROVED sur le candidat ; aucune demande de changements active, y compris d'un autre reviewer. |
| Provenance CI | Run exact, même dépôt/source/HEAD/branche et head_commit, événement pull_request, tentative 1, workflow Validate ID 373497148 et chemin/ref autorisés, completed/success. |
| Quatre checks | Réponses de l'endpoint des jobs de **ce run et cette tentative**, exactement tests/ha-tests/hacs/hassfest, noms et IDs uniques, HEAD/branche/run/tentative identiques, completed/success et dates cohérentes. |

Le workflow ID provient des métadonnées Actions courantes du dépôt ; suppression
et recréation exigeraient une mise à jour revue, jamais un fallback par nom.
Le chemin est exactement `.github/workflows/validate.yml`, éventuellement
suffixé par `@refs/pull/<PR>/merge` ou `@refs/heads/<branche source>`.
Les quatre résultats viennent d'Actions, pas de contextes de commit status,
de noms de checks fournis par un appelant ou d'un succès global seul. Aucun
appel à un endpoint check-suite, check-run ou de modification n'est nécessaire.
Cette preuve situe la CI ; elle n'atteste pas le contenu de son YAML ou les
protections de ce contenu.

L'association du run à la PR doit être explicite, unique et concordante dans
`pull_requests`. Après certaines fusions GitHub vide ce tableau : **refus**, sans
déduire l'association du seul SHA ni emprunter un claim encore inconnu. Cette
première tranche n'atteste pas l'équivalence des arbres candidat/merge ni la
provenance d'une future exécution manuelle.

## Revue : limite conservatrice explicite

Les reviews REST sont lues entièrement et classées par date/ID. COMMENTED
n'efface pas CHANGES_REQUESTED ; une approbation périmée ou dismissed ne vaut
pas revue du nouveau SHA. Les identités du propriétaire sont vérifiées par
nom, ID et type User, jamais par body ou association d'auteur déclarée.

**Une fusion par le propriétaire n'est pas auto-attestée comme une revue.**
Les commentaires libres et bilans MANAGER ne sont pas parsés. GitHub interdit
l'approbation formelle de sa propre PR : pour les PR du mainteneur sans review
formelle, ce lecteur renvoie `manager_review_unverified`. Il ne prétend donc pas
authentifier rétroactivement les revues historiques. Une autre représentation
vérifiable d'une décision MANAGER demanderait un arbitrage/contrat distinct,
sans créer une approbation ou contourner GitHub. Les threads résolus/non résolus
restent **unknown** ; aucune approbation de revue complète n'est déduite.

## Transport injecté et validation pure

`Reader.get(path, page=..., per_page=...)` est la frontière de confiance.
Le transport séparé ci-dessous implémente ce port ; une intégration future devra
fournir son jeton et un contexte fiable, sans activer une admission implicite.
TLS vérifié, absence de cache, troncature ou redirection restent requis.
Les identifiants restent dans ce client ; ils ne traversent ni la
requête du module, ni l'observation. Un faux transport peut mentir : ces tests
ne constituent aucune attestation GitHub opérationnelle ou cryptographique.

Le transport retourne `Reply(status, data, next_page)` depuis la réponse HTTP
et son Link authentifiés ; next_page=null signifie fin vérifiée, jamais
métadonnée perdue. S'il ne peut établir cette fin, il doit échouer. Les routes
sont construites sous `/repos/Guillaume0385/ha-hoben-community`, uniquement :
dépôt, Git commit candidat, PR, run CI, reviews PR et
`actions/runs/<id>/attempts/1/jobs`. La tranche 009 ajoute seulement
`branches/experimental` pour le lecteur de branche séparé décrit plus bas.
La tranche 010 ajoute uniquement `git/trees/<SHA>` pour le parcours fermé
de métadonnées décrit en fin de document, sans lecture de blob.
La tranche 011 ajoute `git/blobs/<SHA>` pour le lecteur d'identité séparé,
uniquement après validation de sa liaison à l'arbre de campagne.
La tranche 012 ajoute les deux seules routes workflow par nom de fichier fermé,
pour leurs métadonnées de registre, sans ref ni capacité d'exécution.
Aucun lien ou URL du body n'est suivi.
Le module ne lit aucun environnement, secret ou réglage de protection.

Les collections sont paginées par 100, au plus dix pages par lecture. Boucle,
saut, page vide non terminale, doublons ou total changeant/incomplet refusent.
Sans total pour les reviews, une page terminale pleine reste ambiguë et refuse
par prudence. Une réponse 401/403/404/429/5xx, un autre statut ou une exception
ne devient jamais une liste vide ou un succès. Aucun retry ni contournement ;
la sortie se limite à l'enum d'erreur, sans body ni URL d'erreur.

`_collect` effectue les GET ; `_validate` est pur et ne conserve pas les
réponses. Deux lectures complètes doivent produire la même empreinte normalisée
(identités attendues, arbre, état/date PR, CI, IDs/dates des jobs et décisions
de revue). Un changement de HEAD, tentative, PR, jobs ou revue refuse.
`read_evidence(..., previous=observation)` refait ces lectures et compare les
pins précédents. L'empreinte SHA-256 lie des faits ; ce n'est pas une signature.
Ce recheck ne prouve ni l'absence d'une course après lecture, ni une fraîcheur
globale, ni un recheck après approbation d'environnement.

## Faits inconnus et suite différée

Restent explicitement unknown : contexte dispatch/acteur/scénario, threads de
revue, protections de branche, politique et approbations d'environnement,
réservation atomique de claim, mutex, anti-rejeu et recheck après approbation.
Ne pas convertir leur absence en false, politique permissive ou attested=true.
Le contrat d'admission précédent manque donc toujours de preuves et ne peut
être rempli automatiquement par ce résultat partiel. Aucun budget n'est armé
ou changé ; aucun plan ne reçoit une capacité d'exécution.

Les [tests](../tests/test_github_campaign_evidence.py) n'utilisent que des
fixtures REST synthétiques, avec réseau interdit. Ils couvrent spoofing,
erreurs/malformations, pagination, SHA/ref/PR/revue/CI, déplacements et recheck,
immuabilité et sorties expurgées. Une fixture positive n'est pas une preuve live.
Workflows, gates, claims, collecteurs, HA, protocole et main sont inchangés.
Aucun dispatch/rerun/test réel, secret, commande poêle ou écriture Modbus 06/16/22.
Lecture seule, TLS myhoben.fr:465 et confidentialité restent imposés ; aucune
hypothèse universelle OpenedClient=48. Livraison de cette tranche puis STOP.

## Transport GET isolé — HOBEN-126-GITHUB-TRANSPORT-007

Base experimental `bf1edfbd6b6f6e140ed3a9b0e434a280f0b69d61`, après #139.
[github_campaign_transport.py](../scripts/github_campaign_transport.py) fournit
`GitHubGETTransport(token, client=...)` et le même port get. Le backend stdlib
effectue uniquement GET ; le client HTTP injectable permet les tests offline.
Aucun workflow, gate ou script consommateur n'est raccordé. Le lecteur de
preuves précédent et sa règle de revue formelle sont inchangés. Le test de
non-raccordement autorise seulement ce nouveau transport à importer PREFIX/Reply ;
les imports dans les workflows, collecteurs et autres scripts restent interdits.

### Origine, authentification et TLS

L'origine est fixée à `https://api.github.com`. Aucun argument n'accepte une
origine alternative, méthode HTTP ou header libre. Les six routes initiales
restent admises : dépôt, Git commit par SHA hexadécimal complet non nul,
PR/run par ID entier positif, reviews PR et jobs du run/tentative 1. La tranche
009 autorise en plus la seule route exacte branches/experimental ; la tranche
010 ajoute Git trees et la tranche 011 Git blobs par SHA complet non nul,
sans query ni récursivité. Query
dans path, traversée, encodage de chemin, alias de dépôt, sous-routes et autre hôte
refusent avant HTTP. Pour les collections : page 1–10, per_page=100 exactement.

Le jeton opaque ASCII de 8–1024 caractères est **injecté**, jamais découvert via
GITHUB_TOKEN, environnement, fichier ou autre identité. Pas de valeur réelle en
tests. Il n'apparaît pas dans les URLs, repr, Reply ou erreurs ; un écho littéral
ou échappé JSON dans la réponse refuse. Les bodies REST intermédiaires restent
des données internes au lecteur : ne jamais les publier comme observations.

Chaque requête reçoit un SSLContext PROTOCOL_TLS_CLIENT avec certificat et
hostname vérifiés ; aucune option de désactivation n'existe. SSLKEYLOGFILE
n'active pas la journalisation de clés. Le backend conserve la configuration
standard des proxys et de confiance CA, sans lire de jeton d'authentification
dans l'environnement ni changer l'opener global. Un client injecté reste une
frontière de confiance : il doit respecter TLS, timeout, absence de logs/cache
et framing. Les mocks n'établissent aucune connexion TLS réelle.

Toute redirection, y compris même origine, est refusée sans seconde requête ;
l'URL effective doit être exactement celle construite. Un code différent de
200 ferme le flux sans lire son body, sans retry ni suivi de Location. Les
exceptions ne conservent aucun contexte/cause privé et n'affichent qu'une enum
fixe. Le validateur existant réduit ces exceptions à api_unavailable, toujours
UNKNOWN / NOT RUN / FAILURE ; aucun changement de contrat n'est nécessaire.

### Bornes des métadonnées et complétude

Le timeout I/O transmis au backend est 10 s. Une deadline monotone de 10 s est
contrôlée après ouverture, entre lectures read1, après corps et après validation.
Ces contrôles refusent une réponse terminant trop tard ; ils ne préemptent pas
le résolveur DNS ou un appel système bloqué. Une future intégration nécessitant
un plafond absolu de processus devra l'imposer extérieurement. Aucune borne
absolue de processus ou preuve d'admission n'est revendiquée par ce module.

Les seuls nouveaux plafonds portent sur les métadonnées GitHub : corps maximal
**2 Mio**, headers validés au plus **64 Kio / 100 champs**, Link 8192 caractères,
profondeur JSON 64 et dix pages de 100 entrées. Les budgets Hoben restent
inchangés, sans quota RX hoben-live ajouté. Les lectures demandent au plus
64 Kio et dépassent au maximum d'un octet le plafond pour détecter un excès,
puis ferment le flux. La longueur annoncée est vérifiée ; framing absent ou
ambigu Content-Length + Transfer-Encoding refuse. Chunked est décodé par le
backend stdlib, qui signale une terminaison manquante. Compression refusée.

Content-Type JSON UTF-8 obligatoire ; encoding invalide, JSON tronqué, doublons
de clés, NaN/infini, surrogate ou forme racine inattendue refusent. Aucun body
d'erreur, contenu libre ou lien privé n'est imprimé, même lors d'un refus.

Chaque relation Link est unique et doit garder origine, route exacte et query
fermée page/per_page ; next est exclusivement la page suivante. Boucle, saut,
fragment, credentials/port dans l'origine, paramètre supplémentaire, alias
`/repositories/...`, last incohérent ou rel inconnu refusent. L'URL n'est jamais
suivie : le lecteur reconstruit lui-même chaque GET. Sans next, les reviews
doivent avoir une page incomplète ; une page pleine sans preuve est refusée.
Pour les jobs, total_count et cardinalité doivent prouver la page et la présence
ou absence de next. Ces refus conservateurs ne deviennent pas des listes vides.

Les [tests de transport](../tests/test_github_campaign_transport.py) bloquent
DNS et sockets, injectent uniquement un faux HTTP et des credentials synthétiques.
Ils couvrent TLS/redirections/auth, erreurs HTTP/privées, tailles, troncature,
framing chunked réel sur flux mémoire, JSON, Link et compatibilité avec la double
lecture/recheck du validateur. Ils ne valident pas les permissions ou une revue
MANAGER réelle. Protections, approvals, claims, mutex et anti-rejeu restent
inconnus ; aucune décision, collecte, CLI, promotion main ou test réel n'est ajouté.

## Faits partiels de dispatch — HOBEN-126-DISPATCH-FACTS-008

Base experimental `9353c690ba9d8938a7e53e05ae391bd7409c8c09`, après #140.
[github_campaign_dispatch_evidence.py](../scripts/github_campaign_dispatch_evidence.py)
est séparé du lecteur PR/CI et du transport, tous deux inchangés. Il ne contient
aucun backend HTTP, token, lecture d'environnement, horloge ou CLI. Il n'ajoute
aucune route et n'est consommé par aucun workflow/gate/collecteur.

`Expected` épingle la campagne fermée protocol/ha, run_id, workflow_id et SHA
complet, avec cible exclusivement refs/heads/experimental. Les IDs attendus
doivent venir d'une configuration indépendante fiable ; ils ne sont ni découverts
dans la réponse puis recopiés comme attentes, ni inventés dans une table locale.
Les IDs des fixtures sont synthétiques. Le registre des workflows et sa présence
sur la branche par défaut restent UNKNOWN.

`validate_dispatch(expected, payload)` est pur. Il valide structure et relations
de champs REST documentés, sans authentifier lui-même l'origine d'un dict. Seul
un Reader de confiance, notamment le transport injecté de la tranche 007, peut
fournir les vraies réponses authentifiées. Des booleans attested/approved donnés
par l'appelant ne constituent aucune preuve et ne sont jamais consommés.

`read_dispatch(reader, expected, previous=None)` réalise **deux GET distincts**
de `/repos/Guillaume0385/ha-hoben-community/actions/runs/<run_id>`, sans query,
pagination ou autre appel. Réponse non 200, next_page non null, autorisation/API
indisponible, réponse tronquée/malformée ou champ requis manquant : refus et
tous les faits UNKNOWN. Aucune erreur ne conserve body, URL, token ou exception
libre. Le transport concret conserve son refus des redirections et ses limites.

| Faits attestables depuis ce run | Validation |
| --- | --- |
| Dépôt | repository et head_repository : nom/ID/propriétaire exacts du dépôt, identité User. |
| Run, événement et tentative | id épinglé, workflow_dispatch, run_attempt exactement 1, jamais booléen/rerun. |
| Workflow rapporté | workflow_id attendu ; path exact de hoben-protocol-manual.yml ou hoben-ha-manual.yml selon la campagne. Le suffixe @refs/heads/experimental est accepté seulement s'il est présent dans path. |
| SHA et nom de branche rapportés | head_sha et head_commit.id au SHA épinglé ; head_branch exactement experimental. |
| Acteur et déclencheur rapportés | actor et triggering_actor : Guillaume0385, ID 18246624, type User. Aucune copie de actor pour combler un triggering_actor absent ; cette version refuse alors faute de preuve. |

L'observation figée ne retient que des enums de faits/états/erreurs et des
empreintes privées. Aucun payload, dict d'entrée, URL, input ou identité libre
n'est conservé. Même positive, elle reste **can_start=false / execution=NOT RUN /
actions_result=FAILURE**, conversion booléenne false. Aucun snapshot d'admission
complet ne peut être produit à partir de ces seuls faits.

Les deux lectures doivent avoir les mêmes faits normalisés. Le recheck relit
deux fois, compare l'empreinte et exige les mêmes attentes. Modification de
run/tentative/dépôt/acteur/workflow/path/ref/SHA refuse. La progression de status,
conclusion ou updated_at est volontairement ignorée : elle ne prouve ni la
réussite d'un scénario ni une absence d'exécution. Les empreintes ne sont pas des
signatures et ne prouvent pas une fraîcheur globale ou l'absence d'une course.

Restent UNKNOWN, même si un payload ajoute des champs portant ces noms :
workflow_ref, workflow_sha, contenu/registre YAML, scénario/inputs, sender,
contexte runner, HEAD/protection de branche courants, politique/approbations
d'environnement, revue MANAGER/self-approval, PR/CI, claim, mutex, anti-rejeu,
recheck après approbation, sélection UI/main, résultat de scénario, fraîcheur et
autorisation d'exécution. Un path suffixé et head_sha ne deviennent jamais une
preuve de GITHUB_WORKFLOW_REF ou du SHA du YAML réellement chargé.

Les [tests](../tests/test_github_campaign_dispatch_evidence.py) sont entièrement
offline : faux Reader/HTTP, DNS/sockets interdits, cas positifs et refus,
mutations entre lectures, recheck, immuabilité, troncature et sorties expurgées.
Ils vérifient les deux chemins YAML et la compatibilité du transport sans le
raccorder. Cette tranche 008 conserve les règles PR/CI/self-review, les six routes
HTTP initiales, les shells et les budgets. Aucun dispatch/rerun, test GitHub/Hoben
réel, secret Hoben, commande, écriture, PR main ou fusion DEV. Livraison puis STOP.

## HEAD de branche observé — HOBEN-126-BRANCH-HEAD-009

Base experimental `f00c4044e3af0a2069e4948828cb212c884e2586`, après #141.
[github_campaign_branch_evidence.py](../scripts/github_campaign_branch_evidence.py)
est indépendant du dispatch et du lecteur PR/CI. Il ne contient aucun backend
HTTP, token, environnement, horloge, CLI ou consommateur live. Le transport est
étendu d'une seule entrée d'allowlist exacte :
`/repos/Guillaume0385/ha-hoben-community/branches/experimental`.
Les six routes précédentes et leurs tests sont conservés. Branches arbitraires,
main, sous-routes de protection, encodages et paramètres sont refusés avant HTTP.
TLS, origine, redirections, limites et erreurs du transport sont inchangés.

`Expected(sha, repository=..., ref=...)` épingle indépendamment le dépôt exact,
refs/heads/experimental et un SHA hexadécimal complet non nul. Mauvais type,
main, autre dépôt ou pin invalide refusent **avant toute lecture**. Le module
ne construit jamais cette attente depuis un SHA reçu. Un nouveau pin ne peut
pas réutiliser une observation précédente comme recheck.

`validate_branch(expected, repository_payload, branch_payload)` est pur. Il
vérifie le nom/ID/propriétaire du dépôt, puis le nom experimental et commit.sha
égal au pin. Les identités sont strictes ; booléens substitués aux champs,
champ manquant, null ou SHA/branche divergents refusent. Un head_sha de run ou
head_commit.id ne remplace jamais le commit.sha de la réponse de branche.
La fonction pure ne prouve pas elle-même l'authenticité d'un dict : le Reader
et le transport doivent fournir une source GitHub authentifiée et fiable.

`read_branch(reader, expected, previous=None)` fait **quatre GET séquentiels** :
dépôt, branche, dépôt, branche. Le GET dépôt déjà autorisé confirme à chaque
passage l'identité exacte ; une erreur d'identité arrête avant le GET branche.
Les deux observations doivent correspondre au même pin et HEAD. Le recheck
refait les quatre lectures et compare aussi les empreintes antérieures.
Déplacement entre lectures ou depuis l'observation précédente, erreur/permission
API, réponse tronquée/malformée ou next_page non null : tous les faits UNKNOWN.
Aucune réponse partielle valide n'est conservée après un échec ultérieur.

Seuls trois faits peuvent devenir ATTESTED : **dépôt, nom de branche, HEAD
observé**. L'objet figé contient des enums et empreintes privées, aucun dict,
payload, URL libre, token ou exception. Même positif : **can_start=false /
execution=NOT RUN / actions_result=FAILURE**, conversion booléenne false.

`protected`, protection_url, permissions et toute déclaration d'approbation sont
délibérément ignorés. Un changement de protected avec HEAD stable n'atteste ni
ne réfute la politique effective : celle-ci reste UNKNOWN. Restent aussi UNKNOWN
revue MANAGER, politique/approbations d'environnement, workflow_ref/SHA/contenu
YAML, lien au run/PR/CI, claim, mutex, anti-rejeu, sélection UI/main, recheck
après approbation et autorisation d'exécution. Aucun endpoint de protection
n'est lu, autorisé ou modifié.

Les deux réponses HEAD concordantes ne constituent pas un snapshot atomique :
un mouvement aller-retour entre lectures, une course après lecture ou une
réponse périmée ne sont pas exclus. Fraîcheur globale et atomicité restent
UNKNOWN ; les empreintes ne sont pas des signatures. Ce lecteur observe la
branche aux lectures effectuées et ne complète aucun contrat d'admission.

Les [tests](../tests/test_github_campaign_branch_evidence.py) sont exclusivement
offline avec faux Reader/HTTP, DNS/sockets interdits, HEAD déplacé, refus/types,
erreurs et troncature, recheck, confidentialité, immuabilité et refus de toutes
les routes voisines. Les suites historiques transport/dispatch/admission sont
rejouées. Aucun raccordement workflow/gate/collecteur/HA, test GitHub/Hoben réel,
dispatch/rerun/claim, secret, commande/écriture, changement de budget ou main.
Les deux campagnes restent inertes et NOT RUN ; livraison puis STOP.

## Présence du workflow dans un arbre épinglé — HOBEN-126-WORKFLOW-TREE-010

Base experimental `cb5d7d06c545b7a7f71c50e200371ee71bf36873`, après #142.
[github_campaign_workflow_tree.py](../scripts/github_campaign_workflow_tree.py)
est indépendant des lecteurs HEAD, dispatch et PR/CI. Aucun backend HTTP,
token, environnement, horloge, CLI, workflow, gate ou consommateur n'est ajouté.
Les deux shells restent inertes et les contrats d'admission restent inchangés.

`Expected(campaign, sha, repository=..., ref=...)` accepte uniquement les enums
protocol/ha, le dépôt exact, refs/heads/experimental et un SHA complet non nul
épinglé indépendamment. Il ne découvre jamais le SHA attendu depuis une réponse.
Aucun chemin, URL ou branche libre n'est accepté. Les seuls chemins cibles sont
`.github/workflows/hoben-protocol-manual.yml` et
`.github/workflows/hoben-ha-manual.yml`, respectivement.

`validate_workflow_tree(expected, repository, commit, root, github, workflows)`
est pur. Il vérifie le nom/ID/propriétaire du dépôt, le SHA du Git commit égal
au pin, puis les références SHA de son arbre racine, de `.github` et de
`workflows`. Les deux composants de dossier exigent type tree/mode 040000 ;
le fichier final exige type blob/mode **100644** et SHA complet non nul.
Les URLs des réponses ne sont jamais suivies. Le SHA du blob est une identité
Git rapportée par la source ; aucun contenu n'est téléchargé ou interprété,
aucun hash de contenu n'est recalculé.

Chaque arbre doit porter le SHA demandé, `truncated=false` explicite et une
liste complète d'au plus 10 000 entrées de métadonnées. Chaque entrée a un nom
simple unique, un SHA valide et un couple type/mode reconnu. Doublon, entrée
manquante, chemin imbriqué, tree malformé/tronqué, symlink ou submodule : refus.
Par prudence, les symlinks/submodules sont refusés même parmi les entrées
voisines. Un blob régulier exécutable 100755 peut être voisin ; il ne peut
remplacer le YAML cible. Cette borne concerne seulement les métadonnées GitHub,
sans changement d'un budget Hoben ni ajout de quota RX hoben-live.

`read_workflow_tree(reader, expected, previous=None)` réalise deux parcours
de cinq GET : dépôt, Git commit épinglé, arbre racine, `.github`, `workflows`.
Chaque réponse est validée avant de construire la route suivante à partir de
son SHA. Seul le transport existant reçoit une extension minimale d'allowlist :
`/repos/Guillaume0385/ha-hoben-community/git/trees/<SHA hexadécimal complet non nul>`.
Les sept routes précédentes restent inchangées. Aucun paramètre, `recursive`,
pagination d'arbre, blob, Contents, nouvelle route Actions, branche arbitraire,
main, protection ou secret n'est autorisé. TLS, redirections, taille, délai et
refus expurgés du transport sont conservés.

Erreur API/permission, 401/403/404/429/5xx, statut inconnu, next_page non null,
payload tronqué/malformé ou incohérence de chaîne : **tous les faits UNKNOWN**, y
compris après un premier parcours positif. Les empreintes des deux parcours
doivent concorder ; le recheck relit les dix réponses et refuse un changement
de pin/campagne ou d'identité d'arbre/blob. L'observation figée ne garde que
des faits/erreurs fermés et empreintes non secrètes, jamais les réponses, URL,
message de commit ou exception libre. Une empreinte n'est pas une signature.

Seuls **dépôt, commit épinglé, présence du chemin et identité du blob régulier**
peuvent être attestés. Même en positif : **can_start=false / execution=NOT RUN /
actions_result=FAILURE**, conversion booléenne false. La validation d'un dict
n'authentifie pas sa source ; le Reader/transport doit fournir des réponses
GitHub authentifiées fiables. Les fixtures ne prouvent aucune propriété réelle.

La présence du blob ne prouve **ni son contenu YAML, ni l'enregistrement ou le
chargement du workflow par Actions**, ni le workflow_ref effectivement exécuté.
Le pin portant la ref attendue ne prouve pas à lui seul son appartenance à
experimental ou le HEAD courant : ces liens restent UNKNOWN et relèvent de
preuves distinctes. Restent aussi UNKNOWN protections, dispatch, PR/CI, revue
MANAGER, politique/approbations, claim, mutex, anti-rejeu, recheck après approbation,
UI/main et autorisation. Les lectures concordantes ne constituent pas un
snapshot atomique ou une preuve de fraîcheur globale et ne complètent aucune
admission.

Les [tests](../tests/test_github_campaign_workflow_tree.py) utilisent des faux
Reader/HTTP, avec DNS/sockets interdits : deux chemins, pins et chaîne SHA,
types/modes, doublons/troncature, erreurs à chaque lecture, recheck, données
privées, immuabilité, routes encodées/libres et transport existant. Aucun test
GitHub/Hoben réel, raccordement live, dispatch/rerun/claim, secret, commande,
écriture Modbus, changement de codec/budget, modification main ou fusion DEV.

## Identité des octets du blob — HOBEN-126-WORKFLOW-BLOB-011

Base experimental `e06b469a5c8e28763fb42fd7f80698cfde7cee1e`, après #143.
[github_campaign_workflow_blob.py](../scripts/github_campaign_workflow_blob.py)
consomme une preuve d'arbre distincte de la tranche 010 ; aucun lecteur HTTP
par défaut, token, environnement, interpréteur YAML ou CLI n'est ajouté.
Il n'est raccordé à aucun workflow, gate, collecteur, client HA ou contrat
d'admission. Les shells restent inertes et tous les budgets Hoben inchangés.

### Liaison indépendante aux métadonnées d'arbre

L'observation d'arbre reçoit seulement une projection figée supplémentaire
`BlobIdentity` : attentes fermées commit/campagne/dépôt/ref, SHA du blob choisi,
trois SHA d'arbre et empreinte de liaison. Aucune réponse ou donnée libre n'est
retenue. Les règles de validation d'arbre, faits attestables et refus de 010
restent les mêmes. `blob_identity(observation, expected)` vérifie le type,
les faits, les pins et recalcule leur liaison avant de livrer cette projection.
Ce transfert d'identités Git n'est ni une signature ni une autorisation.

Le nouveau `Expected(campaign, commit_sha, blob_sha, repository=..., ref=...)`
épingle indépendamment les deux SHA complets non nuls, la campagne protocol/ha,
le dépôt exact et refs/heads/experimental. Le blob attendu ne vient jamais du
champ sha de sa propre réponse. La preuve d'arbre doit être issue du lecteur
ou validateur distinct de 010 et sélectionner exactement ce blob pour ce
commit/campagne. Preuve absente, en erreur, incohérente, sans projection ou
d'une autre campagne/commit/blob : refus **avant tout GET blob**.

L'API pure `validate_workflow_blob(expected, tree_observation, payload)` valide
les relations, sans authentifier les objets Python reçus. Le lecteur et
l'appelant restent responsables de la source GitHub authentifiée de la preuve
d'arbre et des pins indépendants. Un objet Python construit, même typé et doté
d'une empreinte cohérente, n'est pas une attestation d'origine. Le module n'élève
jamais cette preuve partielle vers une admission ou un accès aux secrets.

### Corps JSON, base64 et identifiant Git

La réponse exige exactement les champs sha, size, encoding, content, avec
url/node_id optionnels bornés et ignorés ; tout autre champ refuse, y compris
un indicateur truncated. encoding vaut base64, size est un entier strict de
0 à **16 Kio** inclus, content une chaîne d'au plus **24 Kio** avec retours
base64 inclus. Les YAML courants font 1 318 et 1 374 octets : ce plafond laisse
une marge bornée sans prétendre autoriser leur contenu futur.

Le décodage accepte le base64 canonique, non replié ou avec LF/CRLF GitHub ;
espace/tabulation, CR isolé, ligne vide, alphabet/padding invalide ou bits de
padding non canoniques refusent. Longueur encodée, taille décodée et size
doivent concorder. L'identifiant est recalculé selon Git :
`SHA1(b"blob " + decimal_size_ascii + b"\0" + decoded_bytes)` et doit égaler
le SHA attendu **et** le sha rapporté. Un hash des seuls octets sans en-tête Git
ne convient pas. L'identité SHA-1 est celle du format Git, pas une signature ou
un mécanisme d'autorisation ; une empreinte SHA-256 interne lie aussi les octets
décodés et les pins pour le recheck.

Les octets restent locaux à la validation et ne sont jamais retournés,
journalisés, interprétés, persistés ou attachés à l'observation. Le résultat
ne conserve que faits/erreurs fermés et empreintes, sans JSON, texte YAML,
URL, token ou exception. Un blob vide/binaire ou un YAML invalide peut posséder
une identité Git valide : cela n'atteste aucune sémantique ni conformité YAML.

### Lectures, recheck et inconnues

`read_workflow_blob(reader, expected, tree_observation, previous=None)` effectue
seulement deux GET du même blob prouvé. Recheck : mêmes pins, preuve d'arbre
cohérente et même liaison. Toute erreur à la seconde lecture invalide aussi
les faits partiels. Le transport ne gagne qu'une famille exacte supplémentaire :
`/repos/Guillaume0385/ha-hoben-community/git/blobs/<SHA complet non nul>`.
Huit routes précédentes préservées ; aucune URL libre, query, branche, Contents,
récursivité, nouveau endpoint Actions, protection ou secret. Redirections,
JSON tronqué/ambigu, doublons de clés, erreurs API et pagination refusent.
Les bornes HTTP/JSON existantes de 2 Mio, délais et TLS vérifié restent imposés
avant la validation de blob ; cette dernière vérifie ses limites plus basses
avant le décodage. Aucun quota RX Hoben n'est ajouté.

Seuls **liaison au chemin/commit/campagne prouvé, identité des octets Git et
taille cohérente bornée** peuvent être attestés. Toujours **can_start=false /
execution=NOT RUN / actions_result=FAILURE**, conversion booléenne false.
YAML interprété, workflow enregistré/chargé, workflow_ref exécuté, HEAD/ascendance
courants, protections, dispatch, revue, PR/CI, approbations, claim, mutex,
anti-rejeu, fraîcheur/atomicité, UI/main, recheck après approbation et autorisation
restent UNKNOWN. La preuve d'arbre est un instantané distinct ; la double
lecture du blob ne la rafraîchit pas et ne crée aucune preuve atomique globale.

Les [tests](../tests/test_github_campaign_workflow_blob.py) sont uniquement
synthétiques : faux Reader/HTTP, DNS/sockets interdits, vraie validation d'arbre,
deux campagnes, altérations/pins erronés, tailles/limites, base64/troncature,
erreurs HTTP et données privées, recheck, immuabilité et routes interdites.
Le test de non-raccordement d'arbre admet uniquement ce nouveau lecteur de
métadonnées ; celui-ci interdit à son tour tout consommateur runtime.
Aucun test GitHub/Hoben réel, dispatch/rerun/claim, secret, commande, écriture,
activation, promotion main ou fusion DEV. Livraison puis STOP.

## Métadonnées du registre Actions — HOBEN-126-ACTIONS-REGISTRY-012

Base experimental `2a19df8f05fbea245b011ccef182df65f2f1c566`, après #144.
[github_campaign_actions_registry.py](../scripts/github_campaign_actions_registry.py)
est indépendant des lecteurs Git/arbre/blob et du contrat d'admission. Il ne
contient aucun backend HTTP, token, lecture d'environnement, interpréteur YAML
ou CLI. Aucun workflow, gate, collecteur ou client HA ne le consomme.

`validate_registry(campaign, payload)` est pur. `read_registry(reader, campaign,
previous=None)` lit deux fois la même route et peut comparer une observation
précédente. La campagne est une enum protocol/ha exclusivement ; aucun ID, nom,
path, ref, branche ou URL libre n'est accepté. Les routes sont fixées par le
code sous `/repos/Guillaume0385/ha-hoben-community/actions/workflows/` :

- `hoben-protocol-manual.yml` ;
- `hoben-ha-manual.yml`.

Ce sont les deux seules extensions de l'allowlist GET du transport. La liste
des workflows, les IDs numériques, validate.yml, tout autre fichier, sous-route
enable/disable/dispatches/runs, ref/query/pagination, encodage ou redirection
restent interdits. Les neuf routes historiques et leurs limites/TLS/refus
restent inchangés ; aucune nouvelle opération Actions n'est exécutée.

La réponse est un objet unique avec id, path, state obligatoires. ID : entier
strict positif au plus 2^53−1 ; path : chemin `.github/workflows/<fichier>` exact
de la campagne, sans suffixe ref. Les seuls états REST reconnus sont active,
deleted, disabled_fork, disabled_inactivity et disabled_manually. Un autre état,
une valeur approximative, une entrée manquante ou une collection, même de taille
un, refuse. Doublons de clés JSON : refus du transport existant.

Les champs optionnels acceptés sont name/node_id (256 caractères),
created_at/updated_at/deleted_at (64), url/html_url/badge_url (2048), tous textes
sans surrogate ; seul deleted_at peut être null. Ils sont bornés et liés, sans
interprétation de leurs dates/URLs ou usage comme identité de campagne.
Aucun lien du body n'est suivi. Tout champ supplémentaire refuse. L'enveloppe
JSON canonique ASCII est bornée à **16 Kio** ; la borne HTTP JSON préexistante
de 2 Mio reste imposée en amont. Ces limites concernent les seules métadonnées
GitHub, sans quota RX Hoben ni changement de budget.

Les deux lectures doivent concorder sur **tous les champs acceptés**, y compris
optionnels ; ordre des clés indifférent, changement/ajout/disparition refusés.
Le recheck exige aussi la même campagne, le même état rapporté et la même
empreinte. 401/403/404/429/5xx, autre statut, pagination, JSON tronqué/ambigu ou
exception : tous les faits UNKNOWN, état rapporté null, **NOT RUN / FAILURE**.
Un 404 ne prouve pas la non-existence du workflow ni sa disponibilité sur la
branche par défaut. Aucun repli vers les fichiers Git ou un autre endpoint.

L'observation figée ne conserve que faits/erreurs/état/campagne en enums et
empreinte SHA-256 ; aucun ID numérique, nom, URL, body, token, YAML ou exception.
Seuls entrée de métadonnées rapportée, ID valide, chemin et état rapportés
peuvent être attestés. deleted atteste une métadonnée historique rapportée,
pas un workflow disponible ; disabled n'est jamais converti en active.
**Même active conserve can_start=false / execution=NOT RUN /
actions_result=FAILURE**, conversion booléenne false.

Une entrée REST ne prouve ni le chargement du YAML au commit/ref épinglé, ni
workflow_ref/SHA exécutés, sélection UI/main, HEAD/ascendance, dispatch, PR/CI,
protections, revue MANAGER, approbations, claim, mutex, anti-rejeu, recheck après
approbation, fraîcheur/atomicité ou autorisation. Tous restent UNKNOWN.
Le Reader de confiance doit fournir une source GitHub authentifiée ; valider
un dict synthétique n'en authentifie pas l'origine. L'empreinte n'est pas une
signature et les deux GET ne constituent pas un snapshot atomique.

### Limite d'accès observée le 27/10/2026

Le connecteur GitHub a refusé chacune des deux routes exactes avec
`INVALID_ARGUMENT` / HTTP 400 : endpoint public non autorisé par l'outil.
Ce refus précède toute métadonnée exploitable ; ce n'est pas une réponse
GitHub 403/404 et il ne prouve ni droits absents ni non-enregistrement.
**L'enregistrement réel des deux campagnes reste UNKNOWN.** Aucun autre
endpoint, CLI, requête HTTP directe ou modification de permission n'a été
utilisé pour contourner ce refus. Livraison limitée au contrat de lecture et
aux validations vérifiables hors ligne, comme prévu par la consigne MANAGER ;
la preuve opérationnelle reste bloquée par cette limitation d'accès.

Les [tests](../tests/test_github_campaign_actions_registry.py) utilisent
seulement faux Reader/HTTP, DNS/sockets interdits : deux campagnes, états connus,
IDs/chemins/états faux, absence de métadonnées, incohérences et changements,
erreurs/privé, pagination, doublons/troncature, recheck, bornes, immuabilité,
routes interdites et non-raccordement. Les lecteurs précédents sont rejoués.
Aucun réseau Hoben, test réel, dispatch/rerun, secret/environnement, activation,
changement de workflow/gate, codec ou budget, PR main ou fusion DEV.
