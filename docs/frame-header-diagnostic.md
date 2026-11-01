# Diagnostic des en-têtes et tailles V4 — #163 / B3

Consigne : [HOBEN-163-B3-FRAME-HEADER-LENGTH-DIAGNOSTIC-005](https://github.com/Guillaume0385/ha-hoben-community/issues/163#issuecomment-6555420754).
Base : `0ed031c09d91412b6386ef2ae0b1cd40d6c3f63c`. Instrumentation seulement :
aucune correction de codec, retry, transport, hypothèse de récupération ou
disponibilité. B2 reste un précédent bloqué ; C/D ne sont pas commencées.

## Un message logique, pas un read TLS

`ExperimentalV4Framer._feed` compte les octets effectivement attribués au
préfixe/corps courant. Le helper `frame_diagnostic.py` ne reçoit aucun octet,
identifiant, exchange ni exception à conserver. Il garde uniquement des
scalaires, sans historique cumulatif. Un en-tête produit un DEBUG une fois,
indépendamment de sa fragmentation. Les corps 07/1B restent ignorés sans décodage.

| Type | Quand la taille devient déterminable | Total / provenance / portée |
| --- | --- | --- |
| Ping | Discriminant reconnu | 1, `fixed_contract`, `frame` |
| CloseClient post-open | Discriminant reconnu sous le contrat existant | 2, `fixed_contract`, `post_open_hypothesis` ; aucune longueur universelle affirmée |
| DataResponseClient / DataResponseServer | 7 octets reçus et MBAP validé : Protocol ID nul, Length 2–254 | 7 + Length, `validated_header`, `frame` |
| DataUpdated | 11 octets reçus et même validation MBAP | 11 + Length, `validated_header`, `frame` |
| OpenedClient accepté | Préfixe déjà strictement validé par l'ouverture existante | `received_bytes=48` pour le **préfixe seulement** ; total `unknown`, provenance/portée `unproven` |
| En-tête MBAP incomplet/invalide, type non pris en charge, frontière ambiguë | Aucune longueur exploitable | Total `unknown`, provenance/portée `unproven` ; aucun scan ni saut d'octets |

`generation` est l'ordinal de tentative/session TLS du lifecycle local, pas un
identifiant de client ni une preuve d'acceptation. Le seul ajout au lifecycle
transmet cet ordinal au diagnostic. Pour une session/framer autonome sans cette
preuve, il reste `unknown`. Les bornes d'export n'imposent aucun plafond de retry.

Une erreur produit un WARNING catégorisé : type fermé, total validé ou
`unknown`, `received_bytes`, portée/provenance, phase et état
`complete|partial|invalid|unknown`. Aucune erreur n'est déduite d'un simple
en-tête DEBUG. Les messages normaux ne créent pas de WARNING.

Ces observations héritent du handoff local déjà autorisé ; elles ne changent
aucun `boundary_proven` ni fait de protocole en preuve universelle.

Pour une erreur de MBAP, `received_bytes` décrit le **préfixe réellement examiné**
de ce message (7 ou 11), pas une longueur déclarée invalide ni tout le read TLS.
Après en-tête validé, le compteur inclut exactement le corps reçu avant EOF.
Les messages précédents/suivants et les queues n'y contribuent pas. Si une
exception locale empêche d'attribuer les octets à une trame, le compteur reste
`unknown` : aucune longueur de chunk ne lui est substituée. Les témoins scalaires
attachés aux événements complets empêchent une erreur PDU/corrélation de prendre
la taille d'un message coalescé ultérieur. Les octets non examinés d'un suffixe
sans frontière restent non attribués. Une taille inconnue signifie « inconnue »,
jamais zéro reçu ou longueur totale de 48.

## Chemin d'erreur et limites des preuves

`V4Session._receive_experimental` → `ExperimentalV4Framer.feed/_feed` est la
frontière B1 `frame_boundary`. La validation MBAP possède sa frontière interne
`mbap_header`. Un rejet normal reste protocolaire ; une exception Python
imprévue garde sa phase prouvée et devient `HobenInternalError` dans
`_receive_unproven_handoff`, puis erreur HA via `HobenClient._refresh_once` et
le coordinator. Le monitor/capteur A2 conservent la catégorie B1. Ni une phase
ni une exception injectée ne prouve la cause de la panne réelle.

Les logs ne publient ni texte/chaîne/traceback d'exception, ni RX/header brut,
ni hexadécimal, GUID, adresse, donnée domestique ou registre. Tous les champs
sont revalidés avant émission. Un handler de log défaillant ne change pas le
résultat du protocole. Une taille n'autorise aucun nouveau traitement/retry.

DataUpdated invalide conserve son WARNING de transition de récupération,
auquel s'ajoute le diagnostic de la trame rejetée. Les sondes rejetées ont leurs
propres diagnostics ; pas de doublon à chaque fragment ni WARNING normal.
Le silence glissant de 30 s, l'abandon RX sans scan, la sonde unique sur le même
TLS et les temporisations/reconnexions existantes restent inchangés.

Preuves offline : tests rouges du contrat de journalisation avant ajout, puis
fragmentation à chaque frontière et octet par octet, concaténation, EOF partiel,
MBAP invalide dont Length=65535, CloseClient, suffixe ambigu, erreur Python
synthétique, confidentialité et vrais client/coordinator/entités HA. Les erreurs
internes restent permanentes ; aucun faux succès/rafraîchissement A1.
**Cause réelle non reproduite, tests réels NOT RUN.** Une correction fonctionnelle
demande une prochaine petite tâche autorisée par MANAGER, sur preuve distincte.

## DEBUG HA temporaire — instruction pour le propriétaire, non exécutée

Avec accord du propriétaire pour une future observation, utiliser l'action HA
native `logger.set_level` uniquement pour ce logger :

```yaml
action: logger.set_level
data:
  custom_components.hoben.frame_diagnostic: debug
```

Après la fenêtre d'observation, remettre le même logger à `warning` avec la
même action. Ne pas activer le DEBUG global, ne pas recharger l'intégration,
ne pas lancer une lecture/test actif pour collecter ces logs. Les erreurs
catégorisées restent visibles à WARNING. Ne partager que les événements scalaires
Hoben pertinents ; ne pas exporter les journaux HA complets ou les traces privées.
CODEX DEV n'a effectué aucun changement de niveau de log sur HA.
