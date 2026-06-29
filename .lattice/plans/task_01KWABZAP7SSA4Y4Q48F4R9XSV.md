# DOPS-11: On-demand weather lookup tool for conversation agent

Conversation agent should be able to fetch real-time weather during the call when user asks. Weather adapter is already complete. Add a weather tool definition to the LangGraph agent, wire into conversation_agent.py. Cache results within session. Natural language responses. Touches: agents/conversation_agent.py, adapters/weather.py. Acceptance: Agent responds to weather questions mid-call; correct location used; results cached; API calls logged with latency; graceful error handling.
