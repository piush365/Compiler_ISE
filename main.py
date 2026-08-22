import sys
from lexer import Lexer, LexError
from parser_recursive_descent import ParserRecursiveDescent, SyntaxErrorExt
from parser_bottom_up import ParserBottomUp
from ai_error_explainer import explain_syntax_error

def run_compiler(source_code: str, use_slr: bool = False):
    print(f"\n--- Compiling: {source_code.strip()} ---")
    try:
        # 1. Lexical Analysis
        lexer = Lexer(source_code)
        tokens = lexer.tokenize()
        print(f"Tokens: {[t.type for t in tokens]}")
        
        # 2. Syntax Analysis
        if use_slr:
            print("\n[SLR(1) Bottom-Up Parser]")
            parser = ParserBottomUp(lexer)
            parser.parse(trace=True)
        else:
            print("\n[LL(1) Recursive Descent Parser]")
            parser = ParserRecursiveDescent(lexer)
            ast = parser.parse()
            import pprint
            print("AST:")
            pprint.pprint(ast)
            
    except LexError as e:
        print(f"Lexical Error: {e.message}")
    except SyntaxErrorExt as e:
        print("\n[Raw Parser Error]")
        print(e.error_info.message)
        print(e.error_info.source_snippet)
        
        print("\n[AI Explanation]")
        explanation = explain_syntax_error(e.error_info, source_code)
        print(explanation)

def main():
    test_programs = [
        # Valid programs
        "x = 5.5 + -3 * sin(y);",
        "z = x ^ 2 ^ 3;",
        "result = (10 % 3) / log(x); y = -x;",
        
        # Invalid programs
        "x = 5.5 + * 3;",           # Unexpected STAR
        "y = (4 + 5 * 2;",          # Missing RPAREN
        "z = 10 ^ ;"                # Missing expression after CARET
    ]
    
    print("=== Compiler Front-End Demonstration ===")
    
    for i, prog in enumerate(test_programs):
        print(f"\n{'='*50}\nTest {i+1}:")
        
        # We process with recursive descent
        run_compiler(prog, use_slr=False)
        
        # Then with SLR
        run_compiler(prog, use_slr=True)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # If a file is passed as an argument
        filename = sys.argv[1]
        with open(filename, 'r') as f:
            code = f.read()
        print("=== Recursive Descent ===")
        run_compiler(code, use_slr=False)
        print("\n=== SLR(1) ===")
        run_compiler(code, use_slr=True)
    else:
        main()
