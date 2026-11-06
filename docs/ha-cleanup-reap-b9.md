# B9 — fermeture TLS confirmée après abort borné

Consigne [HOBEN-163-B9-CLEANUP-REAP-014](https://github.com/Guillaume0385/ha-hoben-community/issues/163#issuecomment-6681569700),
base `experimental` `fc165c6d0d55af38f05f3a20ba876b8da114d387`.
Correction limitée à `AsyncTlsTransport.close()`, tests et documentation.

## Faits et limite d'attribution

Le rapport résidentiel établit un rejet `unknown_type`/`frame_boundary`, puis
`cleanup_failed` environ cinq secondes plus tard. Il ne prouve pas l'opération
TLS fautive ni le SHA des fichiers chargés. Le discriminateur `0x0C` reste inconnu :
un octet examiné ne prouve ni message complet, ni frontière suivante, ni cause
serveur. Les échecs des campagnes HA/all ne prouvent pas la même cause.

Les tests B9 démontrent un défaut **local** : `StreamWriter.wait_closed()` attend
le Future de fermeture partagé du vrai `StreamReaderProtocol`. À l'expiration
de l'ancien `asyncio.timeout(5)`, l'annulation descend dans ce Future. L'abort
suivant peut déclencher `connection_lost(None)` et libérer le transport, mais le
témoin est déjà annulé et le code remonte toujours un timeout. La génération
reste alors terminale, ce qui est nécessaire faute de preuve exploitable.
Cela ne démontre pas que ce mécanisme explique l'incident résidentiel.

## Ordre et budget de fermeture

Le plafond configuré reste **5 s au total**, sans seconde période de cinq secondes :

1. Détacher l'ancien stream et demander `writer.close()` une seule fois.
2. Posséder une seule tâche `hoben-tls-close` qui attend le `wait_closed` original.
   Attendre au plus 4 s sans annuler ce témoin à cette échéance intermédiaire.
3. S'il reste pendant, demander une seule fois `writer.transport.abort()`.
   Attendre le **même** témoin dans la seconde restante. Seul son achèvement
   normal constitue une preuve de fermeture ; le retour d'abort ou `is_closing`
   ne suffit pas. Un callback portant une erreur n'est pas un succès.
4. Avant de rendre la main, terminer/réaper cette tâche, y compris sur erreur,
   timeout et annulation. Aucun nouveau superviseur ni transport n'est créé.

Pour un autre `close_timeout` positif, la réserve vaut un cinquième du délai,
plafonné à une seconde, à l'intérieur du même plafond total. La fermeture forcée
peut donc intervenir avant la fin du délai de fermeture gracieuse précédent ;
elle concerne uniquement l'ancienne connexion déjà destinée à être fermée.
Une notification trop tardive ou une boucle occupée au-delà du plafond ne donne
aucune autorisation rétroactive de reprise.

Toute erreur de close/wait/abort, absence de `wait_closed`, annulation explicite
ou absence de confirmation conserve l'échec fermé. Un close idempotent ultérieur
ne réhabilite pas `cleanup_succeeded`. Les erreurs libres sont remplacées par
les erreurs typées expurgées ; une annulation reste une annulation.

## Reprise et observations HA

Les règles de `V4Session` et `V4Lifecycle` restent inchangées : attendre le close
RX, réaper les opérations TX/probe et vérifier `cleanup_succeeded` avant backoff
et nouvelle génération. L'incident initial `frame_boundary` reste distinct du
secondaire `cleanup_failed`. Pour le discriminateur inconnu de ce test, la
reprise attend **60 s après nettoyage confirmé**, avec un seul superviseur,
puis exige une vraie acquisition V4 décodée/corrélée sur la nouvelle génération.

B7 conserve temporairement le snapshot et sa date d'acquisition originale ;
l'âge augmente et l'état session signale la reprise. L'ouverture seule ne
rafraîchit rien. Auth, arrêt/unload et nettoyage non prouvé restent terminaux.
B8 10+10/30/60, DataUpdated et son silence de 30 s, codecs/framing/MBAP,
discriminateur B5, TLS certificat/hostname et lecture seule sont préservés.

## Preuves hors ligne

- `tests/test_tls_cleanup_b9.py` : vrais StreamWriter/StreamReaderProtocol,
  transport mémoire sans socket et horloge synthétique. RED sur la base : Future
  annulé à cinq secondes malgré le callback d'abort. GREEN : témoin préservé,
  confirmation différée, fermeture lente, échéance totale, absence de confirmation,
  erreurs et annulations concurrentes ; aucune tâche de close orpheline.
- `ha_tests/test_cleanup_b9.py` : vrai client/coordinator/session/lifecycle et
  AsyncTlsTransport, streams/temps synthétiques. Le cas avec témoin asyncio réel
  reproduit aussi RED avant correction. Trois incidents successifs avec lecture
  en vol, suffixe concaténé ignoré, confirmation différée, 59 s sans ouverture,
  reprise à 60 s, nouvelle lecture, B7/A2 et diagnostics B1/B3/B5 cohérents.
  Courses sonde RX/TX et Pong, doubles close/abort, annulation/unload et cleanup
  impossible refusent toute seconde TLS sans preuve.
- Les régressions existantes B6, B7, B8, #160, #171, CloseClient/EOF, refus
  d'identité/TLS, fragmentation et concaténation restent requises, avec Ruff et
  les quatre checks `tests`, `ha-tests`, `hacs`, `hassfest` au HEAD exact de PR.

Commandes officielles : `python -m pytest` et
`python -m pytest -c ha_tests/pytest.ini ha_tests`, dans leurs environnements
Python 3.12 et 3.14 respectifs ; `python -m ruff check .` et
`python -m ruff format --check .`. Les résultats et limites d'environnement sont
rapportés dans la PR ; un check non exécuté n'est pas un succès.

Validation réelle **NOT RUN**. Aucun réseau Hoben/HA résidentiel, test live,
dispatch/rerun, workflow/budget/gate/campagne modifié, nouvelle commande, écriture
Modbus, secret/GUID/RX brut/donnée domestique, automatisation ou changement main.
Le dernier HA/all #42122137042 reste FAILURE, sans validation de version.
MANAGER seul revoit et fusionne ; #126/#189/#186 restent suspendues.
