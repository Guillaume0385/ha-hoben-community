# #207 D4-D — préparation fail-closed, sans admission Live

TASK_ID : `HOBEN-207-HA-LIVE-E2E-SECURE-READY-004D`.
Cette PR est un **développement partiel hors ligne**, soumis à arbitrage
MANAGER avant fusion. **Live HA : NOT RUN. Home Assistant installé : NOT RUN.**

## Composants actuellement livrés

- `.github/scripts/ha-live-d4-security.cjs` : port REST injecté en lecture
  seule, allowlist de quatre URL GitHub exactes, HTTPS fixé, GET uniquement,
  refus des redirects, réponses HTTP non 200, payloads trop grands, politiques
  inconnues, champs privés, jetons dans erreurs et contextes non canoniques.
  Un 403 protection, environnement non lisible, `rulesets:[]`, bypass,
  reviewer non indépendant ou SHA mouvant => refus fixe. **Même une fixture
  parfaite n'émet aucune autorisation Live** : aucune preuve de durabilité de
  réservation ou de décision MANAGER fraîche/immutable n'est acquise.
- `.github/scripts/ha-live-d4-rest-read.cjs` : transport REST authentifiable
  distinct du mock B2, avec 13 routes permises fixées au contexte, pages 1..8,
  réponses JSON bornées et URLs d'origine exacte. Seul un transport HTTP
  injecté est exercé dans les tests ; aucun appel GitHub réel, aucun droit
  pour claim/secret et aucune transformation de fixture en preuve Live.
- `scripts/ha_live_d4_preflight.cjs` : point d'entrée manuel seul, fail-closed,
  retourne NOT RUN (code non nul), ne lit aucun secret Hoben, ne réserve aucun
  tag et ne possède ni worker, ni appel réseau poêle.
- `.github/workflows/hoben-ha-manual.yml` : la sélection directe
  `hoben-live` ne rejoint plus le collecteur historique. Un job
  `d4_preflight` sans environnement Hoben et avec seulement `contents:read`
  effectue un diagnostic REST authentifié. Même si le diagnostic se déroulait
  normalement, la conclusion reste NOT RUN. L'alias `all` comprend
  historiquement `hoben-live` : il est **temporairement refusé dans son
  ensemble**, afin d'éviter un détour autour du nouveau gate. Cela nécessite
  arbitrage MANAGER avant fusion ; les autres sélections individuelles ne sont
  pas modifiées. Le workflow expérimental Info #186 reste inchangé.
- `.github/scripts/ha-live-d4-observation.cjs` : classification *synthétique*
  d'événements fermés et ordonnés, durée 300 s **à compter d'une réponse
  réellement corrélée**, même génération TLS, événement de livraison inconnue,
  absence EOF/fermeture/timeout et cleanup. Erreurs et cleanup KO => FAILED ;
  candidat/réponse absents => INCONCLUSIVE. Le champ `simulation_only:true`
  interdit toute confusion avec une preuve opérationnelle.

## Prérequis MANAGER non remplis

1. Attester via un lecteur GitHub **effectivement autorisé** le détail de
   `experimental` (l'intégration actuelle reçoit 403), y compris la protection
   contre modifications hors revue, le SHA de HEAD et le pin du workflow.
2. Attester `hoben-live` via l'API native/identité indépendante avec
   `Actions:read` effectivement utilisable ; reviewers, self-review, absence
   de bypass, branche unique, entrée dans l'environnement et approbation
   indépendante propre au run/tentative/déploiement/SHA. Le connecteur actuel
   ne peut pas appeler cet endpoint.
3. Démontrer une réservation GitHub atomique **durable et irréversible** :
   création conditionnelle seule ne suffit pas ; les règles de protection
   des refs/tags, l'absence de capacité de suppression/réécriture et la
   disponibilité d'une preuve non falsifiable doivent être arbitrées.
   Les rulesets visibles `[]` ne prouvent rien. Aucune écriture GitHub ou
   modification Settings n'a été tentée.
4. Attester une décision MANAGER réelle non éditée sur le HEAD/CI exact,
   les quatre checks de la PR puis toutes les pages d'API, l'absence de
   CHANGES_REQUESTED/threads ouverts et les anciens workflows concurrents.
5. Implémenter puis revoir un vrai preflight -> claim -> environnement ->
   recheck complet -> seul step secret -> propriétaire HA/session V4 ->
   cleanup et double validation publique séparée. **Cet ensemble n'est pas
   actuellement réalisé : l'admission demeure NOT RUN.** Le classificateur
   synthétique ne collecte aucune donnée du vrai client.

Aucun drapeau `complete:true`, `secrets_allowed:true` ni `live_ready:true`
n'est délivré. Le 403, 400, une politique absente ou ambiguë provoquent un refus
sans écho de réponse privée. Les mocks D4-A/B1/B2/C1/C2 restent des simulations,
jamais des permissions.

## Validation et retour arrière

Matrice hors ligne :
`node --test tests/js/ha-live-d4-security.test.cjs`,
`node --test tests/js/ha-live-d4-observation.test.cjs`,
`pytest -q tests/test_ha_live_d4_security_207.py` puis Python complet,
Ruff, HA tests et quatre checks de CI sur le HEAD exact. Les tests n'exécutent
aucune requête réelle. Les précédents contrôles D1/D2/D3 et D4-A..C2 sont
conservés.

Avant tout dispatch, MANAGER devra autoriser explicitement une campagne Live
après nouvelle revue du SHA et des preuves. L'arrêt technique attendu est
`NOT RUN` ; un bouton manuel ou une approbation de l'environnement n'est
jamais un permis automatique. Un retour arrière ne doit modifier aucune
protection : fermer la PR avant fusion ou, après décision MANAGER distincte,
revenir aux fichiers de workflow antérieurs par une nouvelle PR examinée.

TLS vérifié `myhoben.fr:465`, V4 en lecture seule, aucun 06/16/22 ou commande,
aucune valeur domestique/GUID/RX secret publiée, aucune supposition sur la
longueur du message Info `0x0C`. La voie #186 et #192 restent séparées.
