# #207 D4-C1 — audit statique du futur workflow HA Live, hors ligne

**NOT RUN — aucun workflow actif modifié, aucun accès GitHub authentifié,
aucun permis Live HA.** D4-C1 ajoute uniquement la fonction pure
`scripts/ha_live_workflow_static_gate_offline.py::audit_workflow()` et des
tests synthétiques. Elle n'est importée par aucun workflow GitHub Actions.
Le workflow HA actuel `.github/workflows/hoben-ha-manual.yml` est lu tel quel
par un test de régression : son graphe ne possède pas preflight/claim/recheck,
et il est **REFUSED** pour D4. L'audit ne le désactive ni ne le rend plus sûr.

## Contrat d'entrée et retour

La fonction accepte soit un document YAML (chaîne), soit son AST Python
`dict/list` (pour les tests), soit une page simulée D4-B1/B2 avec exactement
`{request,status,items,next}`. La page pointe vers le chemin fixe
`/repos/Guillaume0385/ha-hoben-community/contents/.github/workflows/hoben-ha-manual.yml?ref=<SHA>` :
`status=200`, `next=null`, `items={path,sha,encoding:'base64',content}`.
Le SHA du **commit** attendu est fourni par l'appelant et doit être hexadécimal
(40 chiffres) ; la référence de requête doit correspondre exactement.
Le `sha` de `items` est comparé au SHA-1 **Git blob** calculé localement à partir
des octets décodés. Ceci ne prouve ni transport GitHub réel ni authenticité :
le commit SHA et le blob source sont tous deux des données de fixture.

Le YAML est parsé par un `SafeLoader` dédié : refus des clés dupliquées,
anchors/alias/tags explicites, merges, documents multiples, types ou champs
inconnus, erreurs UTF-8 et ambiguïtés. `on` est bien une clé YAML et non le
booléen YAML 1.1. Bornes : 48 KiB par YAML, au plus 800 nœuds,
16 niveaux, commandes de test limitées à 2 048 caractères. Les errors sont
anonymisées et réduites au statut `REFUSED`.

Le résultat `AuditVerdict` figé indique au mieux `structure:CANDIDATE_ONLY`,
**toujours** `execution:offline`, `admission:NOT RUN`, `complete:false`,
`secrets_allowed:false`, `live_ready:false`. `CANDIDATE_ONLY` signifie
*graphe statique crédible* ; **jamais** READY FOR DISPATCH.

## Structure examinée, sans présumer l'exécution

Le schéma volontairement fermé de **maquettes futures** exige le seul
`workflow_dispatch`/`hoben-live`, le filtre exact owner/repository/ref/
attempt, le mutex partagé et `cancel-in-progress:false`, zéro permission
à la racine, et quatre jobs dépendants :

1. `preflight` sans secret, dépôt/ref/acteur fixes, sortie `admitted` ;
2. `claim` dépend de l'admission, permissions **contents:write** limitées
   à ce job et sortie `claim_ref` ;
3. `collect` dépend d'un claim non vide et possède `environment:hoben-live` ;
   ses étapes sont dans l'ordre checkout épinglé, `recheck` recevant le claim,
   `worker` conditionné au succès et au résultat positif du recheck (seul
   détenteur de `HOBEN_USER_GUID`), `cleanup` sous `always()` ;
4. `result` sans secret, dépend de collect et possède `always()`.

Chaque checkout utilise la révision SHA complète de l'action déjà épinglée,
`ref:${{ github.sha }}` et `persist-credentials:false`. Aucune expression
GitHub dynamique supplémentaire, permission étendue, matrix, action inconnue,
`continue-on-error`, injection anticipée de secret ou étape supplémentaire
ne passe l'audit. Une simulation positive reste un candidat structurel.

**Limite fondamentale :** vérifier les IDs, dépendances, `if`, permissions,
emplacements de secrets et pin ne prouve pas que les scripts `run` exécutent
une vérification réelle, créent un tag durable, recontrôlent GitHub ou nettoient
correctement le runner. Le YAML ne prouve pas non plus les reviewers indépendants,
l'absence de bypass dans *Settings*, le job effectivement approuvé, la
concurrence historique, la fraîcheur de la CI, ni la provenance des réponses.
Les étapes peuvent contenir un corps inopérant ; aucune analyse textuelle de
ce corps ne devient une preuve d'exécution. Aucun code réel de claim/recheck
ou raccordement n'est créé. Tout cela requiert D4-C2 ou une décision spécifique,
revue MANAGER, contrôles GitHub réels et validation fonctionnelle ultérieure.
D4-A, D4-B1 et D4-B2 restent inchangés et non attestants.

Tests : `python -m pytest -q tests/test_ha_live_workflow_static_gate_offline_207.py`
(exécute aussi `node --test tests/js/ha-live-workflow-static-gate-offline.test.cjs`).
Les jeux adversariaux couvrent YAML malformé, données privées simulées,
clés dupliquées, base64, mauvais commit/blob/ref, dépendances inversées,
protection environnement manquante, permissions, secret avant recheck,
annulation de concurrence et suppression de cleanup. Tests uniquement locaux
ou CI ordinaires. **Live HA et HA installé : NOT RUN ; #192 non résolu.**
