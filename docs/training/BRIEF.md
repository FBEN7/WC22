# Brief de formation : Football Data Analyst côté fournisseur de données

## Le rôle visé

Chez un fournisseur (Hudl StatsBomb, Stats Perform/Opta, SkillCorner…), le
client achète de la **donnée fiable** et des **métriques défendables**. Un
analyste doit donc savoir :

1. lire le modèle de données événementiel et ses pièges (repères de coordonnées,
   périodes, définitions d'événements) ;
2. prouver qu'une donnée est juste ou fausse (contrôles qualité) ;
3. répondre en SQL à une question client, avec une définition précise ;
4. construire et évaluer un modèle (xG, valeur de possession) sans se mentir ;
5. expliquer tout cela à quelqu'un qui n'est pas analyste.

Chaque jalon ci-dessous travaille un de ces points. Le socle (téléchargement,
entrepôt DuckDB, harnais de tests, page « Match centre ») est fourni. Le reste
est à toi.

## Règles du jeu

- **Les tests sont le cahier des charges.** Un test « SKIPPED TODO » est un
  travail à faire. Un jalon est terminé quand son fichier de tests passe sans
  aucun skip.
- **Les tests ne suffisent pas.** Pour chaque jalon, écris `notes/Mx.md` (une
  page maximum) : les choix faits, ce que tu as trouvé dans les données, les
  limites. C'est ce texte qu'on te fera défendre en entretien.
- **Une branche et une PR par jalon** sur ton repo, même si tu es seul. Les
  recruteurs regardent l'historique.
- Ne cherche pas de solution toute faite avant d'avoir bloqué au moins une
  heure. Lire la doc StatsBomb (`doc/` du repo open-data) est autorisé et
  recommandé.

## Mise en route

```bash
pip install -e ".[dev]"
python -m fdl download --fixtures   # 3 matchs piégés, pour les tests
pytest                              # 11 passed, 29 skipped
python -m fdl download && python -m fdl build   # 3 tournois complets
```

Les 3 matchs de test sont choisis pour leurs pièges : la finale 2022
(prolongation + tirs au but), Canada–Maroc (le but canadien est un csc) et
Pays de Galles–Iran (carton rouge, buts dans le temps additionnel).

---

## M1 — Qualité des données · `src/fdl/quality.py`

**Objectif :** cinq contrôles automatiques. `check_coordinates_in_bounds` est
l'exemple corrigé.

**Ce que tu vas découvrir :** la donnée ouverte contient de **vrais défauts**.
Les tests en exigent la détection exacte : deux horodatages faux dans la finale,
et cinq joueurs de la finale dont les périodes de poste sont dans le désordre ou
se chevauchent. Il y a aussi un piège inverse : des milliers de liens
`related_events` à sens unique qui ne sont **pas** des défauts. À toi de
trouver lesquels et pourquoi.

**Livrable écrit :** lance `python -m fdl quality` sur les trois tournois.
Pour chaque contrôle qui échoue : combien de violations, deux exemples, et ton
hypothèse (erreur de collecte, de traitement, ou règle mal comprise de ta part).

**Questions d'entretien :**
- Un client dit que le score d'un match est faux dans votre API. Comment
  enquêtes-tu ?
- Quelle différence entre un contrôle bloquant et un contrôle d'alerte ?
  Classe tes cinq contrôles.
- Comment repérer un collecteur qui se trompe *systématiquement* (et pas au hasard) ?

## M2 — SQL analytique · `sql/*.sql`

**Objectif :** minutes jouées, profil de passe par 90 minutes, PPDA.
`00_example_team_shots.sql` est l'exemple corrigé. Chaque fichier devient une
vue, donc `02` réutilise `minutes_played`.

**Pièges :** les minutes ne se calculent **pas** avec `lineups` (M1 t'a montré
pourquoi). La séance de tirs au but n'est pas du temps de jeu. Pour le PPDA,
chaque équipe a son propre repère de coordonnées : le seuil sur `x` n'est pas
le même pour les passes adverses et pour tes actions défensives.

**Livrable écrit :** les 10 meilleurs passeurs progressifs par 90 minutes des
trois tournois, avec le seuil de minutes que tu as choisi et pourquoi. Le PPDA
des quatre demi-finalistes de 2022, avec une phrase sur ce que la métrique ne
voit pas.

**Questions d'entretien :**
- Pourquoi `passes_p90` d'un joueur à 25 minutes est-il trompeur ? Que fais-tu ?
- Deux fournisseurs donnent des PPDA différents pour le même match. Pourquoi ?

## M3 — Modèle xG · `src/fdl/xg.py`

**Objectif :** géométrie du tir, au moins deux variables tirées du freeze
frame (défenseurs dans le cône, position du gardien…), validation croisée
**groupée par match**. `evaluate` et `calibration_table` sont fournis.

**Barre à atteindre** (test `test_model_on_full_data`, base complète) : faire
mieux que distance + angle seuls, **sans** battre largement le xG de
StatsBomb. Si tu le bats de loin, tu as une fuite de données (par exemple
`end_location`, qui n'est connue qu'après le tir). Pour repère : sur la Coupe
du monde 2022, un modèle logistique simple atteint un log loss d'environ 0,28,
contre 0,34 pour la constante et 0,27 pour StatsBomb.

**Livrable écrit :** tableau log loss / Brier / AUC (constante, distance +
angle, ton modèle, StatsBomb), courbe de calibration, et les trois tirs où toi
et StatsBomb êtes le plus en désaccord, avec ton explication.

**Questions d'entretien :**
- Pourquoi le log loss plutôt que l'AUC pour un modèle de xG ?
- Pourquoi grouper la validation par match ? Que se passe-t-il sinon ?
- Ton modèle est entraîné sur des tournois masculins. Peux-tu l'appliquer à
  l'Euro féminin 2025 ? Comment le vérifierais-tu ?

## M4 — Expected Threat · `src/fdl/xt.py`

**Objectif :** la grille xT de Karun Singh par itération, puis la valeur de
chaque passe ou conduite. Le test sur deux cellules est calculé à la main dans
la docstring : refais le calcul sur papier avant de coder.

**Livrable écrit :** les 10 meilleurs joueurs en xT ajouté par 90 minutes,
puis trois limites du xT. Par exemple : il ignore les défenseurs, ne crédite
pas le joueur qui perd le ballon, et souffre de cellules vides avec peu de
données. Explique en quoi un modèle comme l'OBV de StatsBomb répond à certaines
de ces limites.

## M5 — Application Streamlit · `app/streamlit_app.py`

**Objectif :** compléter les pages « Data quality », « xG model »,
« Expected threat » et « Player profile » (radar en percentiles, avec la
taille de l'échantillon affichée). La page « Match centre » sert d'exemple.

**Critère :** une personne qui n'a jamais vu le projet comprend chaque page
sans tes explications. Fais-la tester par quelqu'un.

## M6 — Synthèse portfolio · section *Findings* du README

En anglais (les offres des fournisseurs sont en anglais) : trois constats
chiffrés, un ou deux visuels, les limites. Mets à jour le tableau d'avancement
du README. Respecte la licence StatsBomb (attribution) si tu publies.

---

## Prolongement conseillé : données de tracking

Les fournisseurs vendent de plus en plus de tracking (SkillCorner, Hudl/Veo…).
Ton repo `Veo` produit déjà du tracking à partir de la vidéo. Un M7 naturel :
charger les données ouvertes de SkillCorner ou de Metrica dans le même
entrepôt, puis relier événements et positions. Par exemple : la pression réelle
sur le porteur au moment de la passe, comparée au flag `under_pressure` de
StatsBomb.
