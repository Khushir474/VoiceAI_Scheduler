# DOPS-9: Smart commute planning (work vs in-person vs virtual)

Planning agent should: (1) if user has a work event, plan commute to work; (2) else find next in-person event and plan commute there; (3) if next event is virtual, tell user no commute needed. Detect virtual events by location field or platform tags (Zoom, Meet, Teams). Touches: agents/planning_agent.py, adapters/maps.py, agents/state.py. Acceptance: Correct commute recommendation based on day type; virtual event detection works; departure time includes buffer.
