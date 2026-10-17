# HOBEN-81-E7-CHAT-CAUSAL-DIAG-003 — diagnostic contractuel hors ligne

Cette tranche est **un diagnostic de validateurs publiés**, pas une
reproduction du producteur L7 v3 non publié. Aucun trafic réseau, aucune
capture, aucune commande et aucune horloge réelle n'interviennent.

## Deux instants propriétaires distincts

Dans le contrat v3 présent sur `experimental`, le premier rejet causal
est enregistré dans `causal_ms` et `rx_diagnostic.rejection_ms`.
La décision effective d'entrée en quarantaine est représentée par
`quarantine.entered_ms`. Ces points sont conceptuellement distincts.
Le validateur Python `scripts/session_suite_v3.py` impose pourtant
`causal == entered` ; son équivalent Node
`.github/scripts/session-suite-v3.cjs` impose `causal === entered`.
La même paire de validateurs exige la cohérence du diagnostic de rejet,
l'ordre EOF/consommation/acceptation et les limites de temps.

Le test `tests/test_session_causal_clock_diagnostic.py` part d'un rapport
v3 synthétique publié, sans inventer de nouvel événement : il ne varie que
les instants d'entrée en quarantaine et d'EOF, en conservant la cohérence
des deux copies du timestamp EOF. Il vérifie les deux validateurs :

- causal = entrée : contrat accepté lorsque l'EOF est strictement ultérieur ;
- entrée = causal + 1 ms : contrat rejeté malgré l'ordre chronologique
  EOF puis acceptation préservé ;
- entrée = causal - 1 ms : contrat rejeté ;
- EOF à l'entrée ou avant : refus, sans transformer le résultat en succès ;
- EOF strictement après l'entrée : cas témoin contractuel accepté.

Cela établit **la contradiction de représentation** et le comportement
fail-closed des validateurs actuels. Cela ne prouve pas que le vrai
`V4Session._begin_quarantine` a produit cet écart : le producteur
`session_suite_v3` de L7 n'est pas livré sur GitHub. Le commentaire
historique #6222094878 constitue un indice, non une preuve reproductible
avec les seuls composants publiés.

## Suite soumise à MANAGER

La correction minimale candidate serait de représenter fidèlement deux
instants monotones distincts avec `causal_ms <= entered_ms`, sous les
contraintes de provenance et de cohérence de la décision réelle ; **ce
document n'autorise ni n'implémente cette modification**. Avant tout
changement des validateurs, une tranche MANAGER doit définir la borne
admissible, la sémantique exacte du premier rejet et la preuve du producteur
réel. Ne pas décaler artificiellement un timestamp ni inventer un EOF.

Le verrou `quarantine-installation`, les gates, les rapports historiques,
les budgets H1/H2, les politiques L1–L7, les workflows et le runtime restent
inchangés. **session-300 : NOT RUN ; reconnexion : NOT RUN.** Étape 7 non
validée ; étape 8 suspendue.
