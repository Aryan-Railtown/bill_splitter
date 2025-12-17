import railtracks as rt
import base64
from pydantic import BaseModel, Field

system_message = (
    "You are an agent that can read bills and return a list of items with their costs."
    "Incase of multiple elements with the same name, add numbers to the end of the name to make it unique."
)

model = rt.llm.OpenAILLM("gpt-4o")


class Item(BaseModel):
    item: str = Field(description="The name of the item")
    cost: float = Field(description="The cost of the item")


class SpliterOutput(BaseModel):
    items: list[Item] = Field(description="The list of object `Item`")


spliter_agent = rt.agent_node(
    output_schema=SpliterOutput,
    name="Parsing agent",
    system_message=system_message,
    llm=model,
)


async def process(uploaded_file):
    """
    Processes the uploaded file and returns a dictionary with the parsed bill.
    """
    # Convert uploaded_file to base64
    file_bytes = uploaded_file.read()
    base64_image_str = "data:image/jpg;base64,"
    base64_image_str += base64.b64encode(file_bytes).decode("utf-8")
    try:
        resp = await rt.call(
            spliter_agent,
            user_input=rt.llm.UserMessage(
                "Read this bill and tell me the items and their costs",
                attachment=base64_image_str,
            ),
        )
        struct_resp = resp.structured  # type: ignore
        assert isinstance(
            struct_resp, SpliterOutput
        ), "Response is not of type SpliterOutput"
        return struct_resp
    except AssertionError as e:
        return SpliterOutput(
            items=[
                Item(item="item1", cost=30.4),
                Item(item="item2", cost=20.2),
                Item(item="item3", cost=10.1),
                Item(item="item4", cost=5.3),
            ]
        )


if __name__ == "__main__":
    import streamlit as st
    import asyncio
    uploaded_file = st.file_uploader("Upload bill image", type=["jpg", "jpeg", "png"])
    if uploaded_file:
        st.success("Bill image uploaded! LLM is processing...")
        parsed_bill = asyncio.run(process(uploaded_file))
        print(parsed_bill)