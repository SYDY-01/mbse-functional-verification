#这个是用于从X语言模型生成NuXMV模型
import sys
from antlr4 import *
from CDLexer import CDLexer
from CDParser import CDParser

# 导入我们自己写的两个核心模块 (就像 include 头文件一样)
from x_transpiler import MyXLanguageVisitor
from nuxmv_generator import NuXMVGenerator

def main():
    # 配置输入输出路径
    # input_file = "TestWrong/input_FMCS_FI-01.txt"
    # output_file = "TestWrong/input_FMCS_FI_01_Result.smv"
    # input_file = "FMCS/input_XModel_FMCS.txt"
    # output_file = "FMCS/input_XModel_FMCS_Result.smv"
    input_file = "EventSemanticsTests/input_XModel_EventSemantics.txt"
    output_file = "EventSemanticsTests/input_XModel_EventSemantics_Result.smv"
    try:
        # ==========================================
        # 1. 前端：读取代码并生成抽象语法树 (AST)
        # ==========================================
        print(f"[*] 1. 正在读取源文件: {input_file} ...")
        input_stream = FileStream(input_file, encoding='utf-8')
        lexer = CDLexer(input_stream)
        stream = CommonTokenStream(lexer)
        parser = CDParser(stream)

        tree = parser.stored_definition()

        # ==========================================
        # 2. 中端：使用 Visitor 遍历 AST，提取结构化数据
        # ==========================================
        print("[*] 2. 正在解析语法树并提取模型结构与行为...")
        visitor = MyXLanguageVisitor()
        visitor.visit(tree)

        # ==========================================
        # 3. 后端：将提取的数据交给 NuXMV 代码生成器
        # ==========================================
        print("[*] 3. AST 解析完成，开始生成 NuXMV 代码...")
        generator = NuXMVGenerator()

        # 生成离散类代码
        for m in visitor.discrete_models:
            generator.generate_discrete(m)

        # 生成耦合类代码
        for m in visitor.coupled_models:
            generator.generate_coupled(m)

        # ==========================================
        # 4. 落地：写入输出文件
        # ==========================================
        final_code = generator.get_result()
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(final_code)

        print(f"[+] 大功告成！NuXMV 代码已成功保存至: {output_file}")

    except Exception as e:
        print(f"[!] 发生致命错误: {e}")


if __name__ == '__main__':
    main()