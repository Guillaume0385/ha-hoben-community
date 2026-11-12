# #207 D4-C2 — port atomique de réservation simulée, hors ligne

**NOT RUN — aucune admission Live HA.** La tâche prépare uniquement
`.github/scripts/ha-live-claim-port-offline.cjs` et ses tests. Elle ne raccorde
aucun workflow, API GitHub, secret ou client de poêle. Les modules D4-A, D4-B1,
D4-B2 et D4-C1 restent inchangés.

## Contrat du port injecté

`new OfflineClaimPort(store).reserve(context, {timeoutMs, signal})` reçoit un
contexte **fermé**, contenant `repository:{id,full_name}` pour le dépôt exact,
`ref:refs/heads/experimental`, un SHA de merge hexadécimal de 40 caractères,
`contract:hoben-207-ha-live-admission-v1`, `run_id` positif et `attempt:1`.
La clé synthétique est `hoben-207-ha-live-admission-v1:<sha>` : elle n'inclut
**pas** le run, afin de refuser le replay d'un SHA entre runs indépendants.
Les métadonnées enregistrables ne contiennent que ces champs et `version:1` ;
aucun GUID, identité de poêle ou donnée privée.

Le stockage injecté expose **uniquement** `createIfAbsent({key,metadata})` et
`lookup({key})`. Son contrat exige une opération unique de création
conditionnelle atomique ; le lookup est une lecture de contrôle, jamais une
seconde écriture. Le `SharedMockClaimStore` fourni pour les tests effectue
check+insert de façon synchrone sur une Map privée, partagée entre plusieurs
ports indépendants. Il ne possède ni release, suppression, remplacement,
TTL, claim Git réel ni connexion réseau. Capacité fixe de 64 clés, sans éviction.

Seul un ACK `created:true` cohérent **et** une lecture retrouvant exactement
la métadonnée attendue permettent de retourner une **simulation** figée :
`{schema:1,execution:'offline',simulation:'RESERVED_ONLY',admission:'NOT RUN',
complete:false,secrets_allowed:false,live_ready:false}`. Une collision,
fausse confirmation, donnée supplémentaire, échec de readback ou incohérence
conduit à la seule erreur publique `ha_live_claim_port_offline_refused`.
L'entrée, la sortie et les erreurs sont bornées et ne publient aucune exception
du stockage.

Une opération est tentée **une seule fois** par port et clé ; un résultat
ambigu, une erreur, une annulation ou un timeout consomme la tentative locale.
Le budget injectable est de 1 à 5 000 ms (défaut 1 000 ms) pour la création
**et** sa relecture, sans réessai automatique. Un appel externe déjà commencé
peut finir après timeout ; le résultat tardif n'est jamais pris pour un succès.
Un crash après insertion conserve la clé du mock et empêche les autres ports
de la réserver. Un échec avant persistance sur un autre processus ne peut
**pas** être arbitré de façon durable par ce mock : **aucune permission de
réessai aveugle n'est accordée**.

## Limite de preuve et suite interdite

Le mock est volontairement volatile et ne fonctionne qu'à l'intérieur d'un
processus Node. Un ACK, même suivi d'une lecture de contrôle, **ne prouve pas**
la durabilité, l'atomicité, les autorisations ou la sémantique de création du
serveur GitHub. Une implémentation distante pourrait mentir ou répondre après
une erreur ; ce port n'est pas une attestation GitHub authentifiée.
La structure YAML préparée par D4-C1 et le contrat D4-A n'apportent pas non
plus de preuve d'exécution réelle ou d'approbation d'environnement.

Toute véritable réservation, permission GitHub, recheck ou intégration au
workflow HA nécessitera une tâche D4-C3 distincte explicitement autorisée par
MANAGER. Les validations Live HA et HA installé #207 restent **NOT RUN** ;
`admission:NOT RUN`, `complete:false`, `secrets_allowed:false` et
`live_ready:false` sont invariants. #192 cleanup reste ouvert en attente ; V4
reste en lecture seule, TLS vérifié en production, aucune commande de poêle.

## Tests hors ligne

`node --test tests/js/ha-live-claim-port-offline.test.cjs` démontre 32 ports
concurrents sur un même mock : un seul succès simulé ; replay inter-runs,
collision, crash après insertion, faux ACK, lecture mensongère, erreurs,
annulation, timeout, clé/métadonnées fermées, budgets et non-fuites.
`pytest -q tests/test_ha_live_claim_port_offline_207.py` vérifie également
l'exécution Node, les refus expurgés et l'absence de point d'entrée Live.
Les suites D4-A/B1/B2/C1 et les quatre checks CI restent obligatoires.
