import httpx

# Maximum length of response text to include in error logs
MAX_RESPONSE_PREVIEW_LENGTH = 500


def format_response(
    response: httpx.Response, max_preview_length: int = MAX_RESPONSE_PREVIEW_LENGTH
) -> str:
    """
    Format HTTP response details for logging.

    Args:
        response: The HTTP response to format.
        max_preview_length: Maximum length of response text to include.

    Returns:
        Formatted string with response details.
    """
    return (
        f"HTTP response details:\n  Status: {response.status_code}"
        "\n  Headers:"
        + "".join(f"\n    {key}: {value}" for key, value in response.headers.items())
        + (
            f"\n  Response:\n    {response.text[:max_preview_length]}"
            + ("..." if len(response.text) > max_preview_length else "")
            if response.text
            else ""
        )
    )
