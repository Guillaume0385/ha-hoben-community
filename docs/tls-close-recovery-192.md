# #192 — fermeture TLS avec preuve indépendante de libération

Tâche `#192-TLS-CLOSE-RECOVERY-002`,
[consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/192#issuecomment-6974615182),
base `experimental` `4010844a891144e561ff1430dbb87d9ea056ccf0`.

## Défaut reproduit hors ligne

Le Future de fermeture de `StreamReaderProtocol` transmet l'exception reçue
par `connection_lost`. `StreamWriter.wait_closed()` peut ainsi lever
`ssl.SSLError` après que les finaliseurs CPython ont fermé le descripteur et
libéré les propriétaires du transport. Le code précédent déclarait toujours
`cleanup_failed` dans cette situation, interdisant la génération suivante.

Le test positif a d'abord échoué sur la base avec `TransportError`, malgré le
descripteur fermé et les propriétaires détachés. Il passe après correction.
La fixture HA reproduit trois générations normales puis, en génération 4,
les trois expirations de corrélation V4 avec les deux délais existants de 60 s,
puis une erreur TLS de fermeture injectée à +49 ms. La génération 5 n'est
ouverte qu'après fermeture attestée et délai de reconnexion existant ; seule
sa nouvelle réponse V4 peut rafraîchir les données HA.

Ce scénario caractérise un défaut conditionnel réel du traitement d'erreur,
**pas la cause prouvée de l'incident résidentiel** du 18/11. Le SHA installé
dans HA reste non vérifié. Les traces résidentielles n'attestent pas les quatre
preuves ci-dessous ; elles ne permettent donc pas de conclure que cette
correction aurait accepté ce cleanup. Les validations réelles V1–V6 de #192
restent ouvertes, sans campagne ni validation HA installée par CODEX DEV.

## Contrat de preuve

Avant `writer.close()`, un adaptateur capture les objets liés à cette fermeture :
StreamWriter, transport SSL applicatif, SSLProtocol, transport selector brut,
socket et Future partagé. Il vérifie leurs types exacts et leurs liens. Seules
les piles CPython selector 3.12 et 3.14 testées sont reconnues ; une autre pile,
version, classe ou donnée illisible conserve le refus après erreur TLS.

Après l'erreur TLS, l'abort existant et le véritable `gather` du waiter,
**toutes** les conditions suivantes doivent être vraies dans le budget initial :

| Preuve | Conditions indépendantes requises |
| --- | --- |
| `socket_closed` | Socket capturée à fd -1 ; socket, boucle, protocole et serveur du transport brut détachés ; fermeture et buffer vide. |
| `tls_released` | Transports et protocole applicatif détachés ; état UNWRAPPED ; timers SDK libérés, backlog et sortie TLS vides. |
| `stream_released` | Identité writer/protocole/Future capturés conservée ; transport, lecteur, writer serveur et tâche du protocole détachés. |
| `waiter_reaped` | Tâche propriétaire réellement attendue, terminée sans annulation ; elle et le même Future partagé portent la même erreur TLS. |

L'identité de la socket capturée évite de confondre un numéro de fd réutilisé
ou une autre génération avec la fermeture concernée. Aucun flag de diagnostic
ne participe à cette décision. Le retour d'abort reste nécessaire mais ne
prouve rien seul ; le callback observé n'est pas une preuve de libération.

Toute preuve partielle, fd encore actif, propriétaire ou timer retenu, Future
substitué, implémentation inconnue, erreur non-TLS, timeout ou annulation garde
le comportement de refus. Le cleanup session et la politique lifecycle ne sont
pas modifiés : aucune reconnexion si `cleanup_succeeded` manque. Les deadlines,
la vérification TLS, les codecs, la rétention HA, #160/#212 et #219 restent
inchangés. Une erreur TLS ne devient jamais une fermeture TLS gracieuse.

## Diagnostics et intégrité

Le schéma existant `hoben_tls_close` reste inchangé : il conserve notamment
`wait_closed=raised_tls` et `future=completed_error`. Une ligne DEBUG séparée
du logger `custom_components.hoben.close_diagnostic.termination` expose seulement
`schema`, génération bornée, résultat `verified`/`not_confirmed` et les quatre
booléens. C'est une projection de la décision, jamais sa source. Aucun texte
d'exception, secret, identifiant privé, RX ou valeur domestique n'est publié.

Les seuls fichiers runtime modifiés sont `transport.py` et
`close_diagnostic.py`. Leurs deux SHA256 existants sont actualisés dans
`.github/info-manual-route.json`. La liste fermée, toutes les autres empreintes,
les workflows et la logique des gates #186 restent inchangés. MANAGER doit
revoir le diff et le HEAD exact avant toute fusion.

## Vérification synthétique et limites

`tests/test_tls_close_recovery_192.py` utilise les véritables classes CPython
SSLProtocol, StreamReaderProtocol/Writer et SelectorSocketTransport. Une
socketpair UNIX fournit uniquement des descripteurs jetables ; aucune connexion
réseau, handshake TLS ou écriture socket n'est effectuée. Les octets de test
sont injectés en mémoire et l'état TLS établi est synthétique. Les finaliseurs
SDK de fermeture exécutés ne sont pas remplacés dans le cas positif.

La matrice comprend : preuve complète ; callback seul avec fd actif ; fd fermé
sans libération des propriétaires ; erreur non-TLS ; timeout ; annulation ;
double close ; timer/protocole retenus ; réapage manquant ; Future substitué ;
classe, version ou SDK inconnus ; diagnostic borné sans exception privée.
La suite HA utilise les vrais client, coordinator, session et lifecycle et
vérifie les cas positif et négatifs jusqu'à l'unload, sans nouvelle acquisition
fabriquée ni tâche RX/lifecycle/close restante.

Le scénario positif unitaire et le scénario HA génération 4 ont aussi été
rejoués en remplaçant en mémoire uniquement `AsyncTlsTransport.close` par sa
méthode extraite de la base Git : ils échouent avec le refus attendu ; les
mêmes tests passent avec la correction. Une défaillance du logger de preuve,
y compris une exception d'annulation émise par ce logger, ne change pas la
décision opérationnelle ; une véritable annulation du propriétaire reste propagée.

Les tests historiques de cleanup sans preuve physique continuent à refuser les
erreurs TLS. Ces tests ne deviennent pas des succès sous prétexte de callback.
Les résultats chiffrés et les quatre checks CI figurent dans la PR au HEAD exact.
Live Hoben, HA installé, workflow manuel, V1–V6 : **NOT RUN**.
