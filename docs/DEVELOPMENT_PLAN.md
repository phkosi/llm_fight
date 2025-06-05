# Development Plan

This document summarizes outstanding tasks for ongoing development and tracks completed milestones.

## Outstanding Tasks

- **LLM Interaction Robustness**: Continue refining prompts, response parsing, and error handling to better cope with unexpected LLM outputs.
- **Scalability**: Explore optimizations for very large numbers of simulations, such as improved state handling or batch execution.
- **Test Suite Enhancements**:
  - Property-based tests for `FighterState.apply_delta` to cover a wider range of deltas.
  - Simulated failure scenarios for `_single_fight` and `run_batch` to verify graceful error handling.
  - Negative CLI option tests to check validation and error messages.

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
