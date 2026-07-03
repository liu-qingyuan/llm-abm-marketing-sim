```markdown
# llm-abm-marketing-sim Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill introduces the development patterns and conventions used in the `llm-abm-marketing-sim` Python repository. The project focuses on agent-based marketing simulations, emphasizing clear code organization, consistent naming, and maintainable test practices. You will learn how to structure Python code, follow commit and file naming conventions, and manage tests in this codebase.

## Coding Conventions

### File Naming
- Use **kebab-case** for all file names.
  - Example:  
    ```
    agent-manager.py
    simulation-runner.py
    ```

### Import Style
- Use **relative imports** within the package.
  - Example:
    ```python
    from .utils import calculate_metrics
    from .models import Agent
    ```

### Export Style
- Use **named exports** (i.e., define functions/classes explicitly for import).
  - Example:
    ```python
    def run_simulation():
        pass

    class MarketingAgent:
        pass
    ```

### Commit Messages
- Use **conventional commit** style.
- Prefix test-related commits with `test`.
- Keep commit messages concise (average ~43 characters).
  - Example:
    ```
    test: add coverage for agent interactions
    ```

## Workflows

### Running the Simulation
**Trigger:** When you want to execute the core simulation logic.
**Command:** `/run-simulation`

1. Ensure all dependencies are installed.
2. Navigate to the main simulation file (e.g., `simulation-runner.py`).
3. Run the script using Python:
    ```bash
    python simulation-runner.py
    ```

### Adding a New Agent Type
**Trigger:** When introducing a new agent behavior or type.
**Command:** `/add-agent-type`

1. Create a new Python file using kebab-case (e.g., `influencer-agent.py`).
2. Define your agent class with named exports.
    ```python
    class InfluencerAgent:
        pass
    ```
3. Use relative imports to integrate with existing modules.
4. Update the simulation runner to include the new agent.

### Writing Tests
**Trigger:** When adding or updating features.
**Command:** `/write-test`

1. Create a test file matching the pattern `*.test.*` (e.g., `agent-manager.test.py`).
2. Write test functions for each feature or bug fix.
    ```python
    def test_agent_creation():
        # test logic here
        pass
    ```
3. Run tests using your preferred Python test runner.

## Testing Patterns

- Test files follow the `*.test.*` naming pattern (e.g., `simulation-runner.test.py`).
- The testing framework is not specified; use standard Python testing tools (e.g., `unittest`, `pytest`).
- Place tests alongside or near the modules they cover.
- Use clear, descriptive function names for tests.
- Example test file:
    ```python
    def test_simulation_runs():
        # Arrange
        # Act
        # Assert
        pass
    ```

## Commands
| Command            | Purpose                                      |
|--------------------|----------------------------------------------|
| /run-simulation    | Run the main simulation logic                |
| /add-agent-type    | Add a new agent type to the simulation       |
| /write-test        | Create and run a new test for a module       |
```
