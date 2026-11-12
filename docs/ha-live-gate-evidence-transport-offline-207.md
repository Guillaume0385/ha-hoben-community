# #207 D4-B2 — collecte simulée GitHub REST, exclusivement hors ligne

**NOT RUN ; aucune preuve GitHub authentifiée, aucun Live HA autorisé.**
Le module `.github/scripts/ha-live-gate-evidence-transport-offline.cjs` ne
contient pas de client HTTP, d'identifiants, de jetons ou d'accès aux variables
d'environnement. Il ne s'exécute dans aucun workflow. Son seul point d'entrée
`await collect({mockTransport, context, now, signal})` reçoit un transport
explicitement fourni par le test ; il ne construit jamais ce transport.
Le contrat du transport est `request({method:'GET', url, signal})`, avec une
réponse synthétique `{status, headers, body}`. L'injection n'est **pas** une
preuve d'authenticité : un appelant malveillant pourrait implémenter un autre
transport. Ce module n'est donc pas une frontière de sécurité de production et
ne doit pas être raccordé à un environnement doté de secrets.

## Routes fixes et vérification

Le contexte impose l'identité constante du dépôt et de son propriétaire, la
branche `experimental`, les SHA hexadécimaux, les identifiants numériques, un
premier `workflow_dispatch` et le scénario `hoben-live` de la voie HA séparée.
À partir de ce contexte, le collecteur calcule les **13 routes D4-B1** :
`branch`, `run`, `prs`, `head_commit`, `merge_commit`, `reviews`, `ci_run`,
`ci_jobs`, `environment`, `deployment`, `approvals`, `workflow`, `concurrency`.
Le préfixe de chaque URL est invariablement `https://api.github.com/repos/Guillaume0385/ha-hoben-community`.
Seules les méthodes GET sont émises ; aucune URL fournie par une réponse n'est
exécutée. Un status 3xx, un champ `Location`, une méthode mutatrice, un changement
d'hôte, de route ou de query, ou une réponse manquante provoquent un refus.

Les collections emploient uniquement `per_page=100&page=N`, à partir de 1.
La seule forme acceptée du header `link` est une indication **exacte** du prochain
chemin calculé par le collecteur, avec `rel="next"`. Les headers autorisés sont
`date`, `content-type` fixé à `application/json`, et `link` optionnel.
Toute redirection, autre relation, lien ambigu, duplication d'identifiant entre
pages, saut de page, date HTTP invalide ou périmée est refusée. Aucun header
`Date` fourni par un mock n'atteste la fraîcheur d'une réponse réelle.

Bornes : 8 pages par source, 24 requêtes cumulées, 100 éléments par page,
24 KiB par réponse, 65 536 octets JSON pour l'entrée complète de D4-B1,
350 ms par requête et 5 s pour une collecte. Les promesses suspendues sont
bornées par timeout avec signal d'annulation. La pagination se termine
explicitement sans `next` ; un lot de 100 éléments sans `next` est ambigu et
refusé. **Cette règle n'établit pas l'exhaustivité de la liste distante** :
aucune source distante n'est contactée ou attestée.

## Sortie et refus

`collect` renvoie `{execution:'offline', admission:'NOT RUN',
secrets_allowed:false, live_ready:false, fixture, evidence}`. `fixture`
reprend exactement le schéma d'entrée de `inspect()` D4-B1 :
`{execution,observed_at,context,sources}` et treize enveloppes `pages` de
`{request,status,items,next}`. `evidence` est le résultat de l'appel à
`inspect(fixture,now)` ; chaque preuve est **`complete:false`**.
Les objets retournés sont figés, et `requireAttested()` D4-B1 continue à
refuser sans aucune API d'admission Live. L'absence, les incohérences de run,
SHA, PR, jobs ou approbation et les réponses ambiguës échouent avant sortie.

Tout refus est réduit à `ha_live_offline_transport_refused` : aucune réponse
brute, exception de transport, URL non autorisée ou identité sensible n'est
répercutée. La copie JSON refuse les getters, les prototypes étrangers, les
cycles, les clés de secrets et les budgets excessifs. Des valeurs mockées
restent **non authentifiées** ; une valeur de string éventuellement sensible ne
doit jamais être fournie comme fixture. Les essais unitaires ne contiennent que
des valeurs inventées.

## Portée et validation

Tests Node adversariaux et wrapper Python (statuts 401/403/404/429/5xx,
redirections, headers, pagination, doublons, octets, délais, abort, identité et
D4-B1 `inspect`/`requireAttested`). Les suites D4-A et D4-B1 ne sont pas
modifiées. Aucun workflow, gate réel, tag/claim, approbation, mutex, client HA,
poêle, secret ni connexion GitHub réelle n'est créé. Les campagnes Live HA et HA
installé restent **NOT RUN**. Le cleanup réel #192 reste en observation et
n'est pas déclaré corrigé. L'étape suivante requiert une décision MANAGER
distincte et une attestation authentifiée que ce helper ne fournit pas.
