"""
LLM step call, behind a provider switch.

Primary target: Bedrock (Claude on Amazon Bedrock, Mantle client).
Interim: Anthropic API direct, while Bedrock model access is pending
(AWS support case 178690525700030). Swap by setting LLM_PROVIDER=bedrock
in .env.ninelives — no other code changes.
"""
import config


def step_stream(prompt: str):
    """One reasoning step. Yields text deltas as they arrive so the caller
    can persist each chunk transactionally (chunk-level durability).
    Thinking is left on by default per model guidance; temperature/top_p
    are not set (rejected with 400 on this model family)."""
    if config.LLM_PROVIDER == "anthropic":
        yield from _step_stream_anthropic(prompt)
    elif config.LLM_PROVIDER == "bedrock":
        yield from _step_stream_bedrock(prompt)
    else:
        raise ValueError(f"unknown LLM_PROVIDER: {config.LLM_PROVIDER}")


def _step_stream_anthropic(prompt: str):
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    with client.messages.stream(
        model=config.ANTHROPIC_MODEL,
        max_tokens=config.STEP_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": "low"},
    ) as stream:
        yield from stream.text_stream


def _step_stream_bedrock(prompt: str):
    import json
    import boto3

    client = boto3.client("bedrock-runtime", region_name=config.BEDROCK_REGION_PRIMARY)
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": config.STEP_MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    })
    response = client.invoke_model_with_response_stream(modelId=config.BEDROCK_MODEL_ID, body=body)
    for event in response["body"]:
        chunk = json.loads(event["chunk"]["bytes"])
        if chunk.get("type") == "content_block_delta" and chunk["delta"].get("type") == "text_delta":
            yield chunk["delta"]["text"]
