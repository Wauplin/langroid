import json
from typing import Optional

import pytest

import langroid as lr
from langroid import ChatDocument
from langroid.language_models.mock_lm import MockLMConfig
from langroid.utils.configuration import Settings, set_global


@pytest.mark.parametrize("use_functions_api", [False, True])
@pytest.mark.parametrize("use_tools_api", [False, True])
def test_llm_done_tool(
    test_settings: Settings,
    use_functions_api: bool,
    use_tools_api: bool,
):
    """
    Test whether LLM is able to GENERATE DoneTool in required format,
    and the agent handles the tool correctly (in a task).
    """

    class MyAgent(lr.ChatAgent):
        def agent_response(
            self,
            msg: Optional[str | ChatDocument] = None,
        ) -> Optional[ChatDocument]:
            return self.create_agent_response(content=msg.content)

    set_global(test_settings)
    DoneTool = lr.agent.tools.orchestration.DoneTool
    tool_name = DoneTool.default_value("request")
    agent = MyAgent(
        lr.ChatAgentConfig(
            name="Test",
            use_functions_api=use_functions_api,
            use_tools_api=use_tools_api,
            use_tools=not use_functions_api,
            system_message=f"""
            User will give a number. Process it like this:
            - if number is even, divide by 2 and simply return the result,
                SAY NOTHING ELSE!
            - if number is odd, use the TOOL: {tool_name} to indicate you are finished,
                along with the number as is in the `content` field.
            """,
        )
    )
    # test DoneTool in llm_response
    agent.enable_message(DoneTool, use=True, handle=True)
    response = agent.llm_response("4")
    assert "2" in response.content
    response = agent.llm_response("5")
    assert len(agent.get_tool_messages(response)) == 1
    tool = agent.get_tool_messages(response)[0]
    assert isinstance(tool, DoneTool)
    assert tool.content == "5"

    # test DoneTool in task
    task = lr.Task(agent, interactive=False)

    result = task.run("12")  # 12 -> 6 -> 3 -> done
    assert "3" in result.content


def test_agent_done_tool(test_settings: Settings):
    """
    Verify generation of AgentDoneTool by agent_response method,
    and correct handling by task.
    """
    set_global(test_settings)
    AgentDoneTool = lr.agent.tools.orchestration.AgentDoneTool

    class XTool(lr.ToolMessage):
        purpose = "to show x"
        request = "x_tool"
        x: int

    class XYTool(lr.ToolMessage):
        purpose = "to show x, y"
        request = "x_y_tool"
        x: int
        y: int

        def handle(self) -> AgentDoneTool:
            return AgentDoneTool(content=str(self.x + self.y))

    class MyAgent(lr.ChatAgent):
        def agent_response(
            self,
            msg: Optional[str | ChatDocument] = None,
        ) -> Optional[ChatDocument]:
            value = int(str) if isinstance(msg, str) else int(msg.content)
            if value == 3:
                return self.create_agent_response(
                    tool_messages=[AgentDoneTool(content="3")]
                )
            else:
                return self.create_agent_response(content=str(value))

    agent = MyAgent(
        lr.ChatAgentConfig(llm=MockLMConfig(response_fn=lambda x: str(int(x) + 1)))
    )
    # use = False, since LLM is not generating any of these
    agent.enable_message(AgentDoneTool, use=False, handle=True)
    agent.enable_message(XTool, use=False, handle=True)
    agent.enable_message(XYTool, use=False, handle=True)

    # test agent generation of AgentDoneTool directly (in agent_response)
    task = lr.Task(agent, interactive=False)
    result = task.run("1")
    assert result.content == "3"

    class MyAgent(lr.ChatAgent):
        def x_tool(self, msg: XTool) -> AgentDoneTool | str:
            if msg.x == 3:
                xy = XYTool(x=3, y=5)
                return AgentDoneTool(content="xy", tools=[xy])
            else:
                return str(msg.x)

    # Test agent generation of AgentDoneTool indirectly (in tool).
    # LLM generates next number via XTool, agent handles it.
    agent = MyAgent(
        lr.ChatAgentConfig(
            name="MyAgent",
            llm=MockLMConfig(
                response_fn=lambda x: json.dumps(XTool(x=int(x) + 1).dict())
            ),
        )
    )

    agent.enable_message(AgentDoneTool, use=False, handle=True)
    agent.enable_message(XTool, use=False, handle=True)

    main_agent = lr.ChatAgent(
        lr.ChatAgentConfig(name="Main", llm=MockLMConfig(response_fn=lambda x: x))
    )
    main_agent.enable_message(XYTool, use=False, handle=True)

    main_task = lr.Task(main_agent, interactive=False)
    task = lr.Task(agent, interactive=False)
    main_task.add_sub_task(task)
    result = main_task.run("1")
    # when MyAgent sees x=3, it generates AgentDoneTool, with tools = [XYTool(3, 5)],
    # which is in turn handled by the MainAgent, to produce
    # AgentDoneTool(content=8)
    assert result.content == "8"


@pytest.mark.parametrize("use_functions_api", [True, False])
@pytest.mark.parametrize("use_tools_api", [True, False])
def test_orch_tools(
    test_settings: Settings,
    use_functions_api: bool,
    use_tools_api: bool,
):
    """
    Test multiple orchestration tools in a 3-agent setting:
    PassTool use by agent,
    ForwardTool use by agent, LLM,
    DoneTool use by agent, LLM
    """

    set_global(test_settings)
    # these orch tools are enabled for HANDLING by default in any ChatAgent,
    # via the ChatAgentConfig.enable_orchestration_tool_handling = True flag.
    # But if we need to enable the LLM to generate these, we need to explicitly
    # enable these, as we see for some of the tools below.

    DoneTool = lr.agent.tools.orchestration.DoneTool
    ForwardTool = lr.agent.tools.orchestration.ForwardTool
    PassTool = lr.agent.tools.orchestration.PassTool

    done_tool_name = DoneTool.default_value("request")
    forward_tool_name = ForwardTool.default_value("request")

    class ReduceTool(lr.ToolMessage):
        purpose = "to remove last zero from a number ending in 0"
        request = "reduce_tool"
        number: int

        def handle(self) -> int:
            return int(self.number / 10)

    reduce_tool_name = ReduceTool.default_value("request")

    class TestAgent(lr.ChatAgent):
        def reduce_tool(self, msg: ReduceTool) -> PassTool:
            # validate and pass on
            return PassTool()

    agent = TestAgent(
        lr.ChatAgentConfig(
            name="Test",
            use_functions_api=use_functions_api,
            use_tools_api=use_tools_api,
            use_tools=not use_functions_api,
            system_message=f"""
            Whenever you receive a number, process it like this:
            - if the number ENDS in 0, use the TOOL: {reduce_tool_name} 
                to reduce it, and the Reducer will return the result to you,
                and you must CONTINUE processing it using these same rules.
            - else if number is EVEN, FORWARD it to the "EvenHandler" agent,
                    using the `{forward_tool_name}` TOOL; the EvenHandler will 
                    return the result of this TOOL, and you CONTINUE processing
                    it using these same rules.
            - else if number is ODD, use the {done_tool_name} to indicate you are 
            finished,
                along with the number as is in the `content` field.
            """,
        )
    )
    # test DoneTool in llm_response
    agent.enable_message(DoneTool, use=True, handle=True)
    agent.enable_message(ForwardTool, use=True, handle=True)
    agent.enable_message(ReduceTool, use=True, handle=True)
    task = lr.Task(agent, interactive=False)

    even_agent = lr.ChatAgent(
        lr.ChatAgentConfig(
            name="EvenHandler",
            llm=MockLMConfig(response_fn=lambda x: str(int(round(float(x))) / 2)),
        )
    )
    even_task = lr.Task(even_agent, single_round=True, interactive=False)

    # distracting agent that should not handle any msgs
    class TriplerAgent(lr.ChatAgent):
        def reduce_tool(self, msg: ReduceTool) -> None:
            # validate and forward to Reducer
            return ForwardTool(agent="Reducer")

    triple_agent = TriplerAgent(
        lr.ChatAgentConfig(
            name="Tripler",
            llm=MockLMConfig(response_fn=lambda x: str(int(round(float(x))) * 3)),
        )
    )
    triple_agent.enable_message(ReduceTool, use=False, handle=True)
    triple_task = lr.Task(triple_agent, single_round=True, interactive=False)

    class ReducerAgent(lr.ChatAgent):
        def reduce_tool(self, msg: ReduceTool) -> DoneTool:
            return DoneTool(content=str(msg.handle()))

    reducer_agent = ReducerAgent(lr.ChatAgentConfig(name="Reducer"))
    reducer_agent.enable_message(ReduceTool, use=False, handle=True)

    reducer_task = lr.Task(reducer_agent, single_round=False, interactive=False)

    task.add_sub_task([triple_task, reducer_task, even_task])

    result = task.run("1200", turns=60)  # 1200 -> 120 -> 12 -> 6 -> 3 -> done
    assert "3" in result.content


@pytest.mark.parametrize("use_functions_api", [True, False])
@pytest.mark.parametrize("use_tools_api", [True, False])
def test_send_tools(
    test_settings: Settings,
    use_functions_api: bool,
    use_tools_api: bool,
):

    set_global(test_settings)

    SendTool = lr.agent.tools.orchestration.SendTool
    AgentSendTool = lr.agent.tools.orchestration.AgentSendTool
    DoneTool = lr.agent.tools.orchestration.DoneTool
    AgentDoneTool = lr.agent.tools.orchestration.AgentDoneTool

    send_tool_name = SendTool.default_value("request")
    done_tool_name = DoneTool.default_value("request")

    class ThreeTool(lr.ToolMessage):
        purpose = "to handle a <number> that is a MULTIPLE of 3"
        request = "three_tool"
        number: int

    class SubThreeTool(lr.ToolMessage):
        purpose = "to subtract 3 from a number, and if result is zero, add 1 again"
        request = "sub_three_tool"
        number: int

        def handle(self) -> int:
            ans = self.number - 3
            final = ans if ans != 0 else 1
            return AgentDoneTool(content=str(final))

    three_tool_name = ThreeTool.default_value("request")

    class ProcessorAgent(lr.ChatAgent):

        def three_tool(self, msg: ThreeTool) -> AgentSendTool:
            # validate and pass on
            return AgentSendTool(
                to="ThreeHandler",
                tools=[SubThreeTool(number=msg.number)],
            )

    processor = ProcessorAgent(
        lr.ChatAgentConfig(
            name="Processor",
            use_functions_api=use_functions_api,
            use_tools_api=use_tools_api,
            use_tools=not use_functions_api,
            system_message=f"""
            Your task is to HANDLE an incoming number OR a tool-result, 
            EXACTLY in the FALLBACK order below.
            
            - if number or result is > 0 AND a multiple of 10, send it to "ZeroHandler" 
                Agent, using the TOOL: `{send_tool_name}`.
            - ELSE if number or result is a multiple of 5, send it to "FiveHandler" 
                Agent, 
                using the TOOL: `{send_tool_name}`.
            - ELSE if the number or result is a multiple of 3, use the TOOL: 
              `{three_tool_name}` to process it,
            - OTHERWISE, use the TOOL: `{done_tool_name}` to indicate you are finished,
                with `content` field set to the received number.
            """,
        )
    )
    processor_task = lr.Task(processor, interactive=False)
    processor.enable_message(SendTool, use=True, handle=True)
    processor.enable_message(ThreeTool, use=True, handle=True)

    five_agent = lr.ChatAgent(
        lr.ChatAgentConfig(
            name="FiveHandler",
            llm=MockLMConfig(
                response_fn=lambda x: (
                    f"""
                    result is {int(x)//5}, apply the number-handling rules to 
                    decide what to do next
                    """
                ),
            ),
        )
    )
    five_task = lr.Task(five_agent, single_round=True, interactive=False)

    zero_agent = lr.ChatAgent(
        lr.ChatAgentConfig(
            name="ZeroHandler",
            llm=MockLMConfig(
                response_fn=lambda x: (
                    f"""
                 result is {int(x)//10}, apply the number-handling rules to
                 decide what to do next
                 """
                ),
            ),
        )
    )
    zero_task = lr.Task(zero_agent, single_round=True, interactive=False)

    three_agent = lr.ChatAgent(
        lr.ChatAgentConfig(
            name="ThreeHandler",
            llm=None,
        )
    )
    three_agent.enable_message(SubThreeTool, use=False, handle=True)
    three_task = lr.Task(three_agent, interactive=False)

    processor_task.add_sub_task([five_task, zero_task, three_task])

    result = processor_task.run("180", turns=20)
    # 180 -> 18 -> 15 -> 3 -> 1 -> done
    assert result.content == "1"

    result = processor_task.run("250", turns=20)  # 250 -> 25 -> 5 -> 1 -> done
    assert result.content == "1"
