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
- Le workflow HA existant est **strictement inchangé** à ce stade.
  L'empreinte SHA256 de ce fichier est épinglée dans
  `.github/info-manual-route.json` du parcours #186 ; le changement initial
  du YAML a provoqué des échecs officiels `manual_info_route_not_connected`.
  Il a été retiré intégralement de la PR, sans toucher au manifeste, au
  routage Info ou aux protections #186. Le CLI `d4_preflight` n'est raccordé
  à aucun job et n'accorde jamais de permis. **Le scénario hoben-live du
  workflow actuel ne doit PAS être exécuté, y compris par `all`** : aucune
  nouvelle campagne n'est autorisée.
- `.github/scripts/ha-live-d4-observation.cjs` : classification *synthétique*
  d'événements fermés et ordonnés, durée 300 s **à compter d'une réponse
  réellement corrélée**, même génération TLS, événement de livraison inconnue,
  acquisitions V4 nouvelles répétées (intervalle sans réponse de 60 s maximum),
  absence EOF/fermeture/timeout et cleanup. Un seul read suivi de 300 s de
  silence ou d'un simple événement TLS ouvert demeure INCONCLUSIVE.
  Erreurs et cleanup KO => FAILED ;
  candidat/réponse absents => INCONCLUSIVE. Le champ `simulation_only:true`
  interdit toute confusion avec une preuve opérationnelle.

**Arbitrage supplémentaire demandé :** autoriser explicitement, dans le
périmètre D4-D, la révision vérifiée de l'empreinte du workflow HA dans le
manifeste fermé #186 (sans altérer son gate, sa politique ou sa liste de
fichiers) et la revue de non-régression. Sans cette autorisation, aucune
modification persistante du workflow HA ne peut satisfaire les tests #186.

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
   un test adversarial D4-D avec deux ports indépendants et un store mutable
   reproduit le rejeu lorsque la référence simulée est supprimée entre deux
   runs : les deux réservations obtiennent ACK et readback, mais aucune n'est
   un permis Live. Cette démonstration impose un refus si le serveur ne peut
   pas garantir une trace durable impossible à réutiliser.
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


## 14/11/2026 — raccordement fail-closed au workflow HA existant

La décision prioritaire MANAGER permet de modifier exclusivement
`.github/workflows/hoben-ha-manual.yml` et de réépingler les quatre
références d’intégrité du YAML / routeur #186. Le scénario manuel
`hoben-live` traverse désormais `admission`, `d4-preflight`,
`d4-claim`, le job `collect` sous l’environnement déjà nommé
`hoben-live`, `d4-recheck`, `d4-capture` et la publication D4-D séparée.
`d4-capture` appelle le vrai `ha_session_live_worker.collect`, le
coordinateur Home Assistant et `ha_live_d4_observer.observe`. Le runtime
Home Assistant est installé depuis les versions figées déjà présentes ;
aucune fixture n’est utilisable en collecte. Le lanceur retire l’identité et
les métadonnées Actions de l’environnement du client avant l’observation.
Les rapports ne contiennent que des scalaires et catégories validés
successivement par Python et Node, puis par un runner sans secret Hoben.

Le choix `all` est refusé globalement avec `NOT RUN` : sa séquence
historique comporte `hoben-live` et ne dispose pas d’un claim individuel.
Les autres scénarios historiques restent sélectionnables individuellement.
Le choix `hoben-live` de `.github/workflows/hoben-manual.yml` demeure Info
#186, inchangé.

**La voie reste volontairement NON AUTORISÉE et NOT RUN.** Les API de
protection de `experimental` (403), l’environnement `hoben-live`
(non exposé par le connecteur) et l’indélébilité de la réservation
(`rulesets:[]`) ne sont toujours pas attestés. Le CLI preflight et
le claim D4 refusent explicitement ; aucun état simulé ne peut ouvrir
`d4-capture`. Le chemin est raccordé techniquement, mais **ni la preuve
d’admission, ni une campagne réelle, ni le fonctionnement du nouveau
worker au contact de Hoben ne sont validés**. MANAGER doit décider des
prérequis indépendants avant tout lancement manuel. Les quatre CI ne
prouvent pas ces protections ou le comportement Live.
