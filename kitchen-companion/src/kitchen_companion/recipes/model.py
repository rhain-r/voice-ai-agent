from fractions import Fraction
from typing import Annotated

from pydantic import BaseModel, PlainSerializer, PlainValidator, WithJsonSchema


def to_fraction(value: object) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, bool):
        raise ValueError("not a quantity")
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        return Fraction(str(value))
    if isinstance(value, str):
        return Fraction(value.strip())
    raise ValueError(f"not a quantity: {value!r}")


Qty = Annotated[
    Fraction,
    PlainValidator(to_fraction),
    PlainSerializer(lambda f: f"{f.numerator}/{f.denominator}", return_type=str),
    WithJsonSchema({"type": "string", "examples": ["3/2"]}),
]


class Ingredient(BaseModel):
    qty: Qty | None
    qty_max: Qty | None = None
    unit: str | None
    name: str
    note: str | None = None
    raw: str


class Step(BaseModel):
    index: int
    text: str
    timer_minutes: int | None = None


class Recipe(BaseModel):
    id: str
    title: str
    servings: int = 4
    total_time_min: int | None = None
    source_url: str | None = None
    ingredients: list[Ingredient]
    steps: list[Step]
