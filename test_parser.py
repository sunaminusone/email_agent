from pprint import pprint

from src.services import parse_user_input, make_agent_input


if __name__ == "__main__":
    user_query = "Do you have CD19 CAR-T products? Please also share the price and datasheet."

    conversation_history = [
        {"role": "user", "content": "Hi, I am looking for CAR-T related products."}
    ]

    attachments = []

    parsed = parse_user_input(
        user_query=user_query,
        conversation_history=conversation_history,
        attachments=attachments,
    )

    print("\n===== ParsedResult =====")
    print(parsed.model_dump_json(indent=2))

    agent_input = make_agent_input(
        user_query=user_query,
        conversation_history=conversation_history,
        attachments=attachments,
    )

    print("\n===== Agent Input =====")
    pprint(agent_input)