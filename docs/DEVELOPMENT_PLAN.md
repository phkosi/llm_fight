# Development Plan

This document summarizes outstanding tasks for ongoing development and tracks completed milestones.

## Outstanding Tasks

- **Scalability**: Explore optimizations for very large numbers of simulations, such as improved state handling or batch execution.

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
