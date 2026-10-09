# Campagne exploratoire H1/H2 de #48 — GitHub Actions uniquement

> **Portée historique mise à jour (décision propriétaire du 9 octobre 2026).**
> Les sections ci-dessous décrivent les sondes H1/H2 et l'ancien mécanisme
> `main` / `workflow_dispatch`. Elles **ne sont plus la procédure de
> déclenchement du cycle expérimental actuel**. Les tests H1/H2 sont destinés
> exclusivement à la voie `hoben-experimental` sur `experimental`, isolée du
> plugin HA ; la voie séparée `hoben-live` doit valider le **vrai comportement
> du client Home Assistant**. MANAGER peut déclencher ces essais après chaque
> merge revu sans demander d'accord conversationnel, sous réserve des contrôles
> et approbations effectivement imposés par GitHub. **Aucune PR vers `main`**
> avant demande explicite du propriétaire. Les anciens plafonds, interdictions
> d'écriture et exigences de chiffrement décrits ci-dessous restent applicables.
> Voir [le workflow expérimental actuel](experimental-protocol-workflow.md)
> et [l'Issue #54](https://github.com/Guillaume0385/ha-hoben-community/issues/54).


Cette procédure prépare l'observation demandée par le propriétaire le
2026-10-07. **Aucune session réelle H1/H2 n'a encore été exécutée.** Les tests
pytest sont synthétiques, sans serveur ni identifiant réel. Le routeur de
production n'est pas implémenté et la frontière OpenedClient reste inconnue.
La PR #49 conserve la branche `codex/issue-48` et reste en brouillon.

## Prérequis de confiance avant la première exécution

Le workflow dédié n'existe actuellement que dans le candidat : il ne peut pas
s'accorder l'accès à `hoben-live`. MANAGER doit préparer une **installation de
gouvernance séparée**, revue et validée sur main, limitée à :

- `.github/workflows/opened-client-boundary.yml` ;
- `.github/scripts/opened-client-boundary-gate.cjs` et son test hors ligne
  `tests/test_boundary_workflow.py` ;
- la règle de capture privée bornée dans `AGENTS.md` et la procédure associée.

Ce sous-ensemble installe la voie de confiance, pas le routeur ni la session
persistante. Il ne fusionne pas #49 ni ne clôture #48. Les quatre checks habituels
et une revue indépendante restent requis pour cette installation. MANAGER
enregistre sa classification de validation live conformément à `AGENTS.md`.
Aucun changement des voies existantes, du gate `--live-premerge`, de secrets ou
de protections n'est effectué par CODEX DEV.

MANAGER vérifie ensuite, dans les paramètres GitHub, que main est protégée et
que `hoben-live` autorise **exactement la branche protégée main**, sans branche
candidate ni tag. Le workflow vérifie aussi `main.protected`, son SHA actuel,
le propriétaire exact, l'acteur/sender `Guillaume0385` et l'absence de rerun.
Il vérifie le HEAD courant de la PR #49, sa branche et son dépôt. Une seconde
vérification intervient après l'attente de protection et le checkout, avant
l'injection du credential dans le seul step de collecte.

La disponibilité de l'environnement, de son secret existant `HOBEN_USER_GUID`
et du canal de chiffrement doit être vérifiée par MANAGER avant dispatch.
Si un DeviceGuid déjà persisté est disponible, MANAGER peut le fournir via le
secret protégé optionnel `HOBEN_DEVICE_GUID`. Sinon, les 32 zéros restent la
valeur initiale normale ; l'identité attribuée est conservée privément et
réutilisée automatiquement entre les sessions du même run. Aucun nouvel
Identifiant HOBEN n'est demandé et aucun secret n'est copié par CODEX DEV.

## Certificat de capture et conservation

MANAGER prépare, **sur son poste privé**, une clé RSA d'au moins 3072 bits et
son certificat public. Cette opération ne collecte rien sur Hoben. Exemple
avec clé privée protégée par une phrase secrète, hors de tout checkout :

```sh
umask 077
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 \
  -aes-256-cbc -out manager-boundary.key.pem
openssl req -new -x509 -key manager-boundary.key.pem -days 365 \
  -subj '/CN=Hoben capture recipient' -out manager-boundary.cert.pem
openssl x509 -in manager-boundary.cert.pem -outform DER | openssl dgst -sha256
```

Seul le PEM **public** est configuré dans la variable d'environnement GitHub
`hoben-live` nommée `HOBEN_CAPTURE_CERTIFICATE`. La clé privée et sa phrase
secrète ne sont jamais envoyées à GitHub. Le MANAGER compare l'empreinte DER
SHA256 obtenue et saisit ses 64 caractères hexadécimaux minuscules lors du
dispatch. Ce hash concerne seulement le certificat public, jamais un identifiant
ou une trame du poêle.

Avant toute connexion, la sonde vérifie cette empreinte, `notBefore ≤ maintenant`
et `notAfter ≥ maintenant + 1 h`, RSA ≥3072 et un chiffrement de préflight.
La capture utilise des dossiers 0700 et fichiers 0600 dans `RUNNER_TEMP`, hors
checkout. Les octets RX sont append-only dans `rx.bin` ; les journaux et
annotations sont séparés. Un tar privé est chiffré en CMS AuthEnvelopedData
**AES-256-GCM**, avec **RSA-OAEP/SHA256**, puis supprimé. Les fichiers privés
sont supprimés du runner après le scellement. Aucun fallback en clair n'existe.

Deux artefacts distincts sont récupérables pendant **sept jours** :

- `boundary-ciphertext-<SHA>-<run_id>` contient uniquement `captures.cms` ;
- `boundary-report-<SHA>-<run_id>` contient uniquement `report.json`, anonymisé.

Le dépôt public peut exposer le ciphertext ; seule la clé privée MANAGER permet
le déchiffrement. Le certificat public est indépendant de l'identité du poêle.
Les fichiers RX, identités, registres et valeurs domestiques ne sont jamais
affichés, envoyés dans les summaries ou joints à des artefacts non chiffrés.
L'expiration GitHub ne supprime pas les copies téléchargées : MANAGER conserve
ses copies déchiffrées dans un dossier privé et les supprime après analyse selon
sa politique de conservation. Toute diffusion du secret de déchiffrement est
interdite.

## Dispatch et répétitions

Après revue du code exact et enregistrement de sa décision, MANAGER lance dans
Actions **MANAGER OpenedClient H1 H2 observations**, fichier
`opened-client-boundary.yml`, sur **main** avec :

| Input | Valeur |
| --- | --- |
| `reviewed_sha` | HEAD complet actuel de #49, examiné par MANAGER |
| `mode` | `H1`, `H2`, ou `both` pour la campagne de base de 12 sessions |
| `observation_seconds` | `90` recommandé ; fenêtre bornée de 30 à 90 s |
| `recipient_sha256` | Empreinte DER du certificat public examiné |

Le candidat exécuté est exactement ce SHA, avec credentials Git non persistés
et sans installation de dépendances candidates. Le workflow et son gate viennent
du SHA main du dispatch. Un nouveau HEAD, une main modifiée pendant l'attente,
un autre acteur, une autre définition de workflow ou un rerun échoue fermé.
Revoir les changements et faire un **nouveau dispatch**, sans relancer en boucle.

La campagne n'a ni matrix ni concurrence interne. Une concurrence globale
empêche deux campagnes H1/H2 simultanées. MANAGER évite également de lancer
d'autres sondes/gates Hoben pendant cette observation ; aucun reload/redémarrage
HA ni commande du poêle ne fait partie de la campagne.

Pour chaque hypothèse, six sessions distinctes s'enchaînent dans cet ordre :
pauses volontaires avant le premier RX de **0 ms ×2**, **100 ms ×2**, **1 s ×2**.
Le délai entre sessions est de **15 s**. Il n'y a aucun retry/reconnect d'une
session ; une demande d'association ou un refus arrête immédiatement la
campagne. Deux erreurs consécutives l'arrêtent aussi, avec le nombre réellement
exécuté : aucun troisième transport ni passage au mode suivant n'est lancé.
Une session réellement sans erreur remet le compteur à zéro ; le changement
de mode, un EOF ou une fin de fenêtre n'effacent pas une anomalie antérieure.
EOF passif sans réponse attendue, notamment sous H1, reste une limitation
enregistrée, sans attribution certaine à un manque de keepalive.

Budgets fixes : connexion vérifiée `myhoben.fr:465` ≤5 s, ouverture ≤15 s après
OpenClient, observation ≤90 s après réception du premier octet 0x04, RX ≤1 Mio,
réponse sollicitée ≤10 s. Capacité RX 4096 ; seule la dernière capacité peut
être réduite pour respecter exactement le plafond. Ces nombres sont des
paramètres expérimentaux et n'établissent aucune propriété du serveur.

## Collecte et hypothèses

Chaque `rx.bin` conserve tous les octets applicatifs déchiffrés **effectivement
retournés** par le lecteur, dans l'ordre, dès la première lecture après
OpenClient. Le journal contient index, offset absolu, capacité demandée, taille
effective, début/fin monotones, gap du lecteur, gap de complétion, EOF/erreur et
pauses volontaires. Les instants/catégories des tentatives et complétions TX,
indices de requêtes et résultats de corrélation sont conservés séparément.
Il n'y a ni remplissage de buffer, ni suppression d'octets inconnus. Un arrêt
conserve exactement les données déjà retournées ; il ne prétend pas avoir lu
les octets encore dans la pile TLS ou sur le serveur.

H1 n'émet que l'ouverture et les Pong correspondant à des Ping **avant** son
début. Après le premier octet 0x04, il observe passivement, sans Modbus/Pong.
Le lot RX entier est examiné avant tout Pong : si un ou plusieurs Ping sont
suivis du premier 0x04 dans cette même lecture, même fragmentaire, aucun Pong
n'est émis pour ce lot. Un lot contenant uniquement des Ping avant l'ouverture
conserve ses Pong. Les octets et la suppression sont consignés sans scan.
L'analyse examine tous les seuils préchoisis **50 ms, 200 ms, 1 s**, groupes,
tailles autour du préfixe et données suivantes. Les temps sont ceux du client,
pas des émissions serveur. Une réception coalescée, l'absence de gap mesuré ou
l'absence de données suivantes restent inconclusives sur une pause serveur.

H2 accumule le préfixe connu et place, **sous hypothèse uniquement**, le début
post-open à `opening_offset + 48`. Le surplus et les octets différés restent
dans la capture indépendante. Le framer expérimental traite Ping, 0x0E
(`1 + 6 + MBAP.Length`) et 0x1B (`5 + 6 + MBAP.Length`), en réutilisant les
codecs MBAP ; les quatre métadonnées restent opaques. Aucun scan d'un marqueur
plus loin n'est permis. CloseClient reste terminal avec suffixe opaque, sans
longueur universelle inventée.

H2 autorise les Pong ainsi candidats et au maximum deux lectures V4 fixes
FFFF/unit 1/fonction 04/adresse 1024/quantité 20. La première part ≥5 s après
le préfixe complet ; la seconde ≥20 s après la première réponse corrélée valide.
Une trame H2 déjà commencée mais incomplète suspend toute nouvelle lecture V4
et son timer d'émission jusqu'à sa complétion, sans boucle sur un timer expiré.
Une réponse ainsi commencée avant la requête ne peut donc pas lui être attribuée.
Si elle se termine sans waiter, sa corrélation est refusée et les émissions
restent désactivées ; le RX continue d'être conservé passivement.
Un seul lecteur reste actif pendant les timers/TX. Notifications et réponses
sont distinctes, sans fusion dans un snapshot. Timeout, annulation, corrélation
invalide ou absence de réponse terminale clôturent le waiter écrit avant toute
autre requête. Une exception Modbus corrélée est terminale et n'entraîne aucune
deuxième lecture. Un framing invalide arrête les émissions tout en conservant
le RX jusqu'à fermeture/budget ; si un waiter était en vol, la session ferme.
Une même livraison valide puis invalide ne produit aucun Pong de ce lot.
La validation couvre aussi les PDU et toutes les corrélations du lot avant tout
Pong ou comptage de réponse ; une réponse surnuméraire invalide le lot entier.
Une lecture déjà terminée est traitée selon son horodatage de fin, même si le
collecteur reprend après l'échéance. Une réception réellement tardive est
conservée dans l'archive sans compter comme réponse acceptée ni permettre de TX.
Si la fenêtre globale expire avec une requête FFFF en vol, l'arrêt est
`response_timeout`, le résultat est partiel et le lecteur/transport ferment.
Il compte comme erreur pour l'arrêt après deux erreurs consécutives ; une
fenêtre complète exige l'absence de waiter abandonné.
Un EOF avec une lecture FFFF encore en attente reçoit la catégorie
`pending_response_eof`, reste partiel et compte aussi comme erreur. Le lecteur
et le transport sont fermés avant de retourner le résultat ; aucune requête
ne réutilise cette session.
Une anomalie de framing/corrélation dans `emission_stop` compte comme erreur
de campagne même si le RX passif se poursuit jusqu'à `observation_budget` ou
`peer_eof`, avant la première requête comme entre deux lectures. Les émissions
restent arrêtées et tous les octets retournés sont conservés. La catégorie
`terminal_close_h2` seule décrit une fermeture opaque, sans erreur de framing ;
si elle interrompt une réponse attendue, la session est néanmoins en erreur.

Les conclusions H1/H2 exigent un préfixe de 48 octets **accepté** par le
collecteur : décodage existant, profil V4 reconnu, DeviceGuid ASCII et différent
de la valeur initiale nulle. Ce contrôle ne prouve toujours pas la longueur
totale d'OpenedClient. Préfixe incomplet, refusé ou non accepté avant l'arrêt :
les octets et les timings restent conservés, mais les deux hypothèses sont
inconclusives et la comparaison indique `insufficient_data`. Un suffixe
ressemblant à Ping/0x0E/0x1B ne peut pas rendre ce contexte admissible.

Ni association forcée ni fonction 06/16/22, FFF0, commande de chauffage,
paramètre installateur ou essai moteur n'est envoyé. Le framing H2 est contenu
dans `scripts/` et n'est jamais importé par HobenClient/HA.

## Récupération et analyse privée après le run

MANAGER télécharge les deux artefacts du **run GitHub réel** et conserve le
ciphertext/clé dans son dossier privé, jamais dans le dépôt. Déchiffrer vers un
fichier temporaire 0600 ; **ne l'extraire qu'après succès authentifié** :

```sh
umask 077
openssl cms -decrypt -binary -inform DER -in captures.cms \
  -recip manager-boundary.cert.pem -inkey manager-boundary.key.pem \
  -out captures.private.tar
```

Si cette commande échoue, supprimer `captures.private.tar` : un déchiffreur peut
écrire un préfixe avant la vérification GCM finale. Après succès, examiner les
membres du tar dans le dossier privé puis y extraire l'archive. Elle ne contient
que les fichiers des sessions, journaux/annotations et identités privées.
`assigned-identity.json` permet la réutilisation contrôlée par MANAGER dans un
futur run ; il ne doit jamais être joint à une Issue.

L'analyse locale **hors ligne** de ces captures GitHub est permise ; elle ne
remplace pas la provenance GitHub des connexions réelles. Rejouer chaque session
avec le même checkout examiné :

```sh
python scripts/replay_opened_client_boundary.py \
  --session-directory /chemin/prive/session-01
```

Le replay vérifie la couverture du journal/RX, conserve les timings originaux
H1, analyse les mêmes octets sous H2 et compare les coupures synthétiques
**1/48/257 octets**. Il écrit `reanalysis.json` séparément et ne modifie aucun
fichier brut. Ne pas réécrire les temps H1 lors du re-chunking, ni exiger des
valeurs domestiques ou identités identiques entre essais.
Il valide lui-même les octets du préfixe et exige l'événement privé
`opening_accepted`, lié à la lecture qui a permis cette acceptation. Un marqueur
0x04 isolé, une déclaration contredite par les octets ou une ancienne capture
sans cet événement ne produisent aucune conclusion compatible.

Le rapport public contient les tailles/offsets, catégories, couverture du
suffixe, corrélations/comptages et délais min/médian/max par session, ainsi que
des agrégats explicitement nommés. Une distribution des médianes de sessions
n'est pas présentée comme une médiane de tous les gaps. Les résultats permettent
« compatible avec les deux », « H2 contredite », « aucun modèle étayé » ou
« données insuffisantes » ; ces états ne prouvent jamais une frontière.
Les hypothèses ne sont pas exhaustives et une longueur fixe peut aussi être
suivie d'une pause.
Le rapport de campagne utilise le schéma 2 : `opening_context` indique
l'admissibilité et sa catégorie par session ; `eligible_sessions`,
`excluded_sessions` et `opening_context_counts` rendent les exclusions visibles.
Comptages H1/H2/comparaison, distributions agrégées des tailles/gaps et fenêtres
complètes ne portent que sur les sessions admissibles. Toutes les sessions,
y compris celles exclues, gardent leurs métadonnées d'arrêt et leur capture.
Une session sans préfixe accepté compte comme erreur et ne remet pas à zéro
la série d'erreurs de campagne, même si le transport se termine par EOF.
Le schéma reste 2 ; `stop` décrit la fin de collecte, `emission_stop` conserve
l'anomalie H2 et `pending_response_eof` distingue une lecture abandonnée à EOF.
`partial` et `complete_windows` mesurent la collecte de la fenêtre RX, pas le
succès des lectures ni l'absence d'erreur H2 : une fenêtre entièrement collectée
peut garder `partial=false` et compter dans `complete_windows` tout en portant
une anomalie et en arrêtant la campagne après sa répétition. Les compteurs
`v4_requests` et `correlated_responses` restent distincts.

Après analyse, MANAGER consigne dans #48 les conclusions anonymisées, provenance,
portée et limites. Il décide si une preuve suffisante permet le routeur, si une
autre observation est nécessaire ou si le blocage protocolaire persiste. Aucun
silence, fixture synthétique ou résultat favorable isolé n'autorise une règle
universelle, la fusion de #49 ou les tâches 2–6.

## Interruptions et limites de conservation

EOF, plafond, erreur et réponse abandonnée produisent un résultat partiel.
SIGTERM/annulation permet de fermer et de sceller les octets déjà reçus quand le
runner laisse le temps de cleanup. Une interruption forcée/SIGKILL ou une panne
de chiffrement/stockage peut empêcher la récupération ; aucun résultat ni
artefact complet n'est alors revendiqué. Les uploads ciblent seulement les deux
fichiers d'export, jamais un wildcard du dossier privé. Les logs de la collecte
sont supprimés, les summaries ne contiennent que le SHA et un statut générique.

## Voie expérimentale distincte préparée par #54

#54 réutilise les primitives H1/H2, capture, chiffrement et replay examinées dans
#49/#52 sur une PR ciblant `experimental`, sans modifier ces deux PR ni conclure
sur la frontière. L’entrée `run_experimental_boundary.py` fixe le scénario et
la projection publique ; elle appelle la bibliothèque de campagne, sans lancer
le CLI historique `workflow_dispatch` ni contourner ses contrôles.

Son petit bootstrap main indépendant propose `hoben-experimental-request.yml`,
consommant une décision JSON MANAGER puis un label sur #54 via le connecteur.
La référence de déploiement `issues:labeled` est main : son environnement dédié
`hoben-experimental` est **Branch main uniquement**, avec approbation indépendante
et prevent-self-review, sans modification de `hoben-live` ni des anciens gates.
Le candidat est le HEAD expérimental fusionné/revu, pas celui du run main.
Voir [l’opération précise](experimental-protocol-workflow.md) pour le dry-run,
les labels réservés, les Settings du propriétaire, la réservation et la lecture
corrélée du run/rapport une heure plus tard.

Les artefacts de cette voie sont `experimental-ciphertext-<SHA>-<run_id>` et
`experimental-report-<SHA>-<run_id>`, rétention 7 jours ; le déchiffrement privé
CMS décrit plus haut reste applicable. Le certificat public de #52 est épinglé
sur main avant TLS ; aucun secret certificat ni clé privée n’est demandé à DEV.
Les budgets, stops et hypothèses restent ceux de cette campagne. Les workflows
historiques conservent leur procédure ; aucune substitution de validation stable.

La préparation offline de #54 ne prouve ni installation, ni dry-run GitHub réel,
ni observation Hoben et ne débloque pas #48/#51. Ces preuves et décisions restent
à fournir par MANAGER après les revues et fusions autorisées.
