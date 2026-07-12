import re

# ALL-CAPS words that look like name words but are field labels; a name match
# must stop before them so the label (and its value's own pattern) survives —
# "MARGARET HALE DOB: 03/12/1948" redacts the name and leaves "DOB:" for the
# DOB pattern.
_LABEL_WORDS = (
    "DOB|DATE|BIRTH|SSN|MRN|ID|MEMBER|PATIENT|POLICY|ACCOUNT|CLAIM|GROUP"
    "|PLAN|PHONE|FAX|EMAIL|ADDRESS|ATTN|RE"
)
# One name word: capitalized first letter, then letters in either case, so
# both "Margaret" and "MARGARET" match (remittance/EOB text is often ALL
# CAPS). Prose stays safe because name patterns only fire after a
# Patient:/Member:/Name:/Dear label.
_NAME_WORD = rf"(?!(?i:{_LABEL_WORDS})\b)[A-Z][A-Za-z'-]+"
# 2-6 name words, with an optional single-letter middle initial ("J." / "J")
# between them.
_NAME_SEQ = rf"{_NAME_WORD}(?:[^\S\n]+(?:[A-Z]\.?[^\S\n]+)?{_NAME_WORD}){{1,5}}"


class PHIRedactor:
    """Regex-based PHI redaction. Runs BEFORE any text reaches Claude or is logged.

    Residual risk (deliberate non-goals, pinned by the guard tests in
    tests/redaction/test_redaction_corpus.py): bare 10-digit numbers are not
    treated as phone numbers because NPIs share the shape and pass through by
    design; street addresses, MRN-labeled values, and dates without a
    DOB-style label are not redacted.
    """

    PATTERNS = [
        # SSN must come before phone to avoid partial matches. Separators
        # must be all-dashes, all-spaces, or absent — a mixed 5-4 grouping is
        # a ZIP+4, not an SSN. Bare 9-digit runs redact as [SSN] even when
        # they are really claim references: over-redaction is the safe
        # direction.
        {
            "placeholder": "[SSN]",
            "pattern": "ssn",
            "regex": re.compile(r"\b(?:\d{3}-\d{2}-\d{4}|\d{3} \d{2} \d{4}|\d{9})\b"),
        },
        # Names after Patient:, Member:, Name:, Dear (labels case-insensitive)
        {
            "placeholder": "[PATIENT_NAME]",
            "pattern": "name_label",
            "regex": re.compile(
                rf"\b(?i:Patient|Member|Name)\s*:[^\S\n]*({_NAME_SEQ})",
            ),
        },
        {
            "placeholder": "[PATIENT_NAME]",
            "pattern": "dear_name",
            "regex": re.compile(
                rf"\b(?i:Dear)[^\S\n]+({_NAME_SEQ})",
            ),
        },
        # DOB patterns
        {
            "placeholder": "[DOB]",
            "pattern": "dob",
            "regex": re.compile(
                r"(?:DOB|Date of Birth|Birth Date)\s*:\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
                re.IGNORECASE,
            ),
        },
        # Member/Policy/Subscriber ID
        {
            "placeholder": "[MEMBER_ID]",
            "pattern": "member_id",
            "regex": re.compile(
                r"(?:Member ID|Policy #|ID|Subscriber ID)\s*:\s*([A-Za-z0-9][\w-]+)",
                re.IGNORECASE,
            ),
        },
        # Phone numbers: (555) 123-4567, (555)123-4567, 555-123-4567,
        # 555.123.4567, 555 123 4567. A separator is required after a bare
        # area code (and bare 10-digit runs never match) so NPIs and other
        # long references are left alone.
        {
            "placeholder": "[PHONE]",
            "pattern": "phone",
            "regex": re.compile(
                r"(?<!\d)(?:\(\d{3}\)[\s.-]?|\d{3}[\s.-])\d{3}[\s.-]\d{4}\b"
            ),
        },
        # Email addresses. Heuristic — matches the common shape; may over-match
        # strings like package coordinates or @mentions with a TLD-shaped
        # suffix. Acceptable for insurance documents; low false-positive risk.
        {
            "placeholder": "[EMAIL]",
            "pattern": "email",
            "regex": re.compile(
                r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
            ),
        },
    ]

    def redact(self, text: str) -> tuple[str, list[dict]]:
        """Redact PHI from text.

        Returns:
            (redacted_text, redaction_log) where redaction_log entries have
            placeholder, pattern, and position keys. `position` is the offset
            in the text as it stood when that entry's pattern ran — earlier
            patterns' replacements shift it relative to the original text —
            so it is suitable for ordering entries, not for indexing into
            either the input or the output.
        """
        redacted = text
        log: list[dict] = []

        for pat_info in self.PATTERNS:
            placeholder = pat_info["placeholder"]
            pattern_name = pat_info["pattern"]
            regex = pat_info["regex"]

            # For labeled patterns (name_label, dear_name, dob, member_id),
            # we replace only the captured group, keeping the label intact.
            if pattern_name in ("name_label", "dear_name", "dob", "member_id"):
                offset = 0
                for match in list(regex.finditer(redacted)):
                    if match.lastindex and match.lastindex >= 1:
                        group_start = match.start(1) + offset
                        group_end = match.end(1) + offset
                        original = match.group(1)
                        redacted = (
                            redacted[:group_start]
                            + placeholder
                            + redacted[group_end:]
                        )
                        log.append({
                            "placeholder": placeholder,
                            "pattern": pattern_name,
                            "position": match.start(1),
                        })
                        offset += len(placeholder) - len(original)
            else:
                for match in reversed(list(regex.finditer(redacted))):
                    log.append({
                        "placeholder": placeholder,
                        "pattern": pattern_name,
                        "position": match.start(),
                    })
                    redacted = (
                        redacted[: match.start()]
                        + placeholder
                        + redacted[match.end() :]
                    )

        # Sort log by position for consistent output
        log.sort(key=lambda x: x["position"])
        return redacted, log
