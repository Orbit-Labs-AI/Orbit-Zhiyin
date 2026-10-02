"""Validate authored family features without deriving capability from raw text."""

from .dictionary import ItemFeatures


def extract_features(record):
    return ItemFeatures.model_validate(record).model_dump(exclude_unset=True)
