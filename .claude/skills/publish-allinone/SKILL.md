---
name: publish-allinone
description: Publish the latest skating-analyzer source to GitHub, export the latest source as a Docker all-in-one image tar, and deploy that image locally. Use when asked to update GitHub, export an all-in-one image, local deploy, release/deploy the newest source, or repeat this repo's publish-and-deploy workflow.
---

# Publish All-in-one

Use this skill in the `skating-analyzer` repository to publish the current source, produce a Docker all-in-one image archive, and run it locally.

## Guardrails

- Treat `.env`, `data/`, `backups/`, `models/`, `dist/`, `*.tar`, and `.claude/worktrees/` as local artifacts. Do not commit secrets, runtime databases, uploaded videos, model weights, or exported image tar files.
- Commit `.claude/skills/**` when the task changes this skill. Do not commit `.claude/settings.local.json` or worktrees.
- If the worktree contains unrelated user edits, do not revert them. Include the latest intended source changes unless the user explicitly narrows the scope.
- Prefer PowerShell on Windows. Run commands from the repository root unless a step specifies another directory.

## Standard Workflow

1. Inspect the repository state:

```powershell
git status --short --branch
git remote -v
```

2. Validate the source before publishing:

```powershell
Push-Location backend
pytest tests
Pop-Location

Push-Location frontend
npm run build
Pop-Location
```

3. Review what will be committed:

```powershell
git status --short
git diff --stat
git diff -- .gitignore .claude/skills scripts docker backend frontend ai_skating_analysis_pack README.md README.zh.md
```

4. Stage and commit the latest source changes:

```powershell
git add -A
git status --short
git commit -m "Update skating analyzer all-in-one release"
```

If Git reports there is nothing to commit, continue to the export and deploy steps.

5. Push the current branch to GitHub:

```powershell
git push origin HEAD
```

6. Build and export the all-in-one image tar:

```powershell
.\scripts\export-allinone-image.ps1 -ImageName skating-analyzer-allinone -ImageTag latest -OutputDir .\dist
```

Expected output artifact:

```text
dist\skating-analyzer-allinone-latest.tar
```

7. Deploy the freshly built local image:

```powershell
docker rm -f skating-allinone 2>$null
docker run -d `
  --name skating-allinone `
  -p 8080:80 `
  -v "${PWD}\data:/data" `
  -v "${PWD}\backups:/backups" `
  -v "${PWD}\models:/models:ro" `
  -v "${PWD}\.env:/workspace/.env:ro" `
  skating-analyzer-allinone:latest
```

If `.env` does not exist, omit the `.env` mount and pass required environment variables through the deployment environment instead.

8. Verify the local deployment:

```powershell
docker ps --filter "name=skating-allinone"
curl.exe -f http://localhost:8080/api/health
```

Open the app at `http://localhost:8080`.

## Failure Handling

- If tests fail, stop before commit/push unless the user explicitly asks to publish despite failures.
- If `docker build` fails, inspect the Dockerfile stage shown in the error and fix source/build issues before retrying.
- If port `8080` is occupied, either stop the old `skating-allinone` container or run with another host port such as `-p 8081:80`; report the actual URL.
- If `.env` is missing, the container can still start, but AI provider calls may fail until credentials are configured.

## Final Report

Report:

- Branch and pushed commit hash, or state that there was nothing new to commit.
- Test results for backend and frontend.
- Docker image name and exported tar path.
- Container name, health-check result, and local URL.
