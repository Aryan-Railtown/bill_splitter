from backend.bill_parser import Item, SpliterOutput
import railtracks as rt

system_message = "You are a finance management assistant that keeps track of all transactions in a notion root page 'Bill Splitter Database'." \
"You have 2 pages under this root page:" \
    "'Transaction History' : All previous transactions listed here, you are only allowed to add to this and" \
    "'Balance Sheet' : This page contains the names of all people and their overall balances (could be +ve or -ve)." \
"Whnever a new transaction is added, you need to do the following steps:" \
    "1. Add the transaction to the 'Transaction History' page" \
    "2. Read the 'Balance Sheet' page and get all the group members' balances" \
    "3. Based on who paid this bill, and how much each person spent, calculate the balances" \
    "4. Update the 'Balance Sheet'." \
    

llm_model = rt.llm.OpenAILLM("gpt-4o")

finance_agent = rt.agent_node(
    name="Finance Manager",
    system_message=system_message,
    llm=llm_model,
)

async def process(members, parsed_bill: SpliterOutput, item_assignments, paid_by):
    """
    Processes the parsed bill and returns a dictionary with the split result.
    """
    response = await rt.call(
        finance_agent, "This bill was paid by " + paid_by + ". Please process the bill and update the balance sheet accordingly." \
                        "Here is the bill: " + str(parsed_bill) + ". Here are the item assignments: " + str(item_assignments) + ""\
                        "Here are the group members: " + str(members) + "." \
                        "Please tell me the final balance for each person in the group, including the person who paid (-ve balance for spending, +ve balance for earning)."
    )
    print(response)

    return {
        "Amir": 30.4,
        "Logan": 20.2,
        "Levi": 10.1
    }