"""
Versioning du modèle de scoring — source de vérité unique.

Bumper ce numéro à chaque changement de weights, de fonctions de scoring,
ou de seuils de tier. Une version = un ensemble de paramètres reproductible.

Format : MAJOR.MINOR.PATCH
  MAJOR : changement de dimensions (ex: ajout d'un 8e critère)
  MINOR : changement de weights ou de seuils tier
  PATCH : bug fix n'affectant pas les résultats finaux
"""

MODEL_VERSION = "1.0.0"
