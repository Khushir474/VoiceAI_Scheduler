# DOPS-13: Max persona warmth — update prompts and Vapi assistant config

Current prompts say 'DailyOps AI' but Vapi assistant is named Max. Prompts are functional but robotic. Update: (1) rename DailyOps AI → Max in all prompts; (2) add warm, friendly, personable tone guide; (3) use user's name naturally; (4) add empathy/humor for schedule context; (5) natural transitions. Touches: agents/prompts.py, adapters/voice/dailyops_prompt.py. Acceptance: Agent greets user warmly; uses first name; tone feels conversational not corporate; tested across light/heavy schedule scenarios.
