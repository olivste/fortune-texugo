"""Account validation, Argon2id and encrypted CPF."""
import hashlib
import hmac
import os
import re
from argon2 import PasswordHasher, Type
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

PASSWORDS = PasswordHasher(type=Type.ID)
DUMMY_HASH = PASSWORDS.hash('not-a-user-password')


def cpf(value):
    if not re.fullmatch(r'[0-9.\-\s]+', value):
        raise HTTPException(422, 'CPF inválido')
    value = re.sub(r'\D', '', value)
    if len(value) != 11 or len(set(value)) == 1:
        raise HTTPException(422, 'CPF inválido')
    for size in (9, 10):
        digit = (sum(int(value[i]) * (size + 1 - i) for i in range(size)) * 10) % 11
        if int(value[size]) != (0 if digit == 10 else digit):
            raise HTTPException(422, 'CPF inválido')
    return value


def instagram(value):
    value = value.strip().lstrip('@').lower()
    if not re.fullmatch(r'[a-z0-9_](?:[a-z0-9_.]{0,28}[a-z0-9_])?', value) or '..' in value:
        raise HTTPException(422, 'Instagram inválido: use de 1 a 30 letras, números, pontos ou sublinhados')
    return value


def cpf_lookup(value):
    key = os.environ.get('CPF_HMAC_KEY', '')
    if len(key) < 32:
        raise HTTPException(503, 'Cadastro indisponível: proteção de dados não configurada')
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def encrypt_cpf(value):
    try:
        return Fernet(os.environ['CPF_ENCRYPTION_KEY'].encode()).encrypt(value.encode()).decode()
    except (KeyError, ValueError):
        raise HTTPException(503, 'Cadastro indisponível: proteção de dados não configurada')



def decrypt_cpf(value):
    try:
        return Fernet(os.environ['CPF_ENCRYPTION_KEY'].encode()).decrypt(value.encode()).decode()
    except (KeyError, ValueError, InvalidToken):
        raise HTTPException(503, 'Não foi possível gerar o código de retirada. Tente novamente mais tarde.')


def phone(value):
    if not re.fullmatch(r'[0-9+().\-\s]+', value):
        raise HTTPException(422, 'Informe telefone com DDD válido')
    digits = re.sub(r'\D', '', value)
    if len(digits) in (12, 13) and digits.startswith('55'):
        digits = digits[2:]
    if not re.fullmatch(r'[1-9]{2}(?:[2-5][0-9]{7}|9[0-9]{8})', digits):
        raise HTTPException(422, 'Informe telefone com DDD válido')
    return digits


def phone_lookup(value):
    key = os.environ.get('PHONE_PEPPER', '')
    if len(key) < 32:
        raise HTTPException(503, 'Cadastro indisponível: proteção de dados não configurada')
    return hmac.new(key.encode(), ('account-phone:' + value).encode(), hashlib.sha256).hexdigest()


# Same existing Fernet key, separate columns and domain-separated lookup for phones.
encrypt_phone = encrypt_cpf
decrypt_phone = decrypt_cpf
