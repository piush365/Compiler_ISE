import re
from dataclasses import dataclass
from typing import List

@dataclass
class Token:
    type: str
    value: str
    line: int
    column: int
    
    def __repr__(self):
        return f"Token({self.type}, {repr(self.value)}, line={self.line}, col={self.column})"

class LexError(Exception):
    def __init__(self, message, line, column):
        super().__init__(f"{message} at line {line}, column {column}")
        self.message = message
        self.line = line
        self.column = column

class Lexer:
    # Token specification using named capturing groups
    TOKEN_SPEC = [
        ('FLOAT', r'\d+\.\d+'),          # Floating point numbers
        ('INT', r'\d+'),                 # Integers
        ('COMMENT', r'//.*'),            # Line comments
        ('FUNC', r'\b(?:sqrt|sin|cos|log)\b'), # Mathematical functions
        ('IDENTIFIER', r'[a-zA-Z_]\w*'), # Identifiers (variables)
        ('PLUS', r'\+'),                 # Addition
        ('MINUS', r'-'),                 # Subtraction
        ('STAR', r'\*'),                 # Multiplication
        ('SLASH', r'/'),                 # Division
        ('PERCENT', r'%'),               # Modulo
        ('CARET', r'\^'),                # Exponentiation
        ('LPAREN', r'\('),               # Left Parenthesis
        ('RPAREN', r'\)'),               # Right Parenthesis
        ('ASSIGN', r'='),                # Assignment
        ('SEMI', r';'),                  # Semicolon
        ('WHITESPACE', r'[ \t]+'),       # Spaces and tabs
        ('NEWLINE', r'\n'),              # Line endings
        ('MISMATCH', r'.'),              # Any other character (error)
    ]
    
    # Compile the regex pattern
    REGEX = re.compile('|'.join(f'(?P<{name}>{pattern})' for name, pattern in TOKEN_SPEC))

    def __init__(self, source_code: str):
        self.source_code = source_code
        self.tokens: List[Token] = []
        
    def tokenize(self) -> List[Token]:
        line_num = 1
        line_start = 0
        self.tokens = []
        
        for match in self.REGEX.finditer(self.source_code):
            kind = match.lastgroup
            value = match.group()
            column = match.start() - line_start + 1
            
            if kind == 'NEWLINE':
                line_start = match.end()
                line_num += 1
            elif kind == 'WHITESPACE' or kind == 'COMMENT':
                continue
            elif kind == 'MISMATCH':
                raise LexError(f"Unexpected character '{value}'", line_num, column)
            else:
                self.tokens.append(Token(kind, value, line_num, column))
                
        # Append an EOF token to simplify parsing
        self.tokens.append(Token('EOF', '', line_num, len(self.source_code) - line_start + 1))
        return self.tokens

if __name__ == "__main__":
    # Small test
    test_code = "x = 5.5 + -3 * sin(y); // test"
    lexer = Lexer(test_code)
    for tok in lexer.tokenize():
        print(tok)
