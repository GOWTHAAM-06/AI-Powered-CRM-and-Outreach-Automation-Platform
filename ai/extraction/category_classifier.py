
"""
Lead Category Classifier.
Classifies opportunities into: 'job', 'startup', 'internship', 'hackathon', 'college_tpo'.
"""

import re
from typing import Dict, Any, Tuple


def classify_category(record: Dict[str, Any]) -> Tuple[str, float]:
    """
    Classifies an opportunity based on title, description, and source context.
    Returns: (category, confidence)
    """
    title = str(record.get("title", "")).lower()
    description = str(record.get("description", "")).lower()
    combined = f"{title} {description}"

    if any(k in combined for k in ["hackathon", "sprint", "prize pool", "codefest", "ideathon"]):
        return "hackathon", 0.95

    if any(k in combined for k in ["placement cell", "tpo", "on-campus", "campus drive", "placement officer"]):
        return "college_tpo", 0.95

    # Match internship keywords as complete words, including plural forms.
    if any(
        re.search(pattern, combined)
        for pattern in [
            r"\binterns?\b",
            r"\binternships?\b",
            r"\bstipends?\b",
        ]
    ):
        return "internship", 0.95

    if any(k in combined for k in ["founding engineer", "early stage", "yc", "seed funded", "stealth startup"]):
        return "startup", 0.85

    return "job", 0.90
