# Fortune Texugo V4 🦡🎰

Site promocional do Risca Faca para a Calourada de Engenharia, 05/12/2026.

## Visualização
Abra `index.html` no navegador. Sem configuração do Supabase, o jogo roda **somente em demonstração**, sem registro persistente e sem prêmios.

## Funcionalidades
- Interface responsiva com caça-níquel 3×3
- Cadastro por nome e WhatsApp
- Três giros por cadastro no servidor
- Probabilidade de 2% por giro, configurável no banco
- Estoque global de cinco copos e código único de retirada
- Painel administrativo em `admin.html`
- **Premiação real desativada por padrão** no banco

## Configurar Supabase
1. Crie um projeto Supabase.
2. Execute `supabase/schema.sql` no SQL Editor.
3. Configure o segredo `PHONE_PEPPER` com um valor longo e aleatório. **Nunca publique** esse segredo nem a `SUPABASE_SERVICE_ROLE_KEY`.
4. Faça deploy das Edge Functions `register`, `spin` e `admin`. Revise configuração de autenticação/JWT das funções e restrinja CORS ao domínio final antes de publicar.
5. Em `index.html` e `admin.html`, preencha `SUPABASE_URL` e `SUPABASE_ANON_KEY` (chave pública). No site, preencha `TICKET_URL` quando houver link.
6. Crie um usuário no Supabase Auth e insira seu UUID em `fortune_admins` para conceder acesso ao painel.
7. Para publicar a prévia estática, use GitHub Pages (Settings → Pages → Deploy from a branch → main). O backend precisa ser implantado separadamente.

## Segurança e limitações
- **Não habilite `fortune_config.authorized` antes de obter a autorização e validar o regulamento.**
- Nome + WhatsApp **não verifica a posse do número**; múltiplos números, automação e cadastros falsos ainda são possíveis.
- Antes do lançamento, implemente verificação de telefone, rate limiting, CAPTCHA, proteção contra bots, política de privacidade e testes de carga.
- As grades de símbolos são decorativas: o prêmio é determinado pelo sorteio no servidor, não pelas combinações visuais.
- A configuração de 2% e os três giros precisam corresponder ao regulamento autorizado.
- Não há integração real com vendas de ingressos até fornecer uma URL.
