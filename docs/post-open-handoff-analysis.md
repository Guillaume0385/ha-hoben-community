# Issue #48 — analyse du passage post-OpenedClient

Analyse CODEX DEV du 2026-10-07 sur `main`
`73b953d257245a36bd2bb1a0b87c94f6aae30e84`. Le prérequis de la tâche 1
**n'est pas établi** : aucune règle vérifiable présente dans ce dépôt ne permet
de désigner le premier octet du flux post-ouverture pour l'Osmose de référence.
Le parseur/routeur reste à implémenter après résolution de ce prérequis.

## Inventaire des preuves et limites

| Source présente sur main | Ce qu'elle établit | Limite pour le passage post-open |
| --- | --- | --- |
| `protocol.md` §4, offsets OpenedClient | Les champs lus occupent un préfixe de 48 octets. | La longueur complète et les suffixes différés restent inconnus. |
| `protocol.md` §3, analyse statique MyHOBEN 2.2 build 34 | L'application conserve la connexion après l'ouverture et traite Ping, 0x0E et 0x1B. | Son traitement des blocs de lecture ne prouve aucune frontière TCP/TLS. |
| `tests/fixtures/opened_client_v4_production_2026_10_04.json` et `protocol.md` §§4, 19 | Profil V4 et métadonnées publiques observés, zéro suffixe déjà reçu. | La fixture contient uniquement des métadonnées, aucune capture complète ni preuve d'absence de suffixe ultérieur. |
| `protocol.md` §4, validation MANAGER de PR #22 | Deux lectures V4 réussies sur deux connexions fraîches, avec réutilisation du DeviceGuid. | Elle ne valide ni une session persistante ni la frontière complète d'OpenedClient. |
| `protocol.md` §8, validation MANAGER de PR #27 | Les valeurs V4 et leurs entités ont été comparées à MyHOBEN dans les situations observées. | La validation du décodeur ne donne aucune règle de fin de l'ouverture. |
| `myhoben.decode_opened_client()` | Validation des champs connus, identité ASCII et décodage du préfixe. | Le codec accepte au moins 48 octets et ne détermine pas une longueur complète. |
| `session._receive_response()` / `OpenSessionResult` | Accumulation du préfixe et comptage du suffixe déjà lu, sans interprétation de ce suffixe. | Le résultat ne contient ni frontière prouvée ni buffer transférable au routeur. Le compteur ne couvre pas les lectures futures. |
| `open_session_once()` | Fermeture après le résultat ponctuel, sans réutilisation de la connexion. | Un suffixe différé reste non observé ; cette fermeture ne permet pas de poursuivre le flux. |
| `v4_read.open_and_read_v4_once()` / `HobenClient._session_once()` | Refus des suffixes déjà reçus ; le chemin V4 validé reste borné et ferme son transport. | Ces vérifications n'excluent pas un suffixe arrivant après le préfixe. Elles ne sont pas un certificat de passage post-open. |
| `modbus_tcp_frame_size()`, `decode_mbap()`, `protocol.md` §§2, 6, 13 | Taille et validation d'un ADU Modbus à un offset de début déjà établi. | MBAP ne prouve pas que cet offset suit réellement OpenedClient. |

L'inventaire des fichiers suivis, de la fixture et de leur historique ne fournit
pas de capture anonymisée supplémentaire établissant cette transition. Le gel
OpenClient/association reste applicable ; cette analyse n'étend aucun profil.

## Ambiguïté reproductible hors ligne

`tests/test_post_open_handoff.py` utilise le vrai transport et les opérations
ponctuelles existantes, avec des streams asyncio remplacés par la fixture de
test. La protection réseau de `tests/conftest.py` reste active. Les identités,
préfixes, registres et métadonnées utilisés sont entièrement synthétiques.

Deux livraisons suffisent à distinguer **observation** et **preuve de frontière** :

1. Préfixe et suffixe dans la même lecture : le suffixe reste non classifié et
   la lecture V4 est refusée, même si les octets ressemblent à Ping, à une réponse
   Modbus 0x0E valide ou à une notification 0x1B. Aucun Pong ou Modbus n'est émis
   en réponse au suffixe et le transport ferme.
2. Préfixe, puis suffixe dans une lecture ultérieure : l'ouverture ponctuelle
   retourne les mêmes métadonnées publiques que la fixture Osmose, dont
   `unclassified_bytes == 0`, puis ferme sans consommer ce suffixe. Le test couvre
   aussi un préfixe fragmenté. Le contenu différé reste opaque et non publié.

Les douze cas couvrent ces trois ressemblances et un suffixe opaque, le refus
existant, la fermeture, l'absence de requête applicative/reconnexion et la
confidentialité du rapport, du repr et des logs. Les tests montrent la limite
du contrat actuel ; ils n'affirment pas qu'un suffixe existe en production et ne
demandent pas d'élargir le chemin d'ouverture gelé.

Une période silencieuse, un timeout, la fin d'un bloc TLS, un profil V4 ou un
paquet suivant ressemblant à une trame valide ne lèvent pas cette ambiguïté.
Reconnaître un MBAP corrélé à l'intérieur d'un suffixe inconnu serait déjà lui
attribuer une origine post-open sans preuve.

## Preuve attendue et condition de reprise

Le MANAGER doit fournir et examiner une preuve protocolaire vérifiable,
limitée au chemin d'ouverture déjà accepté sur l'Osmose de référence, qui :

- définit une règle déterministe de fin d'OpenedClient pour ce contexte ;
- justifie l'attribution des octets suivants au flux post-open, même lorsqu'ils
  arrivent dans une lecture différée ou ressemblent à Ping/0x0E/0x1B ;
- précise la portée et la provenance de cette règle, ses conditions
  d'application et le refus à appliquer hors de ce contexte ;
- conserve explicitement les limites universelles et l'association hors du
  périmètre réactivé.

Une analyse statique vérifiable établissant cette frontière peut contribuer à
cette preuve. Toute observation réelle complémentaire relève d'une intervention
MANAGER séparément autorisée et contrôlée. Une capture ou une absence de suffixe
sur quelques lectures n'établit pas, seule, une règle générale d'absence future.
Ne publier aucun identifiant, code, paquet privé ou valeur domestique.

La résolution est enregistrée par le MANAGER dans #48 et dans les sources
protocolaires pertinentes avec son niveau de confiance exact. Après cette
résolution, restaurer `state:in-progress` et reprendre la même branche/PR pour
implémenter et tester le routeur. Le résultat reste à soumettre à CODEX REVIEW
avant la validation MANAGER. Les tâches dépendantes 2 à 6 restent en attente.

## Contrat conservé pour la future implémentation

Le routeur ne recevra que des octets **déjà attribués** au flux post-open par la
règle prouvée. Il restera pur, indépendant de HA et sans I/O : ordre conservé,
suffixe incomplet borné, catégories réponse/notification distinctes, EOF propre
distinct d'une troncature et refus terminal sans resynchronisation arbitraire.
Les tailles documentées restent `1 + 6 + MBAP.Length` pour 0x0E et
`5 + 6 + MBAP.Length` pour 0x1B ; les quatre octets de notification restent opaques.
Les codecs MBAP existants seront réutilisés. Aucun nouveau contrat exécutable,
routeur, lecteur TLS, contrôle du poêle ou règle de fusion n'est ajouté ici.

## Livrable intermédiaire

Cette analyse et ses tests conservent le prérequis bloquant de #48. Le code
runtime, les formats d'ouverture, les workflows live et les faits de
`protocol.md` restent inchangés. Le statut canonique est porté par l'Issue ; une
PR conservant ce travail reste ouverte et non prête à fusionner jusqu'à
résolution du prérequis et réalisation du périmètre complet de la tâche 1.
