Analyse la couverture de tests sur le nouveau code signalé par SonarQube et ajoute les tests manquants.

## Étapes

1. Récupérer les mesures de couverture via `mcp__sonarqube__get_component_measures` (project key : `Upellift99_ovispect_eb1d2582-6a12-4f42-b76e-af6ed00a10f7`, metrics : `new_coverage,new_uncovered_lines,new_lines_to_cover`)
2. Récupérer les issues de type `CODE_SMELL` avec tag `coverage` ou de type `new_coverage` via `mcp__sonarqube__search_sonar_issues_in_projects` si disponible
3. Identifier les fichiers avec la plus faible couverture sur le nouveau code
4. Pour chaque fichier (un à la fois) :
   - Lire le fichier source pour comprendre la logique à tester
   - Identifier les branches et lignes non couvertes
   - Écrire ou compléter les tests selon les conventions du projet (cf. `CLAUDE.md` ou `README`)
   - Lancer les tests et le typecheck pertinents pour le projet
   - Proposer un commit : `test: add tests for <composant/module>`
5. Attendre validation avant de passer au fichier suivant
