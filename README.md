# skills-ref

Reference implementation for Agent Skills v1.1 — validates skills, checks dependencies, and runs tests.

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Validate a skill

```bash
# Check if skill is valid (dependencies present, versions OK)
python skills_ref.py validate ./my-skill --skills-root ./skills

# Force validation even with missing deps (for development)
python skills_ref.py validate ./my-skill --skills-root ./skills --force
```

### Initialize a new skill

```bash
# Creates SKILL.md template with auto-populated requires
python skills_ref.py init ./my-new-skill --skills-root ./skills
```

### Run tests

```bash
python skills_ref.py test ./my-skill --skills-root ./skills
```

### Check dependencies

```bash
# List all skills
python skills_ref.py deps --skills-root ./skills

# Show dependency graph
python skills_ref.py deps --skills-root ./skills --graph

# Check for circular dependencies
python skills_ref.py deps --skills-root ./skills --check-circular
```

## Test Cases Format

Test cases are defined in YAML:

```yaml
cases:
  - name: test_name
    description: What this test verifies
    input: "The prompt to send to the agent"
    assertions:
      output_contains:
        - "expected text"
      output_not_contains:
        - "error"
      output_matches:
        - "regex pattern"
      semantic_match:
        criterion: "Clear criterion for LLM judge"
```

## Extending with Agent Runner

To actually run tests against an agent, pass an `agent_runner` function to `run_tests()`:

```python
from skills_ref import run_tests

def my_agent_runner(skill_path, input_prompt):
    # Call your agent here
    # Return the output as a string
    return agent.run(skill_path, input_prompt)

passed, total = run_tests(skill_path, skills_root, agent_runner=my_agent_runner)
```

## License

MIT
