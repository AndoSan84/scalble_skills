# RFC: Skill Dependencies and Testing Specification

**Author:** Andrea Gasparro  
**Status:** Draft  
**Created:** January 2026  
**Target:** Agent Skills Specification v1.1

---

## Summary

This RFC proposes two additions to the Agent Skills specification:

1. **`requires`** - A field to declare dependencies between skills
2. **`test`** - A field to declare test cases for skill validation

These additions enable enterprise-scale skill management while maintaining full backward compatibility with the current specification.

---

## Motivation

### The problem

Agent Skills are becoming the "programs" of the agentic era. As organizations adopt skills at scale, they face challenges that the current specification doesn't address:

1. **Skills depend on other skills** - A "deploy-to-production" skill may assume an "environment-selector" skill exists. Today there's no way to declare this dependency.

2. **Skills break silently** - When skill A depends on skill B, modifying B can break A without any warning. Unlike traditional software with compile-time checks, skills are resolved at inference time by the agent.

3. **No standard way to test skills** - Each organization invents its own testing approach, leading to fragmentation and non-portable solutions.

### Why this matters now

The Agent Skills standard has achieved remarkable adoption in just one month: Claude Code, Gemini CLI, Cursor, VS Code, GitHub, and OpenAI Codex all support it. This success means organizations are now deploying skills at scale, and the limitations are becoming apparent.

Without standardized dependencies and testing:
- Teams build proprietary solutions that don't interoperate
- Skills become fragile as they grow in number
- Enterprise adoption is hindered by lack of governance tools

### The opportunity

By adding minimal, optional fields for dependencies and testing, we can:
- Enable enterprise-scale skill management
- Allow tooling to validate skill compatibility
- Create an ecosystem of testable, composable skills
- Do all this without breaking existing skills

---

## Specification

### 1. The `requires` field

A new optional frontmatter field declaring dependencies on other skills.

#### Schema

```yaml
requires:
  - skill: <skill-name>         # Required. Name of the required skill.
    version: <version>          # Optional. Minimum version required.
```

Skills are identified by their `name` field (as defined in the current spec). The tool searches for dependencies in the same skills root directory.

#### Version validation

When `version` is specified, it represents the **minimum required version** (the version the skill was developed/tested with).

**Validation rules:**

| Present version | Required version | Result |
|-----------------|------------------|--------|
| 1.5.0 | 1.2.0 | ✓ OK (1.5.0 >= 1.2.0) |
| 1.0.0 | 1.2.0 | ✗ ERROR (1.0.0 < 1.2.0) |
| (not found) | any | ✗ ERROR (can be ignored with flag) |
| 1.5.0 | (omitted) | ✓ OK (any version accepted) |

#### Example

```yaml
---
name: integration-test-runner
description: Runs integration tests on specified environment.

metadata:
  version: "2.1.0"

requires:
  - skill: environment-selector
    version: "1.2.0"
  - skill: logging-standards
---
```

#### Snapshot on creation

When creating a skill, tooling SHOULD auto-populate `requires` based on skills present in the environment:

```bash
skills-ref init my-new-skill

# Tooling detects environment-selector@1.2.0 is present
# Auto-generates:
requires:
  - skill: environment-selector
    version: "1.2.0"
```

The developer can then adjust as needed.

#### Agent behavior

**Agents require no changes.** The `requires` field is consumed by tooling, not by agents.

From the agent's perspective, nothing changes: it discovers skills, reads `SKILL.md` files, and activates them as needed. The agent is unaware of dependency resolution — it simply sees a set of validated, ready-to-use skills.

#### Tooling behavior

Dependency validation is handled by the `skills-ref` tool **at submission time**.

**Tooling MUST:**

- **Check presence**: Verify all required skills exist in the skills directory.
- **Validate versions**: If version specified, check `present_version >= required_version`.
- **Detect circular dependencies**: Reject dependency chains that form cycles.
- **Report failures clearly**: Indicate which dependencies are missing or outdated.

**On success:** The skill is valid and can be used.

**On failure:** Clear error with option to ignore (e.g., `--force` flag for missing deps during development).

---

### 2. The `test` field

A new optional frontmatter field declaring test cases for skill validation.

#### Schema

```yaml
test:
  cases: <path>                 # Required. Relative path to test cases file.
  config:                       # Optional. Test execution configuration.
    timeout: <seconds>          # Max seconds per test case (default: 60).
    parallel: <boolean>         # Allow parallel execution (default: true).
```

#### Test cases file schema

```yaml
# test/cases.yaml

cases:
  - name: <test-name>           # Required. Unique identifier.
    description: <string>       # Optional. Human-readable description.
    input: <string>             # Required. The prompt to send (include any context inline).
    
    assertions:                 # Required. At least one assertion.
      output_contains:          # Output must contain ALL of these (case-insensitive).
        - <string>
      output_not_contains:      # Output must contain NONE of these (case-insensitive).
        - <string>
      output_matches:           # Output must match regex pattern.
        - <pattern>
      semantic_match:           # LLM-judged semantic criterion.
        criterion: <string>     # Clear, unambiguous success criterion.
```

The schema is intentionally minimal and agent-agnostic. Any context needed for the test (files, configurations, examples) should be included directly in the `input` field.

#### Example

```yaml
---
name: environment-selector
description: Selects deployment environment (DEV, UAT, PROD).

metadata:
  version: "1.2.0"

test:
  cases: test/cases.yaml
  config:
    timeout: 30
---
```

```yaml
# test/cases.yaml

cases:
  - name: select_dev
    description: Should select DEV environment when requested
    input: "Select the DEV environment for deployment"
    assertions:
      output_contains:
        - "DEV"
      output_not_contains:
        - "PROD"
        - "error"

  - name: reject_prod_without_confirmation
    description: Should require confirmation for PROD
    input: "Select PROD environment"
    assertions:
      output_contains:
        - "confirm"
      semantic_match:
        criterion: "Response asks for explicit confirmation before proceeding with production deployment"

  - name: parse_config_and_select
    description: Should parse inline config and select correct environment
    input: |
      Given this deployment configuration:
      ```json
      {"target": "DEV", "region": "eu-west-1", "dry_run": true}
      ```
      Select the appropriate environment based on the config.
    assertions:
      output_contains:
        - "DEV"
        - "eu-west-1"
      output_not_contains:
        - "PROD"
```

#### Execution semantics

**Assertion types:**

| Assertion | Pass condition |
|-----------|----------------|
| `output_contains` | Output includes ALL listed strings (case-insensitive) |
| `output_not_contains` | Output includes NONE of listed strings (case-insensitive) |
| `output_matches` | Output matches ALL listed regex patterns |
| `semantic_match` | LLM judge evaluates criterion as met |

**Test execution:**
- Each test case runs once
- All assertions must pass for the test to pass
- If a test fails, fix the skill or fix the test criterion

**Semantic match:**
- The criterion must be clear and unambiguous
- A well-written criterion will pass consistently
- If tests are flaky, the criterion needs to be more precise

---

### 3. Recommended `metadata` fields

While not part of the core specification, we recommend these `metadata` fields for ecosystem consistency:

```yaml
metadata:
  version: "1.2.3"              # SemVer version of this skill (required for publishing)
  author: <string>              # Author or organization name
  repository: <url>             # Source repository URL
  changelog: <path>             # Path to changelog file
  deprecated: <boolean>         # If true, skill is deprecated
  superseded-by: <coordinate>   # Skill that replaces this one
```

#### Versioning semantics

We recommend SemVer for skill versions:

- **MAJOR:** Breaking changes to skill behavior or expected output format
- **MINOR:** New capabilities, backward-compatible behavior changes
- **PATCH:** Bug fixes, documentation updates, internal improvements

---

## Implementation notes

### For tooling implementations (skills-ref, CI/CD)

Tooling implementing this specification should:

1. **Validate `requires`** at submission time against skills present in the environment
2. **Auto-generate `requires`** when creating new skills (snapshot of current environment)
3. **Provide clear errors** showing exactly which dependencies are missing or incompatible
4. **Support the CLI surface**: `validate`, `init`, `test`, `deps`

### For agent implementations

**No changes required.** Agents continue to:

1. Discover skills from configured locations
2. Read `SKILL.md` files as today
3. Activate skills based on task relevance

The `requires`, `test`, and `metadata.version` fields are opaque to agents — they may ignore them entirely. Tooling ensures that by the time an agent sees a skill, all dependencies are satisfied.

### For skill authors

Skill authors should:

1. **Declare dependencies explicitly** rather than assuming skills exist
2. **Write tests** for critical behavior, using clear assertion criteria
3. **Use semantic versioning** to communicate the impact of changes

### For CI/CD systems

Build systems can:

1. **Build dependency graphs** from `requires` fields
2. **Run tests automatically** when skills or their dependencies change
3. **Enforce version constraints** before deploying skill updates
4. **Detect and alert** on deprecated dependencies

### Reference tooling

The `skills-ref` CLI should be extended with:

```bash
# Initialize a new skill with auto-populated requires
skills-ref init ./my-skill

# Validate skill format and dependencies
skills-ref validate ./my-skill

# Run tests
skills-ref test ./my-skill

# Check for circular dependencies
skills-ref deps --check-circular

# Visualize dependency graph
skills-ref deps --graph
```

---

## Security considerations

### Skill name collisions

Skills are identified by name only. In shared environments, naming collisions could occur.

**Mitigations:**
- Use descriptive, organization-prefixed names (e.g., `acme-environment-selector`)
- Control which skill directories are included in your environment

### Test case injection

Malicious test cases could attempt to execute harmful commands.

**Mitigations:**
- Test runners should execute in sandboxed environments
- Limit available tools during test execution
- Review test cases as part of skill review process

---

## Migration guide

### From v1.0 skills

Existing skills require no changes. To adopt the new features:

1. **Add version** to `metadata`: `metadata: { version: "1.0.0" }`
2. **Add `requires`** for any assumed dependencies
3. **Add `test`** with at least smoke test cases

### Gradual adoption

Organizations can adopt features incrementally:

| Phase | Features | Effort |
|-------|----------|--------|
| 1 | Add versions to metadata | Low |
| 2 | Declare explicit dependencies | Low |
| 3 | Add basic tests (string assertions) | Medium |
| 4 | Add semantic tests | Low |

---

## Open questions

1. **Should there be a standard skill registry?**
   
   A registry would enable sharing skills across organizations and teams. For now, skills are local files managed via git.

2. **Should semantic assertions have a standard judge prompt?**
   
   Standardizing the judge prompt would improve consistency across implementations but reduce flexibility.

3. **How should the tool discover the skills root directory?**
   
   Options: config file, environment variable, convention (e.g., `.skills/` or `skills/` in project root).

---

## Changelog

- **2026-01-27:** Simplified spec: removed namespaces, optional deps, retry logic. Version = minimum required. Deterministic testing.
- **2026-01-26:** Initial draft

---

## References

- [Agent Skills Specification](https://agentskills.io/specification)
- [Semantic Versioning 2.0.0](https://semver.org/)
- [Maven POM Reference - Dependencies](https://maven.apache.org/pom.html#Dependencies)
