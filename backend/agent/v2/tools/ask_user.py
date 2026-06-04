"""Ask the user a clarifying question."""

from ..tools_registry import tool, ToolParameter


@tool(
    name="ask_user",
    description=(
        "Ask the user a structured multiple-choice question. "
        "Always provide 2-4 clear options with short labels and descriptions. "
        "The user can also type a free-form answer instead of picking an option. "
        "If you need more than one clarification, strongly prefer a single grouped questionnaire via `questions` instead of multiple sequential ask_user calls. "
        "Only ask questions one-by-one when later questions truly depend on the earlier answer."
    ),
    parameters=[
        ToolParameter(
            name="question",
            type="string",
            description="The question to ask the user. Should be clear and specific.",
        ),
        ToolParameter(
            name="options",
            type="array",
            description="2-4 options for the user to choose from.",
            required=False,
            items={
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "Short option name (1-5 words)"},
                    "description": {"type": "string", "description": "Brief explanation of this option"},
                },
                "required": ["label", "description"],
            },
        ),
        ToolParameter(
            name="question_index",
            type="integer",
            description="Optional 1-based index of this question within a planned multi-question clarification sequence.",
            required=False,
        ),
        ToolParameter(
            name="question_total",
            type="integer",
            description="Optional total number of questions in the planned clarification sequence.",
            required=False,
        ),
        ToolParameter(
            name="question_plan",
            type="array",
            description="Optional short labels for the full question sequence in order, so the UI can show what is coming next.",
            required=False,
            items={
                "type": "string",
                "description": "Short label for one clarification question in the sequence",
            },
        ),
        ToolParameter(
            name="questions",
            type="array",
            description="Optional grouped questionnaire. Use this instead of separate ask_user calls when you need multiple short clarifications at once.",
            required=False,
            items={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Optional short tab title (1-2 words preferred)"},
                    "question": {"type": "string", "description": "The question to ask"},
                    "options": {
                        "type": "array",
                        "description": "2-4 options for this question",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string", "description": "Short option name (1-5 words)"},
                                "description": {"type": "string", "description": "Brief explanation of this option"},
                            },
                            "required": ["label", "description"],
                        },
                    },
                },
                "required": ["question", "options"],
            },
        ),
    ],
    scope="both",
)
async def ask_user(question: str, **kwargs) -> str:
    return question
