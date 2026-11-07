# #192 — caractérisation S1/S2 et instrumentation diagnostic-only

Tâche `HOBEN-192-HA-CLEANUP-OFFLINE-001`,
[consigne #6695381974](https://github.com/Guillaume0385/ha-hoben-community/issues/192#issuecomment-6695381974),
base `experimental` `6e37c5a04f3d90353cf9340250423aecacb60130`.

**Aucun correctif causal de cleanup établi.** Cette caractérisation ne solde pas
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

## Étape diagnostique autorisée par MANAGER après ce blocage

La dernière section de la même consigne autorise une instrumentation limitée,
**sans modification du contrat de fermeture**. Son RED/GREEN porte uniquement
sur la perte de discrimination : les 12 cas de base n'émettent aucun témoin
permettant de distinguer les opérations ; ils échouent avec les nouvelles
assertions diagnostiques. Après instrumentation, ces assertions deviennent
vertes. Cela ne corrige ni ne prouve la cause des incidents réels S1/S2.

`close_diagnostic.CloseTrace` émet un seul log structuré `hoben_tls_close` par
fermeture effective : DEBUG sans échec, WARNING sinon. Un close idempotent ne
fabrique ni log de succès ni attestation de réapage supplémentaire. Le schéma
reste local au journal ; rapports/gates de campagne Python/Node inchangés.

- Opérations fermées : `writer_close`, `wait_closed`, `abort`, `reap`.
- Résultats fermés : `returned`, `raised_connection`, `raised_tls`,
  `raised_other`, `timeout`, `cancelled`, `not_confirmed` (entrée/pending).
- État du Future partagé : `pending`, `completed_ok`, `completed_error`,
  `cancelled`, ou `unknown` si le SDK n'est pas inspectable. L'accès ne consomme
  pas l'exception du Future, ne l'attend pas et ne le modifie pas.
- Callback : `observed` uniquement si le tap temporaire a reçu l'appel réel
  `connection_lost`, puis a transmis **le même argument** au callback original.
  `not_observed` ne prouve pas son absence : un callback déjà exécuté ou capturé
  par la boucle avant installation peut échapper au tap. Son résultat typé est
  séparé de celui de `wait_closed`. Le callback original est restauré avant log.
- Génération : entier déjà attribué par le lifecycle au diagnostic B3 du
  framer ; `unknown` si indisponible. Un contexte temporaire dans
  `V4Session._release_transport` transmet seulement cet entier aux wrappers
  imbriqués et au transport. Aucun compteur parallèle ni identifiant privé.
- Maximum 12 événements, premier échec et un secondaire conservés même si la
  liste sature ; ordre plafonné à 65535, indicateur `truncated` en cas de perte.
  Le schéma est testé à 4096 octets JSON maximum ; tout champ hors allowlist
  est rejeté. Un callback tardif ne modifie pas le diagnostic déjà émis.
  Durées en millisecondes, plafonnées au close_timeout configuré, au plus 60 s
  pour la télémétrie. Pour le réglage normal : 5000 ms ; `duration_capped`
  signale une valeur réelle supérieure, sans augmenter le délai opérationnel.

La lecture du Future utilise les détails CPython de StreamReaderProtocol
testés en Python 3.12 et 3.14 ; ce n'est pas une nouvelle API de preuve. Une
implémentation non inspectable reste `unknown` et ne modifie pas le close réel.

Les catégories ne pilotent **aucune** décision. Callback avec erreur, abort,
`is_closing`, Future terminé avec erreur et close idempotent ne deviennent pas
des preuves de cleanup. Une annulation/erreur du logger n'interrompt pas la
fermeture réelle. Aucun texte/type d'exception libre, argument, cause, traceback,
GUID, RX ou valeur de registre n'est retenu dans le diagnostic.

Les cas supplémentaires couvrent annulations concurrentes et doubles fermetures
S1/S2, premier échec suivi d'une erreur d'abort, refus de succès sans callback,
réapage, restauration du callback, saturation, génération inconnue et logger
défaillant. Les suites B6/B7/B8/B9/#160/#171 et contrats Python/Node restent
requises ; les résultats exacts et quatre CI figurent dans le bilan au HEAD PR.
Les checks verts de #191 ne sont pas ceux de cette étape.

## Instruction DEBUG Home Assistant, sans activation par CODEX DEV

Après revue/déploiement autorisés seulement, MANAGER peut proposer d'ajouter
temporairement au bloc logger existant (sans dupliquer sa clé) :

```yaml
logger:
  logs:
    custom_components.hoben.close_diagnostic: debug
```

Cela permet de voir aussi les fermetures sans erreur. Les échecs restent au
niveau WARNING. Revenir ensuite au niveau antérieur ; n'activer aucun logger
global, TLS ou RX brut, ne pas exporter les journaux HA privés. Cette instruction
n'a pas été exécutée ; aucun accès HA résidentiel, test réel ou workflow live.
