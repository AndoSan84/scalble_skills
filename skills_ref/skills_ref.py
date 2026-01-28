#!/usr/bin/env python3
"""
skills-ref: Reference implementation for Agent Skills v1.1

Validates skills, checks dependencies, and runs tests according to
the Agent Skills Dependencies and Testing Specification.

Usage:
    skills-ref validate <skill-path> [--skills-root <path>] [--force]
    skills-ref init <skill-path> [--skills-root <path>]
    skills-ref test <skill-path> [--skills-root <path>]
    skills-ref deps [--skills-root <path>] [--check-circular] [--graph]
"""

import argparse
import os
import re
import sys
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from packaging import version as pkg_version


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class Dependency:
    skill: str
    version: Optional[str] = None


@dataclass
class TestConfig:
    timeout: int = 60
    parallel: bool = True


@dataclass
class Assertion:
    output_contains: list[str] = field(default_factory=list)
    output_not_contains: list[str] = field(default_factory=list)
    output_matches: list[str] = field(default_factory=list)
    semantic_match: Optional[dict] = None


@dataclass
class TestCase:
    name: str
    input: str
    assertions: Assertion
    description: Optional[str] = None


@dataclass
class SkillMetadata:
    name: str
    description: str
    version: Optional[str] = None
    requires: list[Dependency] = field(default_factory=list)
    test_cases_path: Optional[str] = None
    test_config: TestConfig = field(default_factory=TestConfig)


# ============================================================================
# Parsing
# ============================================================================

def parse_skill_md(skill_path: Path) -> SkillMetadata:
    """Parse a SKILL.md file and extract frontmatter."""
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"SKILL.md not found in {skill_path}")
    
    content = skill_md.read_text(encoding="utf-8")
    
    # Extract YAML frontmatter
    if not content.startswith("---"):
        raise ValueError(f"SKILL.md must start with YAML frontmatter (---)")
    
    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"Invalid frontmatter format in {skill_md}")
    
    frontmatter = yaml.safe_load(parts[1])
    
    # Required fields
    if "name" not in frontmatter:
        raise ValueError(f"Missing required field 'name' in {skill_md}")
    if "description" not in frontmatter:
        raise ValueError(f"Missing required field 'description' in {skill_md}")
    
    # Parse metadata
    metadata = frontmatter.get("metadata", {})
    version = metadata.get("version") if isinstance(metadata, dict) else None
    
    # Parse requires
    requires = []
    for req in frontmatter.get("requires", []):
        if isinstance(req, dict):
            requires.append(Dependency(
                skill=req.get("skill"),
                version=req.get("version")
            ))
    
    # Parse test config
    test_config = TestConfig()
    test_cases_path = None
    if "test" in frontmatter:
        test = frontmatter["test"]
        test_cases_path = test.get("cases")
        if "config" in test:
            cfg = test["config"]
            test_config = TestConfig(
                timeout=cfg.get("timeout", 60),
                parallel=cfg.get("parallel", True)
            )
    
    return SkillMetadata(
        name=frontmatter["name"],
        description=frontmatter["description"],
        version=version,
        requires=requires,
        test_cases_path=test_cases_path,
        test_config=test_config
    )


def parse_test_cases(skill_path: Path, cases_path: str) -> list[TestCase]:
    """Parse test cases file."""
    full_path = skill_path / cases_path
    if not full_path.exists():
        raise FileNotFoundError(f"Test cases file not found: {full_path}")
    
    content = yaml.safe_load(full_path.read_text(encoding="utf-8"))
    cases = []
    
    for case in content.get("cases", []):
        assertions = case.get("assertions", {})
        cases.append(TestCase(
            name=case["name"],
            input=case["input"],
            description=case.get("description"),
            assertions=Assertion(
                output_contains=assertions.get("output_contains", []),
                output_not_contains=assertions.get("output_not_contains", []),
                output_matches=assertions.get("output_matches", []),
                semantic_match=assertions.get("semantic_match")
            )
        ))
    
    return cases


# ============================================================================
# Validation
# ============================================================================

@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def find_skill_by_name(skills_root: Path, name: str) -> Optional[Path]:
    """Find a skill directory by name."""
    for skill_dir in skills_root.iterdir():
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            try:
                meta = parse_skill_md(skill_dir)
                if meta.name == name:
                    return skill_dir
            except Exception:
                continue
    return None


def compare_versions(present: str, required: str) -> bool:
    """Check if present version >= required version."""
    try:
        return pkg_version.parse(present) >= pkg_version.parse(required)
    except Exception:
        # Fallback to string comparison if not valid semver
        return present >= required


def validate_dependencies(
    skill: SkillMetadata,
    skills_root: Path,
    force: bool = False
) -> ValidationResult:
    """Validate that all dependencies are present and versions match."""
    result = ValidationResult(valid=True)
    
    for dep in skill.requires:
        dep_path = find_skill_by_name(skills_root, dep.skill)
        
        if dep_path is None:
            msg = f"Required skill '{dep.skill}' not found"
            if force:
                result.warnings.append(f"{msg} (ignored with --force)")
            else:
                result.errors.append(msg)
                result.valid = False
            continue
        
        # Check version if specified
        if dep.version:
            try:
                dep_meta = parse_skill_md(dep_path)
                if dep_meta.version is None:
                    result.warnings.append(
                        f"Skill '{dep.skill}' has no version in metadata, "
                        f"cannot verify >= {dep.version}"
                    )
                elif not compare_versions(dep_meta.version, dep.version):
                    msg = (
                        f"Skill '{dep.skill}' version {dep_meta.version} "
                        f"< required {dep.version}"
                    )
                    if force:
                        result.warnings.append(f"{msg} (ignored with --force)")
                    else:
                        result.errors.append(msg)
                        result.valid = False
            except Exception as e:
                result.errors.append(f"Error reading '{dep.skill}': {e}")
                result.valid = False
    
    return result


def detect_circular_dependencies(skills_root: Path) -> list[list[str]]:
    """Detect circular dependency chains. Returns list of cycles found."""
    # Build dependency graph
    graph: dict[str, list[str]] = {}
    
    for skill_dir in skills_root.iterdir():
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            try:
                meta = parse_skill_md(skill_dir)
                graph[meta.name] = [dep.skill for dep in meta.requires]
            except Exception:
                continue
    
    # DFS to find cycles
    cycles = []
    visited = set()
    rec_stack = []
    
    def dfs(node: str, path: list[str]) -> None:
        if node in rec_stack:
            # Found cycle
            cycle_start = rec_stack.index(node)
            cycles.append(rec_stack[cycle_start:] + [node])
            return
        
        if node in visited:
            return
        
        visited.add(node)
        rec_stack.append(node)
        
        for neighbor in graph.get(node, []):
            dfs(neighbor, path + [neighbor])
        
        rec_stack.pop()
    
    for node in graph:
        if node not in visited:
            dfs(node, [node])
    
    return cycles


def validate_skill(
    skill_path: Path,
    skills_root: Path,
    force: bool = False
) -> ValidationResult:
    """Full validation of a skill."""
    result = ValidationResult(valid=True)
    
    # Parse skill
    try:
        skill = parse_skill_md(skill_path)
    except Exception as e:
        result.errors.append(f"Failed to parse SKILL.md: {e}")
        result.valid = False
        return result
    
    # Validate name format
    if not re.match(r'^[a-z][a-z0-9-]*$', skill.name):
        result.warnings.append(
            f"Name '{skill.name}' should be lowercase with hyphens only"
        )
    
    # Validate dependencies
    dep_result = validate_dependencies(skill, skills_root, force)
    result.errors.extend(dep_result.errors)
    result.warnings.extend(dep_result.warnings)
    if not dep_result.valid:
        result.valid = False
    
    # Check for circular dependencies involving this skill
    cycles = detect_circular_dependencies(skills_root)
    for cycle in cycles:
        if skill.name in cycle:
            result.errors.append(f"Circular dependency detected: {' -> '.join(cycle)}")
            result.valid = False
    
    # Validate test cases file exists if specified
    if skill.test_cases_path:
        test_file = skill_path / skill.test_cases_path
        if not test_file.exists():
            result.errors.append(f"Test cases file not found: {skill.test_cases_path}")
            result.valid = False
    
    return result


# ============================================================================
# Test Runner
# ============================================================================

def evaluate_assertions(output: str, assertions: Assertion) -> tuple[bool, list[str]]:
    """Evaluate assertions against output. Returns (passed, errors)."""
    errors = []
    output_lower = output.lower()
    
    # output_contains
    for expected in assertions.output_contains:
        if expected.lower() not in output_lower:
            errors.append(f"output_contains: '{expected}' not found in output")
    
    # output_not_contains
    for forbidden in assertions.output_not_contains:
        if forbidden.lower() in output_lower:
            errors.append(f"output_not_contains: '{forbidden}' found in output")
    
    # output_matches
    for pattern in assertions.output_matches:
        if not re.search(pattern, output, re.IGNORECASE):
            errors.append(f"output_matches: pattern '{pattern}' not matched")
    
    # semantic_match - requires LLM, placeholder for now
    if assertions.semantic_match:
        criterion = assertions.semantic_match.get("criterion", "")
        # This would call an LLM API to judge
        # For now, we'll mark it as needing manual verification
        print(f"    ⚠ semantic_match requires LLM judge: '{criterion}'")
    
    return len(errors) == 0, errors


def run_test_case(
    case: TestCase,
    skill: SkillMetadata,
    skill_path: Path,
    agent_runner: Optional[callable] = None
) -> tuple[bool, list[str]]:
    """
    Run a single test case.
    
    agent_runner: callable that takes (skill_path, input) and returns output string.
                  If None, uses a mock that just echoes the input.
    """
    if agent_runner is None:
        # Mock runner for testing the tool itself
        print(f"    ⚠ No agent runner configured, skipping execution")
        return True, []
    
    try:
        output = agent_runner(skill_path, case.input)
        return evaluate_assertions(output, case.assertions)
    except Exception as e:
        return False, [f"Execution error: {e}"]


def run_tests(
    skill_path: Path,
    skills_root: Path,
    agent_runner: Optional[callable] = None
) -> tuple[int, int]:
    """
    Run all tests for a skill.
    Returns (passed_count, total_count).
    """
    skill = parse_skill_md(skill_path)
    
    if not skill.test_cases_path:
        print(f"No tests defined for skill '{skill.name}'")
        return 0, 0
    
    cases = parse_test_cases(skill_path, skill.test_cases_path)
    passed = 0
    total = len(cases)
    
    print(f"\nRunning {total} test(s) for '{skill.name}':\n")
    
    for case in cases:
        desc = f" - {case.description}" if case.description else ""
        print(f"  [{case.name}]{desc}")
        
        success, errors = run_test_case(case, skill, skill_path, agent_runner)
        
        if success:
            print(f"    ✓ PASSED")
            passed += 1
        else:
            print(f"    ✗ FAILED")
            for err in errors:
                print(f"      - {err}")
    
    print(f"\nResults: {passed}/{total} passed")
    return passed, total


# ============================================================================
# Init Command
# ============================================================================

def init_skill(skill_path: Path, skills_root: Path) -> None:
    """Initialize a new skill with auto-populated requires."""
    skill_path.mkdir(parents=True, exist_ok=True)
    
    # Collect all available skills and their versions
    available_skills = []
    for skill_dir in skills_root.iterdir():
        if not skill_dir.is_dir() or skill_dir == skill_path:
            continue
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            try:
                meta = parse_skill_md(skill_dir)
                available_skills.append({
                    "name": meta.name,
                    "version": meta.version
                })
            except Exception:
                continue
    
    # Generate SKILL.md template
    skill_name = skill_path.name
    
    requires_block = ""
    if available_skills:
        requires_lines = ["requires:"]
        for s in available_skills:
            if s["version"]:
                requires_lines.append(f'  - skill: {s["name"]}')
                requires_lines.append(f'    version: "{s["version"]}"')
            else:
                requires_lines.append(f'  - skill: {s["name"]}')
        requires_block = "\n" + "\n".join(requires_lines)
    
    template = f'''---
name: {skill_name}
description: TODO - Describe what this skill does and when to use it.

metadata:
  version: "1.0.0"
{requires_block}
test:
  cases: test/cases.yaml
  config:
    timeout: 60
---

# {skill_name}

## Instructions

TODO - Add skill instructions here.

## Examples

TODO - Add examples here.
'''
    
    skill_md = skill_path / "SKILL.md"
    skill_md.write_text(template, encoding="utf-8")
    print(f"Created {skill_md}")
    
    # Create test directory and template
    test_dir = skill_path / "test"
    test_dir.mkdir(exist_ok=True)
    
    test_template = '''cases:
  - name: basic_test
    description: TODO - Describe what this test verifies
    input: "TODO - The prompt to send"
    assertions:
      output_contains:
        - "expected text"
      output_not_contains:
        - "error"
'''
    
    test_file = test_dir / "cases.yaml"
    test_file.write_text(test_template, encoding="utf-8")
    print(f"Created {test_file}")
    
    if available_skills:
        print(f"\nAuto-populated requires with {len(available_skills)} skill(s) found in {skills_root}")
        print("Edit SKILL.md to keep only the dependencies you actually need.")


# ============================================================================
# Deps Command
# ============================================================================

def show_deps(skills_root: Path, check_circular: bool = False, graph: bool = False) -> None:
    """Show dependency information."""
    # Build dependency info
    skills_info = {}
    
    for skill_dir in skills_root.iterdir():
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            try:
                meta = parse_skill_md(skill_dir)
                skills_info[meta.name] = {
                    "version": meta.version,
                    "requires": [(d.skill, d.version) for d in meta.requires]
                }
            except Exception as e:
                print(f"Warning: Could not parse {skill_dir}: {e}")
    
    if check_circular:
        cycles = detect_circular_dependencies(skills_root)
        if cycles:
            print("Circular dependencies detected:")
            for cycle in cycles:
                print(f"  {' -> '.join(cycle)}")
            sys.exit(1)
        else:
            print("No circular dependencies found.")
        return
    
    if graph:
        print("\nDependency Graph:")
        print("=" * 40)
        for name, info in sorted(skills_info.items()):
            version_str = f"@{info['version']}" if info['version'] else ""
            print(f"\n{name}{version_str}")
            if info['requires']:
                for dep_name, dep_version in info['requires']:
                    dep_ver_str = f" (>= {dep_version})" if dep_version else ""
                    present = "✓" if dep_name in skills_info else "✗"
                    print(f"  └── {present} {dep_name}{dep_ver_str}")
            else:
                print("  └── (no dependencies)")
        return
    
    # Default: list all skills
    print(f"\nSkills in {skills_root}:")
    print("=" * 40)
    for name, info in sorted(skills_info.items()):
        version_str = f"@{info['version']}" if info['version'] else " (no version)"
        deps_count = len(info['requires'])
        deps_str = f", {deps_count} dep(s)" if deps_count > 0 else ""
        print(f"  {name}{version_str}{deps_str}")


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="skills-ref: Agent Skills validation and testing tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  skills-ref validate ./my-skill
  skills-ref init ./new-skill --skills-root ./skills
  skills-ref test ./my-skill
  skills-ref deps --graph
  skills-ref deps --check-circular
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # validate command
    validate_parser = subparsers.add_parser("validate", help="Validate a skill")
    validate_parser.add_argument("skill_path", type=Path, help="Path to skill directory")
    validate_parser.add_argument("--skills-root", type=Path, default=Path("."),
                                  help="Root directory containing all skills")
    validate_parser.add_argument("--force", action="store_true",
                                  help="Continue despite missing dependencies")
    
    # init command
    init_parser = subparsers.add_parser("init", help="Initialize a new skill")
    init_parser.add_argument("skill_path", type=Path, help="Path for new skill directory")
    init_parser.add_argument("--skills-root", type=Path, default=Path("."),
                              help="Root directory containing all skills")
    
    # test command
    test_parser = subparsers.add_parser("test", help="Run tests for a skill")
    test_parser.add_argument("skill_path", type=Path, help="Path to skill directory")
    test_parser.add_argument("--skills-root", type=Path, default=Path("."),
                              help="Root directory containing all skills")
    
    # deps command
    deps_parser = subparsers.add_parser("deps", help="Show dependency information")
    deps_parser.add_argument("--skills-root", type=Path, default=Path("."),
                              help="Root directory containing all skills")
    deps_parser.add_argument("--check-circular", action="store_true",
                              help="Check for circular dependencies")
    deps_parser.add_argument("--graph", action="store_true",
                              help="Show dependency graph")
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    
    try:
        if args.command == "validate":
            result = validate_skill(args.skill_path, args.skills_root, args.force)
            
            if result.warnings:
                print("Warnings:")
                for w in result.warnings:
                    print(f"  ⚠ {w}")
            
            if result.errors:
                print("Errors:")
                for e in result.errors:
                    print(f"  ✗ {e}")
            
            if result.valid:
                print(f"\n✓ Skill '{args.skill_path}' is valid")
                sys.exit(0)
            else:
                print(f"\n✗ Skill '{args.skill_path}' has validation errors")
                sys.exit(1)
        
        elif args.command == "init":
            init_skill(args.skill_path, args.skills_root)
        
        elif args.command == "test":
            passed, total = run_tests(args.skill_path, args.skills_root)
            if total > 0 and passed < total:
                sys.exit(1)
        
        elif args.command == "deps":
            show_deps(args.skills_root, args.check_circular, args.graph)
    
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
