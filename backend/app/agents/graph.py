"""LangGraph workflow orchestrating the three agents."""

from typing import Any
from langgraph.graph import StateGraph, END
from app.agents.state import AgentState
from app.agents.planning_agent import PlanningAgent
from app.agents.conversation_agent import ConversationAgent
from app.agents.evaluation_agent import EvaluationAgent
from app.services.logger import DebugLogger


class DailyOpsGraph:
    """LangGraph workflow for daily planning."""

    def __init__(
        self,
        debug_logger: DebugLogger,
        planning_agent: PlanningAgent,
        conversation_agent: ConversationAgent,
        evaluation_agent: EvaluationAgent,
    ):
        self.debug_logger = debug_logger
        self.planning_agent = planning_agent
        self.conversation_agent = conversation_agent
        self.evaluation_agent = evaluation_agent
        self.graph = self._build_graph()

    def _build_graph(self):
        """Build the LangGraph workflow."""
        workflow = StateGraph(AgentState)

        # Add nodes (agents)
        workflow.add_node("planning", self._planning_node)
        workflow.add_node("conversation", self._conversation_node)
        workflow.add_node("evaluation", self._evaluation_node)

        # Define edges
        workflow.set_entry_point("planning")
        workflow.add_edge("planning", "conversation")
        workflow.add_edge("conversation", "evaluation")
        workflow.add_edge("evaluation", END)

        return workflow.compile()

    async def _planning_node(self, state: AgentState) -> dict[str, Any]:
        """Planning node wrapper."""
        state = await self.planning_agent.run(state)
        return state.model_dump()

    async def _conversation_node(self, state: AgentState) -> dict[str, Any]:
        """Conversation node wrapper."""
        # Convert dict back to AgentState
        state = AgentState(**state)
        state = await self.conversation_agent.run(state)
        return state.model_dump()

    async def _evaluation_node(self, state: AgentState) -> dict[str, Any]:
        """Evaluation node wrapper."""
        # Convert dict back to AgentState
        state = AgentState(**state)
        state = await self.evaluation_agent.run(state)
        return state.model_dump()

    async def run(self, state: AgentState) -> AgentState:
        """Execute the entire workflow."""
        await self.debug_logger.log_event(
            agent_name="DailyOpsGraph",
            event_type="workflow_start",
            message="Daily planning workflow started",
            input_payload={"run_id": state.run_id, "user_id": state.user_id},
        )

        try:
            # Run the graph
            output = await self.graph.ainvoke(state.model_dump())

            # Convert output back to AgentState
            final_state = AgentState(**output)

            await self.debug_logger.log_event(
                agent_name="DailyOpsGraph",
                event_type="workflow_complete",
                message="Daily planning workflow completed",
                output_payload={
                    "has_plan": final_state.plan is not None,
                    "evaluation_score": final_state.evaluation_score,
                    "has_error": final_state.error is not None,
                },
            )

            return final_state

        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="DailyOpsGraph",
                event_type="workflow_error",
                level="error",
                message=f"Workflow failed: {str(e)}",
                error=str(e),
            )
            raise
