# Session Preflight Check

Execute a complete session preflight to understand the current project state before starting work.

## Steps

1. **Get bearings**
   - Run `pwd` to confirm working directory
   - Run `git status` to see current branch and changes
   - Run `git log --oneline -10` to see recent commits

2. **Read handoff artifacts**
   - Check the OS temp directory for a recent handoff doc from the `handoff` skill

3. **Check service status**
   - Check if Docker containers are running with `docker compose ps`
   - Check if backend is responding on port 8000
   - Check if frontend is responding on port 3000

4. **Run baseline verification**
   - If baseline services are down, report the issue
   - If tests fail, fix baseline first before new work

## Output Format

Provide a concise summary (10-15 lines max) with:
- Current branch and uncommitted changes
- Last session's progress (if available)
- Next suggested feature to work on
- Service status (backend/frontend/database)
- Any blockers or issues to address first

## Constraints

- Do NOT start implementing features during preflight
- Do NOT run long-running tests (only quick smoke checks)
- Keep output short and actionable
- Report issues clearly so they can be fixed before starting work
