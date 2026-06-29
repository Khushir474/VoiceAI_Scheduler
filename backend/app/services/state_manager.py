"""State manager for persisting conversation FSM state to Supabase."""

import logging
from datetime import datetime
from typing import Optional

from app.agents.conversation_state_machine import (
    ConversationSession,
    ConversationState,
    StateTransitionLog,
    StateTransitionTrigger,
)

logger = logging.getLogger(__name__)


class StateManager:
    """Manages persistence and retrieval of conversation state.

    Responsibilities:
    - Create new conversation sessions
    - Persist state transitions to the database
    - Load sessions from the database
    - Update session metadata
    """

    def __init__(self, supabase_client):
        """Initialize StateManager with a Supabase client.

        Args:
            supabase_client: Supabase async client instance
        """
        self.supabase = supabase_client

    async def create_session(
        self,
        run_id: str,
        user_id: str,
    ) -> ConversationSession:
        """Create a new conversation session.

        Args:
            run_id: Unique identifier for this call
            user_id: UUID of the user

        Returns:
            ConversationSession with initial state
        """
        session = ConversationSession(
            run_id=run_id,
            user_id=user_id,
            current_state=ConversationState.GREETING,
        )

        # Persist to database
        try:
            await self.supabase.table("conversation_sessions").insert({
                "run_id": run_id,
                "user_id": str(user_id),
                "current_state": session.current_state.value,
                "started_at": session.started_at.isoformat(),
            }).execute()

            logger.info(f"Created conversation session: run_id={run_id}, user_id={user_id}")
        except Exception as e:
            logger.error(f"Failed to create conversation session: {e}")
            raise

        return session

    async def persist_transition(
        self,
        transition_log: StateTransitionLog,
    ) -> bool:
        """Persist a state transition to the database.

        Args:
            transition_log: StateTransitionLog entry to persist

        Returns:
            True if successful, False otherwise
        """
        try:
            await self.supabase.table("state_transitions").insert({
                "run_id": transition_log.run_id,
                "user_id": str(transition_log.user_id),
                "from_state": transition_log.from_state.value,
                "to_state": transition_log.to_state.value,
                "trigger": transition_log.trigger.value,
                "latency_ms": transition_log.latency_ms,
                "metadata": transition_log.metadata,
                "created_at": transition_log.timestamp.isoformat(),
            }).execute()

            logger.debug(
                f"Persisted transition: {transition_log.from_state.value} -> "
                f"{transition_log.to_state.value} (trigger: {transition_log.trigger.value})"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to persist state transition: {e}")
            return False

    async def update_session_state(
        self,
        run_id: str,
        current_state: ConversationState,
        previous_state: Optional[ConversationState] = None,
    ) -> bool:
        """Update the current state of a conversation session.

        Args:
            run_id: Unique identifier for this call
            current_state: New current state
            previous_state: Previous state (for audit)

        Returns:
            True if successful, False otherwise
        """
        try:
            await self.supabase.table("conversation_sessions").update({
                "current_state": current_state.value,
                "previous_state": previous_state.value if previous_state else None,
                "state_changed_at": datetime.utcnow().isoformat(),
            }).eq("run_id", run_id).execute()

            logger.debug(f"Updated session state: run_id={run_id}, state={current_state.value}")
            return True
        except Exception as e:
            logger.error(f"Failed to update session state: {e}")
            return False

    async def update_interaction_counts(
        self,
        run_id: str,
        barge_in_count: Optional[int] = None,
        silence_timeout_count: Optional[int] = None,
        stt_attempts: Optional[int] = None,
        stt_low_confidence_count: Optional[int] = None,
        error_count: Optional[int] = None,
    ) -> bool:
        """Update interaction counters for a session.

        Args:
            run_id: Unique identifier for this call
            barge_in_count: Number of barge-ins
            silence_timeout_count: Number of silence timeouts
            stt_attempts: Number of STT attempts
            stt_low_confidence_count: Number of low-confidence STT results
            error_count: Number of errors

        Returns:
            True if successful, False otherwise
        """
        update_data = {}

        if barge_in_count is not None:
            update_data["barge_in_count"] = barge_in_count
        if silence_timeout_count is not None:
            update_data["silence_timeout_count"] = silence_timeout_count
        if stt_attempts is not None:
            update_data["stt_attempts"] = stt_attempts
        if stt_low_confidence_count is not None:
            update_data["stt_low_confidence_count"] = stt_low_confidence_count
        if error_count is not None:
            update_data["error_count"] = error_count

        if not update_data:
            return True

        try:
            await self.supabase.table("conversation_sessions").update(
                update_data
            ).eq("run_id", run_id).execute()

            logger.debug(f"Updated interaction counts: run_id={run_id}, {update_data}")
            return True
        except Exception as e:
            logger.error(f"Failed to update interaction counts: {e}")
            return False

    async def log_error(
        self,
        run_id: str,
        user_id: str,
        error: Exception | str,
        recoverable: bool = True,
    ) -> bool:
        """Log an error to the conversation session.

        Args:
            run_id: Unique identifier for this call
            user_id: UUID of the user
            error: Error object or message
            recoverable: Whether this error can be recovered from

        Returns:
            True if successful, False otherwise
        """
        try:
            # Update session with error
            await self.supabase.table("conversation_sessions").update({
                "last_error": str(error),
            }).eq("run_id", run_id).execute()

            # Log error to error recovery table
            await self.supabase.table("error_recovery_logs").insert({
                "run_id": run_id,
                "user_id": str(user_id),
                "error_type": type(error).__name__ if isinstance(error, Exception) else "unknown",
                "error_message": str(error),
                "attempt": 1,
                "result": "logged",
                "metadata": {"recoverable": recoverable},
            }).execute()

            logger.info(f"Logged error: run_id={run_id}, error={str(error)}")
            return True
        except Exception as e:
            logger.error(f"Failed to log error: {e}")
            return False

    async def log_recovery_attempt(
        self,
        run_id: str,
        user_id: str,
        error_type: str,
        attempt: int,
        recovery_strategy: str,
        result: str,
        metadata: Optional[dict] = None,
    ) -> bool:
        """Log an error recovery attempt.

        Args:
            run_id: Unique identifier for this call
            user_id: UUID of the user
            error_type: Type of error being recovered from
            attempt: Which attempt number this is
            recovery_strategy: Strategy used for recovery
            result: 'success', 'partial', or 'failed'
            metadata: Additional context

        Returns:
            True if successful, False otherwise
        """
        try:
            await self.supabase.table("error_recovery_logs").insert({
                "run_id": run_id,
                "user_id": str(user_id),
                "error_type": error_type,
                "attempt": attempt,
                "recovery_strategy": recovery_strategy,
                "result": result,
                "metadata": metadata or {},
            }).execute()

            logger.info(
                f"Logged recovery attempt: run_id={run_id}, "
                f"error_type={error_type}, attempt={attempt}, result={result}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to log recovery attempt: {e}")
            return False

    async def get_session(self, run_id: str) -> Optional[dict]:
        """Retrieve a conversation session from the database.

        Args:
            run_id: Unique identifier for this call

        Returns:
            Session data dict or None if not found
        """
        try:
            response = await self.supabase.table("conversation_sessions").select(
                "*"
            ).eq("run_id", run_id).execute()

            if response.data and len(response.data) > 0:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"Failed to retrieve session: {e}")
            return None

    async def get_transition_history(
        self,
        run_id: str,
        limit: int = 100,
    ) -> list[dict]:
        """Retrieve the transition history for a session.

        Args:
            run_id: Unique identifier for this call
            limit: Maximum number of transitions to return

        Returns:
            List of transition log entries
        """
        try:
            response = await self.supabase.table("state_transitions").select(
                "*"
            ).eq("run_id", run_id).order(
                "created_at",
                desc=False,
            ).limit(limit).execute()

            return response.data if response.data else []
        except Exception as e:
            logger.error(f"Failed to retrieve transition history: {e}")
            return []

    async def get_error_history(
        self,
        run_id: str,
    ) -> list[dict]:
        """Retrieve the error history for a session.

        Args:
            run_id: Unique identifier for this call

        Returns:
            List of error recovery log entries
        """
        try:
            response = await self.supabase.table("error_recovery_logs").select(
                "*"
            ).eq("run_id", run_id).order(
                "created_at",
                desc=False,
            ).execute()

            return response.data if response.data else []
        except Exception as e:
            logger.error(f"Failed to retrieve error history: {e}")
            return []

    async def close_session(
        self,
        run_id: str,
        final_state: ConversationState,
    ) -> bool:
        """Mark a session as closed/ended.

        Args:
            run_id: Unique identifier for this call
            final_state: Final state when closing

        Returns:
            True if successful, False otherwise
        """
        try:
            await self.supabase.table("conversation_sessions").update({
                "current_state": final_state.value,
                "ended_at": datetime.utcnow().isoformat(),
            }).eq("run_id", run_id).execute()

            logger.info(f"Closed session: run_id={run_id}, final_state={final_state.value}")
            return True
        except Exception as e:
            logger.error(f"Failed to close session: {e}")
            return False
