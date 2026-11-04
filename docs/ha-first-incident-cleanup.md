# HA-F1 — premier incident et nettoyage du propriétaire HA

Tâche exclusive [HOBEN-126-HA-F1-FIRST-INCIDENT-CLEANUP-010](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6641303570),
issue #126, base `experimental` `744a22992664695f19ef106bdcf4c1acddbefdb6` après
fusion de #163/B6/#179. #163 reste prioritaire si une correction principale est
réactivée ; cette instrumentation ne lance pas HA-F2 ni une autre tâche.

## Portée

Les observations des sept scénarios HA existants et du dual optionnel reçoivent
un diagnostic commun. Le chemin HA conserve les vrais HobenClient, coordinator,
V4Lifecycle et V4Session ; les décorateurs de test appellent chaque opération
originale une seule fois. Les wrappers observent des types/événements fermés et
des états locaux, sans parser, copier ou conserver un paquet. Aucun horaire,
Pong, lecture, backoff, retry, décision de scénario ou quota n'est ajouté.

Le module reste dans `scripts/`, embarqué en lecture seule dans le bundle de
campagne isolé. Aucun import depuis le plugin distribué. Le chemin historique
autonome #112 et ses anciens rapports restent inchangés ; le scénario hoben-live
de la campagne réutilise toujours cet observateur, décoré seulement pour F1.
Les workflows/gates, sept choix historiques de all, ordonnanceur, budgets et
plafond de sortie **8192 octets** sont conservés. Dépassement : refus, jamais repli
sur un rapport privé ou troncature qui ferait disparaître une cause.

## Paire de version et champs publics

Les nouveaux rapports contiennent ensemble `diagnostic_schema: 1` et
`diagnostic`. L'un sans l'autre, une version inconnue, clé additionnelle ou
structure incohérente est refusé par Python et Node. Les rapports historiques
sans cette paire restent lisibles et **n'attestent aucun diagnostic F1** ; les
requalifier comme preuve F1 exigerait les champs validés. Une validation de
structure n'est pas une signature d'authenticité d'un rapport arbitraire : les
contrôles de provenance de publication restent inchangés.

Le diagnostic contient `end_ms`, `first`, `terminal`, `cleanup`, `owners` et
`invalid`. Tous ses temps sont relatifs au **début de la collecte F1**, y compris
ouverture et teardown. Ils ne sont pas une heure du foyer. Le dual conserve
séparément son T0 après acceptation ; ses témoins sont recoupés avec ce décalage.

Les trois événements sont null ou un tuple fixe :

| Index | Champ |
| --- | --- |
| 0–1 | rôle a/b, ordinal local du propriétaire (tentative 1/2) |
| 2 | temps relatif en ms |
| 3 | catégorie fermée |
| 4 | phase fermée du contrat existant |
| 5 | source transport_connect/read/write/close, session ou observer |
| 6 | sous-code uniquement pour CloseClient complet réellement reconnu |

`first` est figé au premier incident du véritable propriétaire ou de ses
diagnostics structurés B3. Un poll ultérieur ne le remplace pas. `terminal`
conserve le premier refus terminal du propriétaire ou de l'observation ; un
arrêt volontaire de fin de scénario n'invente pas une erreur. `cleanup` conserve
le premier échec réel de fermeture ou l'absence de preuve finale de libération.

Les catégories incluent timeout, eof, close_client, transport, tls, protocol,
internal, cancelled, authentication, authorization, cleanup_failed, closed et
exhausted. EOF vient du transport ; CloseClient exige le chemin complet du
framer et son sous-code prouvé. Ni silence, préfixe isolé, annulation locale,
erreur interne ni fermeture locale ne prouvent une cause serveur. Une longueur
universelle d'OpenedClient n'est toujours pas établie.

Chaque propriétaire expose seulement rôle, ordinal, `accepted`, `accepted_generation`, `close_client_subcode`, `stage`,
`close`, `pending`, `last_read`. Une tentative refusée n'est pas une génération
acceptée ; l'ordinal seul ne prouve aucune connexion TLS. `accepted_generation`
compte les ouvertures réellement acceptées et reste null après un refus : une
seconde tentative peut être la première génération acceptée. Lectures et
témoins sont liés à cette génération, sans créditer la tentative refusée.
Les tableaux restent
de taille fixe, au plus deux propriétaires a et un b :

- `close` : demande, début de l'appel close transport, retour réussi de cet
  appel, attestation finale par le vrai propriétaire. Null signifie non attesté.
  Un retour de close sans ouverture acceptée ne prouve pas un handshake TLS.
- `pending` : masque entier 0–127, bits 0 à 6 : RX actif, TX en cours/attente, waiter présent,
  transport possédé, sonde de récupération active, ouverture active, opérations
  appelantes actives. Zéro exige tous ces témoins inactifs ; les booléens et
  bits additionnels sont refusés. Ce codage garde le plafond de 8192 octets.
  Un transport détaché ne prouve jamais sa fermeture.
- `stage` : active, stop_operations, session_close, transport_release,
  tls_close, tls_closed ou reaped ; progression locale, pas statut serveur.
  `construction_failed` désigne un constructeur refusé : aucune ouverture
  acceptée, fermeture ni ressource attestée, pending null (ressources inconnues).
- `close_client_subcode` : sous-code du CloseClient complet reconnu par le vrai
  propriétaire, sinon null. Il conserve la preuve typée si une annulation du
  cleanup empêche la publication du témoin de perte par le lifecycle ; aucun
  CloseClient n'est déduit du timeout, de l'EOF ou du nettoyage.
- `last_read` : séquence, temps de validation, âge calculé à end_ms, ou null.
  Pour a, le coordinator doit avoir accepté une nouvelle acquisition avec son
  vrai témoin corrélé ; b conserve sa seule lecture V4 corrélée autorisée.
  Une erreur, un poll, une ouverture ou un snapshot conservé ne réarme pas l'âge.

L'attestation exige le vrai `cleanup_succeeded`, le retour du close transport et
aucune ressource encore active. Un close idempotent ultérieur ne remplace pas
un close en échec. Une annulation de l'observateur après libération effective
ne devient pas à elle seule un faux échec de cleanup ; une fermeture réellement
interrompue ou non attestée reste explicitement en échec.
Le diagnostic est une copie figée à la collecte : une fermeture ultérieure du
worker ne peut pas compléter rétroactivement ses preuves de fermeture.

## Preuves et limites

Les tests rouges initiaux démontrent l'absence de diagnostic dans deux rapports
solo timeout/close. Les tests verts utilisent le vrai chemin HA sur transports
et horloge synthétiques : fermeture réussie/échouée, première cause persistante,
annulation avant ou pendant close, EOF, TLS, CloseClient fragmenté et erreur
locale. La dernière acquisition reste ancienne pendant l'interruption.

Les fixtures indépendantes Python/Node vérifient omissions, types exacts,
booléens, bornes, chronologie, rôle/ordinal, ressources, sous-code, âge, non-fuite,
résumé public et plafond de sortie. Les preuves de cleanup/lectures sont liées
aux témoins existants ; supprimer ou contredire une preuve courante est refusé.
Les métriques et verdicts des fixtures historiques sont identiques avec ou sans
F1 ; une erreur de collecte du diagnostic invalide la preuve au lieu de changer
le fonctionnement réseau ou d'inventer un succès.

Les rapports existants et le rapport passif #163 ne permettent pas de produire
rétrospectivement ce diagnostic. Les validations hors ligne ne prouvent pas la
cause d'une panne réelle. Résultats unitaires/HA/Ruff et quatre CI à consigner
sur le HEAD exact de la PR ; aucun succès implicite pour une CI non exécutée.

Validation réelle **NOT RUN**. Aucun Hoben/HA résidentiel, workflow live,
dispatch/rerun, écriture Modbus, commande poêle, secret/GUID/RX/header/payload
brut, valeur domestique ou exception libre publié. Aucun DEBUG global, main,
automatisation ou fusion. TLS certificat/hostname vérifiés et V4 lecture seule
conservés ; revue/fusion exclusivement MANAGER.
