# HOBEN-81-E7-CHAT-WIRING-002 — audit de raccordement hors ligne

> Étape 7/8, `experimental` uniquement. Cette note ne constitue ni une admission
> GitHub ni une validation réelle. **Session-300 : NOT RUN ; scénario de reprise :
> NOT RUN** tant que le verrou structurel reste installé.

## Deux voies distinctes

| Point | Chemin H1/H2 historique | Suite expérimentale V4 |
| --- | --- | --- |
| Workflow | `.github/workflows/hoben-experimental.yml` | `.github/workflows/hoben-session-300.yml` |
| Politique | `.github/config/hoben-experimental.json` : `scenario=h1h2` | `.github/scripts/session-suite-gate.cjs` : admission distincte `session-suite` |
| Exécution | `scripts/launch_experimental_boundary.py` → `scripts/run_experimental_boundary.py` → `scripts.probe_opened_client_boundary.campaign_with_signals` → `scripts.boundary_capture.run_campaign` | `scripts/launch_session_suite.py` → `scripts/run_session_suite.py` → `scripts.session_suite.observe_suite` |
| Gestionnaire | Sonde historique H1/H2, **pas** le gestionnaire V4 partagé | Factory réelle `V4Lifecycle(session_factory=partial(V4Session, ...))`, `Session300`, puis `SessionReconnect` / `NoPongAfter120` |
| État opérationnel | Voie H1/H2 existante, budgets propres inchangés | `quarantine-installation` refuse inconditionnellement **avant** `dry-run` |

Le simple fait que `V4Session` et `V4Lifecycle` soient importables ne
démontre donc pas le raccordement du chemin H1/H2 à la suite 300 secondes.
La suite V4 est un **autre** workflow, avec son lanceur, sa provenance,
son budget et son environnement après admission. Il ne faut ni renommer la
sonde H1/H2 en « session-300 », ni détourner son `scenario` ou ses rapports.

## Verrou et chemin de refus

Le job initial `quarantine-installation` du workflow V4 possède
`permissions: {}`, aucun checkout, aucun environnement ni secret et une
étape fixe qui écrit **les deux `NOT RUN (quarantine_not_installed)`**, puis
termine avec `exit 1`. `dry-run` en dépend ; son échec empêche admission
et collecte avant le moindre secret Hoben. Aucun drapeau d'environnement,
paramètre d'entrée ou scénario de repli ne débloque ce chemin.

Les tests déterministes du dépôt vérifient l'exécution shell du refus,
l'absence de permissions et le graphe. Les nouveaux contrôles croisés
`tests/test_session_300_workflow.py` vérifient en outre la séparation
historique/V4 et les imports du **vrai** gestionnaire dans la factory.
Ces assertions statiques ne remplacent ni un test d'admission réel ni une
preuve de session continue pendant 300 secondes.

## Raccordements existants et dépendances restantes

1. **Déjà présent, mais non accessible en réel** : le lanceur fixe de suite
   impose 360 s, puis 600 s, avec plafond global de 1020 s ; le moteur
   séquentiel appelle `observe_300` puis la reprise seulement si le premier
   résultat est `continuous_300s` ou `reconnected`. La factory de
   `run_session_suite.py` utilise les vrais `V4Session`/`V4Lifecycle`,
   en lecture seule ; ce code ne constitue pas une autorisation d'exécution.
2. **Non livré** : le producteur v3 L7 CODEX DEV, nécessaire aux observations
   propriétaires et à l'agrégat RX de 150 s prévus par le contrat L6ter.
   Aucune copie locale, aucun patch non publié et aucun consommateur actif
   ne sont supposés disponibles. Les validateurs v3 ne sont **pas** un
   producteur v3 ; les producteurs installés restent v2.
3. **Décisions ultérieures distinctes** : terminer et faire revoir L7 par
   MANAGER, établir l'admission et le routage versionnés du rapport attendu
   dans une tranche séparée, puis seulement instruire une éventuelle
   levée du verrou. Ce travail exige un nouveau périmètre MANAGER et une
   revue/CI propres. Ne pas modifier ici L1–L7, les contrats v1/v2/v3,
   les voies historiques, les workflows, les gates ou les budgets.

Le préfixe `OpenedClient` de 48 octets ne prouve toujours aucune longueur
totale universelle. Aucune règle de cadrage nouvelle n'est introduite.
Les deux scénarios réels restent **NOT RUN** ; la validation fonctionnelle
de l'étape 7 reste ouverte et l'intégration Home Assistant de l'étape 8
reste suspendue.
