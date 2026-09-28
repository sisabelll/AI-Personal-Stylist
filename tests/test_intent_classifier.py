"""
"Give me a different outfit" returned the same outfit.

classify_intent's system prompt described three intents — ask_question,
modify_outfit, finalize_outfit — while UserActionType had five. The two it
never mentioned, new_outfit and reset_session, were still valid values of the
response model, so the model emitted them inconsistently: "show me another
outfit" happened to land on new_outfit, but "give me a different outfit" fell
back to modify_outfit. That routes to _refine_look(), which runs in edit mode
where the stylist is instructed to keep items "EXACTLY (copy verbatim)" — so
asking for a new outfit told the system to preserve the old one.

The structural test below is the one that matters: it fails the moment someone
adds an enum value without teaching the classifier about it.
"""
import inspect
import os

import pytest

from agents.interpreter import ContextInterpreter
from core.schemas import UserActionType

PROMPT_SRC = inspect.getsource(ContextInterpreter.classify_intent)


class TestEveryIntentIsDocumented:
    @pytest.mark.parametrize("action", list(UserActionType), ids=lambda a: a.value)
    def test_prompt_describes_this_action(self, action):
        assert action.value in PROMPT_SRC, (
            f"{action.value} is a valid response value but the classifier prompt "
            "never describes it, so the model has to guess when to use it"
        )

    def test_the_two_that_were_missing_are_present(self):
        assert "new_outfit" in PROMPT_SRC
        assert "reset_session" in PROMPT_SRC

    def test_prompt_distinguishes_whole_outfit_from_one_garment(self):
        """The actual discriminator — without it the model splits the difference."""
        lowered = PROMPT_SRC.lower()
        assert "different outfit" in lowered
        assert "change the shoes" in lowered, "needs a contrasting modify_outfit example"


LIVE = os.environ.get("OPENAI_API_KEY") and os.environ.get("RUN_LIVE_INTENT_TESTS")


@pytest.mark.skipif(not LIVE, reason="set RUN_LIVE_INTENT_TESTS=1 to call the API")
class TestLiveClassification:
    @pytest.fixture(scope="class")
    def interpreter(self):
        from services.client import OpenAIClient
        return ContextInterpreter(OpenAIClient())

    @pytest.mark.parametrize("text", [
        "give me a different outfit",
        "I want a completely different look",
        "show me another outfit",
        "can I see a different one",
        "something else please",
    ])
    def test_whole_outfit_requests_regenerate(self, interpreter, text):
        assert interpreter.classify_intent(text) is UserActionType.NEW_OUTFIT

    @pytest.mark.parametrize("text", [
        "change the shoes",
        "swap the blazer for a jacket",
        "make it more casual",
        "tweed is too much",
    ])
    def test_partial_changes_still_edit(self, interpreter, text):
        assert interpreter.classify_intent(text) is UserActionType.MODIFY_OUTFIT

    def test_questions_and_acceptance_unaffected(self, interpreter):
        assert interpreter.classify_intent("is tweed too much?") is UserActionType.ASK_QUESTION
        assert interpreter.classify_intent("perfect, thanks") is UserActionType.FINALIZE_OUTFIT
