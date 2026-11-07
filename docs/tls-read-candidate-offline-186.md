# #186 — comparaison hors ligne des candidats de lecture TLS

Tâche `HOBEN-186-TLS-READ-CANDIDATE-OFFLINE-001`, base HA
`13703b09b2fa07cfcd5e2ab97ba823149f2a29d7`, branche cible `experimental`.
**Résultat : INCONCLUSIVE pour la longueur et la frontière de tout Info 0x0C.**
Le banc reproduit des décisions statiques documentées de l'APK ; il ne lance
ni Android, ni le code natif/.NET original, ni une session réelle.

## Sources épinglées et contrat de comparaison

- [Consigne MANAGER #186](https://github.com/Guillaume0385/ha-hoben-community/issues/186#issuecomment-6713923452).
- [RE PR #4](https://github.com/Guillaume0385/MyHOBEN_extract/pull/4), HEAD
  `e2f88b0dfcd130b9b9f9e52d69a900d8ded48b6e` :
  [rapport Info](https://github.com/Guillaume0385/MyHOBEN_extract/blob/e2f88b0dfcd130b9b9f9e52d69a900d8ded48b6e/reports/2026-11-06-info-0c-framing.md),
  [contrat de réception](https://github.com/Guillaume0385/MyHOBEN_extract/blob/e2f88b0dfcd130b9b9f9e52d69a900d8ded48b6e/analysis/receive_boundary_contract_apk34.md),
  [complétions réseau](https://github.com/Guillaume0385/MyHOBEN_extract/blob/e2f88b0dfcd130b9b9f9e52d69a900d8ded48b6e/analysis/network_receive_completion_apk34.md).

`tests/tls_read_candidate_186.py` livre exactement les mêmes octets synthétiques,
dans le même ordre et avec les mêmes découpages, à deux consommateurs mémoire
asynchrones indépendants. Une entrée désigne une **complétion de lecture de
plaintext prescrite**, pas un paquet TCP, un enregistrement TLS ou une trame
applicative prouvée. Les tailles `delivery_bytes` sont en octets effectivement
retournés à chaque consommateur. HA peut cesser de lire avant le modèle APK.
Chaque complétion est limitée à 512 octets pour respecter la capacité du buffer
APK (`06000C21:0108–0120`), sans assimiler cette capacité à une taille de message.

Le modèle APK choisit au plus une branche par complétion, sans accumulation,
séparation ni sauvegarde du suffixe. Les décisions de Pong et de nouvelle lecture
logique sont des événements : **aucune émission, commande ou reprise réelle**.
Info/02 compte cumulativement les occurrences : les trois premières sollicitent
une lecture logique, les suivantes transfèrent toute la livraison. Aucun reset
sur un succès n'est ajouté. Info/04 n'a pas de limite dédiée prouvée ici.
Les candidats 07/0E/1B représentent seulement l'appel du décodeur commun
`06000C47:0679–0708` ; son résultat et le traitement UI ne sont pas émulés.

Le second consommateur appelle le **vrai `ExperimentalV4Framer.feed`** avec les
options de classification B4 et de récupération DataUpdated. Un événement de
framer complet ne suffit pas à prouver un décodage ou une corrélation. Les champs
`correlated_reads=not_executed` des comparaisons isolées le rendent explicite.
Les tests séparés des vrais `V4Session`, client, lifecycle et coordinator HA
vérifient ces preuves supplémentaires et le nettoyage, sans modifier leur code.

## Matrice et différences observées

Toutes les valeurs de discriminateur/sous-code ci-dessous sont **synthétiques**.
`|` sépare deux complétions ; `+` réunit des éléments dans une seule complétion.
Les messages connus des fixtures sont annotés par construction, jamais retrouvés
en scannant un suffixe inconnu. Les comptes concernent les événements retournés.

| Livraisons synthétiques | Modèle APK | Vrai framer HA / garde |
| --- | --- | --- |
| Info seul, taille 1 | continuation, aucun dispatch | rejet unsupported dès le discriminateur |
| Info + 00/01/05/06, taille 2 | un transfert de **toute** la livraison | rejet unsupported ; aucun sous-code interprété |
| Info + 02/04, taille 2 | décision de lecture logique, sans TX | même rejet |
| Info + 03/07/inconnu, taille 2 | aucune transmission au handler Info | même rejet |
| Info `|` chacun des neuf sous-codes | deux continuations sans réassemblage, tailles 1/1 | une seule lecture de taille 1, puis arrêt |
| Info/sous-code + Ping ou réponse 0E | aucun Ping ou 0E dispatché séparément ; transfert entier ou continuation selon le sous-code | rejet sans saut de deux octets ni recherche de frontière |
| Ping + Info/sous-code | un Ping, suffixe Info non dispatché | erreur avant retour de la liste d'événements, aucun Ping rendu au propriétaire RX |
| réponse 0E complète, taille 50 | un candidat décodeur, résultat inconnu | une trame ; les tests propriétaires démontrent ensuite une lecture corrélée |
| réponse 0E aux **49 coupures** internes, y compris MBAP | pas de réassemblage ; candidat seulement si premier fragment > 2 octets | exactement une trame, origine de l'échange attachée au premier octet |
| deux réponses 0E concaténées, taille 100 | un candidat décodeur | deux trames ; cela ne crédite pas deux requêtes, ni un replay |
| Ping + réponse + Ping, taille 52 | un seul Ping ; réponse et second Ping non dispatchés séparément | trois événements, dont une réponse |
| deux Pings ensemble ou séparés | respectivement un ou deux Pings | deux Pings dans les deux cas ; un marqueur d'un octet n'a pas de coupure interne |
| MBAP invalide ou 0E tronquée puis EOF/TLS | tentative possible, jamais un succès attesté | invalid_mbap ou partial_eof ; aucune réponse complète |
| 1B avec longueur MBAP invalide | un candidat décodeur sans résultat attesté | signal DataUpdated ; politique de silence 30 s non exécutée par ce comparateur |
| CloseClient contrôlé, entier/fragmenté/concaténé | entier : transfert complet et demande d'annulation ; fragmenté : aucun réassemblage | événement de deux octets **selon hypothèse post-open HA**, arrêt avant suffixe |
| discriminateur inconnu | continuation hors branches sélectionnées | rejet unknown_type, pas de resynchronisation |
| EOF vide / exception TLS, avec ou sans fragment | zéro-read : continuation sans preuve de maintien ; exception : événement **local** Info/03 et annulation demandée | EOF/TLS distincts, partial_eof seulement sur EOF avec octets incomplets ; une exception TLS conserve sa catégorie |

Le modèle ne démontre jamais qu'une session APK reste fonctionnelle. L'état
`not_established` exprime cette limite ; une demande d'annulation n'atteste pas
un cleanup. Le comparateur framer indique `lifecycle_not_executed`.
Les tests propriétaires, eux, prouvent une fermeture unique, RX terminé et
`cleanup_succeeded`, et les tests HA vérifient `cleaned_generation`, absence de
nouvelle connexion et de faux timestamp après Info. B7 peut conserver le snapshot
antérieur : cette disponibilité n'est jamais comptée comme une acquisition.

`_opening_buffer[48:]` est un suffixe d'une livraison d'ouverture déjà reçue,
**pas une autre complétion ReadAsync**. Un test propriétaire utilise un Ping
dans ce suffixe et une réponse fragmentée dans les lectures suivantes. Un autre
refuse d'attribuer une réponse reçue dans ce suffixe à une requête future.
Les 48 octets demeurent un préfixe, pas un total OpenedClient prouvé.

## Rapport expurgé et reproduction

`compare()` retourne des événements, compteurs, tailles et énumérations fermées.
`bounded_json()` refuse les champs supplémentaires, textes libres et faux drapeau
de preuve ; plafond **8192 octets par cas**, 64 complétions de 512 octets au plus,
128 événements par côté. Dépassement : erreur fermée, sans rapport tronqué présenté
comme complet. Aucun RX, payload, identité, registre ou texte d'exception n'est
sérialisé. Les journaux de framer sont également vérifiés contre des marqueurs
privés synthétiques. Le schéma reste uniquement dans les tests Python ; aucun
nouveau contrat Node ni branchement aux campagnes n'est introduit.

```sh
python -m pytest -q tests/test_tls_read_candidate_186.py
python -m pytest -c ha_tests/pytest.ini -q ha_tests/test_tls_read_candidate_186.py
python -m pytest -q tests/test_v4_session.py tests/test_session_ignored_rx.py \
  tests/test_frame_boundary_classification_b4.py tests/test_data_updated_silence.py \
  tests/test_tls_cleanup_b9.py
python -m pytest -c ha_tests/pytest.ini -q ha_tests/test_frame_boundary_reconnect_b4.py
python -m ruff check .
python -m ruff format --check .
```

Deux hypothèses RED d'équivalence (« comptes APK == dispatch HA » pour deux Pings
concaténés et pour une réponse coupée après son deuxième octet) échouent comme
attendu. Les assertions GREEN du banc établissent ces différences et les refus
de faux succès. **Ce n'est pas un RED/GREEN de correction de production.**
Les résultats complets et quatre CI au SHA exact sont consignés dans la PR.

## Limites et suite réservée au MANAGER

Les retours `SslStream.ReadAsync` APK et `asyncio.StreamReader.read(4096)` n'ont
pas le même contrat de segmentation. Leur appliquer une livraison synthétique
identique isole les décisions de dispatch, sans prouver une segmentation réelle.
MBAP validé permet 7+L pour 07/0E et 11+L pour 1B ; aucun total Info n'en découle.
Le drapeau `boundary_proven=false` reste obligatoire, même pour un cas positif.

Supprimer une livraison entière peut perdre un Ping ou une réponse concaténée.
« Drop sans reconnexion » reste une politique future à arbitrer, pas un fait
APK/TLS ni une conclusion fonctionnelle de ce banc. Aucun saut de deux octets,
fallback ou changement de retry/framing/codec/transport n'est implémenté.
La causalité cleanup de #192 reste non résolue ; cette tâche ne la valide pas.
Tests réels, Android/natif, réseau Hoben/HA, dispatch/rerun : **NOT RUN**.

Absence de changement CHANGELOG justifiée : fichiers exclusivement tests/docs,
aucun impact sur le plugin distribué, les workflows, gates, budgets, campagnes,
TLS vérifié, V4 lecture seule ou politiques B7/B8/DataUpdated. Aucune promotion,
fusion ou automatisation n'est réalisée par CODEX DEV.
