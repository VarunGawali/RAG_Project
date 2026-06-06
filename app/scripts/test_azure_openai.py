from openai import AzureOpenAI
from app import config


def main():
    print("Testing Azure OpenAI chat connection...")
    print("Endpoint:", config.AZURE_OPENAI_ENDPOINT)
    print("API version:", config.AZURE_OPENAI_API_VERSION)
    print("Chat deployment:", config.AZURE_OPENAI_CHAT_DEPLOYMENT)

    client = AzureOpenAI(
        azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
        api_key=config.AZURE_OPENAI_API_KEY,
        api_version=config.AZURE_OPENAI_API_VERSION,
    )

    response = client.chat.completions.create(
        model=config.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[
            {
                "role": "user",
                "content": "Reply exactly with: Azure OpenAI OK"
            }
        ],
        temperature=0,
        max_tokens=20,
    )

    print(response.choices[0].message.content)


if __name__ == "__main__":
    main()