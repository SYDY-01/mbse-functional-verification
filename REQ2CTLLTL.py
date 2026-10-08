# -*- coding: utf-8 -*-
"""
将结构化Markdown需求转换为经过X语言模型约束校验的nuXmv CTL/LTL规约。

使用方式
========
1. 将本脚本、X语言解析器、需求文件、追溯文件和X模型放入工程目录。
2. 在“用户配置区”修改四个输入/输出文件名（如已经一致则不必修改）。
3. 直接在 IDE 中右键运行本脚本，或双击运行。

输入格式保持不变：
- 需求文件是带 Markdown 标题的 .md 文件，每条需求形如：
  REQ-UAV-CONS-01：当【供电系统】处于【稳定供电状态】时，……
- 追溯文件保持 source(...)、state_source(...) 等原格式；不需要额外JSON。
- X语言模型经ANTLR解析并构建类型化IR，用于检查组件实例、状态、
  端口、变量、方向和字面量类型。

本文支持的五类规则：
- 当前状态一致性                     -> LTL
- 因果响应（固定 n 步 / 无界最终）       -> CTL / LTL
- 状态持续（强直到）                 -> LTL
- 互斥约束                           -> LTL
- 最终到达约束                       -> LTL

固定步模板中 n 为非负整数；当 n=0 时定义 AX^0 Q = Q，
即在触发前件成立的当前状态检查 Q。代码不提供“可能响应”、
“必然不响应”、一般不可达或最终稳定等未在本文定义的额外分支。

对于具有明确触发前件 P 的规约，脚本还会在同一输出文件中追加
CTLSPEC NAME COV_<需求编号> := EF(P)，用于检查触发条件是否可达。
这些诊断属性不计入正式需求规约总数。

依赖：antlr4-python3-runtime，以及与CD.g4对应的CDLexer、CDParser、
CDVisitor和x_transpiler模块。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Literal

from x_transpiler import (
    CoupledModel,
    DiscreteModel,
    Port,
    Variable,
    parse_x_model,
)


# ============================================================================
# 用户配置区：通常只需要修改这里的四个文件名
# ============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent

# 用于确认电脑实际运行的是哪一版脚本。
SCRIPT_VERSION = "2026-09-11-r7-final-model-grounded-binding"

REQUIREMENTS_FILE = SCRIPT_DIR / "FMCS/FMCS_Req_Final.md"
TRACE_FILE = SCRIPT_DIR / "FMCS/FMCS_Req_TC_validated.txt"
X_MODEL_FILE = SCRIPT_DIR / "FMCS/input_XModel_FMCS.txt"
OUTPUT_FILE = SCRIPT_DIR / "FMCS/FMCS_CTL_and_LTL_Specifications.smv"

# True：遇到无法绑定或无法识别的需求时停止，不生成可能错误的规约。
STRICT_MODE = True

# True：运行结束后等待按回车，适合双击脚本运行；IDE中可改为 False。
PAUSE_AFTER_RUN = True


# ============================================================================
# 数据结构
# ============================================================================


class ConversionError(ValueError):
    """需求解析或语义绑定失败。"""


@dataclass(frozen=True)
class Requirement:
    req_id: str
    text: str


@dataclass
class TraceSource:
    natural_name: str
    module_name: str
    # 可在source(...)第三个参数中显式给出。省略时由耦合模型中该组件类
    # 的唯一实例确定，不再通过组件名称硬编码猜测。
    instance_name: str | None
    entries: dict[str, dict[str, str]] = field(
        default_factory=lambda: {
            "state_source": {},
            "condition_source": {},
            "event_source": {},
            "value_source": {},
            "time_source": {},
        }
    )


@dataclass(frozen=True)
class GeneratedFormula:
    req_id: str
    source_text: str
    pattern_type: str
    logic: Literal["CTL", "LTL"]
    formula: str
    warnings: tuple[str, ...] = ()
    # 仅对具有明确触发前件 P 的模板赋值。最终输出会据此生成 EF(P)。
    trigger_condition: str | None = None


@dataclass(frozen=True)
class BindingRecord:
    """一次需求槽位解析的可审计记录。"""

    requirement_id: str
    object_name: str
    requested_term: str
    matched_term: str
    mapping_kind: str
    match_mode: Literal["exact", "normalized"]
    expression: str


@dataclass(frozen=True)
class FormalizationResult:
    formulas: tuple[GeneratedFormula, ...]
    mapping_count: int
    ignored_time_mapping_count: int
    binding_records: tuple[BindingRecord, ...]
    errors: tuple[str, ...] = ()


# ============================================================================
# 通用文本处理
# ============================================================================


def clean_text(text: str) -> str:
    """统一标点并删除不影响CNL模板的空白。"""

    text = text.strip()
    text = text.replace(",", "，")
    text = text.strip(" \t\r\n，,。；;")
    text = re.sub(r"\s+", "", text)
    return text


def strip_outer_brackets(text: str) -> str:
    text = clean_text(text)
    if (
        text.startswith("【")
        and text.endswith("】")
        and text.count("【") == 1
        and text.count("】") == 1
    ):
        return text[1:-1]
    return text


def semantic_key(text: str) -> str:
    """生成用于确定性术语比对的规范化键。"""

    text = strip_outer_brackets(text)
    removable_tokens = (
        "最终一定会",
        "最终会",
        "一定会",
        "不应",
        "应",
        "不会",
        "会",
        "发出",
        "发送",
        "输出",
        "触发",
        "收到",
        "进入",
        "达到",
        "处于",
        "满足",
        "保持",
        "完成",
        "信号",
        "命令",
        "指令",
        "状态",
        "阶段",
        "工作",
        "切换",
        "类",
    )
    for token in removable_tokens:
        text = text.replace(token, "")
    return text


def bracket_items(text: str) -> list[str]:
    return [clean_text(item) for item in re.findall(r"【([^】]+)】", text)]


def split_condition(text: str) -> list[str]:
    """将条件拆成 [原子命题, 连接词, 原子命题, ...]。"""

    parts = [part for part in re.split(r"(且|或)", clean_text(text)) if part]
    return [clean_text(part) for part in parts]


def parenthesize(expression: str) -> str:
    return f"({expression.strip()})"


def negate(expression: str) -> str:
    return f"!{parenthesize(expression)}"


def normalize_steps(text: str) -> int:
    text = strip_outer_brackets(text)
    match = re.fullmatch(r"\d+", text)
    if not match:
        raise ConversionError(f"固定步响应中的步数必须是非负整数，实际为：{text}")
    return int(text)


def nested_next(operator: Literal["AX", "EX", "X"], expression: str, steps: int) -> str:
    result = expression.strip()
    if steps == 0:
        return parenthesize(result)
    for _ in range(steps):
        result = f"{operator} ({result})"
    return result


# ============================================================================
# 需求文件读取：保留用户现有Markdown格式
# ============================================================================


REQUIREMENT_LINE_PATTERN = re.compile(
    r"^\s*(?P<req_id>REQ[-_A-Za-z0-9]+)\s*[：:]\s*(?P<text>.+?)\s*$"
)


def read_requirements(path: Path) -> list[Requirement]:
    if not path.exists():
        raise FileNotFoundError(f"找不到需求文件：{path}")

    requirements: list[Requirement] = []
    seen_ids: set[str] = set()

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(),
        start=1,
    ):
        match = REQUIREMENT_LINE_PATTERN.match(raw_line)
        if not match:
            # Markdown标题、空行和说明文字均保持原样并自动忽略。
            continue

        req_id = match.group("req_id")
        text = clean_text(match.group("text"))

        if req_id in seen_ids:
            raise ConversionError(
                f"需求文件第{line_number}行存在重复编号：{req_id}"
            )
        if not text:
            raise ConversionError(f"需求{req_id}没有正文。")

        seen_ids.add(req_id)
        requirements.append(Requirement(req_id=req_id, text=text))

    if not requirements:
        raise ConversionError(
            "需求文件中未找到形如“REQ-UAV-XXX-01：需求正文”的需求。"
        )

    return requirements


# ============================================================================
# X语言模型符号索引与追踪配置校验
# ============================================================================


_ASSIGNMENT_PATTERN = re.compile(
    r"(?P<name>[A-Za-z_][A-Za-z0-9_.]*)\s*"
    r"(?P<operator>=|!=|>=|<=|>|<)\s*"
    r"(?P<value>.+)"
)
_SEND_ACTION_PATTERN = re.compile(
    r"^send\s*\(\s*(?P<target>[A-Za-z_]\w*)\s*,\s*"
    r"(?P<value>.*?)\s*\)\s*;?$",
    re.IGNORECASE | re.DOTALL,
)
_VALUE_ACTION_PATTERN = re.compile(
    r"^\s*(?P<target>[A-Za-z_]\w*)\s*=(?!=)\s*"
    r"(?P<value>.*?)\s*;?$",
    re.DOTALL,
)
_TIME_SOURCE_PATTERN = re.compile(
    r"^statehold\s*\(\s*(?:infinite|\d+)\s*\)$",
    re.IGNORECASE,
)


class ModelSymbolIndex:
    """
    由X语言类型化IR构建的只读模型符号索引。

    索引用于校验已有追踪配置，不从自然语言自动猜测业务语义。它检查：
    组件实例唯一性、元素归属、状态/端口/变量存在性、端口方向、公开观察
    语义，以及当前有限离散子集中的字面量类型和静态数值域。
    """

    def __init__(
        self,
        discrete_models: Iterable[DiscreteModel],
        coupled_models: Iterable[CoupledModel],
    ):
        self.models: dict[str, DiscreteModel] = {}
        self.instances: dict[str, str] = {}
        self.instances_by_class: dict[str, list[str]] = {}
        self.incoming_connections: dict[tuple[str, str], tuple[str, str]] = {}
        self.numeric_domains: dict[tuple[str, str], tuple[int, int]] = {}

        for model in discrete_models:
            if model.name in self.models:
                raise ConversionError(f"X模型存在重复离散组件类：{model.name}")
            self._validate_model_namespace(model)
            self.models[model.name] = model

        coupled_list = list(coupled_models)
        if not self.models:
            raise ConversionError("X模型中没有可用于绑定的离散组件。")
        if not coupled_list:
            raise ConversionError("X模型中没有包含组件实例的耦合模型。")

        for coupled in coupled_list:
            self._index_parts(coupled)

        for coupled in coupled_list:
            self._validate_connections(coupled)

        self._infer_numeric_domains()

    @classmethod
    def from_model_file(cls, path: Path) -> "ModelSymbolIndex":
        visitor = parse_x_model(path)
        return cls(visitor.discrete_models, visitor.coupled_models)

    @staticmethod
    def _validate_model_namespace(model: DiscreteModel) -> None:
        def ensure_unique(items: Iterable[str], label: str) -> None:
            seen: set[str] = set()
            duplicates: set[str] = set()
            for item in items:
                if item in seen:
                    duplicates.add(item)
                seen.add(item)
            if duplicates:
                values = "、".join(sorted(duplicates))
                raise ConversionError(
                    f"组件{model.name}存在重复{label}：{values}"
                )

        ensure_unique((state.name for state in model.states), "状态")
        ensure_unique((port.name for port in model.ports), "端口")
        ensure_unique((variable.name for variable in model.variables), "变量/参数")

        state_names = {state.name for state in model.states}
        if not state_names:
            raise ConversionError(f"组件{model.name}没有离散状态。")
        initial_states = [state.name for state in model.states if state.is_initial]
        if len(initial_states) != 1:
            raise ConversionError(
                f"组件{model.name}必须且只能包含一个初始状态，"
                f"实际为{len(initial_states)}个。"
            )
        for state in model.states:
            for transition in state.transitions:
                if transition.target not in state_names:
                    raise ConversionError(
                        f"组件{model.name}的状态{state.name}转移指向"
                        f"未定义状态{transition.target}。"
                    )

        for port in model.ports:
            direction = str(port.direction).replace(" ", "").lower()
            if direction not in {"eventinput", "eventoutput"}:
                raise ConversionError(
                    f"组件{model.name}的端口{port.name}方向不受支持："
                    f"{port.direction}。"
                )
        for variable in model.variables:
            if variable.kind not in {"value", "parameter"}:
                raise ConversionError(
                    f"组件{model.name}的符号{variable.name}类别"
                    f"不受支持：{variable.kind}。"
                )

        port_names = {port.name for port in model.ports}
        variable_names = {variable.name for variable in model.variables}
        overlap = port_names & variable_names
        if overlap:
            raise ConversionError(
                f"组件{model.name}的端口与变量发生名称冲突："
                f"{'、'.join(sorted(overlap))}"
            )

    def _index_parts(self, coupled: CoupledModel) -> None:
        for part in coupled.parts:
            if part.class_name not in self.models:
                raise ConversionError(
                    f"耦合模型{coupled.name}中的实例{part.instance_name}引用了"
                    f"未定义组件类{part.class_name}。"
                )
            previous = self.instances.get(part.instance_name)
            if previous is not None:
                raise ConversionError(
                    f"组件实例名{part.instance_name}在耦合模型中不唯一："
                    f"{previous}与{part.class_name}。"
                )
            self.instances[part.instance_name] = part.class_name
            self.instances_by_class.setdefault(part.class_name, []).append(
                part.instance_name
            )

    @staticmethod
    def _direction(port: Port) -> str:
        return str(port.direction).replace(" ", "").strip().lower()

    @classmethod
    def _is_input(cls, port: Port) -> bool:
        return cls._direction(port).endswith("input")

    @classmethod
    def _is_output(cls, port: Port) -> bool:
        return cls._direction(port).endswith("output")

    @staticmethod
    def _datatype(datatype: str) -> str:
        return str(datatype).strip().lower()

    @classmethod
    def _datatype_group(cls, datatype: str) -> str:
        name = cls._datatype(datatype)
        if name in {"int", "integer", "real"}:
            return "numeric"
        if name in {"bool", "boolean"}:
            return "boolean"
        return name

    @staticmethod
    def _parse_endpoint(endpoint: str) -> tuple[str, str]:
        match = re.fullmatch(
            r"(?P<instance>[A-Za-z_]\w*)\.(?P<port>[A-Za-z_]\w*)",
            endpoint.strip(),
        )
        if not match:
            raise ConversionError(f"连接端点格式不受支持：{endpoint}")
        return match.group("instance"), match.group("port")

    def _port(self, instance_name: str, port_name: str) -> Port:
        module_name = self.instances.get(instance_name)
        if module_name is None:
            raise ConversionError(f"X模型中不存在组件实例：{instance_name}")
        model = self.models[module_name]
        port = next((p for p in model.ports if p.name == port_name), None)
        if port is None:
            raise ConversionError(
                f"组件实例{instance_name}（{module_name}）不存在端口{port_name}。"
            )
        return port

    def _validate_connections(self, coupled: CoupledModel) -> None:
        for connection in coupled.connections:
            source_instance, source_port_name = self._parse_endpoint(
                connection.source
            )
            target_instance, target_port_name = self._parse_endpoint(
                connection.target
            )
            source_port = self._port(source_instance, source_port_name)
            target_port = self._port(target_instance, target_port_name)

            if not self._is_output(source_port):
                raise ConversionError(
                    f"连接源{connection.source}不是输出端口。"
                )
            if not self._is_input(target_port):
                raise ConversionError(
                    f"连接目标{connection.target}不是输入端口。"
                )
            if self._datatype_group(source_port.datatype) != self._datatype_group(
                target_port.datatype
            ):
                raise ConversionError(
                    f"连接{connection.source}->{connection.target}的端口类型不兼容："
                    f"{source_port.datatype}与{target_port.datatype}。"
                )

            target_key = (target_instance, target_port_name)
            previous = self.incoming_connections.get(target_key)
            if previous is not None:
                raise ConversionError(
                    f"输入端口{connection.target}存在多个发送源；当前转换范围"
                    "不包含未定义仲裁规则的多源并发写入。"
                )
            self.incoming_connections[target_key] = (
                source_instance,
                source_port_name,
            )

    @staticmethod
    def _normalise_action(action_item) -> str:
        if isinstance(action_item, (tuple, list)):
            if not action_item:
                return ""
            action_item = action_item[0]
        return str(action_item).strip().rstrip(";")

    @staticmethod
    def _parameter_values(model: DiscreteModel) -> dict[str, str]:
        return {
            variable.name: str(variable.init_value).strip()
            for variable in model.variables
            if variable.kind == "parameter" and variable.init_value is not None
        }

    @classmethod
    def _resolve_integer_constant(
        cls,
        expression: str | None,
        model: DiscreteModel,
    ) -> int | None:
        if expression is None:
            return None
        text = str(expression).strip().rstrip(";")
        parameters = cls._parameter_values(model)
        visited: set[str] = set()

        while text in parameters:
            if text in visited:
                return None
            visited.add(text)
            text = parameters[text]

        try:
            value = Decimal(text)
        except (InvalidOperation, ValueError):
            return None
        if not value.is_finite() or value != value.to_integral_value():
            return None
        return int(value)

    def _infer_numeric_domains(self) -> None:
        """按第5节相同的静态常量假设推导有限整数域。"""

        class_domains: dict[tuple[str, str], tuple[int, int]] = {}

        for model in self.models.values():
            symbols: dict[str, set[int]] = {}
            for port in model.ports:
                if (
                    self._is_output(port)
                    and self._datatype_group(port.datatype) == "numeric"
                ):
                    symbols[port.name] = {0}
            for variable in model.variables:
                if (
                    variable.kind == "value"
                    and self._datatype_group(variable.datatype) == "numeric"
                ):
                    if variable.init_value is None:
                        raise ConversionError(
                            f"组件{model.name}的数值变量{variable.name}"
                            "缺少可用于有限域推导的初值。"
                        )
                    initial = self._resolve_integer_constant(
                        variable.init_value, model
                    )
                    if initial is None:
                        raise ConversionError(
                            f"组件{model.name}的数值变量{variable.name}"
                            f"初值无法静态解析为整数：{variable.init_value}。"
                        )
                    symbols[variable.name] = {initial}

            for state in model.states:
                for transition in state.transitions:
                    for action_item in transition.actions:
                        action = self._normalise_action(action_item)
                        if not action:
                            continue
                        match = _SEND_ACTION_PATTERN.fullmatch(action)
                        if match is None:
                            match = _VALUE_ACTION_PATTERN.fullmatch(action)
                        if match is None:
                            continue
                        target = match.group("target")
                        if target.startswith("out_"):
                            target = target[4:]
                        if target not in symbols:
                            continue
                        value = self._resolve_integer_constant(
                            match.group("value"), model
                        )
                        if value is None:
                            raise ConversionError(
                                f"组件{model.name}的数值符号{target}包含无法静态"
                                f"解析为整数的更新：{action}。"
                            )
                        symbols[target].add(value)

            for symbol_name, values in symbols.items():
                lower = min(values)
                upper = max(values)
                class_domains[(model.name, symbol_name)] = (lower, upper)

        for instance_name, module_name in self.instances.items():
            model = self.models[module_name]
            for port in model.ports:
                domain = class_domains.get((module_name, port.name))
                if domain is not None:
                    self.numeric_domains[(instance_name, port.name)] = domain
            for variable in model.variables:
                domain = class_domains.get((module_name, variable.name))
                if domain is not None:
                    self.numeric_domains[(instance_name, variable.name)] = domain

        # 输入端口的有限域由其静态连接源继承。
        for target, source in self.incoming_connections.items():
            source_domain = self.numeric_domains.get(source)
            if source_domain is not None:
                self.numeric_domains[target] = source_domain

    def resolve_instance(self, source: TraceSource) -> tuple[str, DiscreteModel]:
        module = self.models.get(source.module_name)
        if module is None:
            raise ConversionError(
                f"追踪对象“{source.natural_name}”引用了X模型中不存在的"
                f"组件类{source.module_name}。"
            )

        if source.instance_name:
            actual_class = self.instances.get(source.instance_name)
            if actual_class is None:
                raise ConversionError(
                    f"追踪对象“{source.natural_name}”引用了不存在的组件实例"
                    f"{source.instance_name}。"
                )
            if actual_class != source.module_name:
                raise ConversionError(
                    f"组件实例{source.instance_name}的实际类型为{actual_class}，"
                    f"与追踪配置中的{source.module_name}不一致。"
                )
            return source.instance_name, module

        candidates = self.instances_by_class.get(source.module_name, [])
        if len(candidates) != 1:
            if not candidates:
                detail = "不存在该类型的实例"
            else:
                detail = f"候选实例为：{'、'.join(sorted(candidates))}"
            raise ConversionError(
                f"无法唯一确定追踪对象“{source.natural_name}”对应的"
                f"{source.module_name}实例，{detail}。请在source(...)的第三个"
                "参数中显式给出实例名。"
            )
        source.instance_name = candidates[0]
        return candidates[0], module

    @staticmethod
    def _public_view_mode(port: Port) -> Literal["event", "data"]:
        """与第5节代码生成器保持一致：显式字段优先，命名仅作回退。"""

        for attribute in ("semantic_kind", "signal_kind", "view_mode"):
            value = getattr(port, attribute, None)
            if value is None:
                continue
            normalized = str(value).strip().lower()
            if normalized in {"event", "pulse", "message"}:
                return "event"
            if normalized in {"data", "persistent", "state", "value"}:
                return "data"
        is_event = getattr(port, "is_event", None)
        if isinstance(is_event, bool):
            return "event" if is_event else "data"
        return "event" if port.name.lower().startswith("ev") else "data"

    @staticmethod
    def _split_configured_name(
        configured_name: str,
        expected_instance: str,
    ) -> str:
        name = configured_name.strip()
        if "." in name:
            prefix, name = name.rsplit(".", 1)
            if prefix != expected_instance:
                raise ConversionError(
                    f"追踪表达式限定实例{prefix}与解析得到的实例"
                    f"{expected_instance}不一致。"
                )
        if name.startswith("in_"):
            name = name[3:]
        elif name.startswith("out_"):
            name = name[4:]
        for suffix in ("_value", "_valid"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        return name

    def _find_member(
        self,
        instance_name: str,
        module: DiscreteModel,
        member_name: str,
    ) -> tuple[Port | Variable, str]:
        port = next((item for item in module.ports if item.name == member_name), None)
        if port is not None:
            return port, "port"
        variable = next(
            (item for item in module.variables if item.name == member_name),
            None,
        )
        if variable is not None:
            return variable, (
                "parameter" if variable.kind == "parameter" else "variable"
            )
        raise ConversionError(
            f"组件实例{instance_name}（{module.name}）不存在端口、变量或参数"
            f"{member_name}。"
        )

    def _validate_literal(
        self,
        member: Port | Variable,
        instance_name: str,
        member_name: str,
        operator: str,
        value: str,
    ) -> str:
        datatype = self._datatype(member.datatype)
        group = self._datatype_group(datatype)
        normalized_value = value.strip()

        if group == "boolean":
            if operator not in {"=", "!="}:
                raise ConversionError(
                    f"布尔符号{instance_name}.{member_name}不支持比较符{operator}。"
                )
            if normalized_value.lower() not in {"true", "false"}:
                raise ConversionError(
                    f"{instance_name}.{member_name}为布尔类型，但追踪值为"
                    f"{normalized_value}。"
                )
            return normalized_value.upper()

        if group == "numeric":
            try:
                decimal_value = Decimal(normalized_value)
            except (InvalidOperation, ValueError) as error:
                raise ConversionError(
                    f"{instance_name}.{member_name}为数值类型，但追踪值为"
                    f"{normalized_value}。"
                ) from error
            if (
                not decimal_value.is_finite()
                or decimal_value != decimal_value.to_integral_value()
            ):
                raise ConversionError(
                    f"当前有限离散转换仅支持整数值，{instance_name}."
                    f"{member_name}的追踪值为{normalized_value}。"
                )
            integer_value = int(decimal_value)
            domain = self.numeric_domains.get((instance_name, member_name))
            if (
                operator in {"=", "!="}
                and domain is not None
                and not (domain[0] <= integer_value <= domain[1])
            ):
                raise ConversionError(
                    f"追踪值{integer_value}超出{instance_name}.{member_name}"
                    f"的静态有限域{domain[0]}..{domain[1]}。"
                )
            return str(integer_value)

        # 当前X语言子集中的其他有限类型以标识符或字符串字面量表示。
        if not normalized_value:
            raise ConversionError(
                f"{instance_name}.{member_name}的追踪比较值为空。"
            )
        return normalized_value

    def compile_mapping(
        self,
        source: TraceSource,
        kind: str,
        raw_expression: str,
    ) -> str:
        if kind == "time_source":
            raise ConversionError(
                "time_source不是本文五类需求模板中的模型原子命题；固定步数"
                "应直接由需求模板的非负整数槽位给出。"
            )

        instance_name, module = self.resolve_instance(source)
        raw = raw_expression.strip()

        if kind == "state_source":
            if not re.fullmatch(r"[A-Za-z_]\w*", raw):
                raise ConversionError(f"状态映射格式不受支持：{raw}")
            states = {state.name for state in module.states}
            if raw not in states:
                raise ConversionError(
                    f"组件实例{instance_name}（{module.name}）不存在状态{raw}。"
                )
            return f"{instance_name}.state = {raw}"

        match = _ASSIGNMENT_PATTERN.fullmatch(raw)
        if not match:
            raise ConversionError(f"追踪表达式格式不受支持：{raw}")

        configured_name = match.group("name")
        operator = match.group("operator")
        value = match.group("value").strip()
        member_name = self._split_configured_name(
            configured_name, instance_name
        )

        if member_name == "state":
            if operator not in {"=", "!="}:
                raise ConversionError("状态枚举仅支持=或!=比较。")
            if value not in {state.name for state in module.states}:
                raise ConversionError(
                    f"组件实例{instance_name}（{module.name}）不存在状态{value}。"
                )
            return f"{instance_name}.state {operator} {value}"
        if member_name == "timer":
            raise ConversionError(
                "timer是第5节生成的辅助变量，不作为需求追踪配置中的源模型"
                "业务元素。"
            )

        member, member_kind = self._find_member(
            instance_name, module, member_name
        )
        if isinstance(member, Port):
            if kind == "condition_source":
                if not self._is_input(member):
                    raise ConversionError(
                        f"condition_source必须引用输入端口，但{instance_name}."
                        f"{member_name}的方向为{member.direction}。"
                    )
                if self._public_view_mode(member) != "event":
                    raise ConversionError(
                        f"condition_source表示一次到达事件，但{instance_name}."
                        f"{member_name}被解释为持续数据视图。"
                    )
            elif kind == "event_source":
                if not self._is_output(member):
                    raise ConversionError(
                        f"event_source必须引用输出端口，但{instance_name}."
                        f"{member_name}的方向为{member.direction}。"
                    )
                if self._public_view_mode(member) != "event":
                    raise ConversionError(
                        f"event_source表示一次发送事件，但{instance_name}."
                        f"{member_name}被解释为持续数据视图。"
                    )
            elif kind == "value_source":
                if not self._is_output(member):
                    raise ConversionError(
                        f"value_source引用端口时必须是输出端口，但"
                        f"{instance_name}.{member_name}的方向为{member.direction}。"
                    )
                if self._public_view_mode(member) != "data":
                    raise ConversionError(
                        f"value_source表示持续值，但{instance_name}."
                        f"{member_name}被解释为单步事件视图。"
                    )

            target_name = (
                f"in_{member_name}"
                if self._is_input(member)
                else f"out_{member_name}"
            )
        else:
            if kind in {"condition_source", "event_source"}:
                raise ConversionError(
                    f"{kind}当前只允许绑定离散端口；{instance_name}."
                    f"{member_name}是{member_kind}。"
                )
            target_name = member_name

        normalized_value = self._validate_literal(
            member,
            instance_name,
            member_name,
            operator,
            value,
        )
        return (
            f"{instance_name}.{target_name} {operator} {normalized_value}"
        )

    def validate_trace_sources(
        self,
        sources: Iterable[TraceSource],
    ) -> tuple[int, int]:
        """校验全部原子映射；time_source仅做兼容性语法检查。"""

        mapping_count = 0
        ignored_time_count = 0
        for source in sources:
            non_time_count = sum(
                len(entries)
                for kind, entries in source.entries.items()
                if kind != "time_source"
            )
            if non_time_count:
                self.resolve_instance(source)

            for kind, entries in source.entries.items():
                for natural_term, expression in entries.items():
                    if kind == "time_source":
                        ignored_time_count += 1
                        if not _TIME_SOURCE_PATTERN.fullmatch(expression.strip()):
                            raise ConversionError(
                                f"time_source({natural_term})格式不受支持："
                                f"{expression}"
                            )
                        continue
                    try:
                        self.compile_mapping(source, kind, expression)
                    except ConversionError as error:
                        raise ConversionError(
                            f"追踪对象“{source.natural_name}”的{kind}"
                            f"（{natural_term}）校验失败：{error}"
                        ) from error
                    mapping_count += 1
        return mapping_count, ignored_time_count


# ============================================================================
# 追溯文件读取与原子命题绑定
# ============================================================================


SOURCE_PATTERN = re.compile(
    r"^source\(\s*(?P<natural>[^,]+?)\s*,\s*"
    r"(?P<model>[^,)]+?)"
    r"(?:\s*,\s*(?P<instance>[^)]+?))?\s*\)\s*\{\s*$"
)

ENTRY_PATTERN = re.compile(
    r"^(?P<kind>state_source|condition_source|event_source|value_source|time_source)"
    r"\(\s*(?P<natural>[^,]+?)\s*,\s*(?P<expr>.+?)\s*\)\s*$"
)


def parse_trace_file(path: Path) -> list[TraceSource]:
    if not path.exists():
        raise FileNotFoundError(f"找不到追溯文件：{path}")

    sources: list[TraceSource] = []
    current: TraceSource | None = None

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith(("#", "--", "```")):
            continue

        source_match = SOURCE_PATTERN.match(line)
        if source_match:
            if current is not None:
                raise ConversionError(
                    f"追踪文件第{line_number}行开始了新source块，"
                    f"但对象“{current.natural_name}”尚未结束。"
                )
            module_name = source_match.group("model").strip()
            explicit_instance = source_match.group("instance")
            current = TraceSource(
                natural_name=clean_text(source_match.group("natural")),
                module_name=module_name,
                instance_name=(
                    explicit_instance.strip()
                    if explicit_instance
                    else None
                ),
            )
            sources.append(current)
            continue

        if line == "}":
            if current is None:
                raise ConversionError(
                    f"追踪文件第{line_number}行出现了多余的右花括号。"
                )
            current = None
            continue

        entry_match = ENTRY_PATTERN.match(line)
        if entry_match:
            if current is None:
                raise ConversionError(
                    f"追溯文件第{line_number}行的映射项不在source块内：{line}"
                )
            kind = entry_match.group("kind")
            natural = clean_text(entry_match.group("natural"))
            expression = entry_match.group("expr").strip()
            if natural in current.entries[kind]:
                raise ConversionError(
                    f"追踪文件第{line_number}行重复定义"
                    f"{kind}({natural})。"
                )
            current.entries[kind][natural] = expression
            continue

        raise ConversionError(
            f"无法识别追溯文件第{line_number}行：{line}"
        )

    if not sources:
        raise ConversionError("追溯文件中没有解析到任何source(...)块。")

    if current is not None:
        raise ConversionError(
            f"追踪对象“{current.natural_name}”的source块未以右花括号结束。"
        )

    return sources


class TraceResolver:
    def __init__(
        self,
        sources: Iterable[TraceSource],
        symbol_index: ModelSymbolIndex,
    ):
        self.sources = list(sources)
        self.symbol_index = symbol_index
        self.by_object: dict[str, TraceSource] = {}
        self.current_requirement_id: str | None = None
        self.binding_records: list[BindingRecord] = []

        for source in self.sources:
            key = clean_text(source.natural_name)
            if key in self.by_object:
                raise ConversionError(f"追溯文件存在重复对象：{key}")
            self.by_object[key] = source

    def begin_requirement(self, requirement_id: str) -> None:
        self.current_requirement_id = requirement_id

    def end_requirement(self) -> None:
        self.current_requirement_id = None

    def resolve_condition(self, phrase: str) -> str:
        kind_order = self._kind_order(phrase, role="condition")
        return self._resolve_phrase(phrase, kind_order)

    def resolve_result(self, phrase: str) -> str:
        kind_order = self._kind_order(phrase, role="result")
        return self._resolve_phrase(phrase, kind_order)

    def resolve_object_term(
        self,
        object_name: str,
        term: str,
        kind_order: tuple[str, ...],
    ) -> str:
        object_key = clean_text(object_name)
        source = self.by_object.get(object_key)
        if source is None:
            raise ConversionError(f"追溯文件中不存在对象：{object_name}")

        normalized_term = clean_text(term)

        # 第一阶段：严格按原始槽位名称匹配。
        #
        # kind_order 已由上下文决定。例如“收到……”优先查询
        # condition_source，“发送/发出……”优先查询 event_source。
        # 因此必须逐类查询并在首个类型命中时返回，不能把不同类型的
        # 同名或近义术语合并为歧义候选。
        for kind in kind_order:
            raw_expression = source.entries.get(kind, {}).get(normalized_term)
            if raw_expression is not None:
                return self._compile_and_record(
                    source,
                    kind,
                    raw_expression,
                    requested_term=normalized_term,
                    matched_term=normalized_term,
                    match_mode="exact",
                )

        # 第二阶段：兼容用户原有输入中的“进入可工作状态”、
        # “输出高负载工作状态”等动作+槽位写法。
        target_key = semantic_key(normalized_term)
        for kind in kind_order:
            matches_in_current_kind: list[tuple[str, str]] = []
            for natural, raw_expression in source.entries.get(kind, {}).items():
                natural_key = semantic_key(natural)
                if target_key and natural_key and target_key == natural_key:
                    matches_in_current_kind.append((natural, raw_expression))

            if len(matches_in_current_kind) == 1:
                matched_term, expression = matches_in_current_kind[0]
                return self._compile_and_record(
                    source,
                    kind,
                    expression,
                    requested_term=normalized_term,
                    matched_term=matched_term,
                    match_mode="normalized",
                )

            if len(matches_in_current_kind) > 1:
                candidates = "，".join(
                    f"{kind}({natural})"
                    for natural, _ in matches_in_current_kind
                )
                raise ConversionError(
                    f"需求槽位在同一映射类型内存在歧义："
                    f"对象=“{object_name}”，槽位=“{term}”，"
                    f"候选映射={candidates}。"
                )

        raise ConversionError(
            f"无法绑定需求槽位：对象=“{object_name}”，槽位=“{term}”。"
        )

    def _compile_and_record(
        self,
        source: TraceSource,
        kind: str,
        raw_expression: str,
        *,
        requested_term: str,
        matched_term: str,
        match_mode: Literal["exact", "normalized"],
    ) -> str:
        expression = self.symbol_index.compile_mapping(
            source,
            kind,
            raw_expression,
        )
        self.binding_records.append(
            BindingRecord(
                requirement_id=self.current_requirement_id or "<preflight>",
                object_name=source.natural_name,
                requested_term=requested_term,
                matched_term=matched_term,
                mapping_kind=kind,
                match_mode=match_mode,
                expression=expression,
            )
        )
        return expression

    def _resolve_phrase(
        self,
        phrase: str,
        kind_order: tuple[str, ...],
    ) -> str:
        items = bracket_items(phrase)
        if len(items) < 2:
            raise ConversionError(
                f"原子命题必须至少包含【对象】和【状态/事件/数值】两个槽位：{phrase}"
            )
        return self.resolve_object_term(items[0], items[-1], kind_order)

    @staticmethod
    def _kind_order(
        phrase: str,
        role: Literal["condition", "result"],
    ) -> tuple[str, ...]:
        phrase = clean_text(phrase)
        if "收到" in phrase:
            return (
                "condition_source",
                "event_source",
                "state_source",
                "value_source",
            )
        if "发送" in phrase or "发出" in phrase:
            return (
                "event_source",
                "condition_source",
                "state_source",
                "value_source",
            )
        if "输出" in phrase:
            return (
                "value_source",
                "event_source",
                "state_source",
                "condition_source",
            )
        if any(token in phrase for token in ("处于", "进入", "达到")):
            return (
                "state_source",
                "value_source",
                "condition_source",
                "event_source",
            )
        if role == "condition":
            return (
                "state_source",
                "condition_source",
                "event_source",
                "value_source",
            )
        return (
            "state_source",
            "value_source",
            "event_source",
            "condition_source",
        )


# ============================================================================
# CNL模板匹配和CTL/LTL生成
# ============================================================================


class RequirementConverter:
    def __init__(self, resolver: TraceResolver):
        self.resolver = resolver

    def convert(self, requirement: Requirement) -> GeneratedFormula:
        # 模板采用首次匹配原则。较具体的模板必须位于较一般模板之前。
        parsers = (
            self._parse_fixed_step_response,
            self._parse_explicit_eventual_response,
            self._parse_consistency,
            self._parse_unbounded_response,
            self._parse_until,
            self._parse_mutex,
            self._parse_eventually,
        )

        first_binding = len(self.resolver.binding_records)
        self.resolver.begin_requirement(requirement.req_id)
        try:
            for parser in parsers:
                generated = parser(requirement)
                if generated is not None:
                    return generated

            raise ConversionError(
                f"{requirement.req_id}未匹配任何受支持的CNL模板："
                f"{requirement.text}"
            )
        except Exception:
            # 不将转换失败的半成品绑定写入审计记录。
            del self.resolver.binding_records[first_binding:]
            raise
        finally:
            self.resolver.end_requirement()

    def _condition_expression(self, text: str) -> str:
        parts = split_condition(text)
        if not parts:
            raise ConversionError(f"空条件：{text}")

        connectors = set(parts[1::2])
        if len(connectors) > 1:
            raise ConversionError(
                f"同一条件中混用“且”和“或”会产生未声明的"
                f"优先级，请拆分需求或显式改写：{text}"
            )

        expression = self.resolver.resolve_condition(parts[0])
        index = 1
        while index < len(parts):
            if index + 1 >= len(parts):
                raise ConversionError(f"条件连接词后缺少原子命题：{text}")
            connector = parts[index]
            right = self.resolver.resolve_condition(parts[index + 1])
            operator = "&" if connector == "且" else "|"
            expression = f"{parenthesize(expression)} {operator} {parenthesize(right)}"
            index += 2
        return expression

    def _result_expression(self, target: str, result: str) -> str:
        return self.resolver.resolve_result(target + result)

    def _parse_fixed_step_response(
        self,
        requirement: Requirement,
    ) -> GeneratedFormula | None:
        match = re.match(
            r"^当(?P<condition>.+?)后，?"
            r"(?P<target>.+?)"
            r"一定在"
            r"(?P<steps>【?\d+】?)步后"
            r"(?P<result>.+)$",
            requirement.text,
        )
        if not match:
            return None

        condition = self._condition_expression(match.group("condition"))
        result = self._result_expression(
            match.group("target"),
            match.group("result"),
        )
        steps = normalize_steps(match.group("steps"))
        temporal_result = nested_next("AX", result, steps)

        formula = (
            f"SPEC AG ({parenthesize(condition)} -> {temporal_result});"
        )
        return GeneratedFormula(
            req_id=requirement.req_id,
            source_text=requirement.text,
            pattern_type="固定步响应",
            logic="CTL",
            formula=formula,
            trigger_condition=condition,
        )

    def _parse_explicit_eventual_response(
        self,
        requirement: Requirement,
    ) -> GeneratedFormula | None:
        # 保留用户原输入：“当P时/后，Q最终一定会R”。
        match = re.match(
            r"^当(?P<condition>.+?)(?:时|后)，?"
            r"(?P<target>.+?)"
            r"(?:最终一定会|最终会)"
            r"(?P<result>.+)$",
            requirement.text,
        )
        if not match:
            return None

        condition = self._condition_expression(match.group("condition"))
        result = self._result_expression(
            match.group("target"),
            match.group("result"),
        )
        formula = (
            f"LTLSPEC G ({parenthesize(condition)} -> "
            f"F {parenthesize(result)});"
        )
        return GeneratedFormula(
            req_id=requirement.req_id,
            source_text=requirement.text,
            pattern_type="最终响应",
            logic="LTL",
            formula=formula,
            trigger_condition=condition,
        )

    def _parse_consistency(
        self,
        requirement: Requirement,
    ) -> GeneratedFormula | None:
        match = re.match(
            r"^当(?P<condition>.+?)时，?"
            r"(?P<target>.+?)"
            r"(?P<mode>不应|应|不会|会)"
            r"(?P<result>.+)$",
            requirement.text,
        )
        if not match:
            return None

        condition = self._condition_expression(match.group("condition"))
        result = self._result_expression(
            match.group("target"),
            match.group("result"),
        )
        if match.group("mode") in {"不应", "不会"}:
            result = negate(result)

        formula = (
            f"LTLSPEC G ({parenthesize(condition)} -> {parenthesize(result)});"
        )
        return GeneratedFormula(
            req_id=requirement.req_id,
            source_text=requirement.text,
            pattern_type="当前状态一致性",
            logic="LTL",
            formula=formula,
            trigger_condition=condition,
        )

    def _parse_unbounded_response(
        self,
        requirement: Requirement,
    ) -> GeneratedFormula | None:
        # 保留用户原输入：“当P后，Q应进入/应发出R”。
        match = re.match(
            r"^当(?P<condition>.+?)后，?"
            r"(?P<target>.+?)"
            r"(?P<mode>不应|应|不会|会)"
            r"(?P<result>.+)$",
            requirement.text,
        )
        if not match:
            return None

        if match.group("mode") in {"不应", "不会"}:
            raise ConversionError(
                f"{requirement.req_id}使用了触发后的否定响应，但其语义可能是"
                "“最终不发生”或“始终不发生”，需要单独模板明确。"
            )

        condition = self._condition_expression(match.group("condition"))
        result = self._result_expression(
            match.group("target"),
            match.group("result"),
        )
        formula = (
            f"LTLSPEC G ({parenthesize(condition)} -> "
            f"F {parenthesize(result)});"
        )
        return GeneratedFormula(
            req_id=requirement.req_id,
            source_text=requirement.text,
            pattern_type="无界最终响应",
            logic="LTL",
            formula=formula,
            trigger_condition=condition,
        )

    def _parse_until(
        self,
        requirement: Requirement,
    ) -> GeneratedFormula | None:
        if "直到" not in requirement.text:
            return None

        left, right = requirement.text.split("直到", 1)
        if not left or not right:
            raise ConversionError(f"{requirement.req_id}的“直到”模板不完整。")

        hold_expression = self.resolver.resolve_condition(left)
        stop_expression = self._condition_expression(right)
        formula = (
            f"LTLSPEC G ({parenthesize(hold_expression)} -> "
            f"({parenthesize(hold_expression)} U {parenthesize(stop_expression)}));"
        )
        return GeneratedFormula(
            req_id=requirement.req_id,
            source_text=requirement.text,
            pattern_type="状态持续（强直到）",
            logic="LTL",
            formula=formula,
            trigger_condition=hold_expression,
        )

    def _parse_mutex(
        self,
        requirement: Requirement,
    ) -> GeneratedFormula | None:
        match = re.match(
            r"^(?P<subject>.+?)不会同时处于"
            r"(?P<first>.+?)和(?P<second>.+)$",
            requirement.text,
        )
        if not match:
            return None

        subject_items = bracket_items(match.group("subject"))
        first_items = bracket_items(match.group("first"))
        second_items = bracket_items(match.group("second"))
        if len(subject_items) != 1 or not first_items or not second_items:
            raise ConversionError(f"{requirement.req_id}的互斥模板槽位不完整。")

        subject = subject_items[0]
        kind_order = (
            "state_source",
            "value_source",
            "condition_source",
            "event_source",
        )
        first = self.resolver.resolve_object_term(
            subject,
            first_items[-1],
            kind_order,
        )
        second = self.resolver.resolve_object_term(
            subject,
            second_items[-1],
            kind_order,
        )

        warnings: list[str] = []
        first_assignment = parse_simple_assignment(first)
        second_assignment = parse_simple_assignment(second)
        if (
            first_assignment
            and second_assignment
            and first_assignment[0] == second_assignment[0]
            and first_assignment[2] != second_assignment[2]
        ):
            warnings.append(
                "两个互斥命题是同一枚举变量的不同取值，该规约在单值变量"
                "语义下恒真，不能作为有效缺陷检测规约。"
            )

        formula = (
            f"LTLSPEC G (!({parenthesize(first)} & {parenthesize(second)}));"
        )
        return GeneratedFormula(
            req_id=requirement.req_id,
            source_text=requirement.text,
            pattern_type="互斥约束",
            logic="LTL",
            formula=formula,
            warnings=tuple(warnings),
        )

    def _parse_eventually(
        self,
        requirement: Requirement,
    ) -> GeneratedFormula | None:
        match = re.match(
            r"^(?P<subject>.+?)一定会(?:达到|进入)(?P<goal>.+)$",
            requirement.text,
        )
        if not match:
            return None

        goal = self.resolver.resolve_result(
            match.group("subject") + match.group("goal")
        )
        formula = f"LTLSPEC F {parenthesize(goal)};"
        return GeneratedFormula(
            req_id=requirement.req_id,
            source_text=requirement.text,
            pattern_type="最终可达性",
            logic="LTL",
            formula=formula,
        )


def parse_simple_assignment(
    expression: str,
) -> tuple[str, str, str] | None:
    match = re.fullmatch(
        r"(?P<name>[A-Za-z_][A-Za-z0-9_.]*)\s*"
        r"(?P<operator>=|!=|>=|<=|>|<)\s*"
        r"(?P<value>.+)",
        expression.strip(),
    )
    if not match:
        return None
    return (
        match.group("name"),
        match.group("operator"),
        match.group("value").strip(),
    )


# ============================================================================
# 输出与主程序
# ============================================================================


def coverage_property_name(requirement_id: str) -> str:
    """将需求编号转换为合法且易识别的 nuXmv 属性名。"""
    safe_id = re.sub(r"[^A-Za-z0-9_]", "_", requirement_id.strip())
    safe_id = re.sub(r"_+", "_", safe_id).strip("_")
    if not safe_id:
        raise ConversionError(f"无法由需求编号生成覆盖属性名：{requirement_id!r}")
    return f"COV_{safe_id}"


def trigger_coverage_statement(formula: GeneratedFormula) -> str | None:
    """为触发型规约生成 EF(P)；非触发型规约返回 None。"""
    if not formula.trigger_condition:
        return None
    name = coverage_property_name(formula.req_id)
    condition = parenthesize(formula.trigger_condition)
    return f"CTLSPEC NAME {name} := EF {condition};"


def formalize_requirements(
    requirements_path: Path,
    trace_path: Path,
    model_path: Path,
    *,
    strict: bool = True,
) -> FormalizationResult:
    """执行需求形式化及模型约束绑定。

    处理顺序为：解析X模型并构建符号索引，校验完整追踪
    配置，然后仅对通过校验的原子命题执行CNL模板组装。
    strict=True时任一需求失败都不返回部分结果。
    """

    requirements = read_requirements(requirements_path)
    trace_sources = parse_trace_file(trace_path)
    symbol_index = ModelSymbolIndex.from_model_file(model_path)
    mapping_count, ignored_time_count = symbol_index.validate_trace_sources(
        trace_sources
    )

    resolver = TraceResolver(trace_sources, symbol_index)
    converter = RequirementConverter(resolver)
    formulas: list[GeneratedFormula] = []
    errors: list[str] = []

    for requirement in requirements:
        try:
            formulas.append(converter.convert(requirement))
        except (ConversionError, ValueError) as error:
            errors.append(f"{requirement.req_id}: {error}")

    if errors and strict:
        details = "\n".join(f"  - {error}" for error in errors)
        raise ConversionError(
            f"共有{len(errors)}条需求转换失败，未生成部分结果：\n{details}"
        )

    return FormalizationResult(
        formulas=tuple(formulas),
        mapping_count=mapping_count,
        ignored_time_mapping_count=ignored_time_count,
        binding_records=tuple(resolver.binding_records),
        errors=tuple(errors),
    )


def render_output(
    result: FormalizationResult,
    requirements_path: Path,
    trace_path: Path,
    model_path: Path,
) -> str:
    formulas = list(result.formulas)
    ctl_count = sum(formula.logic == "CTL" for formula in formulas)
    ltl_count = sum(formula.logic == "LTL" for formula in formulas)
    warning_count = sum(len(formula.warnings) for formula in formulas)
    coverage_formulas = [
        formula for formula in formulas if formula.trigger_condition
    ]

    coverage_names: dict[str, str] = {}
    for formula in coverage_formulas:
        name = coverage_property_name(formula.req_id)
        previous_id = coverage_names.get(name)
        if previous_id is not None and previous_id != formula.req_id:
            raise ConversionError(
                "需求编号在转换为覆盖属性名后发生冲突："
                f"{previous_id!r} 与 {formula.req_id!r} 均对应 {name!r}。"
            )
        coverage_names[name] = formula.req_id

    lines = [
        "-- ==================================================================",
        "-- 由结构化CNL需求自动生成的nuXmv规约",
        f"-- 需求文件：{requirements_path.name}",
        f"-- 追溯文件：{trace_path.name}",
        f"-- X模型文件：{model_path.name}",
        f"-- 通过模型约束校验的追踪映射：{result.mapping_count}",
        f"-- 仅做兼容性语法检查的time_source："
        f"{result.ignored_time_mapping_count}（不参与本文模板绑定）",
        f"-- 实际需求槽位绑定：{len(result.binding_records)}",
        f"-- 规约总数：{len(formulas)}（CTL={ctl_count}, LTL={ltl_count}）",
        f"-- 触发可达性检查：{len(coverage_formulas)}（不计入正式规约总数）",
        f"-- 诊断警告：{warning_count}",
        "-- ==================================================================",
        "",
    ]

    for formula in formulas:
        lines.append(f"-- [{formula.req_id}] {formula.pattern_type} / {formula.logic}")
        lines.append(f"-- 原始需求：{formula.source_text}")
        for warning in formula.warnings:
            lines.append(f"-- WARNING: {warning}")
        lines.append(formula.formula)
        lines.append("")

    lines.extend(
        [
            "-- ==================================================================",
            "-- 触发可达性检查（仅用于空触发预警，不计入正式需求规约）",
            "-- ==================================================================",
            "",
        ]
    )
    for formula in coverage_formulas:
        lines.append(
            f"-- [TRIGGER-COVERAGE {formula.req_id}] {formula.pattern_type}"
        )
        lines.append(f"-- 触发条件：{formula.trigger_condition}")
        coverage_statement = trigger_coverage_statement(formula)
        if coverage_statement is not None:
            lines.append(coverage_statement)
        lines.append("")

    # 在详细输出之后集中追加一份纯规约复制区。这里不写需求编号、原始需求
    # 或诊断警告，便于直接复制到现有的 nuXmv 模型中。边界标记采用
    # nuXmv 注释语法，即使一并复制也不会影响模型解析。
    lines.extend(
        [
            "-- ==================================================================",
            "-- BEGIN: 可直接复制到nuXmv模型的完整规约与覆盖检查",
            "-- 注意：正式规约与覆盖检查分别统计；本区仅用于集中复制。",
            "-- ==================================================================",
            "-- 正式需求规约",
        ]
    )
    lines.extend(formula.formula for formula in formulas)
    lines.extend(
        [
            "",
            "-- 触发可达性检查（不计入正式规约总数）",
        ]
    )
    lines.extend(
        statement
        for formula in coverage_formulas
        if (statement := trigger_coverage_statement(formula)) is not None
    )
    lines.extend(
        [
            "-- ==================================================================",
            "-- END: 可直接复制到nuXmv模型的完整规约与覆盖检查",
            "-- ==================================================================",
            "",
        ]
    )

    return "\n".join(lines).rstrip() + "\n"


def write_text_atomic(path: Path, text: str) -> None:
    """先写入同目录临时文件，成功后再替换目标文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> None:
    print("开始转换CNL需求……")
    print(f"脚本版本：{SCRIPT_VERSION}")
    print(f"脚本位置：{Path(__file__).resolve()}")
    print(f"需求文件：{REQUIREMENTS_FILE}")
    print(f"追溯文件：{TRACE_FILE}")
    print(f"X模型文件：{X_MODEL_FILE}")

    requirements = read_requirements(REQUIREMENTS_FILE)
    result = formalize_requirements(
        REQUIREMENTS_FILE,
        TRACE_FILE,
        X_MODEL_FILE,
        strict=STRICT_MODE,
    )
    formulas = list(result.formulas)
    output_text = render_output(
        result,
        REQUIREMENTS_FILE,
        TRACE_FILE,
        X_MODEL_FILE,
    )
    write_text_atomic(OUTPUT_FILE, output_text)

    ctl_count = sum(formula.logic == "CTL" for formula in formulas)
    ltl_count = sum(formula.logic == "LTL" for formula in formulas)
    coverage_count = sum(
        formula.trigger_condition is not None for formula in formulas
    )
    warnings = [
        (formula.req_id, warning)
        for formula in formulas
        for warning in formula.warnings
    ]

    print("")
    print("转换完成。")
    print(f"成功转换：{len(formulas)}/{len(requirements)}")
    print(f"模型约束校验映射：{result.mapping_count}")
    print(
        "time_source兼容项："
        f"{result.ignored_time_mapping_count}（不参与当前模板绑定）"
    )
    print(f"实际需求槽位绑定：{len(result.binding_records)}")
    exact_count = sum(
        record.match_mode == "exact" for record in result.binding_records
    )
    normalized_count = len(result.binding_records) - exact_count
    print(f"严格名称匹配：{exact_count}")
    print(f"确定性术语归一匹配：{normalized_count}")
    print(f"CTL规约：{ctl_count}")
    print(f"LTL规约：{ltl_count}")
    print(f"触发可达性检查：{coverage_count}（不计入正式规约总数）")
    print(f"输出文件：{OUTPUT_FILE}")

    if result.errors:
        print(f"跳过的需求：{len(result.errors)}")
        for error in result.errors:
            print(f"  - {error}")

    if warnings:
        print("")
        print("语义警告：")
        for req_id, warning in warnings:
            print(f"  - {req_id}: {warning}")


def run() -> int:
    exit_code = 0
    try:
        main()
    except Exception as error:  # 保留完整错误信息，便于右键运行时检查。
        exit_code = 1
        print("")
        print("转换失败：")
        print(error)
    finally:
        if PAUSE_AFTER_RUN:
            try:
                input("\n按回车键关闭……")
            except EOFError:
                pass
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run())
