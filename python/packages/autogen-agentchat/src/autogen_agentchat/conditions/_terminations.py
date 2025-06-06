import asyncio
import time
from typing import Awaitable, Callable, List, Sequence

from autogen_core import Component
from pydantic import BaseModel
from typing_extensions import Self

from ..base import TerminatedException, TerminationCondition
from ..messages import (
    BaseAgentEvent,
    BaseChatMessage,
    HandoffMessage,
    StopMessage,
    TextMessage,
    ToolCallExecutionEvent,
)


class StopMessageTerminationConfig(BaseModel):
    pass


class StopMessageTermination(TerminationCondition, Component[StopMessageTerminationConfig]):
    """Terminate the conversation if a StopMessage is received."""

    component_config_schema = StopMessageTerminationConfig
    component_provider_override = "autogen_agentchat.conditions.StopMessageTermination"

    def __init__(self) -> None:
        self._terminated = False

    @property
    def terminated(self) -> bool:
        return self._terminated

    async def __call__(self, messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> StopMessage | None:
        if self._terminated:
            raise TerminatedException("Termination condition has already been reached")
        for message in messages:
            if isinstance(message, StopMessage):
                self._terminated = True
                return StopMessage(content="Stop message received", source="StopMessageTermination")
        return None

    async def reset(self) -> None:
        self._terminated = False

    def _to_config(self) -> StopMessageTerminationConfig:
        return StopMessageTerminationConfig()

    @classmethod
    def _from_config(cls, config: StopMessageTerminationConfig) -> Self:
        return cls()


class MaxMessageTerminationConfig(BaseModel):
    max_messages: int
    include_agent_event: bool = False


class MaxMessageTermination(TerminationCondition, Component[MaxMessageTerminationConfig]):
    """Terminate the conversation after a maximum number of messages have been exchanged.

    Args:
        max_messages: The maximum number of messages allowed in the conversation.
        include_agent_event: If True, include :class:`~autogen_agentchat.messages.BaseAgentEvent` in the message count.
            Otherwise, only include :class:`~autogen_agentchat.messages.BaseChatMessage`. Defaults to False.
    """

    component_config_schema = MaxMessageTerminationConfig
    component_provider_override = "autogen_agentchat.conditions.MaxMessageTermination"

    def __init__(self, max_messages: int, include_agent_event: bool = False) -> None:
        self._max_messages = max_messages
        self._message_count = 0
        self._include_agent_event = include_agent_event

    @property
    def terminated(self) -> bool:
        return self._message_count >= self._max_messages

    async def __call__(self, messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> StopMessage | None:
        if self.terminated:
            raise TerminatedException("Termination condition has already been reached")
        self._message_count += len([m for m in messages if self._include_agent_event or isinstance(m, BaseChatMessage)])
        if self._message_count >= self._max_messages:
            return StopMessage(
                content=f"Maximum number of messages {self._max_messages} reached, current message count: {self._message_count}",
                source="MaxMessageTermination",
            )
        return None

    async def reset(self) -> None:
        self._message_count = 0

    def _to_config(self) -> MaxMessageTerminationConfig:
        return MaxMessageTerminationConfig(
            max_messages=self._max_messages, include_agent_event=self._include_agent_event
        )

    @classmethod
    def _from_config(cls, config: MaxMessageTerminationConfig) -> Self:
        return cls(max_messages=config.max_messages, include_agent_event=config.include_agent_event)


class TextMentionTerminationConfig(BaseModel):
    text: str


class TextMentionTermination(TerminationCondition, Component[TextMentionTerminationConfig]):
    """Terminate the conversation if a specific text is mentioned.


    Args:
        text: The text to look for in the messages.
        sources: Check only messages of the specified agents for the text to look for.
    """

    component_config_schema = TextMentionTerminationConfig
    component_provider_override = "autogen_agentchat.conditions.TextMentionTermination"

    def __init__(self, text: str, sources: Sequence[str] | None = None) -> None:
        self._termination_text = text
        self._terminated = False
        self._sources = sources

    @property
    def terminated(self) -> bool:
        return self._terminated

    async def __call__(self, messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> StopMessage | None:
        if self._terminated:
            raise TerminatedException("Termination condition has already been reached")
        for message in messages:
            if self._sources is not None and message.source not in self._sources:
                continue

            content = message.to_text()
            if self._termination_text in content:
                self._terminated = True
                return StopMessage(
                    content=f"Text '{self._termination_text}' mentioned", source="TextMentionTermination"
                )
        return None

    async def reset(self) -> None:
        self._terminated = False

    def _to_config(self) -> TextMentionTerminationConfig:
        return TextMentionTerminationConfig(text=self._termination_text)

    @classmethod
    def _from_config(cls, config: TextMentionTerminationConfig) -> Self:
        return cls(text=config.text)


class FunctionalTermination(TerminationCondition):
    """Terminate the conversation if an functional expression is met.

    Args:
        func (Callable[[Sequence[BaseAgentEvent | BaseChatMessage]], bool] | Callable[[Sequence[BaseAgentEvent | BaseChatMessage]], Awaitable[bool]]): A function that takes a sequence of messages
            and returns True if the termination condition is met, False otherwise.
            The function can be a callable or an async callable.

    Example:

        .. code-block:: python

            import asyncio
            from typing import Sequence

            from autogen_agentchat.conditions import FunctionalTermination
            from autogen_agentchat.messages import BaseAgentEvent, BaseChatMessage, StopMessage


            def expression(messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> bool:
                # Check if the last message is a stop message
                return isinstance(messages[-1], StopMessage)


            termination = FunctionalTermination(expression)


            async def run() -> None:
                messages = [
                    StopMessage(source="agent1", content="Stop"),
                ]
                result = await termination(messages)
                print(result)


            asyncio.run(run())

        .. code-block:: text

            StopMessage(source="FunctionalTermination", content="Functional termination condition met")

    """

    def __init__(
        self,
        func: Callable[[Sequence[BaseAgentEvent | BaseChatMessage]], bool]
        | Callable[[Sequence[BaseAgentEvent | BaseChatMessage]], Awaitable[bool]],
    ) -> None:
        self._func = func
        self._terminated = False

    @property
    def terminated(self) -> bool:
        return self._terminated

    async def __call__(self, messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> StopMessage | None:
        if self._terminated:
            raise TerminatedException("Termination condition has already been reached")
        if asyncio.iscoroutinefunction(self._func):
            result = await self._func(messages)
        else:
            result = self._func(messages)
        if result is True:
            self._terminated = True
            return StopMessage(content="Functional termination condition met", source="FunctionalTermination")
        return None

    async def reset(self) -> None:
        self._terminated = False


class TokenUsageTerminationConfig(BaseModel):
    max_total_token: int | None
    max_prompt_token: int | None
    max_completion_token: int | None


class TokenUsageTermination(TerminationCondition, Component[TokenUsageTerminationConfig]):
    """Terminate the conversation if a token usage limit is reached.

    Args:
        max_total_token: The maximum total number of tokens allowed in the conversation.
        max_prompt_token: The maximum number of prompt tokens allowed in the conversation.
        max_completion_token: The maximum number of completion tokens allowed in the conversation.

    Raises:
        ValueError: If none of max_total_token, max_prompt_token, or max_completion_token is provided.
    """

    component_config_schema = TokenUsageTerminationConfig
    component_provider_override = "autogen_agentchat.conditions.TokenUsageTermination"

    def __init__(
        self,
        max_total_token: int | None = None,
        max_prompt_token: int | None = None,
        max_completion_token: int | None = None,
    ) -> None:
        if max_total_token is None and max_prompt_token is None and max_completion_token is None:
            raise ValueError(
                "At least one of max_total_token, max_prompt_token, or max_completion_token must be provided"
            )
        self._max_total_token = max_total_token
        self._max_prompt_token = max_prompt_token
        self._max_completion_token = max_completion_token
        self._total_token_count = 0
        self._prompt_token_count = 0
        self._completion_token_count = 0

    @property
    def terminated(self) -> bool:
        return (
            (self._max_total_token is not None and self._total_token_count >= self._max_total_token)
            or (self._max_prompt_token is not None and self._prompt_token_count >= self._max_prompt_token)
            or (self._max_completion_token is not None and self._completion_token_count >= self._max_completion_token)
        )

    async def __call__(self, messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> StopMessage | None:
        if self.terminated:
            raise TerminatedException("Termination condition has already been reached")
        for message in messages:
            if message.models_usage is not None:
                self._prompt_token_count += message.models_usage.prompt_tokens
                self._completion_token_count += message.models_usage.completion_tokens
                self._total_token_count += message.models_usage.prompt_tokens + message.models_usage.completion_tokens
        if self.terminated:
            content = f"Token usage limit reached, total token count: {self._total_token_count}, prompt token count: {self._prompt_token_count}, completion token count: {self._completion_token_count}."
            return StopMessage(content=content, source="TokenUsageTermination")
        return None

    async def reset(self) -> None:
        self._total_token_count = 0
        self._prompt_token_count = 0
        self._completion_token_count = 0

    def _to_config(self) -> TokenUsageTerminationConfig:
        return TokenUsageTerminationConfig(
            max_total_token=self._max_total_token,
            max_prompt_token=self._max_prompt_token,
            max_completion_token=self._max_completion_token,
        )

    @classmethod
    def _from_config(cls, config: TokenUsageTerminationConfig) -> Self:
        return cls(
            max_total_token=config.max_total_token,
            max_prompt_token=config.max_prompt_token,
            max_completion_token=config.max_completion_token,
        )


class HandoffTerminationConfig(BaseModel):
    target: str


class HandoffTermination(TerminationCondition, Component[HandoffTerminationConfig]):
    """Terminate the conversation if a :class:`~autogen_agentchat.messages.HandoffMessage`
    with the given target is received.

    Args:
        target (str): The target of the handoff message.
    """

    component_config_schema = HandoffTerminationConfig
    component_provider_override = "autogen_agentchat.conditions.HandoffTermination"

    def __init__(self, target: str) -> None:
        self._terminated = False
        self._target = target

    @property
    def terminated(self) -> bool:
        return self._terminated

    async def __call__(self, messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> StopMessage | None:
        if self._terminated:
            raise TerminatedException("Termination condition has already been reached")
        for message in messages:
            if isinstance(message, HandoffMessage) and message.target == self._target:
                self._terminated = True
                return StopMessage(
                    content=f"Handoff to {self._target} from {message.source} detected.", source="HandoffTermination"
                )
        return None

    async def reset(self) -> None:
        self._terminated = False

    def _to_config(self) -> HandoffTerminationConfig:
        return HandoffTerminationConfig(target=self._target)

    @classmethod
    def _from_config(cls, config: HandoffTerminationConfig) -> Self:
        return cls(target=config.target)


class TimeoutTerminationConfig(BaseModel):
    timeout_seconds: float


class TimeoutTermination(TerminationCondition, Component[TimeoutTerminationConfig]):
    """Terminate the conversation after a specified duration has passed.

    Args:
        timeout_seconds: The maximum duration in seconds before terminating the conversation.
    """

    component_config_schema = TimeoutTerminationConfig
    component_provider_override = "autogen_agentchat.conditions.TimeoutTermination"

    def __init__(self, timeout_seconds: float) -> None:
        self._timeout_seconds = timeout_seconds
        self._start_time = time.monotonic()
        self._terminated = False

    @property
    def terminated(self) -> bool:
        return self._terminated

    async def __call__(self, messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> StopMessage | None:
        if self._terminated:
            raise TerminatedException("Termination condition has already been reached")

        if (time.monotonic() - self._start_time) >= self._timeout_seconds:
            self._terminated = True
            return StopMessage(
                content=f"Timeout of {self._timeout_seconds} seconds reached", source="TimeoutTermination"
            )
        return None

    async def reset(self) -> None:
        self._start_time = time.monotonic()
        self._terminated = False

    def _to_config(self) -> TimeoutTerminationConfig:
        return TimeoutTerminationConfig(timeout_seconds=self._timeout_seconds)

    @classmethod
    def _from_config(cls, config: TimeoutTerminationConfig) -> Self:
        return cls(timeout_seconds=config.timeout_seconds)


class ExternalTerminationConfig(BaseModel):
    pass


class ExternalTermination(TerminationCondition, Component[ExternalTerminationConfig]):
    """A termination condition that is externally controlled
    by calling the :meth:`set` method.

    Example:

    .. code-block:: python

        from autogen_agentchat.conditions import ExternalTermination

        termination = ExternalTermination()

        # Run the team in an asyncio task.
        ...

        # Set the termination condition externally
        termination.set()

    """

    component_config_schema = ExternalTerminationConfig
    component_provider_override = "autogen_agentchat.conditions.ExternalTermination"

    def __init__(self) -> None:
        self._terminated = False
        self._setted = False

    @property
    def terminated(self) -> bool:
        return self._terminated

    def set(self) -> None:
        """Set the termination condition to terminated."""
        self._setted = True

    async def __call__(self, messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> StopMessage | None:
        if self._terminated:
            raise TerminatedException("Termination condition has already been reached")
        if self._setted:
            self._terminated = True
            return StopMessage(content="External termination requested", source="ExternalTermination")
        return None

    async def reset(self) -> None:
        self._terminated = False
        self._setted = False

    def _to_config(self) -> ExternalTerminationConfig:
        return ExternalTerminationConfig()

    @classmethod
    def _from_config(cls, config: ExternalTerminationConfig) -> Self:
        return cls()


class SourceMatchTerminationConfig(BaseModel):
    sources: List[str]


class SourceMatchTermination(TerminationCondition, Component[SourceMatchTerminationConfig]):
    """Terminate the conversation after a specific source responds.

    Args:
        sources (List[str]): List of source names to terminate the conversation.

    Raises:
        TerminatedException: If the termination condition has already been reached.
    """

    component_config_schema = SourceMatchTerminationConfig
    component_provider_override = "autogen_agentchat.conditions.SourceMatchTermination"

    def __init__(self, sources: List[str]) -> None:
        self._sources = sources
        self._terminated = False

    @property
    def terminated(self) -> bool:
        return self._terminated

    async def __call__(self, messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> StopMessage | None:
        if self._terminated:
            raise TerminatedException("Termination condition has already been reached")
        if not messages:
            return None
        for message in messages:
            if message.source in self._sources:
                self._terminated = True
                return StopMessage(content=f"'{message.source}' answered", source="SourceMatchTermination")
        return None

    async def reset(self) -> None:
        self._terminated = False

    def _to_config(self) -> SourceMatchTerminationConfig:
        return SourceMatchTerminationConfig(sources=self._sources)

    @classmethod
    def _from_config(cls, config: SourceMatchTerminationConfig) -> Self:
        return cls(sources=config.sources)


class TextMessageTerminationConfig(BaseModel):
    """Configuration for the TextMessageTermination termination condition."""

    source: str | None = None
    """The source of the text message to terminate the conversation."""


class TextMessageTermination(TerminationCondition, Component[TextMessageTerminationConfig]):
    """Terminate the conversation if a :class:`~autogen_agentchat.messages.TextMessage` is received.

    This termination condition checks for TextMessage instances in the message sequence. When a TextMessage is found,
    it terminates the conversation if either:
    - No source was specified (terminates on any TextMessage)
    - The message source matches the specified source

    Args:
        source (str | None, optional): The source name to match against incoming messages. If None, matches any source.
            Defaults to None.
    """

    component_config_schema = TextMessageTerminationConfig
    component_provider_override = "autogen_agentchat.conditions.TextMessageTermination"

    def __init__(self, source: str | None = None) -> None:
        self._terminated = False
        self._source = source

    @property
    def terminated(self) -> bool:
        return self._terminated

    async def __call__(self, messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> StopMessage | None:
        if self._terminated:
            raise TerminatedException("Termination condition has already been reached")
        for message in messages:
            if isinstance(message, TextMessage) and (self._source is None or message.source == self._source):
                self._terminated = True
                return StopMessage(
                    content=f"Text message received from '{message.source}'", source="TextMessageTermination"
                )
        return None

    async def reset(self) -> None:
        self._terminated = False

    def _to_config(self) -> TextMessageTerminationConfig:
        return TextMessageTerminationConfig(source=self._source)

    @classmethod
    def _from_config(cls, config: TextMessageTerminationConfig) -> Self:
        return cls(source=config.source)


class FunctionCallTerminationConfig(BaseModel):
    """Configuration for the :class:`FunctionCallTermination` termination condition."""

    function_name: str


class FunctionCallTermination(TerminationCondition, Component[FunctionCallTerminationConfig]):
    """Terminate the conversation if a :class:`~autogen_core.models.FunctionExecutionResult`
    with a specific name was received.

    Args:
        function_name (str): The name of the function to look for in the messages.

    Raises:
        TerminatedException: If the termination condition has already been reached.
    """

    component_config_schema = FunctionCallTerminationConfig
    component_provider_override = "autogen_agentchat.conditions.FunctionCallTermination"
    """The schema for the component configuration."""

    def __init__(self, function_name: str) -> None:
        self._terminated = False
        self._function_name = function_name

    @property
    def terminated(self) -> bool:
        return self._terminated

    async def __call__(self, messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> StopMessage | None:
        if self._terminated:
            raise TerminatedException("Termination condition has already been reached")
        for message in messages:
            if isinstance(message, ToolCallExecutionEvent):
                for execution in message.content:
                    if execution.name == self._function_name:
                        self._terminated = True
                        return StopMessage(
                            content=f"Function '{self._function_name}' was executed.",
                            source="FunctionCallTermination",
                        )
        return None

    async def reset(self) -> None:
        self._terminated = False

    def _to_config(self) -> FunctionCallTerminationConfig:
        return FunctionCallTerminationConfig(
            function_name=self._function_name,
        )

    @classmethod
    def _from_config(cls, config: FunctionCallTerminationConfig) -> Self:
        return cls(
            function_name=config.function_name,
        )
