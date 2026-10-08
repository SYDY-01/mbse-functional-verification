"""ANTLR前端与X语言类型化中间表示。

ANTLR生成的语法分析树由 ``MyXLanguageVisitor`` 遍历，并被投影为
组件、端口、状态、转移和连接组成的类型化IR。第4节的模型符号
校验与第5节的nuXmv代码生成共用该IR。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

from antlr4 import CommonTokenStream, FileStream
from antlr4.error.ErrorListener import ErrorListener

from CDLexer import CDLexer
from CDParser import CDParser
from CDVisitor import CDVisitor
# ==========================================
# 1. 数据结构升级 (新增 Variable)
# ==========================================


@dataclass
class Port:
    name: str
    direction: str
    datatype: str


@dataclass
class Variable:
    name: str
    datatype: str
    kind: str  # 'value' 或 'parameter'
    init_value: str | None = None  # 初始值可为空


@dataclass
class Transition:
    trigger: str
    target: str
    guard: str = ""
    # 每项为（动作文本，该动作的路径条件）。
    actions: List[Tuple[str, str]] = field(default_factory=list)

@dataclass
class State:
    name: str
    is_initial: bool
    hold_time: str = "infinite"
    transitions: List[Transition] = field(default_factory=list)


@dataclass
class DiscreteModel:
    name: str
    ports: List[Port] = field(default_factory=list)
    variables: List[Variable] = field(default_factory=list)  # [新增] 存储变量和参数
    states: List[State] = field(default_factory=list)


@dataclass
class Part:
    instance_name: str
    class_name: str


@dataclass
class Connection:
    source: str
    target: str


@dataclass
class CoupledModel:
    name: str
    parts: List[Part] = field(default_factory=list)
    connections: List[Connection] = field(default_factory=list)


class XModelParseError(ValueError):
    """X语言模型无法完成词法或语法分析。"""


class _CollectingErrorListener(ErrorListener):
    """收集ANTLR错误，避免无效模型被静默转换。"""

    def __init__(self):
        super().__init__()
        self.errors: list[str] = []

    def syntaxError(
        self,
        recognizer,
        offendingSymbol,
        line,
        column,
        msg,
        e,
    ):
        self.errors.append(f"第{line}行第{column + 1}列：{msg}")


# ==========================================
# 2. Visitor 增强版
# ==========================================
class MyXLanguageVisitor(CDVisitor):
    def __init__(self):
        super().__init__()
        self.discrete_models = []
        self.coupled_models = []

        self.current_model = None
        self.current_state = None

        # 作用域标记 (用于区分同名的 component_clause)
        self.in_part_section = False
        self.in_value_section = False
        self.in_parameter_section = False

        self.current_trigger = None
        self.current_guards = []
        self.pending_actions = []
        self.active_transitions = []
        self.when_block_transitions = []

        # --- 顶层类分流 ---

    def visitClass_definition(self, ctx: CDParser.Class_definitionContext):
        prefix = ctx.class_prefixes().getText()
        class_name = ctx.class_specifier().IDENT().getText()

        if 'discrete' in prefix:
            self.current_model = DiscreteModel(name=class_name)
            self.visit(ctx.class_specifier())
            self.discrete_models.append(self.current_model)
            self.current_model = None

        elif 'couple' in prefix:
            self.current_model = CoupledModel(name=class_name)
            self.visit(ctx.class_specifier())
            self.coupled_models.append(self.current_model)
            self.current_model = None
        return None

        # ==================== [新增] 变量与参数提取 ====================

    # 1. 解析 Parameter 块
    def visitParameter_part(self, ctx: CDParser.Parameter_partContext):
        self.in_parameter_section = True
        self.visitChildren(ctx)
        self.in_parameter_section = False
        return None

    def visitNew_parameter_component_close(self, ctx: CDParser.New_parameter_component_closeContext):
        if self.in_parameter_section and isinstance(self.current_model, DiscreteModel):
            datatype = ctx.type_specifier().getText()
            comp_list = ctx.component_list().component_declaration()
            for comp in comp_list:
                var_name = comp.IDENT().getText()
                init_val = None
                if comp.modification() and comp.modification().initializer():
                    init_val = comp.modification().initializer().getText()

                self.current_model.variables.append(Variable(var_name, datatype, 'parameter', init_val))
        return self.visitChildren(ctx)

    # 2. 解析 Value 块
    def visitValue_section(self, ctx: CDParser.Value_sectionContext):
        self.in_value_section = True
        self.visitChildren(ctx)
        self.in_value_section = False
        return None

    def visitComponent_clause(self, ctx: CDParser.Component_clauseContext):
        if self.in_part_section and isinstance(self.current_model, CoupledModel):
            class_name = ctx.type_specifier().getText()
            comp_list = ctx.component_list().component_declaration()
            for comp in comp_list:
                inst_name = comp.IDENT().getText()
                self.current_model.parts.append(
                    Part(instance_name=inst_name, class_name=class_name)
                )

        elif self.in_value_section and isinstance(self.current_model, DiscreteModel):
            datatype = ctx.type_specifier().getText()
            comp_list = ctx.component_list().component_declaration()
            for comp in comp_list:
                var_name = comp.IDENT().getText()
                init_val = None
                if comp.modification() and comp.modification().initializer():
                    init_val = comp.modification().initializer().getText()

                self.current_model.variables.append(
                    Variable(var_name, datatype, "value", init_val)
                )

        return self.visitChildren(ctx)

    # ==================== 其他已有的提取逻辑 ====================

    def visitPart_section(self, ctx: CDParser.Part_sectionContext):
        self.in_part_section = True
        self.visitChildren(ctx)
        self.in_part_section = False
        return None

    def visitConnect_clause(self, ctx: CDParser.Connect_clauseContext):
        if isinstance(self.current_model, CoupledModel):
            refs = ctx.component_reference()
            if len(refs) == 2:
                self.current_model.connections.append(Connection(refs[0].getText(), refs[1].getText()))
        return self.visitChildren(ctx)

    def visitPort_component_clause(self, ctx: CDParser.Port_component_clauseContext):
        if isinstance(self.current_model, DiscreteModel):
            prefix_ctx = ctx.port_prefix()
            direction = prefix_ctx.getText() if prefix_ctx else "unknown"
            datatype = ctx.type_specifier().getText()
            # 语法允许在同一条声明中给出多个端口，必须逐项提取，不能只
            # 记录第一个端口，否则后续模型符号校验会产生假阴性。
            for component in ctx.component_list().component_declaration():
                port_name = component.IDENT().getText()
                self.current_model.ports.append(
                    Port(port_name, direction, datatype)
                )
        return self.visitChildren(ctx)

    def visitInitial_state_definition(self, ctx: CDParser.Initial_state_definitionContext):
        self.current_state = State(name=ctx.IDENT().getText(), is_initial=True)
        self.visitChildren(ctx)
        if isinstance(self.current_model, DiscreteModel):
            self.current_model.states.append(self.current_state)
        self.current_state = None
        return None

    def visitNoninitial_state_definition(self, ctx: CDParser.Noninitial_state_definitionContext):
        self.current_state = State(name=ctx.IDENT().getText(), is_initial=False)
        self.visitChildren(ctx)
        if isinstance(self.current_model, DiscreteModel):
            self.current_model.states.append(self.current_state)
        self.current_state = None
        return None

    def visitStatehold_clause(self, ctx: CDParser.Statehold_clauseContext):
        if self.current_state:
            self.current_state.hold_time = ctx.expression().getText()
        return self.visitChildren(ctx)

    def visitWhen_goto_out_clause(self, ctx: CDParser.When_goto_out_clauseContext):
        self.current_trigger = "timeover"
        self._reset_action_context()
        self.visitChildren(ctx)
        self.current_trigger = None
        return None

    def visitWhen_receive_clause(self, ctx: CDParser.When_receive_clauseContext):
        self.current_trigger = ctx.receive_clause().getText()
        self._reset_action_context()
        self.visitChildren(ctx)
        self.current_trigger = None
        return None

    def _reset_action_context(self):
        self.pending_actions = []
        self.active_transitions = []
        self.when_block_transitions = []

    def visitSimple_statement(self, ctx: CDParser.Simple_statementContext):
        self._attach_action(ctx.getText())
        return None

    def visitSend_clause(self, ctx: CDParser.Send_clauseContext):
        self._attach_action(ctx.getText())
        return None

    def _attach_action(self, action_text: str):
        # 条件栈显式保留动作所在的嵌套分支路径。
        action_guard = " and ".join(self.current_guards) if self.current_guards else ""

        if self.active_transitions:
            for t in self.active_transitions:
                t.actions.append((action_text, action_guard))
        else:
            self.pending_actions.append((action_text, action_guard))

    def visitTransition_clause(self, ctx: CDParser.Transition_clauseContext):
        if self.current_state and self.current_trigger:
            target_state = ctx.IDENT().getText()
            guard_str = " and ".join(self.current_guards) if self.current_guards else ""

            trans = Transition(
                trigger=self.current_trigger,
                target=target_state,
                guard=guard_str,
                actions=list(self.pending_actions)
            )
            self.current_state.transitions.append(trans)
            self.active_transitions.append(trans)
            self.when_block_transitions.append(trans)
        return self.visitChildren(ctx)

    def visitIf_statement(self, ctx: CDParser.If_statementContext):
        if_expr = ctx.expression().getText()
        saved_pending = list(self.pending_actions)
        saved_active = list(self.active_transitions)

        self.current_guards.append(if_expr)
        self.active_transitions = list(saved_active)
        for stmt in ctx.statement():
            self.visit(stmt)
        self.current_guards.pop()

        accumulated_negation = f"not ({if_expr})"

        for elseif_ctx in ctx.elseif_statement():
            elseif_expr = elseif_ctx.expression().getText()
            self.current_guards.append(f"{accumulated_negation} and ({elseif_expr})")

            self.pending_actions = list(saved_pending)
            self.active_transitions = list(saved_active)
            for stmt in elseif_ctx.statement():
                self.visit(stmt)
            self.current_guards.pop()

            accumulated_negation += f" and not ({elseif_expr})"

        if ctx.else_statement():
            self.current_guards.append(accumulated_negation)
            self.pending_actions = list(saved_pending)
            self.active_transitions = list(saved_active)
            for stmt in ctx.else_statement().statement():
                self.visit(stmt)
            self.current_guards.pop()

        self.pending_actions = saved_pending
        self.active_transitions = list(self.when_block_transitions)
        return None

    def visitOut_with_satement(self, ctx: CDParser.Out_with_satementContext):
        self.active_transitions = self.when_block_transitions
        for stmt in ctx.statement():
            self.visit(stmt)
        return None


def parse_x_model(path: str | Path) -> MyXLanguageVisitor:
    """
    解析一份完整X语言模型并返回构造了类型化IR的Visitor。

    该函数同时检查词法和语法错误。第4节的模型符号校验与第5节的
    nuXmv代码生成可复用同一份IR，避免两套解析过程产生不一致。
    """

    model_path = Path(path)
    if not model_path.exists():
        raise FileNotFoundError(f"找不到X语言模型文件：{model_path}")

    input_stream = FileStream(str(model_path), encoding="utf-8")
    lexer = CDLexer(input_stream)
    lexer_errors = _CollectingErrorListener()
    lexer.removeErrorListeners()
    lexer.addErrorListener(lexer_errors)

    token_stream = CommonTokenStream(lexer)
    parser = CDParser(token_stream)
    parser_errors = _CollectingErrorListener()
    parser.removeErrorListeners()
    parser.addErrorListener(parser_errors)

    tree = parser.stored_definition()
    errors = lexer_errors.errors + parser_errors.errors
    if errors:
        details = "\n".join(f"  - {error}" for error in errors)
        raise XModelParseError(
            f"X语言模型包含{len(errors)}项词法/语法错误：\n{details}"
        )

    visitor = MyXLanguageVisitor()
    visitor.visit(tree)
    if not visitor.discrete_models and not visitor.coupled_models:
        raise XModelParseError("X语言模型中未解析到离散组件或耦合组件。")

    return visitor
