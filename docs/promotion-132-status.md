# Bilan de promotion experimental → main — 26 octobre 2026

## Situation

La PR [#132](https://github.com/Guillaume0385/ha-hoben-community/pull/132) prépare la promotion **intégrale** du contenu de `experimental` vers `main`, avant les travaux distincts de l'Issue #126 sur les campagnes manuelles de tests.

Le commit de réconciliation `17c44d99ab7e57b040248a6726af606f9b09302c` a deux parents : ancien `experimental` `762f217710ba4e062cba09c4e101412e94393cb3` et `main` `2e7d5cf80f2301a3afce966a6edebfe3c9f7383f`. Son arbre Git `1cba874c3602ed4473fa9ff9ef5b805b14a20acd` est identique à celui de l'ancien `experimental` ; cette réconciliation n'a modifié aucun fichier applicatif, workflow, test ou documentation.

La CI [Validate #40409269635](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/40409269635) sur ce commit est SUCCESS : `tests`, `ha-tests`, `hacs` et `hassfest`.

## Derniers tests réels et blocage de provenance

Sur le commit précédent `762f217...`, les deux campagnes avaient réussi :
- [expérimental #40398217063](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/40398217063) : session continue 300 s, reconnexion observée et stabilité 120 s ;
- [Home Assistant #40397615689](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/40397615689) : client HA réel, session continue 300 s.

Sur le commit de réconciliation `17c44d9...`, les relances [expérimentale #40409948231](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/40409948231) et [HA #40410020067](https://github.com/Guillaume0385/ha-hoben-community/actions/runs/40410020067) ont échoué **au preflight**, avec collecte SKIPPED : **NOT RUN**, pas d'échec fonctionnel du client ou du protocole.

Le gate `.github/scripts/manual-hoben-gate.cjs` exige notamment un HEAD `experimental` issu d'une PR revue, fusionnée sur `experimental`, avec arbre candidat identique et CI `pull_request` validée. Le commit de réconciliation a été publié directement, sans cette provenance. Ne pas désactiver ou contourner le gate.

## Tranche documentaire de régularisation

Cette PR documentaire ne modifie que ce bilan et ne change ni le protocole, ni le client, ni les workflows, ni les règles de sécurité. Après revue, CI et fusion sur `experimental`, son commit de fusion devra être vérifié comme nouvelle provenance admissible. **Les deux campagnes réelles doivent être redéclenchées manuellement sur le nouveau SHA exact**, sous réserve des gates et approbations d'environnement. Un succès CI n'autorise pas à lui seul les tests live.

La PR #132 vers `main` reste en attente des validations réelles concluantes sur ce nouveau HEAD. Ne pas fusionner vers `main` avant cette revue MANAGER. L'Issue #126 reste distincte et non commencée.

Règles inchangées : lecture seule, TLS vérifié vers `myhoben.fr:465`, aucune écriture Modbus 06/16/22 ni commande poêle, aucune donnée privée ou RX brut, aucune longueur totale universelle inventée pour `OpenedClient`.
