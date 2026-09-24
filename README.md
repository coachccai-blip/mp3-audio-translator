# Doublr — doublage audio par IA, voix natives, durée identique

Doublr prend un fichier audio (ou vidéo) dans une langue et produit la même piste dans une autre langue :

- **durée totale identique** (±50 ms) et chaque phrase doublée démarre à l'horodatage exact de l'original ;
- **voix de locuteurs natifs uniquement** : pas de clonage, pas de voix « multilingue » à accent ;
- **fond sonore conservé** (musique, ambiance), avec ducking automatique sous la voix ;
- parcours simple : **importer → choisir la langue → exporter**. Les réglages experts restent dans « Avancé ».

Langues : français, anglais, chinois (mandarin), allemand, suédois, espagnol, italien, polonais, avec leurs variantes régionales (fr-CA, en-GB, es-MX, de-AT…).

---

## Gratuit, sans aucune clé

Par défaut, tout tourne sur votre ordinateur, gratuitement et sans limite :

| Étape | Moteur gratuit (local) | Option premium (clé) |
|---|---|---|
| Séparation voix/fond, transcription | Demucs, Whisper large-v3 | — |
| Traduction isochrone | modèle open source via **Ollama** (`gemma3:4b` par défaut, `gemma3:12b` si carte graphique) | Claude (`ANTHROPIC_API_KEY`) |
| Voix natives | **Kokoro** (HD 24 kHz) et **Piper** | Azure Neural TTS (400+ voix, gratuit jusqu'à 500 000 caractères/mois) |

Voix gratuites disponibles : anglais US (30), anglais UK (12), chinois (9), français (4), espagnol d'Espagne (3), du Mexique (2), d'Argentine (1), italien (3), allemand (3), polonais (2), suédois (2). Les variantes sans voix native gratuite (fr-CA, fr-BE, fr-CH, en-AU, en-IE, de-AT, de-CH, zh-TW) sont masquées en mode gratuit, jamais doublées avec un accent étranger ; elles apparaissent si vous ajoutez une clé Azure.
Qualité : les voix gratuites sont moins expressives que les voix Azure, et la traduction locale moins fine que Claude, surtout sur les langues moins courantes. À écouter avant de publier.

## Deux façons de l'utiliser

| | Serveur local (vrai doublage) | GitHub Pages (démo) |
|---|---|---|
| URL | `http://localhost:5173` ou la page GitHub Pages connectée à votre serveur | `https://coachccai-blip.github.io/mp3-audio-translator/` |
| Analyse des fichiers | ✅ | ✅ (dans le navigateur) |
| Transcription, traduction, voix, export | ✅ | ❌ simulés |

GitHub Pages n'héberge que des pages statiques : il ne peut pas faire tourner Whisper, Demucs ni appeler les API avec vos clés. La page publiée sert donc :

1. de **démo interactive** du parcours (bandeau « Mode démo ») ;
2. d'**interface** pour votre serveur local (Chrome, Edge, Firefox ; Safari peut bloquer l'accès d'une page HTTPS à `localhost` — utilisez alors `http://localhost:5173`) : si `doublr` tourne sur votre machine (`http://localhost:8000`), la page GitHub Pages s'y connecte automatiquement (sinon : Réglages → Serveur local). Vos fichiers et vos clés restent sur votre machine.

---

## Installation sur Windows (recommandé : en un double-clic)

1. Téléchargez **[Installer-Doublr.bat](https://coachccai-blip.github.io/mp3-audio-translator/Installer-Doublr.bat)** (bouton « Installer sur Windows » sur le site).
2. Double-cliquez dessus. Si Windows affiche « Windows a protégé votre ordinateur », cliquez sur **Informations complémentaires → Exécuter quand même**.
3. Laissez faire (20 à 60 min, ~12 Go) : Python, Node.js, PyTorch, Whisper large-v3, Demucs, pyannote, les voix Kokoro et Piper, Ollama et son modèle de traduction sont installés dans `%LOCALAPPDATA%\Doublr`, **sans droits administrateur**. Une carte NVIDIA est détectée et utilisée automatiquement.
4. Les clés API sont **facultatives** : appuyez sur Entrée pour les passer (Doublr fonctionne alors gratuitement).
5. Double-cliquez sur le raccourci **Doublr** du Bureau : le serveur démarre et Doublr s'ouvre dans votre navigateur (`http://localhost:8000`). Laissez la fenêtre noire ouverte pendant l'utilisation.

Les fichiers doublés vont dans `Documents\Doublr`. Pour mettre à jour : menu Démarrer → **Mettre à jour Doublr** (vos clés et projets sont conservés).

## Installation manuelle (macOS, Linux, Windows)

Prérequis : Python 3.11+, Node 20+, FFmpeg et Rubber Band (time-stretching haute qualité).

```bash
# macOS
brew install ffmpeg rubberband
# Ubuntu / Debian
sudo apt install ffmpeg rubberband-cli libsndfile1
# Windows : winget install ffmpeg  (Rubber Band : https://breakfastquay.com/rubberband/)
```

```bash
git clone https://github.com/coachccai-blip/mp3-audio-translator.git
cd mp3-audio-translator
cp .env.example .env            # puis renseignez vos clés (voir plus bas)

# Backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -e ".[ai,dev]"      # [ai] = Whisper, Demucs, pyannote, pyrubberband (PyTorch, ~3 Go)
uvicorn app.main:app --port 8000

# Frontend (autre terminal)
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

Sans l'extra `[ai]`, l'application démarre mais refuse de transcrire (message explicite). Sans Rubber Band, un time-stretch WSOLA intégré (pitch conservé) prend le relais, de qualité un peu inférieure.

### Ligne de commande

```bash
cd backend
python -m app.cli dub ../samples/mon_episode.mp3 --to de-DE --to es-ES --out ../exports
```

## Configuration des clés

Dans `.env` (ou depuis l'écran **Réglages**, qui écrit dans ce même fichier et ne renvoie jamais les clés au navigateur) :

| Variable | Rôle | Obligatoire |
|---|---|---|
| `ANTHROPIC_API_KEY` | Traduction isochrone (Claude, modèle `DOUBLR_CLAUDE_MODEL`, par défaut `claude-opus-5`) | oui |
| `AZURE_SPEECH_KEY` + `AZURE_SPEECH_REGION` | Synthèse vocale Azure Neural TTS | oui (fournisseur par défaut) |
| `ELEVENLABS_API_KEY` | Second fournisseur TTS | non |
| `HF_TOKEN` | Diarisation pyannote (plusieurs locuteurs). Acceptez les conditions de `pyannote/speaker-diarization-3.1` sur Hugging Face | non (sinon 1 seul locuteur) |

Chaque clé a un bouton **Tester** dans Réglages.

**Confidentialité** : séparation, transcription et assemblage tournent sur votre machine. Seuls les textes à traduire (Claude) et à synthétiser (TTS) partent vers ces API. Aucune télémétrie.

## Ajouter une voix au catalogue

Le catalogue `config/voices.yaml` ne contient **que des voix natives** (une voix contenant « Multilingual » est rejetée au chargement).

1. Ajoutez une entrée sous la locale :
   ```yaml
   fr-CA:
     - id: azure:fr-CA-AntoineNeural
       provider: azure
       display_name: Antoine
       gender: male
       age_range: adult
       styles: [neutral]
       sample: samples/voices/fr-CA-antoine.mp3
       validated_by: null
       validated_on: null
   ```
2. Vérifiez l'identifiant auprès d'Azure : `python scripts/sync_azure_voices.py` (existence, locale, voix non multilingue).
3. Générez un échantillon : `python scripts/audition.py --locale fr-CA`, faites-le écouter par un locuteur natif.
4. Si la voix est validée, renseignez `validated_by` et `validated_on`.
5. En production, mettez `DOUBLR_REQUIRE_VALIDATED_VOICES=true` : seules les voix validées sont proposées, et une variante sans voix validée est **masquée** (l'API renvoie 422 « Aucune voix native validée pour … »).

Recalibrez ensuite les débits de parole sur le TTS réel : `python scripts/calibrate_rate.py --write`.

## Publier sur GitHub Pages

Le workflow `.github/workflows/pages.yml` lance les tests backend, construit le frontend puis le publie, **à chaque push sur `main`**.

1. Fusionnez la branche de développement dans `main` (via une pull request).
2. Sur GitHub : **Settings → Pages → Build and deployment → Source : GitHub Actions** (à faire une seule fois).
3. Le workflow publie `https://coachccai-blip.github.io/mp3-audio-translator/`.

Si vous forkez le dépôt, ajoutez l'URL de votre page à `DOUBLR_CORS_ORIGINS` dans le `.env` de votre serveur local.

## Tests

```bash
cd backend && pytest -q
```

Les tests d'acceptation (`tests/test_acceptance.py`) couvrent le §13.1 du brief sur les 3 fichiers générés par `scripts/make_samples.py` (MP3 stéréo 44,1 kHz, WAV mono 48 kHz, FLAC stéréo) :
durée ±50 ms, départ des segments ±20 ms, aucun stretch > 12 % sans statut « à vérifier », refus d'une locale sans voix native, un seul appel TTS après édition d'un segment, régénération limitée aux segments du locuteur dont la voix change, format / fréquence / canaux identiques, lot multi-fichiers × multi-langues exporté en une action.
Ils utilisent des moteurs factices (pas de modèles ni d'appels réseau).

## Architecture

```
backend/app/
  main.py              FastAPI + WebSocket de progression
  api/                 routes REST (projets, locuteurs, segments, voix, réglages, export)
  pipeline/            analyze → separate (Demucs) → transcribe (faster-whisper) → diarize (pyannote)
                       → translate (Claude, isochrone) → tts/ (Azure, ElevenLabs) → fit (boucle de durée)
                       → assemble (placement, fondus 10 ms, ducking −6 dB, loudness EBU R128) → report
  services/            catalogue de voix, coûts, jobs, export
  models/              SQLite via SQLModel
frontend/src/          React 18 + Vite + TypeScript + Tailwind, interface en 8 langues, thème clair/sombre
config/                voices.yaml, languages.yaml
scripts/               audition.py, calibrate_rate.py, sync_azure_voices.py, make_samples.py
```

Le cache (`data/projects/<id>/…`) est indexé par hash des entrées : modifier un segment ne resynthétise que ce segment puis réassemble ; changer la voix d'un locuteur ne régénère que ses segments.

## Limites connues / à confirmer

- **Identifiants de voix Azure « à confirmer »** : la documentation Microsoft n'était pas accessible pendant le développement. Les voix du catalogue sont des voix neuronales Azure connues, marquées `status: to_confirm`. Lancez `scripts/sync_azure_voices.py` avec votre clé avant la production.
- **Contrôle de durée cible natif du TTS** : non utilisé (à vérifier dans la doc Azure / ElevenLabs actuelle). La durée est tenue par la boucle retraduction + time-stretch ≤ 12 %.
- **ElevenLabs** : filtrage des voix par langue + accent de la Voice Library ; les valeurs d'accent (`NATIVE_ACCENTS`) et l'endpoint `shared-voices` sont à confirmer.
- **Genre / âge du locuteur** : estimation grossière par la hauteur de voix, uniquement pour pré-sélectionner une voix.
- **Tarifs** : l'estimation de coût utilise des tarifs publics indicatifs (`services/cost.py`), à ajuster.
- **Rapport PDF** : généré si `reportlab` est installé (`pip install reportlab`), sinon JSON uniquement.
- **Mode démo** (GitHub Pages sans serveur) : traduction et voix simulées ; l'export est désactivé.
- Pas encore de packaging desktop (Tauri) ni d'API REST documentée pour intégration (V2 du brief).
