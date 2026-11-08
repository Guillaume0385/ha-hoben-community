# #186-D6 — ports V4/livraisons injectables en mémoire

Tâche `HOBEN-186-INFO-TLS-ADAPTER-OFFLINE-009`, base
`bc506063b425e6e3c9ca92b9df536ce5af29cdd6`, [consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/186#issuecomment-6713923452).
Ce module prépare les contrats entre le worker mémoire D4 et un futur adaptateur
supervisé. **Aucun transport TLS réel, fournisseur de socket ou worker réseau**
n'est implémenté. Les ports concrets restent liés aux types mémoire exacts de D4.

## Interfaces et propriétaires

`scripts/info_delivery_tls_adapter.py` expose trois interfaces `Protocol` et leur
implémentation `MemoryInfoPorts` :

| Port | Observation/action autorisée dans cette tâche |
| --- | --- |
| `PlaintextDeliveryPort.delivered` | Constate une livraison effectivement retournée par le read mémoire, au sein de l'unique tâche RX du vrai V4Session |
| `V4OwnerPort.allow_v4_read` | Autorise une seule demande neuve après drop et Ping/Pong vérifiés par D4 ; ne connecte ni ne transmet lui-même |
| `CleanupWitnessPort.finish` | Vérifie fermeture/session CLOSED/RX terminé/aucune opération active/cleanup et tâche D4 réapée ; ne crée aucun autre propriétaire de close |

La fixture seule fournit V4Session persistant, capacité privée et horloge simulée.
Le constructeur exige une session vierge, un `MemoryFactory` et un
`MemoryTransport` exacts. Le lease est à usage unique ; autre session, autre RX,
factory/génération changée ou port générique sont refusés. Les interfaces ne
permettent pas d'injecter un client réseau dans le point d'entrée D4.

D4 reçoit un paramètre privé optionnel `_tls_ports`, défaut `None`. Sa voie
historique reste inchangée. Un hook mémoire constate les vrais retours de read ;
aucun lecteur concurrent n'est ajouté. L'autorisation précède la demande V4 et
une erreur sur sa réponse interdit le succès même si le codec l'a décodée.
Aucun client/coordinator/codec/framer/transport de production n'est modifié.

## Disposition de fixture, jamais frontière TLS prouvée

`feed_memory` associe des métadonnées fermées à l'objet effectivement mis dans
la file mémoire. La FIFO est bornée à 32 ; source non déclarée, ordre incohérent,
layout inconnu, génération différente, préfixe partiel ou quarantaine donnent
un refus. Le callback RX vérifie le propriétaire réel ; une déclaration seule
ne vaut jamais réception ni lecture V4. Les bytes ne sont ni copiés dans le
rapport ni journalisés. Les compteurs portent sur les livraisons plaintext
réellement retournées, pas sur les exceptions de contrôle.

- Défaut `unknown` : aucune autorisation de nouvelle V4.
- `fragmented_fixture` ou `coalesced_fixture` : FAILURE, sans scan/skip/deuxième
  reader ; une réponse décodable n'annule pas ce refus.
- `isolated_fixture` : hypothèse **explicite du banc synthétique** seulement.
  Elle ne prouve pas qu'une livraison ReadAsync contient un message complet.
  Une déclaration mensongère cohérente ne peut pas être authentifiée par ce
  modèle ; les fragments visibles du vrai framer sont néanmoins refusés.

Le positif exige candidat effectivement jeté par D4, Ping/Pong, nouvelle demande
et lecture décodée/corrélée dans la même session et cleanup attesté. Les tailles
Info de C restent des **tailles de livraisons**, jamais un total applicatif.
Info framing **INCONCLUSIVE**, **boundary_proven=false** restent invariants.
0x0C concaténé peut perdre Ping/0E, un fragment peut laisser un suffixe ambigu ;
aucun comportement serveur ni longueur Info n'est inféré.

## Temps, rapports et limites

Le calendrier D2/D4 demeure **3540 s observation +60 s cleanup, total 3600 s** ;
les bornes locales D4 plus strictes sont conservées. Le port ne réarme aucun
timer. Sans Info et sans incident, fenêtre complète puis cleanup attesté donnent
INCONCLUSIVE ; preuve manquante ou incident = FAILURE, jamais faux succès.

Le rapport fermé (8192 octets maximum) valide le vrai rapport D4/C imbriqué et
recoupe ses faits stables avec le vrai owner mémoire : drops, tailles observées,
lectures, première erreur, séquence de validation et ressources fermées. Il
exporte uniquement booléens/catégories/comptes/tailles agrégées : au plus
256 livraisons, 4096 octets chacune, une autorisation V4. Aucun identifiant,
GUID, RX/header/payload brut, donnée domestique ou exception libre.
`tls_provenance=not_proven`, `process_reap=not_proven` : le réapage asyncio D4
n'atteste pas un processus OS ; D5 reste une preuve séparée sur processus factice.
La validation JSON n'authentifie pas un journal entièrement fabriqué.

D1 valide le C offline imbriqué mais refuse le rapport D6 comme preuve live.
D3 garde `manual_info_route_not_connected`. Aucun workflow/gate/claim/launcher,
choix GitHub, HA distribué, politique B7/B8/DataUpdated ou automation modifié.
Le hook et les compteurs nouveaux sont limités au transport mémoire D4 ; les
options supplémentaires de la fixture ne constituent aucune configuration HA.

Tests RED/GREEN : défaut refusé puis positif sur le vrai V4Session ; matrices
ambiguïté/fragment/concaténation, corrélation, générations, source, absence Info,
deadlines, cancel/timeout/EOF/TLS/cleanup, défaut-off, falsification et non-fuites.
Régressions A/B/C/D1–D5 et #192, HA et Ruff avant revue MANAGER. CHANGELOG non
modifié : cette couche offline non raccordée n'a aucun effet distribué.

**Tests Hoben/HA réels NOT RUN. Lancement manuel NON PRÊT.** #192 demeure waiting,
cleanup S1/S2/V1–V6 non résolu. MANAGER seul prépare la suite ; CODEX livre une PR
experimental, state:review, puis s'arrête sans fusion ni nouvelle attribution.
