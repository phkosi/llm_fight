# Development Plan

This document summarizes outstanding tasks for ongoing development and tracks completed milestones.

## Outstanding Tasks

- **Fix CLI Execution Failure**: Investigate why `run.py` invoking `src.cli.app` fails to launch Typer commands.
  - Examine interactions between `typer`, `sys.argv`, and the import structure.
  - Consider simplifying the entry point or using an alternative CLI runner if required.
- **Configuration Testing**: Ensure `test_config_loading_correct_values` in `tests` works consistently. Defaults from `configparser` should override properly in the test environment.
- **Advanced Combat Log**: Create structured log objects that support querying and summarization of long fights.
- **Dynamic Loadouts, Classes, and Environments**: Allow fighters and environments to be defined via configuration files so matches can vary.
- **LLM Interaction Robustness**: Continue refining prompts, response parsing, and error handling to better cope with unexpected LLM outputs.
- **Scalability**: Explore optimizations for very large numbers of simulations, such as improved state handling or batch execution.

## Completed Milestones

- Core State Updates Implemented
- Prompts & Context Enhanced
- BodyPart Mechanics Implemented
- Effect System Refined
- Code Refactored and Cleaned Up
- Comprehensive Testing Suite Established (Unit, Integration, End-to-End)
