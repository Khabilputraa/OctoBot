import abc
import contextlib
import json
import typing

import octobot_commons.logging as logging

import octobot_agents.agent.channels.agent as agent_channels
import octobot_agents.constants as constants
import octobot_agents.storage as storage
import octobot_agents.enums as enums
import octobot_services.services as services
import octobot_services.enums as services_enums
import octobot_services.errors as services_errors

class AbstractAIAgentChannel(agent_channels.AbstractAgentChannel):

    __metaclass__ = abc.ABCMeta

class AbstractAIAgentChannelConsumer(agent_channels.AbstractAgentChannelConsumer):

    __metaclass__ = abc.ABCMeta
    
    def __init__(
        self,
        callback: typing.Optional[typing.Callable] = None,
        size: int = 0,
        priority_level: int = agent_channels.AbstractAgentChannel.DEFAULT_PRIORITY_LEVEL,
        expected_inputs: int = 1,
    ):

        super().__init__(callback, size=size, priority_level=priority_level)
        self.expected_inputs = expected_inputs
        self.received_inputs: typing.Dict[str, typing.Any] = {}

    def is_ready(self) -> bool:
        return len(self.received_inputs) >= self.expected_inputs
    
    def add_input(self, source_name: str, data: typing.Any) -> None:

        self.received_inputs[source_name] = data
    
    def get_aggregated_inputs(self) -> typing.Dict[str, typing.Any]:

        return self.received_inputs.copy()
    
    def clear_inputs(self) -> None:
        self.received_inputs.clear()

class AbstractAIAgentChannelProducer(agent_channels.AbstractAgentChannelProducer, abc.ABC):

    AGENT_VERSION: str = "1.0.0"
    DEFAULT_MODEL: typing.Optional[str] = None
    DEFAULT_MAX_TOKENS: int = constants.AGENT_DEFAULT_MAX_TOKENS
    DEFAULT_TEMPERATURE: float = constants.AGENT_DEFAULT_TEMPERATURE
    MAX_RETRIES: int = constants.AGENT_DEFAULT_MAX_RETRIES
    MODEL_POLICY: typing.Optional[services_enums.AIModelPolicy] = None

    ENABLE_MEMORY: bool = False
    MEMORY_SEARCH_LIMIT: int = 5
    MEMORY_STORAGE_ENABLED: bool = True
    MEMORY_AGENT_ID_KEY: str = constants.MEMORY_AGENT_ID_KEY
    
    AGENT_CHANNEL: typing.Optional[typing.Type[agent_channels.AbstractAgentChannel]] = None
    AGENT_CONSUMER: typing.Optional[typing.Type[AbstractAIAgentChannelConsumer]] = None
    
    def __init__(
        self,
        channel: typing.Optional[agent_channels.AbstractAgentChannel],
        ai_service: typing.Optional[services.AbstractAIService] = None,
        model: typing.Optional[str] = None,
        max_tokens: typing.Optional[int] = None,
        temperature: typing.Optional[float] = None,
        enable_memory: typing.Optional[bool] = None,
    ):

        super().__init__(channel)
        self.name = self.__class__.__name__
        self.model = model or self.DEFAULT_MODEL
        self.max_tokens = max_tokens or self.DEFAULT_MAX_TOKENS
        self.temperature = temperature or self.DEFAULT_TEMPERATURE
        self._custom_prompt: typing.Optional[str] = None
        self.ai_service: services.AbstractAIService = None
        self.logger = logging.get_logger(f"{self.__class__.__name__}")
        
        # Initialize memory storage if memory is enabled
        memory_enabled = enable_memory if enable_memory is not None else self.ENABLE_MEMORY
        self.memory_manager: storage.AbstractMemoryStorage = storage.create_memory_storage(
            enums.MemoryStorageType.JSON,
            agent_name=self.__class__.__name__,
            agent_version=self.AGENT_VERSION,
            enabled=memory_enabled,
            search_limit=self.MEMORY_SEARCH_LIMIT,
            storage_enabled=self.MEMORY_STORAGE_ENABLED,
            agent_id_key=self.MEMORY_AGENT_ID_KEY,
        )
    
    def has_memory_enabled(self) -> bool:

        return self.memory_manager.is_enabled()
    
    @property
    def prompt(self) -> str:
        return self._custom_prompt or self._get_default_prompt()
    
    @prompt.setter
    def prompt(self, value: str) -> None:

        self._custom_prompt = value
    
    @abc.abstractmethod
    def _get_default_prompt(self) -> str:

        raise NotImplementedError("_get_default_prompt not implemented")
    
    @abc.abstractmethod
    async def execute(self, input_data: typing.Any, ai_service: services.AbstractAIService) -> typing.Any:

        raise NotImplementedError("execute not implemented")
    
    async def push(
        self,
        result: typing.Any,
        agent_name: typing.Optional[str] = None,
        agent_id: typing.Optional[str] = None,
    ) -> None:

        if self.channel is None:
            return
        await self.perform(
            result,
            agent_name=agent_name or self.name,
            agent_id=agent_id or "",
        )
    
    async def perform(
        self,
        result: typing.Any,
        agent_name: str,
        agent_id: str,
    ) -> None:

        if self.channel is None:
            return
        for consumer_instance in self.channel.get_filtered_consumers(
            agent_name=agent_name,
            agent_id=agent_id,
        ):
            await consumer_instance.queue.put({
                "agent_name": agent_name,
                "agent_id": agent_id,
                "result": result,
            })
    
    @contextlib.contextmanager
    def _memory_tool_executor(self):

        def executor(tool_name: str, arguments: dict) -> typing.Any:
            return storage.execute_memory_tool(self.memory_manager, tool_name, arguments)
        
        yield executor
    
    async def _call_llm(
        self,
        messages: list,
        llm_service: services.AbstractAIService,
        json_output: bool = True,
        response_schema: typing.Optional[typing.Any] = None,
        input_data: typing.Optional[typing.Any] = None,
        memory_query: typing.Optional[str] = None,
        tools: typing.Optional[list] = None,
        return_tool_calls: bool = False,
    ) -> typing.Any:
 
        all_tools = []
        if self.memory_manager.is_enabled():
            all_tools.extend(storage.get_memory_tools(self.memory_manager, llm_service))
        if tools:
            all_tools.extend(tools)

        effective_schema = response_schema
        if effective_schema is None and self.AGENT_CHANNEL is not None:
            effective_schema = self.AGENT_CHANNEL.get_output_schema()

        effective_model = self.model
        if self.MODEL_POLICY is not None:
            policy_model = llm_service.get_model_for_policy(self.MODEL_POLICY.value)
            if policy_model:
                effective_model = policy_model


        if all_tools:
            try:
                with self._memory_tool_executor() as executor:
                    return await llm_service.get_completion_with_tools(
                        messages=messages,
                        tool_executor=executor if not return_tool_calls else None,
                        model=effective_model,
                        max_tokens=self.max_tokens,
                        temperature=self.temperature,
                        json_output=json_output,
                        response_schema=effective_schema,
                        tools=all_tools,
                        return_tool_calls=return_tool_calls,
                    )
            except services_errors.InvalidRequestError as e:
                error_message = str(e).lower()
                if "does not support tools" in error_message or "does not support" in error_message and "tool" in error_message:
                    self.logger.warning(
                        f"Model {self.model} does not support tools. "
                        f"Falling back to regular completion without memory tools. "
                        f"Error: {e}"
                    )
                    
                else:

                    raise
            except Exception as e:
                error_message = str(e).lower()
                if "does not support tools" in error_message or "does not support" in error_message and "tool" in error_message:
                    # Model doesn't support tools - fall back to regular completion
                    self.logger.warning(
                        f"Model {self.model} does not support tools. "
                        f"Falling back to regular completion without memory tools. "
                        f"Error: {e}"
                    )
                    # Fall through to regular get_completion below
                else:
                    # Different error - re-raise it
                    raise
        
        response = await llm_service.get_completion(
            messages=messages,
            model=effective_model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            json_output=json_output,
            response_schema=effective_schema,
            tools=None,
        )
        return llm_service.parse_completion_response(
            response,
            json_output=json_output
        )
    
    def format_data(self, data: typing.Any, default_message: str = "No data available.") -> str:

        if not data:
            return default_message
        return json.dumps(data, indent=2, default=str)
    
    async def _get_relevant_memories(
        self,
        query: str,
        input_data: typing.Any,
        limit: typing.Optional[int] = None,
    ) -> typing.List[dict]:

        return await self.memory_manager.search_memories(query, input_data, limit=limit)
    
    def _format_memories_for_prompt(self, memories: typing.List[dict]) -> str:

        return self.memory_manager.format_memories_for_prompt(memories)
    
    async def _store_execution_memory(
        self,
        input_data: typing.Any,
        output: typing.Any,
        user_message: typing.Optional[str] = None,
        assistant_message: typing.Optional[str] = None,
        metadata: typing.Optional[dict] = None,
    ) -> None:
        
        await self.memory_manager.store_execution_memory(
            input_data, output, user_message, assistant_message, metadata
        )
