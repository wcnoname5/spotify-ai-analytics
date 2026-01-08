import os
import logging
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from .tools import initialize_tools

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Global placeholders for lazy initialization
_tools_list = None
_llm = None
_tool_executor = None

def get_llm():
    """Factory function to get the correct LLM based on env vars."""
    use_gemini = os.getenv("USE_GEMINI", "False").lower() == "true"
    
    if use_gemini:
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        api_key = os.getenv("GEMINI_API_KEY")
        logger.info(f"Using Gemini model: {model_name}")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables.")
        return ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key, temperature=0)
    else:
        model_name = os.getenv("OPENAI_MODEL", "gpt-4")
        api_key = os.getenv("OPENAI_API_KEY")
        logger.info(f"Using OpenAI model: {model_name}")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables.")
        return ChatOpenAI(model=model_name, api_key=api_key, temperature=0)

def get_resources():
    """
    Lazy initialize tools and LLM. 
    This prevents data loading and LLM initialization from happening 
    at module import time, allowing setup_logging() to be called first.
    """
    global _tools_list, _llm, _tool_executor
    if _tools_list is None:
        _tools_list = initialize_tools()
        _llm = get_llm()
        _tool_executor = {tool.name: tool for tool in _tools_list}
    return _llm, _tools_list, _tool_executor
