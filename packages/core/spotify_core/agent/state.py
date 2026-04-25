import operator
from typing import TypedDict, List, Literal, Annotated, Sequence, Optional, Any
from langchain_core.messages import BaseMessage
from .schemas import IntentPlan

class AgentState(TypedDict):
    input: str
    messages: Annotated[Sequence[BaseMessage], operator.add]
    intent: Optional[Literal['factual_query', 'insight_analysis', 'recommendation', 'other']]
    plan: Optional[IntentPlan]
    tool_results: List[Optional[Any]] # e.g., the queries and their results
    final_response: Optional[str]
    retry_count: Optional[int]
