# R2 — récupération prouvée de hoben-live, observation de 300 s

Tâche exclusive [HOBEN-126-HA-R2-LIVE300-PROVEN-RECOVERY-013](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6656463863),
base `experimental` `dfef9f101c252c4c8198b976e0138fe79c2e1c32` après R1/#183.
HA-F2/15 minutes est annulée ; R3/R4/R5 ne sont pas activées par cette PR.

## Deux résultats distincts

Le prédicat nominal reste : `continuous=true`, au moins 300000 ms utiles,
6 lectures décodées et réutilisation attestée, après les contrôles communs de
fin, cleanup et absence d'erreur. Une continuité nominale n'est pas renommée
en récupération. Le calcul historique `continuous_300s` reste intact.

Le nouveau chemin alternatif SUCCESS porte `recovered=true` et conserve
`continuous=false`. Un incident récupéré pendant la troisième acquisition peut
donner 5/6 lectures valides ; la tentative échouée reste dans le rapport. Une
perte entre deux appels peut donner 6/6 lectures, sans continuité TLS. Ces
résultats ne prétendent ni à 300 s sans interruption ni à 300 s après reprise :
la fenêtre originale de 300 s reste observée, avec incident visible et fin
encore active sur la nouvelle génération. Aucun délai n'est réinitialisé.

## Preuve obligatoire et indépendante Python/Node

Les champs HA-F1 existants suffisent ; aucun nouveau schéma ou champ public.
Après validation de forme/chronologie et de ressources, les deux validateurs
exigent ensemble :

- Six échantillons et observation complète d'au moins 300 s, avant 330 s.
  Premier et dernier échantillons décodés. Une ouverture ou première acquisition
  initiale manquante ne fournit pas l'ancrage validé requis pour ce chemin.
- Premier incident F1 sur le propriétaire accepté 1 : EOF, transport/TLS,
  timeout ou CloseClient reconnu non auth 3/6, en phase TLS read, corrélation
  ou post-open. Refus des phases d'ouverture/inconnues et des rejets protocolaires
  de framing. La catégorie seule ne prouve jamais une reprise.
- Exactement deux propriétaires acceptés, générations 1/2 ; fermeture TLS et
  cleanup réellement attestés, étape reaped, aucun pending. Aucun événement
  terminal ni erreur de cleanup. Le premier incident suit la dernière lecture
  valide de l'ancien propriétaire et précède sa demande de fermeture ; son
  cleanup précède la dernière acquisition attestée du nouveau propriétaire.
- Chaque lecture décodée conserve une séquence corrélée consécutive sur sa
  génération ; le dernier témoin F1 correspond au nombre de ces acquisitions.
  Tout échantillon de génération 2 constate déjà la génération 1 nettoyée.
  Chaque poll échoué appartient à l'ancienne génération et possède une lecture
  décodée ultérieure sur la nouvelle. Aucun replay ni lecture cachée ajouté.
- Dernière acquisition de génération 2, même séquence à la fin de fenêtre et au
  cleanup final. Fin encore active, aucune nouvelle perte/erreur de nettoyage
  masquée par l'arrêt local. Génération 2 effectivement nettoyée/réapée.
- Supervisor normalement terminé et réapé, quotas et horloge monotone native
  respectés pour publier SUCCESS. Une horloge synthétique ne valide pas un run.

Les temps F1 se comparent à leur propre origine ; celle-ci peut précéder la
première acquisition. Les séquences/générations relient les témoins aux samples.
Les compteurs et le booléen `reused` gardent leur sens réel. Le résumé distingue
continuité/récupération, durée utile et lectures valides/tentées, puis publie
le premier incident, terminal et cleanup F1 sans donnée privée.

Auth, annulation, arrêt, interne/générique, framing non prouvé, session neuve
sans lecture, cache B7, perte terminale ou cleanup absent restent FAILURE ou
rapport refusé selon les contrôles existants. Aucun nouveau statut INCONCLUSIVE
n'est inventé. Les anciens seuls compteurs de génération ne suffisent plus à
attester `recovered` pour cette campagne ; sans F1 complet, l'alternative est
fausse. Le chemin nominal historique reste lisible sans F1.

### Correction R2-C — premier incident permanent dans le nominal

La [consigne corrective HOBEN-126-HA-R2C-FIRST-PERMANENT-F1-014](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6663323850)
part du SHA `c53a8be97a7e8281391209cf672649158e8047b7` après #184.
Les sept fixtures signalées dans le [bilan post-fusion](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6658950993)
étaient locales, non publiées ; elles sont reconstruites dans les tests R2-C.

Un `diagnostic.first` de catégorie `authentication`, `authorization`, `internal`,
`cancelled`, `cleanup_failed`, `closed` ou `exhausted` interdit SUCCESS même si
les six lectures sont déclarées valides, `continuous=true` et les événements
`terminal`/`cleanup` sont nuls. Les projecteurs indépendants Python/Node donnent
alors `error=unexpected` pour cette contradiction ; le premier incident F1 et
ses champs restent intacts, les compteurs ne changent pas et `recovered=false`.
Les quatorze cas (sept catégories, deux validateurs) sont RED avant le correctif
puis GREEN ; un SUCCESS falsifié ou un effacement du seul champ error est refusé.

La présence d'un premier incident n'est pas à elle seule un échec permanent :
une tentative TLS/transport/timeout d'ouverture non acceptée, nettoyée puis
suivie des six acquisitions valides conserve le nominal historique sans
prétendre à une récupération de génération acceptée. `first=null` reste nominal
sain. La récupération R2 entièrement prouvée et ses refus ne changent pas.
Les omissions partielles de F1, types/champs non autorisés, événement tronqué,
tap invalide et pending contradictoire sont rejetés par les contrats existants.
Aucun schéma ou champ nouveau ; les rapports historiques sans F1 gardent leur
contrat, et la provenance des données ne peut pas être fabriquée par validation
structurelle. Aucun code d'observateur, plugin, scénario voisin, budget, gate,
workflow ou politique de reconnexion ne change dans R2-C.

## Observation et bornes conservées

L'adaptateur de campagne active une vérification de fraîcheur dans l'observateur
300 s existant : nouvelle donnée décodée ET avancement du témoin public
génération/séquence, timestamp de succès présent, owner actif/non échoué. Le
timestamp n'est jamais réécrit et l'ordre UTC ne remplace pas la corrélation.
Un drapeau HA de succès ou une copie du snapshot ne crée aucune acquisition.
Les appels historiques directs de l'observateur #112 gardent leur défaut et
leurs contrats ; seul l'adaptateur `hoben-live` de campagne active ce contrôle.

| Borne existante | R2 |
| --- | --- |
| Appels | 6, à 0/50/100/150/200/250 s depuis le premier échantillon |
| Observation | 300 s, y compris l'attente après la sixième acquisition |
| Collecte | 330 s maximum, ouverture comprise |
| Processus | 360 s maximum, cleanup/guardian/réapage compris |
| Ouvertures | 2 maximum ; une seule transition récupérable dans ce budget |
| Ressources | 1 Gio, 128 PID, sortie privée 8192 octets maximum |

La cadence de 50 s est celle de ce scénario historique, distincte du polling HA
résidentiel de 60 s. Aucun appel de rattrapage, ajustement de deadline, budget,
gate, ordonnanceur `all` ou workflow ne change. R1, dual, session-reconnect,
H1/H2, client distribué, lifecycle, protocole/framing/codec et délais B8 restent
inchangés. La politique de reprise reste celle du vrai client du banc.

## Validation et limites

RED sur base intacte : trois cas HA (EOF, CloseClient 3, timeout) avec ancienne
génération nettoyée et lecture corrélée neuve, mais SUCCESS refusé ; dix cas de
contrat Python/Node refusant pareillement la preuve complète. GREEN après
correction ; vrais client/coordinator/lifecycle, transport et horloge simulés.
Tests de pertes pendant acquisition et entre appels, nominal, cache B7 et
expiration à 300 s, cleanup échoué/annulé, annulation en lecture, framing et auth.
Fixtures d'omission/falsification, frontières temporelles, séquences et compteurs,
origines F1 distinctes, ressources, confinement et publication sans fuite.
Les régressions existantes protègent notamment 299999/300000 ms, annulation du
tail/cleanup, horloge rétrograde, fin avant 330 s et contrats #112/R1.

Les reçus des tests de contrat sont des fixtures, pas une preuve de confinement
réel. La validation structurelle ne signe pas un rapport arbitraire : provenance,
isolation, gates et contrôle du code restent indispensables. Aucun fait serveur
nouveau ni frontière OpenedClient universelle n'est établi. Une lecture TLS ne
prouve pas une frontière ; les rejets de framing ne sont pas ignorés par R2.

Aucun accès Hoben/HA résidentiel, test réel, dispatch/rerun, secret/GUID/RX brut,
valeur domestique, header/payload privé, exception libre, commande/écriture,
main, automation ou fusion DEV. V4 lecture seule et TLS certificat/hostname
vérifiés vers `myhoben.fr:465`. Quatre CI à vérifier au HEAD exact puis revue
MANAGER ; les tests synthétiques ne valident pas le service réel.
