# FIM Baseline Version Control Repository

This repository stores immutable snapshots of all approved baselines.
Each commit represents a baseline approval event.

## Structure
```
<agent-hostname>/
    <YYYY-MM-DD_HHMMSS>_<baseline-id>.json   ← baseline snapshot
```

## Security
- Never manually delete or rewrite history
- Each snapshot is SHA-256 verified
- Git commit hash stored in fim.baselines.git_hash column
