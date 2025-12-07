# Playwright E2E Testing Plan
## Component: Frontend E2E Tests (Playwright)

**Follow design_spec.md**: Implement comprehensive E2E tests covering all major user flows for the orchestrator dashboard MVP using Playwright. Tests must pass in CI (GitHub Actions assumed). No new features - test existing functionality.

**Acceptance Criteria**:
1. Playwright installed and configured in `orchestrator-dashboard`
2. Tests cover: view runs list, create run, view run details + graph, pause/resume, human queue resolution
3. Tests pass locally (`npx playwright test`) and in headless mode
4. GitHub Actions workflow runs tests on PRs
5. Test reports with screenshots/videos on failure
6. Coverage of happy paths + error states (404, network failure)

## Task Breakdown (7 atomic commits)

