"""Initializes the local development environment."""

import shutil
import subprocess
from pathlib import Path
from textwrap import dedent

from decouple import config as auto_config
from loguru import logger

LOG_DEPTH = 1
DATA_DIR = Path(__file__).resolve().parent.parent / "var"

logger = logger.opt(colors=True, depth=LOG_DEPTH)

dev_hosts: list[str] = [
    "localhost",
    "127.0.0.1",
    "::1",
]


@logger.catch
def main() -> None:
    ensure_env_var_file()
    ensure_dev_server_cert()
    success_message()


def ensure_env_var_file() -> None:
    logger.info("🌏 Ensuring Environment Variable")
    dot_env_file = Path(".env")
    for file in auto_config.SUPPORTED:
        if Path(file).exists():
            logger.warning(
                "    👉 <i>{file}</> already exists. "
                "Skip creating <i>{target}</> file.",
                file=file,
                target=dot_env_file,
            )
            return

    from django.core.management.utils import get_random_secret_key

    logger.info("    🔑 Secret key generated and set up as 🐛 debugging environment.")
    secret_key = get_random_secret_key()
    allowed_hosts = ",".join(dev_hosts)

    dot_env_content = """
    SECRET_KEY='{secret_key}'

    DEBUG=True

    ALLOWED_HOSTS={allowed_hosts}

    EMAIL_BACKEND=django.core.mail.backends.filebased.EmailBackend

    SITE_NAME=Django-Dev
    """
    dot_env_content = dot_env_content.format(
        secret_key=secret_key,
        allowed_hosts=allowed_hosts,
    )
    dot_env_content = dedent(dot_env_content).strip()
    dot_env_file.write_text(dot_env_content + "\n")
    logger.info(
        "    ✅ <green><i>{dot_env_file}</> created.</>", dot_env_file=dot_env_file
    )


def ensure_dev_server_cert() -> None:
    logger.info("🔐 Ensuring Development Server Certificate")
    if not shutil.which("mkcert"):
        logger.warning("    🤔 <i>mkcert</> not found on your <i>PATH</>. ")
        logger.warning("    👍 It is highly recommended that you install it.")
        logger.warning("    🔗 https://github.com/FiloSottile/mkcert")
        return

    logger.info("    🌲 Installing local CA. You may be prompted for permission.")
    subprocess.run(["mkcert", "-install"], check=True)
    logger.info("    ✒️ Creating certificate.")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "mkcert",
            "--cert-file",
            f"{DATA_DIR / 'dev-server.crt'}",
            "--key-file",
            f"{DATA_DIR / 'dev-server.key'}",
            *dev_hosts,
        ],
        check=True,
    )
    logger.info("    ✅ <green>Done!</>")


def success_message() -> None:
    logger.info("🎉 Your local environment is now ready!")
    for hint in (
        "🔹 Execute <u><i>just manage migrate</></> to initialize database.",
        "🔹 Execute <u><i>just manage createsuperuser</></> to create superuser.",
        "🔹 Execute <u><i>just dev</></> to start the development server.",
        "🔹 The development server will run on <u><i>https://localhost:8000</></>",
    ):
        logger.info("    {}", hint)


if __name__ == "__main__":
    main()
