# V2 Isolated Local Runtime

Baseline: `c291324c62bcc930f96f3429dcdc9521e060b516`

Branch: `codex/skating-analyzer-v2`

Worktree: `<repo>`

Runtime root: `<runtime-dir>`

The main worktree and its `data`, database, backups, outputs, and uncommitted files are not used.

## Start legacy mode

Do not load `.env.v2.local`. With no `SKATING_ANALYSIS_PIPELINE`, startup defaults to `legacy` and preserves the existing application behavior.

## Start isolated Shadow foundation

From the V2 worktree, load the untracked local environment and start the backend:

```powershell
Get-Content .env.v2.local | ForEach-Object {
  if ($_ -match '^([^#=]+)=(.*)$') { Set-Item -Path "Env:$($matches[1])" -Value $matches[2] }
}
Set-Location backend
python -m uvicorn app.main:app --reload
```

Iteration 0 Shadow is intentionally a no-op. It reports readiness in the parent-authorized advanced card but does not compute V2 results or write family data.

Start the frontend in a second terminal with `npm run dev`. `/home`, `/review`, `/growth`, and `/me` remain the four primary spaces. Shadow status is available only at `/me/advanced?tool=shadow` after parent PIN verification.

## Safety checks

- `SKATING_ANALYSIS_PIPELINE=shadow|v2` requires `V2_RUNTIME_ROOT`.
- All declared writable paths and the SQLite file must resolve beneath that root or startup fails.
- Public capabilities disclose mode, public authority, and supported schema versions only. Local paths and provider secrets are excluded.
- `.env.v2.local`, databases, videos, Golden labels, caches, and model outputs are ignored and must not be committed.
