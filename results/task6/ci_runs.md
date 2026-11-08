# CI runs (`.github/workflows/ci.yml`) — evidence copied from the GitHub Actions logs

| Run | Model evaluated | 1 lint + gitleaks | 2 unit tests | 3 evaluation (Release asset) | 4 quality gate | Link |
|---|---|---|---|---|---|---|
| #7 | `model-v1` | success | success (20 tests) | success: json_validity 100.0, full_frame 50.0 | **success** | https://github.com/rajnikhil259/cloud-computing-assignment/actions/runs/42475512196 |
| #6 | `model-base` (untrained Pythia-70M) | success | success | success: json_validity 0.0 | **FAILED** (as intended) | https://github.com/rajnikhil259/cloud-computing-assignment/actions/runs/42475510183 |

Run #5 (push, 09:40 UTC) failed in stage 1 only because downloading the gitleaks binary from GitHub returned
HTTP 504 seven times; the step now falls back to the official gitleaks container image.
