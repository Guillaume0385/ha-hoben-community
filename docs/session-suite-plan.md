# Suite « Tests expérimentaux session » — tranche structurelle 7/8-E

La [consigne MANAGER](https://github.com/Guillaume0385/ha-hoben-community/issues/81#issuecomment-6176992612)
demande une suite unique, sur le workflow push `experimental` existant :
`session-300`, puis `session-reconnect-no-pong`. L'étape 8 est suspendue.
La validation historique de la session continue reste acquise :
[run 38766830984](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/38766830984),
SHA `4ea1c802155b95014d50c6a4aab8250621959466`, résultat vérifié par MANAGER
`continuous_300s`, sans reconnexion. Elle ne valide pas le nouveau scénario ni
la suite, et ne prouve aucune frontière universelle OpenedClient.

## Installation structurelle : aucun accès réel

La suite complète dépasse une petite PR. Cette première tranche livre seulement
la politique opt-in `NoPongAfter120`, son raccordement au vrai `V4Session`, et
ses tests avec le vrai `V4Lifecycle`. Aucun collecteur live n'instancie cette
politique. Le scénario `session-300` conserve son fonctionnement par défaut.

Le job initial `suite-installation` échoue inconditionnellement, sans checkout,
permission, environnement ni secret. Il écrit deux résultats **NOT RUN** dans
le résumé du run. `dry-run` en dépend et ne peut continuer ; admission, collecte
et publication restent derrière leurs dépendances et conditions existantes.
Une ancienne autorisation session-300, même authentique, ne lève pas ce verrou.
Cette pause mécanique empêche une exécution réelle du premier scénario seul.
Elle ne modifie aucun Setting, secret, claim, gate historique ou H1/H2.

## Politique de Pong testée hors ligne

- Le délai monotone de 120 s part de l'ouverture strictement acceptée de la
  première génération. Seule la réponse Pong à un Ping déjà reçu est inhibée.
- La décision est prise sous le verrou TX juste avant l'émission ; lectures V4
  et unique propriétaire RX restent inchangés. Aucun timer ne ferme le transport.
- Toute nouvelle génération rétablit les Pong normaux. Le lifecycle partagé
  reste propriétaire des pertes, du nettoyage et du backoff borné.
- Seul un EOF effectivement reçu est compté comme fermeture du pair. Fermeture
  locale, silence et erreur TLS générique ne sont pas des preuves d'EOF serveur.
  Un EOF après inhibition est une observation temporelle, pas une preuve de
  timeout Ping. Aucun payload, registre, identifiant ou exception n'est exporté.

Cette tranche ne fournit ni le second collecteur, ni un rapport public de suite,
ni la mesure des 120 s stables après reconnexion. Les compteurs de politique
restent en mémoire ; aucune nouvelle projection publique n'est activée.

## Proposition de plafonds, à approuver avant activation

| Budget | Proposition non activée |
| --- | --- |
| Scénario 1 | 300 s utiles ; plafond 360 s inchangé. |
| Scénario 2 | Plafond dur 600 s, nettoyage inclus ; au plus trois ouvertures, 1 Mio RX cumulé et dix lectures fixes espacées d'au moins 60 s. |
| Attente après inhibition | Au plus 180 s après T+120, puis `no_disconnect` ou `not_exercised`, sans forcer la fermeture serveur. |
| Après réouverture | 120 s stables, avec lecture corrélée et Pong rétablis ; aucune attribution causale automatique. |
| Suite | Plafond dur 1020 s : 360 + 600 + 60 s de marge d'orchestration/nettoyage. |

Ces valeurs sont une proposition de revue, sans autorisation live. La future
activation devra borner explicitement connexion, ouverture, backoff et nettoyage
dans ces plafonds. Le budget historique de six lectures de `session-300` reste
inchangé ; les dix lectures proposées concernent seulement le futur scénario 2.

## Suite requise avant toute activation

Une tranche MANAGER suivante devra installer ensemble : l'orchestrateur séquentiel
sur le collecteur/launcher existant, les budgets distincts, deux sous-rapports
stricts Python/Node, le statut global et le nouveau contrat d'approbation de suite
liant SHA, CI, deux scénarios et plafonds approuvés. Un premier résultat non valide
doit laisser le second NOT RUN. Sans Ping inhibé : `not_exercised` ; sans perte
observée : `no_disconnect` ; sans reprise/stabilité : échec ou inconclusif.

Le nouveau contrat doit refuser les anciennes décisions et claims session-300,
conserver les gates acteur/SHA/CI/environnement/recheck et la publication isolée,
et réserver une nouvelle autorisation anti-rejeu de suite. Le verrou structurel
ne pourra être retiré que dans cette activation complète revue par MANAGER.
DEV/CI restent offline ; ni rerun ancien, ni workflow indépendant, ni déclencheur
manuel, ni HA/hoben-live/main, ni commande/association/écriture Modbus.
