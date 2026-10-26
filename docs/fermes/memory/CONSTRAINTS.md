# Constraints
project_id: fermes-hermes

| ID | Constraint | Source |
|---|---|---|
| C-001 | Do not conflate this fork with Project Coordinator, Ideas/Hindsight or other Hermes installations | Owner |
| C-002 | Upstream source updates are reviewed, not automatically merged into qualified branch | Owner and fork maintenance |
| C-003 | Do not modify production Hermes runtime as a side effect of source work | Workstream controls |
| C-004 | Tests distinguish static, unit, integration and live Qwen acceptance; do not claim E2E PASS from direct LM Studio only | Owner reliability goals |
| C-005 | No tool runner may silently hang on inherited stdin; bounded termination and safety required | Prior failure evidence |
| C-006 | Independent review and durable evidence before merge or declaring a component qualified | Owner requirements |
| C-007 | The final self-learning architecture is Hermes-owned and local-first, with recoverable memory/compaction and demonstrable non-regression | Owner |
| C-008 | Secrets, personal API keys, access tokens and model-server auth never go in GitHub Issues, logs or source files | Security |
