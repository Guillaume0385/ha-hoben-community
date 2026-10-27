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
`actions/runs/<id>/attempts/1/jobs`. Aucun lien ou URL du body n'est suivi.
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
origine alternative, méthode HTTP ou header libre. Seules les six routes du
lecteur sont admises : dépôt, Git commit par SHA hexadécimal complet non nul,
PR/run par ID entier positif, reviews PR et jobs du run/tentative 1. Query dans
path, traversée, encodage de chemin, alias de dépôt, sous-routes et autre hôte
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
