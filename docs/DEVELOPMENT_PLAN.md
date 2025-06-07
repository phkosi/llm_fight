# Development Plan

This document summarizes outstanding tasks for ongoing development and tracks completed milestones.

## Outstanding Tasks

- **Scalability**: Explore optimizations for very large numbers of simulations, such as improved state handling or batch execution.

- **Ollama API refactor**: migrate from `/v1/chat/completions` to the modern `/api` endpoints.
  - Research shows `/api/generate` accepts a `prompt` plus optional parameters such as
    `format`, `options`, `system`, `template`, `stream`, `raw`, `keep_alive` and
    `context`. When `stream` is `false` the JSON reply contains the complete text in a
    `response` field.
  - **Adjust tests first (TDD)**:
    - Update endpoint expectations in `tests/test_agents.py` and any other tests
      referencing `/v1/chat/completions`.
    - Add new tests for `_post_json` to handle `data["message"]["content"]` and
      `data["response"]` while remaining compatible with the legacy `choices`
      structure.
  - Update the default `ollama_api_url` in `src/config.py` and
    `llmfight.ini.example` to `http://localhost:11434/api/chat`.
  - Revise `get_ollama_url()` so a bare host will be normalised with `/api/chat`
    and allow `/api/generate` when specified.
  - Adjust `ping_ollama()` to compute the base with `.split('/api')[0]` and check
    `'/api/tags'`.
  - Extend `_post_json()` to read from the new response shapes and fall back to
    legacy `choices` if neither exists. Always send `{"stream": false}` in the
    payload.
  - Update README examples and configuration instructions for the new endpoint.

## Completed Milestones

- Core State Updates Implemented
- Prompts & Context Enhanced
- BodyPart Mechanics Implemented
- Effect System Refined
- Code Refactored and Cleaned Up
- Comprehensive Testing Suite Established (Unit, Integration, End-to-End)
- CLI Entry Point Fixed
- Configuration Loading Tests Passing
- Async Batch Concurrency Introduced
- Structured Combat Log Implemented
- Dynamic Loadouts, Classes, and Environments
- Initial improvements for LLM Interaction Robustness: Judge Phase1 now receives recent combat log context
- Robust parsing retries with exponential backoff for malformed LLM responses
- Simulated failure scenarios for `_single_fight` and `run_batch` now tested
- Property-based tests for `FighterState.apply_delta`
  - Use `hypothesis` strategies to generate random combinations of deltas for
    pain, exhaustion and heat adjustments.
  - Randomly construct wound payloads that target existing and non-existent
    body parts and ensure invariants (e.g. HP never increases).
  - Generate effect addition/removal data and verify that permanent effects
    are not duplicated and TTL logic is respected.
- Negative CLI option tests
- CLI Visualization Improvements completed: rich tables, progress bar and verbose output with tests
- Test Suite Enhancements completed: additional edge case tests for config save, invalid probabilities, and guarded_call
  - Invoke the CLI entry point with invalid options using `CliRunner`.
  - Check that invalid model names or configuration paths produce helpful
    error messages and non-zero exit codes.
  - Cover mutually exclusive options and missing required parameters.
