# #126/033 — premier incident et récupération du banc dual-session

[Consigne MANAGER #6633368216](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6633368216),
autorisation propriétaire du 04/11/2026. Base experimental
`90da4a7ad5ced51ad3a7383e08ef6341bdee2459`, après #173/032 et #174/B4.
Cette livraison et ses preuves sont **hors ligne**, tests réels **NOT RUN**.

## Faits et portée

Le run manuel #41843581769 a six lectures A validées avant la demande +360 s,
sans réponse décodée ensuite. Le cleanup B est confirmé à +361,8 s ; A n'a
pas de cleanup confirmé. Ni CloseClient vers A, ni exclusivité serveur, ni
cause distante ne sont démontrés. Les injections de ce dossier sont des
scénarios synthétiques distincts, pas une reconstitution de messages privés.

Le test rouge montre que le banc transformait un wrapper HA contenant
`timeout` en `unexpected`. Un test séparé du vrai client confirme que son
timeout de lecture se récupère déjà avec le lifecycle existant : **aucun code
client/coordinator/lifecycle de production n'est modifié**. Seul le worker de
ce scénario active maintenant `ha_reconnect=True` ; les autres scénarios et
all ne changent pas. Vrais propriétaires partagés, sans second parseur/lecteur.

## Interruption admissible et reprise

Le contrat mesure une interruption de la septième acquisition A (départ
+360 s, tolérance 5 s), après six lectures valides, autour du close B. Il
borne sa preuve à une reprise A ; cela ne change pas les retries HA distribués.
Un CloseClient/EOF idle dans les cinq secondes autour de cette échéance peut
aussi précéder le septième poll : aucune émission ni lecture échouée sur le fil
n'est inventée. Un CloseClient qui annule une TX encore inachevée reste un refus
sûr du banc, pas une expiration authentique autorisant un nouveau retry.

- CloseClient complet reçu sur **A** : diagnostic B3 complet de deux octets,
  sous-code lu par le vrai RX sous hypothèse post-open. Sous-codes de refus
  d'identité/autorisation 2/4/5 terminaux ; aucun sous-code à partir de `05` seul.
- EOF réellement observé sur A, sans lui attribuer de CloseClient absent.
- Expiration du vrai délai de lecture A de 30 s, constatée par le propriétaire
  ou son objet `asyncio.Timeout` déjà expiré. Une erreur inconnue ne devient
  jamais un timeout par lecture de texte ou commodité.

Rôles et générations sont séparés. Un événement de B ne devient pas un
événement de A. Une réponse tardive mais antérieure à l'échéance, même
fragmentée, conserve la continuité. Après expiration, un éventuel en-tête
MBAP validé de réponse sur l'ancienne A peut être conservé comme métadonnée
`late_frame`, **sans créditer son corps, une acquisition ou de la fraîcheur**.
Il n'est pas une nouvelle réponse corrélée. Une seconde anomalie indépendante,
une frontière inconnue ou une preuve manquante refuse la réussite. Les messages
07/1B déjà délimités restent ignorés selon le contrat partagé.

Le même superviseur HA termine le close original et réape RX/TX/waiters ; la
génération suivante n'ouvre qu'après cleanup attesté **et 60 s de backoff**.
TLS/V4 frais, une lecture corrélée/décodée, puis **300 s stables sur cette
génération** sont requis. Une ouverture seule ne renouvelle ni snapshot ni date.
Le maintien A1 et l'âge du dernier succès restent visibles. Auth, erreur interne
générique, stop/unload, cleanup interrompu/annulé/échoué et seconde panne sont
terminaux pour la preuve ; aucune autre A n'est ouverte par le banc.
DataUpdated invalide seul conserve #160 (30 s glissantes/une sonde/sans close).

La cadence reste 60 s : demande échouée comptée comme telle, poll pendant le
backoff sans TX. La récupération peut prolonger l'observation jusqu'à +720 ou
+780 s, au plus 14 opportunités A et 15 demandes A+B, sans rattrapage rapproché.
Les minima 660 s et 300 s après cleanup réel B restent requis. Le plafond
global **900 s** commence avant préparation, réserve **60 s** pour teardown et
réapage ; aucune deadline n'est réarmée. Budget insuffisant = FAILURE.
Deux connexions simultanées au plus : deux générations A au maximum et une B,
jamais deux A en concurrence. B garde sa lecture unique et ses Pong normaux.

## Preuve et publication

Schéma 2, fermé et validé indépendamment par Python/Node :

- `incident` : premier événement avec rôle, génération, phase, temps relatif,
  échéance si timeout et sous-code/preuve B3 uniquement si réellement reçus ;
- `terminal` et `cleanup_errors` : refus et défauts secondaires séparés ; une
  fermeture échouée ne remplace jamais le diagnostic initial de la lecture ;
- `owners` : ouverture, acceptation, retour du close original et cleanup/réapage
  par génération, cohérents avec les compteurs agrégés ;
- acquisitions : émission réelle, génération/séquence, décodage, maintien,
  disponibilité, dernier succès/âge ; aucune valeur domestique.

`continuous` et `recovered` sont exclusifs. La récupération prouvée peut valider
le contrat opérationnel tout en conservant son incident et ses acquisitions
échouées. Un poll sans émission ou un en-tête tardif n'incrémente pas les lectures
décodées. Schéma 1 historique lisible, sans lui inventer de reprise. Les bornes
8192 octets par détail, 16384 par étape et 64 Kio par rapport restent inchangées ;
dépassement = refus. Le résultat exige aussi horloge native et réapage externe,
pas seulement un job collect vert. Les fixtures synthétiques ne sont pas du live.

Les tests couvrent les ordres close B / TX A, CloseClient A ou B, EOF sans
CloseClient, silence/délais, fragmentation, réponse post-timeout, cleanup lent,
annulé/échoué, stop, auth et erreur interne de nouvelle génération. Les refus
Python/Node couvrent les preuves absentes, contradictoires ou privées.
Pas de total universel OpenedClient, de verrou serveur inféré ou de changement
au protocole : TLS certificat/hostname vérifiés myhoben.fr:465, V4 lecture seule.
Aucun secret/GUID/RX/payload/header brut, valeur domestique ou exception libre ;
aucun test réel, dispatch/rerun, accès HA résidentiel, commande/écriture poêle,
modification de main ou d'automatisation. Revue/fusion réservées au MANAGER.
