from backend.bill_parser import Item, SpliterOutput

def process(members, parsed_bill: SpliterOutput, item_assignments):
    """
    Processes the parsed bill and returns a dictionary with the split result.
    """
    # mock for now, replace with actual splitting logic
    print("Processing split for members:", members)
    print("Parsed bill:", parsed_bill)
    print("Item assignments:", item_assignments)
    return {
        "Amir": 30.4,
        "Logan": 20.2,
        "Levi": 10.1
    }