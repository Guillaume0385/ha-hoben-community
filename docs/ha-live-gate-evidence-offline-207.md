# #207 D4-B1 — adaptateur de preuves GitHub simulées (hors ligne)

**NOT RUN / NON CONNECTÉ.** Ce lot prépare seulement la lecture conservatrice de
réponses REST **synthétiques**. Le module
`.github/scripts/ha-live-gate-evidence-offline.cjs` ne fait aucun appel réseau,
HTTP, GitHub Actions, Home Assistant ou Hoben et n'importe aucun secret. Aucun
workflow, gate actif, contrôle d'environnement ou collecteur n'est raccordé.
Le contrat D4-A de `ha-live-gate-contract.cjs` reste inchangé.

## Entrée et sortie

`inspect(fixture, now)` prend un instant injecté en millisecondes UTC (epoch) et
un objet JSON strictement borné (65 536 octets, 3 000 nœuds, profondeur 14).
L'entrée exige `execution: offline`, `observed_at` frais (30 s max), un
`context` fermé et les treize sources simulant des réponses GitHub REST :
`branch`, `run`, `prs`, `head_commit`, `merge_commit`, `reviews`, `ci_run`,
`ci_jobs`, `environment`, `deployment`, `approvals`, `workflow`, `concurrency`.
Chacune contient `pages`, des réponses `{request,status,items,next}` ; l'URL
fixe par type de source et chaque index de pagination sont vérifiés. `next`
constitue un **signal dans une fixture**, jamais la preuve que l'API réelle a
été entièrement parcourue. Une pagination signalée inachevée, une URL qui
change, un statut non-200 (dont 401/403/404/429/5xx), une source manquante,
une réponse vide, du JSON ambigu ou un dépassement de budget refusent.

Les contrôles croisent les ID et logins du propriétaire, les dépôts, les acteurs,
la branche protégée `experimental`, l'événement `workflow_dispatch`, la
première tentative, le SHA courant, la PR fusionnée unique, les deux SHA
d'arbres, le run CI de PR et les quatre jobs `tests`, `ha-tests`, `hacs`,
`hassfest`, ainsi que la politique `hoben-live`, ses reviewers indépendants et
les liens présentés pour le deployment et l'approbation. Les sources et champs
autorisés sont explicitement fermés. Les détails inconnus ne sont jamais
interprétés comme des garanties implicites.

La sortie possède les **neuf noms** de preuves D4-A : `branch`, `run`, `prs`,
`trees`, `review`, `ci`, `environment`, `workflow`, `concurrency`. Les seuls
faits numériques ou catégoriels extraits de fixtures sont projetés, et les
éléments non attestables restent à `null`. **Toutes les enveloppes portent
`complete: false`, y compris lorsqu'une fixture paraît cohérente.** Aucun
fournisseur authentifié n'existe dans D4-B1 ; l'absence de preuve extérieure ne
peut pas devenir `complete: true` au moyen d'un champ de fixture. La sortie
figée conserve `execution: offline`, `admission: NOT RUN`,
`secrets_allowed: false`, `live_ready: false`. `requireAttested` refuse toujours
et n'est pas une API d'admission réelle. Un appel éventuel à `OfflineClaims`
(D4-A) refuserait ces preuves incomplètes. Les erreurs publiques utilisent
uniquement `ha_live_offline_evidence_refused`, sans détail brut d'API.

## Ce qui n'est pas attestable par D4-B1

- **Identité et provenance :** une réponse REST fournie comme fixture peut
  contenir les bons ID/login sans attester l'authentification de son transport,
  le `sender` du déclenchement ou la fraîcheur du HEAD au moment d'un futur
  lancement. Ces valeurs devront être reliées aux réponses authentifiées et
  recontrôlées au moment critique.
- **Décision MANAGER :** un commentaire et une review GitHub ne sont pas
  interchangeables. Une review auto-approuvée est impossible comme preuve
  d'approbation indépendante ; une review `COMMENTED` n'est pas `APPROVED` ;
  aucun texte libre n'est converti en décision MANAGER scellée et immuable.
  L'absence de lien vérifiable au HEAD exact, à la CI et aux threads ouverts
  laisse la preuve `review` incomplète.
- **Approbation d'environnement :** une ligne d'approval et un deployment
  n'attestent pas à eux seuls l'entrée du **job collect** après approbation,
  ni le lien unique run/attempt/SHA/deployment, ni la politique effective
  au recheck. Même un objet simulé contenant ces champs reste incomplet.
- **Workflow et mutex :** le YAML courant `hoben-ha-manual.yml` n'installe
  pas la chaîne D4-A preflight/claim/environment/recheck/secrets/worker. Un
  blob YAML n'atteste ni l'ordre sûr avant secrets, ni le claim atomique
  durable anti-rejeu. Une liste GitHub Actions ne détient pas le mutex partagé ;
  `concurrency.runs=[]` ne serait pas une preuve d'exclusivité.
- **Pages et schémas réels :** les enveloppes de test ne représentent pas une
  signature, des en-têtes HTTP authentifiés ou l'exhaustivité des collections
  GitHub. Des champs GitHub absents ou des règles inconnues doivent bloquer
  le raccordement D4-B2, pas être fabriqués ou traités comme `true`.

D4-B2 et D4-C nécessiteront des décisions MANAGER nouvelles pour choisir
les endpoints authentifiés, démontrer l'exhaustivité et vérifier l'intégrité
workflow/claim/mutex/déploiement. Cette PR n'ouvre aucune autorisation Live HA.
Les essais réels #207 restent **NOT RUN** et le cleanup #192 reste non résolu.
Le V4 et l'intégration HA ne changent pas : lecture seule et validation TLS
normale vers `myhoben.fr:465` conservées.

## Validation

- `node --test tests/js/ha-live-gate-evidence-offline.test.cjs` : fixtures
  synthétiques, réponses/pagination lacunaires, actor/repo/SHA/CI incorrects,
  politique modifiée, approval d'un autre deployment ou d'une autre tentative,
  refus sans preuve et absence de fuite.
- `pytest -q tests/test_ha_live_gate_evidence_offline_207.py` : wrapper Node,
  API fermée et refus publics non verbeux.
- D4-A continue à être testé sans modifier son module, ses fixtures ou ses
  invariants. Pas de dispatch ni de test sur un poêle ou HA installé.
