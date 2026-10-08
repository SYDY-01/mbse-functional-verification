# -*- coding: utf-8 -*-
"""Regression tests for ``reduce_and_trace0.py``.

The file can be executed directly with an IDE's ``Run Python File`` action,
or from the directory containing both Python files:

    python -m unittest -v test_reduce_and_trace.py

The unit tests are self-contained.  The FMCS integration tests automatically
look for FI model/result fixtures in ``TestWrong`` relative to this file or the
project working directory.  ``FMCS_TRACE_TEST_DATA`` may override that folder.
The requirement specification is searched independently because it may be in
the project root, ``TestWrong``, or ``FMCS``.  Both the paper-project filename
``FMCS_时序逻辑结果.smv`` and the exported English filename are supported;
``FMCS_TRACE_REQUIREMENTS`` may override the complete path.
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path

try:
    import reduce_and_trace as trace_tool
except ModuleNotFoundError as import_error:
    # Windows may append ``_2`` when a revised file is downloaded beside an
    # older copy.  Keep right-click execution usable, while retaining the
    # canonical ``reduce_and_trace0.py`` name as the first choice.
    if import_error.name != "reduce_and_trace":
        raise
    try:
        from old import reduce_and_trace_2 as trace_tool
    except ModuleNotFoundError as fallback_error:
        if fallback_error.name != "reduce_and_trace_2":
            raise
        raise ModuleNotFoundError(
            "未找到追溯实现文件。请将 reduce_and_trace.py（推荐）或 "
            "reduce_and_trace_2.py 与本测试文件放在同一目录。"
        ) from fallback_error


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
FMCS_FAULT_FIXTURE_NAMES = (
    "input_FMCS_FI_01_Result.smv",
    "input_FMCS_FI_01_Result.txt",
    "input_FMCS_FI_02_Result.smv",
    "input_FMCS_FI_02_Result.txt",
    "input_FMCS_FI_03_Result.smv",
    "input_FMCS_FI_03_Result.txt",
    "input_FMCS_FI_04_Result.smv",
    "input_FMCS_FI_04_Result.txt",
    "input_FMCS_FI_05_Result.smv",
    "input_FMCS_FI_05_Result.txt",
)
FMCS_REQUIREMENT_SPECIFICATION_NAMES = (
    "FMCS_时序逻辑结果.smv",
    "FMCS_CTL_and_LTL_Specifications.smv",
)


def locate_fmcs_fault_directory() -> Path | None:
    """Locate the directory containing the five FI model/result pairs."""
    candidates: list[Path] = []
    configured = os.environ.get("FMCS_TRACE_TEST_DATA")
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        [
            SCRIPT_DIRECTORY / "TestWrong",
            SCRIPT_DIRECTORY.parent / "TestWrong",
            Path.cwd() / "TestWrong",
            SCRIPT_DIRECTORY,
            SCRIPT_DIRECTORY / "upload",
            SCRIPT_DIRECTORY.parent / "upload",
            Path.cwd(),
            Path.cwd() / "upload",
        ]
    )

    visited: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in visited:
            continue
        visited.add(resolved)
        if all(
            (resolved / name).is_file()
            for name in FMCS_FAULT_FIXTURE_NAMES
        ):
            return resolved
    return None


def locate_requirement_specification(
    fault_directory: Path | None,
) -> Path | None:
    """Locate the annotated 51-requirement/41-coverage specification file."""
    configured = os.environ.get("FMCS_TRACE_REQUIREMENTS")
    if configured:
        configured_path = Path(configured).expanduser().resolve()
        return configured_path if configured_path.is_file() else None

    directories: list[Path] = []
    if fault_directory is not None:
        directories.extend(
            [
                fault_directory,
                fault_directory.parent,
                fault_directory.parent / "FMCS",
            ]
        )
    directories.extend(
        [
            SCRIPT_DIRECTORY,
            SCRIPT_DIRECTORY / "TestWrong",
            SCRIPT_DIRECTORY / "FMCS",
            SCRIPT_DIRECTORY.parent,
            SCRIPT_DIRECTORY.parent / "upload",
            Path.cwd(),
            Path.cwd() / "TestWrong",
            Path.cwd() / "FMCS",
        ]
    )

    visited: set[Path] = set()
    for directory in directories:
        resolved_directory = directory.resolve()
        if resolved_directory in visited:
            continue
        visited.add(resolved_directory)
        for filename in FMCS_REQUIREMENT_SPECIFICATION_NAMES:
            candidate = resolved_directory / filename
            if candidate.is_file():
                return candidate
    return None


FMCS_FIXTURE_DIRECTORY = locate_fmcs_fault_directory()
FMCS_REQUIREMENT_FILE = locate_requirement_specification(
    FMCS_FIXTURE_DIRECTORY
)


class ViolationClassificationTests(unittest.TestCase):
    def test_supported_pattern_mapping(self) -> None:
        expected = {
            "当前状态一致性": "一致性违规",
            "固定步响应": "因果响应违规",
            "最终响应": "因果响应违规",
            "无界最终响应": "因果响应违规",
            "状态持续（强直到）": "状态持续性违规",
            "互斥约束": "互斥安全性违规",
            "最终可达性": "最终可达性违规",
        }
        for pattern, category in expected.items():
            with self.subTest(pattern=pattern):
                self.assertEqual(
                    trace_tool.classify_requirement_pattern(pattern),
                    category,
                )

    def test_supported_formula_shapes(self) -> None:
        cases = {
            "G (A.state = on -> A.value = 1)": "一致性违规",
            "AG (A.trigger = TRUE -> AX A.value = 1)": "因果响应违规",
            # A fixed-step response with n=0 checks Q in the current state.
            "AG (A.trigger = TRUE -> A.value = 1)": "因果响应违规",
            "G (A.trigger = TRUE -> F A.state = done)": "因果响应违规",
            "G (A.state = wait -> (A.state = wait U A.done = TRUE))": (
                "状态持续性违规"
            ),
            "G !(A.state = off & A.value = 18)": "互斥安全性违规",
            "F A.state = done": "最终可达性违规",
        }
        for formula, category in cases.items():
            with self.subTest(formula=formula):
                actual, shape = trace_tool.infer_formula_violation(formula)
                self.assertEqual(actual, category)
                self.assertTrue(shape)

    def test_provenance_and_formula_agree(self) -> None:
        formula = "G (A.trigger = TRUE -> F A.state = done)"
        source = trace_tool.RequirementSpecRecord(
            requirement_id="REQ-T-01",
            pattern_type="无界最终响应",
            logic_type="LTL",
            formula=f"LTLSPEC {formula};",
        )
        result = trace_tool.classify_violation(formula, [source])
        self.assertEqual(result.category, "因果响应违规")
        self.assertEqual(result.consistency, "一致")
        self.assertEqual(result.warnings, ())

    def test_formula_fallback_is_explicit(self) -> None:
        result = trace_tool.classify_violation("F A.state = done", [])
        self.assertEqual(result.category, "最终可达性违规")
        self.assertEqual(result.basis, "公式结构回退")
        self.assertTrue(any("未找到来源" in item for item in result.warnings))

    def test_pattern_formula_conflict_requires_review(self) -> None:
        source = trace_tool.RequirementSpecRecord(
            requirement_id="REQ-T-CONFLICT",
            pattern_type="最终可达性",
            logic_type="LTL",
            formula="LTLSPEC G (A.state = on -> A.value = 1);",
        )
        result = trace_tool.classify_violation(
            "G (A.state = on -> A.value = 1)",
            [source],
        )
        self.assertEqual(result.category, "待人工复核")
        self.assertEqual(result.consistency, "不一致")
        self.assertTrue(result.warnings)

    def test_multiple_sources_with_same_category_are_retained(self) -> None:
        formula = "G (A.trigger = TRUE -> F A.state = done)"
        sources = [
            trace_tool.RequirementSpecRecord(
                requirement_id="REQ-T-01",
                pattern_type="最终响应",
                logic_type="LTL",
                formula=f"LTLSPEC {formula};",
            ),
            trace_tool.RequirementSpecRecord(
                requirement_id="REQ-T-02",
                pattern_type="无界最终响应",
                logic_type="LTL",
                formula=f"LTLSPEC {formula};",
            ),
        ]
        result = trace_tool.classify_violation(formula, sources)
        self.assertEqual(result.category, "因果响应违规")
        self.assertEqual(result.consistency, "一致")


class TraceAndCoverageUnitTests(unittest.TestCase):
    def test_utf16_nuxmv_output_is_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.txt"
            expected = "-- specification F A.state = done is true\r\n"
            path.write_bytes(expected.encode("utf-16"))
            self.assertEqual(
                trace_tool.read_text_with_fallback(path),
                expected,
            )

    def test_false_coverage_property_is_not_a_formal_counterexample(self) -> None:
        requirement_text = """\
-- [REQ-T-01] 当前状态一致性 / LTL
LTLSPEC G ((A.state = on) -> (A.value = 1));

-- [TRIGGER-COVERAGE REQ-T-01] 当前状态一致性
-- 触发条件：A.state = on
CTLSPEC NAME COV_REQ_T_01 := EF (A.state = on);
"""
        result_text = """\
-- specification G (A.state = on -> A.value = 1) is false
Trace Type: Counterexample
-> State: 1.1 <-
  A.state = on
  A.value = 0
-- specification COV_REQ_T_01 := EF (A.state = on) is false
Trace Type: Counterexample
-> State: 2.1 <-
  A.state = off
  A.value = 0
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requirement_path = root / "requirements.smv"
            result_path = root / "result.txt"
            compressed_path = root / "compressed.txt"
            requirement_path.write_text(requirement_text, encoding="utf-8")
            result_path.write_text(result_text, encoding="utf-8")

            catalog = trace_tool.parse_trigger_coverage_catalog(
                requirement_path
            )
            output_path, stats = trace_tool.compress_nuxmv_output(
                result_path,
                compressed_path,
                coverage_catalog=catalog,
            )
            statuses = trace_tool.parse_trigger_coverage_results(
                output_path,
                catalog,
            )
            traces = trace_tool.parse_trace_report(output_path, catalog)

            self.assertEqual(len(catalog.checks), 1)
            self.assertEqual(statuses, {"COV_REQ_T_01": False})
            self.assertEqual(stats.counterexamples, 1)
            self.assertEqual(len(traces), 1)
            self.assertNotIn("COV_", str(traces[0]["spec"]))

    def test_incomplete_coverage_results_are_not_reported_as_all_reachable(
        self,
    ) -> None:
        catalog = trace_tool.TriggerCoverageCatalog()
        catalog.add(
            trace_tool.TriggerCoverageCheck(
                property_name="COV_REQ_T_01",
                requirement_id="REQ-T-01",
                pattern_type="当前状态一致性",
                condition="A.state = on",
                formula="EF (A.state = on)",
            )
        )
        summary = "\n".join(
            trace_tool.format_trigger_coverage_summary(catalog, {})
        )
        self.assertIn("已获得检查结果: 0/1", summary)
        self.assertIn("检查结果不完整", summary)
        self.assertNotIn("所有触发型规约的触发条件均可达", summary)


@unittest.skipUnless(
    FMCS_FIXTURE_DIRECTORY is not None and FMCS_REQUIREMENT_FILE is not None,
    "未找到FMCS集成测试文件；请检查TestWrong中的FI结果文件及"
    "FMCS_时序逻辑结果.smv，或设置FMCS_TRACE_TEST_DATA和"
    "FMCS_TRACE_REQUIREMENTS。",
)
class FmcsIntegrationRegressionTests(unittest.TestCase):
    EXPECTED = {
        "01": {
            "stats": (3, 636, 132, 504),
            "requirements": {
                "REQ-FMCS-FLOW-09": "因果响应违规",
                "REQ-FMCS-LIVE-49": "最终可达性违规",
                "REQ-FMCS-HOLD-38": "状态持续性违规",
            },
            "components": {"CBM", "RADAR"},
        },
        "02": {
            "stats": (1, 212, 44, 168),
            "requirements": {
                "REQ-FMCS-CONS-03": "一致性违规",
            },
            "components": {"RADAR"},
        },
        "03": {
            "stats": (1, 191, 24, 167),
            "requirements": {
                "REQ-FMCS-FLOW-15": "因果响应违规",
            },
            "components": {"AP"},
        },
        "04": {
            "stats": (2, 424, 96, 328),
            "requirements": {
                "REQ-FMCS-FLOW-33": "因果响应违规",
                "REQ-FMCS-LIVE-47": "最终可达性违规",
            },
            "components": {"FC"},
        },
        "05": {
            "stats": (5, 1055, 215, 840),
            "requirements": {
                "REQ-FMCS-FLOW-24": "因果响应违规",
                "REQ-FMCS-FLOW-27": "因果响应违规",
                "REQ-FMCS-FLOW-32": "因果响应违规",
                "REQ-FMCS-HOLD-39": "状态持续性违规",
                "REQ-FMCS-SAFE-45": "互斥安全性违规",
            },
            "components": {"AP"},
        },
    }

    @classmethod
    def setUpClass(cls) -> None:
        assert FMCS_FIXTURE_DIRECTORY is not None
        assert FMCS_REQUIREMENT_FILE is not None
        cls.data = FMCS_FIXTURE_DIRECTORY
        cls.requirement_file = FMCS_REQUIREMENT_FILE
        cls.requirement_index = trace_tool.parse_requirement_spec_index(
            cls.requirement_file
        )
        cls.coverage_catalog = trace_tool.parse_trigger_coverage_catalog(
            cls.requirement_file
        )

    def test_generated_provenance_catalog_counts(self) -> None:
        self.assertEqual(len(self.requirement_index), 51)
        self.assertEqual(
            sum(len(records) for records in self.requirement_index.values()),
            51,
        )
        self.assertTrue(
            all(len(records) == 1 for records in self.requirement_index.values())
        )
        self.assertEqual(len(self.coverage_catalog.checks), 41)

    def test_five_fault_models_preserve_expected_instance_index(self) -> None:
        expected_mapping = {
            "FC": "FlightMissionControl",
            "CBM": "ControlBusModule",
            "BAT": "Battery",
            "PL": "Payload",
            "RADAR": "Radar",
            "AP": "AutoPilot",
            "OP": "oper",
        }
        for fault_id in self.EXPECTED:
            with self.subTest(fault=fault_id):
                model_path = (
                    self.data / f"input_FMCS_FI_{fault_id}_Result.smv"
                )
                self.assertEqual(
                    trace_tool.parse_smv_model(model_path),
                    expected_mapping,
                )

    def test_five_fault_results_and_compression_do_not_regress(self) -> None:
        totals = trace_tool.CompressionStats()
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory)
            for fault_id, expectation in self.EXPECTED.items():
                result_path = (
                    self.data / f"input_FMCS_FI_{fault_id}_Result.txt"
                )
                compressed_path = output_root / f"FI_{fault_id}.txt"
                output_path, stats = trace_tool.compress_nuxmv_output(
                    result_path,
                    compressed_path,
                    coverage_catalog=self.coverage_catalog,
                )
                totals.add(stats)
                self.assertEqual(
                    (
                        stats.counterexamples,
                        stats.raw_states,
                        stats.retained_states,
                        stats.folded_states,
                    ),
                    expectation["stats"],
                )

                traces = trace_tool.parse_trace_report(
                    output_path,
                    self.coverage_catalog,
                )
                actual_requirements: dict[str, str] = {}
                actual_components: set[str] = set()
                for item in traces:
                    failed_spec = str(item["spec"])
                    sources = trace_tool.find_requirement_sources(
                        failed_spec,
                        self.requirement_index,
                    )
                    self.assertEqual(len(sources), 1)
                    classification = trace_tool.classify_violation(
                        failed_spec,
                        sources,
                    )
                    self.assertEqual(classification.consistency, "一致")
                    actual_requirements[sources[0].requirement_id] = (
                        classification.category
                    )
                    actual_components.update(
                        match.group(1)
                        for match in re.finditer(
                            r"\b([A-Za-z_][A-Za-z0-9_]*)\.",
                            failed_spec,
                        )
                    )

                self.assertEqual(
                    actual_requirements,
                    expectation["requirements"],
                )
                self.assertEqual(actual_components, expectation["components"])

        self.assertEqual(
            (
                totals.counterexamples,
                totals.raw_states,
                totals.retained_states,
                totals.folded_states,
            ),
            (12, 2518, 511, 2007),
        )
        self.assertAlmostEqual(
            totals.state_block_reduction_rate,
            79.71,
            places=2,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
