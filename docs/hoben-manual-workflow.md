# Tests Hoben manuels — installation du bouton, phase 1 de #119

La section finale **ARBITRAGE PROPRIÉTAIRE PRIORITAIRE — 24/10/2026** de
[l'Issue #119](https://github.com/Guillaume0385/ha-hoben-community/issues/119)
autorise cette première PR issue de `main` et ciblant `main`, limitée à Actions,
ses tests et sa documentation. Elle ne promeut aucun protocole expérimental,
client HA ou scénario réel sur `main`. La revue indépendante et MANAGER, ainsi
que les quatre checks CI hors ligne, restent requis ; DEV ne fusionne pas.

## Interface GitHub réellement installée

Après fusion MANAGER de la phase 1 sur la branche par défaut `main`, la page
**Actions → Tests Hoben manuels → Run workflow** peut proposer le formulaire
du fichier `.github/workflows/hoben-manual.yml`.
[GitHub exige la présence du fichier sur la branche par défaut](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch)
pour afficher ce bouton. Aucun dispatch n'est réalisé pour vérifier son affichage
pendant le développement.

Le sélecteur natif **Use workflow from** choisit la branche ou le ref dont GitHub
exécute le workflow. Il n'est pas remplacé par un input libre et ne peut pas
masquer `main`. Choisir `main` ne provoque jamais un checkout ou un lancement
implicite du code d'`experimental`.

La liste obligatoire `scenario` propose exactement :

- `h1h2` : campagne H1/H2 ;
- `session-300` : session continue 300 s ;
- `session-reconnect` : scénario de reconnexion par inhibition des Pong ;
- `all` : H1/H2, puis session-300, puis reconnexion, dans cet ordre.

## Phase 1 : toutes les collectes restent NOT RUN

Le seul job est un préflight de cinq minutes au plus. Il ne contient ni checkout,
script Python, sonde, artefact, environnement, accès à un secret Hoben, ni job
aval de collecte. Le token GitHub de l'action épinglée a seulement les droits
de lecture du contenu et des Actions nécessaires à la vérification de provenance.

L'événement doit être `workflow_dispatch`, sur le dépôt exact, par
`Guillaume0385` (identifiant GitHub vérifié), tentative 1. Toute relance nécessite
un **nouveau dispatch manuel** ; Re-run all jobs / failed jobs reste refusé.
Le ref et le SHA Actions/workflow doivent concorder. Seul le ref exact
`refs/heads/experimental` peut atteindre la vérification API : HEAD courant
protégé, provenance et identité du run doivent encore correspondre.

- `main`, autre branche ou tag : `NOT RUN: branch_not_activated` ;
- contexte, acteur ou tentative invalide : refus avant vérification API ;
- preuve API manquante, modifiée ou inaccessible : NOT RUN ;
- contexte experimental recevable : `NOT RUN: experimental_runtime_not_installed`.

Les trois scénarios sont toujours affichés comme NOT RUN, avec leur sélection
explicite. Le job est volontairement en échec ; ce n'est ni un test réel échoué,
ni une réussite simulée. Aucun commentaire d'admission MANAGER n'est demandé.
Le mutex partagé `hoben-read-only-observation`, sans annulation et avec file
d'attente, est conservé ; aucun réglage de dépôt n'est modifié.

## Dépendance : seconde PR sur experimental après fusion de la première

Le fichier doit aussi exister au même chemin sur le ref choisi. Avant report,
le bouton sur `main` ne rend donc pas le fichier disponible sur `experimental` ;
un dispatch vers un ref sans ce fichier n'est pas un lancement valide. Ne pas
utiliser une ancienne voie, un rerun ou un autre checkout pour le contourner.

Après validation/fusion de cette première PR par MANAGER, une **seconde PR**
reportera l'interface sur `experimental` et raccordera les collecteurs existants.
Elle devra conserver acteur/ref/SHA, revue/CI exactes, anti-rejeu, approbations
d'environnement effectivement requises et recheck avant secrets, isolation des
collecteurs et de la publication, lecture seule et TLS vérifié `myhoben.fr:465`.
La décision MANAGER par commentaire pré-fusion est supprimée pour cette nouvelle
voie manuelle ; elle n'est pas remplacée par une approbation fabriquée.

Les plafonds existants demeurent : H1/H2 six sessions par hypothèse, 90 s et
1 Mio RX par session ; session-300 300 s utiles / 360 s de processus ; reconnexion
600 s de processus avec maximum fonctionnel 360 s ; suite 1020 s. Les critères
EOF, nouvelle génération, 120 s stables et lecture corrélée restent requis.
La phase 2 devra distinguer SUCCESS, FAILURE, INCONCLUSIVE et NOT RUN, arrêter
`all` en cas de condition bloquante et nommer les scénarios non exécutés.

Aucune activation de `main` par simple copie de fichiers : elle exigera une
décision propriétaire distincte après installation et validation de ses contrôles.
Aucun test réel par DEV ; étape 8 HA toujours suspendue.

## Voies retirées et historique

Les trois anciens workflows `live-validation.yml`, `manager-live-hoben.yml` et
`opened-client-boundary.yml` sont retirés de `.github/workflows/`. Leurs copies
figées restent dans `tests/fixtures/retired_workflows/`, uniquement pour les
régressions hors ligne. GitHub ne les exécute pas depuis ce dossier. Les scripts
et codecs historiques restent en place ; aucun workflow actif ne les appelle.
`validate.yml` et `publish-release.yml` sont inchangés.

Retirer un fichier empêche ses nouveaux déclenchements depuis cette définition ;
cela n'annule pas un ancien run déjà créé. Le propriétaire doit contrôler les
runs historiques avant toute activation ultérieure. DEV n'en relance ni n'en
annule aucun à l'occasion de cette PR.

Cette phase ne retire pas encore les définitions propres à `experimental` :
leur suppression appartient à la seconde PR. Les anciennes procédures ci-dessous
et dans les archives ne constituent aucune autorisation de les lancer.
