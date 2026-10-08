"""FMCS需求形式化链的回归与边界测试。"""

from __future__ import annotations

import copy
import hashlib
import re
import unittest
from pathlib import Path

import REQ2CTLLTL as formalizer
from nuxmv_generator import NuXMVGenerator
from x_transpiler import parse_x_model


class RequirementFormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = Path(__file__).resolve().parent

        def first_existing(*paths: Path) -> Path:
            for path in paths:
                if path.exists():
                    return path
            return paths[0]

        cls.requirements_path = first_existing(
            formalizer.REQUIREMENTS_FILE,
            base / "FMCS_Req_Final.md",
            base / "upload/FMCS_Req_Final.md",
        )
        cls.trace_path = first_existing(
            formalizer.TRACE_FILE,
            base / "FMCS_Req_TC_validated.txt",
            base / "FMCS_Req_TC.txt",
            base / "upload/FMCS_Req_TC.txt",
        )
        cls.model_path = first_existing(
            formalizer.X_MODEL_FILE,
            base / "input_XModel_FMCS.txt",
            base / "upload/input_XModel_FMCS.txt",
        )
        cls.result = formalizer.formalize_requirements(
            cls.requirements_path,
            cls.trace_path,
            cls.model_path,
        )
        cls.symbol_index = formalizer.ModelSymbolIndex.from_model_file(
            cls.model_path
        )
        cls.trace_sources = formalizer.parse_trace_file(cls.trace_path)

    def test_fmcs_regression_counts(self) -> None:
        formulas = self.result.formulas
        self.assertEqual(len(formulas), 51)
        self.assertEqual(sum(item.logic == "CTL" for item in formulas), 2)
        self.assertEqual(sum(item.logic == "LTL" for item in formulas), 49)
        self.assertEqual(
            sum(item.trigger_condition is not None for item in formulas),
            41,
        )
        self.assertEqual(self.result.mapping_count, 70)
        self.assertEqual(len(self.result.binding_records), 101)
        self.assertEqual(
            sum(item.match_mode == "exact" for item in self.result.binding_records),
            67,
        )

    def test_fmcs_formula_text_has_no_regression(self) -> None:
        text = "\n".join(item.formula for item in self.result.formulas) + "\n"
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.assertEqual(
            digest,
            "9b4859201f19d14fb905246f22fea097d4fd96cd558e51ac10a56dc825dfe648",
        )

    def test_formula_symbols_exist_in_generated_target_modules(self) -> None:
        visitor = parse_x_model(self.model_path)
        generator = NuXMVGenerator()
        for model in visitor.discrete_models:
            generator.generate_discrete(model)
        for model in visitor.coupled_models:
            generator.generate_coupled(model)
        target_model = generator.get_result()

        module_matches = list(
            re.finditer(r"(?m)^MODULE\s+([A-Za-z_]\w*)", target_model)
        )
        module_text: dict[str, str] = {}
        for index, match in enumerate(module_matches):
            end = (
                module_matches[index + 1].start()
                if index + 1 < len(module_matches)
                else len(target_model)
            )
            module_text[match.group(1)] = target_model[match.start():end]

        formula_text = "\n".join(item.formula for item in self.result.formulas)
        references = set(
            re.findall(
                r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b",
                formula_text,
            )
        )
        self.assertEqual(len(references), 27)
        for instance_name, member_name in references:
            with self.subTest(reference=f"{instance_name}.{member_name}"):
                class_name = self.symbol_index.instances[instance_name]
                body = module_text[class_name]
                member = re.escape(member_name)
                self.assertRegex(
                    body,
                    rf"(?:\b{member}\s*:|\b{member}\s*:=|"
                    rf"next\({member}\)|init\({member}\))",
                )

    def test_zero_step_means_current_state(self) -> None:
        resolver = formalizer.TraceResolver(
            copy.deepcopy(self.trace_sources),
            self.symbol_index,
        )
        converter = formalizer.RequirementConverter(resolver)
        requirement = formalizer.Requirement(
            "REQ-ZERO",
            "当【自动驾驶仪】处于【可工作状态】且【自动驾驶仪】收到"
            "【第一飞行模式信号】后，【自动驾驶仪】一定在【0】步后"
            "输出【高负载工作状态】",
        )
        formula = converter.convert(requirement).formula
        self.assertNotIn("AX", formula)
        self.assertIn("AP.out_current = 18", formula)

    def test_possible_fixed_step_is_outside_paper_scope(self) -> None:
        resolver = formalizer.TraceResolver(
            copy.deepcopy(self.trace_sources),
            self.symbol_index,
        )
        converter = formalizer.RequirementConverter(resolver)
        requirement = formalizer.Requirement(
            "REQ-POSSIBLE",
            "当【自动驾驶仪】处于【可工作状态】后，【自动驾驶仪】可能在"
            "【1】步后输出【高负载工作状态】",
        )
        with self.assertRaises(formalizer.ConversionError):
            converter.convert(requirement)

    def test_invalid_state_mapping_is_rejected(self) -> None:
        radar = next(
            copy.deepcopy(source)
            for source in self.trace_sources
            if source.natural_name == "雷达"
        )
        radar.entries["state_source"]["无效状态"] = "does_not_exist"
        with self.assertRaises(formalizer.ConversionError):
            self.symbol_index.validate_trace_sources([radar])

    def test_wrong_event_direction_is_rejected(self) -> None:
        radar = next(
            copy.deepcopy(source)
            for source in self.trace_sources
            if source.natural_name == "雷达"
        )
        radar.entries["event_source"]["错误方向"] = "evHighPowerOn = TRUE"
        with self.assertRaises(formalizer.ConversionError):
            self.symbol_index.validate_trace_sources([radar])

    def test_non_integer_and_out_of_domain_values_are_rejected(self) -> None:
        for value in ("1.5", "99"):
            with self.subTest(value=value):
                radar = next(
                    copy.deepcopy(source)
                    for source in self.trace_sources
                    if source.natural_name == "雷达"
                )
                radar.entries["value_source"]["无效数值"] = (
                    f"current = {value}"
                )
                with self.assertRaises(formalizer.ConversionError):
                    self.symbol_index.validate_trace_sources([radar])


if __name__ == "__main__":
    unittest.main(verbosity=2)
