# Demande H1/H2 depuis GitHub Work — préalable #51 de #48

**Campagne H1/H2 : NOT RUN. Nouveau canal réel : non encore prouvé.**
CODEX DEV prépare la passerelle et ses simulations hors ligne. La PR #49 reste
en brouillon au SHA `00215ef0589d34e9cf9c2ed5f3c3d2fe9f51ee06` ; #48 reste
`state:blocked` en attente d'observations et d'une décision protocolaire.
La livraison #51 peut seule être revue/fusionnée séparément. Elle ne livre pas
le routeur, ne clôture pas #48 et ne débloque pas les tâches 2–6.

## Faisabilité et confiance

Le MANAGER a vérifié le canal `pull_request_target: labeled` : le run
[37741697334](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/37741697334)
de l'ancien gate utilise `Guillaume0385` comme acteur et triggering actor,
tentative 1. Sa connexion Work peut ajouter/retirer un label puis lire les
commentaires, statuts et runs. Elle ne fournit pas dispatch/écriture de variable.
Cette preuve ne teste **pas** le nouveau workflow #51 ni H1/H2 : son propre
dry-run est obligatoire après installation. Une autre GitHub App dont
l'acteur/sender diffère est refusée.

La politique main fixe le seul scénario `h1h2`, ce candidat et le certificat
**public** fourni par MANAGER dans
[#48, commentaire 6054724678](https://github.com/Guillaume0385/ha-hoben-community/issues/48#issuecomment-6054724678),
empreinte DER SHA256
`f0209da5d964c02b9733610bfb4457f7bebd24fdfd32934e1165460bf0ab3246`.
MANAGER a attesté une conservation durable de la clé privée correspondante.
La clé/phrase secrète restent hors GitHub. Aucune variable d'environnement à
écrire depuis Work n'est nécessaire. Ne pas remplacer ce destinataire pour
contourner un échec : toute rotation impose revue et installation sur main.

La revue indépendante #5452887287 sur le candidat est `COMMENTED` par
`Guillaume0385` via la connexion utilisée pour CODEX REVIEW, **pas GitHub
APPROVED**. La politique main atteste cette décision précise (SHA, identité,
état, digest du corps), vérifiée via l'API. La revue indépendante de #51 et la
décision MANAGER d'installation doivent explicitement confirmer cette
attestation du rôle REVIEW. Le gate ne déduit jamais une autorisation d'un
texte libre « MANAGER/CODEX REVIEW approuve ». Revue supprimée/modifiée,
changements demandés, thread non résolu ou nouveau HEAD refusent la demande.
Une nouvelle revue/HEAD exige une politique main séparément revue.

La décision effective est calculée par reviewer à partir des reviews actives
`APPROVED` et `CHANGES_REQUESTED`, dans leur ordre chronologique. Un commentaire
`COMMENTED`, une review `PENDING` ou la dismissal d'une autre review ne lève
jamais une demande de corrections. Seule sa propre dismissal explicite ou une
approbation ultérieure de ce reviewer la remplace. Ce contrôle vaut à l'entrée
et au recheck après attente de l'environnement ; l'attestation exacte et les
threads restent vérifiés séparément.

## Installation séparée et prérequis GitHub

1. Faire examiner #51 indépendamment par CODEX REVIEW, vérifier `tests`,
   `ha-tests`, `hacs`, `hassfest` sur son HEAD et enregistrer la classification
   MANAGER selon `AGENTS.md`. La classification MANAGER du 2026-10-08 exige la
   validation authentifiée pré-merge existante pour #51 après corrections et
   review indépendante du HEAD final. Suivre son gate existant. Seul MANAGER
   fusionne #51.
2. Vérifier main protégée et `hoben-live` avec **une seule** politique de
   déploiement : type `branch`, nom `main`, `custom_branch_policies=true`,
   `protected_branches=false`. Aucun tag, wildcard ou branche candidate.
   Une ancienne exception ou politique inaccessible à l'API refuse même le
   dry-run (`environment_policy_unverified`/`github_or_configuration_unavailable`).
   MANAGER constate et documente le refus. Toute correction de droits,
   protections ou secrets relève du propriétaire avec autorisation distincte,
   hors de cette tâche ; ni DEV ni la tâche MANAGER ne modifient ces réglages.
3. Vérifier que la politique réelle du dépôt public permet ce workflow
   `pull_request_target` et le checkout v7 **same-repository** épinglé. Ne pas
   supposer une exception ni contourner un refus. Les nouvelles politiques
   publiques sont annoncées en évaluation puis appliquées à partir du
   2 novembre 2026 aux dépôts concernés. Le dry-run installé fournit la preuve
   pour ce dépôt/main. Un refus GitHub avant le gate n'autorise aucun live.
4. Le job main doit pouvoir lire PR/revues/checks/runs et la politique
   d'environnement (Actions read), créer un tag d'audit (Contents write) et
   publier un statut (Statuses write). Le publisher lit le seul rapport public
   et commente #49. Aucun PAT/secret GitHub supplémentaire ni permission
   d'administration. Le runner candidat a uniquement des permissions de
   lecture. Les tags `hoben-boundary-*` ne sont pas des tags de release.
5. Vérifier le secret existant `HOBEN_USER_GUID` dans `hoben-live` et éventuellement
   `HOBEN_DEVICE_GUID`. Ne jamais les recopier dans Work, une Issue, un argument
   ou les logs. Vérifier la conservation privée de la clé de déchiffrement.
6. Préparer, si absents dans les labels du dépôt, les deux noms
   `manager-hoben-boundary-dry-run` et `manager-hoben-boundary-live`. Leur
   création n'autorise rien. Ne les appliquer qu'après installation selon
   la procédure ci-dessous, avec la connexion MANAGER dont l'acteur est prouvé.

MANAGER utilise les opérations GitHub déjà disponibles dans Work. Une opération
ou configuration inaccessible impose un refus documenté, sans contournement.
Toute modification nécessaire de droits, protections ou secrets relève du
propriétaire avec autorisation distincte. La passerelle et la tâche MANAGER ne
changent pas ces réglages ; aucune automatisation n'est modifiée par DEV.

Références GitHub :
[sécurité pull_request_target](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target),
[checkout v7 et têtes de forks](https://github.blog/changelog/2026-06-18-safer-pull_request_target-defaults-for-github-actions-checkout/),
[main et environnements](https://github.blog/changelog/2025-11-07-actions-pull_request_target-and-environment-branch-protections-changes/).

## Dry-run obligatoire depuis Work

1. Relever la main courante **après installation** et le HEAD complet inchangé
   de #49. Vérifier #48 ouverte avec son seul `state:blocked`, #49 ouverte/en
   brouillon, quatre checks exact-HEAD réussis, revue attestée présente, aucun
   changement demandé ni thread non résolu. Relire diff/remarques/confidentialité.
   Ne lancer aucune autre voie live pendant le parcours.
2. Retirer les deux labels réservés de #49 s'ils sont présents. Ajouter
   **uniquement `manager-hoben-boundary-dry-run`** via la connexion MANAGER.
   Un label déjà posé ne génère pas un événement neuf. Le job dry-run n'a
   aucun environnement/secret Hoben et n'importe pas le candidat : zéro DNS,
   transport ou connexion Hoben. Le gate lit seulement la politique GitHub
   de l'environnement, sans accéder à ses secrets.
3. Lire le nouveau run **MANAGER H1 H2 label request** : événement
   `pull_request_target`, acteur/triggering actor `Guillaume0385`, tentative 1,
   HEAD = main relevée. Le tag atomique
   `hoben-boundary-dry-run-<mainSHA>-<candidateSHA>` pointe sur main et mémorise
   son `run_id`. Ne jamais modifier/supprimer un claim pour refaire un essai.
4. Attendre le succès réel de `request`, `dry-run`, `publish`, avec `observations`
   sauté. Sur #49, lire le commentaire du même run/main/candidat : `dry_run_pass`,
   `no_hoben_connection`, zéro session. Le statut candidat
   `hoben-boundary-dry-run/<mainSHA>` et l'artefact public
   `boundary-dry-run-report-<run_id>` doivent correspondre. Le vrai chiffrement
   CMS AES-256-GCM/RSA-OAEP-SHA256 est exercé avec le destinataire épinglé.
   Il ne prouve pas à lui seul que MANAGER sait encore déchiffrer.
5. Refus, run absent, API indisponible ou résultat partiel **ne vaut pas PASS**.
   Ne pas demander live, rerun ou relancer en boucle. Corriger le préalable par
   décision/revue appropriée ; un claim consommé exige une nouvelle main revue
   puis un nouveau dry-run. Un vieux run/gate/label n'est pas cette preuve.

## Demande live après preuve et décision MANAGER

Le label live signifie explicitement : « J'ai examiné le code complet, ce HEAD
et cette main, les remarques/revues et quatre checks ; je fais confiance au
candidat pour recevoir le credential dans cette campagne H1/H2 bornée ».
MANAGER enregistre sa décision exact-HEAD dans #48/#49 avant l'ajout. Ce
commentaire assure la traçabilité humaine ; l'autorisation machine vient de
l'événement authentifié et des vérifications serveur, jamais du texte.

La tâche MANAGER autonome peut prendre et enregistrer cette décision ponctuelle
depuis Work, y compris lors d'un passage planifié, après tous les prérequis.
L'autorisation propriétaire couvre déjà cette campagne : aucune nouvelle
demande manuelle utilisateur n'est requise. Le tick seul ne constitue pas une
décision et ne justifie jamais un lancement systématique, un rerun ou un retry.
DEV et PRE-REVIEW ne peuvent ni demander la campagne ni poser ces labels.

1. Relever à nouveau les SHA. Main changée : réexaminer puis refaire le dry-run.
   Candidat changé : politique main/revue nouvelle obligatoire. Arrêter jusqu'à
   ces préalables ; ne pas réécrire #49 pour satisfaire le gate.
2. Retirer le label dry-run. Ajouter **uniquement `manager-hoben-boundary-live`**
   sur #49. Ne pas poser simultanément les deux labels ni employer
   `manager-live-hoben` comme raccourci. Suivre le run lié au commentaire/statut
   et au tag `hoben-boundary-live-<mainSHA>-<candidateSHA>`.
3. Le gate vérifie le vrai dry-run du même couple et réclame cette phase une
   seule fois. Un échec/annulation consomme aussi le claim. Le groupe existant
   `hoben-boundary-campaign` sérialise H1/H2 ; les autres runs Hoben actifs sont
   refusés à l'entrée et après attente d'environnement. MANAGER ne lance aucun
   autre gate live pendant la collecte. `hoben-live` et ses approbations restent
   applicables ; une seconde vérification serveur complète précède le seul
   step recevant les secrets.
4. Le point d'entrée **main** `run_boundary_request.py` valide son propre
   contexte label et les checkouts, préflighte certificat/chiffrement avant
   import candidat ou lecture du credential, puis appelle le collecteur #49
   épinglé comme bibliothèque. Il ne simule pas un dispatch et ne modifie pas
   son CLI dispatch-only. Scénario fixe : H1 puis H2, **90 s**, six sessions
   maximum chacun, pauses 0/100 ms/1 s ×2, espacement 15 s, arrêts anticipés
   existants. Aucun script/hôte/chemin/SHA/durée/mode fourni par l'utilisateur,
   boucle de retry, écriture poêle, installation candidate ou credential Git
   persistant. Les autres scénarios exigent une PR de gouvernance distincte.

## Lecture du résultat et retour à #48

Lire depuis Work le commentaire de #49 avec le run, scénario, SHA main/candidat
et raison bornée. Le tableau anonymisé détaille mode, arrêt, contexte d'ouverture,
H1/H2/comparaison et V4 émis/corrélé. Le publisher main, runner frais sans secret
Hoben/code candidat, télécharge **uniquement le rapport public**, revalide
schéma/provenance/categories/bornes, puis publie commentaire/summary/statut
`hoben-boundary-live/<mainSHA>`. Rapport absent/malformé : pas de succès.
Le publisher doté du token d'écriture ne télécharge jamais le ciphertext.

| Résultat | Sens |
| --- | --- |
| `pending` | Demande unique acceptée ; run lié à suivre, pas de résultat acquis |
| `dry_run_pass` / `no_hoben_connection` | Canal et chiffrement synthétique vérifiés ; zéro observation Hoben |
| `inconclusive` / `hypotheses_unproven` | Collecte/exports/publication achevés ; frontière non prouvée |
| `failure` / `job_or_report_failed_or_incomplete` | Job, interruption, export ou rapport incomplet |
| `refused` / raison du gate | Précondition invalide ; aucune permission live |

Un doublon ne remplace pas le statut d'une demande déjà réclamée. Un nouveau
HEAD rend les anciens résultats inapplicables. Comparer run réel, tentative,
SHA, scénario et rapports ; un check vert ne prouve jamais une frontière.

Artefacts distincts, **sept jours** :
`boundary-ciphertext-<candidateSHA>-<run_id>` contient seulement `captures.cms` ;
`boundary-report-<candidateSHA>-<run_id>` seulement le rapport compact
`report.json`. Les annotations complètes schéma 2/temps, octets, journaux et
identité attribuée restent dans le ciphertext. Aucun fallback en clair.
Téléchargement/déchiffrement/analyse suivent la
[procédure de campagne](opened-client-boundary-campaign.md#récupération-et-analyse-privée-après-le-run),
hors dépôt et avec la clé privée MANAGER. SIGKILL/runner perdu ou échec crypto
peut empêcher la récupération : aucun artefact complet n'est alors revendiqué.

Après analyse privée, MANAGER consigne seulement provenance, conclusions et
limites anonymisées dans #48, puis décide de lever ou maintenir son blocage.
DEV reprend la même Issue/branche/PR selon son état et la décision de reprise.
Rien ne clôture automatiquement #48, fusionne #49 ou lance la roadmap suivante.

## Amendement court proposé pour l'automatisation MANAGER

> Pour #48, après installation/revue indépendante de #51 sur main, vérifier les
> prérequis/SHA, demander via Work le dry-run unique avec
> `manager-hoben-boundary-dry-run` et lire son run/statut/rapport. La tâche
> MANAGER autonome, y compris lors d'un passage planifié, peut décider une seule
> campagne déjà autorisée par le propriétaire, après PASS réel et décision de
> confiance exact-HEAD enregistrée, sans nouvelle demande manuelle utilisateur.
> Retirer ce label puis demander
> `manager-hoben-boundary-live`. Attendre la demande unique, lire les catégories
> anonymisées et faire analyser privément le ciphertext avant toute reprise de
> #48. Tick périodique, manque de crédits, ancien label/run ou statut vert ne
> vaut jamais autorisation nouvelle ; aucune campagne live récurrente, rerun,
> suppression de claim ou boucle de relance.
> Si une configuration GitHub manque ou est inaccessible, constater/documenter
> le refus. Toute modification de droits, protections ou secrets relève du
> propriétaire avec autorisation distincte, hors de cette tâche. DEV/PRE-REVIEW
> ne pose aucun label de demande live.

Ce texte est prêt à examiner ; DEV ne modifie pas l'automatisation MANAGER/REVIEW.
