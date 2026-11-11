# #207-D3 — Diagnostics HA et préparation manuelle hors ligne

Tâche `HOBEN-207-HA-LIVE-INSTRUMENTATION-003`, base
`1434c035bb0addd569b6bee2aa5f0c2c2b4e66db`, cible `experimental`.
D1/PR #208 et D2/PR #209 sont fusionnées. Les deux validations réelles de #207
restent **NOT RUN**. #192 cleanup réel demeure non résolu.

## Contrat de projection

`HobenClient.session_diagnostics` et le champ `session` du téléchargement des
diagnostics HA exposent uniquement la tentative courante, ou la dernière après
fermeture. Ils ne font aucune lecture réseau, demande V4, ouverture, mutation
HA ni recherche d'identité. Un client non démarré ou conservateur renvoie `None`.
L'activation est exclusivement attachée par le lifecycle HA persistant ; les
fixtures privées #186 et autres modes ne reçoivent pas de capacité nouvelle.

Le schéma 1 est fermé et revalidé avant export HA : clés inconnues, type non
scalaire, booléen à la place d'un entier, borne dépassée ou fausse frontière sont
refusés. Les données d'entrée du collecteur sont des événements internes fermés,
une taille entière et un indicateur de candidat ; jamais de bytes ou d'exception.

| Champ | Provenance et limites |
|---|---|
| `scope=tls_attempt`, `tls_generation` | Ordinal local de tentative du lifecycle, comme B3 ; distinct de l'identité et du compteur de sessions acceptées. 1..2147483647, sinon unknown/None, jamais d'enroulement. Compteurs remis à zéro pour chaque tentative, pas de total multi-session implicite. |
| `tls_connected`, `v4_accepted` | Attestations positives seulement après retour de l'ouverture existante et acceptation V4 respectivement. False signifie non attesté ; une erreur d'ouverture peut survenir après connexion TLS sans qu'un résultat d'ouverture ait été rendu. |
| `unsupported_deliveries`, `unsupported_delivery_bytes`, `last_delivery_bytes` | Abandon D1 admissible du bloc entier réellement retourné par read. Dernière taille 1..4096, scope `tls_delivery`. Ne compte ni suffixe OpenedClient ni fragment d'une trame connue. |
| `info_candidate_deliveries` | Premier octet admissible égal à 0x0C ; aucun sous-code, scan, décodeur ou taille Info supposée. La perte des messages concaténés demeure acceptée. |
| `v4_write_attempts`, `v4_requests` | Appel de la seule écriture V4, puis retour effectif de celle-ci. Écriture interrompue/échouée ne devient pas une écriture terminée. Ni l'une ni l'autre ne prouve une réponse serveur. |
| `v4_responses_correlated` | Incrément du vrai verified_read_sequence après décodage et contrôles TID/unité/fonction/20 registres/exchange. Pas un simple premier octet 0x0E, pas une exception Modbus ou une publication HA garantie. |
| `responses_after_drop`, `responses_after_info_candidate` | Sous-ensembles corrélés après au moins un drop/candidat dans cette même tentative. Pas de stabilité de 300 s déduite de ces compteurs. |
| `v4_responses_uncredited`, `acquisition_uncertain` | Réponse connue validée mais non créditée après suspension D2. Aucune nouvelle fraîcheur ni nouvelle demande FFFF sur cette génération. |
| `pings`, `pongs` | Ping post-open réellement délimité et traité sous le verrou TX ; Pong dont l'écriture a effectivement rendu. Pas de crédit pour un Ping perdu derrière une tête inconnue ou une écriture échouée. Les échanges pendant l'ouverture ne sont pas inclus. |
| `rx_timeouts`, `eof_received`, `terminal_error` | Timeouts RX effectivement levés, EOF typé réellement reçu, erreur du propriétaire. Silence, fermeture locale et erreur interne ne deviennent jamais un EOF serveur. L'erreur peut résulter d'un arrêt local ; croiser les diagnostics B1/B3 catégorisés. |
| `transport_close_requested`, `transport_closed`, `transport_close_failed` | Appel réel de close et son retour/échec. Le seul détachement ou abort n'atteste rien. |
| `cleanup_requested`, `cleanup_succeeded`, `cleanup_failed`, `cleanup_interrupted` | Demande du lifecycle, propriété cleanup_succeeded vérifiée après abort/close et réapage, ou échec/annulation. Un close transport rendu pendant que RX/TX est encore en cours ne crédite pas le cleanup complet. Un indicateur d'interruption reste historique même si un arrêt explicite peut ensuite finir. |

Tous les compteurs saturent à 65535, y compris le cumul d'octets ;
`counters_capped=true` signale la perte d'exactitude. Aucune limite de compteur
ne ferme la session, ne provoque une erreur ni ne modifie une politique réseau.
Les snapshots sont des copies constantes, sans historique croissant ni payload.
`boundary_proven=false` et `info_framing=INCONCLUSIVE` restent constants.
Une livraison TLS n'est pas une trame Hoben entière. Les métadonnées D3 ne
constituent ni une attestation d'admission live ni un verdict de campagne.

Les nouveaux événements DEBUG de `custom_components.hoben.session_diagnostics`
sont échantillonnés : quatre premiers puis puissances de deux par compteur,
une seule émission par indicateur. Au plafond, pas de répétition. Une défaillance
du handler ne remplace ni n'annule RX/cleanup. Les logs existants D1/B1/B3 sont
conservés ; plusieurs lignes de diagnostics ne représentent pas plusieurs drops.

## Recette réutilisable, exclusivement synthétique pour D3

Les tests `tests/test_live_diagnostics_207.py` et
`ha_tests/test_live_diagnostics_207.py` utilisent les vrais propriétaires et
coordinator, avec transports mémoire et horloges injectées. Ils peuvent être
relancés par pytest, sans secret, socket Hoben/HA ou dispatcher GitHub.

1. Acquisition initiale valide ; garder snapshot et timestamp originaux.
2. Livraison à tête inconnue contenant éventuellement Ping, 0x0E ou 0x1B :
   compter un bloc perdu, aucun de ses événements concaténés.
3. Ping/Pong suivant puis réponse réellement corrélée sur la même tentative :
   seuls ces événements incrémentent les compteurs ; contrôler la vraie réussite
   du coordinator séparément, pas seulement une valeur conservée B7.
4. Timeout puis réponse tardive : TLS/RX conservés, D2 suspend l'acquisition ;
   compteurs uncredited distincts, âge/timestamp conservés, aucun SUCCESS inventé.
5. EOF/TLS/auth/protocole, cleanup retenu/échoué/annulé, nouvelle génération,
   saturation >16 et jusqu'au plafond, confidentialité et refus de faux schéma.

La suite plus large conserve les tests DataUpdated 30 s, retry RX D2 1 s,
fragments/concaténations, B4/B6/B7/B8 et #192. Aucun skip/xfail ou faux cleanup.
Les résultats et quatre checks du HEAD exact sont consignés dans la PR.

## Inspection de la voie manuelle existante — pas une admission

Source examinée à la base ci-dessus : `.github/workflows/hoben-ha-manual.yml`
(« Vérification réelle Home Assistant »). D3 ne modifie ce fichier, ses options,
les scripts de campagne, budgets, conditions d'admission ou artefacts.
L'extension autorisée par le propriétaire et MANAGER ajoute seulement le chemin
fixe du nouveau module à FILES dans `.github/scripts/info-manual-route.cjs`
et réépingle les empreintes réelles dans `.github/info-manual-route.json`.
Le contrôle normal a accepté cette modification après l'autorisation précise ;
aucune règle de liste, hash, policy, refus ou gate n'est affaiblie. Le `hoben-live` de
`.github/workflows/hoben-manual.yml` reste distinct, consacré à #186.

Constats vérifiables : workflow_dispatch, contrôle owner et triggering_actor,
checkout au github.sha sans credentials persistés, environnement hoben-live,
mutex hoben-read-only-observation sans annulation concurrente, worker isolé et
rapports Python/Node fermés. Sept scénarios historiques dans all inchangés ;
dual-session-observation demeure optionnel, hors all. Les protections effectives
de l'environnement GitHub ne sont pas attestables par le YAML seul.

**Limites de raccordement à soumettre au MANAGER avant validation réelle :**

- La route native actuelle autorise experimental **et main** et une tentative
  positive quelconque ; `campaign_runtime_contract.validate_context` précise
  que la provenance est informative, pas un gate de PR/merge/SHA. D3 est limité
  à experimental et n'exécute aucune de ces voies. Aucun claim anti-rejeu ni
  recheck post-approbation n'est démontré dans ce parcours. Leur absence de
  démonstration n'est ni une dispense ni une autorisation de lancement.
- `ha_session_live_worker.collect` active actuellement ha_reconnect pour le seul
  mode dual-session. Le scénario hoben-live utilise le chemin conservateur ;
  il ne faut pas l'annoncer comme validation de la politique HA D1/D2/D3.
- Les collecteurs suppriment les sorties privées et les enveloppes de rapports
  sont fermées : ils ne transportent pas les nouveaux diagnostics D3. Ajouter
  des clés ou activer DEBUG dans un worker ne les rend pas publiables. Un futur
  raccordement doit faire valider le bon propriétaire HA, le schéma de rapport,
  la double validation et la réserve cleanup, sans divulgation ni faux succès.

D3 prépare donc l'instrumentation et cette recette, **pas READY FOR DISPATCH**.
Toute modification de workflow/protections ou activation de collecte exige la
revue sécurité spécifique du MANAGER et une tâche distinctement définie. Ne pas
réutiliser un ancien run/claim ou une fixture comme preuve réelle.

Après ces vérifications, MANAGER seul peut préparer la validation réservée au
propriétaire : branche experimental et SHA/revue/CI vérifiés, owner, approbations,
gate/recheck/anti-rejeu/mutex effectivement attestés avant accès au secret déjà
prévu ; aucune nouvelle identité requise. Aucun dispatch/approbation par DEV/CI.
Observer candidat réellement reçu, réponse corrélée sur la même TLS, âge et
stabilité réelle 300 s, puis cleanup attesté. Absence de candidat/corrélation :
INCONCLUSIVE ; erreur ou cleanup KO distincts, jamais masqués. Un timer ou une
mesure B7 conservée ne prouve pas cette stabilité. Les valeurs/réglages et RX ne
sont jamais demandés ou publiés. Aucun geste installateur/sécurité ni commande.

Les deux validations réelles de #207 et les critères #192 restent en attente.
TLS CA/hostname `myhoben.fr:465` et V4 lecture seule ne sont pas modifiés.
