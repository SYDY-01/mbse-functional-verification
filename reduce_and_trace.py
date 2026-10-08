# -*- coding: utf-8 -*-
"""
nuXmv counterexample reduction and requirement traceability.

Pipeline:
    raw nuXmv output
        -> trigger-reachability result separation
        -> safe counterexample reduction
        -> *_compressed.txt
        -> requirement/component tracing and rule-based diagnosis
        -> *_Trace_diagnosis.txt

Named CTL properties whose names begin with COV_ are diagnostic trigger-
reachability checks.  They are summarized separately and never counted as
failed functional specifications or sent to counterexample diagnosis.

Only Python's standard library is required.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# Default paths. They preserve the usage style of the original script.
# Command-line arguments can override every path without editing this file.
# ---------------------------------------------------------------------------
SCRIPT_DIRECTORY = Path(__file__).resolve().parent
DEFAULT_RESULT_FILE = (
    SCRIPT_DIRECTORY / "TestWrong/input_FMCS_FI_05_Result.txt"
)
DEFAULT_MODEL_FILE = (
    SCRIPT_DIRECTORY / "TestWrong/input_FMCS_FI_05_Result.smv"
)
DEFAULT_REQUIREMENT_SPEC_FILE = (
    SCRIPT_DIRECTORY / "TestWrong/FMCS_CTL_and_LTL_Specifications.smv"
)
# DEFAULT_RESULT_FILE = (
#     SCRIPT_DIRECTORY / "FMCS/input_XModel_FMCS_Result.txt"
# )
# DEFAULT_MODEL_FILE = (
#     SCRIPT_DIRECTORY / "FMCS/input_XModel_FMCS_Result.smv"
# )
# DEFAULT_REQUIREMENT_SPEC_FILE = (
#     SCRIPT_DIRECTORY / "FMCS/FMCS_CTL_and_LTL_Specifications.smv"
# )

SPECIFICATION_PREFIX_RE = re.compile(
    r"^--\s*specification\b",
    flags=re.IGNORECASE,
)
FALSE_SPEC_RE = re.compile(
    r"^--\s*specification\s+(.*?)\s+is\s+false\s*$",
    flags=re.IGNORECASE,
)
SPEC_RESULT_RE = re.compile(
    r"^--\s*specification\s+(.*?)\s+is\s+(true|false)\s*$",
    flags=re.IGNORECASE,
)
TRIGGER_COVERAGE_HEADER_RE = re.compile(
    r"^--\s*\[TRIGGER-COVERAGE\s+([^\]]+)\]\s*(.*?)\s*$",
    flags=re.IGNORECASE,
)
TRIGGER_COVERAGE_SPEC_RE = re.compile(
    r"^CTLSPEC\s+NAME\s+([A-Za-z_][A-Za-z0-9_]*)\s*"
    r":=\s*(.*?)\s*;\s*$",
    flags=re.IGNORECASE | re.DOTALL,
)
STATE_HEADER_RE = re.compile(
    r"->\s*State:\s*([0-9]+(?:\.[0-9]+)*)\s*<-",
    flags=re.IGNORECASE,
)
FORMULA_VARIABLE_RE = re.compile(
    r"\b[A-Za-z_][A-Za-z0-9_]*"
    r"(?:\.[A-Za-z_][A-Za-z0-9_$\[\]-]*)+\b"
)


# ---------------------------------------------------------------------------
# Generic text I/O
# ---------------------------------------------------------------------------
def read_text_with_fallback(file_path: Path) -> str:
    """
    Read UTF-8 and PowerShell-redirected UTF-16 output safely.

    PowerShell 5 commonly writes UTF-16 LE.  A NUL-byte check is used because
    a BOM-less UTF-16 file can sometimes be decoded as UTF-8 without raising
    an exception, while still producing unusable text.
    """
    data = file_path.read_bytes()

    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig")
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16")

    sample = data[:4096]
    if sample and sample.count(b"\x00") / len(sample) > 0.10:
        even_nuls = sample[0::2].count(b"\x00")
        odd_nuls = sample[1::2].count(b"\x00")
        encoding = "utf-16-be" if even_nuls > odd_nuls else "utf-16-le"
        return data.decode(encoding)

    for encoding in ("utf-8-sig", "gb18030", "utf-16-le"):
        try:
            return data.decode(encoding)
        except UnicodeError:
            continue

    return data.decode("utf-8", errors="replace")


def read_lines_with_fallback(file_path: Path) -> list[str]:
    """Read a text file and retain line endings."""
    return read_text_with_fallback(file_path).splitlines(keepends=True)


def write_utf8(file_path: Path, lines: Iterable[str]) -> None:
    """Write normalized UTF-8 text and create only the required parent path."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8", newline="\n") as file:
        for line in lines:
            file.write(line if line.endswith("\n") else f"{line}\n")


def extract_failed_spec(specification_line: str) -> str | None:
    """Return the formula when a nuXmv result line says that it is false."""
    match = FALSE_SPEC_RE.match(specification_line.strip())
    return match.group(1).strip() if match else None


def parse_specification_result(
    specification_line: str,
) -> tuple[str, bool] | None:
    """Return ``(printed property, is_true)`` for one nuXmv result line."""
    match = SPEC_RESULT_RE.match(specification_line.strip())
    if not match:
        return None
    return match.group(1).strip(), match.group(2).lower() == "true"


def extract_state_id(header: str) -> str:
    match = STATE_HEADER_RE.search(header)
    return match.group(1) if match else "?"


def parse_assignment(line: str) -> tuple[str, str] | None:
    """Parse a nuXmv delta-trace assignment and reject visual separators."""
    stripped = line.strip()
    if not stripped or stripped.startswith("--"):
        return None
    if re.fullmatch(r"=+", stripped) or "=" not in stripped:
        return None

    left, right = stripped.split("=", 1)
    variable = left.strip()
    value = right.strip()

    if not variable or not value:
        return None
    if not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_.$\[\]-]*",
        variable,
    ):
        return None

    return variable, value


def is_assignment_line(line: str) -> bool:
    return parse_assignment(line) is not None


def is_fold_summary_line(line: str) -> bool:
    stripped = line.strip()
    return (
        stripped.startswith("... [已折叠")
        or stripped.startswith("... [隐藏的状态区间")
    )


# ---------------------------------------------------------------------------
# Requirement-to-specification source index
# ---------------------------------------------------------------------------
def formula_signature(spec: str) -> str:
    """
    Build a formatting-insensitive signature for cross-file formula matching.

    Parenthesis and whitespace differences between the generated SPEC/LTLSPEC
    statement and nuXmv's result line are ignored.  The order of identifiers,
    values and logical/temporal operators is retained.
    """
    normalized = spec.strip()
    normalized = re.sub(
        r"^--\s*specification\s+",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"\s+is\s+(?:true|false)\s*$",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"^(?:LTLSPEC|CTLSPEC|SPEC)\s+",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    # Named properties may be printed as either ``NAME COV_X := EF(P)`` or
    # ``COV_X := EF(P)``.  Remove the diagnostic name before comparing the
    # actual formula with the generated coverage index.
    normalized = re.sub(
        r"^NAME\s+[A-Za-z_][A-Za-z0-9_]*\s*:=\s*",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"^[A-Za-z_][A-Za-z0-9_]*\s*:=\s*",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = normalized.rstrip("; ")

    token_pattern = re.compile(
        r"<->|->|<=|>=|!=|:=|"
        r"[A-Za-z_][A-Za-z0-9_.$]*|"
        r"-?\d+(?:\.\d+)?|"
        r"[!&|=<>+\-*/]"
    )
    return "\x1f".join(token_pattern.findall(normalized))


@dataclass(frozen=True)
class TriggerCoverageCheck:
    """Metadata for one generated ``EF(P)`` diagnostic property."""

    property_name: str
    requirement_id: str
    pattern_type: str
    condition: str
    formula: str


@dataclass
class TriggerCoverageCatalog:
    """Lookup trigger checks by either property name or printed formula."""

    checks: list[TriggerCoverageCheck] = field(default_factory=list)
    by_name: dict[str, TriggerCoverageCheck] = field(default_factory=dict)
    by_signature: dict[str, list[TriggerCoverageCheck]] = field(
        default_factory=dict
    )

    def add(self, check: TriggerCoverageCheck) -> None:
        normalized_name = check.property_name.upper()
        previous = self.by_name.get(normalized_name)
        if previous and previous.requirement_id != check.requirement_id:
            raise ValueError(
                "覆盖属性名重复："
                f"{check.property_name} 同时对应 "
                f"{previous.requirement_id} 和 {check.requirement_id}。"
            )
        if previous:
            return

        self.checks.append(check)
        self.by_name[normalized_name] = check
        signature = formula_signature(check.formula)
        self.by_signature.setdefault(signature, []).append(check)

    def match_result_body(self, result_body: str) -> list[TriggerCoverageCheck]:
        """Match nuXmv output whether it prints the name, formula, or both."""
        for name in re.findall(
            r"\bCOV_[A-Za-z0-9_]+\b",
            result_body,
            flags=re.IGNORECASE,
        ):
            check = self.by_name.get(name.upper())
            if check:
                return [check]

        signature = formula_signature(result_body)
        return list(self.by_signature.get(signature, []))


def parse_trigger_coverage_catalog(
    requirement_spec_file: str | Path,
) -> TriggerCoverageCatalog:
    """Read generated ``TRIGGER-COVERAGE`` metadata before the copy block."""
    spec_path = Path(requirement_spec_file)
    catalog = TriggerCoverageCatalog()
    if not spec_path.exists():
        return catalog

    lines = read_lines_with_fallback(spec_path)
    current_requirement_id: str | None = None
    current_pattern_type = ""
    current_condition = ""
    line_index = 0

    while line_index < len(lines):
        line = lines[line_index].strip()
        if "BEGIN: 可直接复制" in line:
            break

        header_match = TRIGGER_COVERAGE_HEADER_RE.match(line)
        if header_match:
            current_requirement_id = header_match.group(1).strip()
            current_pattern_type = header_match.group(2).strip()
            current_condition = ""
            line_index += 1
            continue

        if current_requirement_id and line.startswith("-- 触发条件："):
            current_condition = line.split("：", 1)[1].strip()
            line_index += 1
            continue

        if current_requirement_id and re.match(
            r"^CTLSPEC\s+NAME\b",
            line,
            flags=re.IGNORECASE,
        ):
            statement_parts = [line]
            while (
                ";" not in statement_parts[-1]
                and line_index + 1 < len(lines)
            ):
                line_index += 1
                statement_parts.append(lines[line_index].strip())

            statement = " ".join(
                part for part in statement_parts if part
            )
            spec_match = TRIGGER_COVERAGE_SPEC_RE.match(statement)
            if not spec_match:
                raise ValueError(
                    "无法解析触发可达性规约："
                    f"{statement}"
                )

            property_name = spec_match.group(1)
            formula_body = spec_match.group(2).strip()
            catalog.add(
                TriggerCoverageCheck(
                    property_name=property_name,
                    requirement_id=current_requirement_id,
                    pattern_type=current_pattern_type,
                    condition=current_condition,
                    formula=formula_body,
                )
            )
            current_requirement_id = None
            current_pattern_type = ""
            current_condition = ""

        line_index += 1

    return catalog


def is_trigger_coverage_result(
    result_body: str,
    catalog: TriggerCoverageCatalog | None,
) -> bool:
    """Identify diagnostics so they never enter requirement-failure tracing."""
    if re.search(
        r"\bCOV_[A-Za-z0-9_]+\b",
        result_body,
        flags=re.IGNORECASE,
    ):
        return True
    return bool(catalog and catalog.match_result_body(result_body))


def parse_trigger_coverage_results(
    result_file: str | Path,
    catalog: TriggerCoverageCatalog,
) -> dict[str, bool]:
    """Return property-name -> reachability status from the nuXmv output."""
    if not catalog.checks:
        return {}

    result_path = Path(result_file)
    statuses: dict[str, bool] = {}
    for raw_line in read_lines_with_fallback(result_path):
        parsed = parse_specification_result(raw_line)
        if parsed is None:
            continue
        result_body, is_true = parsed
        for check in catalog.match_result_body(result_body):
            previous = statuses.get(check.property_name)
            if previous is not None and previous != is_true:
                raise ValueError(
                    f"覆盖属性 {check.property_name} 出现相互矛盾的结果。"
                )
            statuses[check.property_name] = is_true

    return statuses


def format_trigger_coverage_summary(
    catalog: TriggerCoverageCatalog,
    statuses: dict[str, bool],
) -> list[str]:
    """Render a compact diagnostic section without inflating the 51 specs."""
    lines = [
        "[*] 触发可达性检查 (Trigger Reachability Check):",
        "    说明: 仅检查触发前件是否可达；诊断属性不计入正式需求规约总数。",
    ]

    if not catalog.checks:
        lines.extend(
            [
                "    未在规约生成文件中发现触发可达性检查。",
                "",
            ]
        )
        return lines

    reachable = [
        check
        for check in catalog.checks
        if statuses.get(check.property_name) is True
    ]
    unreachable = [
        check
        for check in catalog.checks
        if statuses.get(check.property_name) is False
    ]
    missing = [
        check
        for check in catalog.checks
        if check.property_name not in statuses
    ]

    lines.extend(
        [
            f"    适用规约: {len(catalog.checks)}",
            "    已获得检查结果: "
            f"{len(statuses)}/{len(catalog.checks)}",
            f"    已获得结果中触发条件可达: {len(reachable)}",
            "    已获得结果中触发条件不可达（潜在空满足）: "
            f"{len(unreachable)}",
            f"    未获得检查结果: {len(missing)}",
        ]
    )

    if unreachable:
        lines.append("    [!] 潜在空满足需求:")
        for check in unreachable:
            condition = check.condition or check.formula
            lines.append(
                f"        - {check.requirement_id} "
                f"({check.pattern_type}): {condition}"
            )
    elif not missing:
        lines.append("    [+] 所有触发型规约的触发条件均可达。")

    if missing:
        lines.append(
            "    [!] 检查结果不完整，不能据此推断全部触发条件均可达。"
        )
        lines.append("    [!] 未解析到结果的覆盖属性:")
        for check in missing:
            lines.append(
                f"        - {check.requirement_id}: "
                f"{check.property_name}"
            )

    lines.append("")
    return lines


@dataclass(frozen=True)
class RequirementSpecRecord:
    """One provenance record retained during requirement formalization."""

    requirement_id: str
    pattern_type: str
    logic_type: str
    formula: str


def parse_requirement_spec_index(
    requirement_spec_file: str | Path,
) -> dict[str, list[RequirementSpecRecord]]:
    """Build formula -> source requirement entries from the generated file."""
    spec_path = Path(requirement_spec_file)
    index: dict[str, list[RequirementSpecRecord]] = {}

    if not spec_path.exists():
        print(
            f"[!] 警告: 找不到时序逻辑结果文件 {spec_path}，"
            "报告仍会生成，但无法追溯到来源需求编号。"
        )
        return index

    lines = read_lines_with_fallback(spec_path)
    current_requirement_id: str | None = None
    current_pattern_type = ""
    current_logic_type = ""
    line_index = 0

    while line_index < len(lines):
        line = lines[line_index].strip()
        if "BEGIN: 可直接复制" in line:
            break

        header_match = re.match(
            r"^--\s*\[([^\]]+)\]\s*(.*?)\s*/\s*(CTL|LTL)\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if header_match:
            current_requirement_id = header_match.group(1).strip()
            current_pattern_type = header_match.group(2).strip()
            current_logic_type = header_match.group(3).upper()
            line_index += 1
            continue

        if re.match(
            r"^(LTLSPEC|CTLSPEC|SPEC)\b",
            line,
            flags=re.IGNORECASE,
        ):
            if current_requirement_id:
                formula_parts = [line]
                while (
                    ";" not in formula_parts[-1]
                    and line_index + 1 < len(lines)
                ):
                    line_index += 1
                    formula_parts.append(lines[line_index].strip())

                formula_statement = " ".join(
                    part for part in formula_parts if part
                )
                signature = formula_signature(formula_statement)
                if signature:
                    entry = RequirementSpecRecord(
                        requirement_id=current_requirement_id,
                        pattern_type=current_pattern_type,
                        logic_type=current_logic_type,
                        formula=formula_statement,
                    )
                    candidates = index.setdefault(signature, [])
                    if not any(
                        candidate.requirement_id == current_requirement_id
                        for candidate in candidates
                    ):
                        candidates.append(entry)

            current_requirement_id = None
            current_pattern_type = ""
            current_logic_type = ""

        line_index += 1

    return index


def find_requirement_sources(
    failed_spec: str,
    requirement_spec_index: dict[str, list[RequirementSpecRecord]],
) -> list[RequirementSpecRecord]:
    """Return every provenance record matching a failed printed formula."""
    return list(
        requirement_spec_index.get(formula_signature(failed_spec), [])
    )


def format_requirement_trace(
    matches: list[RequirementSpecRecord],
) -> str:
    """Format source IDs without repeating the natural-language requirement."""
    output_lines = ["[*] 来源需求追溯 (Source Requirement Trace):"]

    if not matches:
        output_lines.append("    未在时序逻辑结果文件中找到匹配的来源需求。")
        return "\n".join(output_lines)

    for match_index, match in enumerate(matches, start=1):
        if len(matches) > 1:
            output_lines.append(f"    候选来源 #{match_index}:")
        output_lines.append(
            "    需求编号 (Requirement ID): "
            f"{match.requirement_id}"
        )
        output_lines.append(
            "    需求模式/逻辑类型 (Pattern/Logic): "
            f"{match.pattern_type} / {match.logic_type}"
        )
        output_lines.append(
            "    生成规约 (Generated Spec): "
            f"{match.formula}"
        )

    return "\n".join(output_lines)


# ---------------------------------------------------------------------------
# SMV instance/module reverse index
# ---------------------------------------------------------------------------
def parse_smv_model(smv_file: str | Path) -> dict[str, str]:
    """Extract instance -> module type mappings from MODULE main."""
    smv_path = Path(smv_file)
    mapping: dict[str, str] = {}

    if not smv_path.exists():
        print(f"[!] 警告: 找不到模型文件 {smv_path}，将跳过实例名还原步骤。")
        return mapping

    in_main_module = False
    for raw_line in read_lines_with_fallback(smv_path):
        line = raw_line.strip()
        if not line or line.startswith("--"):
            continue

        module_match = re.match(
            r"^MODULE\s+([A-Za-z_][A-Za-z0-9_]*)\b",
            line,
            flags=re.IGNORECASE,
        )
        if module_match:
            in_main_module = module_match.group(1).lower() == "main"
            continue
        if not in_main_module:
            continue

        instance_match = re.match(
            r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*"
            r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(|;)",
            line,
        )
        if instance_match:
            instance_name, module_name = instance_match.groups()
            mapping[instance_name] = module_name

    return mapping


# ---------------------------------------------------------------------------
# Safe reduction of each counterexample independently
# ---------------------------------------------------------------------------
@dataclass
class TraceStateBlock:
    header: str
    body: list[str] = field(default_factory=list)
    loop_marker: str | None = None

    @property
    def state_id(self) -> str:
        return extract_state_id(self.header)

    @property
    def assignments(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in self.body:
            assignment = parse_assignment(line)
            if assignment:
                variable, value = assignment
                result[variable] = value
        return result

    def render(self) -> list[str]:
        lines: list[str] = []
        if self.loop_marker:
            lines.append(self.loop_marker)
        lines.append(self.header)
        lines.extend(self.body)
        return lines


@dataclass
class CompressionStats:
    counterexamples: int = 0
    raw_states: int = 0
    retained_states: int = 0
    folded_states: int = 0

    @property
    def state_block_reduction_rate(self) -> float:
        if self.raw_states == 0:
            return 0.0
        return self.folded_states / self.raw_states * 100.0

    def add(self, other: "CompressionStats") -> None:
        self.counterexamples += other.counterexamples
        self.raw_states += other.raw_states
        self.retained_states += other.retained_states
        self.folded_states += other.folded_states


def extract_formula_variables(spec: str) -> list[str]:
    """Return referenced hierarchical variables in first-occurrence order."""
    variables: list[str] = []
    seen: set[str] = set()
    for match in FORMULA_VARIABLE_RE.finditer(spec):
        variable = match.group(0)
        if variable not in seen:
            variables.append(variable)
            seen.add(variable)
    return variables


def count_next_operators(spec: str) -> int:
    """Conservatively obtain the largest relevant next-step neighbourhood."""
    return len(
        re.findall(
            r"(?<![A-Za-z0-9_])(?:AX|EX|X)(?![A-Za-z0-9_])",
            spec,
        )
    )


def parse_state_chunk(lines: list[str]) -> list[TraceStateBlock]:
    """Parse one counterexample state sequence and bind loop markers to states."""
    states: list[TraceStateBlock] = []
    current: TraceStateBlock | None = None
    pending_loop_marker: str | None = None
    pending_after_marker: list[str] = []

    for raw_line in lines:
        stripped = raw_line.strip()

        if stripped.startswith("-- Loop starts here"):
            pending_loop_marker = raw_line
            pending_after_marker = []
            continue

        if stripped.startswith("-> State:"):
            if current is not None:
                states.append(current)
            current = TraceStateBlock(
                header=raw_line,
                loop_marker=pending_loop_marker,
            )
            if pending_after_marker:
                current.body.extend(pending_after_marker)
            pending_loop_marker = None
            pending_after_marker = []
            continue

        if pending_loop_marker is not None:
            pending_after_marker.append(raw_line)
        elif current is not None:
            current.body.append(raw_line)

    if current is not None:
        if pending_loop_marker is not None:
            current.body.append(pending_loop_marker)
            current.body.extend(pending_after_marker)
        states.append(current)

    return states


def is_auxiliary_variable(
    variable: str,
    extra_foldable_variables: set[str],
) -> bool:
    """Variables allowed inside a foldable waiting/bus-idle state."""
    return (
        variable == "timer"
        or variable.endswith(".timer")
        or variable in extra_foldable_variables
    )


def state_is_fold_candidate(
    state: TraceStateBlock,
    extra_foldable_variables: set[str],
) -> bool:
    """
    A state is foldable only when it contains no observable business update.

    Empty delta states are stuttering candidates.  Input blocks, loop entries,
    event-validity changes and every non-timer/non-whitelisted assignment are
    protected.
    """
    if state.loop_marker:
        return False
    if any(line.strip().startswith("-> Input:") for line in state.body):
        return False

    assignments = state.assignments
    if not assignments:
        return True

    return all(
        is_auxiliary_variable(variable, extra_foldable_variables)
        for variable in assignments
    )


def compress_state_sequence(
    states: list[TraceStateBlock],
    spec: str,
    minimum_run: int,
    extra_foldable_variables: set[str],
) -> tuple[list[str], CompressionStats]:
    """Compress one trace while preserving formula and lasso evidence."""
    stats = CompressionStats(counterexamples=1, raw_states=len(states))
    if not states:
        return [], stats

    formula_variables = set(extract_formula_variables(spec))
    next_radius = max(1, count_next_operators(spec))
    protected: set[int] = {0, len(states) - 1}
    evidence_indices: set[int] = set()

    for index, state in enumerate(states):
        changed_variables = set(state.assignments)
        if state.loop_marker:
            evidence_indices.add(index)
        if changed_variables & formula_variables:
            evidence_indices.add(index)
        if any(variable.endswith("_valid") for variable in changed_variables):
            evidence_indices.add(index)
        if any(line.strip().startswith("-> Input:") for line in state.body):
            evidence_indices.add(index)

    for evidence_index in evidence_indices:
        for offset in range(-next_radius, next_radius + 1):
            neighbour = evidence_index + offset
            if 0 <= neighbour < len(states):
                protected.add(neighbour)

    candidates = [
        index not in protected
        and state_is_fold_candidate(state, extra_foldable_variables)
        for index, state in enumerate(states)
    ]

    output: list[str] = []
    index = 0

    while index < len(states):
        if not candidates[index]:
            output.extend(states[index].render())
            stats.retained_states += 1
            index += 1
            continue

        run_start = index
        while index < len(states) and candidates[index]:
            index += 1
        run_end = index - 1
        run_length = run_end - run_start + 1

        if run_length < minimum_run:
            for state_index in range(run_start, run_end + 1):
                output.extend(states[state_index].render())
                stats.retained_states += 1
            continue

        # Keep both boundaries of the waiting segment; remove only its interior.
        output.extend(states[run_start].render())
        stats.retained_states += 1

        hidden_start = states[run_start + 1].state_id
        hidden_end = states[run_end - 1].state_id
        skipped = max(0, run_length - 2)

        if skipped:
            output.append(
                "    ... [已折叠 "
                f"{skipped} 步纯计时器等待或总线空转状态] ...\n"
            )
            output.append(
                "    ... [隐藏的状态区间: "
                f"{hidden_start} 到 {hidden_end}] ...\n"
            )
            stats.folded_states += skipped

        if run_end != run_start:
            output.extend(states[run_end].render())
            stats.retained_states += 1

    # A run of one cannot be folded; keep accounting exact defensively.
    stats.retained_states = stats.raw_states - stats.folded_states
    return output, stats


def compress_nuxmv_output(
    input_file: str | Path,
    output_file: str | Path | None = None,
    minimum_run: int = 3,
    extra_foldable_variables: set[str] | None = None,
    coverage_catalog: TriggerCoverageCatalog | None = None,
) -> tuple[Path, CompressionStats]:
    """
    Reduce every false-property counterexample independently and save UTF-8.

    True-property output, nuXmv banners and trace metadata remain unchanged.
    """
    input_path = Path(input_file)
    if not input_path.exists():
        raise FileNotFoundError(f"找不到 nuXmv 输出文件: {input_path}")
    if minimum_run < 3:
        raise ValueError("minimum_run 至少应为 3，才能保留折叠区间两端。")

    output_path = (
        Path(output_file)
        if output_file
        else input_path.with_name(f"{input_path.stem}_compressed.txt")
    )
    foldable_variables = set(extra_foldable_variables or {"CBM.state"})
    lines = read_lines_with_fallback(input_path)
    output_lines: list[str] = []
    total_stats = CompressionStats()

    active_failed_spec: str | None = None
    index = 0

    while index < len(lines):
        stripped = lines[index].strip()

        if SPECIFICATION_PREFIX_RE.match(stripped):
            failed_spec = extract_failed_spec(stripped)
            if failed_spec and is_trigger_coverage_result(
                failed_spec,
                coverage_catalog,
            ):
                active_failed_spec = None
            else:
                active_failed_spec = failed_spec
            output_lines.append(lines[index])
            index += 1
            continue

        if (
            active_failed_spec
            and stripped.startswith("Trace Type: Counterexample")
        ):
            output_lines.append(lines[index])
            index += 1

            # Preserve any trace preamble until the first State block.
            while index < len(lines):
                next_stripped = lines[index].strip()
                if next_stripped.startswith("-> State:"):
                    break
                if SPECIFICATION_PREFIX_RE.match(next_stripped):
                    break
                output_lines.append(lines[index])
                index += 1

            if index >= len(lines) or SPECIFICATION_PREFIX_RE.match(
                lines[index].strip()
            ):
                continue

            trace_end = index
            while trace_end < len(lines):
                if SPECIFICATION_PREFIX_RE.match(lines[trace_end].strip()):
                    break
                trace_end += 1

            states = parse_state_chunk(lines[index:trace_end])
            compressed_lines, trace_stats = compress_state_sequence(
                states,
                active_failed_spec,
                minimum_run,
                foldable_variables,
            )
            output_lines.extend(compressed_lines)
            total_stats.add(trace_stats)
            index = trace_end
            active_failed_spec = None
            continue

        output_lines.append(lines[index])
        index += 1

    write_utf8(output_path, output_lines)
    return output_path, total_stats


# ---------------------------------------------------------------------------
# Parse compressed counterexamples and reconstruct delta states
# ---------------------------------------------------------------------------
def parse_trace_report(
    trace_file: str | Path,
    coverage_catalog: TriggerCoverageCatalog | None = None,
) -> list[dict[str, object]]:
    """Extract false specifications and compressed counterexample lines."""
    trace_path = Path(trace_file)
    if not trace_path.exists():
        raise FileNotFoundError(f"找不到反例报告文件: {trace_path}")

    traces: list[dict[str, object]] = []
    current_spec: str | None = None
    current_trace: list[str] = []
    is_in_trace = False

    def save_current_trace() -> None:
        nonlocal current_spec, current_trace
        if current_spec and current_trace:
            traces.append({"spec": current_spec, "trace": current_trace[:]})

    for raw_line in read_lines_with_fallback(trace_path):
        line = raw_line.strip()

        if SPECIFICATION_PREFIX_RE.match(line):
            save_current_trace()
            failed_spec = extract_failed_spec(line)
            if failed_spec and is_trigger_coverage_result(
                failed_spec,
                coverage_catalog,
            ):
                current_spec = None
            else:
                current_spec = failed_spec
            current_trace = []
            is_in_trace = False
            continue

        if current_spec is None:
            continue
        if line.startswith("Trace Type: Counterexample"):
            is_in_trace = True
            continue
        if not is_in_trace:
            continue

        if (
            line.startswith("-> State:")
            or line.startswith("-> Input:")
            or line.startswith("-- Loop starts here")
            or is_assignment_line(line)
            or is_fold_summary_line(line)
        ):
            current_trace.append(line)

    save_current_trace()
    return traces


@dataclass
class ReconstructedState:
    state_id: str
    values: dict[str, str]
    deltas: dict[str, str]
    loop_start: bool = False


def reconstruct_trace_states(trace: list[str]) -> list[ReconstructedState]:
    """Expand nuXmv's delta notation into cumulative state valuations."""
    state_deltas: list[tuple[str, dict[str, str], bool]] = []
    current_id: str | None = None
    current_deltas: dict[str, str] = {}
    pending_loop_start = False
    current_loop_start = False

    def finish_state() -> None:
        nonlocal current_id, current_deltas, current_loop_start
        if current_id is not None:
            state_deltas.append(
                (current_id, current_deltas.copy(), current_loop_start)
            )
        current_id = None
        current_deltas = {}
        current_loop_start = False

    for line in trace:
        if line.startswith("-- Loop starts here"):
            # nuXmv prints the marker immediately before the loop-entry state.
            pending_loop_start = True
            continue
        if line.startswith("-> State:"):
            finish_state()
            current_id = extract_state_id(line)
            current_loop_start = pending_loop_start
            pending_loop_start = False
            continue
        if line.startswith("-> Input:") or is_fold_summary_line(line):
            continue

        assignment = parse_assignment(line)
        if assignment and current_id is not None:
            variable, value = assignment
            current_deltas[variable] = value

    finish_state()

    reconstructed: list[ReconstructedState] = []
    cumulative_values: dict[str, str] = {}
    for state_id, deltas, loop_start in state_deltas:
        cumulative_values.update(deltas)
        reconstructed.append(
            ReconstructedState(
                state_id=state_id,
                values=cumulative_values.copy(),
                deltas=deltas,
                loop_start=loop_start,
            )
        )
    return reconstructed


# ---------------------------------------------------------------------------
# Lightweight evaluation for the supported generated formula shapes
# ---------------------------------------------------------------------------
def strip_outer_parentheses(expression: str) -> str:
    result = expression.strip()
    while result.startswith("(") and result.endswith(")"):
        depth = 0
        wraps_entire_expression = True
        for index, character in enumerate(result):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0 and index != len(result) - 1:
                    wraps_entire_expression = False
                    break
            if depth < 0:
                wraps_entire_expression = False
                break
        if not wraps_entire_expression or depth != 0:
            break
        result = result[1:-1].strip()
    return result


def split_top_level(
    expression: str,
    operator: str,
) -> tuple[str, str] | None:
    depth = 0
    index = 0
    while index <= len(expression) - len(operator):
        character = expression[index]
        if character == "(":
            depth += 1
            index += 1
            continue
        if character == ")":
            depth -= 1
            index += 1
            continue
        if depth == 0 and expression.startswith(operator, index):
            return (
                expression[:index].strip(),
                expression[index + len(operator):].strip(),
            )
        index += 1
    return None


def split_top_level_word(
    expression: str,
    operator: str,
) -> tuple[str, str] | None:
    depth = 0
    for index, character in enumerate(expression):
        if character == "(":
            depth += 1
            continue
        if character == ")":
            depth -= 1
            continue
        if depth != 0 or not expression.startswith(operator, index):
            continue

        before = expression[index - 1] if index > 0 else " "
        after_index = index + len(operator)
        after = expression[after_index] if after_index < len(expression) else " "
        if not (before.isalnum() or before == "_") and not (
            after.isalnum() or after == "_"
        ):
            return (
                expression[:index].strip(),
                expression[after_index:].strip(),
            )
    return None


def compare_values(left: str, operator: str, right: str) -> bool | None:
    left_value = left.strip()
    right_value = right.strip()

    try:
        left_number = float(left_value)
        right_number = float(right_value)
        if operator == "=":
            return left_number == right_number
        if operator == "!=":
            return left_number != right_number
        if operator == "<":
            return left_number < right_number
        if operator == ">":
            return left_number > right_number
        if operator == "<=":
            return left_number <= right_number
        if operator == ">=":
            return left_number >= right_number
    except ValueError:
        pass

    if operator not in {"=", "!="}:
        return None
    left_normalized = left_value.upper() if left_value.upper() in {
        "TRUE",
        "FALSE",
    } else left_value
    right_normalized = right_value.upper() if right_value.upper() in {
        "TRUE",
        "FALSE",
    } else right_value
    equal = left_normalized == right_normalized
    return equal if operator == "=" else not equal


def evaluate_propositional(
    expression: str,
    values: dict[str, str],
) -> bool | None:
    """Evaluate the Boolean/comparison subset used in generated APs."""
    expr = strip_outer_parentheses(expression)
    if not expr:
        return None

    implication = split_top_level(expr, "->")
    if implication:
        left, right = implication
        left_result = evaluate_propositional(left, values)
        right_result = evaluate_propositional(right, values)
        if left_result is False or right_result is True:
            return True
        if left_result is True and right_result is False:
            return False
        return None

    disjunction = split_top_level(expr, "|")
    if disjunction:
        left, right = disjunction
        left_result = evaluate_propositional(left, values)
        right_result = evaluate_propositional(right, values)
        if left_result is True or right_result is True:
            return True
        if left_result is False and right_result is False:
            return False
        return None

    conjunction = split_top_level(expr, "&")
    if conjunction:
        left, right = conjunction
        left_result = evaluate_propositional(left, values)
        right_result = evaluate_propositional(right, values)
        if left_result is False or right_result is False:
            return False
        if left_result is True and right_result is True:
            return True
        return None

    if expr.startswith("!") and not expr.startswith("!="):
        result = evaluate_propositional(expr[1:].strip(), values)
        return None if result is None else not result

    if expr.upper() == "TRUE":
        return True
    if expr.upper() == "FALSE":
        return False

    atomic_match = re.fullmatch(
        r"([A-Za-z_][A-Za-z0-9_.$\[\]-]*)\s*"
        r"(<=|>=|!=|=|<|>)\s*"
        r"([A-Za-z_][A-Za-z0-9_.$\[\]-]*|-?\d+(?:\.\d+)?)",
        expr,
    )
    if not atomic_match:
        return None

    left_name, operator, right_token = atomic_match.groups()
    if left_name not in values:
        return None
    right_value = values.get(right_token, right_token)
    return compare_values(values[left_name], operator, right_value)


def consume_prefix_operator(
    expression: str,
    operators: tuple[str, ...],
) -> tuple[str | None, str]:
    expr = strip_outer_parentheses(expression)
    for operator in sorted(operators, key=len, reverse=True):
        match = re.match(
            rf"^{re.escape(operator)}(?![A-Za-z0-9_])",
            expr,
        )
        if match:
            return operator, strip_outer_parentheses(expr[match.end():])
    return None, expr


def consume_next_chain(expression: str) -> tuple[int, str]:
    count = 0
    remainder = expression
    while True:
        operator, next_remainder = consume_prefix_operator(
            remainder,
            ("AX", "EX", "X"),
        )
        if operator is None:
            return count, strip_outer_parentheses(remainder)
        count += 1
        remainder = next_remainder


def find_loop_index(states: list[ReconstructedState]) -> int:
    for index, state in enumerate(states):
        if state.loop_start:
            return index
    return max(0, len(states) - 1)


def find_key_state_indices(
    spec: str,
    states: list[ReconstructedState],
) -> list[tuple[int, str]]:
    """
    Locate evidence for the formula shapes generated by the current toolchain.

    This is a witness extractor, not a general CTL/LTL model checker.  nuXmv
    remains responsible for truth evaluation.
    """
    if not states:
        return []

    normalized = re.sub(
        r"^(?:LTLSPEC|SPEC)\s+",
        "",
        spec.strip().rstrip(";"),
        flags=re.IGNORECASE,
    )
    global_operator, body = consume_prefix_operator(normalized, ("AG", "G"))
    loop_index = find_loop_index(states)

    if global_operator:
        implication = split_top_level(body, "->")
        if implication:
            antecedent, consequent = implication
            consequent = strip_outer_parentheses(consequent)

            next_count, next_target = consume_next_chain(consequent)
            if next_count > 0:
                for index in range(0, len(states) - next_count):
                    if evaluate_propositional(
                        antecedent,
                        states[index].values,
                    ) is not True:
                        continue
                    target_index = index + next_count
                    if evaluate_propositional(
                        next_target,
                        states[target_index].values,
                    ) is False:
                        return [
                            (index, "触发状态"),
                            (target_index, "响应检查状态"),
                        ]

            eventual_operator, eventual_target = consume_prefix_operator(
                consequent,
                ("AF", "EF", "F"),
            )
            if eventual_operator:
                for index, state in enumerate(states):
                    if evaluate_propositional(
                        antecedent,
                        state.values,
                    ) is not True:
                        continue
                    future_results = [
                        evaluate_propositional(eventual_target, item.values)
                        for item in states[index:]
                    ]
                    if not any(result is True for result in future_results):
                        result = [(index, "触发状态")]
                        if loop_index != index:
                            result.append((loop_index, "循环入口/未实现响应"))
                        return result

            until_parts = split_top_level_word(consequent, "U")
            if until_parts:
                hold_condition, target_condition = until_parts
                for index, state in enumerate(states):
                    if evaluate_propositional(
                        antecedent,
                        state.values,
                    ) is not True:
                        continue

                    target_seen = False
                    for later_index in range(index, len(states)):
                        later_values = states[later_index].values
                        if evaluate_propositional(
                            target_condition,
                            later_values,
                        ) is True:
                            target_seen = True
                            break
                        if evaluate_propositional(
                            hold_condition,
                            later_values,
                        ) is False:
                            return [
                                (index, "持续条件触发状态"),
                                (later_index, "持续条件破坏状态"),
                            ]

                    if not target_seen:
                        result = [(index, "持续条件触发状态")]
                        if loop_index != index:
                            result.append((loop_index, "循环入口/目标未发生"))
                        return result

            # Immediate invariant: G(P -> Q)
            if not re.search(
                r"(?<![A-Za-z0-9_])(?:AX|EX|X|AF|EF|F|U)"
                r"(?![A-Za-z0-9_])",
                consequent,
            ):
                for index, state in enumerate(states):
                    if (
                        evaluate_propositional(antecedent, state.values) is True
                        and evaluate_propositional(consequent, state.values)
                        is False
                    ):
                        return [(index, "违反不变量的状态")]

        # Safety formula such as G !(P & Q).
        for index, state in enumerate(states):
            if evaluate_propositional(body, state.values) is False:
                return [(index, "禁止组合出现状态")]

    eventual_operator, eventual_target = consume_prefix_operator(
        normalized,
        ("AF", "EF", "F"),
    )
    if eventual_operator:
        return [(loop_index, "循环入口/目标状态未到达")]

    # Conservative fallback: use formula-variable changes and the loop entry.
    referenced = set(extract_formula_variables(spec))
    changed_indices = [
        index
        for index, state in enumerate(states)
        if set(state.deltas) & referenced
    ]
    if changed_indices:
        key_index = changed_indices[-1]
        result = [(key_index, "规约相关变量变化状态")]
        if loop_index != key_index:
            result.append((loop_index, "循环入口/反例末端"))
        return result
    return [(loop_index, "循环入口/反例末端")]


def format_reconstructed_fragment(
    spec: str,
    trace: list[str],
) -> list[str]:
    states = reconstruct_trace_states(trace)
    selected = find_key_state_indices(spec, states)
    variables = extract_formula_variables(spec)

    if not states or not selected:
        return ["    未能从反例中重建关键状态。"]

    lines: list[str] = []
    emitted_indices: set[int] = set()
    for state_index, label in selected:
        if state_index in emitted_indices or not 0 <= state_index < len(states):
            continue
        emitted_indices.add(state_index)
        state = states[state_index]
        loop_note = "；Loop starts here" if state.loop_start else ""
        lines.append(
            f"    -> State: {state.state_id} <- [{label}{loop_note}]"
        )

        emitted_variable = False
        for variable in variables:
            if variable in state.values:
                lines.append(f"       {variable} = {state.values[variable]}")
                emitted_variable = True

        if not emitted_variable:
            lines.append("       未找到该规约引用变量的显式或继承取值。")

    return lines


# ---------------------------------------------------------------------------
# Rule-driven diagnosis and report generation
# ---------------------------------------------------------------------------
def contains_temporal_operator(spec: str, *operators: str) -> bool:
    for operator in operators:
        if re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(operator)}"
            rf"(?![A-Za-z0-9_])",
            spec,
        ):
            return True
    return False


PATTERN_TO_VIOLATION = {
    "当前状态一致性": "一致性违规",
    "一致性约束": "一致性违规",
    "固定步响应": "因果响应违规",
    "最终响应": "因果响应违规",
    "无界最终响应": "因果响应违规",
    "因果流转响应": "因果响应违规",
    "状态持续（强直到）": "状态持续性违规",
    "状态持续约束": "状态持续性违规",
    "互斥约束": "互斥安全性违规",
    "互斥安全性": "互斥安全性违规",
    "最终可达性": "最终可达性违规",
}

VIOLATION_EXPLANATIONS = {
    "一致性违规": (
        "触发条件成立时，目标状态或变量约束未能同时满足。"
    ),
    "因果响应违规": (
        "触发条件成立后，受控组件未在规定逻辑步或后续路径中"
        "产生预期响应。"
    ),
    "状态持续性违规": (
        "目标条件未最终发生，或者持续条件未保持至目标条件成立。"
    ),
    "互斥安全性违规": "反例中出现了规约禁止的状态或变量组合。",
    "最终可达性违规": (
        "反例的有限前缀及循环后缀中未到达目标状态。"
    ),
}


@dataclass(frozen=True)
class ViolationClassification:
    """Auditable classification from provenance and formula structure."""

    category: str
    source_category: str | None
    formula_category: str | None
    formula_shape: str
    basis: str
    consistency: str
    warnings: tuple[str, ...] = ()


def normalize_pattern_type(pattern_type: str) -> str:
    """Normalize harmless typography differences in generated metadata."""
    normalized = re.sub(r"\s+", "", pattern_type.strip())
    return normalized.replace("(", "（").replace(")", "）")


def classify_requirement_pattern(pattern_type: str) -> str | None:
    """Map one supported requirement pattern to its violation category."""
    return PATTERN_TO_VIOLATION.get(normalize_pattern_type(pattern_type))


def infer_formula_violation(spec: str) -> tuple[str | None, str]:
    """
    Infer a category from the restricted formula shapes generated in Section 4.

    The result is used as a consistency check when provenance is available and
    only as a fallback when no source requirement can be recovered.  It is not
    a general CTL/LTL semantic classifier.
    """
    normalized = re.sub(
        r"^(?:LTLSPEC|CTLSPEC|SPEC)\s+",
        "",
        spec.strip().rstrip(";"),
        flags=re.IGNORECASE,
    )
    global_operator, body = consume_prefix_operator(normalized, ("AG", "G"))

    if global_operator:
        implication = split_top_level(body, "->")
        if implication:
            _, consequent = implication
            consequent = strip_outer_parentheses(consequent)

            if split_top_level_word(consequent, "U"):
                return "状态持续性违规", "G(P -> (H U Q))"

            next_count, _ = consume_next_chain(consequent)
            if next_count > 0:
                return "因果响应违规", f"{global_operator}(P -> X^{next_count} Q)"

            eventual_operator, _ = consume_prefix_operator(
                consequent,
                ("AF", "EF", "F"),
            )
            if eventual_operator:
                return "因果响应违规", f"{global_operator}(P -> F Q)"

            if not contains_temporal_operator(
                consequent,
                "AX",
                "EX",
                "X",
                "AF",
                "EF",
                "F",
                "U",
            ):
                # AG(P -> Q) is the n=0 form of the paper's fixed-step CTL
                # template; G(P -> Q) is the current-state LTL invariant.
                if global_operator == "AG":
                    return "因果响应违规", "AG(P -> Q), n=0"
                return "一致性违规", "G(P -> Q)"

        safety_body = strip_outer_parentheses(body)
        if safety_body.startswith("!"):
            prohibited = strip_outer_parentheses(safety_body[1:])
            if split_top_level(prohibited, "&"):
                return "互斥安全性违规", "G(!(P & Q))"

    eventual_operator, _ = consume_prefix_operator(
        normalized,
        ("AF", "EF", "F"),
    )
    if eventual_operator:
        return "最终可达性违规", f"{eventual_operator}(Q)"

    return None, "未识别的受限公式结构"


def classify_violation(
    spec: str,
    source_records: list[RequirementSpecRecord],
) -> ViolationClassification:
    """Combine provenance-first classification with a formula cross-check."""
    formula_category, formula_shape = infer_formula_violation(spec)
    warnings: list[str] = []

    recognized_source_categories: set[str] = set()
    for record in source_records:
        category = classify_requirement_pattern(record.pattern_type)
        if category is None:
            warnings.append(
                "未识别来源需求模式 "
                f"{record.pattern_type!r}（{record.requirement_id}）。"
            )
        else:
            recognized_source_categories.add(category)

    if len(recognized_source_categories) > 1:
        categories = "、".join(sorted(recognized_source_categories))
        warnings.append(f"同一规约的来源记录给出了冲突分类：{categories}。")
        return ViolationClassification(
            category="待人工复核",
            source_category=categories,
            formula_category=formula_category,
            formula_shape=formula_shape,
            basis="来源需求模式与公式结构（存在冲突）",
            consistency="不一致",
            warnings=tuple(warnings),
        )

    source_category = next(iter(recognized_source_categories), None)
    if source_category is not None:
        if formula_category is None:
            warnings.append("公式结构未被受限结构分类器识别。")
            return ViolationClassification(
                category=source_category,
                source_category=source_category,
                formula_category=None,
                formula_shape=formula_shape,
                basis="来源需求模式",
                consistency="公式结构未识别",
                warnings=tuple(warnings),
            )
        if source_category != formula_category:
            warnings.append(
                "来源需求模式与公式结构的分类不一致："
                f"{source_category} / {formula_category}。"
            )
            return ViolationClassification(
                category="待人工复核",
                source_category=source_category,
                formula_category=formula_category,
                formula_shape=formula_shape,
                basis="来源需求模式与公式结构（存在冲突）",
                consistency="不一致",
                warnings=tuple(warnings),
            )
        return ViolationClassification(
            category=source_category,
            source_category=source_category,
            formula_category=formula_category,
            formula_shape=formula_shape,
            basis="来源需求模式与公式结构",
            consistency="一致",
            warnings=tuple(warnings),
        )

    if formula_category is not None:
        if not source_records:
            warnings.append("未找到来源需求记录，已回退为公式结构分类。")
        return ViolationClassification(
            category=formula_category,
            source_category=None,
            formula_category=formula_category,
            formula_shape=formula_shape,
            basis="公式结构回退",
            consistency="无法执行来源交叉检查",
            warnings=tuple(warnings),
        )

    warnings.append("来源需求模式和公式结构均不足以确定违规类型。")
    return ViolationClassification(
        category="待人工复核",
        source_category=None,
        formula_category=None,
        formula_shape=formula_shape,
        basis="未分类",
        consistency="无法判断",
        warnings=tuple(warnings),
    )


def diagnose_failure(
    spec: str,
    trace: list[str],
    smv_mapping: dict[str, str],
    source_records: list[RequirementSpecRecord],
) -> str:
    diagnosis: list[str] = []

    instances = sorted(
        set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\.", spec))
    )
    involved_components: list[str] = []
    for instance in instances:
        module_name = smv_mapping.get(instance)
        if module_name:
            involved_components.append(
                f"【{module_name}】(实例: {instance})"
            )
        else:
            involved_components.append(
                f"【未解析模块类型】(实例: {instance})"
            )

    if involved_components:
        diagnosis.append(
            "[*] 失效规约涉及组件: " + ", ".join(involved_components)
        )
    else:
        diagnosis.append(
            "[*] 失效规约涉及组件: 未从公式中识别到层级实例标识"
        )

    diagnosis.append(
        "[*] 关键反例状态片段 "
        "(Reconstructed Witness Fragment):"
    )
    diagnosis.extend(format_reconstructed_fragment(spec, trace))

    classification = classify_violation(spec, source_records)
    diagnosis.append("[*] 违规分类 (Violation Classification):")
    diagnosis.append(
        "    来源模式分类: "
        f"{classification.source_category or '未获得'}"
    )
    diagnosis.append(
        "    公式结构: "
        f"{classification.formula_shape}"
    )
    diagnosis.append(
        "    公式结构分类: "
        f"{classification.formula_category or '未识别'}"
    )
    diagnosis.append(f"    分类依据: {classification.basis}")
    diagnosis.append(f"    一致性检查: {classification.consistency}")
    diagnosis.append(f"    -> [{classification.category}]")

    explanation = VIOLATION_EXPLANATIONS.get(classification.category)
    if explanation:
        diagnosis.append(f"       {explanation}")
    for warning in classification.warnings:
        diagnosis.append(f"    [!] 分类警告: {warning}")

    return "\n".join(diagnosis)


def write_diagnosis_report(
    compressed_trace_file: str | Path,
    model_file: str | Path,
    requirement_spec_file: str | Path,
    output_file: str | Path,
    compression_stats: CompressionStats,
    coverage_catalog: TriggerCoverageCatalog | None = None,
) -> tuple[Path, int]:
    """Generate the original report fields plus reconstructed witness states."""
    output_path = Path(output_file)
    smv_mapping = parse_smv_model(model_file)
    requirement_index = parse_requirement_spec_index(requirement_spec_file)
    if coverage_catalog is None:
        coverage_catalog = parse_trigger_coverage_catalog(
            requirement_spec_file
        )
    coverage_statuses = parse_trigger_coverage_results(
        compressed_trace_file,
        coverage_catalog,
    )
    traces = parse_trace_report(compressed_trace_file, coverage_catalog)

    report_lines = [
        "==================================================",
        "        nuXmv 反例自动追溯与诊断报告",
        "==================================================",
        "",
        "[*] 反例折叠统计 (Counterexample Reduction Statistics):",
        f"    反例数量: {compression_stats.counterexamples}",
        f"    原始状态块: {compression_stats.raw_states}",
        f"    保留状态块: {compression_stats.retained_states}",
        f"    折叠状态块: {compression_stats.folded_states}",
        "    状态块压缩率: "
        f"{compression_stats.state_block_reduction_rate:.2f}%",
        "",
    ]
    report_lines.extend(
        format_trigger_coverage_summary(
            coverage_catalog,
            coverage_statuses,
        )
    )

    if not traces:
        report_lines.extend(
            ["[+] 未发现验证结果为 False 的规约及其反例。", ""]
        )
        write_utf8(output_path, report_lines)
        return output_path, 0

    for counterexample_index, item in enumerate(traces, start=1):
        spec = str(item["spec"])
        trace = list(item["trace"])
        source_records = find_requirement_sources(spec, requirement_index)
        report_lines.extend(
            [
                "--------------------------------------------------",
                f"【反例 #{counterexample_index}】",
                f"失败的规范 (Failed Spec): {spec}",
                "",
                format_requirement_trace(source_records),
                "",
                "[*] 压缩反例轨迹 (Compressed Counterexample Trace):",
            ]
        )
        report_lines.extend(f"    {line}" for line in trace)
        report_lines.extend(
            [
                "",
                diagnose_failure(
                    spec,
                    trace,
                    smv_mapping,
                    source_records,
                ),
                "",
            ]
        )

    write_utf8(output_path, report_lines)
    return output_path, len(traces)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "先折叠 nuXmv 反例，再追溯来源需求与组件实例并生成诊断报告。"
        )
    )
    parser.add_argument(
        "result",
        nargs="?",
        default=str(DEFAULT_RESULT_FILE),
        help="nuXmv 原始输出文件。",
    )
    parser.add_argument(
        "--model",
        default=str(DEFAULT_MODEL_FILE),
        help="包含 MODULE main 的综合 NuXmv 模型。",
    )
    parser.add_argument(
        "--requirements",
        default=str(DEFAULT_REQUIREMENT_SPEC_FILE),
        help="带需求编号和模式类型的 CTL/LTL 生成结果文件。",
    )
    parser.add_argument(
        "--compressed-output",
        help="折叠日志输出路径；默认在原文件名后添加 _compressed。",
    )
    parser.add_argument(
        "--report-output",
        help="追溯报告输出路径；默认在原文件名后添加 _Trace_diagnosis。",
    )
    parser.add_argument(
        "--minimum-run",
        type=int,
        default=3,
        help="开始折叠的连续候选状态块数，默认 3。",
    )
    parser.add_argument(
        "--fold-variable",
        action="append",
        default=None,
        help=(
            "额外允许折叠的变量，可重复指定；默认保留原实现中的 CBM.state。"
        ),
    )
    return parser


def main() -> int:
    args = build_argument_parser().parse_args()
    result_path = Path(args.result)
    compressed_path = (
        Path(args.compressed_output)
        if args.compressed_output
        else result_path.with_name(f"{result_path.stem}_compressed.txt")
    )
    report_path = (
        Path(args.report_output)
        if args.report_output
        else result_path.with_name(
            f"{result_path.stem}_Trace_diagnosis.txt"
        )
    )
    extra_foldable = {"CBM.state"}
    if args.fold_variable:
        extra_foldable.update(args.fold_variable)

    try:
        coverage_catalog = parse_trigger_coverage_catalog(args.requirements)
        print(
            "[*] 已载入触发可达性检查: "
            f"{len(coverage_catalog.checks)} 条。"
        )
        print(f"[*] 1. 正在读取并折叠 nuXmv 输出: {result_path}")
        compressed_path, stats = compress_nuxmv_output(
            result_path,
            compressed_path,
            minimum_run=args.minimum_run,
            extra_foldable_variables=extra_foldable,
            coverage_catalog=coverage_catalog,
        )
        print(f"[+] 折叠日志已保存: {compressed_path}")
        print(
            "[*] 状态块统计: "
            f"{stats.raw_states} -> {stats.retained_states}，"
            f"折叠 {stats.folded_states}，"
            f"压缩率 {stats.state_block_reduction_rate:.2f}%"
        )

        print("[*] 2. 正在建立需求—规约与实例—模块索引...")
        print("[*] 3. 正在重建状态取值并生成追溯诊断报告...")
        report_path, trace_count = write_diagnosis_report(
            compressed_path,
            args.model,
            args.requirements,
            report_path,
            stats,
            coverage_catalog,
        )
        print(f"[+] 共处理 {trace_count} 个反例。")
        print(f"[+] 追溯诊断报告已保存: {report_path}")
        return 0
    except (FileNotFoundError, ValueError, OSError) as error:
        print(f"[!] 处理失败: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())





