# Development Plan

This document summarizes outstanding tasks for ongoing development and tracks completed milestones.

## Outstanding Tasks

- **LLM Interaction Robustness**: Continue refining prompts, response parsing, and error handling to better cope with unexpected LLM outputs.
- **Scalability**: Explore optimizations for very large numbers of simulations, such as improved state handling or batch execution.
- **Test Suite Enhancements**:
  1. **Property-based tests for `FighterState.apply_delta`**
     - Use `hypothesis` strategies to generate random combinations of deltas for
       pain, exhaustion and heat adjustments.
     - Randomly construct wound payloads that target existing and non-existent
       body parts and ensure invariants (e.g. HP never increases).
     - Generate effect addition/removal data and verify that permanent effects
       are not duplicated and TTL logic is respected.
  3. **Negative CLI option tests**
     - Invoke the CLI entry point with invalid options using `CliRunner`.
     - Check that invalid model names or configuration paths produce helpful
       error messages and non-zero exit codes.
     - Cover mutually exclusive options and missing required parameters.

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
- Simulated failure scenarios for `_single_fight` and `run_batch` now tested
