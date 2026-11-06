# #192 — caractérisation offline S1/S2, preuve causale manquante

Tâche `HOBEN-192-HA-CLEANUP-OFFLINE-001`,
[consigne #6695381974](https://github.com/Guillaume0385/ha-hoben-community/issues/192#issuecomment-6695381974),
base `experimental` `6e37c5a04f3d90353cf9340250423aecacb60130`.

**Aucun correctif de production établi.** Cette caractérisation ne solde pas
#192, ne démontre pas la cause résidentielle et ne valide pas le run réel.
Les tests sont verts en vérifiant aussi des `cleanup_failed` attendus : ils
ne constituent donc pas une preuve RED/GREEN d'un défaut corrigé.

## Fixture et chemins exécutés

`ha_tests/test_cleanup_offline_192.py` garde HobenClient, coordinator, monitor,
V4Lifecycle, V4Session et AsyncTlsTransport. Seules les connexions sont
remplacées par des streams mémoire avec les vrais StreamWriter et
StreamReaderProtocol. Leur Future partagé est terminé par le véritable
`connection_lost`, ou reste sans confirmation dans le cas négatif. Le contexte
TLS vérifié est réel, préchargé pour supprimer l'aléa du chargement de CA dans
un thread ; endpoint, SNI, certificat et hostname restent vérifiés par le test.
Horloge, ouvertures, réponses V4 et incidents sont entièrement synthétiques.

S1 : première lecture validée, nouvelle lecture en vol, discriminateur 0x0C
non délimité **ou CloseClient complet indépendant**, nettoyage RX, snapshot/date
d'origine conservés, puis reprise conforme B8 seulement avec confirmation.
Aucune lecture du sous-code de 0x0C ni nouvelle interprétation du framing.

S2 : vrais observateurs `ha_campaign_observer` et `ha_reconnect_observer`,
adaptateur PongInjection et tap F1 `ha_incident_observer`. Une inhibition Pong,
perte CloseClient gen1, cleanup gen1, nouvelle ouverture gen2, cinq lectures V4
au total et stabilité 120 s, puis fermeture finale gen2. Les preuves sont
projetées par les validateurs Python et Node ; la garde HA/all conserve les
deux NOT RUN après cleanup incertain. Pas de worker réseau ou campagne réelle.
`ha_dual_instrumentation.TrackedTransport.close()` délègue aussi le close sans
attester un succès après exception ; il ne fait pas partie du scénario S2.
Aucun scénario dual-session annulé n'est exécuté.

## Matrice de caractérisation sur la base, sans correction

| Signal injecté à la fermeture | S1 (deux incidents) | S2 (gen2 finale) |
| --- | --- | --- |
| `connection_lost(None)` | cleanup attesté ; nouvelle TLS et lecture fraîche | reprise puis cleanup final attestés |
| `connection_lost(ConnectionResetError)` | cleanup_failed, aucune nouvelle TLS | cinq lectures et reprise conservées, cleanup_failed transport, owner tls_close |
| `connection_lost(SSLError)` | cleanup_failed, aucune nouvelle TLS | même forme de rapport, cleanup_failed transport |
| aucune confirmation, même après abort | plafond 5 s, cleanup_failed, aucune nouvelle TLS | reprise précédemment attestée conservée, échec cleanup final timeout |

Pour les callbacks d'erreur, la fixture avance de 125 ms entre demande de close
et notification. Ce délai synthétique n'est **pas** une mesure de la cause
réelle. Deux erreurs différentes produisent la même catégorie publique
`transport/cleanup/transport_close`, sans qu'un timeout de cinq secondes soit
nécessaire. Pour S1, l'absence de callback reproduit aussi la chronologie de
cinq secondes, mais seulement parce que cette absence a été injectée.

Le code CPython de StreamWriter.wait_closed attend le Future du protocole.
StreamReaderProtocol.connection_lost le termine normalement ou avec une erreur.
Le code B9 transmet les erreurs sans certifier le cleanup, annule/réape son
waiter à l'échéance et interdit la nouvelle génération si la preuve manque.
La matrice ne démontre ni double close, ni annulation indue, ni réapage oublié
lorsque le même témoin termine normalement.

## Blocage et suite MANAGER

Les symptômes S1/S2 sont reproduits **conditionnellement** à une faute injectée,
mais aucun contrat violé par le code de base n'est établi. Accepter les erreurs
ou l'abort comme preuve de succès pour obtenir un test vert modifierait le
contrat de sûreté ; cela n'est pas un correctif causal autorisé.

Il manque la provenance réelle de la fermeture en échec : appel writer.close,
résultat wait_closed, annulation/timeout/erreur typée, état du témoin et moment
du callback connection_lost. Le rapport public actuel conserve la génération,
le stage et la catégorie, mais ne départage pas ces causes. Aucun RX, message
d'exception privé ou accès HA réel n'a été recherché pour combler cette lacune.

La documentation statique `MyHOBEN_extract/analysis/session_apk34.md` décrit
l'annulation des boucles et la fermeture du client mobile ; elle ne fournit pas
une attestation du cleanup asyncio de HA, ni la cause de ces deux incidents.
Ses commandes client ne sont pas reproduites.

MANAGER doit préciser la preuve manquante ou une étape diagnostique bornée dans
la même consigne : catégories fermées par opération de close et état de témoin,
sans exception libre ni octet privé, puis réautoriser la même tâche. Aucun
changement de budget, codec/framing, retry B8, B7 300 s, DataUpdated 30 s, gate,
workflow, main/release ou automatisation. #192 reste ouverte ; validations
V1–V6 non soldées et dernier HA/all #42283866996 toujours FAILURE.

Commandes hors ligne : pytest HA sur ce fichier et régressions B6/B8/B9/#171,
pytest unitaire transport/B6/B9, Ruff check/format. Les résultats exacts sont
consignés dans le commentaire canonique. Sans PR corrective ni nouveau HEAD de
production, les quatre CI de cette investigation restent **NOT RUN** ; les
checks verts de #191 appartiennent au code de base et ne prouvent pas #192.
