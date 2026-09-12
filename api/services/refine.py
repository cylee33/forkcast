"""(profile, instruction) -> (patched profile, field diff). Structured Gemini output,
cached and rate-limit-retried; degrades to the unchanged profile with an empty diff
when the LLM is unavailable or never validates -- never crashes, never guesses."""
from api.models import ConceptProfile
from api.services import llm_client
from api.services.llm_schema import LLMConceptProfile, from_concept_profile, to_concept_profile

PROMPT_TEMPLATE = """You are Forkcast's restaurant-concept editor. Apply the instruction below to
the current ConceptProfile and return the FULL updated ConceptProfile JSON (every field, not just
the changed ones). Change only what the instruction implies; leave every other field exactly as
given. Keep proposed_weights over exactly the keys D, C, T, A, S_spend, K, Sup.

Current profile:
{profile_json}

Instruction: {instruction}
"""


def _diff(before: ConceptProfile, after: ConceptProfile) -> dict:
    b, a = before.model_dump(), after.model_dump()
    return {k: {"from": b[k], "to": a[k]} for k in b if b[k] != a[k]}


def refine(profile: ConceptProfile, instruction: str) -> tuple[ConceptProfile, dict]:
    profile_json = from_concept_profile(profile).model_dump_json()
    prompt = PROMPT_TEMPLATE.format(profile_json=profile_json, instruction=instruction)
    cache_input = f"{profile_json}|{instruction}"
    result = llm_client.generate_structured("concept_refine", cache_input=cache_input, prompt=prompt,
                                             schema=LLMConceptProfile)
    if result is None:
        return profile, {}
    patched = to_concept_profile(result)
    return patched, _diff(profile, patched)
