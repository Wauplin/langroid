from llmagent.language_models.base import LanguageModel


# Define a class for OpenAI GPT-3 that extends the base class
class OpenAIGPT3(LanguageModel):
    def __init__(self, api_key: str):
        self.api_key = api_key

    def generate(self, prompt: str, max_tokens: int) -> str:
        import openai

        openai.api_key = self.api_key
        response = openai.Completion.create(
            engine="text-davinci-003",
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=0,
        )
        return response.choices[0].text.strip()
