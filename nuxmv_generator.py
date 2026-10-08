import re
from decimal import Decimal, InvalidOperation


class NuXMVGenerator:
    """
    将当前项目的离散 X 模型 IR 转换为 nuXmv 模型。

    端口编码约定
    ------------
    1. 输入端口统一接收两个形参：
       - in_<p>_value：最近一次载荷；
       - in_<p>_valid：当前状态是否存在一次新的事件到达。

       同时生成派生符号 in_<p>。它只在 valid 为 TRUE 时呈现载荷，
       否则返回空闲值，供既有规约作为“单步事件/数据视图”使用。

    2. 通过 send(p, value) 更新的输出端口采用事件传输机制：
       - out_<p>_value：持久载荷；
       - out_<p>_valid：单步有效位；
       - out_<p>：由端口的“规约观察语义”决定是单步视图还是持久视图。

    3. 通过 p = value 更新的输出端口采用持续数据传输机制：
       - out_<p>：持久数据；
       - 耦合时将 TRUE 作为其 valid 形参，使接收端公开视图持续可见。

    4. “传输机制”和“规约观察语义”彼此独立：
       - send(voltage, 3) 仍可作为一次传输，但 out_voltage 对规约保持
         最近值，用于表达持续电压；
       - send(evHighPowerOn, TRUE) 的 out_evHighPowerOn 对规约只在
         valid=TRUE 的当前状态中可见。

    端口观察语义优先读取 IR 的 semantic_kind/signal_kind/view_mode/
    is_event；现有 IR 没有这些字段时，以端口名是否以 ev 开头作为兼容
    规则。也可以在构造生成器时传入 event_view_predicate 覆盖该规则。
    """

    _SEND_PATTERN = re.compile(
        r"^send\s*\(\s*([A-Za-z_]\w*)\s*,\s*(.*?)\s*\)\s*;?\s*$",
        re.IGNORECASE | re.DOTALL,
    )
    _ASSIGNMENT_PATTERN = re.compile(
        r"^\s*([A-Za-z_]\w*)\s*=(?!=)\s*(.*?)\s*;?\s*$",
        re.DOTALL,
    )
    _RECEIVE_PATTERN = re.compile(
        r"^receive\s*\(\s*([A-Za-z_]\w*)\s*\)\s*$",
        re.IGNORECASE,
    )
    _TIMEOVER_PATTERN = re.compile(
        r"^timeover(?:\s*\(\s*\))?$",
        re.IGNORECASE,
    )
    _DECIMAL_LITERAL_PATTERN = re.compile(
        r"(?<![\w.])[-+]?(?:\d+\.\d*|\.\d+)"
        r"(?:[eE][+-]?\d+)?(?![\w.])"
    )

    def __init__(self, event_view_predicate=None):
        self.code = []
        self.event_view_predicate = event_view_predicate

        # generate_coupled 根据这里记录的声明顺序组装模块实参。
        # 主程序须先生成 discrete，再生成 couple。
        self.input_ports_by_model = {}

        # 记录每个离散模型输出端口的语义：event 或 data。
        # 耦合层据此决定传递 raw value + valid，还是 data + TRUE。
        self.output_port_modes_by_model = {}

        # 记录公开端口是单步事件视图还是持久数据视图。
        self.port_view_modes_by_model = {}

        # 记录哪些输入端口被 receive(...) 用作事件触发器，以便耦合时
        # 拒绝把持续数据端口连接到事件接收触发器。
        self.receive_ports_by_model = {}

    def emit(self, text: str, indent: int = 0):
        self.code.append("    " * indent + text)

    @staticmethod
    def _datatype_name(port) -> str:
        return str(port.datatype).strip().lower()

    def _idle_value(self, port) -> str:
        return (
            "0"
            if self._datatype_name(port) in ("int", "real")
            else "FALSE"
        )

    def _smv_port_type(self, port, numeric_domains) -> str:
        if self._datatype_name(port) in ("int", "real"):
            lower_bound, upper_bound = numeric_domains[port.name]
            if lower_bound == upper_bound:
                return f"{{{lower_bound}}}"
            return f"{lower_bound}..{upper_bound}"
        return "boolean"

    @staticmethod
    def _normalise_action_item(action_item):
        """兼容 (action, guard) 和旧版单独动作字符串。"""
        if isinstance(action_item, (tuple, list)):
            if not action_item:
                return "", None
            action_text = action_item[0]
            action_guard = action_item[1] if len(action_item) > 1 else None
        else:
            action_text = action_item
            action_guard = None

        return str(action_text).strip().rstrip(";"), action_guard

    def _iter_actions(self, model):
        for state in model.states:
            for transition in state.transitions:
                for action_item in transition.actions:
                    action_text, action_guard = self._normalise_action_item(
                        action_item
                    )
                    if action_text:
                        yield state, transition, action_text, action_guard

    def _parse_action(self, action_text: str):
        """
        返回 (kind, target, value)，kind 为 send 或 assignment。
        无法识别的动作返回 None。
        """
        text = str(action_text).strip().rstrip(";")

        send_match = self._SEND_PATTERN.fullmatch(text)
        if send_match:
            value = send_match.group(2).strip()
            if not value:
                return None
            return "send", send_match.group(1), value

        assignment_match = self._ASSIGNMENT_PATTERN.fullmatch(text)
        if assignment_match:
            target = assignment_match.group(1).strip()
            value = assignment_match.group(2).strip()
            if not value:
                return None
            if target.startswith("out_"):
                target = target[4:]
            return (
                "assignment",
                target,
                value,
            )

        return None

    @staticmethod
    def _declared_output_mode(port):
        """
        可选地读取 IR 中显式声明的输出传输机制。

        该模式仅回答“由 send 还是直接赋值更新”，不决定规约看到的是
        单步值还是持久值。
        """
        for attribute in ("transport_mode", "update_mode"):
            value = getattr(port, attribute, None)
            if value is None:
                continue

            normalised = str(value).strip().lower()
            if normalised in {"event", "send", "pulse", "message"}:
                return "event"
            if normalised in {"data", "assignment", "persistent", "state"}:
                return "data"

        return None

    @staticmethod
    def _declared_view_mode(port):
        """读取 IR 中可选的公开观察语义声明。"""
        for attribute in (
            "semantic_kind",
            "signal_kind",
            "view_mode",
        ):
            value = getattr(port, attribute, None)
            if value is None:
                continue

            normalised = str(value).strip().lower()
            if normalised in {"event", "pulse", "message"}:
                return "event"
            if normalised in {"data", "persistent", "state", "value"}:
                return "data"

        is_event = getattr(port, "is_event", None)
        if isinstance(is_event, bool):
            return "event" if is_event else "data"

        return None

    def _port_view_mode(self, port):
        """
        决定原端口名在规约中表示单步事件还是持久数据。

        当前 FMCS 模型以 ev... 命名事件，以 voltage/current 等名称命名
        持续数据。若项目以后不再采用该命名约定，应在 IR 上显式设置
        semantic_kind，或向生成器传入 event_view_predicate。
        """
        if self.event_view_predicate is not None:
            return (
                "event"
                if bool(self.event_view_predicate(port))
                else "data"
            )

        declared_mode = self._declared_view_mode(port)
        if declared_mode is not None:
            return declared_mode

        return (
            "event"
            if str(port.name).strip().lower().startswith("ev")
            else "data"
        )

    def _infer_output_port_modes(self, model):
        """
        推导每个输出端口是一次性事件还是持续数据。

        - send(p, value) -> event
        - p = value       -> data
        - 没有任何更新    -> event（保守默认）

        “无更新默认 event”很重要：若故障注入删除某事件端口唯一的 send，
        该端口仍保持 valid=FALSE，而不会被误当成持续有效的数据输入。
        若 IR 已显式声明端口模式，则优先采用声明并检查动作是否一致。
        """
        output_ports = {
            p.name: p
            for p in model.ports
            if p.direction == "eventoutput"
        }
        observed_kinds = {name: set() for name in output_ports}

        for _, _, action_text, _ in self._iter_actions(model):
            parsed = self._parse_action(action_text)
            if parsed is None:
                raise ValueError(
                    f"组件 {model.name} 包含当前转换器不支持的动作："
                    f"{action_text}"
                )

            kind, target, _ = parsed
            if target in observed_kinds:
                observed_kinds[target].add(kind)

        modes = {}
        for port_name, port in output_ports.items():
            kinds = observed_kinds[port_name]

            if kinds == {"send", "assignment"}:
                raise ValueError(
                    f"组件 {model.name} 的输出端口 {port_name} 同时使用 "
                    "send 和直接赋值，无法确定其事件/数据语义"
                )

            inferred_mode = (
                "event"
                if not kinds or kinds == {"send"}
                else "data"
            )
            declared_mode = self._declared_output_mode(port)

            if declared_mode is not None and kinds:
                action_mode = "event" if kinds == {"send"} else "data"
                if declared_mode != action_mode:
                    raise ValueError(
                        f"组件 {model.name} 的输出端口 {port_name} "
                        f"声明为 {declared_mode}，但实际使用 {action_mode} "
                        "更新方式"
                    )

            modes[port_name] = declared_mode or inferred_mode

        return modes

    def _parameter_value_map(self, model):
        """返回当前离散模型中可在编译期读取的常量参数。"""
        return {
            v.name: str(v.init_value).strip()
            for v in model.variables
            if v.kind == "parameter" and v.init_value is not None
        }

    def _resolve_integer_constant(self, expr, model):
        """
        将整数字面量或直接引用的常量参数解析为 Python 整数。

        支持：3、3.0、-2、H（H 的初始化值仍须是可解析整数）。
        不支持：H + 1、输入变量表达式、非整数实数等动态表达式。
        无法静态解析时返回 None，由调用位置给出包含模型上下文的错误。
        """
        if expr is None:
            return None

        text = str(expr).strip().rstrip(";")
        parameters = self._parameter_value_map(model)
        visited = set()

        while text in parameters:
            if text in visited:
                return None
            visited.add(text)
            text = parameters[text].strip()

        try:
            value = Decimal(text)
        except (InvalidOperation, ValueError):
            return None

        if not value.is_finite():
            return None

        if value != value.to_integral_value():
            return None

        return int(value)

    def _infer_numeric_output_domains(self, model):
        """
        根据数值输出端口的初值和动作中的常量值推导有限声明区间。

        本函数同时支持 send(current, 18)、current = 18 和
        out_current = 18，但不修改 IR。
        """
        numeric_ports = {
            p.name
            for p in model.ports
            if p.direction == "eventoutput"
            and self._datatype_name(p) in ("int", "real")
        }

        observed_values = {
            port_name: {0}
            for port_name in numeric_ports
        }

        for _, _, action_text, _ in self._iter_actions(model):
            parsed = self._parse_action(action_text)
            if parsed is None:
                raise ValueError(
                    f"组件 {model.name} 包含当前转换器不支持的动作："
                    f"{action_text}"
                )

            _, target_port, value_expr = parsed
            if target_port not in observed_values:
                continue

            value = self._resolve_integer_constant(value_expr, model)
            if value is None:
                raise ValueError(
                    f"组件 {model.name} 的数值输出端口 {target_port} "
                    f"包含无法静态解析的赋值：{action_text}"
                )

            observed_values[target_port].add(value)

        domains = {}
        for port_name, values in observed_values.items():
            lower_bound = min(values)
            upper_bound = max(values)

            domains[port_name] = (lower_bound, upper_bound)

        return domains

    def _infer_numeric_variable_domains(self, model):
        """
        根据内部数值变量的初值和常量赋值推导有限声明区间。

        当前转换范围仅接受整数字面量或可静态解析为整数的常量参数。
        一般算术更新、输入依赖表达式和非整数实数由本函数显式拒绝，
        避免使用与源模型无关的固定默认区间。
        """
        numeric_variables = {
            variable.name: variable
            for variable in model.variables
            if variable.kind == "value"
            and str(variable.datatype).strip().lower() in ("int", "real")
        }
        observed_values = {
            variable_name: set()
            for variable_name in numeric_variables
        }

        for variable_name, variable in numeric_variables.items():
            if variable.init_value is None:
                raise ValueError(
                    f"组件 {model.name} 的数值变量 {variable_name} "
                    "缺少可用于有限域推导的初值"
                )

            initial_value = self._resolve_integer_constant(
                variable.init_value,
                model,
            )
            if initial_value is None:
                raise ValueError(
                    f"组件 {model.name} 的数值变量 {variable_name} "
                    f"包含无法静态解析的初值：{variable.init_value}"
                )
            observed_values[variable_name].add(initial_value)

        for _, _, action_text, _ in self._iter_actions(model):
            parsed = self._parse_action(action_text)
            if parsed is None:
                raise ValueError(
                    f"组件 {model.name} 包含当前转换器不支持的动作："
                    f"{action_text}"
                )

            action_kind, target, value_expr = parsed
            if target not in observed_values:
                continue

            if action_kind != "assignment":
                raise ValueError(
                    f"组件 {model.name} 的内部变量 {target} "
                    f"不能通过 send 动作更新：{action_text}"
                )

            value = self._resolve_integer_constant(value_expr, model)
            if value is None:
                raise ValueError(
                    f"组件 {model.name} 的数值变量 {target} "
                    f"包含当前转换范围不支持的动态或非整数赋值："
                    f"{action_text}"
                )
            observed_values[target].add(value)

        domains = {}
        for variable_name, values in observed_values.items():
            lower_bound = min(values)
            upper_bound = max(values)

            domains[variable_name] = (lower_bound, upper_bound)

        return domains

    def _translate_expr(self, expr: str, in_ports: list = None) -> str:
        if expr is None or not str(expr).strip():
            return ""

        expr = str(expr)
        expr = expr.replace("==", "=")
        expr = re.sub(r"\band\b", "&", expr, flags=re.IGNORECASE)
        expr = re.sub(r"\bor\b", "|", expr, flags=re.IGNORECASE)
        expr = re.sub(r"\bnot\b", "!", expr, flags=re.IGNORECASE)
        expr = re.sub(r"\btrue\b", "TRUE", expr, flags=re.IGNORECASE)
        expr = re.sub(r"\bfalse\b", "FALSE", expr, flags=re.IGNORECASE)
        def normalise_decimal(match):
            literal = match.group(0)
            try:
                value = Decimal(literal)
            except (InvalidOperation, ValueError) as error:
                raise ValueError(f"无法解析数值字面量：{literal}") from error

            if not value.is_finite() or value != value.to_integral_value():
                raise ValueError(
                    "当前有限状态转换仅支持整数取值，不允许将非整数"
                    f"字面量 {literal} 静默截断"
                )

            return str(int(value))

        expr = self._DECIMAL_LITERAL_PATTERN.sub(normalise_decimal, expr)

        if in_ports:
            for port in in_ports:
                # 组件内部行为读取最近一次持久载荷；公开的 in_<port>
                # 则是供规约观察的单步视图。
                expr = re.sub(
                    rf"\b{re.escape(port)}\b",
                    f"in_{port}_value",
                    expr,
                )

        return expr

    def _build_condition(self, model, state, transition, in_ports):
        conds = [f"state = {state.name}"]
        trigger = str(transition.trigger or "").strip()

        if not trigger:
            pass

        elif self._TIMEOVER_PATTERN.fullmatch(trigger):
            hold_time = str(state.hold_time).strip().lower()

            if hold_time == "infinite":
                return "FALSE"

            conds.append(
                f"timer >= "
                f"{self._translate_expr(state.hold_time, in_ports)}"
            )

        else:
            receive_match = self._RECEIVE_PATTERN.fullmatch(trigger)
            if receive_match:
                port_name = receive_match.group(1)
                if port_name not in in_ports:
                    raise ValueError(
                        f"组件 {model.name} 的转移引用了未声明输入端口："
                        f"receive({port_name})"
                    )

                # receive(port) 只由当前步的新事件触发。
                conds.append(f"in_{port_name}_valid = TRUE")
            else:
                raise ValueError(
                    f"组件 {model.name} 的状态 {state.name} 包含当前转换器"
                    f"不支持的触发器：{trigger}"
                )

        if transition.guard:
            conds.append(
                self._translate_expr(transition.guard, in_ports)
            )

        return " & ".join(conds)

    def _collect_receive_ports(self, model):
        receive_ports = set()
        for state in model.states:
            for transition in state.transitions:
                trigger = str(transition.trigger or "").strip()
                match = self._RECEIVE_PATTERN.fullmatch(trigger)
                if match:
                    receive_ports.add(match.group(1))
        return receive_ports

    @staticmethod
    def _event_storage_name(port_name: str) -> str:
        return f"out_{port_name}_value"

    @staticmethod
    def _data_storage_name(port_name: str) -> str:
        return f"out_{port_name}"

    def generate_discrete(self, model):
        self.code.append(
            "\n---------------------------------------------------------"
        )
        self.code.append(f"-- MODULE: {model.name}")
        self.code.append(
            "---------------------------------------------------------"
        )

        state_names = [state.name for state in model.states]
        if not state_names:
            raise ValueError(f"组件 {model.name} 没有可生成的离散状态")

        input_port_objects = [
            port
            for port in model.ports
            if port.direction == "eventinput"
        ]
        in_ports = [port.name for port in input_port_objects]
        self.input_ports_by_model[model.name] = list(in_ports)
        self.receive_ports_by_model[model.name] = self._collect_receive_ports(
            model
        )

        output_port_objects = [
            port
            for port in model.ports
            if port.direction == "eventoutput"
        ]
        output_port_modes = self._infer_output_port_modes(model)
        self.output_port_modes_by_model[model.name] = dict(
            output_port_modes
        )

        port_view_modes = {
            port.name: self._port_view_mode(port)
            for port in model.ports
            if port.direction in ("eventinput", "eventoutput")
        }
        self.port_view_modes_by_model[model.name] = dict(port_view_modes)

        # 事件观察语义必须能够获得有效位。直接赋值型输出没有事件脉冲，
        # 因此不能暴露为单步事件视图。
        for port in output_port_objects:
            if (
                port_view_modes[port.name] == "event"
                and output_port_modes[port.name] == "data"
            ):
                raise ValueError(
                    f"组件 {model.name} 的输出端口 {port.name} 被声明/命名为"
                    "事件视图，但仅使用直接赋值更新；请改用 send，或将该"
                    "端口显式声明为 data 视图"
                )

        params_list = []
        for port_name in in_ports:
            params_list.extend(
                [
                    f"in_{port_name}_value",
                    f"in_{port_name}_valid",
                ]
            )

        params = f"({', '.join(params_list)})" if params_list else ""
        self.emit(f"MODULE {model.name}{params}")

        # ================================================================
        # 1. 变量声明及局部计时器上界。
        # ================================================================
        self.emit("VAR")
        self.emit(f"state : {{{', '.join(state_names)}}};", 1)

        finite_hold_times = []
        for state in model.states:
            hold_time = str(state.hold_time).strip()

            if hold_time.lower() == "infinite":
                continue

            resolved_time = self._resolve_integer_constant(hold_time, model)
            if resolved_time is None:
                raise ValueError(
                    f"组件 {model.name} 的状态 {state.name} "
                    f"包含无法静态解析的驻留时间：{hold_time}"
                )
            if resolved_time < 0:
                raise ValueError(
                    f"组件 {model.name} 的状态 {state.name} "
                    f"包含负驻留时间：{hold_time}"
                )

            finite_hold_times.append(resolved_time)

        h_max = max(finite_hold_times + [1])
        self.emit(f"timer : 0..{h_max};", 1)

        numeric_output_domains = self._infer_numeric_output_domains(model)
        numeric_variable_domains = self._infer_numeric_variable_domains(
            model
        )

        for port in output_port_objects:
            port_type = self._smv_port_type(
                port,
                numeric_output_domains,
            )
            mode = output_port_modes[port.name]

            if mode == "event":
                self.emit(
                    f"{self._event_storage_name(port.name)} : "
                    f"{port_type};",
                    1,
                )
                self.emit(
                    f"out_{port.name}_valid : boolean;",
                    1,
                )
            else:
                self.emit(
                    f"{self._data_storage_name(port.name)} : "
                    f"{port_type};",
                    1,
                )

        # 内部数值变量的有限域由源模型初值和常量更新推导。
        for variable in model.variables:
            if variable.kind == "value":
                if str(variable.datatype).strip().lower() in ("int", "real"):
                    lower_bound, upper_bound = numeric_variable_domains[
                        variable.name
                    ]
                    variable_type = (
                        f"{{{lower_bound}}}"
                        if lower_bound == upper_bound
                        else f"{lower_bound}..{upper_bound}"
                    )
                else:
                    variable_type = "boolean"
                self.emit(f"{variable.name} : {variable_type};", 1)

        # ================================================================
        # 2. 输入和事件输出的公开单步视图。
        # ================================================================
        parameter_defines = [
            variable
            for variable in model.variables
            if variable.kind == "parameter"
        ]
        transported_event_output_objects = [
            port
            for port in output_port_objects
            if output_port_modes[port.name] == "event"
        ]

        if (
            input_port_objects
            or transported_event_output_objects
            or parameter_defines
        ):
            self.emit("DEFINE")

            for port in input_port_objects:
                if port_view_modes[port.name] == "event":
                    self.emit(f"in_{port.name} := case", 1)
                    self.emit(
                        f"in_{port.name}_valid : "
                        f"in_{port.name}_value;",
                        2,
                    )
                    self.emit(f"TRUE : {self._idle_value(port)};", 2)
                    self.emit("esac;", 1)
                else:
                    # 持续数据视图忽略事件有效位，始终呈现最近载荷。
                    self.emit(
                        f"in_{port.name} := in_{port.name}_value;",
                        1,
                    )

            for port in transported_event_output_objects:
                if port_view_modes[port.name] == "event":
                    self.emit(f"out_{port.name} := case", 1)
                    self.emit(
                        f"out_{port.name}_valid : "
                        f"{self._event_storage_name(port.name)};",
                        2,
                    )
                    self.emit(f"TRUE : {self._idle_value(port)};", 2)
                    self.emit("esac;", 1)
                else:
                    # 例如 Battery 的 send(voltage, 3)：传输仍产生 valid，
                    # 但规约观察 out_voltage 时读取持久载荷。
                    self.emit(
                        f"out_{port.name} := "
                        f"{self._event_storage_name(port.name)};",
                        1,
                    )

            for variable in parameter_defines:
                value = self._translate_expr(variable.init_value)
                self.emit(f"{variable.name} := {value};", 1)

        # ================================================================
        # 3. 初始状态。
        # ================================================================
        self.emit("ASSIGN")
        init_state = next(
            (
                state.name
                for state in model.states
                if state.is_initial
            ),
            state_names[0],
        )
        self.emit(f"init(state) := {init_state};", 1)
        self.emit("init(timer) := 0;", 1)

        for port in output_port_objects:
            init_value = self._idle_value(port)
            if output_port_modes[port.name] == "event":
                self.emit(
                    f"init({self._event_storage_name(port.name)}) "
                    f":= {init_value};",
                    1,
                )
                self.emit(
                    f"init(out_{port.name}_valid) := FALSE;",
                    1,
                )
            else:
                self.emit(
                    f"init({self._data_storage_name(port.name)}) "
                    f":= {init_value};",
                    1,
                )

        for variable in model.variables:
            if variable.kind == "value" and variable.init_value is not None:
                value = self._translate_expr(variable.init_value)
                self.emit(f"init({variable.name}) := {value};", 1)

        # ================================================================
        # 4. 状态转移。
        # ================================================================
        self.emit("\n    -- ====== 状态转移逻辑 ======")
        self.emit("next(state) := case", 1)
        for state in model.states:
            for transition in state.transitions:
                condition = self._build_condition(
                    model,
                    state,
                    transition,
                    in_ports,
                )
                self.emit(f"{condition} : {transition.target};", 2)
        self.emit("TRUE : state;", 2)
        self.emit("esac;", 1)

        # ================================================================
        # 5. 内部变量、持续数据和事件载荷更新。
        # ================================================================
        self.emit("\n    -- ====== 变量与行为更新逻辑 ======")

        variable_updates = {}
        output_port_by_storage = {}
        output_storage_by_port = {}
        send_conditions_by_storage = {}

        for variable in model.variables:
            if variable.kind == "value":
                variable_updates[variable.name] = []

        for port in output_port_objects:
            mode = output_port_modes[port.name]
            storage_name = (
                self._event_storage_name(port.name)
                if mode == "event"
                else self._data_storage_name(port.name)
            )
            variable_updates[storage_name] = []
            output_port_by_storage[storage_name] = port
            output_storage_by_port[port.name] = storage_name

            if mode == "event":
                send_conditions_by_storage[storage_name] = []

        for state, transition, action_text, action_guard in self._iter_actions(
            model
        ):
            base_condition = self._build_condition(
                model,
                state,
                transition,
                in_ports,
            )
            specific_conditions = [f"({base_condition})"]

            if action_guard:
                specific_conditions.append(
                    f"({self._translate_expr(action_guard, in_ports)})"
                )

            full_condition = " & ".join(specific_conditions)
            parsed = self._parse_action(action_text)
            if parsed is None:
                raise ValueError(
                    f"组件 {model.name} 包含当前转换器不支持的动作："
                    f"{action_text}"
                )

            action_kind, target, value_expr = parsed
            translated_value = self._translate_expr(value_expr, in_ports)

            if target in output_storage_by_port:
                storage_name = output_storage_by_port[target]
                expected_mode = output_port_modes[target]
                actual_mode = (
                    "event" if action_kind == "send" else "data"
                )

                if expected_mode != actual_mode:
                    raise ValueError(
                        f"组件 {model.name} 的输出端口 {target} "
                        f"被推导为 {expected_mode}，但动作 {action_text} "
                        f"使用了 {actual_mode} 更新方式"
                    )

                variable_updates[storage_name].append(
                    (full_condition, translated_value)
                )

                if action_kind == "send":
                    send_conditions_by_storage[storage_name].append(
                        full_condition
                    )

            elif action_kind == "assignment" and target in variable_updates:
                variable_updates[target].append(
                    (full_condition, translated_value)
                )

            elif action_kind == "send":
                raise ValueError(
                    f"组件 {model.name} 的 send 动作引用了未声明的"
                    f"输出端口：{action_text}"
                )

            else:
                raise ValueError(
                    f"组件 {model.name} 的赋值动作引用了未声明或不支持的"
                    f"目标 {target}：{action_text}"
                )

        for variable_name, updates in variable_updates.items():
            if not updates:
                self.emit(
                    f"next({variable_name}) := {variable_name};",
                    1,
                )
                continue

            self.emit(f"next({variable_name}) := case", 1)
            for condition, value_expr in updates:
                self.emit(f"{condition} : {value_expr};", 2)

            # 载荷和持续数据均保留最近一次取值；事件是否在本步发生，
            # 由独立 valid 位以及公开单步视图表达。
            self.emit(f"TRUE : {variable_name};", 2)
            self.emit("esac;", 1)

        # 只有 send 型事件输出生成脉冲 valid。无 send（例如删除发送动作的
        # 故障模型）时，valid 始终为 FALSE。
        for storage_name, send_conditions in send_conditions_by_storage.items():
            port = output_port_by_storage[storage_name]
            valid_name = f"out_{port.name}_valid"

            if send_conditions:
                self.emit(f"next({valid_name}) := case", 1)
                for condition in send_conditions:
                    self.emit(f"{condition} : TRUE;", 2)
                self.emit("TRUE : FALSE;", 2)
                self.emit("esac;", 1)
            else:
                self.emit(f"next({valid_name}) := FALSE;", 1)

        # ================================================================
        # 6. 局部计时器。
        # ================================================================
        self.emit("\n    -- ====== 计时器 (Timer) 逻辑 ======")
        self.emit("next(timer) := case", 1)

        for state in model.states:
            transition_conditions = [
                f"({self._build_condition(model, state, transition, in_ports)})"
                for transition in state.transitions
            ]

            if transition_conditions:
                self.emit(
                    f"{' | '.join(transition_conditions)} : 0;",
                    2,
                )

            if str(state.hold_time).strip().lower() != "infinite":
                max_time = self._translate_expr(state.hold_time, in_ports)
                self.emit(
                    f"state = {state.name} & timer < {max_time} "
                    f": timer + 1;",
                    2,
                )
                self.emit(
                    f"state = {state.name} & timer >= {max_time} "
                    f": timer;",
                    2,
                )

        self.emit("TRUE : timer;", 2)
        self.emit("esac;", 1)

    def generate_coupled(self, model):
        self.code.append(
            "\n---------------------------------------------------------"
        )
        self.code.append(f"-- 主模块：耦合系统 ({model.name})")
        self.code.append(
            "---------------------------------------------------------"
        )
        self.emit("MODULE main")
        self.emit("VAR")

        topology = {}
        for connection in model.connections:
            if connection.target in topology:
                raise ValueError(
                    f"耦合模型 {model.name} 的输入端口 "
                    f"{connection.target} 存在多条连接"
                )
            topology[connection.target] = connection.source

        for part in model.parts:
            args = []
            input_ports = self.input_ports_by_model.get(part.class_name)

            if input_ports is None:
                raise ValueError(
                    f"生成耦合模型 {model.name} 前未生成离散组件 "
                    f"{part.class_name}，无法确定输入端口顺序"
                )

            target_receive_ports = self.receive_ports_by_model.get(
                part.class_name,
                set(),
            )

            for input_port_name in input_ports:
                instance_target = (
                    f"{part.instance_name}.{input_port_name}"
                )
                class_target = f"{part.class_name}.{input_port_name}"
                source_port = topology.get(instance_target)

                if source_port is None:
                    source_port = topology.get(class_target)

                if source_port is None:
                    raise ValueError(
                        f"耦合模型 {model.name} 中的输入端口 "
                        f"{instance_target} 未建立连接"
                    )

                try:
                    source_reference, source_port_name = source_port.rsplit(
                        ".",
                        1,
                    )
                except ValueError as error:
                    raise ValueError(
                        f"耦合模型 {model.name} 的连接源格式无效："
                        f"{source_port}"
                    ) from error

                source_part = next(
                    (
                        candidate
                        for candidate in model.parts
                        if candidate.instance_name == source_reference
                        or candidate.class_name == source_reference
                    ),
                    None,
                )

                if source_part is None:
                    raise ValueError(
                        f"耦合模型 {model.name} 的连接源 "
                        f"{source_port} 无法解析到组件实例"
                    )

                source_modes = self.output_port_modes_by_model.get(
                    source_part.class_name
                )
                if source_modes is None:
                    raise ValueError(
                        f"生成耦合模型 {model.name} 前未生成连接源组件 "
                        f"{source_part.class_name}"
                    )

                source_mode = source_modes.get(source_port_name)
                if source_mode is None:
                    raise ValueError(
                        f"组件 {source_part.class_name} 不存在输出端口 "
                        f"{source_port_name}"
                    )

                if (
                    input_port_name in target_receive_ports
                    and source_mode != "event"
                ):
                    raise ValueError(
                        f"耦合模型 {model.name} 将持续数据端口 "
                        f"{source_port} 连接到了事件触发器 "
                        f"{instance_target} 的 receive(...)"
                    )

                if source_mode == "event":
                    # 事件连接传递持久载荷和单步到达标志。
                    args.extend(
                        [
                            f"{source_part.instance_name}."
                            f"out_{source_port_name}_value",
                            f"{source_part.instance_name}."
                            f"out_{source_port_name}_valid",
                        ]
                    )
                else:
                    # 持续数据直接传值，并以 TRUE 表示数据始终可见。
                    args.extend(
                        [
                            f"{source_part.instance_name}."
                            f"out_{source_port_name}",
                            "TRUE",
                        ]
                    )

            argument_text = ", ".join(args)
            if argument_text:
                declaration = (
                    f"{part.instance_name} : "
                    f"{part.class_name}({argument_text});"
                )
            else:
                declaration = (
                    f"{part.instance_name} : {part.class_name};"
                )
            self.emit(declaration, 1)

    def get_result(self) -> str:
        return "\n".join(self.code)
