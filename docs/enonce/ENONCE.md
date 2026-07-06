# Automatic Fraud Detection Project

> **Source :** https://app.jedha.co/course/etl-with-airflow-lds/automatic-fraud-detection-project-lds  
> **Type :** Projet de certification — Bloc 3 AIA (RNCP38777)  
> **Durée estimée :** 90 min

---

## Contexte 📇

La fraude est un problème majeur pour les institutions financières. En 2019, la [Banque Centrale Européenne](https://www.ecb.europa.eu/pub/cardfraud/html/ecb.cardfraudreport202110~cac4c418e8.en.html) estimait que les transactions frauduleuses par carte de crédit représentaient plus d'**1 milliard d'euros** dans l'UE.

L'IA peut aider à résoudre ce problème en détectant les paiements frauduleux de manière très précise — c'est aujourd'hui l'un des cas d'usage les plus répandus chez les Data Scientists.

Cependant, même si nous parvenons à construire des algorithmes performants, la difficulté réside désormais dans leur **mise en production** : prédire les paiements frauduleux en temps réel et y répondre de façon appropriée.

---

## Objectifs du projet 🎯

Le métier a exprimé deux besoins :

- **Être notifié dès qu'une fraude est détectée** (une simple notification suffit)
- **Consulter chaque matin un récapitulatif** de tous les paiements et fraudes de la veille

---

## Données disponibles

### Dataset historique — Fraudulent Payments

- **URL :** [fraudTest.csv](https://lead-program-assets.s3.eu-west-3.amazonaws.com/M05-Projects/fraudTest.csv)
- Contient un grand nombre de paiements labellisés (frauduleux ou non)
- À utiliser pour entraîner l'algorithme de détection

### API temps réel — Real-time payment API

- **URL :** [Real-time Fraud Detection (HuggingFace Space)](https://huggingface.co/spaces/sdacelo/real-time-fraud-detection)
- Endpoint `/current-transactions` : récupère les paiements en cours
- Mise à jour **toutes les minutes**
- À utiliser pour les prédictions en temps réel

---

## Livrables 📬

| Livrable | Description |
|----------|-------------|
| **Schéma d'infrastructure** | Diagramme (PowerPoint, Word…) expliquant l'architecture choisie et les raisons de ce choix |
| **Code source** | Tous les éléments nécessaires pour construire l'infrastructure |
| **Vidéo de démonstration** | Enregistrement de l'infrastructure en fonctionnement ([Vidyard](https://www.vidyard.com/) recommandé) |

---

## Conseils et tips 🦮

### Construire l'algorithme

Vous pouvez utiliser **n'importe quelle bibliothèque** (`sklearn`, `tensorflow`), des [APIs ML](https://www.programmableweb.com/category/machine-learning/api) ou des outils no-code.

Si vous ne souhaitez pas construire l'algorithme vous-même, **AmazonML** est une bonne option ([cours dédié disponible](https://app.jedha.co/track/aws-machine-learning-stack-track)).

> **Important :** pensez à construire quelque chose de **réutilisable** ! Le preprocessing doit être intégré au pipeline — pas seulement un `.predict()`.

### Priorité : le Data Pipeline avant le ML

> **La partie la plus importante est le Pipeline de Données — PAS l'algorithme ML.**  
> L'algorithme ML est secondaire. Concentrez-vous d'abord sur le pipeline.

### Par où commencer ?

Les éléments minimaux à mettre en place :

1. **Entraîner un algorithme**
2. **Le déployer en production**
3. **Stocker les données en temps réel dans une base de données**

Architecture suggérée (point de départ) :

![basic_infrastructure](https://lead-program-assets.s3.eu-west-3.amazonaws.com/Data_infrastructure_example_for_fraud_detection.png)

> Cette architecture n'est qu'une **suggestion** — vous pouvez vous en écarter.  
> Les éléments **minimaux obligatoires** sont :
> - Un élément collectant et stockant les données
> - Un élément consommant les données
> - Un processus ETL (ou ELT)

### Répartition du travail en équipe

Suggestion de découpage :

| Membre | Tâche |
|--------|-------|
| Membre 1 | Entraînement de l'algorithme |
| Membre 2 | Infrastructure MLflow |
| Membre 3 | Pipeline d'ingestion de données en temps réel |
