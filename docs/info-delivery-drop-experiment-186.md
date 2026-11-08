# #186-B — abandon expérimental d'une livraison Info, hors ligne seulement

Tâche `HOBEN-186-INFO-DELIVERY-DROP-EXPERIMENT-002`,
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/186#issuecomment-6713923452),
base `fbd5e35a1a69eaa7f6444e7cfa9f5f06ef01c80c` sur `experimental`.
**Info framing INCONCLUSIVE ; boundary_proven=false.** Aucun fait serveur ou
contrat « une lecture = une trame » ne découle de ce prototype.

## Portée et défaut-off

Le [banc #186-A](tls-read-candidate-offline-186.md), PR #194 fusionnée, compare
les décisions statiques APK aux vraies règles incrémentales HA. Sa source RE
reste [PR #4](https://github.com/Guillaume0385/MyHOBEN_extract/pull/4), HEAD épinglé
`e2f88b0dfcd130b9b9f9e52d69a900d8ded48b6e`. Les tailles Info 00..07 demeurent
inconnues ; 48 octets restent un préfixe OpenedClient, pas un total prouvé.

Cette tranche ajoute seulement une capacité privée à usage unique
`_InfoDeliveryDropExperiment`, passée explicitement par une fixture au paramètre
privé `_info_delivery_drop` d'un vrai `V4Session(mode=PERSISTENT)`.
Sans capacité, valeur **None** par défaut, le traitement antérieur reste actif.
La capacité est refusée en mode conservateur et avec les budgets/inhibitions/
quarantaines de campagne incompatibles avec le mode persistant. Une capacité
déjà attribuée ne peut pas être réutilisée par une autre session.

**Aucun fournisseur dans HobenClient, V4Lifecycle, HA, configuration, environnement,
script ou workflow.** Les tests HA vérifient le défaut-off et un test statique
interdit tout fournisseur de production/campagne. Il n'existe pas de procédure
d'activation HA/live dans cette PR ; seul un test dirigé fournit la capacité.

## Point d'interception et gardes

L'unique propriétaire RX attend le vrai `transport.read(4096, bounded=False)`
dans la branche normale de `_read_framed_delivery`. Le prototype examine
uniquement son résultat intact. Il ne s'applique jamais au suffixe conservé
`_opening_buffer[48:]`, ni à la branche de lecture/quarantaine/sonde DataUpdated.

Pour abandonner une livraison, toutes ces conditions sont nécessaires :

- capacité privée présente, donnée de type bytes, taille réelle de 1 à 4096 ;
- premier octet égal au discriminateur Info, sans examen d'un autre octet ;
- tâche courante identique à l'unique RX, transport identique au transport possédé ;
- session CONNECTED, sans erreur RX ni cleanup échoué ;
- vrai framer, aucun état partiel ni tail retenu, récupération DataUpdated inactive.

La livraison **entière** est libérée avant l'attente suivante. Aucun scan,
skip de deux octets, copie/rétention de suffixe, reset du framer ou faux événement
Ping/CloseClient/V4 n'est ajouté. Les mêmes Future, corrélation et échéance
absolue d'acquisition restent en place. Ni timestamp HA, ni témoin de lecture,
ni notification de succès ou compteur de stabilité n'est modifié par un drop.
Une lecture ne réussit qu'après une réponse 0E réellement reçue et validée par
le chemin de corrélation/décodage existant. Cela ne prouve pas l'âge serveur des
registres, seulement une acquisition reçue et décodée selon le contrat existant.

Une condition non satisfaite laisse les anciennes règles s'appliquer : un type
non pris en charge, un MBAP/PDU invalide, auth, TLS, EOF, arrêt/annulation ou
cleanup non attesté ne devient pas un rejet silencieux. DataUpdated conserve
son silence glissant de 30 s et sa seule sonde. Les délais B8 et le hold B7 ne
sont ni activés différemment ni modifiés.

## Borne anti-boucle et diagnostic

La fixture choisit un plafond entier de **1 à 16 livraisons abandonnées**, pour
toute la durée de l'objet, jamais rechargé après une bonne acquisition. Au plus
64 Kio sont ainsi abandonnés et 16 lignes DEBUG émises. La livraison admissible
suivante dépasse le plafond : erreur protocolaire locale et cleanup existant,
y compris si aucun appelant n'attend une lecture. Ce n'est pas une provenance
de rejet wire du framer, ni une nouvelle erreur récupérable. Le plafond réduit
uniquement cette expérience privée ; aucune limite de campagne ne change.

Chaque drop émet une ligne DEBUG à vocabulaire fermé :
`event=info_delivery_discarded`, `delivery_bytes` (octets effectivement retournés),
`discarded_deliveries`, `experimental_hypothesis=true`, `boundary_proven=false`.
`delivery_bytes` n'est **pas frame_bytes**. Aucun sous-code, RX, GUID, payload,
valeur domestique, registre, texte d'exception ou traceback n'est journalisé.

## Matrice synthétique et limites observées

| Cas | Résultat attendu dans le prototype privé |
| --- | --- |
| Info seul, ou sous-codes synthétiques 00..07/inconnu | Une livraison abandonnée sans interprétation de sous-code ; pas de fermeture sur ce seul événement |
| Info + Ping/0E concaténé | Tout est perdu, y compris le suffixe connu ; aucun Pong/succès crédité pour ce suffixe |
| Info puis Ping puis 0E fragmentée | Un seul RX/transport ; vrai Pong, puis lecture corrélée ; les 49 coupures 0E restent gérées |
| Info isolé puis octet de sous-code séparé | Le second octet n'est pas rattaché à Info ; anciennes règles, souvent rejet ou EOF partiel |
| Ping + Info dans une livraison | Info n'est pas en tête : rejet existant, aucun scan |
| Premier octet d'une livraison égal à Info dans un corps 0E/07/1B partiel | Framer actif : aucun drop, réassemblage/contrôles habituels |
| Suffixe Info d'OpenedClient | Aucun drop ; suffixe sans provenance de nouvelle lecture, refus existant |
| Info pendant récupération/sonde DataUpdated | Gardes DataUpdated inchangées ; aucune consommation du plafond privé |
| Drops répétés / après acquisition correcte | Compteur non réarmé ; arrêt sûr au dépassement du plafond |
| Timeout après drops | Future identique ; expiration à l'échéance initiale, aucune fausse lecture ni seconde connexion |
| Auth, mauvais identifiant de transaction, donnée non sollicitée, erreur locale, EOF/TLS | Échec typé et cleanup existants ; aucune réussite ni reprise inventée |
| Annulation/arrêts concurrents ou vraie erreur de close | RX/TX réapés ; cleanup_failed reste non attesté, aucune seconde session |
| Vrai client/coordinator HA sans capacité | Rejet/reconnexion Info existants ; snapshot B7 conservé sans fausse fraîcheur |

Les 30 scénarios positifs RED échouaient sur le RX initial (fonctionnalité absente),
puis passent avec la capacité privée. Les tests de refus et les régressions sont
distincts : la fragmentation de messages inconnus demeure **non résolue**.
Voir les résultats et les quatre CI au HEAD exact dans la PR de cette tranche.

```sh
python -m pytest -q tests/test_info_delivery_drop_186.py
python -m pytest -q tests/test_tls_read_candidate_186.py tests/test_v4_session.py \
  tests/test_v4_persistent.py tests/test_session_ignored_rx.py \
  tests/test_frame_boundary_classification_b4.py tests/test_cleanup_b6.py \
  tests/test_tls_cleanup_b9.py tests/test_data_updated_silence.py \
  tests/test_ha_reconnect_timing_b8.py
python -m pytest -c ha_tests/pytest.ini ha_tests
python -m ruff check .
python -m ruff format --check .
```

**Risque de l'hypothèse :** StreamReader.read et SslStream.ReadAsync segmentent
différemment ; jeter une livraison peut masquer un événement utile ou perdre une
réponse et mener au timeout. Aucun maintien de session ni gain de stabilité réel
n'est démontré. #192 cleanup S1/S2 et V1–V6 restent non soldés. Tests réels,
Android/natif, serveur Hoben, HA résidentiel, dispatch/rerun : **NOT RUN**.
Activation éventuelle, étape suivante, revue et fusion sont réservées au MANAGER.
