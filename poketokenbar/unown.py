"""Unown letters are individual attributes, independent of shiny color."""

SPECIES_ID = 201
FORMS = tuple("abcdefghijklmnopqrstuvwxyz") + ("exclamation", "question")


def resolved(species_id: int, form: str | None = None) -> str | None:
    if species_id != SPECIES_ID:
        return None
    return form if form in FORMS else "a"


def symbol(form: str) -> str:
    return {"exclamation": "!", "question": "?"}.get(form, form.upper())


def display_name(name: str, species_id: int, form: str | None = None) -> str:
    form = resolved(species_id, form)
    return f"{name} [{symbol(form)}]" if form is not None else name


def roll_form(roll: int, collected: set[str]) -> str:
    """Uncollected letters weigh two, owned letters one; no guaranteed novelty."""
    weights = [1 if form in collected else 2 for form in FORMS]
    remaining = roll % sum(weights)
    for form, weight in zip(FORMS, weights):
        if remaining < weight:
            return form
        remaining -= weight
    return FORMS[-1]
