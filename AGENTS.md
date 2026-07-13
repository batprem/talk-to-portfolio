# Agent Instructions

## Delegation Policy

The main agent must delegate implementation tasks to the appropriate specialist agent whenever the task clearly belongs to a specific area of the codebase.

- Delegate backend tasks to the backend agent. This includes API design, server-side business logic, database access, data processing, authentication, integrations, tests for backend behavior, and changes under `backend/`.
- Delegate frontend tasks to the frontend agent. This includes UI components, client-side state, styling, routing, browser behavior, accessibility, frontend tests, and changes under `frontend/`.
- For tasks that touch both `backend/` and `frontend/`, the main agent must coordinate both specialist agents and ensure the contract between the two sides is explicit.

## Main Agent Responsibilities

The main agent owns coordination, final integration, and verification. It should:

- Clarify scope before delegation when the request is ambiguous.
- Give each specialist agent a concise task with relevant files, expected behavior, and verification requirements.
- Review specialist outputs before applying or accepting changes.
- Ensure backend and frontend changes remain compatible.
- Run or request the appropriate tests before considering the work complete.

## Repository Structure

- `backend/`: server-side application code and backend tests.
- `frontend/`: client-side application code and frontend tests.
- `datasets/`: local data files used by the project.
