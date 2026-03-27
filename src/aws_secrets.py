import boto3
import json
import logging

logger = logging.getLogger(__name__)

SECRET_NAME = "gaston/gmail/oauth-credentials"
REGION = "eu-west-1"


def get_gmail_credentials() -> dict:
    """
    Lee las credenciales OAuth2 de Gmail desde AWS Secrets Manager.
    Retorna dict con: client_id, client_secret, refresh_token
    """
    client = boto3.client("secretsmanager", region_name=REGION)

    try:
        response = client.get_secret_value(SecretId=SECRET_NAME)
        secret = json.loads(response["SecretString"])

        for key in ["client_id", "client_secret", "refresh_token"]:
            if key not in secret:
                raise ValueError(f"Falta '{key}' en el secreto {SECRET_NAME}")

        return secret

    except Exception as e:
        logger.error(f"Error leyendo secreto {SECRET_NAME}: {e}")
        raise
