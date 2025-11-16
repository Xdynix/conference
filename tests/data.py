VALID_PASSWORDS = [
    "12345678",
    "3.1415926",
    "        ",
    "banana!?",
    "a secret",
    "john-doe@email.com",
    "password",
    "Pa33w0rd",
    "11111111",
    "一二三四五六七八",
    (
        "The polka-dotted giraffe tap-danced on a rainbow while "
        "juggling spaghetti-filled balloons in zero gravity."
    ),
]

INVALID_PASSWORDS = [
    "",
    "1234567",
    "admin",
    "apple",
    "一二三四五六七",
    "p1ax0",
]

USERNAME_NORMALIZATION_DATA: tuple[tuple[str, str], ...] = (
    ("User", "User"),
    ("用户", "用户"),
    ("Ω", "Ω"),
    ("ﬁ", "fi"),
    ("⑨", "9"),
)

EMAIL_NORMALIZATION_DATA: tuple[tuple[str | None, str], ...] = (
    (None, ""),
    ("email@example.com", "email@example.com"),
    ("User-One@Example.Com", "user-one@example.com"),
    ("UPPERCASE-000@EXAMPLE.COM", "uppercase-000@example.com"),
    ("user+alias@example.com", "user+alias@example.com"),
)
