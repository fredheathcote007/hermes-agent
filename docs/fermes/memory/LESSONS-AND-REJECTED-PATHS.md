# Lessons and Rejected Paths
project_id: fermes-hermes

- Do not blindly cherry-pick the entire third draft commit `7dbfcf5a7d` onto v0.22.5: `agent/auxiliary_lmstudio.py` is removed. Port essential behaviour into current interfaces, test, review.
- Do not run Codex with inherited open stdin: observed `Reading additional input from stdin...`; invoke with `</dev/null` and deadlines.
- Do not treat a direct successful LM Studio tool call as an end-to-end Hermes execution pass.
- Do not treat an outdated test suite's missing imported module as proof of runtime regression; adapt tests without silently losing covered behaviours.
- Do not install all external memory/learning components merely to avoid investigating source reuse. Selectively harvest under licence/security/quality review.
- Avoid duplicating GitHub Issues as an independently edited backlog in Google Drive.
