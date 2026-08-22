import os

try:
    from groq import Groq
except ImportError:
    Groq = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None

from parser_recursive_descent import SyntaxErrorInfo

def explain_syntax_error(error_info: SyntaxErrorInfo, source_code: str) -> str:
    """
    Uses the Groq API (fallback to Gemini API) to explain a syntax error.
    
    IMPORTANT CONSTRAINT: The AI does not parse or compile the code itself. 
    It STRICTLY relies on the error caught by the hand-written parser and the 
    expected tokens calculated from the FIRST/FOLLOW sets. It is merely a 
    translation layer to turn formal compiler errors into plain English.
    """
    prompt = f"""You are a helpful compiler error explainer. 
The hand-written parser for a custom arithmetic expression language encountered a syntax error.

Here is the error information strictly determined by the compiler:
- Offending Token: {error_info.token.type} (value: '{error_info.token.value}')
- Line: {error_info.token.line}, Column: {error_info.token.column}
- Expected Tokens: {', '.join(sorted(error_info.expected_tokens))}

Source code snippet:
{error_info.source_snippet}

Please explain in plain, beginner-friendly English why this is a syntax error based on the expected tokens provided by the parser. Do not try to re-parse the code yourself; trust the parser's expected tokens. Finally, suggest a one-line fix.
"""

    groq_api_key = os.environ.get("GROQ_API_KEY")
    if groq_api_key and Groq is not None:
        try:
            client = Groq(api_key=groq_api_key)
            response = client.chat.completions.create(
                model="llama3-8b-8192",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=300
            )
            return response.choices[0].message.content
        except Exception as e:
            # Fallback to Gemini
            pass

    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if gemini_api_key and genai is not None:
        try:
            genai.configure(api_key=gemini_api_key)
            model = genai.GenerativeModel('gemini-2.5-flash')
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"[API Error - Gemini: {str(e)}]\nOriginal Error:\n{error_info.message}\n{error_info.source_snippet}"

    # Generate fallback reason
    missing = []
    if not groq_api_key: missing.append("GROQ_API_KEY missing")
    elif Groq is None: missing.append("groq package not installed")
    else: missing.append("Groq API failed")
    
    if not gemini_api_key: missing.append("GEMINI_API_KEY missing")
    elif genai is None: missing.append("google-generativeai package not installed")

    reason = " and ".join(missing)
    return f"[Fallback Error - {reason}] \nRaw Error:\n{error_info.message}\n{error_info.source_snippet}"
