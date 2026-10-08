# Generated from CD.g4 by ANTLR 4.13.2
from antlr4 import *
if "." in __name__:
    from .CDParser import CDParser
else:
    from CDParser import CDParser

# This class defines a complete generic visitor for a parse tree produced by CDParser.

class CDVisitor(ParseTreeVisitor):

    # Visit a parse tree produced by CDParser#stored_definition.
    def visitStored_definition(self, ctx:CDParser.Stored_definitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#class_definition.
    def visitClass_definition(self, ctx:CDParser.Class_definitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#class_prefixes.
    def visitClass_prefixes(self, ctx:CDParser.Class_prefixesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#class_specifier.
    def visitClass_specifier(self, ctx:CDParser.Class_specifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#enumeration_definition.
    def visitEnumeration_definition(self, ctx:CDParser.Enumeration_definitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#composition.
    def visitComposition(self, ctx:CDParser.CompositionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#bdd_section.
    def visitBdd_section(self, ctx:CDParser.Bdd_sectionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#part_section.
    def visitPart_section(self, ctx:CDParser.Part_sectionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#value_section.
    def visitValue_section(self, ctx:CDParser.Value_sectionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#port_section.
    def visitPort_section(self, ctx:CDParser.Port_sectionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#port_component_clause.
    def visitPort_component_clause(self, ctx:CDParser.Port_component_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#is_flow.
    def visitIs_flow(self, ctx:CDParser.Is_flowContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#input.
    def visitInput(self, ctx:CDParser.InputContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#output.
    def visitOutput(self, ctx:CDParser.OutputContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#event_input.
    def visitEvent_input(self, ctx:CDParser.Event_inputContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#event_output.
    def visitEvent_output(self, ctx:CDParser.Event_outputContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#ibd_section.
    def visitIbd_section(self, ctx:CDParser.Ibd_sectionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#stm_section.
    def visitStm_section(self, ctx:CDParser.Stm_sectionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#is_initial.
    def visitIs_initial(self, ctx:CDParser.Is_initialContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#act_section.
    def visitAct_section(self, ctx:CDParser.Act_sectionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#initial_state_definition.
    def visitInitial_state_definition(self, ctx:CDParser.Initial_state_definitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#noninitial_state_definition.
    def visitNoninitial_state_definition(self, ctx:CDParser.Noninitial_state_definitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#state_statement.
    def visitState_statement(self, ctx:CDParser.State_statementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#enum_list.
    def visitEnum_list(self, ctx:CDParser.Enum_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#component_list.
    def visitComponent_list(self, ctx:CDParser.Component_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#component_declaration.
    def visitComponent_declaration(self, ctx:CDParser.Component_declarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#modification.
    def visitModification(self, ctx:CDParser.ModificationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#array_initializer.
    def visitArray_initializer(self, ctx:CDParser.Array_initializerContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#expression_initializer.
    def visitExpression_initializer(self, ctx:CDParser.Expression_initializerContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#class_modification.
    def visitClass_modification(self, ctx:CDParser.Class_modificationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#argument_list.
    def visitArgument_list(self, ctx:CDParser.Argument_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#argument.
    def visitArgument(self, ctx:CDParser.ArgumentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#import_clause.
    def visitImport_clause(self, ctx:CDParser.Import_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#notation_part.
    def visitNotation_part(self, ctx:CDParser.Notation_partContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#import_as_clause.
    def visitImport_as_clause(self, ctx:CDParser.Import_as_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#import_list.
    def visitImport_list(self, ctx:CDParser.Import_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#extends_clause.
    def visitExtends_clause(self, ctx:CDParser.Extends_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#component_clause.
    def visitComponent_clause(self, ctx:CDParser.Component_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#parameter_component_clause.
    def visitParameter_component_clause(self, ctx:CDParser.Parameter_component_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#new_parameter_component_close.
    def visitNew_parameter_component_close(self, ctx:CDParser.New_parameter_component_closeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#parameter_part.
    def visitParameter_part(self, ctx:CDParser.Parameter_partContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#type_prefix.
    def visitType_prefix(self, ctx:CDParser.Type_prefixContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#is_discrete.
    def visitIs_discrete(self, ctx:CDParser.Is_discreteContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#is_constant.
    def visitIs_constant(self, ctx:CDParser.Is_constantContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#receive_clause.
    def visitReceive_clause(self, ctx:CDParser.Receive_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#send_clause.
    def visitSend_clause(self, ctx:CDParser.Send_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#timeover_clouse.
    def visitTimeover_clouse(self, ctx:CDParser.Timeover_clouseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#connect_clause.
    def visitConnect_clause(self, ctx:CDParser.Connect_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#statement.
    def visitStatement(self, ctx:CDParser.StatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#simple_statement.
    def visitSimple_statement(self, ctx:CDParser.Simple_statementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#break_statement.
    def visitBreak_statement(self, ctx:CDParser.Break_statementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#run_statement.
    def visitRun_statement(self, ctx:CDParser.Run_statementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#return_statement.
    def visitReturn_statement(self, ctx:CDParser.Return_statementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#if_statement.
    def visitIf_statement(self, ctx:CDParser.If_statementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#elseif_statement.
    def visitElseif_statement(self, ctx:CDParser.Elseif_statementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#else_statement.
    def visitElse_statement(self, ctx:CDParser.Else_statementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#while_statement.
    def visitWhile_statement(self, ctx:CDParser.While_statementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#when_statement.
    def visitWhen_statement(self, ctx:CDParser.When_statementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#elsewhen_statement.
    def visitElsewhen_statement(self, ctx:CDParser.Elsewhen_statementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#transition_clause.
    def visitTransition_clause(self, ctx:CDParser.Transition_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#statehold_clause.
    def visitStatehold_clause(self, ctx:CDParser.Statehold_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#when_goto_out_clause.
    def visitWhen_goto_out_clause(self, ctx:CDParser.When_goto_out_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#out_with_satement.
    def visitOut_with_satement(self, ctx:CDParser.Out_with_satementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#when_receive_clause.
    def visitWhen_receive_clause(self, ctx:CDParser.When_receive_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#when_entry_clause.
    def visitWhen_entry_clause(self, ctx:CDParser.When_entry_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#expression.
    def visitExpression(self, ctx:CDParser.ExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#colon_literal.
    def visitColon_literal(self, ctx:CDParser.Colon_literalContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#logical_expression.
    def visitLogical_expression(self, ctx:CDParser.Logical_expressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#logical_term.
    def visitLogical_term(self, ctx:CDParser.Logical_termContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#logical_factor.
    def visitLogical_factor(self, ctx:CDParser.Logical_factorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#relation.
    def visitRelation(self, ctx:CDParser.RelationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#relational_operator.
    def visitRelational_operator(self, ctx:CDParser.Relational_operatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#front_arithmetic.
    def visitFront_arithmetic(self, ctx:CDParser.Front_arithmeticContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#regular_arithmetic.
    def visitRegular_arithmetic(self, ctx:CDParser.Regular_arithmeticContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#add_operator.
    def visitAdd_operator(self, ctx:CDParser.Add_operatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#term.
    def visitTerm(self, ctx:CDParser.TermContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#mul_operator.
    def visitMul_operator(self, ctx:CDParser.Mul_operatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#factor.
    def visitFactor(self, ctx:CDParser.FactorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#index_operator.
    def visitIndex_operator(self, ctx:CDParser.Index_operatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#primary.
    def visitPrimary(self, ctx:CDParser.PrimaryContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#bracket_exp.
    def visitBracket_exp(self, ctx:CDParser.Bracket_expContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#name.
    def visitName(self, ctx:CDParser.NameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#infinite_clause.
    def visitInfinite_clause(self, ctx:CDParser.Infinite_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#type_specifier.
    def visitType_specifier(self, ctx:CDParser.Type_specifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#list_type.
    def visitList_type(self, ctx:CDParser.List_typeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#map_type.
    def visitMap_type(self, ctx:CDParser.Map_typeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#array_literal.
    def visitArray_literal(self, ctx:CDParser.Array_literalContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#string_literal.
    def visitString_literal(self, ctx:CDParser.String_literalContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#real_literal.
    def visitReal_literal(self, ctx:CDParser.Real_literalContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#interger_literal.
    def visitInterger_literal(self, ctx:CDParser.Interger_literalContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#bool_literal.
    def visitBool_literal(self, ctx:CDParser.Bool_literalContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#list_literal.
    def visitList_literal(self, ctx:CDParser.List_literalContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#list_args.
    def visitList_args(self, ctx:CDParser.List_argsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#map_literal.
    def visitMap_literal(self, ctx:CDParser.Map_literalContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#map_args.
    def visitMap_args(self, ctx:CDParser.Map_argsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#empty_args.
    def visitEmpty_args(self, ctx:CDParser.Empty_argsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#function_call.
    def visitFunction_call(self, ctx:CDParser.Function_callContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#component_reference.
    def visitComponent_reference(self, ctx:CDParser.Component_referenceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#component_reference_args.
    def visitComponent_reference_args(self, ctx:CDParser.Component_reference_argsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#function_call_args.
    def visitFunction_call_args(self, ctx:CDParser.Function_call_argsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#function_arguments.
    def visitFunction_arguments(self, ctx:CDParser.Function_argumentsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#array_arguments.
    def visitArray_arguments(self, ctx:CDParser.Array_argumentsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#named_arguments.
    def visitNamed_arguments(self, ctx:CDParser.Named_argumentsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#named_argument.
    def visitNamed_argument(self, ctx:CDParser.Named_argumentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#output_expression_list.
    def visitOutput_expression_list(self, ctx:CDParser.Output_expression_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#array_subscripts.
    def visitArray_subscripts(self, ctx:CDParser.Array_subscriptsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#subscript.
    def visitSubscript(self, ctx:CDParser.SubscriptContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CDParser#select_all.
    def visitSelect_all(self, ctx:CDParser.Select_allContext):
        return self.visitChildren(ctx)



del CDParser