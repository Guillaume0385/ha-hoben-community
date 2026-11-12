# #207 D4-A — contrat d'admission HA Live hors ligne

**NOT RUN — aucune voie Live HA sécurisée ou prête au dispatch par D4-A.**
Le module `.github/scripts/ha-live-gate-contract.cjs` n'est raccordé à aucun
workflow, lanceur, secret ou client HA. Il ne possède ni CLI, ni client GitHub,
ni fonction d'autorisation réelle. Les workflows et gates existants restent
inchangés, notamment le test Info expérimental #186 et le workflow HA distinct.
Le cleanup réel #192 reste non résolu. D1/D2/D3 et B7/B8 ne changent pas.

## Contrat simulé

`OfflineClaims.reserve(snapshot, now)` puis
`recheck(ticket, snapshotAprèsApprobation, preuveEntréeEnvironnement, now)`
forment un modèle local. Les temps sont des millisecondes injectées, croissantes.
Chaque snapshot doit avoir au plus 30 000 ms d'âge ; cette borne de fraîcheur
ne change aucun budget d'observation. Une longue attente d'approbation exige
un nouveau snapshot frais, sans réarmer ni remplacer la réservation initiale.

Les entrées sont des objets JSON fermés, limités en taille/profondeur, sans
getters, cycles, prototypes particuliers ni champs inconnus. Les neuf preuves
`branch`, `run`, `prs`, `trees`, `review`, `ci`, `environment`, `workflow` et
`concurrency` ont chacune une enveloppe `{status: 200, complete: true, data}`.
Une erreur HTTP, page manquante, absence, contradiction ou ambiguïté refuse.
`complete` est **une donnée de fixture**, pas une attestation API.

Le modèle vérifie :

- Dépôt exact (nom et ID), propriétaire `Guillaume0385` (login, ID, type User),
  sender, actor et triggering_actor identiques ; `workflow_dispatch`, tentative
  initiale 1, sélection existante `hoben-live`, workflow HA exact, référence
  `refs/heads/experimental`, SHA égal au HEAD de branche protégée.
- Une seule PR associée, fusionnée par MANAGER/propriétaire vers experimental,
  dépôts head/base identiques ; SHA de merge, HEAD de PR et arbres cohérents.
  Les arbres du HEAD revu et du merge doivent être identiques.
- Décision MANAGER structurée `APPROVED`, non éditée, liée au HEAD/PR/run CI,
  postérieure à la CI et antérieure à la fusion, sans fil non résolu ni demande
  de changements. C'est le **contrat normalisé d'une décision MANAGER**, pas une
  présomption de review GitHub sur sa propre PR.
- CI de PR sur le HEAD exact : `tests`, `ha-tests`, `hacs`, `hassfest`, chacun
  unique, terminé et SUCCESS, même run et SHA. Aucun skipped/neutral, job
  supplémentaire, rerun ou workflow de CI substitué n'est accepté.
- Politique `hoben-live` avec seule branche custom experimental, sans bypass
  administrateur ; reviewers User explicites, règle de self-review et wait timer.
  L'admission refuse dès le préflight une liste vide de reviewers, une politique
  `prevent_self_review=false` ou l'absence de reviewer User indépendant de
  l'acteur. La décision effective d'un reviewer éligible distinct de l'acteur
  est obligatoire, liée au run, tentative 1, SHA, environnement et deployment
  du job collect. Une auto-approbation est refusée, même si d'autres reviewers
  indépendants sont configurés.
  Un statut d'environnement ou deployment ne remplace jamais cette décision.
- Projection statique du futur workflow : SHA exact, environnement hoben-live,
  mutex `hoben-read-only-observation`, `cancel-in-progress: false`, ordre
  preflight → claim → environnement → recheck → secrets → worker.
  Aucune autre observation active n'est admise avant ou après approbation.
- Recheck frais après entrée effective dans l'environnement, avant tout secret ;
  contexte et preuves statiques identiques au preflight. Tout changement de
  reviewers, `prevent_self_review`, identifiant/règle d'environnement, branche,
  SHA, tentative, deployment, review, CI ou workflow refuse et consomme le ticket,
  y compris si les preuves originales sont ensuite restaurées.

La réservation est un **compare-and-insert synchrone en mémoire**, par SHA de
merge et version du contrat, sans appel GitHub ni création de claim réel.
Une seule réservation gagne entre tentatives concurrentes du même SHA. Le ticket
est opaque, lié à l'instance et à la copie du preflight. Un recheck échoué brûle
la réservation ; un succès simulé la consomme. Aucun effacement, reprise ou
éviction ; 64 réservations maximum par instance, puis refus. Cela ne constitue
ni stockage durable, ni verrou distribué : une nouvelle instance ne partage pas
cet historique. Le mutex partagé n'est ici qu'un contrat statique et un état
synthétique vérifié ; il n'est pas créé ou détenu par ce module.

Même le parcours synthétique accepté retourne toujours `execution: offline`,
`admission: NOT RUN`, `secrets_allowed: false`, `live_ready: false` et une empreinte
des seuls faits publics. Le ticket et le résultat sont figés. Aucun résultat ne
peut servir de permis live. Tout refus public est la catégorie fixe
`ha_live_offline_contract_refused`, sans echo d'erreur API ou d'entrée privée.

## Ce qui devra être attesté ultérieurement

D4-B/D4-C ne sont pas autorisées par cette PR. Un futur adaptateur devra obtenir
les données authentifiées GitHub, traiter toutes les pages/erreurs et normaliser
**sans fabriquer** les faits : événement/run réel, HEAD courant, PR et arbres,
décision MANAGER exacte et pertinente, reviews/threads et quatre jobs CI,
politique complète d'environnement (y compris règles inconnues), décision
d'approbation de cette tentative/deployment et entrée effective dans le job.
Si l'API ne permet pas de prouver un lien, le refus doit être conservé.

Il faudra également vérifier le vrai YAML et les sources au commit exact,
conserver l'ordre avant secrets, attester les approbations/recheck et réaliser
un claim atomique durable anti-rejeu avec le vrai mutex partagé. Une liste
d'observations vide n'est pas un verrou atomique ; le claim par SHA ne remplace
pas le mutex entre deux SHA. Le digest public ne signe et n'authentifie rien.
Le schéma de preuve `workflow` décrit l'architecture **future simulée**, pas une
validation du workflow HA actuel. Les helpers/API capables d'autoriser secrets,
créer un tag/ref ou approuver un environnement ne sont jamais appelés ici.

Seul `workflowPath`, helper pur du gate expérimental existant, est réutilisé
pour les chemins de workflows. Aucune protection de #186 n'est modifiée.

## Vérification hors ligne

`node tests/js/ha-live-gate-contract.test.cjs` exerce les mocks GitHub complets,
refus API/identité/main/SHA/review/CI/policy, approbations d'une autre tentative,
recheck obsolète, concurrence/rejeu, limites, types et non-fuites. Le wrapper
`tests/test_ha_live_gate_contract_207.py` l'exécute dans pytest et vérifie les
refus fermés sur des entrées étrangères/privées. Les fixtures sont publiques et
synthétiques ; elles ne consultent aucun serveur et ne créent aucun claim réel.

Ces tests ne prouvent ni sécurité du Live HA existant, ni cleanup réel, ni
approbation effective. Aucun dispatch, test réel, accès HA installé/Hoben,
TLS, commande poêle ou écriture Modbus n'est exécuté. V4 reste en lecture seule,
TLS certificat/hostname vérifiés en production sur myhoben.fr:465. Aucune taille
Info ni frontière applicative nouvelle n'est déduite (`boundary_proven=false`).
