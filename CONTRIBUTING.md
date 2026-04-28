# Contributing to Skating Analyzer

Thanks for your interest in contributing.

This project combines frontend product work, backend APIs, video processing, pose estimation, AI provider integration, and deployment workflows. Clear changes and reproducible steps make contributions much easier to review.

## Before You Start

- Read [README.md](./README.md) for setup and project structure
- Use `.env.example` as the only shared config template
- Do not commit `.env`, runtime data, databases, exported image archives, or user video assets

## Development Setup

### Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Docker

```bash
docker compose up --build
```

## What to Include in a Good Contribution

- A clear problem statement
- What changed and why
- Any UI, API, or data migration impact
- Verification steps
- Screenshots or screen recordings for visible UI changes

## Pull Request Guidelines

- Keep changes focused
- Prefer small, reviewable PRs over broad mixed changes
- Update docs when behavior changes
- Include any new environment variables in `.env.example`
- Mention if the change affects Docker, nginx, media processing, or AI provider configuration

## Coding Notes

- Frontend is React + TypeScript + Vite
- Backend is FastAPI + SQLAlchemy Async
- Runtime data should stay under `./data`
- Public repo content must remain sanitized

## Suggested PR Template

```text
## Summary
- What changed

## Why
- Why this change is needed

## Verification
- Commands run
- Pages tested

## Screenshots
- Before / after if relevant
```

## Security and Privacy

- Never commit real API keys
- Never commit local databases or uploaded videos
- Avoid including sensitive screenshots containing credentials or private user data

## Questions

If a change is large, architectural, or affects product direction, open an issue or draft PR first so discussion can happen earlier.
