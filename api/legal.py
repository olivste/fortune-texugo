"""Editable legal drafts; never invent a controller, legal basis or contact."""
import html
import os
from pathlib import Path
from fastapi.responses import HTMLResponse
ROOT = Path(__file__).resolve().parent.parent


def page(name):
    body = (ROOT/'legal'/f'{name}.html').read_text()
    for key in ('TERMS_VERSION','PRIVACY_VERSION','DATA_CONTROLLER','PRIVACY_CONTACT','PRIVACY_LEGAL_BASIS'):
        fallback = '2026-11-04' if key.endswith('VERSION') else 'PENDENTE DE CONFIGURAÇÃO PELO RESPONSÁVEL'
        body = body.replace('{{'+key+'}}',html.escape(os.environ.get(key) or fallback))
    return HTMLResponse('<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                        '<title>'+('Termos de Uso' if name=='termos' else 'Privacidade')+' — Fortune Texugo</title>'
                        '<link rel="stylesheet" href="/assets/legal.css"><main><a href="/">← Voltar ao jogo</a>'+body+'</main></html>')
