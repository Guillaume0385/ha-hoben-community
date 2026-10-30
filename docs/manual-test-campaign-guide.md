# Utiliser les deux campagnes manuelles Hoben

Les campagnes sont préparées sur `experimental`. Leur disponibilité dans le
formulaire Actions de `main`, les politiques effectives des environnements et
les résultats réels ne sont **pas attestés** par les tests hors ligne. Toute
collecte réelle demande une autorisation distincte du propriétaire ; cette
documentation n’en donne aucune. DEV ne lance ni dispatch ni rerun.

## Choisir et lancer, après autorisation distincte

1. Dans **Actions**, choisir **Tests expérimentaux MyHOBEN** pour le protocole,
   ou **Vérification réelle Home Assistant** pour le véritable client/coordinator
   Home Assistant. Les fichiers sont respectivement
   [hoben-protocol-manual.yml](../.github/workflows/hoben-protocol-manual.yml) et
   [hoben-ha-manual.yml](../.github/workflows/hoben-ha-manual.yml).
2. Dans **Run workflow → Use workflow from**, sélectionner la branche native
   autorisée (`experimental` ou `main`) et le scénario. Le YAML et le code sont
   ceux du commit choisi par GitHub ; aucune substitution de branche n’existe.
   Si le formulaire est absent, faire vérifier sa disponibilité et obtenir une
   autorisation de promotion ; ne pas employer un ancien workflow comme repli.
3. Le propriétaire `Guillaume0385` effectue le lancement manuel. Les deux
   identités GitHub `actor` et `triggering_actor` sont contrôlées. Un commit
   documentaire est admis et les reruns sont autorisés, sans preuve de PR,
   revue, CI préalable ou claim personnalisé à l’admission.
4. Respecter les attentes et approbations natives de l’environnement
   `hoben-experimental` (protocole) ou `hoben-live` (HA). Aucune modification de
   protection ni approbation de substitution. L’état effectif doit être vérifié
   avant la première campagne autorisée ; il n’est pas déduit du YAML.
5. Attendre la fin du run et lire le résumé du job **result**. Le mutex commun
   `hoben-read-only-observation` sérialise les campagnes sans annuler une collecte
   active. Un scénario `all` exécute ses étapes indépendamment et dans l’ordre
   ci-dessous, avec nettoyage entre elles.

Le lancement ne vient jamais d’un push, d’une PR, d’une fusion, d’un label ou
d’une programmation. Les quatre CI restent obligatoires pour les PR de
développement ; elles n’accèdent pas au service Hoben. L’ancien workflow manuel
est historique pour cette procédure, reste inchangé et partage le même mutex.

## Choisir un scénario protocole

| Choix | Ce qu’un résultat positif atteste | Maximum absolu, nettoyage inclus |
| --- | --- | --- |
| `tls-only` | TLS vérifié, sans message applicatif. | 15 s |
| `session-open` | Ouverture V4 avec l’identité initiale documentée, sans association. | 30 s |
| `read-v4-state` | Réponse corrélée à une lecture fixe de 20 registres V4 ; aucune valeur publiée. | 45 s |
| `h1h2` | Douze observations bornées collectées. Résultat scientifique **INCONCLUSIVE**, aucune frontière universelle démontrée. | 1800 s ; 6 H1 + 6 H2, 90 s et 1 Mio RX par session |
| `session-300` | Fenêtre utile de 300 s du collecteur existant et réponse corrélée. | 360 s ; 3 ouvertures, 6 lectures maximum à cadence ≥60 s, 1 Mio RX total |
| `session-reconnect` | Test expérimental : Pong inhibés dès 120 s sur la première génération, perte puis réouverture avant 240 s, lecture corrélée, Pong rétablis et 120 s stables. Sans ces preuves : INCONCLUSIVE. | 600 s ; 3 ouvertures, 10 lectures maximum à cadence ≥60 s, 1 Mio RX total |
| `all` | Les six étapes ci-dessus, séquentiellement, orchestration et nettoyage inclus. | 3000 s (50 min) ; somme des maxima individuels 2850 s, marge 150 s |

`transport` ne démontre ni un EOF TLS ni une cause serveur. `close_client`
conserve sa catégorie et son sous-code numérique. L’inhibition des seuls Pong
du client de test est réservée à ce scénario expérimental ; elle ne démontre
aucune causalité serveur et ne modifie pas la reconnexion HA naturelle. Les
48 octets d’OpenedClient restent un préfixe décodable, pas une longueur totale
universelle. La campagne protocole ne valide pas l’intégration HA.

## Choisir un scénario Home Assistant

| Choix | Observation avec les vrais HobenClient et coordinator | Maximum absolu, nettoyage inclus |
| --- | --- | --- |
| `hoben-live` | Preuve #112 réutilisée : 6 refreshs, session persistante encore active à 300 s utiles monotones. | 360 s, collecte 330 s |
| `open-errors` | Un refresh d’ouverture/lecture réussi, ou son erreur catégorielle. Ne provoque aucune erreur d’identifiants. | 90 s |
| `refresh-v4` | Deux refreshs décodés successifs, tous deux réussis. | 120 s |
| `session-reuse` | Trois refreshs réussis, réutilisation de génération et nouvelles séquences corrélées. | 180 s |
| `session-reconnect` | Test HA isolé : inhibition des seuls Pong après 120 s, perte effective, réouverture avant 240 s, lecture corrélée puis 120 s stables avec Pong rétablis ; sinon INCONCLUSIVE. Aucun changement aux Pong du client HA installé. | 600 s ; 2 ouvertures, 6 refreshs maximum |
| `cleanup` | Un refresh puis fermeture effectivement attestée. | 60 s |
| `availability` | Deux refreshs réussis et disponibilité constatée du coordinator à la fin de l’observation. | 120 s |
| `all` | Les sept étapes ci-dessus, indépendantes et séquentielles. | 1800 s ; somme des maxima individuels 1530 s |

Chaque exécution HA garde **1 Gio de mémoire agrégée**, **128 PID/threads**,
six refreshs maximum et la limite actuelle du vrai client de deux ouvertures.
L’arbitrage permet trois ouvertures de reconnexion HA ; cette implémentation
reste plus restrictive avec deux. Le plafond global `all` est de quinze
ouvertures et quarante-deux refreshs. **Aucun quota, compteur ou proxy RX HA.**
Ces maxima ne sont pas des durées minimales ni des preuves de réussite.

Une lecture ultérieure réussie n’efface pas une erreur antérieure dans les
compléments ordinaires. La reconnexion est distincte : une lecture en échec
peut précéder une récupération positivement attestée. Une simple réouverture
ne suffit jamais. La disponibilité n’est pas déduite d’un ancien snapshot si
la session n’est plus active à la fin de l’observation.

## Lire le résumé et le rapport

Le résumé **result** donne la sélection, le résultat global, le résultat du job
`collect`, les totaux des quatre statuts, la durée globale et le plafond absolu.
La provenance **informative** est ref/SHA/run/tentative : ce n’est ni une preuve
de validation réelle ni un contrôle supplémentaire de PR/merge/CI à l’admission.
Le tableau indique pour chaque scénario le statut, le diagnostic catégoriel,
la durée, le plafond, les lectures réussies/tentées et le nettoyage attesté.

| Statut | Interprétation |
| --- | --- |
| SUCCESS | Les critères positifs et le nettoyage sont attestés pour cette étape. |
| FAILURE | Erreur, dépassement, preuve incohérente/incomplète ou nettoyage manquant. |
| INCONCLUSIVE | Observation bornée effectuée, mais hypothèse/récupération non démontrée. Ce n’est pas une validation. |
| NOT RUN | Étape non commencée ou preuve absente/refusée. Ne démontre pas à lui seul qu’aucune connexion n’a pu avoir lieu. |

`all` continue après une étape INCONCLUSIVE entièrement collectée/nettoyée ;
FAILURE ou NOT RUN arrête la suite et laisse les étapes restantes NOT RUN.
Le verdict global est SUCCESS seulement si toutes les étapes sont SUCCESS
**et** le job `collect` a réussi. H1/H2 étant INCONCLUSIVE, `all` protocole
reste donc globalement FAILURE. Un `collect` annulé/échoué garde un verdict
global FAILURE même si une étape précédente est localement attestée SUCCESS.

Les diagnostics sont fermés : `observed`, `not_observed`, catégories d’erreur
d’ouverture/transport/protocole, `timeout`, `cancelled`, `memory`, `processes`,
`cleanup_failed`, `report_refused`, `supervisor_refused`, etc. Aucun texte
d’exception privé n’est nécessaire pour leur interprétation. Admission refusée :
NOT RUN, sans déclarer à tort que les collecteurs ne sont pas raccordés.

Seul le JSON anonymisé validé est publié sur le runner **result**, sans
environnement ni secret Hoben, dans un artefact nommé
`protocol-campaign-<SHA>-<run>-a<tentative>` ou
`ha-campaign-<SHA>-<run>-a<tentative>`, conservé **sept jours maximum**.
Le JSON contient les preuves allowlistées et les durées ; le résumé présente
aussi les plafonds dérivés du catalogue fixe. Rapport absent, corrompu ou trop
volumineux : aucun artefact de repli, NOT RUN et FAILURE global. Une annulation
du run peut empêcher le job result lui-même de s’exécuter ; son absence ne
constitue aucune preuve de succès.

## Limites et sécurité

Lecture seule, lectures fixes, TLS certificat/hostname vérifiés vers
`myhoben.fr:465`. Aucune commande poêle, écriture Modbus 06/16/22, association,
consigne, ventilation ou marche/arrêt. Aucun GUID, secret, RX brut, valeur
domestique, exception libre ou journal privé dans les rapports ou les logs.

Les tests déterministes valident les contrats Python/Node, la supervision et
le vrai chemin HA avec peers simulés. Ils ne démontrent ni le comportement réel
du serveur ni la disponibilité UI de `main` ou les protections effectives.
La préparation de la validation réelle et toute promotion main restent des
étapes séparées, autorisées explicitement par le propriétaire.

Pour la maintenance et les plafonds détaillés :
[contrat d’exécution](manual-test-campaign-runtime.md),
[admission actuelle](manual-test-campaign-admission-contract.md) et
[consigne MANAGER actuelle](https://github.com/Guillaume0385/ha-hoben-community/issues/126#issuecomment-6435985641).
